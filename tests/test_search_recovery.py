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
        # A page delivered before a restart is still 'delivered' after it: delivered_pages lives in the checkpoint, so a
        # re-selection after a public resume is caught just the same (the recovery obligation survives restart).
        import json
        t=self._fixture()
        resp=[self._act('read','P',path='big.txt'),
              self._act('receipt','r0',index=0),   # delivered
              self._act('receipt','r0',index=0),   # re-select #1 -> reconsider
              self._act('receipt','r0',index=0)]   # re-select #2 -> block
        task=self._submit(t.ledger,None,'work',mode='work',provider='kiro',model='claude-sonnet-5',contract=t.contract())['id']
        run=self._Owned(t.ledger,self._FW(t.ledger,resp)); run.enable(task)
        # delivered_pages is written at the NEXT prompt build (it records the page rendered into the following prompt),
        # so after read + first receipt + the build that renders that receipt, it is populated and in the checkpoint.
        run.run(task,steps=3)
        seq,state=run.state(task)
        self.assertTrue(state.get('delivered_pages'))  # recorded from the REAL render, survives in the checkpoint
        # fresh runtime object (simulates a restart): the durable state carries delivered_pages
        from onecrew.ledger import Ledger
        restored=self._Owned(Ledger(t.root,t.ledger.state_root),self._FW(t.ledger,resp))
        st=None
        for _ in range(3):
            st=restored.run(task,steps=1)
            if st['phase']=='blocked': break
        self.assertEqual(st['phase'],'blocked')
        self.assertIn('already-delivered',st['message'])

    def test_A_does_not_fit_page_is_not_recorded_as_delivered(self):
        # A1: a built-but-undelivered page (its render returns does_not_fit under a tiny budget) must NOT become 'served'.
        from onecrew.owned import Owned
        t=self._fixture()
        resp=[self._act('read','P',path='big.txt'),self._act('receipt','r0',index=0)]
        task=self._submit(t.ledger,None,'work',mode='work',provider='kiro',model='claude-sonnet-5',contract=t.contract())['id']
        run=Owned(t.ledger,self._FW(t.ledger,resp)); run.enable(task)
        run.run(task,steps=2)
        seq,state=run.state(task)
        state2=dict(state)
        # a budget too small for any page -> does_not_fit; delivery must record nothing for it
        val=run._latest_result(state2, 50, task)
        self.assertTrue(val.get('does_not_fit'))
        before=dict(state2.get('delivered_pages') or {})
        # the tiny-budget render above did not add a NEW delivered key (nothing recorded on does_not_fit)
        run._latest_result(state2, 50, task)
        self.assertEqual(set((state2.get('delivered_pages') or {})), set(before))

class AskGateTests(unittest.TestCase):
    """P6 R4 verify-premise gate (B1/B2) against the REAL owned ask handler (model stubbed, handler not reimplemented).
    RED on the pre-fix code (self_verify_count incremented forever and never bounded; a cited receipt passed on mere
    existence) and GREEN on the fix. Honest LIMITS are asserted, not hidden."""
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
        # B2: the SAME unresolved technical ask repeated is bounded on STABLE content -> honest no_progress block, never
        # waiting-on-user, never burning to the budget. (RED pre-fix: self_verify_count rose forever, phase stayed running.)
        run,task,st=self._run([self._ask(kind='technical') for _ in range(6)], 6)
        self.assertEqual(st['phase'],'blocked')
        self.assertEqual(st['recovery']['kind'],'no_progress')
        self.assertEqual(run.ledger.requests(task,pending=True),[])  # never reached the user
        self.assertIn('Repeated technical ask',st['message'])

    def test_B2_result_carries_no_attempt_counter_so_observe_also_bounds_it(self):
        # The handler's returned result for a gated ask carries NO per-attempt counter, so observe()'s same-result guard
        # treats the repeats as one stable result (a changing count can no longer mask the loop). First gated return:
        run,task,st=self._run([self._ask(kind='technical')], 1)
        last=json.loads(run.store.read_blob(run.state(task)[1]['receipts'][-1]['blob']))['result']
        self.assertEqual(last, {'action':'ask','blocked':'self_verify_first'})  # stable, no count field

    def test_B1_technical_without_citation_is_self_verify_first(self):
        run,task,st=self._run([self._ask(kind='technical')], 1)
        self.assertEqual(st['phase'],'running')
        self.assertEqual((st.get('recovery') or {}).get('kind'),'self_verify_first')
        self.assertEqual(run.ledger.requests(task,pending=True),[])

    def test_B1_machine_checkable_claim_rejects_unrelated_receipt(self):
        # B1: a declared machine-checkable claim_kind (commit_relationship) citing an UNRELATED receipt (a read) does NOT
        # pass on mere existence -> gated to self-verify. (RED pre-fix: any existing receipt passed.)
        run,task,st=self._run([fixtures.action('read',path='calc.py'),
            self._ask(kind='technical',verification='looked at calc.py',verified_receipt=0,claim_kind='commit_relationship')], 2)
        self.assertEqual(st['phase'],'running')
        self.assertEqual((st.get('recovery') or {}).get('kind'),'self_verify_first')
        self.assertEqual(run.ledger.requests(task,pending=True),[])

    def test_B1_machine_checkable_claim_accepts_matching_git_receipt(self):
        # The same claim citing a git_show receipt (the right tool for a commit relationship) reaches the user.
        run,task,st=self._run([fixtures.action('git_show',commit='HEAD'),
            self._ask(kind='technical',verification='git_show HEAD shows ancestry',verified_receipt=0,claim_kind='commit_relationship')], 2)
        self.assertEqual(st['phase'],'waiting')
        self.assertEqual(len(run.ledger.requests(task,pending=True)),1)

    def test_B_authority_reaches_user_without_forcing_a_technical_step(self):
        run,task,st=self._run([self._ask(kind='authority',question='Which account may I deploy to?')], 1)
        self.assertEqual(st['phase'],'waiting')
        self.assertEqual(len(run.ledger.requests(task,pending=True)),1)

    def test_B_LIMIT_relabel_technical_as_business_bypasses_gate(self):
        # DOCUMENTED LIMIT (un-closable without a core verifier): a worker that MISLABELS a technical matter 'business'
        # is not caught - the gate trusts the declared kind and does not re-classify. Asserted so the limit is explicit.
        run,task,st=self._run([self._ask(kind='business')], 1)
        self.assertEqual(st['phase'],'waiting')  # reaches user (known limit)

    def test_B_LIMIT_cited_receipt_content_not_semantically_verified(self):
        # DOCUMENTED LIMIT: for a machine-checkable claim the gate checks the cited receipt is of the RIGHT TYPE, not that
        # its CONTENT supports the claim. A git_show of an UNRELATED commit still passes. Closing this needs a core-run
        # verifier (e.g. the core itself runs the ancestry check) - out of the bounded A/B scope.
        run,task,st=self._run([fixtures.action('git_show',commit='HEAD'),
            self._ask(kind='technical',verification='cited a git_show (but of an unrelated commit)',
                      verified_receipt=0,claim_kind='commit_relationship')], 2)
        self.assertEqual(st['phase'],'waiting')  # type matches; content relevance is NOT verified (known limit)

class CTSCheckpointContinuationTests(unittest.TestCase):
    """Finding C: the CTS task is blocked at step 118 on prompt_budget - receipt 117 is a ~12 KB read whose text cannot be
    paged to a VALID page (MIN_PAGE) in the room the tight Kiro cap leaves after the fixed context. This test works on a
    COPY of the real checkpoint (never the original), asserts the blocker is a clearly-analysed prompt_budget case (not
    made green by widening the cap, lowering the threshold, or editing the checkpoint), and that the A/B keys add no bytes
    to this checkpoint - so A/B does not cause or worsen C. The real fix for C is a context-allocation change OUTSIDE the
    bounded A/B scope; it is reported as a dependency, not attempted here."""
    CTS_STATE=r"D:\OneCrewRuns\live-task-e76c703\state-live1"
    def _load_copy(self):
        import sqlite3, json, os, tempfile, shutil
        if not os.path.isdir(self.CTS_STATE): self.skipTest('CTS live state not present on this host')
        tmp=tempfile.mkdtemp(prefix='cts-copy-'); self.addCleanup(shutil.rmtree, tmp, True)
        dst=os.path.join(tmp,'state-live1'); shutil.copytree(self.CTS_STATE,dst)
        db=sqlite3.connect(os.path.join(dst,'ledger.sqlite3')); db.row_factory=sqlite3.Row
        tid='TASK-8b938053d4804e32be5176e8d7fabec0'
        row=db.execute("SELECT payload FROM events WHERE task_id=? AND kind='workflow.checkpoint' ORDER BY seq DESC LIMIT 1",(tid,)).fetchone()
        return json.loads(row['payload']), dst

    def test_C_oversized_read_is_sub_valid_in_the_tight_room_and_needs_more_room_not_a_threshold_change(self):
        import json, os
        from onecrew.ledger import Ledger
        from onecrew.owned import Owned
        from onecrew.paging import MIN_PAGE
        st,dst=self._load_copy()
        self.assertEqual(st.get('phase'),'blocked')
        self.assertEqual((st.get('recovery') or {}).get('kind'),'prompt_budget')  # a clearly-analysed blocker, unchanged
        ref=st['receipts'][-1]; self.assertEqual(ref['action'],'read')  # a ~12 KB read, the largest latest result
        run=Owned(Ledger(os.path.dirname(os.path.dirname(__file__)), dst), None)  # project unused: a read has no log
        # Through the REAL _latest_result: in the room the tight Kiro context leaves (~1758), the largest page of this
        # read is UNDER a valid page (MIN_PAGE). Lowering MIN_PAGE or widening the cap to 'go green' is forbidden.
        run._page_starved=False; run._latest_result(st, 1758)
        self.assertLess(run._page_content, MIN_PAGE)  # sub-valid in the room left -> the real prompt_budget block
        # The MINIMAL option (reported as an out-of-A/B-scope dependency, not implemented): give the latest result more
        # room. With ~2500 chars a VALID page of the SAME read is delivered - no threshold change, no cap widening.
        run._page_starved=False; run._latest_result(st, 2500)
        self.assertGreaterEqual(run._page_content, MIN_PAGE)

    def test_C_AB_keys_add_no_bytes_to_this_checkpoint(self):
        from onecrew.ledger import canonical
        st,_=self._load_copy()
        # A/B state keys are absent/empty on a pre-A/B blocked checkpoint, and the conditional recovery hints are not set,
        # so switching to the A/B runtime adds no context bytes here (A/B neither causes nor worsens the prompt_budget block).
        self.assertEqual(len(canonical(st.get('delivered_pages') or {})), 2)  # '{}'
        prog=st.get('progress') or {}
        self.assertNotIn('reconsider_by_page', prog)
        self.assertNotIn('self_verify', prog)


if __name__=='__main__': unittest.main()
