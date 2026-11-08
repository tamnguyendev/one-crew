"""2.5.0.dev11: `plan propose` refuses, before anything is written, what `plan lint` reports as a form refusal and `owner approve` would refuse.

Dogfood 05/11: a contract whose assumption evidence was not a file:line was proposed, lint then flagged it, and the plan had to be amended
before approval. The refusal now comes at propose, with the same codes lint prints; nothing (anchor, revision file, event) is left behind.
"""
from onecrew.ledger import LedgerError
from onecrew.v2 import lint, plan as plans
from tests.test_v2_l1 import PY, Fixture, milestone, plan_json


def codes(text):
    return [line.split(']')[0].split('[')[1] for line in str(text).splitlines() if line.startswith(' - [')]


class ProposeFormTests(Fixture):
    def nothing_written(self, name='P1'):
        with self.ledger.transaction() as conn:                                 # None: the ledger file was not even created
            rows = 0 if conn is None else conn.execute("SELECT count(*) FROM tasks WHERE request_key LIKE ?", ('%' + name,)).fetchone()[0]
        self.assertEqual(rows, 0)
        self.assertEqual(list((self.ledger.state_root / 'plans').rglob('v1.json')) if (self.ledger.state_root / 'plans').exists() else [], [])

    def refused_like_lint(self, value, expected):
        found = [c for c, _ in lint.lint(lint.ReadOnlyLedger(self.root, self.ledger.state_root), value)]
        self.assertIn(expected, found)
        with self.assertRaises(LedgerError) as caught:
            plans.propose(self.ledger, 'P1', value, 'claude-opus-5-5')
        self.assertIn(expected, codes(caught.exception))
        self.assertIn('plan lint', str(caught.exception))
        self.nothing_written()

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
        self.refused_like_lint(plan_json(decisions=[]), 'origin_missing')                 # an empty new field opts the contract in (C-rules)
        with self.assertRaises(LedgerError) as caught:
            plans.propose(self.ledger, 'P1', plan_json(decisions=[]), 'claude-opus-5-5')
        self.assertEqual(codes(caught.exception), ['origin_missing', 'item_without_source'])

    def test_a_clean_contract_still_proposes_and_approval_only_rules_stay_at_approve(self):
        plans.propose(self.ledger, 'P1', plan_json(), 'claude-opus-5-5')
        value = plan_json(); value['understanding']['confidence'] = 'low'      # not a form rule: approve refuses it, propose does not
        plans.propose(self.ledger, 'P2', value, 'claude-opus-5-5')
        with self.assertRaises(LedgerError) as caught:
            plans.approve(self.ledger, 'P2', 'owner', 'fixture')
        self.assertIn('confidence_low', codes(caught.exception))

    def test_a_non_model_author_is_still_only_a_lint_note(self):
        plans.propose(self.ledger, 'P1', plan_json(), 'claude')                # author_not_model_id is lint's, approve does not refuse it
