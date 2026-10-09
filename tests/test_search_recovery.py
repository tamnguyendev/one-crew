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
        with patch('onecrew.discovery.SEARCH_PAGE',1):
            pages=[];cursor=0
            while cursor is not None:
                result=self.discovery.search('','Cloud Auth',cursor);pages.append(result);cursor=result['next_cursor']
            self.assertEqual(len(pages),3)
            self.assertEqual({m['path'] for p in pages for m in p['matches']},
                             {'shared/lib/settings/page.dart','shared/lib/l10n/vi.arb'})
            self.assertTrue(all(p['recursive'] and p['query']=='Cloud Auth' for p in pages))
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


if __name__=='__main__': unittest.main()
