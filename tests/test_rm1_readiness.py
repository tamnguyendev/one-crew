import contextlib
import io
import json
import os
from pathlib import Path
from unittest.mock import patch

from onecrew import cli
from onecrew.v2 import active_plan, hook_cli, install, plan, tracking
from tests.test_v2_advisor import AUTHOR, sourced, size_m
from tests.v2_fixture import Fixture, plan_json


class Readiness(Fixture):
    def call(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), *args])
        return code, out.getvalue()

    def doctor(self):
        with patch.dict(os.environ, {'ONECREW_LANG': 'vi'}):
            return next((level, detail) for level, name, detail in
                        install.doctor_facts(self.root, self.ledger.state_root, claude=None)
                        if name == install.t('doctor.plan'))

    def write_export(self, **changes):
        for path in (active_plan.project_file(self.root), hook_cli.state_copy(self.ledger.state_root, self.root)):
            body = json.loads(path.read_text(encoding='utf-8'))
            path.write_text(json.dumps(dict(body, **changes)), encoding='utf-8')

    def test_accepted_ledger_overrides_old_export(self):
        self.approved()
        with self.ledger.transaction(write=True) as conn:
            state = plan.derive(self.ledger, conn, 'P1')
            plan.emit(self.ledger, conn, state['task_id'], 'plan.accepted',
                      {'revision': 1, 'sha': state['approved']['sha'], 'artifact_sha': self.tree()})
        self.assertIn('đã nghiệm thu', self.doctor()[1])

    def test_expired_enforce_explains_block_and_refresh(self):
        self.approved()
        self.write_export(mode='enforce', expires='2020-01-01T00:00:00+00:00')
        level, text = self.doctor()
        self.assertEqual(level, 'FAIL')
        for term in ('hết hạn', '2020-01-01', 'chặn lệnh ghi', 'hook export P1'):
            self.assertIn(term, text)

    def test_stopped_closed_and_pending_revision_reported(self):
        self.approved()
        plan.amend(self.ledger, 'P1', plan_json(title='Two'), 'title', 'codex')
        self.assertIn('bản 2 đang chờ duyệt', self.doctor()[1])
        for status in ('closed', 'stopped_with_report'):
            with self.subTest(status=status):
                level, text = install._plan_readiness(dict(plan='Separate', revision=1, mode='enforce', status=status),
                                                      self.root, self.ledger.state_root)
                self.assertEqual(level, 'WARN')
                self.assertIn(status, text)

    def test_approved_active_is_ready(self):
        self.approved()
        active_plan.project_file(self.root).unlink()
        level, detail = self.doctor()
        self.assertEqual(level, 'PASS')
        self.assertIn('P1 bản 1', detail)
        self.assertFalse(active_plan.project_file(self.root).exists())

    def test_user_hook_reports_missing_observation_coverage_once(self):
        with patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': self.temp.name, 'ONECREW_LANG': 'en'}):
            rows = install.doctor_facts(self.root, self.ledger.state_root, claude=None)
            hook = [(level, detail) for level, name, detail in rows if name == install.t('doctor.user')]
        self.assertEqual(len(hook), 1)
        self.assertEqual(hook[0][0], 'WARN')
        self.assertIn(f'0/{len(install.OBSERVE_EVENTS)}', hook[0][1])
        self.assertIn('install --observe', hook[0][1])

    def test_ai_can_read_approve_and_accept_syntax_without_writes(self):
        self.propose()
        before = self.events()
        with patch.dict(os.environ, {'CLAUDE_CODE_CHILD_SESSION': '1'}):
            for verb, flag in [('approve', '--choose'), ('accept', '--artifact-sha')]:
                for args in [('owner', verb, '--help'), ('owner', 'help', verb)]:
                    code, text = self.call(*args)
                    self.assertEqual(code, 0)
                    self.assertIn(flag, text)
                    self.assertIn('--reference', text)
        self.assertEqual(before, self.events())

    def test_owner_mutation_still_refused_in_ai(self):
        self.propose()
        before = self.events()
        with patch.dict(os.environ, {'ONECREW_ACTOR': 'codex'}):
            code, text = self.call('owner', 'approve', 'P1', '--reference', 'fixture')
        self.assertEqual(code, 2)
        self.assertIn('refused', text)
        self.assertEqual(before, self.events())

    def test_lint_and_propose_show_required_advice_only(self):
        for name, value, required in [('small', sourced(plan_json()), False), ('medium', sourced(size_m()), True)]:
            with self.subTest(name=name):
                path = Path(self.temp.name) / 'proposal.json'
                path.write_text(json.dumps(value), encoding='utf-8')
                args = ['--file', str(path), '--author', AUTHOR]
                code, text = self.call('plan', 'lint', *args)
                self.assertEqual(code, 0, text)
                self.assertEqual('advice_required' in text, required)
                code, text = self.call('plan', 'propose', name, *args)
                self.assertEqual(code, 0, text)
                self.assertEqual('next_step' in json.loads(text), required)

    def test_step0_lists_missing_advice_and_choice_in_vietnamese(self):
        self.propose(value=sourced(size_m()))
        code, text = self.call('owner', 'approve', 'P1', '--reference', 'fixture', '--human')
        self.assertNotEqual(code, 0)
        for term in ('Chưa duyệt', 'onecrew plan advise P1', 'Chủ chọn', '--choose'):
            self.assertIn(term, text)
        self.assertNotIn('Chưa xác nhận được', text)
        card = next(n for n in tracking.detail(self.ledger.state_root, 'P1')['needs_user'] if n['kind'] == 'approve')
        self.assertIn('plan advise', card['reason'])
        self.assertIsNone(card['reply_command'])

    def test_unknown_outcome_stays_unknown(self):
        self.propose()
        with patch('onecrew.v2.plan_cli.main', return_value=0):
            code, text = self.call('owner', 'approve', 'P1', '--reference', 'fixture', '--human')
        self.assertNotEqual(code, 0)
        self.assertIn('Chưa xác nhận được', text)
