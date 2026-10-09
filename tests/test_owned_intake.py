import tempfile
from pathlib import Path
import unittest
from onecrew.ledger import Ledger, LedgerError
from onecrew.owned_intake import submit
from onecrew.discovery import Discovery


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'project'; self.root.mkdir()
        self.ledger=Ledger(self.root,Path(self.tmp.name)/'state')

    def test_goal_idempotence_and_conflict(self):
        a=submit(self.ledger,'Review architecture','first')
        self.assertEqual(a['id'],submit(Ledger(self.root,self.ledger.state_root),'Review architecture','first')['id'])
        for kwargs in ({'goal':'Other'},{'goal':'Review architecture','max_calls':21}):
            with self.assertRaises(LedgerError): submit(self.ledger,request_key='first',**kwargs)
        self.assertEqual(list(self.root.iterdir()),[])

    def test_permissions_are_explicit(self):
        with self.assertRaises(LedgerError): submit(self.ledger,'Fix bug','a',mode='change')
        with self.assertRaises(LedgerError): submit(self.ledger,'Push','b',mode='delivery',branch='main',remote='origin')

    def test_discovery_nested_and_paged(self):
        (self.root/'child/.git').mkdir(parents=True)
        for i in range(120): (self.root/f'f{i:03}.py').write_text('needle\n')
        d=Discovery(self.root)
        self.assertTrue(d.list()['entries'][0]['repository'])
        self.assertEqual(d.list()['next_cursor'],100)
        self.assertIsNone(d.list(cursor=100)['next_cursor'])
        self.assertTrue(d.search('','needle')['matches'])
        (self.root/'long.py').write_text('x'*13000)
        self.assertEqual(d.read('long.py')['next_cursor'],12000)
        self.assertEqual(len(d.read('long.py',12000)['text']),1000)

    def test_control_escape_secret_and_links(self):
        d=Discovery(self.root)
        for name in ('../outside.py','.env','.git/config','keys/credentials.json'):
            with self.assertRaises(LedgerError): d.read(name)
        (self.root/'innocent.py').write_text('API_KEY=abcdefghijklmno')
        with self.assertRaises(LedgerError): d.read('innocent.py')
        target=Path(self.tmp.name)/'outside.py';target.write_text('outside')
        try: (self.root/'link.py').symlink_to(target)
        except OSError: return
        with self.assertRaises(LedgerError): d.read('link.py')


if __name__=='__main__': unittest.main()
