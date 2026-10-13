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

    def test_positive_control_the_core_writes_every_task_and_toolchains_start(self):
        a, b = self.open('task-a', edit=True, commands=True), self.open('task-b', edit=True, commands=True)
        for job in (a, b):
            wt.write(job[2], job[3], {'path': 'calc.py', 'expected_sha256': sha(self.ws(job) / 'calc.py'), 'text': FIXED})
        argvs = [[PY, '-m', 'unittest', '-v'], ['git', 'status', '--short']]
        if NODE: argvs.append([NODE, '-e', 'console.log(require("fs").readFileSync("calc.py","utf8").length)'])
        for argv in argvs:
            result = wt.run(*a, {'argv': argv}, lambda: None)
            self.assertEqual(result['exit_code'], 0, (argv, result['stderr'][-400:]))


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
        facts = json.loads(prompt[prompt.index('{'):])['core_facts']
        self.assertEqual(facts['existing_test_files_modified_or_deleted'], [])
        self.assertEqual(len(facts['files_changed_vs_pin']), 13)
        self.assertTrue(all(d['blob'] for d in facts['diffs']))


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

    def test_a_directory_given_where_a_module_was_expected_is_named(self):
        directory = self.root / 'test'; directory.mkdir()
        hint = wt.diagnose({'stderr': f"Error: Cannot find module '{directory}'\n  code: 'MODULE_NOT_FOUND'", 'stdout': '',
                            'stopped': None, 'exit_code': 1, 'tests': {}, 'boundary': 'contained'})
        self.assertIn('directory was given', hint, 'RED-GX2-N2: ' + str(hint))


if __name__ == '__main__':
    unittest.main()
