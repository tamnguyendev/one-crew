"""Re-entry uses the sealed contract/capabilities, never upgrades old grants."""
import contextlib
import io
import json

from onecrew.ledger import LedgerError
from onecrew.v2 import namespaces, plan, plan_cli
from tests.test_v2_l1 import Fixture, plan_json


class ReentryTests(Fixture):
    def test_cli_declares_engine_and_reentry_does_not_create_or_approve(self):
        body = self.root / 'contract.json'
        body.write_text(json.dumps(plan_json()), encoding='utf-8')
        caps = [*namespaces.DEFAULT_CAPABILITIES, 'internal-plan', 'sequential-engine']
        args = ['--project', str(self.root), '--state-root', str(self.ledger.state_root),
                'plan', 'propose', 'P1', '--file', str(body), '--author', 'codex',
                '--workflow', '--reuse-existing']
        args += [a for c in caps for a in ('--capability', c)]
        for _ in range(2):
            output = io.StringIO()
            with contextlib.redirect_stdout(output): code = plan_cli.main(args)
            self.assertEqual(code, 0, output.getvalue())
            view = json.loads(output.getvalue())
            self.assertEqual(view['capabilities'], caps)
            self.assertEqual(view['status'], 'proposed')
        self.assertEqual(self.kinds().count('plan.proposed'), 1)
        self.assertNotIn('plan.approved', self.kinds())

    def test_approved_reentry_preserves_events_and_rejects_contract_or_capability_changes(self):
        self.approved()
        before = self.events()
        self.assertEqual(plan.propose(self.ledger, 'P1', plan_json(), 'codex', reuse_existing=True)['status'], 'approved')
        for kwargs, body in (({'workflow': True}, plan_json()), ({}, plan_json(title='Changed'))):
            with self.assertRaises(LedgerError):
                plan.propose(self.ledger, 'P1', body, 'codex', reuse_existing=True, **kwargs)
        self.assertEqual(self.events(), before)
