"""2.5.0.dev24 — the MEP verifier line (claude/mep-field-fixes-0911, mep2..mep7) merged into 2.5 (owner 10/11: "Gộp MEP rồi gửi").

What must hold together after the merge:
- a receipt of declared inputs is judged by the one checkout-policy rule too (an inputs receipt of another policy is not carried);
- #9: changing a milestone's inputs or inputs_unscanned is a change of acceptance;
- mep7 hole (a): a failure before the Popen (scratch directory, sweep) says the verifier did not start, the run is closed as never
  dispatched and runs again without release-run (an error out of the call without that mark stays held: test_wf_r03a_run_started);
- mep7 hole (b): tool_changed looks the program up again: a bare word that PATH now resolves to another program, or an app alias that now starts
  another program, is a change.
"""
import copy
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from onecrew.v2 import acceptance_diff as ad, plan as plans, verdict
from onecrew.v2.verifiers import command
from tests import test_hf_verifier_inputs as mep
from tests.test_v2_l1 import Fixture, plan_json, milestone

OLD = 'tree-attributes-applied/0'


class InputsReceiptKeepsThePolicy(mep.Inputs):
    def test_an_inputs_receipt_of_another_policy_is_not_carried(self):
        self.plan()
        with patch.object(command, 'CHECKOUT_POLICY', OLD):
            self.run_m1()
        view = self.view()
        self.assertNotEqual(view['state'], 'passed', view)
        self.assertIn('another checkout policy', ' '.join(view.get('stale_reasons') or []), view)


class InputsAreAcceptance(Fixture):
    def contract(self, **config):
        m = milestone(); m['verifier']['config'].update(config)
        return plan_json(milestones=[m])

    def test_changing_inputs_or_unscanned_is_a_change_of_acceptance(self):
        base = self.contract(inputs=['tool', 'spec/a.txt'])
        for change in ({'inputs': ['tool']}, {'inputs': ['tool', 'spec/a.txt', 'spec/b.txt']}, {'inputs': ['tool', 'spec/a.txt'], 'inputs_unscanned': ['spec/a.txt']}):
            with self.subTest(change=change):
                self.assertTrue(ad.classify_contract(base, self.contract(**change))['acceptance_changed'])


class NotStartedBeforeThePopen(Fixture):
    def test_no_scratch_directory_is_not_a_start_and_the_run_is_not_held(self):
        plans.propose(self.ledger, 'P1', plan_json(), 'claude'); plans.approve(self.ledger, 'P1', 'owner', 'fixture')
        real = tempfile.mkdtemp

        def no_scratch(*a, **k):
            if k.get('prefix') == command.SCRATCH_PREFIX: raise OSError(13, 'Access is denied')
            return real(*a, **k)

        with patch.object(command.tempfile, 'mkdtemp', side_effect=no_scratch), self.assertRaises(OSError) as caught:
            verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertIs(getattr(caught.exception, 'verifier_started', None), False)
        shown = verdict.run(self.ledger, 'P1', 'M1', self.root)            # not held: no release-run
        self.assertEqual(shown['milestones'][0]['state'], 'passed', shown['milestones'][0])

    def test_a_failure_in_the_sweep_is_not_a_start(self):
        plans.propose(self.ledger, 'P1', plan_json(), 'claude'); plans.approve(self.ledger, 'P1', 'owner', 'fixture')
        from onecrew.v2 import contract as contracts
        m = contracts.validate(plan_json())['milestones'][0]
        with patch.object(command, '_sweep_scratch', side_effect=OSError(5, 'Access is denied')), self.assertRaises(OSError) as caught:
            command.run(self.ledger, 'P1', 1, 'x' * 64, m, self.root)
        self.assertIs(getattr(caught.exception, 'verifier_started', None), False)


class ToolLookedUpAgain(Fixture):
    def program(self, folder, body):
        folder.mkdir(parents=True, exist_ok=True)
        name = 'onecrewtool.exe' if os.name == 'nt' else 'onecrewtool'
        path = folder / name; path.write_bytes(body); path.chmod(0o755)
        return path

    def test_a_bare_word_that_path_now_finds_elsewhere_is_a_change(self):
        first = self.program(Path(self.temp.name) / 'one', b'program one')
        second = self.program(Path(self.temp.name) / 'two', b'program one')            # the same bytes, another program on PATH
        word = first.stem
        tool = command.tool_identity(word, {'PATH': str(first.parent)})
        self.assertFalse(command.tool_changed(tool, {'PATH': str(first.parent)}))
        self.assertTrue(command.tool_changed(tool, {'PATH': str(second.parent)}))

    def test_an_alias_that_now_starts_another_program_is_a_change(self):
        first = self.program(Path(self.temp.name) / 'v1', b'v1')
        tool = {'word': str(Path(self.temp.name) / 'alias.exe'), 'path': str(first), 'alias': str(Path(self.temp.name) / 'alias.exe'),
                'sha256': __import__('hashlib').sha256(b'v1').hexdigest(), 'environment': None,      # not a Python interpreter (P1)
                'invoked': str(Path(self.temp.name) / 'alias.exe')}                                   # the path started (review of dev24c)
        with patch.object(command, 'app_alias_target', return_value=str(first)):
            self.assertFalse(command.tool_changed(tool))
        with patch.object(command, 'app_alias_target', return_value=str(Path(self.temp.name) / 'v2' / first.name)):
            self.assertTrue(command.tool_changed(tool))                       # the old folder is still on disk; the alias starts v2


class LookedUpWithTheRunsEnvironment(mep.Inputs):
    def test_the_program_is_looked_up_with_the_environment_of_the_folder_it_ran_in(self):
        # review of dev24 (P2): the run made its environment from its cwd; the check of a receipt uses the same folder, not the project root
        self.plan(argv=[mep.PY, '-c', "import pathlib; print(pathlib.Path('cfg.txt').read_text())"], cwd='tool')
        self.run_m1()
        self.assertEqual(self.view()['state'], 'passed', self.view())
        seen = []
        real = command.verifier_env
        with patch.object(command, 'verifier_env', side_effect=lambda d: seen.append(Path(d).resolve()) or real(d)):
            self.view()
        self.assertIn((self.root / 'tool').resolve(), seen, seen)
