import contextlib
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from onecrew import delivery_store as db
from onecrew import interventions as iv
from onecrew.ledger import Ledger, LedgerError, utcnow
from onecrew.specs import Project
from onecrew.supervisor import identity
from onecrew.workflow import Workflow
from tests.test_workflow import FixtureWorker, SAMPLE, profile

QUESTION = {'schema_version': 1, 'question': 'Proceed?', 'reason': 'Decision required', 'impact': 'Root waits',
            'options': [{'id': 'a', 'label': 'A'}, {'id': 'b', 'label': 'B'}], 'recommendation': 'a',
            'action': {'type': 'noop', 'parameters': {}}}
CREATED = identity(os.getpid())['created'] if os.name == 'nt' else 2
DEAD = {'pid': os.getpid(), 'created': CREATED+1, 'host': socket.gethostname()}  # same pid, other creation time (after boot)
BOOTED = {'pid': os.getpid(), 'created': 1, 'host': socket.gethostname()}  # created before the last boot
UNKNOWN = {'pid': 4, 'created': 1, 'host': 'another-host'}
RUNTIME = 'f'*64


class LedgerFixture:
    """Temp state root; delivery roots are registered workflow tasks (keeper reads only lineage/state)."""
    def __init__(self, case):
        tmp = tempfile.TemporaryDirectory(); case.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        env = patch.dict(os.environ, {'ONECREW_DESKTOP_HOME': str(self.base/'desktop')}); env.start(); case.addCleanup(env.stop)
        for name in ('ONECREW_ACTOR', 'ONECREW_RUNNER_INITIATOR', 'ONECREW_KEEPER'): os.environ.pop(name, None)
        self.project = self.base/'project'; (self.project/'specs').mkdir(parents=True)
        (self.project/'specs/SPEC-001-duyet-spec.md').write_text(SAMPLE, encoding='utf-8')
        self.state_root = self.base/'state'; self.ledger = Ledger(self.project, self.state_root)
        spec = Project(self.project).find('SPEC-001')
        Project(self.project).decide(spec, spec.revision, 'approved', 'fixture', 'Test operator approval')
        self.workflow = Workflow(self.ledger, FixtureWorker(self.ledger, []))

    def task(self, key='fixture', phase=None):
        grant = {'schema_version': 1, 'permissions': ['artifact.generate'], 'limits': {'max_calls': 6, 'max_seconds': 3600}, 'source': 'fixture'}
        task = self.ledger.submit('SPEC-001', Project(self.project).find('SPEC-001').revision, key, grant)
        self.workflow.enable(task['id'], task['revision'], profile())
        if phase: self.phase(task['id'], phase)
        return task['id']

    def phase(self, task, phase):
        seq, state = self.workflow.state(task)
        return self.workflow.persist(task, seq, dict(state, phase=phase))

    def root(self, key, phase='running'):
        task = self.task(key, phase)
        with self.ledger.transaction(write=True) as conn:
            db.ensure(conn); conn.execute('INSERT INTO delivery_roots VALUES(?,?,?)', (task, '{}', 'fixture'))
        return task

    def child(self, root, key):
        task = self.task(key)
        with self.ledger.transaction(write=True) as conn:
            conn.execute('INSERT INTO delivery_children VALUES(?,?,?,?)', (task, root, 'node-'+key, 0))
        return task

    def started(self, task, identity=DEAD, initiator=None, tree=RUNTIME):
        """tree=None is a legacy start, written by a runtime that predates runtime evidence and the keeper."""
        payload = {'identity': identity, 'started_at': utcnow()}
        if initiator: payload['initiator'] = initiator
        if tree: payload['runtime'] = {'tree': tree, 'git': None, 'dirty': None}
        with self.ledger.transaction(write=True) as conn:
            self.ledger._event(conn, task, 'runner.started', payload)

    def events(self, task, kind):
        with self.ledger.transaction() as conn:
            return [dict(r) | {'payload': json.loads(r['payload'])} for r in
                    conn.execute('SELECT * FROM events WHERE task_id=? AND kind=? ORDER BY seq', (task, kind))]


class ActorAndRuntimeTests(unittest.TestCase):
    def test_actor_mapping_from_source_then_environment(self):
        with patch.dict(os.environ, {'ONECREW_ACTOR': 'codex'}):
            self.assertEqual(iv.actor(), 'codex')
            self.assertEqual(iv.actor('claude-entry'), 'claude')
            self.assertEqual(iv.actor('kiro-entry'), 'other-entry')
            self.assertEqual(iv.actor('mcp-entry'), 'codex')  # unmapped source falls back to the environment
        for value, expected in (('KEEPER', 'keeper'), ('user', 'user'), ('onecrew', 'onecrew'), ('other-entry', 'other-entry'),
                                ('admin', 'unknown'), ('claude-code', 'unknown'), ('', 'unknown')):
            with patch.dict(os.environ, {'ONECREW_ACTOR': value}):
                self.assertEqual(iv.actor(), expected, value)
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(iv.actor(), 'unknown')
            self.assertEqual(iv.actor('mcp-entry'), 'unknown')
        for value, expected in (('keeper', 'keeper'), ('reply', 'reply'), ('Bad Value!', 'unknown'), ('', 'unknown')):
            with patch.dict(os.environ, {'ONECREW_RUNNER_INITIATOR': value}):
                self.assertEqual(iv.initiator(), expected)

    def test_tree_detects_runtime_changes_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp)
            (package/'a.py').write_text('x = 1\n'); (package/'b.md').write_text('doc'); (package/'c.txt').write_text('ignored')
            (package/'__pycache__').mkdir(); (package/'__pycache__/a.py').write_text('cache')
            first = iv.tree(package)
            (package/'c.txt').write_text('still ignored'); (package/'__pycache__/a.py').write_text('changed cache')
            self.assertEqual(iv.tree(package), first)
            (package/'a.py').write_text('x = 2\n'); second = iv.tree(package)
            self.assertNotEqual(second, first)
            (package/'sub').mkdir(); (package/'sub/d.json').write_text('{}')
            self.assertNotEqual(iv.tree(package), second)
            outside = iv.revision(package)
            self.assertEqual(outside['tree'], iv.tree(package))
            if outside['git'] is None: self.assertIsNone(outside['dirty'])  # no repository: unknown, not clean

    def test_runtime_revision_is_computed_once_per_process(self):
        fake = {'tree': 'a'*64, 'git': None, 'dirty': None}
        with patch.object(iv, '_REVISION', None), patch.object(iv, 'revision', return_value=dict(fake)) as compute:
            first = iv.runtime_revision(); first['tree'] = 'mutated'
            self.assertEqual(iv.runtime_revision(), fake)
            self.assertEqual(compute.call_count, 1)
        real = iv.runtime_revision()
        self.assertRegex(real['tree'], '^[0-9a-f]{64}$')
        self.assertTrue(real['git'] is None or len(real['git']) >= 40)
        self.assertIn(real['dirty'], (True, False, None))

    def test_file_replaced_mid_hash_is_unknown_runtime_not_an_error(self):
        with patch.object(iv, 'tree', side_effect=[FileNotFoundError('replaced'), 'b'*64]):
            self.assertEqual(iv.revision()['tree'], 'b'*64)  # an atomic save settles at once
        with patch.object(iv, 'tree', side_effect=PermissionError('locked')) as hashing:
            self.assertIsNone(iv.revision()['tree'])
        self.assertEqual(hashing.call_count, 2)
        with patch.object(iv, '_REVISION', None), patch.object(iv, 'tree', side_effect=OSError('gone')):
            self.assertIsNone(iv.runtime_revision()['tree'])
        real = iv.runtime_revision()
        self.assertTrue(real['git'] is None or len(real['git']) >= 40)
        self.assertIn(real['dirty'], (True, False, None))


class RecordTests(unittest.TestCase):
    def setUp(self):
        self.f = LedgerFixture(self); self.task = self.f.task()

    def test_record_payload_is_evidence_without_task_mutation(self):
        seq, state = self.f.workflow.state(self.task)
        before = self.f.workflow.control.status(self.task)
        payload = iv.record(self.f.ledger, self.task, 'work.extend', actor='claude-entry', reason='r'*600, details={'max_calls': 9})
        self.assertEqual(payload, {'actor': 'claude', 'channel': 'cli', 'command': 'work.extend', 'reason': 'r'*500,
                                   'details': {'max_calls': 9}, 'runtime': iv.runtime_revision()['tree'], 'checkpoint_seq': seq})
        self.assertEqual(self.f.workflow.state(self.task), (seq, state))
        after = self.f.workflow.control.status(self.task)
        self.assertEqual((after['status'], after['used_calls'], after['deadline']), (before['status'], before['used_calls'], before['deadline']))
        self.assertEqual(iv.record(self.f.ledger, self.task, 'task.cancel', channel='mcp')['actor'], 'unknown')
        with patch.dict(os.environ, {'ONECREW_ACTOR': 'user'}):
            self.assertEqual(iv.record(self.f.ledger, self.task, 'work.pause')['actor'], 'user')
        self.assertEqual(len(self.f.events(self.task, 'control.intervention')), 3)

    def test_keyed_record_is_idempotent_and_invalid_input_rejected(self):
        first = iv.record(self.f.ledger, self.task, 'request.reply', key='REPLY-1')
        self.assertEqual(iv.record(self.f.ledger, self.task, 'request.reply', key='REPLY-1'), first)
        self.assertEqual(len(self.f.events(self.task, 'control.intervention')), 1)
        with self.assertRaises(LedgerError): iv.record(self.f.ledger, 'TASK-'+'0'*32, 'work.pause')
        with self.assertRaises(LedgerError): iv.record(self.f.ledger, self.task, 'bad/command')
        self.assertEqual(iv.record(self.f.ledger, self.task, 'delivery start')['command'], 'delivery.start')
        with self.assertRaises(LedgerError): iv.record(self.f.ledger, self.task, 'work.pause', details=['not', 'a', 'dict'])
        big = iv.record(self.f.ledger, self.task, 'work.extend', details={'x': 'y'*5000})['details']
        self.assertTrue(big['truncated']); self.assertRegex(big['sha256'], '^[0-9a-f]{64}$')
        self.assertEqual(iv.note(self.f.ledger, 'TASK-'+'0'*32, 'work.pause')['recorded'], False)

    def test_summary_orders_interventions_assistance_and_runtime_changes(self):
        child = self.f.task('child')
        self.f.started(self.task, tree='a'*64)
        iv.record(self.f.ledger, self.task, 'task.resume', actor='codex', channel='mcp')
        self.f.started(self.task, tree='a'*64)
        self.f.started(child, tree='c'*64)  # another task's tree never counts as a change here
        with self.f.ledger.transaction(write=True) as conn:
            self.f.ledger._event(conn, child, 'eval.assistance', {'key': 'k', 'actor': 'claude', 'category': 'runtime',
                                 'reason': 'Repaired runner', 'checkpoint': None, 'source': 'operator-recorded; not independently verified'})
        self.f.started(self.task, tree=None)  # legacy start without runtime is not evidence of a change
        self.f.started(self.task, tree='b'*64)
        rows = iv.summary(self.f.ledger, [self.task, child])
        self.assertEqual([r['seq'] for r in rows], sorted(r['seq'] for r in rows))
        self.assertEqual([(r['task'], r['command'], r['actor'], r['channel']) for r in rows], [
            (self.task, 'task.resume', 'codex', 'mcp'), (child, 'eval.assistance', 'claude', 'eval'),
            (self.task, 'runtime.changed', 'unknown', 'runtime')])
        self.assertEqual(rows[1]['category'], 'runtime'); self.assertEqual(rows[1]['reason'], 'Repaired runner')
        self.assertIn('aaaaaaaaaaaa -> bbbbbbbbbbbb', rows[2]['reason'])
        self.assertTrue(all({'task', 'seq', 'at', 'actor', 'channel', 'command', 'reason'} <= set(r) for r in rows))
        self.assertEqual(iv.summary(self.f.ledger, []), [])


class EntryRecordingTests(unittest.TestCase):
    def setUp(self):
        self.f = LedgerFixture(self); self.task = self.f.task()

    def cli(self, module, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = module.main(['--project', str(self.f.project), '--state-root', str(self.f.state_root), *args])
        return code, out.getvalue()

    def test_work_cli_records_mutations_not_reads(self):
        from onecrew import workflow_cli
        with patch.dict(os.environ, {'ONECREW_ACTOR': 'user'}):
            self.assertEqual(self.cli(workflow_cli, 'work', 'status', self.task, '--json')[0], 0)
            self.assertEqual(self.f.events(self.task, 'control.intervention'), [])
            self.assertEqual(self.cli(workflow_cli, 'work', 'pause', self.task, '--json')[0], 0)
            self.assertEqual(self.cli(workflow_cli, 'work', 'cancel', self.task, '--json')[0], 0)
        rows = [e['payload'] for e in self.f.events(self.task, 'control.intervention')]
        self.assertEqual([(r['command'], r['actor'], r['channel']) for r in rows], [('work.pause', 'user', 'cli'), ('work.cancel', 'user', 'cli')])
        code, _ = self.cli(workflow_cli, 'work', 'pause', 'TASK-'+'0'*32, '--json')
        self.assertEqual(code, 2)  # failed command records nothing
        self.assertEqual(len(self.f.events(self.task, 'control.intervention')), 2)

    def test_work_extend_replay_records_one_intervention(self):
        from onecrew import workflow_cli
        budget = self.f.workflow.control.status(self.task)['budget']
        args = ('work', 'extend', self.task, '--revision', budget['revision'], '--request-id', 'more-time', '--max-calls', '9',
                '--deadline', budget['deadline'], '--reason', 'User approved more calls', '--json')
        first, second = self.cli(workflow_cli, *args), self.cli(workflow_cli, *args)  # retry after a timeout
        self.assertEqual((first[0], second[0]), (0, 0)); self.assertEqual(json.loads(first[1]), json.loads(second[1]))
        rows = [e['payload'] for e in self.f.events(self.task, 'control.intervention')]
        self.assertEqual([(r['command'], r['key'], r['reason']) for r in rows], [('work.extend', 'extend:more-time', 'User approved more calls')])

    def test_cli_reply_records_once_and_standalone_task_has_no_continuation(self):
        from onecrew import ledger_cli
        req = self.f.ledger.create_request(self.task, 'q', QUESTION)
        with patch('onecrew.runner.start') as start:
            code, out = self.cli(ledger_cli, 'request', 'reply', req['id'], '--revision', req['revision'], '--choice', 'a', '--json')
            self.assertEqual(code, 0); receipt = json.loads(out)
            self.assertNotIn('continuation', receipt)
            self.cli(ledger_cli, 'request', 'reply', req['id'], '--revision', req['revision'], '--choice', 'a', '--json')
            start.assert_not_called()
        rows = [e['payload'] for e in self.f.events(self.task, 'control.intervention')]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['command'], rows[0]['key'], rows[0]['details']), ('request.reply', receipt['id'], {'request': req['id'], 'choice': 'a'}))

    def test_reply_to_delivery_child_restarts_stopped_root(self):
        from onecrew import ledger_cli
        root = self.f.root('root', 'waiting'); child = self.f.child(root, 'child')
        req = self.f.ledger.create_request(child, 'q', QUESTION)
        with patch('onecrew.runner.status', return_value={'status': 'stopped'}), \
             patch('onecrew.runner.start', return_value={'status': 'alive'}) as start:
            code, out = self.cli(ledger_cli, 'request', 'reply', req['id'], '--revision', req['revision'], '--choice', 'b')
        self.assertEqual(code, 0); self.assertIn('Đã khởi động lại runner task tổng '+root, out)
        start.assert_called_once(); self.assertEqual(start.call_args.args[1], root)
        self.assertEqual(start.call_args.kwargs, {'initiator': 'reply'})
        self.assertEqual(self.f.events(child, 'control.intervention')[0]['payload']['command'], 'request.reply')
        req = self.f.ledger.create_request(root, 'q2', QUESTION)
        # A live runner applies the answer itself; the reply still re-pairs it with a keeper.
        with patch('onecrew.runner.status', return_value={'status': 'alive'}), patch('onecrew.runner.start') as start, \
             patch('onecrew.keeper.ensure', return_value={'status': 'starting'}) as ensure:
            code, out = self.cli(ledger_cli, 'request', 'reply', req['id'], '--revision', req['revision'], '--choice', 'a', '--json')
        start.assert_not_called(); ensure.assert_called_once_with(self.f.ledger.state_root)
        self.assertEqual(json.loads(out)['continuation'], {'task': root, 'status': 'alive', 'started': False, 'keeper': {'status': 'starting'}})

    def test_mcp_mutations_record_source_actor(self):
        from onecrew.mcp_entry import Server
        root = self.f.root('root', 'waiting')
        server = Server(self.f.ledger, True, 'claude-entry')
        server.call('status', {'task': self.task}); server.call('inbox', {'task': self.task})
        self.assertEqual(self.f.events(self.task, 'control.intervention'), [])
        req = self.f.ledger.create_request(root, 'q', QUESTION)
        with patch('onecrew.runner.status', return_value={'status': 'stopped'}), \
             patch('onecrew.runner.start', return_value={'status': 'starting'}) as start:
            receipt = server.call('reply', dict(request=req['id'], revision=req['revision'], choice='a', reference='actual user message'))
        self.assertEqual(receipt['continuation'], {'status': 'starting', 'task': root, 'started': True})
        self.assertEqual(start.call_args.kwargs, {'initiator': 'reply'})
        server.call('cancel', {'task': self.task})
        rows = [(e['task_id'], e['payload']['command'], e['payload']['actor'], e['payload']['channel'])
                for t in (root, self.task) for e in self.f.events(t, 'control.intervention')]
        self.assertEqual(rows, [(root, 'request.reply', 'claude', 'mcp'), (self.task, 'task.cancel', 'claude', 'mcp')])

    def test_mcp_submit_and_resume_record_launch_outcome_and_initiator(self):
        from onecrew.mcp_entry import Server
        from onecrew.owned import Owned
        from onecrew.solution_delivery import Delivery
        server = Server(self.f.ledger, True, 'codex-entry'); owned = self.f.task('owned')
        file = self.f.base/'delivery.json'; file.write_text('{}', encoding='utf-8')
        with patch('onecrew.solution_delivery.submit', return_value={'id': self.task}), \
             patch.object(Delivery, 'enable', return_value={'phase': 'running'}), \
             patch('onecrew.runner.start', return_value={'status': 'starting'}) as start:
            for _ in range(2):  # a replayed submission is one intervention
                self.assertEqual(server.call('delivery_submit', {'file': str(file)})['runner'], {'status': 'starting'})
        self.assertEqual(start.call_args.kwargs, {'initiator': 'codex'})
        with patch('onecrew.owned_intake.submit', return_value={'id': owned}), patch.object(Owned, 'state', return_value=(0, None)), \
             patch.object(Owned, 'enable'), patch('onecrew.runner.start', side_effect=OSError('launch interrupted')):
            self.assertEqual(server.call('submit', {'goal': 'Inspect', 'request_key': 'k'})['runner']['status'], 'unconfirmed')
        self.f.workflow.control.pause(self.task)
        with patch('onecrew.runner.start', side_effect=OSError('launch denied')), self.assertRaises(OSError):
            server.call('resume', {'task': self.task})  # the resume itself happened, so it is still recorded
        self.assertNotEqual(self.f.workflow.control.status(self.task)['status'], 'paused')
        with patch('onecrew.runner.start', return_value={'status': 'alive'}) as start:
            self.assertEqual(server.call('resume', {'task': self.task}), {'status': 'alive'})
        self.assertEqual(start.call_args.kwargs, {'initiator': 'codex'})
        rows = [(e['task_id'], e['payload']['command'], e['payload'].get('key'), e['payload']['details'], e['payload']['actor'], e['payload']['channel'])
                for t in (self.task, owned) for e in self.f.events(t, 'control.intervention')]
        self.assertEqual(rows, [(self.task, 'delivery.submit', 'submit', {'runner': 'starting'}, 'codex', 'mcp'),
                                (self.task, 'task.resume', None, {'runner': 'failed'}, 'codex', 'mcp'),
                                (self.task, 'task.resume', None, {'runner': 'alive'}, 'codex', 'mcp'),
                                (owned, 'job.submit', 'submit', {'runner': 'unconfirmed'}, 'codex', 'mcp')])


if __name__ == '__main__':
    unittest.main()
