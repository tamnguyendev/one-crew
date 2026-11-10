"""2.5.0.dev24 — Kiro round 3 on 84ef359 (FAIL, 3 P1 + 8 P2 + 1 P3); owner 11/11: "Sửa cả lỗi cũ".
- P1 (links): a Python interpreter's packages are found from the path it is STARTED with (a POSIX venv's bin/python is a link into the base
  installation and still the venv's); a receipt keeps the invoked path and the file it runs, and the check resolves the invoked path again, so a
  file or folder link that now points elsewhere is a change.
- P1 (old, since 2.2): EVERY command receipt names its program and Python packages (and env_inputs when declared), and the program rule is judged
  wherever command evidence is judged (plan show, owner accept, the reuse of a retained proof). The checkout policy moves to exact-blob-bytes/3: on a
  plan not yet accepted, each older pass runs once again after the upgrade; an accepted plan keeps its history.
- P2: a missing program (bare or absolute) is refused before the verifier; the PATH loses the folders of the project's repository (by path
  components, not by the milestone's cwd and not by string prefix); the process is started from the found path while the child still sees
  argv[0] as written; a bare name never resolves through OneCrew's own current folder; the caps count folders, and the site-packages discovery is
  capped; two env_inputs naming one place are refused at propose; env_inputs may be declared without inputs.
Red on 84ef359.
"""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from onecrew.ledger import LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import contract as contracts, plan as plans, verdict
from onecrew.v2.verifiers import command
from tests import test_hf_verifier_inputs as mep
from tests.test_dev24_p1_environment import venv
from tests.test_v2_l1 import Fixture, plan_json, milestone

PRINT = "print('chay xong')"
OLD = 'exact-blob-bytes/2'


def can_link(where):
    try:
        os.symlink(where / 'khong-co', where / 'thu-lien-ket'); os.unlink(where / 'thu-lien-ket'); return True
    except (OSError, NotImplementedError):
        return False


class Base(mep.Inputs):
    """The fixture of the inputs tests, without running their tests again here."""


for _name in [n for n in dir(mep.Inputs) if n.startswith('test')]: setattr(Base, _name, None)


def junction(link, folder):
    if os.name == 'nt': subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(folder)], check=True, capture_output=True)
    else: os.symlink(folder, link, target_is_directory=True)


class InvokedPath(Fixture):
    def fake_base(self):
        base = Path(self.temp.name) / 'goc'
        (base / 'bin').mkdir(parents=True); (base / 'bin' / 'python3.11').write_bytes(b'interpreter')
        (base / 'lib' / 'python3.11' / 'site-packages').mkdir(parents=True)
        return base

    def fake_venv(self, base):
        ve = Path(self.temp.name) / 've-posix'
        (ve / 'bin').mkdir(parents=True)
        (ve / 'pyvenv.cfg').write_text(f'home = {base / "bin"}\ninclude-system-site-packages = false\n')
        site = ve / 'lib' / 'python3.11' / 'site-packages'; site.mkdir(parents=True)
        return ve, site

    def test_the_packages_are_found_from_the_invoked_path_not_from_where_its_link_points(self):
        base = self.fake_base(); ve, site = self.fake_venv(base)
        invoked, target = ve / 'bin' / 'python', base / 'bin' / 'python3.11'          # the venv's bin/python, a link to the base interpreter
        before = command.python_environment(invoked, target)
        self.assertIn(str(site), before['site_packages'])
        (site / 'pytest-8.0.dist-info').mkdir(); (site / 'pytest-8.0.dist-info' / 'RECORD').write_text('pytest/__init__.py,,\n')
        self.assertNotEqual(command.python_environment(invoked, target)['sha256'], before['sha256'])

    def test_a_real_posix_style_venv_link(self):
        base = self.fake_base(); ve, site = self.fake_venv(base)
        if not can_link(Path(self.temp.name)): self.skipTest('this system does not allow symbolic links')
        os.symlink(base / 'bin' / 'python3.11', ve / 'bin' / 'python')
        tool = command.tool_identity(str(ve / 'bin' / 'python'), {})
        self.assertEqual(os.path.normcase(tool['invoked']), os.path.normcase(str(ve / 'bin' / 'python')))
        self.assertEqual(os.path.normcase(tool['path']), os.path.normcase(str((base / 'bin' / 'python3.11').resolve())))
        self.assertIn(str(site), tool['environment']['site_packages'])
        self.assertFalse(command.tool_changed(tool, {}))
        (site / 'plugin-2.0.dist-info').mkdir(); (site / 'plugin-2.0.dist-info' / 'RECORD').write_text('x\n')
        self.assertTrue(command.tool_changed(tool, {}))

    def test_an_absolute_file_link_that_now_points_elsewhere_is_a_change(self):
        if not can_link(Path(self.temp.name)): self.skipTest('this system does not allow symbolic links')
        folder = Path(self.temp.name) / 'opt-check'; folder.mkdir()
        (folder / 'python-3.11').write_bytes(b'3.11'); (folder / 'python-3.12').write_bytes(b'3.12')
        link = folder / 'python'; os.symlink(folder / 'python-3.11', link)
        tool = command.tool_identity(str(link), {})
        self.assertFalse(command.tool_changed(tool, {}))
        link.unlink(); os.symlink(folder / 'python-3.12', link)              # 3.11 is still on the disk
        self.assertTrue(command.tool_changed(tool, {}))

    def test_a_folder_link_on_the_way_that_now_points_elsewhere_is_a_change(self):
        one, two = Path(self.temp.name) / 'v1', Path(self.temp.name) / 'v2'
        for folder in (one, two): folder.mkdir(); (folder / 'checker.exe').write_bytes(b'same bytes')
        current = Path(self.temp.name) / 'current'; junction(current, one)
        tool = command.tool_identity(str(current / 'checker.exe'), {})
        self.assertFalse(command.tool_changed(tool, {}))
        os.rmdir(current) if os.name == 'nt' else current.unlink()
        junction(current, two)
        self.assertTrue(command.tool_changed(tool, {}))                          # same bytes, another file


class EveryCommandReceipt(Base):
    def accept(self):
        with patch.dict(os.environ):
            os.environ.pop('ONECREW_ACTOR', None)
            return plans.accept(self.ledger, 'P1', 'owner', 'fixture', self.receipt()['artifact_sha'])

    def test_a_plan_without_inputs_pass_is_not_carried_after_a_package_is_upgraded(self):
        exe, site = venv(Path(self.temp.name) / 've')
        (site / 'pytest-8.0.dist-info').mkdir(); (site / 'pytest-8.0.dist-info' / 'RECORD').write_text('a\n')
        self.plan(inputs=None, argv=[str(exe), '-c', PRINT])
        self.run_m1()
        self.assertEqual(self.view()['state'], 'passed', self.view())
        self.assertIn('program', self.receipt())
        (site / 'pytest-8.0.dist-info').rename(site / 'pytest-8.1.dist-info')
        view = self.view()
        self.assertNotEqual(view['state'], 'passed', view)
        self.assertIn('program', ' '.join(view.get('stale_reasons') or []), view)
        with self.assertRaises(LedgerError):
            self.accept()

    def test_env_inputs_without_inputs_are_recorded_and_judged(self):
        rules = Path(self.temp.name) / 'ngoai' / 'rules.txt'; rules.parent.mkdir(); rules.write_text('v1\n')
        self.plan(inputs=None, argv=[mep.PY, '-c', PRINT], env_inputs=[str(rules)])
        self.run_m1()
        self.assertEqual(self.view()['state'], 'passed', self.view())
        rules.write_text('v2\n')
        view = self.view()
        self.assertNotEqual(view['state'], 'passed', view)
        self.assertIn('env_inputs', ' '.join(view.get('stale_reasons') or []), view)

    def test_the_child_sees_argv0_as_written(self):
        real = command.verifier_env
        here = lambda d: dict(real(d), PATH=str(Path(sys.executable).parent) + os.pathsep + real(d)['PATH'])
        with patch.object(command, 'verifier_env', side_effect=here):
            self.plan(inputs=None, argv=['python', '-c', 'import sys; print(sys.orig_argv[0])'])
            self.run_m1()
            body = self.receipt()
        seen = Snapshots(self.ledger.state_root).read_blob(body['stdout']).decode('utf-8').strip()
        self.assertEqual(seen, 'python')
        self.assertEqual(os.path.normcase(body['program']['invoked']), os.path.normcase(str(Path(sys.executable).parent / ('python.exe' if os.name == 'nt' else 'python'))))

    def refused_twice(self, inputs, argv):
        self.plan(inputs=inputs, argv=argv)
        for _ in range(2):                                                      # not held: the same refusal again, not an unknown outcome
            with self.assertRaises(LedgerError) as caught:
                self.run_m1()
            self.assertIs(getattr(caught.exception, 'verifier_started', None), False)
        self.assertEqual(plans.show(self.ledger, 'P1')['milestones'][0]['runs'], 0)

    def gone(self):
        return str(Path(self.temp.name) / 'da-xoa' / ('python.exe' if os.name == 'nt' else 'python'))

    def test_a_missing_absolute_program_is_refused_before_the_verifier_without_inputs(self):
        self.refused_twice(None, [self.gone(), '-c', PRINT])

    def test_a_missing_absolute_program_is_refused_before_the_verifier_with_inputs(self):
        self.refused_twice('default', [self.gone(), '-c', PRINT])

    def test_a_bare_program_not_on_the_path_is_refused_without_inputs_too(self):
        self.refused_twice(None, ['onecrew-no-such-program-p1c'])


class OldReceipts(Base):
    def setUp(self):
        with patch.object(command, 'CHECKOUT_POLICY', OLD):                       # everything before the upgrade, under the policy it ran
            super().setUp()
            self.plan(inputs=None, argv=[mep.PY, '-c', PRINT])
            self.run_m1()

    def test_a_pass_from_before_the_upgrade_runs_once_again_on_a_plan_not_yet_accepted(self):
        view = self.view()
        self.assertNotEqual(view['state'], 'passed', view)
        self.assertTrue(view.get('needs_recheck'), view)
        self.run_m1()
        self.assertEqual(self.view()['state'], 'passed', self.view())

    def test_an_accepted_plan_keeps_its_history(self):
        with patch.object(command, 'CHECKOUT_POLICY', OLD), patch.dict(os.environ):
            os.environ.pop('ONECREW_ACTOR', None)
            plans.accept(self.ledger, 'P1', 'owner', 'fixture', self.receipt()['artifact_sha'])
        shown = plans.show(self.ledger, 'P1')
        self.assertEqual((shown['status'], shown['milestones'][0]['state']), ('accepted', 'passed'), shown)

    def test_a_receipt_of_this_policy_that_names_no_program_is_not_current(self):
        body = {'kind': 'command-receipt', 'checkout_policy': command.CHECKOUT_POLICY, 'cwd': str(self.root)}
        self.assertTrue(command.program_reasons(body, self.root))
        self.assertEqual(command.CHECKOUT_POLICY, 'exact-blob-bytes/3')


class PathOfTheVerifier(Base):
    def test_the_path_loses_the_repository_not_a_sibling_with_the_same_prefix(self):
        inside, sibling = self.root / 'bin', Path(str(self.root) + '-tools')
        for folder in (inside, sibling): folder.mkdir(exist_ok=True)
        moved = str(inside).upper() if os.name == 'nt' else str(inside)
        with patch.dict(os.environ, PATH=os.pathsep.join([moved, str(sibling), os.environ.get('PATH', '')])):
            got = [os.path.normcase(p) for p in command.verifier_env(self.root / 'tool')['PATH'].split(os.pathsep)]
        self.assertNotIn(os.path.normcase(str(inside)), got)                 # inside the repository, though not inside the cwd `tool`
        self.assertIn(os.path.normcase(str(sibling)), got)                   # C:\...\project-tools is not inside C:\...\project

    def test_a_bare_name_never_resolves_through_onecrews_own_folder(self):
        here = Path(self.temp.name) / 'cwd-cua-onecrew'; here.mkdir()
        (here / ('onecrewprobe.exe' if os.name == 'nt' else 'onecrewprobe')).write_bytes(b'x')
        (here / 'onecrewprobe').chmod(0o755) if os.name != 'nt' else None
        old = os.getcwd(); os.chdir(here); self.addCleanup(os.chdir, old)
        env = {'PATH': str(Path(self.temp.name) / 'khac')}
        self.assertIsNone(command._which('onecrewprobe', env))
        self.assertIsNone(command.program_path('onecrewprobe', env))


class Caps(Fixture):
    def test_folders_count_and_a_new_empty_folder_changes_the_fingerprint(self):
        root = Path(self.temp.name) / 'nhieu-thu-muc'; root.mkdir()
        for i in range(30): (root / f'd{i}').mkdir()
        with patch.object(command, 'ENV_FILES_MAX', 10), self.assertRaises(LedgerError):
            command.env_inputs_identity([str(root)])
        before = command.env_inputs_identity([str(root)])
        (root / 'bat-tinh-nang').mkdir()
        self.assertNotEqual(command.env_inputs_identity([str(root)]), before)

    def test_the_site_packages_discovery_is_capped(self):
        base = Path(self.temp.name) / 'py'; (base / 'bin').mkdir(parents=True); (base / 'bin' / 'python3').write_bytes(b'x')
        for i in range(30): (base / 'lib' / f'python3.{i}' / 'site-packages').mkdir(parents=True)
        with patch.object(command, 'ENV_FILES_MAX', 10), self.assertRaises(LedgerError):
            command.python_environment(base / 'bin' / 'python3')


class TwoNamesOnePlaceAtPropose(Base):
    def test_two_env_inputs_resolving_to_one_place_are_refused_at_propose(self):
        folder = Path(self.temp.name) / 'cong-cu'; folder.mkdir(); (folder / 'x.txt').write_text('x')
        link = Path(self.temp.name) / 'loi-tat'; junction(link, folder)
        with self.assertRaises(LedgerError) as caught:
            self.plan(env_inputs=[str(folder), str(link)])
        self.assertIn('same place', str(caught.exception))
