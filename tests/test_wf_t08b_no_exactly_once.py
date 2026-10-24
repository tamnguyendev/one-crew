"""T08 [E6] (W37a/W37b): nothing in the run/intent code, its states or its reports claims exactly-once for X.

Criteria grep over the modules that reconcile verifier runs and managed intents and over the pages (report, status): the words
"exactly-once" / "exactly once" / "đúng một lần" may appear only in a sentence that denies the promise ("not promised", "không hứa",
"never claimed"). A sample page produced after a release of a held run is checked the same way.
"""
import re
from pathlib import Path

from onecrew.v2 import verdict
import tests.test_wf_t08a_reconcile as t08a            # the module, not the class: the loader must not run T08a again here

ROOT = Path(__file__).resolve().parents[1]
MODULES = ['onecrew/v2/verdict.py', 'onecrew/v2/managed_executor.py', 'onecrew/common_executor.py', 'onecrew/v2/report.py', 'onecrew/v2/engine.py',
           'onecrew/v2/plan_cli.py']
CLAIM = re.compile(r'exactly[- ]once|đúng một lần|chính xác một lần', re.I)
DENIAL = re.compile(r'not promised|never (promised|claimed)|no exactly|không hứa|không cam kết|is not claimed', re.I)


def claims(text):
    """Sentences that use the exactly-once words without denying the promise."""
    out = []
    for sentence in re.split(r'(?<=[.;:\n])', text):
        if CLAIM.search(sentence) and not DENIAL.search(sentence):
            out.append(sentence.strip()[:160])
    return out


class NoExactlyOnceTests(t08a.ReconcileTests):
    # the fixture of T08a is reused; its own tests are not run a second time here
    for _name in [n for n in dir(t08a.ReconcileTests) if n.startswith('test_')]:
        locals()[_name] = None
    del _name

    def test_e6_code_and_states_never_claim_exactly_once(self):
        for rel in MODULES:
            self.assertEqual(claims((ROOT / rel).read_text(encoding='utf-8')), [], rel)

    def test_e6_the_record_of_a_release_denies_the_promise_and_status_text_does_not_claim_it(self):
        self.plan_with(self.x(then_sleep=False))
        self.fabricate_run('r-b', pid=2 ** 22 + 77, minutes=10)
        verdict._mark(self.ledger, 'r-b', 'dispatched', {'plan': 'P1', 'revision': 1, 'milestone': 'M1', 'kind': 'command', 'at': 'fixture'})
        with self.assertRaises(Exception):
            verdict.run(self.ledger, 'P1', 'M1', self.root)                                  # held (unknown outcome)
        released = verdict.release_run(self.ledger, 'P1', 'r-b', 'checked the marker; a second run is acceptable')
        self.assertEqual(claims(released['note']), [], released['note'])                     # the note names the limit, never the promise
        status = verdict.status(self.ledger, 'P1')
        import json
        self.assertEqual(claims(json.dumps(status, ensure_ascii=False)), [])
        self.assertEqual(claims(json.dumps(self.payloads('verdict.run_held') + self.payloads('verdict.run_reconciled'), ensure_ascii=False)), [])
