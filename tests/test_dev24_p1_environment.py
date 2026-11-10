"""2.5.0.dev24 — review of dev24 (Kiro, P1): a pass of declared inputs was carried after a package or plugin outside the repository changed,
because the program fingerprint covered only the exe of argv[0]. Fixed (owner 10/11: "Sửa ngay"):
- a Python interpreter is fingerprinted with what it loads, read from disk: every dist-info/egg-info (name with version, sha256 of RECORD),
  every .pth file and pyvenv.cfg;
- any other program: the contract may declare `env_inputs`, absolute paths outside the repository, fingerprinted with the receipt;
- a change of either makes the pass not carried; a receipt made before the environment was fingerprinted is not carried either.
Red on e96e386 (2a2fa61 before it).
"""
import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from onecrew.ledger import LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import acceptance_diff as ad, contract as contracts, plan as plans
from tests import test_hf_verifier_inputs as mep
from tests.test_v2_l1 import Fixture, plan_json, milestone


def venv(where):
    subprocess.run([sys.executable, '-m', 'venv', '--without-pip', str(where)], check=True, capture_output=True)
    exe = where / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    site = next(p for p in [where / 'Lib' / 'site-packages', *where.glob('lib/python3*/site-packages')] if p.is_dir())
    return exe, site


class EnvironmentFingerprint(mep.Inputs):
    def test_a_package_added_or_upgraded_in_the_interpreter_makes_the_pass_not_carried(self):
        exe, site = venv(Path(self.temp.name) / 've')
        self.plan(argv=[str(exe), '-c', "import pathlib; print(pathlib.Path('tool/cfg.txt').read_text())"])
        self.run_m1()
        self.assertEqual(self.view()['state'], 'passed', self.view())
        plugin = site / 'fakeplugin-1.0.dist-info'; plugin.mkdir()
        (plugin / 'RECORD').write_text('fakeplugin/__init__.py,sha256=x,1\n')
        view = self.view()
        self.assertNotEqual(view['state'], 'passed', view)

    def test_a_declared_path_outside_the_repository_that_changes_makes_the_pass_not_carried(self):
        outside = Path(self.temp.name) / 'outside' / 'rules.txt'; outside.parent.mkdir(); outside.write_text('v1\n')
        self.plan(env_inputs=[str(outside)])
        self.run_m1()
        self.assertEqual(self.view()['state'], 'passed', self.view())
        outside.write_text('v2\n')
        view = self.view()
        self.assertNotEqual(view['state'], 'passed', view)
        self.assertIn('env_inputs', ' '.join(view.get('stale_reasons') or []) + json.dumps(view))

    def test_a_receipt_made_before_the_environment_was_fingerprinted_is_not_carried(self):
        self.plan()
        self.run_m1()
        receipt = self.view()['last_verdict']['receipt']
        store = Snapshots(self.ledger.state_root)
        body = json.loads(store.read_blob(receipt))
        tool = dict(body['input_scope']['tool']); tool.pop('environment', None)
        from onecrew.v2.verifiers import command
        self.assertTrue(command.tool_changed(tool))
        tool['environment'] = {'unreadable': 'PermissionError: denied'}                  # an environment never read proves nothing
        self.assertTrue(command.tool_changed(tool))


class EnvInputsInTheContract(Fixture):
    def test_env_inputs_are_absolute_only_with_inputs_and_a_change_of_acceptance(self):
        def contract(**config):
            m = milestone(); m['verifier']['config'].update(config)
            return plan_json(milestones=[m])
        # review of dev24c: env_inputs may be declared without inputs too (every command receipt names its program)
        self.assertEqual(contracts.validate(contract(env_inputs=['C:/x']))['milestones'][0]['verifier']['config']['env_inputs'], ['C:/x'])
        for bad in ({'inputs': ['a.txt'], 'env_inputs': ['relative/path']}, {'inputs': ['a.txt'], 'env_inputs': []}):
            with self.subTest(bad=bad), self.assertRaises(LedgerError):
                contracts.validate(contract(**bad))
        good = contracts.validate(contract(inputs=['a.txt'], env_inputs=['C:/tools/rules.txt']))
        self.assertEqual(good['milestones'][0]['verifier']['config']['env_inputs'], ['C:/tools/rules.txt'])
        self.assertTrue(ad.classify_contract(contract(inputs=['a.txt'], env_inputs=['C:/a']), contract(inputs=['a.txt'], env_inputs=['C:/b']))['acceptance_changed'])
