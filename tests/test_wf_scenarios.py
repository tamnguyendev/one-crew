"""T54.1 / T54.3 (W40 framework): every declared installed-build behaviour scenario passes on a wheel built from this checkout and installed
into a clean venv, and the observed event kinds cover the release's declared inventory (wfkit/release_events.json).

Select releases with WF_SCENARIO_RELEASES=R01,R05 (default: all). Counter-examples (the framework refuses what proves nothing): a body without
an assertion is refused at registration; a body whose feature path is disabled fails its assertion; a body that does not write a declared
kind fails with the missing kinds named; a scenario run with the checkout on sys.path fails the module boundary.
"""
import json
import os
import shutil
import unittest
from pathlib import Path

from tests import wf_scenarios as sc
from tests import wf_wheel as wh

INVENTORY = json.loads((Path(__file__).resolve().parents[1] / 'wfkit' / 'release_events.json').read_text(encoding='utf-8'))['releases']


class ScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs = wh._runs()
        cls.wheel, _, (modules, packages) = wh.build_wheel(cls.runs)
        cls.python = wh.make_venv(cls.runs)
        wh.install(cls.python, cls.wheel)
        cls.ctx = wh.build_ctx(cls.python, modules, packages)
        cls.releases = [r for r in sc.RELEASES if r in (os.environ.get('WF_SCENARIO_RELEASES') or ','.join(sc.RELEASES)).split(',')]
        sc.load()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.runs, ignore_errors=True)

    def test_every_declared_scenario_passes_and_covers_the_release_inventory(self):
        for release in self.releases:
            with self.subTest(release=release):
                entries = sc.scenarios(release)
                self.assertTrue(entries, release + ': no scenario declared')
                receipts = sc.run_release(release, self.python, self.ctx, self.runs / release, 'c' * 40, 'd' * 64)
                for r in receipts:
                    self.assertEqual(r['result'], 'pass', (release, r['scenario'], r['reasons'], r['error'], [a for a in r['assertions'] if not a['ok']][:3]))
                    self.assertTrue(r['assertions'])
                observed = set().union(*(set(r['observed_events']) for r in receipts))
                expected = set(INVENTORY[release]['kinds'])
                self.assertEqual(expected - observed, set(), release + ': inventory kinds not written by the scenarios')
                proven = {r.split()[0] for rc in receipts for r in rc['requirements']}          # the same reading as release_check.installed
                self.assertEqual(set(INVENTORY[release]['tasks']) - proven, set(), release + ': release tasks without a behaviour scenario')
                if not expected:
                    self.assertTrue(all(r['no_new_events'] for r in receipts), release + ': a release with no new kind must declare why')

    def test_counter_examples_the_framework_refuses(self):
        with self.assertRaisesRegex(ValueError, 'assertion'):
            sc.register('R01', 'bad-import-only', ['x'], ['proposal.checked'], 'import onecrew.v2.plan\n')
        with self.assertRaisesRegex(ValueError, 'task id'):                  # "W17: text" or "W36/W18 text" would be read as no task by T54.1
            sc.register('R01', 'bad-task-token', ['W47: proposal check'], ['proposal.checked'], 'check("x", True)\n')
        with self.assertRaisesRegex(ValueError, 'task id'):
            sc.register('R01', 'bad-task-token2', ['W36/W18 holds'], ['proposal.checked'], 'check("x", True)\n')
        with self.assertRaisesRegex(ValueError, 'expected event kinds'):
            sc.register('R01', 'bad-no-events', ['x'], [], 'check("a", True)\n')
        disabled = {'release': 'R01', 'id': 'ce-disabled-feature', 'requirements': ['counter-example'], 'expected_events': ['proposal.checked'], 'no_new_events': None,
                    'body': 'import onecrew.v2.step0 as s\ncheck("module imports", True)\n'}          # the feature path is never called: no event
        r = sc.run_scenario(disabled, self.python, self.ctx, self.runs / 'ce', 'c' * 40, 'd' * 64)
        self.assertEqual(r['result'], 'fail'); self.assertEqual(r['missing_events'], ['proposal.checked'])
        empty = {'release': 'R02', 'id': 'ce-empty-result', 'requirements': ['counter-example'], 'expected_events': ['learning.outcome'], 'no_new_events': None,
                 'body': 'from onecrew.v2 import outcome\ncheck("outcomes empty is not a result", bool(outcome.outcomes(ledger, "P1")) if False else False)\n'}
        r = sc.run_scenario(empty, self.python, self.ctx, self.runs / 'ce', 'c' * 40, 'd' * 64)
        self.assertEqual(r['result'], 'fail'); self.assertTrue(any('failed assertions' in x for x in r['reasons']))


class BoundaryCounterExample(unittest.TestCase):
    def test_a_checkout_on_sys_path_is_a_boundary_violation(self):
        from onecrew.v2 import boundary
        ctx = {'modules': {'onecrew.v2.plan'}, 'packages': set(), 'parents': set(), 'record_files': set(), 'stdlib_names': set(), 'ref': {}, 'builtin': set(),
               'marker_dirs': [], 'dep_tops': set(), 'dep_files': set(), 'base_exempt': set(), 'driver': None}
        here = str(Path(__file__).resolve().parents[1] / 'onecrew' / 'v2' / 'plan.py')
        self.assertTrue(boundary.violations({'onecrew.v2.plan': {'file': here, 'origin': here, 'frozen': False, 'builtin': False}}, ctx))
