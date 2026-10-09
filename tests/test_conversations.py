from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
from onecrew.ledger import Ledger,LedgerError
from onecrew import conversations as c


def solution():
    return dict(brief='Implement addition correctly, preserving the API.',detail='Fix arithmetic and verify existing tests.',
        acceptance=['Two plus three is five.'],non_goals=['No API redesign.'],assumptions=[],questions=[])


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'repo';self.root.mkdir()
        self.ledger=Ledger(self.root,Path(self.tmp.name)/'state')
        self.cid=c.create(self.ledger,'Shared solution','create','codex')['id']

    def test_no_task_and_project_isolation_and_read_does_not_create_db(self):
        with self.ledger.transaction() as conn:self.assertEqual(conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0],0)
        other=Path(self.tmp.name)/'other';other.mkdir()
        with self.assertRaises(LedgerError):c.read(Ledger(other,self.ledger.state_root),self.cid)
        empty=Ledger(other,Path(self.tmp.name)/'empty-state');self.assertEqual(c.list_conversations(empty),[]);self.assertFalse(empty.path.exists())

    def test_parallel_append_restart_dedup_conflict_and_pagination(self):
        def put(i):return c.append(self.ledger,self.cid,'msg'+str(i),'Opinion '+str(i),'claude')
        with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(put,range(12)))
        self.assertEqual(len({v['seq'] for v in results}),12)
        self.assertEqual(put(0)['id'],results[0]['id'])
        with self.assertRaises(LedgerError):c.append(self.ledger,self.cid,'msg0','different','claude')
        ledger=Ledger(self.root,self.ledger.state_root);page=c.read(ledger,self.cid,limit=3);seen=[]
        while True:
            seen.extend(x['id'] for x in page['events'])
            if not page['has_more']:break
            page=c.read(ledger,self.cid,after=page['cursor'],limit=3)
        self.assertEqual(len(seen),13);self.assertEqual(len(set(seen)),13)

    def test_concurrent_proposals_retained_no_silent_overwrite(self):
        a=c.propose(self.ledger,self.cid,'s1',solution(),'kiro')
        b=c.propose(self.ledger,self.cid,'s2',dict(solution(),detail='Alternative implementation'),'claude')
        self.assertTrue(a['selected']);self.assertTrue(b['conflict'])
        self.assertEqual(c.read(self.ledger,self.cid)['solution']['id'],a['id'])
        with self.assertRaises(LedgerError):c.decide(self.ledger,b['id'],b['revision'],'approve','codex','user said approve')
        c.select(self.ledger,self.cid,b['id'],a['id'],'codex')
        self.assertEqual(c.show_solution(self.ledger,a['id'])['payload'],solution())

    def test_approval_pins_full_content_and_open_questions_block(self):
        a=c.propose(self.ledger,self.cid,'s1',solution(),'kiro')
        with self.assertRaises(LedgerError):c.decide(self.ledger,a['id'],'stale','approve','claude','user')
        decision=c.decide(self.ledger,a['id'],a['revision'],'approve','claude','actual user message')
        self.assertEqual(c.decide(self.ledger,a['id'],a['revision'],'approve','claude','actual user message')['id'],decision['id'])
        b=c.propose(self.ledger,self.cid,'s2',dict(solution(),questions=['Which API?']),'codex',a['id'])
        with self.assertRaises(LedgerError):c.decide(self.ledger,b['id'],b['revision'],'approve','claude','user')
        with self.ledger.transaction() as conn:
            with self.assertRaises(LedgerError):c.approved(self.ledger,conn,a['id'],a['revision'])

    def test_summary_sources_staleness_never_hide_current_decision(self):
        note=c.append(self.ledger,self.cid,'n','Known behavior','kiro')
        c.summarize(self.ledger,self.cid,'Summary',[note['id']],note['seq'],'codex')
        a=c.propose(self.ledger,self.cid,'s',solution(),'kiro');c.decide(self.ledger,a['id'],a['revision'],'approve','codex','user')
        result=c.read(self.ledger,self.cid,limit=1)
        self.assertTrue(result['summary']['stale']);self.assertEqual(result['decision']['choice'],'approve')
        with self.assertRaises(LedgerError):c.summarize(self.ledger,self.cid,'bad',['missing'],note['seq'],'codex')

    def test_source_data_cannot_become_decision_or_leak_secret(self):
        with self.assertRaises(LedgerError):c.append(self.ledger,self.cid,'bad','approve','worker',kind='decision')
        with self.assertRaises(LedgerError):c.append(self.ledger,self.cid,'secret','sk-ant-'+('x'*25),'worker')


if __name__=='__main__':unittest.main()
