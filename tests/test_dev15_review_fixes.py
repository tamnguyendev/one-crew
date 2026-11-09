"""2.5.0.dev15 — fourth independent review (Kiro CLI, 09/11; BAO-CAO-REVIEW-dev14.md, verdict FAIL) on 3662b47. Every test here is red on 3662b47.

P1 (#9)  a reviewer criterion changed in punctuation or in a literal ("safe-mode" -> "safe mode") was shown as "wording or added checks only";
         reordered criteria were not seen. Now only a change of white space is harmless.
P2 (#2)  failures before the verifier still lacked verifier_started=False: a bad snapshot setting, the port before adapter.run (deadline, evidence),
         the reviewer before the model call (environment, scratch directory).
P2 (#4)  the checkout still read .git/info/attributes and core.attributesFile (repository or global config).
P2       plain words: "docs/", "-v", "report.pdf" passed without even a warning. Owner 09/11 (two levels): a warning, not a refusal.
P3       reuse and a repeated approve dropped the warnings.
"""
import copy
import datetime as dt
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))          # test_v2_reviewer imports test_v2_l1 by its plain name

from onecrew.ledger import LedgerError
from onecrew.v2 import acceptance_diff as ad, contract as contracts, lint, plan as plans, verdict
from onecrew.v2.verifiers import command, port, reviewer
from tests import test_dev11_owner_view as dev11          # the module, not its classes: their tests would run again here
from tests.test_dev13_review_fixes import MEDICAL
from tests.test_v2_l1 import Fixture, plan_json
from tests.test_v2_reviewer import ReviewerFixture, answer, row
from tests.test_wf_rx2_adapters import DATA, milestone as port_milestone

CRITERION = 'Does config contain "safe-mode"? fail if it does not.'


def reviewer_contract(criteria):
    return plan_json(milestones=[{'id': 'M1', 'title': 'Review', 'covers': ['O1'], 'verifier': {'type': 'reviewer', 'config': {
        'provider': 'claude', 'model': 'claude-haiku-5-5', 'criteria': criteria, 'max_minutes': 5}}}])


class CriteriaAreReadCharacterByCharacter(Fixture):
    """P1: a reviewer looks for what its question says; any character but white space changed is a change the owner approves."""
    def classify(self, before, after):
        return ad.classify_contract(reviewer_contract(before), reviewer_contract(after))

    def test_a_literal_or_punctuation_changed_is_acceptance(self):
        for new in ('Does config contain "safe mode"? fail if it does not.', 'Does config contain safe-mode? fail if it does not.',
                    'Does config contain "Safe-mode"? fail if it does not.', 'Does config contain "safe-mode"; fail if it does not.'):
            with self.subTest(new=new):
                result = self.classify([{'id': 'R1', 'question': CRITERION}], [{'id': 'R1', 'question': new}])
                self.assertTrue(result['acceptance_changed'], result)
                self.assertNotEqual(result['summary'], 'wording or added checks only')

    def test_white_space_only_stays_routine(self):
        result = self.classify([{'id': 'R1', 'question': CRITERION}], [{'id': 'R1', 'question': '  Does config contain "safe-mode"?\n fail if  it does not. '}])
        self.assertFalse(result['acceptance_changed'], result); self.assertEqual([c['kind'] for c in result['changes']], ['wording'])

    def test_reordered_criteria_are_acceptance_and_an_added_one_stays_routine(self):
        a, b = {'id': 'R1', 'question': CRITERION}, {'id': 'R2', 'question': 'Is b.txt untouched? fail if it changed.'}
        self.assertTrue(self.classify([a, b], [b, a])['acceptance_changed'])
        added = self.classify([a], [a, b])
        self.assertFalse(added['acceptance_changed'], added); self.assertEqual([c['kind'] for c in added['changes']], ['added_check'])


class BeforeTheVerifierEverywhere(ReviewerFixture):
    """P2 (#2): no verifier, adapter or model was called, so the failure says so and verdict.run runs again without release-run."""
    def test_a_bad_snapshot_setting_says_the_command_did_not_start(self):
        plans.propose(self.ledger, 'P1', plan_json(), 'claude'); plans.approve(self.ledger, 'P1', 'owner', 'fixture')
        milestone = contracts.validate(plan_json())['milestones'][0]
        with patch.dict(os.environ, {command.SNAPSHOT_ENV: 'abc'}), self.assertRaises(LedgerError) as caught:
            command.run(self.ledger, 'P1', 1, 'x' * 64, milestone, self.root)
        self.assertIs(getattr(caught.exception, 'verifier_started', None), False)

    def test_the_port_before_its_adapter_says_it_did_not_start(self):
        source = Path(self.temp.name) / 'port-source'; source.mkdir()
        for name in ('input.csv', 'output.csv'):
            (source / name).write_text('id,amount\n1,10.00\n2,5.50\n', encoding='utf-8')
        m = port_milestone('data', port.normalize('data', copy.deepcopy(DATA), 'test'))
        past = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)).isoformat()
        called = []
        adapter = port.get('data')
        with patch.object(adapter, 'run', side_effect=lambda *a, **k: called.append(1)), self.assertRaises(LedgerError) as caught:
            port.run(self.ledger, 'P1', 1, 'a' * 64, m, source, deadline=past)
        self.assertEqual(called, []); self.assertIs(getattr(caught.exception, 'verifier_started', None), False)

    def test_the_reviewer_before_the_model_says_it_did_not_start_and_runs_again(self):
        real = tempfile.mkdtemp

        def no_review_scratch(*a, **k):                  # only the reviewer's own scratch directory; the snapshots before it still work
            if k.get('prefix') == 'ocr-': raise OSError(13, 'Access is denied')
            return real(*a, **k)

        for target, error, effect in ((reviewer.tempfile, 'mkdtemp', no_review_scratch), (reviewer.command, 'verifier_env', OSError(13, 'Access is denied'))):
            with self.subTest(step=error):
                self.tearDown_plan()
                self.start(); self.reply(answer(row('R1'), row('R2')))
                with patch.object(target, error, side_effect=effect), self.assertRaises(OSError) as caught:
                    verdict.run(self.ledger, 'P1', 'M1', self.root)
                self.assertIs(getattr(caught.exception, 'verifier_started', None), False)
                self.assertEqual(self.calls(), 0)
                shown = verdict.run(self.ledger, 'P1', 'M1', self.root)          # on 3662b47: refused, a run of unknown outcome is held
                self.assertEqual(shown['milestones'][0]['state'], 'passed', shown['milestones'][0])

    def tearDown_plan(self):
        """A fresh project and ledger for each sub-test (the plan name is fixed by start())."""
        if getattr(self, '_used', False):
            from onecrew.ledger import Ledger
            base = Path(tempfile.mkdtemp(dir=self.temp.name))
            self.root = base / 'project'; self.root.mkdir()
            self.git('init', '-q'); self.git('config', 'user.name', 'T'); self.git('config', 'user.email', 't@localhost')
            (self.root / 'a.txt').write_text('one\n'); self.git('add', '.'); self.git('commit', '-q', '-m', 'base')
            self.ledger = Ledger(self.root, base / 'state')
            (self.fake / 'calls.txt').unlink(missing_ok=True)
        self._used = True


class CheckoutIgnoresAttributesOutsideTheTree(Fixture):
    """P2 (#4): .git/info/attributes and core.attributesFile (repository or global) are not part of the artifact; the tree's own .gitattributes is."""
    CRLF = '*.txt text eol=crlf\n'

    def checked_out(self, name):
        tree = command.verified_sha(self.root)
        scratch = tempfile.mkdtemp(prefix='ocv-test-'); self.addCleanup(lambda: shutil.rmtree(scratch, ignore_errors=True))
        return (command._checkout(self.root, tree, scratch) / name).read_bytes()

    def test_info_attributes_does_not_change_the_bytes(self):
        info = Path(self.git('rev-parse', '--git-path', 'info'))
        info = info if info.is_absolute() else self.root / info
        info.mkdir(parents=True, exist_ok=True); (info / 'attributes').write_text(self.CRLF)
        (self.root / 'b.txt').write_bytes(b'x\ny\n')
        self.assertEqual(self.checked_out('b.txt'), b'x\ny\n')

    def test_core_attributes_file_of_the_repository_or_the_user_does_not_change_the_bytes(self):
        attributes = Path(self.temp.name) / 'attributes'; attributes.write_text(self.CRLF)
        (self.root / 'b.txt').write_bytes(b'x\ny\n')
        self.git('config', 'core.attributesFile', attributes.as_posix())
        self.assertEqual(self.checked_out('b.txt'), b'x\ny\n')
        self.git('config', '--unset', 'core.attributesFile')
        home = Path(self.temp.name) / 'home'; home.mkdir()
        (home / '.gitconfig').write_text(f'[core]\n\tattributesFile = {attributes.as_posix()}\n')
        os.environ.update(HOME=str(home), USERPROFILE=str(home), XDG_CONFIG_HOME=str(home / '.config'))
        self.assertEqual(subprocess.check_output(['git', '-C', str(self.root), 'config', 'core.attributesFile']).decode().strip(), attributes.as_posix())
        self.assertEqual(self.checked_out('b.txt'), b'x\ny\n')

    def test_the_tree_s_own_gitattributes_still_applies(self):
        (self.root / '.gitattributes').write_text(self.CRLF)
        (self.root / 'b.txt').write_bytes(b'x\ny\n')
        self.assertEqual(self.checked_out('b.txt'), b'x\r\ny\r\n')        # by design: part of the artifact, and hashed with it


class PlainWordsWarnings(Fixture):
    """P2: a folder with a trailing slash, a short flag, a file name with any short extension: a warning (owner: two levels), never a refusal."""
    def owner(self, text):
        value = plan_json(presentation=dict(dev11.PLAIN, not_doing=text))
        led = lint.ReadOnlyLedger(self.root, self.ledger.state_root)
        refused = [r for r in lint.lint(led, value) if r[0] == 'owner_view_technical']
        warned = [w for w in lint.check(led, value)[1] if w[0] == 'owner_view_maybe_technical']
        return refused, warned

    def test_folder_flag_and_file_name_are_warnings(self):
        for text, word in (('Sửa docs/ xong.', 'docs/'), ('Chạy với -v.', '-v'), ('Xuất report.pdf.', 'report.pdf'), ('Xóa bằng -rf.', '-rf'),
                           ('Sửa docs/ bằng -v rồi xuất report.pdf.', 'docs/')):
            with self.subTest(word=word):
                refused, warned = self.owner(text)
                self.assertEqual(refused, []); self.assertEqual(len(warned), 1, warned); self.assertIn(word, warned[0][1])

    def test_everyday_vietnamese_stays_clean(self):
        for text in MEDICAL + ('- Không làm gì thêm, v.v.', 'Người dùng thấy -Không đổi.', 'Ghi chú: e-mail, Wi-Fi, x-quang, COVID-19.',
                               'Nhiệt độ -5 độ.', 'Bệnh nhân nam/nữ, có/không.', 'Liều 2 viên/ngày, 3 lần/tuần.', 'HbA1c và/hoặc đường huyết.',
                               'Ở TP.HCM.', 'Khoảng 2-3 lần.'):
            with self.subTest(text=text):
                self.assertEqual(self.owner(text), ([], []))


class WarningsAreShownAgain(Fixture):
    """P3: reuse and a repeated approve show the warnings a first propose / approve shows."""
    contract = dev11.CommandRefusals.contract

    def test_reuse_and_repeat_approve_carry_the_warnings(self):
        value = self.contract(not_doing='Không gọi api/v2.')
        first = plans.propose(self.ledger, 'P1', value, 'claude-opus-5-5')
        self.assertTrue(first.get('warnings'))
        again = plans.propose(self.ledger, 'P1', value, 'claude-opus-5-5', reuse_existing=True)
        self.assertEqual(again.get('warnings'), first['warnings'])
        approved = plans.approve(self.ledger, 'P1', 'owner', 'fixture')
        self.assertTrue(approved.get('warnings'))
        repeat = plans.approve(self.ledger, 'P1', 'owner', 'fixture')
        self.assertEqual(repeat.get('warnings'), approved['warnings'])
