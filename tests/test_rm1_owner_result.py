import contextlib
import io
import json
import re
from unittest.mock import patch

from onecrew.v2 import cli, hook_cli, owner_results, plan, tracking_sessions
from tests.test_obs1_tracking import QUESTION
from tests.v2_fixture import Fixture, plan_json


class OwnerResults(Fixture):
    def setUp(self):
        super().setUp()
        self.task = self.propose()['anchor_task']
        self.args = ['--project', str(self.root), '--state-root', str(self.ledger.state_root)]
        self.binding = ['--plan', 'P1', '--revision', '1', '--host', 'claude', '--session', 'waiting']
        self.command('notifications', 'follow-owner', *self.binding)

    def command(self, *args, expected=0):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = cli.main(self.args + list(args))
        self.assertEqual(code, expected, output.getvalue())
        return output.getvalue()

    def approve(self):
        self.command('owner', 'approve', 'P1', '--revision', '1', '--reference', 'fixture', '--human')

    def hook(self, verb='check', session='waiting', tool='one', **extra):
        name = {'check': 'PreToolUse', 'background': 'PostToolUse', 'session': 'SessionStart'}[verb]
        event = dict(session_id=session, cwd=str(self.root), hook_event_name=name, tool_name='Bash',
                     tool_use_id=tool, tool_input={'command': 'pwd'})
        event.update(extra)
        with patch.object(hook_cli, 'read_stdin', return_value=(event, None)):
            return self.command('hook', verb)

    def rows(self):
        return owner_results.status(self.ledger, self.task, 1)

    def test_owner_cli_receipt_visible_without_done(self):
        self.approve()
        self.assertEqual([(r['kind'], r['stage']) for r in self.rows()], [('plan.approved', 'recorded')])
        page = tracking_sessions.page(self.ledger.state_root, 'P1', self.ledger.project_id, None).decode()
        self.assertIn('Đã ghi · chờ phiên nhận', page)
        request = self.ledger.create_request(self.task, 'question', QUESTION)
        self.command('owner', 'answer', request['id'], '--revision', request['revision'], '--choice', 'seven', '--reference', 'fixture')
        notice = self.hook()
        self.assertIn('đã duyệt', notice)
        self.assertIn('seven', notice)
        self.assertNotIn('hunter2', notice)

    def test_next_hook_delivers_once_across_restart(self):
        self.approve()
        self.assertIn('Receipt', self.hook('session'))
        self.assertNotIn('Receipt', self.hook('session'))
        self.assertNotIn('Receipt', self.hook())
        self.assertEqual(self.rows()[0]['stage'], 'delivered')

    def test_wrong_ledger_project_task_revision_or_host_session_ignored(self):
        from onecrew.ledger import Ledger
        self.approve()
        self.assertNotIn('Receipt', self.hook(session='other'))
        self.assertNotIn('Receipt', self.hook(host='other'))
        self.assertNotIn('Receipt', self.hook(agent_id='subagent'))
        doc = plan.show(self.ledger, 'P1')
        scope = owner_results._scope(self.ledger, doc['anchor_task'], 1, 'claude', 'waiting')
        other_project = self.root.parent / 'other-project'
        other_project.mkdir()
        for other in (Ledger(other_project, self.ledger.state_root), Ledger(self.root, self.root.parent / 'other-ledger')):
            self.assertFalse(owner_results._path(other, owner_results._scope(other, self.task, 1, 'claude', 'waiting')).exists())
        for changed in (dict(task='wrong-task'), dict(revision=2)):
            owner_results._opportunity(self.ledger, dict(scope, **changed), {}, self.fail)
        plan.amend(self.ledger, 'P1', plan_json(title='New revision'), 'fixture amendment', 'claude')
        self.assertNotIn('Receipt', self.hook())
        self.assertEqual(self.rows()[0]['stage'], 'recorded')

    def ack(self):
        self.approve()
        receipt = re.search(r'Receipt ([0-9a-f]{64})', self.hook()).group(1)
        command = 'onecrew notifications ack-owner ' + ' '.join(self.binding) + ' --receipt ' + receipt
        self.hook(session='other', tool='wrong-ack', tool_input={'command': command})
        self.command('notifications', 'ack-owner', *self.binding, '--receipt', receipt, expected=2)
        self.hook(tool='ack', tool_input={'command': command})
        self.command('notifications', 'ack-owner', *self.binding, '--receipt', receipt)
        return receipt

    def test_recorded_delivered_acknowledged_and_resumed_distinct(self):
        receipt = self.ack()
        self.assertEqual(self.rows()[0]['stage'], 'acknowledged')
        self.hook('background')  # completion of the tool that got the notice
        self.assertEqual(self.rows()[0]['stage'], 'acknowledged')
        self.hook(tool='work')
        self.hook('background', tool='work')
        self.assertEqual(self.rows()[0]['stage'], 'resumed')
        result = self.command('notifications', 'ack-owner', *self.binding, '--receipt', receipt)
        self.assertEqual(json.loads(result)['stage'], 'resumed')

    def test_supported_continuation_requires_observed_resume(self):
        self.ack()
        self.hook('session', source='resume')
        self.hook(tool='work')
        self.hook('background', session='other', tool='work')
        self.hook('background', tool='unrelated')
        self.assertEqual(self.rows()[0]['stage'], 'acknowledged')
        self.hook('background', tool='work')
        self.assertEqual(self.rows()[0]['stage'], 'resumed')

    def test_idle_or_unsupported_host_stays_pending(self):
        other = ['--plan', 'P1', '--revision', '1', '--host', 'codex', '--session', 'waiting']
        self.assertFalse(json.loads(self.command('notifications','follow-owner', *other))['supported'])
        self.approve()
        self.assertEqual({r['stage'] for r in self.rows()}, {'recorded'})
        self.hook()
        self.assertEqual({r['host']:r['stage'] for r in self.rows()}, {'codex':'recorded','claude':'delivered'})

    def test_refusal_or_unknown_creates_no_success(self):
        self.command('owner', 'approve', 'P1', '--revision', '9', '--reference', 'fixture', expected=2)
        self.assertEqual(self.rows(), [])
        with patch('onecrew.v2.plan_cli.main', return_value=0):
            self.command('owner', 'approve', 'P1', '--reference', 'fixture', '--human', expected=1)
        self.assertEqual(self.rows(), [])

    def test_owner_manual_verdict_and_mode_are_visible_from_committed_receipts(self):
        manual = dict(id='M1', title='Inspect sample', verifier={'type':'owner-manual'}, covers=['O1'])
        plan.amend(self.ledger, 'P1', plan_json(milestones=[manual]), 'fixture manual milestone', 'claude')
        self.command('owner', 'approve', 'P1', '--revision', '2', '--reference', 'fixture')
        self.command('owner', 'enforce', 'P1', '--mode', 'log', '--reference', 'fixture', '--human')
        evidence = self.root.parent / 'owner.txt'
        evidence.write_text('Fixture observation', encoding='utf-8')
        artifact = self.tree()
        message = self.command('owner','record','--plan','P1','--milestone','M1','--artifact-sha',artifact,
                               '--result','pass','--receipt-file',str(evidence),'--reference','fixture','--human')
        self.assertIn('Đã ghi kết quả pass', message)
        self.command('owner','accept','P1','--artifact-sha',artifact,'--reference','fixture','--human')
        rows = owner_results.status(self.ledger, self.task, 2)
        self.assertEqual([r['kind'] for r in rows], ['plan.approved','hook.mode_recorded','verdict.recorded','plan.accepted'])
