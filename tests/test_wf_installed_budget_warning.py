"""Codex round 6 P1-1: the T36b [E17] 70% budget warning on the INSTALLED build.

executors.observe calls estimates.warn_budget after every observation, so every native node end runs the warning path. Round 5 imported
onecrew.budget_policy (v1, not in the wheel) there, and wheel 2.2.0.dev4 held every native node with "No module named 'onecrew.budget_policy'".
The shared threshold function now lives in onecrew.budget_core (shipped); v1's budget_policy re-exports it.

This module builds the wheel from this checkout, installs it into a clean venv under %TEMP% (outside the checkout), and runs the R04 scenario
r04-budget-warning-on-installed-engine there with ``-I`` and no PYTHONPATH (tests/wf_scenarios.run_scenario): an earlier attempt measured just
under 70%, then a native node end crosses it -> exactly one notice.exception (budget_warning), no request, no budget/deadline change, and the
nodes still go produced -> verified -> accepted -> handoff. The boundary check proves every onecrew module came from the venv.
"""
import shutil
import unittest

from tests import wf_scenarios as sc
from tests import wf_wheel as wh

SCENARIO = 'r04-budget-warning-on-installed-engine'


class InstalledBudgetWarningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs = wh._runs()
        cls.wheel, _, (modules, packages) = wh.build_wheel(cls.runs)
        cls.python = wh.make_venv(cls.runs)
        wh.install(cls.python, cls.wheel)
        cls.ctx = wh.build_ctx(cls.python, modules, packages)
        cls.modules = modules

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.runs, ignore_errors=True)

    def test_the_wheel_ships_the_warning_closure_and_not_the_v1_policy(self):
        self.assertIn('onecrew.budget_core', self.modules)
        self.assertIn('onecrew.task_intake', self.modules)
        self.assertNotIn('onecrew.budget_policy', self.modules)
        files = [f.replace('\\', '/') for f in wh.installed_record(self.python)['files']]
        self.assertTrue(any(f.endswith('onecrew/budget_core.py') for f in files), 'budget_core is not installed')
        self.assertFalse(any(f.endswith('onecrew/budget_policy.py') for f in files), 'the v1 policy module was installed')

    def test_budget_warning_fires_on_the_installed_engine_and_the_node_reaches_handoff(self):
        entry = next(e for e in sc.scenarios('R04') if e['id'] == SCENARIO)
        r = sc.run_scenario(entry, self.python, self.ctx, self.runs / 'scn', 'c' * 40, 'd' * 64)
        self.assertEqual(r['result'], 'pass', (r['reasons'], r['error'], [a for a in r['assertions'] if not a['ok']][:4]))
        names = [a['name'] for a in r['assertions'] if a['ok']]
        for must in ('exactly one budget warning, on the execution-seconds axis, written by that observation',
                     'the warning is in authority: no request, grants nothing, asks nothing',
                     'a later observation above the same threshold writes no second warning',
                     'the handoff returns the artifact of the verified integration and the candidate reaches the project'):
            self.assertIn(must, names)
        self.assertLessEqual({'executor.observed', 'notice.exception', 'node.produced', 'node.verification', 'node.accepted'}, set(r['observed_events']))
        self.assertEqual(r['boundary_violations'], [])
        self.assertTrue(r['modules'] and all('site-packages' in m['path'] for m in r['modules']), [m for m in r['modules'] if 'site-packages' not in m['path']][:3])


if __name__ == '__main__':
    unittest.main()
