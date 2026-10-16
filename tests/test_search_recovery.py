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

class ReconsileAndAskGateTests(unittest.TestCase):
    """P6 R4 two-mechanism fix: (A) progress-reconciliation recovery when a receipt re-selects an already-served page with
    an unchanged plan; (B) verify-premise gate before a technical ask. Exercises REAL progress.observe and the REAL owned
    ask handler (model stubbed via fixtures, handler NOT reimplemented)."""
    def _page(self, idx, off):
        return {'matches':None}  # unused; receipt result shape below

    def test_A_reread_same_served_page_unchanged_plan_reconsiders_then_blocks(self):
        state={'phase':'running','snapshot':None,'plan':'Step 40: read offset 8649'}
        args={'index':62,'offset':8649}
        res={'text':'section 2.4','next_cursor':10553}
        # first receipt page: served, credited as progress (new page)
        observe(state,'receipt',args,res)
        self.assertEqual(state['phase'],'running')
        self.assertNotIn('reconsider',state['progress'])
        # re-select the SAME page with the SAME (stale) plan -> reconsider signal, still running
        observe(state,'receipt',args,res)
        self.assertEqual(state['phase'],'running')
        self.assertIn('reconsider',state['progress'])
        self.assertEqual(state['progress']['reconsider']['kind'],'already_read_region')
        # re-select AGAIN, still stale -> reconsider limit reached -> blocked (honest, finite)
        observe(state,'receipt',args,res)
        self.assertEqual(state['phase'],'blocked')
        self.assertIn('without advancing the plan',state['message'])

    def test_A_valid_reread_after_plan_update_is_allowed(self):
        state={'phase':'running','snapshot':None,'plan':'Step 40: read offset 8649'}
        args={'index':62,'offset':8649}; res={'text':'x','next_cursor':10553}
        observe(state,'receipt',args,res)
        # genuine plan update (new conclusion) BEFORE re-reading -> not a stale re-read, no block
        state['plan']='Found: registration flow lives in hms_signature_trans; next read lib/foo.dart'
        observe(state,'receipt',args,res)
        self.assertEqual(state['phase'],'running')
        # a plan-WORDING-only change does not count as progress: revert conclusion, re-read twice -> reconsiders/blocks
        state['plan']='Step 40: READ offset 8649   '  # same normalized conclusion as start
        observe(state,'receipt',args,res); observe(state,'receipt',args,res)
        self.assertEqual(state['phase'],'blocked')

    def test_A_counters_survive_checkpoint_roundtrip(self):
        import json
        state={'phase':'running','snapshot':None,'plan':'p'}
        args={'index':5,'offset':100}; res={'text':'y','next_cursor':200}
        observe(state,'receipt',args,res)
        state=json.loads(json.dumps(state))  # simulate checkpoint persist/restore
        observe(state,'receipt',args,res)
        self.assertIn('reconsider',state['progress'])  # served_pages survived the roundtrip

    def test_B_technical_ask_without_verification_is_self_verify_first_not_user_halt(self):
        fixture=fixtures.OwnedTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        run,task,worker=fixture.runtime([fixtures.action('ask',question='Is commit X ahead of HEAD?',
            reason='need to know',options=[{'id':'a','label':'ahead'},{'id':'b','label':'in HEAD'}],
            recommendation='a',kind='technical')])
        state=run.run(task,steps=1)
        self.assertEqual(state['phase'],'running')  # NOT waiting on the user
        self.assertEqual((state.get('recovery') or {}).get('kind'),'self_verify_first')
        self.assertEqual(run.ledger.requests(task,pending=True),[])  # no user request created

    def test_B_authority_ask_reaches_the_user(self):
        fixture=fixtures.OwnedTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        run,task,worker=fixture.runtime([fixtures.action('ask',question='Which account may I deploy to?',
            reason='missing authority',options=[{'id':'a','label':'prod'},{'id':'b','label':'staging'}],
            recommendation='b',kind='authority')])
        state=run.run(task,steps=1)
        self.assertEqual(state['phase'],'waiting')  # genuine authority question reaches the user
        self.assertEqual(len(run.ledger.requests(task,pending=True)),1)

if __name__=='__main__': unittest.main()
