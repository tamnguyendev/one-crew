import unittest, json
import tests.test_owned as fixtures
from onecrew.git_history import History
from onecrew import progress as P


class GitShowRecoveryTests(unittest.TestCase):
    '''Codex GXP6: git_show two-mode contract + finite file-list-exhausted recovery.
    Real History.show on a real temp git repo + real progress.observe (no algorithm copied into the test).'''
    def setUp(self):
        self.f = fixtures.OwnedTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.f.setup_git()
        self.base = self.f.git('rev-parse','HEAD').decode().strip()
        for i in range(135):
            (self.f.root/('file_%03d.txt'%i)).write_text('hello %d\n'%i)
        self.f.git('add','-A'); self.f.git('commit','-q','-m','many files')
        self.change = self.f.git('rev-parse','HEAD').decode().strip()
        self.run,self.task,self.worker = self.f.runtime([],mode='branch',branch='onecrew/pre-ui')
        self.profile = self.run.control.status(self.task)['configuration']['profile']
        self.history = History(self.run,self.task,self.profile,'')
        # the commit touches more than one list page; total is the whole changed-file set
        self.total = self.history.show(self.change,self.change,None,0)['total_paths']
        self.assertGreater(self.total,100)  # forces list paging (cond 1)

    def test_1_list_pages_explicit_mode_unit_range_totals(self):
        p0 = self.history.show(self.change,self.change,None,0)
        self.assertEqual(p0['mode'],'changed_file_list')
        self.assertIn('file index',p0['cursor_unit'])
        self.assertEqual(len(p0['paths']),100)
        self.assertEqual(p0['returned_files'],[0,100])
        self.assertEqual(p0['next_cursor'],100)
        self.assertIn('cursor=100',p0['next_action'])
        p1 = self.history.show(self.change,self.change,None,100)
        self.assertEqual(len(p1['paths']),self.total-100)
        self.assertEqual(p1['returned_files'],[100,self.total])
        self.assertIsNone(p1['next_cursor'])
        self.assertIn('File list complete',p1['next_action'])
        # reassembled complete, in order, no loss / no dup (cond 1)
        allp = p0['paths']+p1['paths']
        self.assertEqual(len(allp),self.total)
        self.assertEqual(len(set(allp)),self.total)
        self.assertEqual(allp,sorted(allp))

    def test_2_totals_and_continuation_are_distinct_and_correct(self):
        # (b) data range inside the result vs (a) whole-commit total: returned_files is the window, total_paths the whole set
        p0 = self.history.show(self.change,self.change,None,0)
        self.assertEqual(p0['total_paths'],self.total)
        self.assertEqual(p0['returned_files'][1]-p0['returned_files'][0],len(p0['paths']))
        self.assertLess(len(p0['paths']),p0['total_paths'])  # a page is NOT the whole total

    def test_3_exhausted_list_then_path_gives_that_file_diff(self):
        p1 = self.history.show(self.change,self.change,None,100)
        pick = p1['paths'][0]  # worker picks a path itself
        d = self.history.show(self.change,self.change,pick,0)
        self.assertEqual(d['mode'],'file_diff')
        self.assertIn('character offset',d['cursor_unit'])
        self.assertEqual(d['path'],pick)
        self.assertIn('+hello',d['diff'])

    def test_4_recall_exhausted_list_recovers_then_blocks_finitely(self):
        st = {'phase':'running','step':1,'work':{}}
        res1 = self.history.show(self.change,self.change,None,100)  # eof list
        P.observe(st,'git_show',{'commit':self.change,'cursor':100},res1)
        self.assertIsNone((st.get('progress') or {}).get('git_show_mode'))  # not on first call
        P.observe(st,'git_show',{'commit':self.change,'cursor':100},res1)
        hint = (st.get('progress') or {}).get('git_show_mode')
        self.assertIsNotNone(hint)
        self.assertEqual(hint['kind'],'file_list_exhausted')
        self.assertEqual(hint['total_files'],self.total)
        self.assertIn('pick the file yourself',hint['hint'])
        # repetition still blocks finitely via the same-result guard (not disabled)
        P.observe(st,'git_show',{'commit':self.change,'cursor':100},res1)
        self.assertEqual(st['phase'],'blocked')
        self.assertEqual(st['recovery']['kind'],'no_progress')

    def test_4b_hint_cleared_by_a_different_action(self):
        st = {'phase':'running','step':1,'work':{}}
        res1 = self.history.show(self.change,self.change,None,100)
        P.observe(st,'git_show',{'commit':self.change,'cursor':100},res1)
        P.observe(st,'git_show',{'commit':self.change,'cursor':100},res1)
        self.assertIsNotNone((st.get('progress') or {}).get('git_show_mode'))
        P.observe(st,'list',{'directory':''},{'entries':[]})
        self.assertIsNone((st.get('progress') or {}).get('git_show_mode'))

    def test_5_restart_resume_preserves_hint_and_counters(self):
        st = {'phase':'running','step':1,'work':{}}
        res1 = self.history.show(self.change,self.change,None,100)
        P.observe(st,'git_show',{'commit':self.change,'cursor':100},res1)
        P.observe(st,'git_show',{'commit':self.change,'cursor':100},res1)
        rt = json.loads(json.dumps(st))  # checkpoint round-trip
        self.assertEqual(rt['progress']['git_show_mode']['kind'],'file_list_exhausted')
        P.observe(rt,'git_show',{'commit':self.change,'cursor':100},res1)  # counters preserved
        self.assertEqual(rt['phase'],'blocked')

    def test_6_controls_short_list_and_multipage_diff_not_degraded(self):
        one = self.history.show(self.base,self.base,None,0)  # short single-page list
        self.assertEqual(one['mode'],'changed_file_list')
        self.assertIsNone(one['next_cursor'])
        big = '\n'.join('line %05d %s'%(i,'z'*40) for i in range(500))
        (self.f.root/'big.txt').write_text(big+'\n')
        self.f.git('add','big.txt'); self.f.git('commit','-q','-m','bigfile')
        bc = self.f.git('rev-parse','HEAD').decode().strip()
        d0 = self.history.show(bc,bc,'big.txt',0)  # multi-page diff
        self.assertEqual(d0['mode'],'file_diff')
        self.assertIsNotNone(d0['next_cursor'])
        self.assertIn('cursor=',d0['next_action'])
        d1 = self.history.show(bc,bc,'big.txt',d0['next_cursor'])
        self.assertEqual(d1['returned_diff_chars'][0],d0['next_cursor'])


if __name__ == '__main__':
    unittest.main()
