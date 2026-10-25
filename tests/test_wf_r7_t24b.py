"""T24b (R05, round 7) [E4]: the handover lists exactly the open findings of the root's register.

Real ledger, real reviewer verifier and register; the provider call is scripted (no model). The first review fails R1 and R2, so the
register opens F1 (R1) and F2 (R2); the second review passes both and only F2 is closed with its receipt. The handover's open-finding
section must be exactly {F1}, its row carrying the ID, the criterion and the artifact; F2 must not appear in that section. The
counter-example "the report does not read the register" (report._open_findings patched to an empty list) turns the check red.
"""
import json
from unittest.mock import patch

from onecrew.v2 import findings, plan as plans, report, verdict
from onecrew.v2.verifiers import reviewer
from tests.test_v2_l1 import Fixture, plan_json
from tests.test_v2_reviewer import reviewer_milestone

OPEN_PREFIX = 'Finding còn mở: '


def open_section(text):
    return [line.strip() for line in text.splitlines() if OPEN_PREFIX in line]


def e4_holds(text, f1, f2):
    rows = [r for r in open_section(text) if not r.endswith('0 theo sổ finding của root.')]
    named = [r for r in rows if (' ' + f1['id'] + ' ') in r + ' ' or (' ' + f2['id'] + ' ') in r + ' ']
    if len(named) != 1 or f1['id'] not in named[0] or f2['id'] in ' '.join(rows):
        return False
    row = named[0]
    return ('tiêu chí ' + f1['criterion']) in row and ('artifact ' + f1['artifact_sha'][:7]) in row


class T24bHandoverFindingsTests(Fixture):
    def setUp(self):
        super().setUp()
        value = plan_json(milestones=[dict(reviewer_milestone(), mode='until_pass', max_repairs=3)])
        plans.propose(self.ledger, 'P1', value, 'codex', workflow=True)
        plans.approve(self.ledger, 'P1', 'owner', 'fixture owner approval')
        (self.root / 'a.txt').write_text('one\ntwo\n')
        self.results = ['fail', 'pass']
        fake = patch.object(reviewer, 'call', side_effect=self.provider)
        fake.start(); self.addCleanup(fake.stop)

    def provider(self, prompt, config, env, scratch, limit):
        result = self.results.pop(0)
        answer = {'criteria': [{'id': c['id'], 'verdict': result, 'evidence': [{'file': 'a.txt', 'line': 2, 'note': 'observed line two'}]}
                               for c in config['criteria']], 'outside_criteria': []}
        return json.dumps(answer), {}, None, False, b''

    def handover(self):
        return report.render_handover(self.ledger.state_root, 'P1', project_id=self.ledger.project_id)

    def test_e4_handover_lists_exactly_the_open_register_finding_and_not_the_closed_one(self):
        verdict.run(self.ledger, 'P1', 'M1')
        opened = {f['criterion']: f for f in findings.list_findings(self.ledger, 'P1', open_only=True)}
        self.assertEqual(set(opened), {'R1', 'R2'})
        f1, f2 = opened['R1'], opened['R2']
        (self.root / 'a.txt').write_text('one\ntwo\nrepaired\n')
        verdict.run(self.ledger, 'P1', 'M1')
        with self.ledger.transaction() as conn:
            task = plans.derive(self.ledger, conn, 'P1')['task_id']
        latest = [p for k, p in ((e['kind'], e['payload']) for e in self.ledger.events(task)) if k == 'verdict.recorded'][-1]
        findings.resolve(self.ledger, 'P1', f2['id'], latest['receipt'], reason='R2 rechecked', artifact_sha=latest['artifact_sha'])
        register = findings.list_findings(self.ledger, 'P1', open_only=True)
        self.assertEqual([f['id'] for f in register], [f1['id']])
        text = self.handover()
        self.assertTrue(e4_holds(text, f1, f2), open_section(text))
        # counter-example: the report does not read the register
        with patch.object(report, '_open_findings', lambda f: []):
            mutant = self.handover()
        self.assertFalse(e4_holds(mutant, f1, f2), open_section(mutant))


if __name__ == '__main__':
    import unittest
    unittest.main()
