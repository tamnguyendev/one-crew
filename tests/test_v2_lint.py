"""v2.1 job 11a, item 1: `plan lint` lists what propose + approve would refuse for in the FORM of a contract, and writes nothing."""
import contextlib
import copy
import hashlib
import io
import json
import sys
from pathlib import Path

from onecrew.ledger import Ledger, LedgerError
from onecrew.v2 import lint, plan_cli, plan as plans
from tests.test_v2_l1 import PY, Fixture, milestone, plan_json


def codes(reasons):
    return [code for code, _ in reasons]


class LintTests(Fixture):
    def lint(self, value, author=None):
        return lint.lint(lint.ReadOnlyLedger(self.root, self.ledger.state_root), value, author)

    def with_assumption(self, evidence):
        value = plan_json()
        value['understanding']['assumptions'] = [{'text': 'The file is there.', 'evidence': evidence}]
        return value

    def test_a_clean_contract_has_no_reasons_and_the_model_id_author_passes(self):
        self.assertEqual(self.lint(plan_json(), 'claude-opus-5-5'), [])
        self.assertEqual(self.lint(plan_json()), [])                       # no --author: not checked

    def test_text_over_the_limit_is_its_own_reason(self):
        reasons = self.lint(plan_json(title='x' * 201))
        self.assertEqual(codes(reasons), ['text_over_limit']); self.assertIn('title', reasons[0][1])
        value = plan_json(); value['output'] = ['y' * 501]
        self.assertEqual(codes(self.lint(value)), ['text_over_limit'])

    def test_a_schema_error_is_reported_with_the_validate_message(self):
        reasons = self.lint(plan_json(status='approved'))
        self.assertEqual(codes(reasons), ['schema']); self.assertIn('unknown fields', reasons[0][1])

    def test_assumption_evidence_must_point_inside_the_project_at_a_real_line(self):
        for evidence, words in (('../outside.py:1', 'outside the project'), ('gone.py:3', 'not a file'), ('a.txt:99', 'line 99')):
            reasons = self.lint(self.with_assumption(evidence))
            self.assertEqual(codes(reasons), ['assumption_evidence_invalid'], evidence); self.assertIn(words, reasons[0][1])
        self.assertEqual(self.lint(self.with_assumption('a.txt:1')), [])

    def test_a_target_path_that_does_not_exist_is_reported(self):
        value = plan_json(); value['understanding']['target']['paths'] = ['a.txt', 'missing.txt']
        reasons = self.lint(value)
        self.assertEqual(codes(reasons), ['target_path']); self.assertIn('missing.txt', reasons[0][1])

    def test_an_author_that_is_not_a_model_id_is_reported_and_the_owner_is_not_one_to_check(self):
        self.assertEqual(codes(self.lint(plan_json(), 'bob')), ['author_not_model_id'])
        self.assertEqual(self.lint(plan_json(), 'owner'), [])

    def test_an_argv_element_with_a_control_character_is_reported_in_milestones_and_preconditions(self):
        value = plan_json(milestones=[milestone('M1', [PY, '-c', 'print(1)\x07'])])
        value['preconditions'] = [{'id': 'P2', 'check': 'command_ok', 'args': {'argv': [PY, '-c', 'pass\x1b']}, 'why': 'the interpreter starts'}]
        reasons = self.lint(value)
        self.assertEqual(codes(reasons), ['argv_control_char', 'argv_control_char'])
        self.assertIn('milestone M1', reasons[0][1]); self.assertIn('precondition P2', reasons[1][1])

    def test_a_control_character_that_validate_also_refuses_is_still_listed_with_it(self):
        reasons = self.lint(plan_json(milestones=[milestone('M1', [PY, '-c', 'print(1)\nprint(2)'])]))
        self.assertEqual(codes(reasons), ['argv_control_char', 'schema'])        # every reason at once, not the first

    def test_strict_mode_by_the_rules_file_wants_origin_and_item_sources(self):
        self.assertEqual(self.lint(plan_json()), [])                             # legacy: no rules file, no new fields
        rules = Path(self.ledger.state_root) / 'plans' / 'owner-rules.md'
        rules.parent.mkdir(parents=True); rules.write_text('# rules\n', encoding='utf-8')
        reasons = self.lint(plan_json())
        self.assertEqual(codes(reasons), ['origin_missing', 'item_without_source'])
        origin = {'by': 'owner', 'at': '2026-10-19', 'quote': 'Do the sample.'}
        sourced = plan_json(origin=origin, items=[dict(i, source='origin') for i in plan_json()['items']])
        self.assertEqual(self.lint(sourced), [])
        bad = copy.deepcopy(sourced); bad['items'][0]['source'] = 'D2'
        bad['decisions'] = [{'id': 'D1', 'choice': 'a', 'alternative': 'b', 'cost': 'c'}]
        self.assertEqual(codes(self.lint(bad)), ['unknown_decision'])

    def test_strict_mode_by_a_new_field_needs_no_rules_file(self):
        origin = {'by': 'owner', 'at': '2026-10-19', 'quote': 'Do the sample.'}
        self.assertEqual(codes(self.lint(plan_json(origin=origin))), ['item_without_source'])

    def test_reasons_that_belong_to_approval_are_not_lint(self):
        value = plan_json(); value['understanding']['confidence'] = 'low'
        value['understanding']['unknowns'] = [{'id': 'U1', 'question': 'Is it so?', 'status': 'open'}]
        self.assertEqual(self.lint(value), [])


class LintWritesNothingTests(Fixture):
    def snapshot(self):
        state = Path(self.ledger.state_root)
        files = {str(p.relative_to(state)): (p.stat().st_size, p.stat().st_mtime_ns) for p in sorted(state.rglob('*')) if p.is_file()} if state.exists() else None
        ledger = hashlib.sha256((state / 'ledger.sqlite3').read_bytes()).hexdigest() if (state / 'ledger.sqlite3').exists() else None
        project = {str(p.relative_to(self.root)): p.stat().st_mtime_ns for p in sorted(self.root.rglob('*')) if p.is_file() and '.git' not in p.parts}
        return files, ledger, project

    def cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = plan_cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'plan', 'lint', *argv])
        return code, out.getvalue()

    def file(self, value):
        path = Path(self.temp.name) / 'contract.json'
        path.write_text(json.dumps(value), encoding='utf-8')
        return str(path)

    def test_the_ledger_handle_of_lint_refuses_a_write(self):
        reader = lint.ReadOnlyLedger(self.root, self.ledger.state_root)
        with self.assertRaises(LedgerError) as caught:
            with reader.transaction(write=True): pass
        self.assertIn('read-only', str(caught.exception))

    def test_lint_leaves_the_state_root_and_the_project_as_they_were_with_and_without_a_ledger(self):
        path = self.file(plan_json(title='x' * 201))
        before = self.snapshot()
        self.assertIsNone(before[0]); self.assertIsNone(before[1])                  # no state root yet: lint must not create one
        self.assertEqual(self.cli('--file', path)[0], 1)
        self.assertEqual(self.snapshot(), before)
        self.propose('P1')                                                            # a real ledger with a plan in it
        before = self.snapshot(); events = self.kinds()
        self.assertEqual(self.cli('--file', self.file(plan_json()), '--author', 'claude-opus-5-5')[0], 0)
        self.assertEqual(self.cli('--file', self.file(plan_json()), '--author', 'bob')[0], 1)
        self.assertEqual(self.snapshot(), before); self.assertEqual(self.kinds(), events)

    def test_exit_codes_and_output_lines(self):
        code, text = self.cli('--file', self.file(plan_json()))
        self.assertEqual((code, text.strip()), (0, 'lint: clean'))
        value = plan_json(title='x' * 201); value['understanding']['target']['paths'] = ['missing.txt']
        code, text = self.cli('--file', self.file(value), '--author', 'bob')
        lines = text.strip().splitlines()
        self.assertEqual(code, 1); self.assertEqual([line.split(']')[0] for line in lines], ['[author_not_model_id', '[text_over_limit'])
        code, text = self.cli('--file', str(Path(self.temp.name) / 'nope.json'))
        self.assertEqual(code, 2); self.assertIn('error', json.loads(text))

    def test_lint_agrees_with_propose_on_what_it_refuses(self):
        for value in (plan_json(title='x' * 201), plan_json(status='approved')):
            self.assertTrue(lint.lint(lint.ReadOnlyLedger(self.root, self.ledger.state_root), value))
            with self.assertRaises(LedgerError): plans.propose(self.ledger, 'Q' + str(id(value)), value, 'claude')
