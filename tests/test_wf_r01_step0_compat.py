"""R01 step-0 events against the REAL old binary (archive of ee46539, unmodified; tests/wf_oldversion.py).

The new kinds written on a `plan:` anchor must be class 0/A and leave the old version's S (status), G (gate) and C (continue) unchanged:
  * `proposal.checked` (W47) - ok, refused and survey_first results;
  * the decision card (W30a) - a `request.created` (class 0) carrying a `v2.decision_card` action, and the HD-05 `decision.recorded` record.
The legacy root is built by the unmodified OLD binary, then current step-0 code
writes neutral events on a COPY; the old binary reads both copies.
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

from onecrew.ledger import Ledger
from onecrew.v2 import cards, compat, plan as plans, step0
import tests.wf_oldversion as ov

REPO = str(Path(__file__).resolve().parents[1])
BASELINE = 'ee46539'
REQUIREMENT = {'acceptance': [{'id': 'A1', 'text': 'The sample is removed', 'semantic': {'removal': 'permanent'}}], 'constraints': [], 'dependencies': []}


def proposal_ok():
    return {'preferred': {'id': 'P1', 'summary': 'Delete the sample file', 'before': 'The sample file exists.', 'after': 'The sample file is gone.',
                          'rationale': 'One deletion meets the acceptance and touches nothing else.',
                          'changes': [{'id': 'X1', 'title': 'Delete a.txt', 'kind': 'delete', 'entries': ['storage'], 'links': ['A1'], 'target': 'a.txt'}]},
            'covers': ['A1'], 'in_authority': True}


def _have_git():
    try:
        subprocess.run(['git', '--version'], capture_output=True, check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


@unittest.skipUnless(_have_git(), 'git is required to archive the old version')
class OldVersionReadsStep0EventsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs = ov._short_runs()
        cls.old = ov.OldVersion(ov.archive(BASELINE, REPO, cls.runs))
        cls.proj = ov.git_project(cls.runs, 'P1')
        cls.base = cls.runs / 'state-base'
        contract_file = cls.runs / 'legacy-r1.json'
        contract_file.write_text(json.dumps(ov.contract('R01 step 0')), encoding='utf-8')
        code, out = cls.old.run(cls.proj, cls.base, 'plan', 'propose', 'r1', '--file', str(contract_file), '--author', 'claude-probe')
        if code: raise AssertionError(out)
        cls.pid = ov.project_id(cls.base, cls.proj)
        cls.task = ov.anchor_id(cls.base, cls.pid, 'plan:r1')
        ov.make_approved(cls.base, cls.task, 'r1')
        cls.before = ov.read(cls.old, cls.proj, cls.base, 'r1')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.runs, ignore_errors=True)

    def copy(self, tag):
        state = self.runs / tag
        shutil.copytree(self.base, state)
        return state, Ledger(self.proj, state)

    def assert_same_for_old(self, state):
        after = ov.read(self.old, self.proj, state, 'r1')
        diff = ov.compare(self.before, after)
        self.assertTrue(diff['S'], f"S changed: {self.before['S']} vs {after['S']}")
        self.assertTrue(diff['G'], 'G changed'); self.assertTrue(diff['C'], 'C changed')
        self.assertFalse(after['read_blocked'])

    def test_proposal_checked_is_class_a_and_the_old_version_reads_the_same(self):
        self.assertEqual(compat.event_class('proposal.checked'), 'A')
        state, ledger = self.copy('proposal')
        results = [step0.review_proposal(ledger, 'r1', REQUIREMENT, proposal_ok())['result'],
                   step0.review_proposal(ledger, 'r1', REQUIREMENT, dict(proposal_ok(), covers=[]))['result'],
                   step0.review_proposal(ledger, 'r1', REQUIREMENT, {'unknowns': [{'id': 'U1', 'question': 'Used elsewhere?', 'affected': ['A1'],
                                                                                 'required_by': 'option_choice', 'status': 'open'}]})['result']]
        self.assertEqual(results, ['ok', 'refused', 'survey_first'])
        self.assertEqual(ov.kinds_on(state, self.task).count('proposal.checked'), 3)
        self.assert_same_for_old(state)

    def test_a_decision_card_and_hd05_record_do_not_change_what_the_old_version_reads(self):
        state, ledger = self.copy('card')
        choices = [{'id': 'B1', 'class': 'business', 'problem': 'Keep or delete the old CSV export?', 'options': [{'id': 'keep', 'label': 'Keep'}, {'id': 'delete', 'label': 'Delete'}],
                    'recommendation': 'keep', 'evidence': ['a.txt:1'], 'scope': 'plan r1', 'decide_by': 'before_approve'},
                   {'id': 'T1', 'class': 'technical', 'problem': 'Helper style?', 'options': [{'id': 'a', 'label': 'Inline'}, {'id': 'b', 'label': 'Module'}],
                    'recommendation': 'a', 'evidence': ['a.txt:1'], 'scope': 'plan r1', 'decide_by': 'before_start',
                    'authority': {'grant_id': 'G-01', 'revision': 'rev-1'}}]
        out = cards.present(ledger, 'r1', choices, {'component': 'step0', 'model': 'claude-sonnet-5-5'})
        self.assertTrue(out['request']); kinds = ov.kinds_on(state, self.task)
        self.assertIn('request.created', kinds); self.assertIn('decision.recorded', kinds)
        self.assert_same_for_old(state)


if __name__ == '__main__':
    unittest.main()
