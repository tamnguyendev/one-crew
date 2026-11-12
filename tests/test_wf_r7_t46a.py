"""Round 7 / T46a (W23b, R02) — E7 and E10 on a fixture where the watched files EXIST.

tests.test_wf_r02_resume.test_e7_e8_e10 hashes `active-plan.json` and the hook configuration "if they are files"; this module makes sure the
files are there (the real `active_plan.export` of each plan, the hook settings `onecrew init` writes, and `.onecrew/config.json`) so the
before/after comparison cannot pass vacuously, and it records EVERY child process started while the pack is built (not only the git calls of
the verifier module): T46a E10 evidence is "the list of child processes and provider calls recorded in step 1: none".

Counter-examples: a pack builder that re-exports the active plan (a write a real export would make) changes the mtime and is caught; a pack
builder that starts a process is caught by the process list.
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.v2 import active_plan, hook_cli, install, resume_pack, where
from tests.test_wf_r02_resume import ResumeBase, WRITE_VERBS, digest_of
from wf_r02 import git_log, model_calls


class ProcessLog:
    """Every process started through subprocess.Popen (subprocess.run/check_output use it) while active, as argv lists."""

    def __init__(self):
        self.seen = []
        self.real = subprocess.Popen

    def __enter__(self):
        log, real = self.seen, self.real

        class Spy(real):
            def __init__(self, args, *a, **k):
                log.append([str(x) for x in (args if isinstance(args, (list, tuple)) else [args])])
                super().__init__(args, *a, **k)
        self.patch = patch('subprocess.Popen', Spy)
        self.patch.start()
        return self.seen

    def __exit__(self, *exc):
        self.patch.stop()


class ResumePackWatchedFilesTests(ResumeBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for name in ('p1', 'p2', 'p3', 'p4'): active_plan.export(cls.ledger, name)
        settings = cls.root / '.claude' / 'settings.local.json'
        install.write_text(settings, install.dump(install.merge_settings({}, hook_cli.portable_settings(sys.executable, cls.state))))
        config = where.config_file(cls.root)
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(json.dumps({'state_root': str(cls.state)}), encoding='utf-8')
        active_plan.export(cls.ledger, 'p1', take_over=True)        # the owner makes the running plan the governing one (dev25 P2-2: only the owner switches it)

    def watched(self):
        files = sorted(set(self.state.rglob('active-plan.json')) | {active_plan.project_file(self.root), self.root / '.claude' / 'settings.local.json',
                                                                    where.config_file(self.root)})
        return files

    def run_all(self):
        for name in ('p1', 'p2', 'p3', 'p4'):
            self.assertEqual(self.cli('continue', name)[0], 0, name)
            self.assertEqual(self.cli('continue', name, '--json')[0], 0, name)

    def test_e7_the_watched_files_exist_and_are_unchanged_by_the_pack(self):
        files = self.watched()
        self.assertTrue(all(p.is_file() for p in files), [str(p) for p in files if not p.is_file()])
        self.assertGreaterEqual(len([p for p in files if p.name == 'active-plan.json']), 2)     # state copy(ies) + project copy
        before = digest_of(files)
        self.assertEqual(len(before), len(files))
        with model_calls() as calls, git_log() as git:
            self.run_all()
        self.assertEqual(calls, [])
        self.assertEqual({a[0] for a in git} & WRITE_VERBS, set())
        self.assertEqual(digest_of(files), before)

    def test_e7_counter_a_pack_that_re_exports_the_active_plan_is_caught(self):
        files = self.watched()
        before = digest_of(files)
        real = resume_pack.build

        def writing(ledger, name, context=None):
            active_plan.export(self.ledger, name)                   # the write a careless builder would make (hooks' file)
            return real(ledger, name, context)
        with patch.object(resume_pack, 'build', writing):
            self.cli('continue', 'p1', '--json')
        self.assertNotEqual(digest_of(files), before, 'the before/after check must see a re-export')
        active_plan.export(self.ledger, 'p1')

    def test_e10_no_child_process_other_than_read_only_git(self):
        with ProcessLog() as procs, model_calls() as calls:
            self.run_all()
        self.assertEqual(calls, [])
        others = [p for p in procs if Path(p[0]).stem.lower() != 'git']
        self.assertEqual(others, [], 'the pack started a process that is not git')
        verbs = set()
        for argv in procs:
            rest = argv[1:]
            while rest and rest[0].startswith('-'):
                rest = rest[2:] if rest[0] in ('-C', '-c') else rest[1:]
            if rest: verbs.add(rest[0])
        self.assertEqual(verbs & WRITE_VERBS, set(), verbs)

    def test_e10_counter_a_pack_that_starts_a_process_is_caught(self):
        real = resume_pack.build

        def spawning(ledger, name, context=None):
            subprocess.run([sys.executable, '-c', 'pass'], check=True)
            return real(ledger, name, context)
        with ProcessLog() as procs, patch.object(resume_pack, 'build', spawning):
            self.cli('continue', 'p3', '--json')
        self.assertTrue([p for p in procs if Path(p[0]).stem.lower() != 'git'], 'the process list must see a spawned worker')


if __name__ == '__main__':
    unittest.main()
