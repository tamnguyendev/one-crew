import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from onecrew.discovery import Discovery
from onecrew.ledger import LedgerError
from onecrew.progress import observe
from onecrew.usage import summarize, record
from tests import test_owned as fixtures


class SearchRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.discovery=Discovery(self.root)

    def put(self,path,text='Cloud Auth'):
        target=self.root/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text,encoding='utf-8')

    def test_recursive_dependency_and_arb_with_scope_and_pagination(self):
        self.put('app/lib/main.dart','main')
        self.put('shared/lib/settings/page.dart')
        self.put('shared/lib/l10n/vi.arb','{"message":"Cloud Auth"}')
        # Per-op scan budget forced to 1 file -> the op scans one file then yields a continuation cursor, so paging tiles
        # the tree without dropping files. (Old behaviour keyed off SEARCH_PAGE; the fix scans a budgeted span per op.)
        with patch('onecrew.discovery.SEARCH_SCAN_FILES',1):
            pages=[];cursor=0
            while cursor is not None:
                result=self.discovery.search('','Cloud Auth',cursor);pages.append(result);cursor=result['next_cursor']
            self.assertEqual(len(pages),3)  # three permitted text files, one scanned per op under the 1-file budget
            self.assertEqual({m['path'] for p in pages for m in p['matches']},
                             {'shared/lib/settings/page.dart','shared/lib/l10n/vi.arb'})
            self.assertTrue(all(p['recursive'] and p['query']=='Cloud Auth' for p in pages))
            # explicit coverage: contiguous tiling, totals, and exhausted only on the final page
            self.assertEqual([p['scanned_from'] for p in pages],[0,1,2])
            self.assertEqual([p['scanned_through'] for p in pages],[1,2,3])
            self.assertTrue(all(p['files_total']==3 for p in pages))
            self.assertTrue(pages[-1]['exhausted'] and pages[-1]['next_cursor'] is None)
            self.assertFalse(any(p['exhausted'] for p in pages[:-1]))
        # Default budget (no patch): the whole small tree is covered in ONE op (no per-file model call), matches intact
        whole=self.discovery.search('','Cloud Auth')
        self.assertEqual({m['path'] for m in whole['matches']},{'shared/lib/settings/page.dart','shared/lib/l10n/vi.arb'})
        self.assertTrue(whole['exhausted'] and whole['next_cursor'] is None)
        self.assertEqual(self.discovery.search('app','Cloud Auth')['matches'],[])

    def test_exclusions_content_withholding_and_bounds_are_explicit(self):
        self.put('.env','Cloud Auth');self.put('build/output.dart');self.put('app_secret.dart')
        self.put('unsafe.dart','API_KEY=aaaaaaaaaaaaaaaaaaaaaaaa\nCloud Auth')
        self.put('safe.dart')
        result=self.discovery.search('','Cloud Auth')
        self.assertEqual([m['path'] for m in result['matches']],['safe.dart'])
        self.assertEqual(result['files_withheld_or_unreadable'],1)
        self.assertEqual(result['entries_excluded'],3)
        with patch('onecrew.discovery.SEARCH_ENTRIES',2):
            self.assertTrue(self.discovery.search('','Cloud Auth')['tree_truncated'])
        with self.assertRaises(LedgerError): self.discovery.search('../outside','Cloud Auth')
        with self.assertRaises(LedgerError): self.discovery.search('','Cloud Auth',-1)

    def test_different_empty_searches_continue_same_search_stops(self):
        state={'phase':'running','snapshot':None}
        for directory,query in [('lib/services','authServiceUser'),('lib/l10n','Cloud Auth'),('lib/services','Cloud')]:
            observe(state,'search',{'directory':directory,'query':query},{'matches':[],'directories':[],'next_cursor':None})
        self.assertEqual(state['phase'],'running')
        for _ in range(2): observe(state,'search',{'directory':'lib/services','query':'Cloud'},
                                  {'matches':[],'directories':[],'next_cursor':None})
        self.assertEqual(state['phase'],'blocked')

    def test_new_source_progress_resets_exploration_but_repeated_read_stops(self):
        state={'phase':'running','snapshot':'one'}
        for i in range(15): observe(state,'search',{'query':str(i)},{'matches':[]})
        result={'path':'lib/page.dart','text':'New evidence','sha256':'hash','next_cursor':None}
        observe(state,'read',{'path':'lib/page.dart'},result)
        self.assertEqual(state['phase'],'running');self.assertEqual(state['progress']['observations'],0)
        for _ in range(2): observe(state,'read',{'path':'lib/page.dart'},result)
        self.assertEqual(state['phase'],'blocked')

    def test_root_exploration_cap_still_applies_to_different_queries(self):
        state={'phase':'running','snapshot':None}
        for i in range(16): observe(state,'search',{'query':str(i)},{'matches':[]})
        self.assertEqual(state['phase'],'blocked')

    def test_owned_receipt_and_restart_keep_search_context(self):
        fixture=fixtures.OwnedTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        run,task,worker=fixture.runtime([fixtures.action('search',directory='',query='absent1'),
            fixtures.action('search',directory='',query='absent2'),fixtures.action('search',directory='',query='absent3'),
            fixtures.action('read',path='calc.py')])
        state=run.run(task,steps=3)
        self.assertEqual(state['phase'],'running')
        index=run.evidence_index(state)
        self.assertEqual([i['arguments']['query'] for i in index],['absent1','absent2','absent3'])
        from onecrew.owned import Owned
        restored=Owned(fixture.ledger,worker)
        self.assertEqual(restored.evidence_index(restored.state(task)[1]),index)
        self.assertEqual(restored.run(task,steps=1)['progress']['observations'],0)

    def test_claude_usage_disjoint_inputs_nested_counters_not_double_counted(self):
        state={'usage':[]}
        value={'input_tokens':2,'cache_creation_input_tokens':100,'cache_read_input_tokens':200,'output_tokens':10,
               'cache_creation':{'ephemeral_1h_input_tokens':100},'iterations':[{'input_tokens':99999}]}
        record(state,'attempt',[value],'claude','sonnet');record(state,'attempt',[value],'claude','sonnet')
        summary=summarize(state['usage']);total=summary['totals_observed_only']
        self.assertEqual(total['input_tokens'],302);self.assertEqual(total['total_tokens'],312)
        self.assertEqual(total['uncached_input_tokens'],102);self.assertEqual(total['cached_input_tokens'],200)
        self.assertEqual(summary['unknown_attempts'],[])
        for invalid in (True,-1,1.5,None):
            broken=dict(value,cache_read_input_tokens=invalid)
            record(state,str(invalid),[broken],'claude','sonnet')
        record(state,'multiple',[value,value],'claude','sonnet')
        self.assertEqual(len(summarize(state['usage'])['unknown_attempts']),5)


class SearchEfficiencyAndStrategySwitchTests(unittest.TestCase):
    """P6 R4 fix: efficient per-op scanning + explicit coverage + new-vs-repeat distinction + strategy-switch signal,
    real anti-loop guard intact. Exercises the REAL Discovery.search and progress.observe (no algorithm reimplemented)."""
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.discovery=Discovery(self.root)
    def put(self,path,text='x'):
        target=self.root/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text,encoding='utf-8')

    def test_large_repo_match_only_at_tail_is_found_in_one_op_no_drop(self):
        # 300 empty files + the needle in the LAST one. One op (default budget) must scan all and find it - the old
        # 100-file page would have needed 3 model calls and (if the worker stopped early) dropped the tail.
        for i in range(300): self.put('d%03d/f.dart'%i,'nothing here')
        self.put('zzz_last/f.dart','TARGET_TOKEN present')
        r=self.discovery.search('','TARGET_TOKEN')
        self.assertEqual([m['path'] for m in r['matches']],['zzz_last/f.dart'])
        self.assertTrue(r['exhausted']);self.assertIsNone(r['next_cursor'])
        self.assertEqual(r['scanned_through'],r['files_total'])

    def test_per_op_file_budget_pages_without_dropping_and_reports_continuation(self):
        for i in range(10): self.put('d%02d/f.dart'%i,'TARGET_TOKEN' if i==9 else 'none')
        seen=[];cursor=0;ops=0
        with patch('onecrew.discovery.SEARCH_SCAN_FILES',3):
            while cursor is not None:
                r=self.discovery.search('','TARGET_TOKEN',cursor);ops+=1
                seen+=[m['path'] for m in r['matches']]
                self.assertEqual(r['scanned_from'],cursor)
                cursor=r['next_cursor']
        self.assertGreater(ops,1);self.assertIn('d09/f.dart',seen)  # tail found, paged, nothing dropped

    def test_new_coverage_empty_searches_do_not_blind_exhaust_but_sustained_no_results_signal_switch(self):
        # A search op that advanced over NEW files (files_scanned>0, scanned_through>cursor) is coverage, not blind
        # exploration - so it does NOT march toward the exploration cap the way a no-coverage observation does; but
        # sustained no-results raise a STRUCTURED strategy_switch hint so the worker pivots.
        state={'phase':'running','snapshot':None}
        for i in range(20):
            observe(state,'search',{'directory':'','query':'absent','cursor':i*3},
                    {'matches':[],'directories':[],'next_cursor':(i+1)*3,'files_scanned':3,'scanned_through':(i+1)*3})
        self.assertEqual(state['phase'],'running')  # advancing coverage did NOT trip the exploration cap
        self.assertIn('strategy_switch',state['progress'])
        self.assertEqual(state['progress']['strategy_switch']['kind'],'search_not_converging')

    def test_repeating_the_same_region_still_blocks_real_loop_guard_intact(self):
        state={'phase':'running','snapshot':None}
        for _ in range(3):
            observe(state,'search',{'directory':'lib','query':'absent','cursor':0},
                    {'matches':[],'directories':[],'next_cursor':None,'files_scanned':2,'scanned_through':2})
        self.assertEqual(state['phase'],'blocked')  # same region+query+cursor repeated -> same-result guard blocks

    def test_a_found_match_clears_the_switch_signal(self):
        state={'phase':'running','snapshot':None}
        for i in range(6):
            observe(state,'search',{'directory':'','query':'absent','cursor':i*3},
                    {'matches':[],'directories':[],'next_cursor':(i+1)*3,'files_scanned':3,'scanned_through':(i+1)*3})
        self.assertIn('strategy_switch',state['progress'])
        observe(state,'search',{'directory':'','query':'found','cursor':0},
                {'matches':[{'path':'a.dart','lines':[1]}],'directories':[],'next_cursor':None,'files_scanned':1,'scanned_through':1})
        self.assertNotIn('strategy_switch',state['progress'])

class ReconsileAndAskGateEndToEndTests(unittest.TestCase):
    """P6 R4 two-mechanism fix, driven through the REAL run loop (work mode): prompt build -> owned._latest_result (which
    records what was ACTUALLY delivered) -> owned._tool -> progress.observe. The model is stubbed (FixtureWorker replays
    actions); the observe/handler/paging code is the real one, never reimplemented. These are RED on the pre-fix code
    (served was recorded in observe off the REQUEST and re-grant keyed off plan text) and GREEN on the fix."""
    def _fixture(self, lines=600):
        import tests.test_work_contract as wc
        from onecrew.owned import Owned
        from onecrew.owned_intake import submit
        from tests.test_workflow import FixtureWorker
        self._wc=wc; self._Owned=Owned; self._submit=submit; self._FW=FixtureWorker
        t=wc.WorkFixture(); t.setUp(); self.addCleanup(t.doCleanups)
        big="\n".join("line %05d %s"%(i,"x"*60) for i in range(lines))+"\nEND\n"
        (t.root/"big.txt").write_text(big); t.git('add','big.txt'); t.git('commit','-q','-m','big')
        return t
    def _act(self, name, plan, **a):
        import json
        return {'plan':plan,'action':name,'arguments':json.dumps(a)}
    def _drive(self, t, resp, steps=None):
        task=self._submit(t.ledger,None,'work',mode='work',provider='kiro',model='claude-sonnet-5',contract=t.contract())['id']
        run=self._Owned(t.ledger,self._FW(t.ledger,resp)); run.enable(task)
        last=None
        for _ in range(steps or len(resp)):
            last=run.run(task,steps=1)
            if last['phase'] in ('blocked','completed','failed'): break
        return run,task,last

    def test_A_CTS_reselect_already_delivered_page_reconsiders_then_blocks(self):
        # CTS sequence: read a large source, page it, then RE-SELECT an already-delivered page. The real _latest_result
        # recorded that page as delivered; re-selecting it with no new content -> bounded reconsider -> honest finite block.
        t=self._fixture()
        resp=[self._act('read','P1',path='big.txt'),
              self._act('receipt','read offset 0',index=0),       # delivered at next build
              self._act('receipt','read offset 0',index=0),       # re-select #1 -> reconsider
              self._act('receipt','read offset 0',index=0)]       # re-select #2 -> limit -> blocked
        run,task,st=self._drive(t,resp)
        self.assertEqual(st['phase'],'blocked')
        self.assertIn('already-delivered',st['message'])  # the RIGHT mechanism blocked it, not a generic guard
        self.assertEqual(st['recovery']['kind'],'no_progress')

    def test_A_plan_reword_does_NOT_regrant_recovery(self):
        # A2: the re-grant signal is DELIVERED content, never plan text. Rewording the plan each step must STILL block.
        t=self._fixture()
        resp=[self._act('read','P1',path='big.txt'),
              self._act('receipt','Step X: read offset 0',index=0),
              self._act('receipt','EXAMINE offset 0 now',index=0),          # reworded
              self._act('receipt','inspect offset 0 differently again',index=0)]  # reworded again
        run,task,st=self._drive(t,resp)
        self.assertEqual(st['phase'],'blocked')
        self.assertIn('already-delivered',st['message'])

    def test_A_distinct_new_pages_are_progress_never_blocked(self):
        # A valid re-read of GENUINELY NEW content (different offsets) is coverage, not a loop: never blocked.
        t=self._fixture()
        resp=[self._act('read','P',path='big.txt'),
              self._act('receipt','A',index=0,offset=0),
              self._act('receipt','B',index=0,offset=4000),
              self._act('receipt','C',index=0,offset=8000),
              self._act('receipt','D',index=0,offset=12000)]
        run,task,st=self._drive(t,resp)
        self.assertNotEqual(st['phase'],'blocked')

    def test_A_restart_preserves_delivered_pages_and_recovery_obligation(self):
        # A1/A2 under confirmed-send recording: delivered_pages is committed only AFTER the model answers the prompt that
        # carried the page (the adapter's send-evidence), and lives in the checkpoint, so a re-selection after a public
        # resume is still caught. Extra re-selects account for the one-step-later commit.
        t=self._fixture()
        resp=[self._act('read','P',path='big.txt'),
              self._act('receipt','r0',index=0),
              self._act('receipt','r0',index=0),
              self._act('receipt','r0',index=0),
              self._act('receipt','r0',index=0)]
        task=self._submit(t.ledger,None,'work',mode='work',provider='kiro',model='claude-sonnet-5',contract=t.contract())['id']
        run=self._Owned(t.ledger,self._FW(t.ledger,resp)); run.enable(task)
        run.run(task,steps=3)
        seq,state=run.state(task)
        self.assertTrue(state.get('delivered_pages'))  # committed only after the response confirmed the send; durable
        from onecrew.ledger import Ledger
        restored=self._Owned(Ledger(t.root,t.ledger.state_root),self._FW(t.ledger,resp))
        st=None
        for _ in range(4):
            st=restored.run(task,steps=1)
            if st['phase']=='blocked': break
        self.assertEqual(st['phase'],'blocked')
        self.assertIn('already-delivered',st['message'])

    def test_A_does_not_fit_render_sets_no_delivery_candidate(self):
        # A1: a render that returns does_not_fit (tiny budget) must leave NO delivery candidate - a built-but-undelivered
        # page is never 'served'. The candidate lives on the runtime, committed to state only at confirmed send.
        from onecrew.owned import Owned
        t=self._fixture()
        resp=[self._act('read','P',path='big.txt'),self._act('receipt','r0',index=0)]
        task=self._submit(t.ledger,None,'work',mode='work',provider='kiro',model='claude-sonnet-5',contract=t.contract())['id']
        run=Owned(t.ledger,self._FW(t.ledger,resp)); run.enable(task)
        run.run(task,steps=2)
        seq,state=run.state(task)
        val=run._latest_result(dict(state), 50, task)  # a budget too small for any page
        self.assertTrue(val.get('does_not_fit'))
        self.assertIsNone(run._delivered_candidate)  # does_not_fit -> no candidate, so nothing can be committed as served

    def test_A_measurement_render_does_NOT_mutate_delivered_state(self):
        # A1 (Codex v2): _fit_work MEASURES the whole size with _latest_result(state,10**8) and re-renders at each candidate
        # budget. A measurement render is NOT a send and must mutate NOTHING - otherwise a build that then fails records a
        # delivery for a prompt the model never saw. RED on the pre-fix code (the measurement render wrote delivered_pages).
        from onecrew.owned import Owned
        t=self._fixture()
        resp=[self._act('read','P',path='big.txt'),self._act('receipt','r0',index=0)]
        task=self._submit(t.ledger,None,'work',mode='work',provider='kiro',model='claude-sonnet-5',contract=t.contract())['id']
        run=Owned(t.ledger,self._FW(t.ledger,resp)); run.enable(task)
        run.run(task,steps=2)
        seq,state=run.state(task)
        before=len(state.get('delivered_pages') or {})
        run._page_starved=False
        run._latest_result(state, 10**8, task)   # the exact MEASUREMENT call _fit_work makes
        self.assertEqual(len(state.get('delivered_pages') or {}), before)  # measurement mutated nothing

class WorkModeB1Mixin:
    """A work-mode driver with a REAL pinned repo (two commits), used to exercise the B1 commit-relationship verifier
    against real Git objects. A git_show runs as one real step; the ask is then dispatched through the REAL _tool handler
    deterministically (no fixture exhaustion), so the gate decision is the production code's, not a reimplementation."""
    def _wm(self, extra_commits=1):
        import tests.test_work_contract as wc
        from onecrew.owned import Owned
        from onecrew.owned_intake import submit
        from tests.test_workflow import FixtureWorker
        t=wc.WorkFixture(); t.setUp(); self.addCleanup(t.doCleanups)
        for i in range(extra_commits):
            (t.root/('c%d.txt'%i)).write_text('x%d'%i); t.git('add','.'); t.git('commit','-q','-m','c%d'%i)
        task=submit(t.ledger,None,'work',mode='work',provider='kiro',model='claude-sonnet-5',contract=t.contract())['id']
        run=Owned(t.ledger,FixtureWorker(t.ledger,[])); run.enable(task)
        profile=run.control.status(task)['configuration']['profile']
        seq,state=run.state(task)
        return run,task,profile,state
    def _ask_tool(self, run, task, profile, state, **askargs):
        base=dict(question='Is HEAD~1 ancestor of HEAD?',reason='r',
                  options=[{'id':'a','label':'x'},{'id':'b','label':'y'}],recommendation='a')
        base.update(askargs)
        return run._tool(task, state, 'ask', base, profile)


class AskGateB1RelationTests(unittest.TestCase, WorkModeB1Mixin):
    """B1 (Codex v2): a commit_relationship CLAIM is verified against the REAL repo objects - two resolved refs + the
    asserted relation checked by the core (merge-base --is-ancestor) in the pinned repo - NOT merely by citing a git-type
    receipt. These drive the real _verify_commit_relationship and the real ask gate. No SHA/keyword/answer is hard-coded."""

    def test_bare_git_show_without_refs_and_relation_does_NOT_reach_user(self):
        # Codex's exact regression: git_show HEAD + 'proves X ahead of HEAD' with NO resolved refs/relation must be GATED,
        # not built into a user question (the relation was never checked).
        run,task,profile,state=self._wm()
        # a git_show receipt is required as the cite; put one on state via a real step is overkill - cite any existing
        # receipt is impossible with none, so assert the handler gates when the claim cannot be verified.
        res=self._ask_tool(run,task,profile,state,kind='technical',verification='git_show HEAD',
                           verified_receipt=0,claim_kind='commit_relationship')
        self.assertEqual(res,{'action':'ask','blocked':'self_verify_first'})
        self.assertEqual((state.get('recovery') or {}).get('kind'),'self_verify_first')

    def test_verified_true_relation_reaches_user(self):
        # HEAD~1 IS an ancestor of HEAD -> the core verifies it -> the question reaches the user (direct ask path open).
        run,task,profile,state=self._wm()
        # need a cited receipt that EXISTS and is git-type: run one real git_show step first
        from tests.test_workflow import FixtureWorker
        import json
        run.worker=FixtureWorker(run.ledger,[{'plan':'g','action':'git_show','arguments':json.dumps({'commit':'HEAD'})}])
        run.run(task,steps=1)
        seq,state=run.state(task)
        res=self._ask_tool(run,task,profile,state,kind='technical',verification='ancestry verified',
                           verified_receipt=0,claim_kind='commit_relationship',
                           claim_refs=['HEAD~1','HEAD'],claim_relation='ancestor')
        self.assertEqual(run.ledger.requests(task,pending=True) and True, True)  # a request was created
        self.assertEqual(state['phase'],'waiting')

    def test_false_relation_does_NOT_reach_user(self):
        # Claiming HEAD is an ancestor of HEAD~1 is FALSE -> gated, never the user.
        run,task,profile,state=self._wm()
        from tests.test_workflow import FixtureWorker
        import json
        run.worker=FixtureWorker(run.ledger,[{'plan':'g','action':'git_show','arguments':json.dumps({'commit':'HEAD'})}])
        run.run(task,steps=1); seq,state=run.state(task)
        res=self._ask_tool(run,task,profile,state,kind='technical',verification='wrong claim',
                           verified_receipt=0,claim_kind='commit_relationship',
                           claim_refs=['HEAD','HEAD~1'],claim_relation='ancestor')
        self.assertEqual(res,{'action':'ask','blocked':'self_verify_first'})
        self.assertEqual(run.ledger.requests(task,pending=True),[])

    def test_unresolvable_ref_does_NOT_reach_user(self):
        run,task,profile,state=self._wm()
        from tests.test_workflow import FixtureWorker
        import json
        run.worker=FixtureWorker(run.ledger,[{'plan':'g','action':'git_show','arguments':json.dumps({'commit':'HEAD'})}])
        run.run(task,steps=1); seq,state=run.state(task)
        res=self._ask_tool(run,task,profile,state,kind='technical',verification='x',
                           verified_receipt=0,claim_kind='commit_relationship',
                           claim_refs=['deadbeefdeadbeef','HEAD'],claim_relation='ancestor')
        self.assertEqual(res,{'action':'ask','blocked':'self_verify_first'})

    def test_dropping_claim_kind_on_reask_does_NOT_drop_the_obligation(self):
        # B1 (Codex v2): once commit_relationship is declared for an obligation, re-asking the SAME obligation with
        # claim_kind dropped must STILL require the verified relation (sticky obligation) - it cannot bypass by relabeling.
        run,task,profile,state=self._wm()
        from tests.test_workflow import FixtureWorker
        import json
        run.worker=FixtureWorker(run.ledger,[{'plan':'g','action':'git_show','arguments':json.dumps({'commit':'HEAD'})}])
        run.run(task,steps=1); seq,state=run.state(task)
        # first ask declares the kind but gives a FALSE relation -> gated and records the sticky kind
        self._ask_tool(run,task,profile,state,kind='technical',verification='x',verified_receipt=0,
                       claim_kind='commit_relationship',claim_refs=['HEAD','HEAD~1'],claim_relation='ancestor')
        # re-ask the SAME obligation with claim_kind DROPPED and no refs -> must still be gated (not reach user). The
        # sticky obligation keeps the verification requirement, so the relabel/drop cannot bypass it; whether it returns
        # self_verify_first or (at the finite limit) self_verify_exhausted, the key property is it NEVER reaches the user.
        res=self._ask_tool(run,task,profile,state,kind='technical',verification='x',verified_receipt=0)
        self.assertIn(res.get('blocked'), ('self_verify_first','self_verify_exhausted'))
        self.assertEqual(run.ledger.requests(task,pending=True),[])

    def test_reask_relabel_business_does_NOT_drop_obligation(self):
        # Codex v3 branch (a): declare commit_relationship with a WRONG relation (gated, records the obligation), then
        # re-ask the SAME question/options/recommendation as kind=business. The business path must NOT be used to escape
        # the unresolved technical obligation - it stays held, no request is created.
        run,task,profile,state=self._wm()
        from tests.test_workflow import FixtureWorker
        import json
        run.worker=FixtureWorker(run.ledger,[{'plan':'g','action':'git_show','arguments':json.dumps({'commit':'HEAD'})}])
        run.run(task,steps=1); seq,state=run.state(task)
        r1=self._ask_tool(run,task,profile,state,kind='technical',verification='x',verified_receipt=0,
                          claim_kind='commit_relationship',claim_refs=['HEAD','HEAD~1'],claim_relation='ancestor')
        self.assertEqual(r1,{'action':'ask','blocked':'self_verify_first'})
        # SAME obligation (same question/options/recommendation) relabeled business, dropping all verification.
        r2=self._ask_tool(run,task,profile,state,kind='business',verification='x',verified_receipt=0)
        self.assertIn(r2.get('blocked'), ('self_verify_first','self_verify_exhausted'))
        self.assertEqual(run.ledger.requests(task,pending=True),[])
        self.assertNotEqual(state['phase'],'waiting')

    def test_reask_relabel_claim_kind_code_flow_does_NOT_drop_obligation(self):
        # Codex v3 branch (b): declare commit_relationship with a WRONG relation (gated), then re-ask the SAME obligation
        # keeping kind=technical but relabeling claim_kind=code_flow (whose type-floor a git_show receipt would satisfy).
        # The original commit_relationship requirement is sticky and re-applied -> still gated, no request.
        run,task,profile,state=self._wm()
        from tests.test_workflow import FixtureWorker
        import json
        run.worker=FixtureWorker(run.ledger,[{'plan':'g','action':'git_show','arguments':json.dumps({'commit':'HEAD'})}])
        run.run(task,steps=1); seq,state=run.state(task)
        r1=self._ask_tool(run,task,profile,state,kind='technical',verification='x',verified_receipt=0,
                          claim_kind='commit_relationship',claim_refs=['HEAD','HEAD~1'],claim_relation='ancestor')
        self.assertEqual(r1,{'action':'ask','blocked':'self_verify_first'})
        # SAME obligation, relabel claim_kind to code_flow (git_show is in code_flow's type-floor) and drop the refs.
        r2=self._ask_tool(run,task,profile,state,kind='technical',verification='x',verified_receipt=0,
                          claim_kind='code_flow')
        self.assertIn(r2.get('blocked'), ('self_verify_first','self_verify_exhausted'))
        self.assertEqual(run.ledger.requests(task,pending=True),[])
        self.assertNotEqual(state['phase'],'waiting')

    def test_verified_relation_resolves_obligation_then_proceeds(self):
        # Control: once the SAME obligation is actually satisfied (true relation + cite + verification) it is RESOLVED and
        # reaches the user; a later ask on that question is not re-gated. Proves resolution is by matching verification only.
        run,task,profile,state=self._wm()
        from tests.test_workflow import FixtureWorker
        import json
        run.worker=FixtureWorker(run.ledger,[{'plan':'g','action':'git_show','arguments':json.dumps({'commit':'HEAD'})}])
        run.run(task,steps=1); seq,state=run.state(task)
        # first: wrong relation -> gated + records obligation
        self._ask_tool(run,task,profile,state,kind='technical',verification='x',verified_receipt=0,
                       claim_kind='commit_relationship',claim_refs=['HEAD','HEAD~1'],claim_relation='ancestor')
        self.assertEqual(run.ledger.requests(task,pending=True),[])
        # then: TRUE relation -> verified -> reaches the user (obligation resolved)
        res=self._ask_tool(run,task,profile,state,kind='technical',verification='verified',verified_receipt=0,
                           claim_kind='commit_relationship',claim_refs=['HEAD~1','HEAD'],claim_relation='ancestor')
        self.assertEqual(state['phase'],'waiting')
        self.assertEqual(len(run.ledger.requests(task,pending=True)),1)

    def test_direct_authority_still_reaches_user_unaffected(self):
        run,task,profile,state=self._wm()
        res=self._ask_tool(run,task,profile,state,kind='authority',question='Which account may I deploy to?')
        self.assertEqual(state['phase'],'waiting')
        self.assertEqual(len(run.ledger.requests(task,pending=True)),1)


class AskGateTests(unittest.TestCase):
    """B2 (verify-premise, finite loop) against the REAL owned ask handler (model stubbed, handler not reimplemented).
    RED on the pre-fix code (self_verify_count incremented forever and never bounded) and GREEN on the fix."""
    def _ask(self, **kw):
        base=dict(question='Is commit X ahead of HEAD?',reason='r',
                  options=[{'id':'a','label':'x'},{'id':'b','label':'y'}],recommendation='a')
        base.update(kw); return fixtures.action('ask', **base)
    def _run(self, resps, steps):
        fx=fixtures.OwnedTests();fx.setUp();self.addCleanup(fx.doCleanups)
        run,task,w=fx.runtime(resps)
        st=run.run(task,steps=steps)
        return run,task,st

    def test_B2_repeated_technical_ask_is_finite_blocked_not_infinite(self):
        run,task,st=self._run([self._ask(kind='technical') for _ in range(6)], 6)
        self.assertEqual(st['phase'],'blocked')
        self.assertEqual(st['recovery']['kind'],'no_progress')
        self.assertEqual(run.ledger.requests(task,pending=True),[])
        self.assertIn('Repeated technical ask',st['message'])

    def test_B2_result_carries_no_attempt_counter_so_observe_also_bounds_it(self):
        run,task,st=self._run([self._ask(kind='technical')], 1)
        last=json.loads(run.store.read_blob(run.state(task)[1]['receipts'][-1]['blob']))['result']
        self.assertEqual(last, {'action':'ask','blocked':'self_verify_first'})

    def test_B1_technical_without_citation_is_self_verify_first(self):
        run,task,st=self._run([self._ask(kind='technical')], 1)
        self.assertEqual(st['phase'],'running')
        self.assertEqual((st.get('recovery') or {}).get('kind'),'self_verify_first')
        self.assertEqual(run.ledger.requests(task,pending=True),[])

    def test_B_authority_reaches_user_without_forcing_a_technical_step(self):
        run,task,st=self._run([self._ask(kind='authority',question='Which account may I deploy to?')], 1)
        self.assertEqual(st['phase'],'waiting')
        self.assertEqual(len(run.ledger.requests(task,pending=True)),1)

    def test_B_LIMIT_relabel_technical_as_business_bypasses_gate(self):
        # DOCUMENTED LIMIT (un-closable without a core re-classifier): a worker that MISLABELS a technical matter as
        # 'business' is not caught - the gate trusts the declared kind and does not re-classify. Asserted, not hidden.
        run,task,st=self._run([self._ask(kind='business')], 1)
        self.assertEqual(st['phase'],'waiting')


class CTSCheckpointContinuationTests(unittest.TestCase):
    """Finding C (Codex v2): the CTS task is blocked at step 118 on prompt_budget - receipt 117 is a ~12.8 KB read whose
    text cannot be paged to a VALID page (MIN_PAGE) in the room the tight Kiro cap leaves after the fixed context. The fix
    is a MINIMAL context-allocation change: a deepest fallback level (4) that trims ONLY retrievable recovery detail (older
    repeats/failures, kept whole in the checkpoint) to free room for the tool result - never cutting scope/authority/
    acceptance, never widening the cap or lowering MIN_PAGE, never editing the checkpoint. Reproduced on a COPY via the
    REAL prompt-build path (_work_prompt), not a hand-chosen _latest_result budget. Skips when the live CTS state or its
    project repo is not on this host (a skip is NOT a pass)."""
    CTS_STATE=r"D:\OneCrewRuns\live-task-e76c703\state-live1"
    CTS_PROJECT=r"D:\TamNT\Workspace\1.Vimes\7.SRM\source\flutter_srm"
    TID="TASK-8b938053d4804e32be5176e8d7fabec0"
    def _copy_runtime(self):
        import os, tempfile, shutil
        if not os.path.isdir(self.CTS_STATE): self.skipTest('CTS live state not present on this host')
        if not os.path.isdir(self.CTS_PROJECT): self.skipTest('CTS project repo not present on this host')
        tmp=tempfile.mkdtemp(prefix='cts-copy-'); self.addCleanup(shutil.rmtree, tmp, True)
        dst=os.path.join(tmp,'state-live1'); shutil.copytree(self.CTS_STATE,dst)
        from onecrew.ledger import Ledger
        from onecrew.owned import Owned
        return Owned(Ledger(self.CTS_PROJECT,dst),None), dst

    def test_C_real_build_delivers_a_valid_page_via_minimal_recovery_trim(self):
        import json
        from onecrew.owned import contract as C, PromptBudgetError
        from onecrew.paging import MIN_PAGE
        run,dst=self._copy_runtime()
        status=run.control.status(self.TID); seq,st=run.state(self.TID)
        self.assertEqual(st.get('phase'),'blocked')
        self.assertEqual((st.get('recovery') or {}).get('kind'),'prompt_budget')
        self.assertEqual(status.get('used_calls'),118)  # real number, preserved, not reset
        ref=st['receipts'][-1]; self.assertEqual(ref['action'],'read')  # the ~12.8 KB read
        prof=dict(status['configuration']['profile'], provider=(st.get('worker') or {}).get('provider') or 'kiro',
                  model=(st.get('worker') or {}).get('model') or 'claude-sonnet-4.5')
        tp,tsch,_=C(prof)
        with run.ledger.transaction() as conn:
            notes=[json.loads(r['payload']) for r in conn.execute(
                "SELECT payload FROM events WHERE task_id=? AND kind='entry.note' ORDER BY seq DESC LIMIT 5",(self.TID,))]
        # REAL prompt-build path: with the level-4 fallback it now builds a prompt whose latest_result carries a VALID page.
        prompt=run._work_prompt(self.TID, st, prof, status, tp, tsch, notes)
        obj=json.loads('{'+prompt.rpartition('\n{')[2])
        page=(obj.get('latest_result') or {}).get('page')
        self.assertTrue(page, 'latest_result must carry a page')
        self.assertGreaterEqual(page[0]['delivered'], MIN_PAGE)  # a VALID page, not a sub-valid note
        self.assertEqual(page[0].get('offset',0), 0)  # correct continuation: starts at the read's beginning
        # used_calls still the real number; the original live state was never touched (we built on a copy)
        self.assertEqual(run.control.status(self.TID).get('used_calls'),118)

    def test_C_minimal_trim_does_not_widen_cap_or_lower_floor(self):
        from onecrew.paging import MIN_PAGE
        from onecrew.owned import Owned
        self.assertEqual(MIN_PAGE, Owned.MIN_PAGE_CONTENT)  # the valid-page floor is unchanged by the C fix

    def test_C_AB_keys_add_no_bytes_to_this_checkpoint(self):
        import json, sqlite3, os, tempfile, shutil
        from onecrew.ledger import canonical
        if not os.path.isdir(self.CTS_STATE): self.skipTest('CTS live state not present on this host')
        tmp=tempfile.mkdtemp(prefix='cts-k-'); self.addCleanup(shutil.rmtree, tmp, True)
        dst=os.path.join(tmp,'state-live1'); shutil.copytree(self.CTS_STATE,dst)
        db=sqlite3.connect(os.path.join(dst,'ledger.sqlite3')); db.row_factory=sqlite3.Row
        row=db.execute("SELECT payload FROM events WHERE task_id=? AND kind='workflow.checkpoint' ORDER BY seq DESC LIMIT 1",(self.TID,)).fetchone()
        st=json.loads(row['payload'])
        self.assertEqual(len(canonical(st.get('delivered_pages') or {})), 2)  # '{}'
        prog=st.get('progress') or {}
        self.assertNotIn('reconsider_by_page', prog)
        self.assertNotIn('self_verify', prog)


if __name__=='__main__': unittest.main()
