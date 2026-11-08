"""2.5.0.dev11: the `plan propose` command refuses, before anything is written, what `plan lint` reports as a form refusal and
`owner approve` would refuse.

Dogfood 05/11: a contract whose assumption evidence was not a file:line was proposed, lint then flagged it, and the plan had to be amended
before approval. The command now refuses at propose, with the same codes lint prints; nothing (anchor, revision file, event) is left behind.
The library function `plan.propose` keeps its behaviour (approve stays the gate for its other callers, for plans recorded before dev11 and
for plan amend); the frozen approve-gate tests are unchanged.
"""
import contextlib
import io
import json

from onecrew.ledger import LedgerError
from onecrew.v2 import cli, lint, plan as plans
from tests.test_v2_l1 import PY, Fixture, milestone, plan_json


def codes(text):
    return [line.split(']')[0].split('[')[1] for line in str(text).splitlines() if line.startswith(' - [')]


class ProposeFormTests(Fixture):
    def command(self, name, value, author='claude-opus-5-5'):
        path = self.root.parent / (name + '.json')
        path.write_text(json.dumps(value), encoding='utf-8')
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root),
                             'plan', 'propose', name, '--file', str(path), '--author', author])
        return code, out.getvalue()

    def nothing_written(self, name='P1'):
        with self.ledger.transaction() as conn:                                 # None: the ledger file was not even created
            rows = 0 if conn is None else conn.execute("SELECT count(*) FROM tasks WHERE request_key LIKE ?", ('%' + name,)).fetchone()[0]
        self.assertEqual(rows, 0)
        plans_dir = self.ledger.state_root / 'plans'
        self.assertEqual(list(plans_dir.rglob('v1.json')) if plans_dir.exists() else [], [])

    def refused_like_lint(self, value, expected):
        found = [c for c, _ in lint.lint(lint.ReadOnlyLedger(self.root, self.ledger.state_root), value)]
        self.assertIn(expected, found)
        code, text = self.command('P1', value)
        self.assertNotEqual(code, 0, text)
        error = json.loads(text)['error']
        self.assertIn(expected, codes(error)); self.assertIn('plan lint', error)
        self.nothing_written()
        return error

    def test_assumption_evidence_that_is_not_a_file_line_is_refused_at_propose(self):
        value = plan_json()
        value['understanding']['assumptions'] = [{'text': 'The file is there.', 'evidence': 'onecrew/v2/owner_cli.py:66'}]
        self.refused_like_lint(value, 'assumption_evidence_invalid')

    def test_a_missing_target_path_is_refused_at_propose(self):
        value = plan_json(); value['understanding']['target']['paths'] = ['a.txt', 'missing.txt']
        self.refused_like_lint(value, 'target_path')

    def test_an_argv_control_character_is_refused_at_propose(self):
        self.refused_like_lint(plan_json(milestones=[milestone('M1', [PY, '-c', 'print(1)\x07'])]), 'argv_control_char')

    def test_provenance_reasons_of_an_opted_in_contract_are_refused_at_propose(self):
        error = self.refused_like_lint(plan_json(decisions=[]), 'origin_missing')           # an empty new field opts the contract in
        self.assertEqual(codes(error), ['origin_missing', 'item_without_source'])

    def test_a_clean_contract_still_proposes_and_approval_only_rules_stay_at_approve(self):
        self.assertEqual(self.command('P1', plan_json())[0], 0)
        value = plan_json(); value['understanding']['confidence'] = 'low'      # not a form rule: approve refuses it, propose does not
        self.assertEqual(self.command('P2', value)[0], 0)
        with self.assertRaises(LedgerError) as caught:
            plans.approve(self.ledger, 'P2', 'owner', 'fixture')
        self.assertIn('confidence_low', codes(caught.exception))

    def test_a_non_model_author_is_still_only_a_lint_note(self):
        self.assertEqual(self.command('P1', plan_json(), author='claude')[0], 0)           # author_not_model_id is lint's

    def test_the_library_keeps_approve_as_the_gate(self):
        value = plan_json(); value['understanding']['target']['paths'] = ['a.txt', 'missing.txt']
        plans.propose(self.ledger, 'P1', value, 'claude-opus-5-5')                          # recorded, as before dev11
        with self.assertRaises(LedgerError) as caught:
            plans.approve(self.ledger, 'P1', 'owner', 'fixture')
        self.assertIn('target_path', codes(caught.exception))
        with self.assertRaises(LedgerError) as caught:
            plans.propose(self.ledger, 'P2', value, 'claude-opus-5-5', check_form=True)
        self.assertIn('target_path', codes(caught.exception))
