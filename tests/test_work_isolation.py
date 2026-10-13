"""Codex review 2 of the generic execution foundation (runtime 6028118, 13/10/2026).

Finding 1: one task's contained command wrote another task's workspace. Finding 2: verification ran on the dirty workspace,
so an ignored package made a wrong delivered module pass. Finding 4: under a token whose default owner is
BUILTIN\\Administrators (the Codex app and the Task Scheduler host on this machine) contained commands could not write
their own workspace. N4: the completion reviewer lost the facts the core had established. N2: the worker never used the
project's declared test command. Adversarial tests are red on 6028118 by behaviour or capability; positive controls are
valid work that must succeed. Scripted workers, real Git/Python/Node and the real Windows boundary."""
import ctypes
from ctypes import wintypes as w
import hashlib
import json
import os
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

from onecrew.ledger import LedgerError
from onecrew import work_tools as wt
from tests.test_work_boundary import FIXED, PY, program, sha
from tests.test_work_contract import WorkFixture

NODE = shutil.which('node')


class Fixture(WorkFixture):
    def open(self, key, **authority):
        runtime, task, _ = self.job(self.contract(**authority), [], key=key)
        return runtime, task, runtime.state(task)[1], runtime.control.status(task)['configuration']['profile']['contract']

    def py(self, job, text):
        runtime, task, state, contract = job
        return wt.run(runtime, task, state, contract, {'argv': [PY, '-c', program(text)]}, lambda: None)

    def ws(self, job):
        return Path(job[2]['work']['workspace']['path'])


@unittest.skipIf(PY is None, 'needs a real Python interpreter on PATH')
class TaskBoundaryTests(Fixture):
    """Finding 1: every task directory belongs to its task."""

    def test_a_task_cannot_write_another_tasks_workspace_temp_or_cache(self):
        a, b = self.open('task-a', edit=True, commands=True), self.open('task-b', edit=True, commands=True)
        b_home = self.ws(b).parent
        targets = [self.ws(b) / 'planted_by_a.py', b_home / 'tmp' / 'planted.txt', b_home / 'cache' / 'planted.txt',
                   self.ws(b) / 'calc.py']
        ran = self.py(a, 'out = {}\n'
                      f'for p in {[str(t) for t in targets]!r}:\n'
                      "    try: open(p, 'a').write('x'); out[p] = 'written'\n"
                      "    except OSError as e: out[p] = 'denied %s' % e.errno\n"
                      "open('own.txt', 'w').write('mine')\nprint(out)")
        self.assertEqual(ran['exit_code'], 0)
        for target in targets[:3]:
            self.assertFalse(target.exists(), 'RED-GX2-F1: task A wrote into task B: ' + str(target))
        self.assertNotIn('x', (self.ws(b) / 'calc.py').read_text()[-1:], 'RED-GX2-F1: task A modified task B calc.py')
        self.assertEqual([c['path'] for c in wt.snapshot(b[2])['changes']], [])
        self.assertEqual((self.ws(a) / 'own.txt').read_text(), 'mine')

    def test_a_task_cannot_rewrite_the_access_rules_of_another_task_the_core_or_the_project(self):
        """An owner may always change an object's DACL (implicit WRITE_DAC). The task directories are owned by the user,
        whose SID is in the contained token, so without an OWNER RIGHTS entry task A could re-grant itself task B."""
        a, b = self.open('dac-a', edit=True, commands=True), self.open('dac-b', edit=True, commands=True)
        targets = {'b-workspace': self.ws(b), 'b-tmp': self.ws(b).parent / 'tmp', 'b-git': self.ws(b).parent / 'git',
                   'b-file': self.ws(b) / 'calc.py', 'project': self.root, 'own-workspace': self.ws(a)}
        # The target list goes through a file (reads are not contained): inlined, a long temp path pushes the program over
        # the 2000-character argument limit (eval harness run of 13/10/2026).
        listing = self.root.parent / 'acl-targets.json'
        listing.write_text(json.dumps({k: str(v) for k, v in targets.items()}))
        ran = self.py(a, 'import ctypes, json\nfrom ctypes import wintypes as w\n'
                      "a = ctypes.WinDLL('advapi32', use_last_error=True)\n"
                      'a.SetNamedSecurityInfoW.argtypes = [w.LPCWSTR, ctypes.c_int, w.DWORD] + [ctypes.c_void_p] * 4\n'
                      'a.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [w.LPCWSTR, w.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]\n'
                      'a.GetSecurityDescriptorDacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(w.BOOL), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(w.BOOL)]\n'
                      'out = {}\n'
                      f'for name, path in json.load(open({str(listing)!r})).items():\n'
                      '    d = ctypes.c_void_p(); a.ConvertStringSecurityDescriptorToSecurityDescriptorW("D:(A;OICI;FA;;;WD)", 1, ctypes.byref(d), None)\n'
                      '    p, dacl, x = w.BOOL(), ctypes.c_void_p(), w.BOOL(); a.GetSecurityDescriptorDacl(d, ctypes.byref(p), ctypes.byref(dacl), ctypes.byref(x))\n'
                      '    out[name] = a.SetNamedSecurityInfoW(path, 1, 0x4, None, None, dacl, None)\n'
                      'print(json.dumps(out))')
        self.assertEqual(ran['exit_code'], 0, ran['stderr'][-300:])
        codes = json.loads(ran['stdout'].strip().splitlines()[-1])
        for name in ('b-workspace', 'b-tmp', 'b-git', 'b-file', 'project'):
            self.assertNotEqual(codes[name], 0, 'task A rewrote the access rules of ' + name + ': ' + str(codes))
        # Positive control: a task keeps full control of its own files (decision 13/10/2026: Python's mkdir(0o700) - tempfile,
        # pip, venv - sets access rules, so WRITE_DAC on its own region is needed).
        self.assertEqual(codes['own-workspace'], 0, 'positive control: a task manages the rules of its own files ' + str(codes))
        own = self.py(a, "import os\nopen('own.py', 'w').write('x')\nos.chmod('own.py', 0o444)\nos.chmod('own.py', 0o666)\n"
                         "os.replace('own.py', 'own2.py')\nos.remove('own2.py')\nprint('ok')")
        self.assertEqual((own['exit_code'], own['stdout'].strip()), (0, 'ok'), 'positive control: a task manages its own files ' + own['stderr'][-300:])
        planted = self.py(a, f"open({str(self.ws(b) / 'planted.py')!r}, 'w').write('x')")
        self.assertNotEqual(planted['exit_code'], 0)
        self.assertFalse((self.ws(b) / 'planted.py').exists())

    def test_positive_control_the_core_writes_every_task_and_toolchains_start(self):
        a, b = self.open('task-a', edit=True, commands=True), self.open('task-b', edit=True, commands=True)
        for job in (a, b):
            wt.write(job[2], job[3], {'path': 'calc.py', 'expected_sha256': sha(self.ws(job) / 'calc.py'), 'text': FIXED})
        argvs = [[PY, '-m', 'unittest', '-v'], ['git', 'status', '--short']]
        if NODE: argvs.append([NODE, '-e', 'console.log(require("fs").readFileSync("calc.py","utf8").length)'])
        for argv in argvs:
            result = wt.run(*a, {'argv': argv}, lambda: None)
            self.assertEqual(result['exit_code'], 0, (argv, result['stderr'][-400:]))

    def test_positive_control_python_private_directories_work_in_the_workspace_and_the_checkout(self):
        """Third review (13/10/2026): without WRITE_DAC on its own region, Python 3.13 mkdir(0o700) failed - and with it
        tempfile.mkdtemp, pip install, venv/ensurepip and pytest tmp_path - for the worker and for verification."""
        job = self.open('mkdtemp', edit=True, commands=True)
        wt.write(job[2], job[3], {'path': 'calc.py', 'expected_sha256': sha(self.ws(job) / 'calc.py'), 'text': FIXED})
        private = program("import os, tempfile\nd = tempfile.mkdtemp(dir='.')\nos.mkdir('own700', 0o700)\n"
                          "with tempfile.TemporaryDirectory() as t: open(os.path.join(t, 'x'), 'w').write('x')\n"
                          "os.rmdir(d); os.rmdir('own700'); print('ok')\n")
        ran = wt.run(*job, {'argv': [PY, '-c', private]}, lambda: None)
        self.assertEqual((ran['exit_code'], ran['stdout'].strip()), (0, 'ok'), 'RED-GX2-F1b: workspace ' + ran['stderr'][-300:])
        runtime, task, state, contract = job
        checked = wt.verify(runtime, task, state, contract, {'setup': [{'argv': [PY, '-c', private]}],
                                                             'verification': [{'argv': [PY, '-m', 'unittest', '-v']}]}, lambda: None)
        self.assertEqual(checked['setup'][0]['exit_code'], 0, 'RED-GX2-F1b: verification checkout ' + str(checked['setup'][0].get('stdout_tail')))
        self.assertEqual(checked['findings'], [])


class AdministratorsOwner:
    """This process's token default owner set to BUILTIN\\Administrators for the duration: the shape of the Codex app and
    Task Scheduler host tokens on this machine. Objects the core creates are then owned by Administrators."""

    def __enter__(self):
        from onecrew import contain
        self.k, self.a, self.token = contain._own()
        previous = contain._info(self.a, self.token, 4)
        self.previous = contain._text(self.k, self.a, ctypes.cast(previous, ctypes.POINTER(ctypes.c_void_p))[0])
        self.set('S-1-5-32-544')
        return self

    def set(self, text):
        from onecrew import contain
        pointer = contain._sid(self.a, text); owner = ctypes.c_void_p(pointer.value)
        ok = self.a.SetTokenInformation(self.token, 4, ctypes.byref(owner), ctypes.sizeof(owner))
        self.k.LocalFree(pointer)
        if not ok: raise unittest.SkipTest('this token cannot make BUILTIN\\Administrators its default owner')

    def __exit__(self, *exc):
        self.set(self.previous); self.k.CloseHandle(self.token)


@unittest.skipIf(PY is None, 'needs a real Python interpreter on PATH')
class OwnerIndependenceTests(unittest.TestCase):
    """Finding 4: permissions of a task directory never depend on who owns it or on the parent's owner-only ACL."""

    def test_contained_commands_write_their_workspace_when_the_core_owner_is_administrators(self):
        with AdministratorsOwner():
            fixture = Fixture('setUp'); fixture.setUp()
            try:
                job = fixture.open('owner-ba', edit=True, commands=True)
                ran = fixture.py(job, "open('calc.py','w').write('def add(a, b):\\n    return a + b\\n'); print('ok')")
                self.assertEqual((ran['exit_code'], ran['stderr'][-200:]), (0, ''),
                                 'RED-GX2-F4: a contained command could not write its own workspace (owner = Administrators)')
                self.assertIn('a + b', (fixture.ws(job) / 'calc.py').read_text())
                # The project made under this owner grants SYSTEM/Administrators/OWNER RIGHTS only: the contained token cannot
                # read it, so the workspace holds its own copy of the objects instead of reading them through alternates.
                self.assertEqual(job[2]['work']['workspace'].get('objects'), 'copied')
                # Reading the core-owned Git directory (home/git) must not depend on the owner either.
                for argv in (['git', 'status', '--short'], [PY, '-m', 'unittest', '-v']):
                    result = wt.run(*job, {'argv': argv}, lambda: None)
                    self.assertEqual(result['exit_code'], 0, ('RED-GX2-F4', argv, result['stderr'][-300:]))
                denied = fixture.py(job, "import os\ntry: open(os.path.join('..', 'git', 'HEAD'), 'a').write('x'); print('written')\n"
                                         "except OSError as e: print('denied', e.errno)")
                self.assertIn('denied', denied['stdout'], 'a contained command wrote the core-owned Git directory')
            finally:
                fixture.doCleanups()


@unittest.skipIf(PY is None, 'needs a real Python interpreter on PATH')
class CleanVerificationTests(Fixture):
    """Finding 2: what is verified is the candidate alone, in a clean checkout."""

    def test_an_ignored_package_cannot_make_a_wrong_delivered_module_pass(self):
        (self.root / '.gitignore').write_text('calc/\n'); self.git('add', '.gitignore'); self.git('commit', '-q', '-m', 'ignore calc/')
        job = self.open('shadow', edit=True, commands=True, local_branches=['fix/shadow'])
        runtime, task, state, contract = job
        wt.write(state, contract, {'path': 'calc.py', 'expected_sha256': sha(self.ws(job) / 'calc.py'), 'text': 'def add(a, b):\n    return a * b\n'})
        (self.ws(job) / 'calc').mkdir(); (self.ws(job) / 'calc' / '__init__.py').write_text('def add(a, b):\n    return a + b\n')
        wt.workspace_commit(state, contract, {'message': 'add'}); wt.export_branch(runtime, task, state, contract, {'name': 'fix/shadow'})
        result = wt.verify(runtime, task, state, contract, {'verification': [{'argv': [PY, '-m', 'unittest', '-v']}]}, lambda: None)
        self.assertTrue(any('core re-run failed' in f for f in result['findings']),
                        'RED-GX2-F2: an ignored package in the workspace made the delivered wrong module verify: ' + str(result['findings']))
        self.assertEqual(result.get('verified_in', {}).get('copied_from_workspace'), [])

    def test_positive_control_setup_recreates_ignored_inputs_and_is_recorded(self):
        (self.root / '.gitignore').write_text('generated/\n')
        (self.root / 'tools').mkdir(); (self.root / 'tools' / 'gen.py').write_text(
            "from pathlib import Path\nPath('generated').mkdir(exist_ok=True)\nPath('generated/value.txt').write_text('5')\n"
            "for i in range(300): Path('generated/dep%d.js' % i).write_text('module.exports = %d' % i)\n")
        (self.root / 'test_generated.py').write_text(
            'import unittest\nfrom pathlib import Path\n\n\nclass G(unittest.TestCase):\n    def test_value(self):\n'
            "        self.assertEqual(Path('generated/value.txt').read_text(), '5')\n")
        self.git('add', '.gitignore', 'tools/gen.py', 'test_generated.py'); self.git('commit', '-q', '-m', 'generated fixture')
        job = self.open('setup', edit=True, commands=True)
        runtime, task, state, contract = job
        wt.write(state, contract, {'path': 'calc.py', 'expected_sha256': sha(self.ws(job) / 'calc.py'), 'text': FIXED})
        wt.run(*job, {'argv': [PY, 'tools/gen.py']}, lambda: None)  # generated in the workspace: not trusted for verification
        check = {'verification': [{'argv': [PY, '-m', 'unittest', '-v']}]}
        without = wt.verify(runtime, task, state, contract, check, lambda: None)
        self.assertTrue(any('core re-run failed' in f for f in without['findings']), without['findings'])
        def objects():
            counts = dict(line.split(': ') for line in wt.wgit(state, 'count-objects', '-v').decode().splitlines())
            return int(counts['count']) + int(counts['in-pack'])
        before = objects()
        withsetup = wt.verify(runtime, task, state, contract, dict(check, setup=[{'argv': [PY, 'tools/gen.py']}]), lambda: None)
        self.assertEqual(withsetup['findings'], [])
        # What setup made (300 dependency-like files) is listed as provenance but never hashed into the workspace store.
        self.assertLess(objects() - before, 10)
        self.assertEqual(withsetup['verified_in']['not_from_candidate']['generated']['files'], 301)
        self.assertIn('generated', withsetup['verified_in']['not_from_candidate'])
        self.assertEqual(withsetup['setup'][0]['exit_code'], 0)

    def test_verification_does_not_run_in_the_workspace(self):
        job = self.open('where', edit=True, commands=True)
        runtime, task, state, contract = job
        wt.write(state, contract, {'path': 'calc.py', 'expected_sha256': sha(self.ws(job) / 'calc.py'), 'text': FIXED})
        marker = program("import os; open('verification_marker.txt','w').write(os.getcwd())")
        result = wt.verify(runtime, task, state, contract, {'verification': [{'argv': [PY, '-m', 'unittest', '-v']},
                                                                              {'argv': [PY, '-c', marker]}]}, lambda: None)
        self.assertFalse((self.ws(job) / 'verification_marker.txt').exists(), 'RED-GX2-F2: verification ran in the workspace')
        self.assertEqual(result['verified_in']['kind'], 'clean checkout of the candidate tree')
        self.assertIn('verification_marker.txt', result['verified_in']['not_from_candidate'])


@unittest.skipIf(PY is None, 'needs a real Python interpreter on PATH')
class VerificationIdentityTests(Fixture):
    """Adversarial review of 4a6bdb9 (13/10/2026): verification must see the candidate only, catch tampering by any of its
    commands, and not raise false alarms; the checkout is a Git work tree like the workspace was."""

    def fixed(self, key):
        job = self.open(key, edit=True, commands=True)
        wt.write(job[2], job[3], {'path': 'calc.py', 'expected_sha256': sha(self.ws(job) / 'calc.py'), 'text': FIXED})
        return job

    def verify(self, job, **args):
        runtime, task, state, contract = job
        return wt.verify(runtime, task, state, contract, args, lambda: None)

    def test_verification_runs_in_the_checkout_and_refuses_arguments_into_the_workspace(self):
        """Decision 13/10/2026: verification is bound to the candidate by the clean checkout, not by a separate identity.
        Commands run there; a path argument into the workspace is refused. Reads elsewhere are a documented limit."""
        job = self.fixed('noread')
        where = program("import os\nprint(os.path.basename(os.getcwd()))\n")
        ran = self.verify(job, verification=[{'argv': [PY, '-m', 'unittest', '-v']}, {'argv': [PY, '-c', where]},
                                             {'argv': [PY, str(self.ws(job) / 'test_calc.py')]}])
        unit, cwd, pointed = ran['commands']
        self.assertTrue(unit['passed'], unit)
        self.assertEqual(cwd['stdout_tail'].strip(), 'v', 'verification did not run in the clean checkout')
        self.assertIn('refused', pointed['reason'] or '', 'RED-GX2-F2b: an argument into the workspace was accepted')
        self.assertIn('reads elsewhere are not contained', ran['verified_in']['identity'])

    def test_a_touched_but_unchanged_candidate_file_is_not_a_finding(self):
        job = self.fixed('touch')
        touch = program("import os, time\ndata = open('calc.py', 'rb').read()\nopen('calc.py', 'wb').write(data)\n"
                        "os.utime('calc.py', (time.time() + 5, time.time() + 5))\n")
        ran = self.verify(job, setup=[{'argv': [PY, '-c', touch]}], verification=[{'argv': [PY, '-m', 'unittest', '-v']}])
        self.assertEqual(ran['findings'], [], 'RED-GX2-F2c: an unchanged candidate file was reported as changed')

    def test_a_candidate_change_restored_by_a_later_command_is_still_found(self):
        job = self.fixed('restore')
        swap = program("open('calc.py', 'w').write('def add(a, b):\\n    return 5\\n')\n")
        back = program('open("calc.py", "w").write(' + repr(FIXED) + ')\n')
        ran = self.verify(job, setup=[{'argv': [PY, '-c', swap]}],
                          verification=[{'argv': [PY, '-m', 'unittest', '-v']}, {'argv': [PY, '-c', back]}])
        self.assertTrue(any('setup command changed the candidate file calc.py' in f for f in ran['findings']),
                        'RED-GX2-F2d: a candidate file changed for the tests and restored afterwards went unnoticed: ' + str(ran['findings']))

    def test_read_only_leftovers_do_not_break_the_next_verification(self):
        job = self.fixed('readonly')
        leave = program("import os, stat\nos.makedirs('out', exist_ok=True)\nopen('out/r.txt', 'w').write('x')\n"
                        "os.chmod('out/r.txt', stat.S_IREAD)\n")
        for _ in range(2):
            ran = self.verify(job, verification=[{'argv': [PY, '-m', 'unittest', '-v']}, {'argv': [PY, '-c', leave]}])
            self.assertEqual(ran['findings'], [])

    def test_git_works_in_the_checkout_at_the_candidate_commit(self):
        job = self.fixed('git')
        ran = self.verify(job, verification=[{'argv': ['git', 'status', '--porcelain']}, {'argv': ['git', 'rev-parse', 'HEAD']}])
        status, head = ran['commands']
        self.assertTrue(status['passed'] and head['passed'], ran['commands'])
        self.assertEqual(status['stdout_tail'].strip(), '', 'the clean checkout is not clean for Git')
        self.assertEqual(head['stdout_tail'].strip(), ran['verified_in']['commit'])
        self.assertEqual(wt.wgit(job[2], 'rev-parse', ran['verified_in']['commit'] + '^{tree}').decode().strip(), ran['candidate'])

    def test_a_package_made_by_setup_that_shadows_a_delivered_module_is_a_finding(self):
        job = self.fixed('shadowpkg')
        plant = program("import os\nos.makedirs('calc', exist_ok=True)\n"
                        "open('calc/__init__.py', 'w').write('def add(a, b):\\n    return a + b\\n')\n")
        ran = self.verify(job, setup=[{'argv': [PY, '-c', plant]}], verification=[{'argv': [PY, '-m', 'unittest', '-v']}])
        self.assertTrue(any('shadows the delivered file calc.py' in f for f in ran['findings']),
                        'RED-GX2-F2e: a setup-made package shadowing the delivered module was not reported: ' + str(ran['findings']))


@unittest.skipIf(PY is None, 'needs a real Python interpreter on PATH')
class VerificationIsolationRound2Tests(Fixture):
    """Second and third adversarial reviews (13/10/2026): one verification must not seed the next, tampering and shadows are
    found, and verification arguments stay inside the checkout."""

    fixed = VerificationIdentityTests.fixed
    verify = VerificationIdentityTests.verify

    def test_an_earlier_verification_cannot_seed_the_next(self):
        job = self.fixed('seed')
        seed = program("import os\nopen(os.path.join(os.environ['TEMP'], 'seed.txt'), 'w').write('x')\n"
                       "os.makedirs(os.environ['npm_config_cache'], exist_ok=True)\n"
                       "open(os.path.join(os.environ['npm_config_cache'], 'seed.txt'), 'w').write('x')\n")
        look = program("import os\nprint('SEEN' if os.path.exists(os.path.join(os.environ['TEMP'], 'seed.txt')) or "
                       "os.path.exists(os.path.join(os.environ['npm_config_cache'], 'seed.txt')) else 'FRESH')\n")
        self.verify(job, verification=[{'argv': [PY, '-c', seed]}])
        ran = self.verify(job, verification=[{'argv': [PY, '-c', look]}])
        self.assertEqual(ran['commands'][0]['stdout_tail'].strip(), 'FRESH', 'RED-GX2-F2g: an earlier verification seeded this one')

    def test_a_same_size_change_with_restored_times_is_found(self):
        job = self.fixed('stat')
        swap = program("import os\nst = os.stat('calc.py')\ntext = open('calc.py').read()\n"
                       "open('calc.py', 'w').write(text.replace('a + b', 'a * b'))\n"
                       "os.utime('calc.py', ns=(st.st_atime_ns, st.st_mtime_ns))\n")
        settle = program('import time\ntime.sleep(1.2)\n')
        ran = self.verify(job, setup=[{'argv': [PY, '-c', settle]}], verification=[{'argv': [PY, '-c', swap]}])
        self.assertTrue(any('changed the candidate file calc.py' in f for f in ran['findings']),
                        'RED-GX2-F2h: a same-size change with restored timestamps went unnoticed: ' + str(ran['findings']))

    def test_the_shadow_rule_spares_build_outputs_and_metadata_but_not_compiled_modules(self):
        job = self.fixed('shadow2')
        wt.write(job[2], job[3], {'path': 'build.gradle', 'expected_sha256': None, 'text': 'apply plugin: "java"\n'})
        plant = program("import os\nos.makedirs('build/classes', exist_ok=True)\nopen('build/classes/x.class', 'w').write('x')\n"
                        "os.makedirs('calc.egg-info', exist_ok=True)\nopen('calc.egg-info/PKG-INFO', 'w').write('x')\n"
                        "open('calc.cp313-win_amd64.pyd', 'wb').write(b'MZ')\n")
        ran = self.verify(job, setup=[{'argv': [PY, '-c', plant]}], verification=[{'argv': [PY, '-m', 'unittest', '-v']}])
        shadow = [f for f in ran['findings'] if 'shadows the delivered file' in f]
        self.assertEqual(len(shadow), 1, 'RED-GX2-F2i: ' + str(shadow))
        self.assertIn('calc.cp313-win_amd64.pyd', shadow[0])

    def test_a_shadow_behind_a_large_dependency_tree_is_still_found(self):
        from functools import partial
        job = self.fixed('deep')
        wt.write(job[2], job[3], {'path': 'src/util.py', 'expected_sha256': None, 'text': 'VALUE = 1\n'})
        plant = program("import os\nos.makedirs('node_modules/dep', exist_ok=True)\n"
                        "for i in range(12): open('node_modules/dep/f%d.js' % i, 'w').write('x')\n"
                        "os.makedirs('src/util', exist_ok=True)\nopen('src/util/__init__.py', 'w').write('VALUE = 2')\n")
        # node_modules sorts (and is walked) before src/; the provenance summary is capped, the shadow check is not.
        with patch.object(wt, '_ignored_outputs', partial(wt._ignored_outputs, limit=5)):
            ran = self.verify(job, setup=[{'argv': [PY, '-c', plant]}], verification=[{'argv': [PY, '-m', 'unittest', '-v']}])
        self.assertTrue(any('shadows the delivered file src/util.py' in f for f in ran['findings']),
                        'RED-GX2-F2j: a shadow past the listing cap was not found: ' + str(ran['findings']))

    def test_arguments_with_dot_dot_segments_are_refused_in_verification(self):
        runtime, task, state, contract = self.fixed('dots')
        base = self.ws((runtime, task, state, contract)).parent / 'v'; base.mkdir(exist_ok=True)
        for argument in ('-f../cache/pip', 'D:..\\cache\\x.whl', '--require=a=../r/x.js', 'file:../r/pkg', '..'):
            with self.assertRaises(LedgerError, msg='RED-GX2-F2k: accepted ' + argument):
                wt.refuse_arguments(runtime, state, [PY, argument], base=base)
        # Third review: the same places spelled without a drive letter (root-relative) or relative to a drive's cwd.
        home = self.ws((runtime, task, state, contract)).parent.resolve()
        rootless = str(home)[len(home.anchor) - 1:]  # '\\...\\<home>'
        for argument in (rootless + '\\git', '--git-dir=' + rootless.replace('\\', '/') + '/git', rootless + '\\r\\calc.py', 'D:git'):
            with self.assertRaises(LedgerError, msg='RED-GX2-F2l: accepted ' + argument):
                wt.refuse_arguments(runtime, state, [PY, argument], base=base)
        wt.refuse_arguments(runtime, state, [PY, '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py'], base=base)
        wt.refuse_arguments(runtime, state, [PY, rootless + '\\v\\test_calc.py', '-W', 'error::DeprecationWarning'], base=base)

    def test_a_compiled_cache_entry_that_python_would_not_check_is_a_shadow(self):
        """Third review: __pycache__/calc.cpython-XY.pyc is loaded instead of calc.py unless it is a checked-hash pyc."""
        job = self.fixed('pyc')
        plant = program("import py_compile, sys\nmode = py_compile.PycInvalidationMode[sys.argv[1]]\n"
                        "py_compile.compile('calc.py', cfile='__pycache__/calc.cpython-%d%d.pyc' % sys.version_info[:2], invalidation_mode=mode)\n")
        unchecked = self.verify(job, setup=[{'argv': [PY, '-c', plant, 'UNCHECKED_HASH']}], verification=[{'argv': [PY, '-m', 'unittest', '-v']}])
        self.assertTrue(any('__pycache__/calc.cpython' in f and 'shadows the delivered file calc.py' in f for f in unchecked['findings']),
                        'RED-GX2-F2m: an unchecked compiled cache entry was not reported: ' + str(unchecked['findings']))
        checked = self.verify(job, setup=[{'argv': [PY, '-c', plant, 'CHECKED_HASH']}], verification=[{'argv': [PY, '-m', 'unittest', '-v']}])
        self.assertEqual(checked['findings'], [], 'a checked-hash pyc is validated against the delivered source by Python itself')


@unittest.skipIf(PY is None, 'needs a real Python interpreter on PATH')
class LegacyHomeTests(Fixture):
    """A workspace left by 6028118 (Low label, inherited DACL granting Authenticated Users modify) must not stay writable by
    other tasks until its own task happens to run again."""

    def test_a_legacy_workspace_of_another_task_is_protected_by_the_first_contained_run(self):
        import subprocess
        a = self.open('legacy-a', edit=True, commands=True)
        base = self.ws(a).parent.parent
        legacy = base / 'abcdef0123456789' / 'r'; legacy.mkdir(parents=True)  # a task home name (16 hex digits)
        (legacy / 'mod.py').write_text('X = 1\n')
        for args in (['/grant', '*S-1-5-11:(OI)(CI)M'], ['/setintegritylevel', '(OI)(CI)L']):
            subprocess.run(['icacls', str(legacy), *args], check=True, capture_output=True)
        getattr(wt, '_LEGACY_SCANNED', set()).discard(str(base))
        ran = self.py(a, f"open({str(legacy / 'mod.py')!r}, 'a').write('X = 2\\n')")
        self.assertNotEqual(ran['exit_code'], 0, 'RED-GX2-legacy: a legacy workspace of another task was writable')
        self.assertEqual((legacy / 'mod.py').read_text(), 'X = 1\n')

    def test_an_existing_test_turned_into_another_kind_of_entry_is_a_test_change(self):
        contract = {'authority': {'edit': True, 'edit_tests': False}, 'scope': {'paths': []}}
        bad = wt.classify(contract, [{'path': 'test_calc.py', 'status': 'T'}])
        self.assertEqual([b['reason'] for b in bad], ['existing test file changed without edit_tests'])

    def test_common_test_files_outside_the_old_name_rule_are_tests(self):
        contract = {'authority': {'edit': True, 'edit_tests': False}, 'scope': {'paths': []}}
        names = ['polls/tests.py', 'conftest.py', 'src/__snapshots__/a.snap', 'e2e/login.cy.ts', 'src/setupTests.ts', 'AppTests.swift',
                 'test_x.rb']
        bad = wt.classify(contract, [{'path': n, 'status': 'M'} for n in names] + [{'path': 'calc.py', 'status': 'M'}])
        self.assertEqual([b['path'] for b in bad], names)

    def test_a_verification_stored_by_an_older_runtime_is_not_reused_for_review(self):
        runtime, task, state, contract = self.open('upgrade', edit=True, commands=True)
        wt.write(state, contract, {'path': 'calc.py', 'expected_sha256': sha(Path(state['work']['workspace']['path']) / 'calc.py'), 'text': FIXED})
        state['work']['verification'] = {'step': state['step'], 'findings': [], 'candidate': None,  # the shape 6028118 stored
                                         'commands': [{'argv': [PY, '-m', 'unittest', '-v'], 'passed': True}]}
        profile = runtime.control.status(task)['configuration']['profile']
        value = {'action': 'finish', 'arguments': json.dumps({'report': 'done', 'verification': [{'argv': [PY, '-m', 'unittest', '-v']}]})}
        runtime._work_verify(task, runtime.state(task)[0], state, profile, value)
        self.assertEqual(state['work']['verification']['verified_in']['kind'], 'clean checkout of the candidate tree')


@unittest.skipIf(PY is None, 'needs a real Python interpreter on PATH')
class ReviewFactsTests(Fixture):
    """N4: the completion review always receives the facts the core established, whatever the provider's prompt cap."""

    def test_core_facts_survive_the_kiro_cap_and_name_untouched_tests(self):
        runtime, task, state, contract = self.open('facts', edit=True, commands=True)
        for index in range(12):
            wt.write(state, contract, {'path': f'module_{index}.py', 'expected_sha256': None, 'text': ('# filler\n' * 400) + f'VALUE = {index}\n'})
        wt.write(state, contract, {'path': 'calc.py', 'expected_sha256': sha(Path(state['work']['workspace']['path']) / 'calc.py'), 'text': FIXED})
        state['work']['verification'] = dict(wt.verify(runtime, task, state, contract, {'verification': [{'argv': [PY, '-m', 'unittest', '-v']}]},
                                                       lambda: None), step=state['step'])
        big = runtime.store.blob(json.dumps({'action': 'read', 'result': {'path': 'x', 'text': 'y' * 30000}}).encode())
        state['receipts'] = [{'index': i, 'action': 'read', 'blob': big, 'successful': True} for i in range(6)]
        profile = dict(runtime.control.status(task)['configuration']['profile'], provider='kiro')
        prompt = runtime._work_review_prompt(task, state, profile, {'action': 'finish', 'arguments': '{"report":"done"}'})
        self.assertLessEqual(len(prompt) + len(json.dumps(__import__('onecrew.owned', fromlist=['REVIEW_SCHEMA']).REVIEW_SCHEMA)), 16000)
        self.assertIn('core_facts', prompt, 'RED-GX2-N4: the review prompt carries no core facts')
        payload = json.loads(prompt[prompt.index('{'):]); facts = payload['core_facts']
        self.assertEqual(facts['existing_test_files_modified_or_deleted'], [])
        self.assertEqual(len(facts['files_changed_vs_pin']), 13)
        # The diffs are the worker's content: outside core_facts, labelled untrusted, with blob ids that survive the cap.
        entries = [d for d in payload['candidate_diffs_untrusted'] if 'path' in d]
        omitted = sum(d.get('omitted_diffs', 0) for d in payload['candidate_diffs_untrusted'])
        self.assertTrue(entries and all(d['blob'] for d in entries))
        self.assertEqual(len(entries) + omitted, 13)

    def test_many_applied_files_stay_bounded_in_the_facts(self):
        from onecrew.ledger import canonical
        runtime, task, state, contract = self.open('applied', edit=True, commands=True)
        verification = {'candidate': None, 'changed_files': [], 'rules': getattr(wt, 'VERIFY_RULES', 3), 'findings': [],
                        'deliveries': {'branches': {}, 'applied': {f'pkg/file_{i:04}.py': 'b' * 40 for i in range(600)}}}
        facts = wt.review_facts(runtime, state, contract, verification)
        facts = facts[0] if isinstance(facts, tuple) else facts
        self.assertLess(len(canonical(facts['delivered'])), 2000, 'RED-GX2-N4c: delivered outputs grow the facts without bound')

    def test_many_verification_outputs_stay_bounded_in_the_facts(self):
        from onecrew.ledger import canonical
        runtime, task, state, contract = self.open('outputs', edit=True, commands=True)
        verified_in = {'kind': 'clean checkout of the candidate tree', 'not_from_candidate': {f'dir{i:03}': {'files': 1, 'bytes': 9} for i in range(500)},
                       'shadowing_candidate_files': [{'entry': f'x{i}.pyc', 'kind': 'file', 'shadows': f'x{i}.py', 'blocking': False} for i in range(50)]}
        verification = {'candidate': None, 'changed_files': [], 'rules': getattr(wt, 'VERIFY_RULES', 3), 'findings': [], 'verified_in': verified_in}
        facts = wt.review_facts(runtime, state, contract, verification)
        facts = facts[0] if isinstance(facts, tuple) else facts
        self.assertLess(len(canonical(facts['verified_in'])), 3600, 'RED-GX2-N4d: verification outputs grow the facts without bound')

    def test_a_stored_review_prompt_is_not_reused_after_verification_ran_again(self):
        runtime, task, state, contract = self.open('prompt', edit=True, commands=True)
        wt.write(state, contract, {'path': 'calc.py', 'expected_sha256': sha(Path(state['work']['workspace']['path']) / 'calc.py'), 'text': FIXED})
        state['work']['verification'] = {'step': state['step'], 'findings': [], 'commands': [{'argv': [PY, '-m', 'unittest'], 'passed': True}]}
        state['review_prompt'] = runtime.store.blob(b'review prompt built from an earlier verification')
        profile = runtime.control.status(task)['configuration']['profile']
        value = {'action': 'finish', 'arguments': json.dumps({'report': 'done', 'verification': [{'argv': [PY, '-m', 'unittest', '-v']}]})}
        runtime._work_verify(task, runtime.state(task)[0], state, profile, value)
        self.assertIn('verified_in', state['work']['verification'])
        self.assertIsNone(state.get('review_prompt'), 'RED-GX2-N4e: the review would use a prompt built from the replaced verification')

    def test_a_current_verification_is_reused_and_an_interrupted_one_is_not_rerun(self):
        runtime, task, state, contract = self.open('reuse', edit=True, commands=True)
        profile = runtime.control.status(task)['configuration']['profile']
        value = {'action': 'finish', 'arguments': json.dumps({'report': 'done'})}
        current = {'step': state['step'], 'rules': getattr(wt, 'VERIFY_RULES', 3), 'findings': [], 'checks': [{'kind': 'ref', 'passed': True}]}
        interrupted = {'step': state['step'], 'interrupted': True, 'findings': ['verification was interrupted']}
        for record in (current, interrupted):
            state['work']['verification'] = dict(record)
            with patch('onecrew.work_tools.verify') as called:
                runtime._work_verify(task, runtime.state(task)[0], state, profile, value)
            self.assertFalse(called.called, 'RED-GX2-N4b: verification re-ran for ' + str(record))

    def test_a_very_large_change_still_fits_the_kiro_review(self):
        runtime, task, state, contract = self.open('facts-large', edit=True, commands=True)
        for index in range(300):  # a refactor across a monorepo: long paths, many files
            wt.write(state, contract, {'path': f'packages/feature_area_{index % 12:02}/src/components/module_with_a_long_name_{index:03}.py',
                                       'expected_sha256': None, 'text': ('# filler\n' * 50) + f'VALUE = {index}\n'})
        state['work']['verification'] = dict(wt.verify(runtime, task, state, contract, {'verification': [{'argv': [PY, '-m', 'unittest', '-v']}]},
                                                       lambda: None), step=state['step'])
        profile = dict(runtime.control.status(task)['configuration']['profile'], provider='kiro')
        prompt = runtime._work_review_prompt(task, state, profile, {'action': 'finish', 'arguments': '{"report":"done"}'})
        facts = json.loads(prompt[prompt.index('{'):])['core_facts']
        self.assertEqual(facts.get('files_changed_count'), 300)
        self.assertEqual(facts['existing_test_files_modified_or_deleted'], [])


class ManifestTests(Fixture):
    """N2: what the project declares about build and test reaches the worker; a directory passed as a module is named."""

    def test_declared_test_commands_are_surveyed_across_ecosystems(self):
        (self.root / 'package.json').write_text(json.dumps({'scripts': {'test': 'node --test', 'start': 'node app.js'},
                                                            'devDependencies': {'mocha': '1'}}))
        (self.root / 'Makefile').write_text('test:\n\tpytest\nother:\n\techo\n')
        (self.root / '.github' / 'workflows').mkdir(parents=True)
        (self.root / '.github' / 'workflows' / 'ci.yml').write_text('jobs:\n  t:\n    steps:\n      - run: npm ci\n      - run: npm test\n')
        found = {m['file']: m for m in wt.project_manifests(self.root)}
        self.assertEqual(found['package.json']['scripts'], {'test': 'node --test'})
        self.assertEqual(found['package.json']['how_to_run'], 'npm test')
        self.assertEqual(found['Makefile']['targets'], ['test'])
        self.assertIn('npm test', found['.github/workflows/ci.yml']['run_steps'])

    def test_the_worker_prompt_carries_the_manifests(self):
        (self.root / 'package.json').write_text(json.dumps({'scripts': {'test': 'node --test'}}))
        self.git('add', 'package.json'); self.git('commit', '-q', '-m', 'node')
        runtime, task, state, contract = self.open('manifests', edit=True, commands=True)
        from onecrew.owned import contract as tools
        profile = runtime.control.status(task)['configuration']['profile']
        prompt, schema, _ = tools(profile)
        text = runtime._work_prompt(task, state, profile, runtime.control.status(task), prompt, schema, [])
        self.assertIn('project_manifests_declared_untrusted', text, 'RED-GX2-N2: the worker never sees the declared test command')
        self.assertIn('npm test', text)

    def test_unusual_manifests_neither_crash_nor_overflow(self):
        from onecrew.ledger import canonical
        (self.root / 'package.json').write_text('[1, 2]')
        web = self.root / 'web'; web.mkdir()
        (web / 'package.json').write_bytes('\ufeff{"scripts": {"test": "vitest"}, "devDependencies": []}'.encode('utf-8'))
        flows = self.root / '.github' / 'workflows'; flows.mkdir(parents=True)
        (flows / 'ci.yml').write_text('jobs:\n  t:\n    steps:\n      - run: |\n          npm ci\n          npm run test:unit\n      - name: x\n')
        for i in range(30):
            (flows / f'w{i:02}.yml').write_text('jobs:\n  t:\n    steps:\n' + ''.join(f'      - run: make test-{j} ' + 'x' * 150 + '\n' for j in range(6)))
        found = wt.project_manifests(self.root)
        by = {m['file']: m for m in found}
        self.assertEqual(by['package.json']['scripts'], {})
        self.assertEqual(by['web/package.json']['scripts'], {'test': 'vitest'})
        self.assertIn('npm run test:unit', by['.github/workflows/ci.yml']['run_steps'])
        self.assertLessEqual(len(canonical(found)), wt.MANIFEST_BUDGET)

    def test_a_relative_directory_is_resolved_against_the_command_directory(self):
        (self.root / 'test').mkdir()
        hint = wt.diagnose({'stderr': "Error: Cannot find module './test'\n", 'stdout': '', 'stopped': None, 'exit_code': 1,
                            'tests': {}, 'boundary': 'contained'}, None, self.root)
        self.assertIn('directory was given', hint)

    def test_a_directory_given_where_a_module_was_expected_is_named(self):
        directory = self.root / 'test'; directory.mkdir()
        hint = wt.diagnose({'stderr': f"Error: Cannot find module '{directory}'\n  code: 'MODULE_NOT_FOUND'", 'stdout': '',
                            'stopped': None, 'exit_code': 1, 'tests': {}, 'boundary': 'contained'})
        self.assertIn('directory was given', hint, 'RED-GX2-N2: ' + str(hint))


if __name__ == '__main__':
    unittest.main()
