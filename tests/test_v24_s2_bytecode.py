"""2.4-S2, Codex review of 2.4.0.dev3 (D:/OneCrewRuns/codex-dev3-review-c2a9a088, bytecode_probe.py / bytecode-result.json), P1:
a bytecode cache that is not the compile of its source was REPORTED by verify_installed, but only after the venv's `onecrew --version`
had run — so the planted code had already executed (marker_created true, entrypoint_exit 0).

Expected: a venv whose caches are not proven to be the compile of their source never has its entrypoint (or anything that imports from it)
started by the identity check; an interpreter check that does not answer, answers partially or cannot read a cache is not a path to
running the unverified runtime; an intact venv still runs and is accepted. Also the rollback path: the OLD runtime's caches are checked
before any of its programs (drill reader, event classifier) runs.

REAL runtime: a venv made by `python -m venv` with the real wheel of this checkout installed by pip (review2.RealVenvIdentity.setUpClass). The payload
is harmless: it only writes a marker file in the test's own folder. Every tampering is undone after its test. Programs started are seen
through a spy on hotfix.run (the one door the module uses to start a process).
"""
import json
import marshal
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_v24_s2_apply import hotfix
import tests.test_v24_s2_review2 as review2           # the module, not the class: its tests are not run a second time here


class BytecodeNeverRuns(unittest.TestCase):
    setUpClass = classmethod(review2.RealVenvIdentity.setUpClass.__func__)
    tearDownClass = classmethod(review2.RealVenvIdentity.tearDownClass.__func__)
    keep = review2.RealVenvIdentity.keep

    def setUp(self):
        self.marker = self.runs / f'marker-{self._testMethodName}.txt'
        self.marker.unlink(missing_ok=True)

    def cache_of(self, module):
        source = self.site / Path(*module.split('/'))
        cache = source.parent / '__pycache__' / f'{source.stem}.{sys.implementation.cache_tag}.pyc'
        self.assertTrue(cache.is_file(), f'pip compiles {module} at install')
        return source, cache

    def plant(self, module):
        """Replace the cache of `module` by the compile of its source PLUS a line that writes the marker; keep the 16-byte header, so Python
        takes it for the cache of the unchanged source (the Codex probe)."""
        source, cache = self.cache_of(module)
        saved = self.keep(cache)
        payload = source.read_bytes() + ('\nfrom pathlib import Path as _P\n_P(' + repr(str(self.marker)) + ').write_text("executed")\n').encode()
        cache.write_bytes(saved[:16] + marshal.dumps(compile(payload, str(source), 'exec')))
        return cache

    def judge(self, **kwargs):
        """verify_installed under a spy: (problems, identity, programs started from inside the venv)."""
        started, real = [], hotfix().run
        def spy(argv, *args, **kw):
            started.append([str(a) for a in argv])
            return real(argv, *args, **kw)
        with patch.object(hotfix(), 'run', spy):
            problems, found = hotfix().verify_installed(self.venv, self.art, baseline=self.baseline, **kwargs)
        inside = [a for a in started if Path(a[0]).resolve().is_relative_to(self.venv.resolve())]
        return problems, found, inside

    def entry_started(self, inside):
        return [a for a in inside if Path(a[0]).name.lower().startswith('onecrew')]

    # ---- control ----------------------------------------------------------------------------------------------------------------
    def test_control_intact_venv_runs_and_is_accepted(self):
        problems, found, inside = self.judge()
        self.assertEqual(problems, [])
        self.assertEqual(found.get('exit'), 0)
        self.assertTrue(self.entry_started(inside), 'the intact runtime is still run by the check')
        self.assertTrue(found.get('record_sha256'))

    # ---- the Codex probe and the same class -------------------------------------------------------------------------------------
    def test_codex_probe_planted_messages_cache_is_refused_and_never_executed(self):
        self.plant('onecrew/v2/messages.py')
        problems, found, inside = self.judge()
        self.assertTrue(any('.pyc' in p and 'messages' in p for p in problems), problems)
        self.assertFalse(self.marker.exists(), 'the planted bytecode ran during the identity check')
        self.assertEqual(self.entry_started(inside), [], 'onecrew --version was started on an unverified runtime')
        self.assertIsNone(found.get('exit'))
        self.assertIsNone(found.get('record_sha256'))

    def test_planted_cache_of_the_package_init_is_refused_and_never_executed(self):
        self.plant('onecrew/__init__.py')                 # imported by every entrypoint
        problems, found, inside = self.judge()
        self.assertTrue(any('.pyc' in p for p in problems), problems)
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.entry_started(inside), [])

    def test_interpreter_check_that_does_not_answer_is_not_a_path_to_running(self):
        with patch.object(hotfix(), 'interpreter', return_value={'error': 'fixture: no answer'}):
            problems, found, inside = self.judge()
        self.assertTrue(problems)
        self.assertEqual(self.entry_started(inside), [])
        self.assertIsNone(found.get('exit'))

    def test_partial_answer_leaves_caches_unproven_and_nothing_runs(self):
        _, cache = self.cache_of('onecrew/v2/messages.py')
        real = hotfix().interpreter
        def partial(venv, caches):
            facts = real(venv, caches)
            facts['pyc'] = {k: v for k, v in facts['pyc'].items() if Path(k).resolve() != cache.resolve()}
            return facts
        with patch.object(hotfix(), 'interpreter', partial):
            problems, found, inside = self.judge()
        self.assertTrue(any('messages' in p for p in problems), problems)
        self.assertEqual(self.entry_started(inside), [])

    def test_unreadable_cache_verdict_is_refused_and_nothing_runs(self):
        real = hotfix().interpreter
        def unreadable(venv, caches):
            facts = real(venv, caches)
            first = sorted(facts['pyc'])[0]
            facts['pyc'][first] = 'unreadable: PermissionError'
            return facts
        with patch.object(hotfix(), 'interpreter', unreadable):
            problems, found, inside = self.judge()
        self.assertTrue(any('.pyc' in p for p in problems), problems)
        self.assertEqual(self.entry_started(inside), [])

    def test_cache_planted_after_the_check_is_not_loaded_by_the_identity_run(self):
        """Defence in depth (a cache replaced between the interpreter check and the entrypoint run): the identity run reads bytecode from an
        empty prefix of its own, never from the venv's __pycache__, so the planted code still does not execute."""
        real = hotfix().interpreter
        def then_plant(venv, caches):
            facts = real(venv, caches)                    # the check sees the intact caches
            self.plant('onecrew/v2/messages.py')          # ...and the cache changes right after
            return facts
        with patch.object(hotfix(), 'interpreter', then_plant):
            problems, found, inside = self.judge()
        self.assertFalse(self.marker.exists(), 'a cache planted after the check was executed by the identity run')
        self.assertEqual(found.get('exit'), 0)
        self.assertEqual(problems, [])                    # what ran was the verified source; the next check of the venv sees the cache
        self.assertTrue(any('.pyc' in p for p in hotfix().verify_installed(self.venv, self.art, baseline=self.baseline)[0]))
        self.assertFalse(self.marker.exists())

    # ---- rollback: the old runtime ------------------------------------------------------------------------------------------------
    def test_old_runtime_with_a_planted_cache_is_refused_before_any_of_its_programs(self):
        tree = hotfix().venv_tree(self.venv)
        current = {'key': 'k', 'old_venv': str(self.venv)}
        prepared = [{'key': 'k', 'seq': 7, 'old_runtime': {'digest': hotfix().content_hash(tree)}}]
        with patch.object(hotfix(), '_records', return_value=prepared):
            self.assertEqual(hotfix()._old_runtime(None, 'FB-x', current), [], 'control: the recorded old runtime is accepted')
            self.plant('onecrew/v2/messages.py')
            started, real = [], hotfix().run
            def spy(argv, *args, **kw):
                started.append(str(argv[0])); return real(argv, *args, **kw)
            with patch.object(hotfix(), 'run', spy):
                problems = hotfix()._old_runtime(None, 'FB-x', current)
        self.assertTrue(any('.pyc' in p or 'bytecode' in p for p in problems), problems)
        self.assertFalse(self.marker.exists())
        self.assertEqual([a for a in started if Path(a).name.lower().startswith('onecrew')], [])


if __name__ == '__main__':
    unittest.main()
