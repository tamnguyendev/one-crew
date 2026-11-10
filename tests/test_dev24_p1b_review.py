"""2.5.0.dev24 — Kiro re-review of 8172655 (FAIL, 2 P1 + 2 P2), owner 10/11: "Sửa ngay".
- P1-a: on Windows, Popen with a bare argv[0] does not search the PATH of the environment it is given, so the fingerprinted program could differ
  from the program started. A bare program is now looked up once on the verifier's own PATH and started by that absolute path; the receipt
  fingerprints the same file. Not found on an inputs plan: refused before the verifier.
- P1-b: a declared env_input that is missing was recorded None and carried (None == None). Now a missing or unreadable env_input refuses the run
  before the verifier, and at show/accept the pass is not carried.
- P2: env_inputs inside the repository (after resolving `..`, case, junctions) are refused at the contract and at the run; one place named twice
  is refused.
- P2: the caps (20000 files, 512 MB) are counted while walking, and apply to the Python environment too (one RECORD/.pth at most 16 MB).
Red on 8172655.
"""
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from onecrew.ledger import LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import contract as contracts, plan as plans
from onecrew.v2.verifiers import command
from tests import test_hf_verifier_inputs as mep
from tests.test_dev24_p1_environment import venv
from tests.test_v2_l1 import Fixture, plan_json, milestone

SHOW = "import sys; print(sys.executable)"


class BareProgramStartsWhatIsFingerprinted(mep.Inputs):
    def test_a_bare_python_starts_the_interpreter_the_receipt_fingerprints(self):
        exe, _ = venv(Path(self.temp.name) / 'veb')            # outside the project and the scratch folder: kept on the verifier's PATH
        real = command.verifier_env
        here = lambda d: dict(real(d), PATH=str(exe.parent) + os.pathsep + real(d)['PATH'])
        with patch.object(command, 'verifier_env', side_effect=here):
            self.plan(argv=['python', '-c', SHOW])
            self.run_m1()
            body = self.receipt()
            started = Snapshots(self.ledger.state_root).read_blob(body['stdout']).decode('utf-8').strip()
            fingerprinted = body['input_scope']['tool']['path']
            self.assertEqual(os.path.normcase(str(Path(started).resolve())), os.path.normcase(fingerprinted), (started, fingerprinted))
            self.assertEqual(os.path.normcase(fingerprinted), os.path.normcase(str(exe.resolve())))
            self.assertEqual(self.view()['state'], 'passed', self.view())

    def test_a_bare_program_not_on_the_verifiers_path_is_refused_before_the_verifier(self):
        self.plan(argv=['onecrew-no-such-program-p1b', 'x'])
        for _ in range(2):                                      # not held: the second run is refused the same way, not as an unknown outcome
            with self.assertRaises(LedgerError) as caught:
                self.run_m1()
            self.assertIs(getattr(caught.exception, 'verifier_started', None), False)
            self.assertIn('absolute path', str(caught.exception))


class MissingEnvInput(mep.Inputs):
    def outside(self):
        path = Path(self.temp.name) / 'ngoai' / 'rules.txt'; path.parent.mkdir(exist_ok=True)
        return path

    def accept(self):
        with patch.dict(os.environ):
            os.environ.pop('ONECREW_ACTOR', None)
            return plans.accept(self.ledger, 'P1', 'owner', 'fixture', self.receipt()['artifact_sha'])

    def test_a_missing_env_input_refuses_the_run_before_the_verifier_and_is_not_held(self):
        rules = self.outside()
        self.plan(env_inputs=[str(rules)])
        with self.assertRaises(LedgerError) as caught:
            self.run_m1()
        self.assertIs(getattr(caught.exception, 'verifier_started', None), False)
        self.assertIn('missing', str(caught.exception))
        self.assertEqual(self.runs(), 0)
        rules.write_text('v1\n')
        self.run_m1()
        self.assertEqual(self.view()['state'], 'passed', self.view())

    def test_an_env_input_gone_after_the_run_is_stale_at_show_and_refused_at_owner_accept(self):
        rules = self.outside(); rules.write_text('v1\n')
        self.plan(env_inputs=[str(rules)])
        self.run_m1()
        self.assertEqual(self.view()['state'], 'passed', self.view())
        rules.unlink()
        view = self.view()
        self.assertNotEqual(view['state'], 'passed', view)
        self.assertIn('env_inputs', ' '.join(view.get('stale_reasons') or []), view)
        with self.assertRaises(LedgerError):
            self.accept()
        self.assertNotEqual(plans.show(self.ledger, 'P1')['status'], 'accepted')


class EnvInputsOutsideTheRepository(mep.Inputs):
    def test_an_env_input_inside_the_repository_or_holding_it_is_refused_at_the_contract(self):
        names = [str(self.root / 'a.txt'), str(self.root / 'tool' / '..' / 'a.txt'), str(self.root.parent)]
        if os.name == 'nt': names.append(str(self.root).upper() + '\\README.md')
        for name in names:
            with self.subTest(name=name), self.assertRaises(LedgerError):
                self.plan(env_inputs=[name])

    def test_an_env_input_inside_the_repository_is_refused_at_the_run(self):
        with self.assertRaises(LedgerError) as caught:
            command.env_inputs_identity([str(self.root / 'a.txt')], self.root)
        self.assertIs(getattr(caught.exception, 'verifier_started', None), False)


class OnePlaceNamedTwice(Fixture):
    def test_the_contract_refuses_one_place_named_twice(self):
        m = milestone(); m['verifier']['config'].update(inputs=['a.txt'], env_inputs=['C:/tools/rules.txt', 'C:/tools/./rules.txt'])
        with self.assertRaises(LedgerError):
            contracts.validate(plan_json(milestones=[m]))
        if os.name == 'nt':
            m['verifier']['config']['env_inputs'] = ['C:/tools/rules.txt', 'c:/TOOLS/rules.txt']
            with self.assertRaises(LedgerError):
                contracts.validate(plan_json(milestones=[m]))

    @unittest.skipUnless(os.name == 'nt', 'a junction is a Windows link')
    def test_a_junction_to_another_env_input_is_refused_at_the_run(self):
        folder = Path(self.temp.name) / 'cong-cu'; folder.mkdir(); (folder / 'x.txt').write_text('x')
        link = Path(self.temp.name) / 'loi-tat'
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(folder)], check=True, capture_output=True)
        with self.assertRaises(LedgerError) as caught:
            command.env_inputs_identity([str(folder), str(link)])
        self.assertIn('same place', str(caught.exception))


class Caps(Fixture):
    def folder(self, count):
        root = Path(self.temp.name) / f'nhieu-{count}'; root.mkdir()
        for i in range(count): (root / f'{i // 1000}').mkdir(exist_ok=True); (root / f'{i // 1000}' / f'f{i}').write_bytes(b'')
        return root

    def test_20000_files_are_fingerprinted_and_20001_are_refused(self):
        root = self.folder(20000)
        self.assertEqual(len(command.env_inputs_identity([str(root)])), 1)
        (root / 'mot-nua.txt').write_bytes(b'')
        with self.assertRaises(LedgerError) as caught:
            command.env_inputs_identity([str(root)])
        self.assertIn('too large', str(caught.exception))

    def test_the_count_stops_the_walk_before_anything_is_hashed(self):
        root = self.folder(50)
        hashed = []
        with patch.object(command, 'ENV_FILES_MAX', 5), patch.object(command, '_file_sha', side_effect=lambda p: hashed.append(p) or '0' * 64), \
                self.assertRaises(LedgerError):
            command.env_inputs_identity([str(root)])
        self.assertEqual(hashed, [])

    def test_the_byte_cap(self):
        big = Path(self.temp.name) / 'lon.bin'; big.write_bytes(b'x' * 11)
        with patch.object(command, 'ENV_BYTES_MAX', 10), self.assertRaises(LedgerError):
            command.env_inputs_identity([str(big)])

    def test_the_python_environment_is_capped_too_and_a_capped_one_is_never_carried(self):
        exe, site = venv(Path(self.temp.name) / 've')
        for i in range(6): (site / f'goi{i}-1.0.dist-info').mkdir(); (site / f'goi{i}-1.0.dist-info' / 'RECORD').write_text('x\n')
        tool = command.tool_identity(str(exe), {})
        self.assertFalse(command.tool_changed(tool))
        with patch.object(command, 'ENV_FILES_MAX', 3):
            with self.assertRaises(LedgerError):
                command.python_environment(exe)
            self.assertTrue(command.tool_changed(tool))
        (site / 'goi0-1.0.dist-info' / 'RECORD').write_bytes(b'y' * 20)
        with patch.object(command, 'META_FILE_MAX', 10), self.assertRaises(LedgerError):
            command.python_environment(exe)
