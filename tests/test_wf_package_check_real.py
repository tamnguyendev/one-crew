"""The real-package run of wfkit.package_check: needs WF_PACKAGE (a handover package directory) and a NEW work dir outside the checkout.
Kept OUT of the gate registry on purpose (the snapshot gate forbids skipped tests). Run by hand on the built package:
    WF_PACKAGE=D:/OneCrewRuns/wf-handover-<commit> python -m unittest tests.test_wf_package_check_real
"""
import copy
import os
import tempfile
import unittest
from pathlib import Path

from wfkit import package_check as pc
from test_wf_package_check import get

PACKAGE = Path(os.environ['WF_PACKAGE']) if os.environ.get('WF_PACKAGE') else None


@unittest.skipUnless(PACKAGE and PACKAGE.exists(), 'set WF_PACKAGE to a handover package directory')
class RealPackageTests(unittest.TestCase):

    def test_real_verifier_passes_judge_and_exercises_both_rollback_branches(self):
        base = Path(tempfile.mkdtemp(prefix='wf-pkgcheck-'))           # %TEMP%: a new work dir outside the checkout
        work = base / 'work'
        try:
            lines = []
            report = pc.run(PACKAGE, work, out=lines.append)
            self.assertTrue((work / 'verification' / 'verify-report.json').exists())
            verdict = pc.judge(report)
            self.assertEqual(verdict, {'result': 'pass', 'reasons': []}, '\n'.join(lines[-6:]))
            self.assertEqual(report['result'], 'pass')
            self.assertEqual(report['judge'], verdict)
            rb = report['rollback']
            self.assertGreater(rb['blocked']['scan_total'], 0)
            self.assertEqual(rb['blocked']['decision'], 'refused')
            self.assertEqual(rb['blocked']['pip_invocations'], 0)
            self.assertEqual(rb['blocked']['installed_before'], rb['blocked']['installed_after'])
            self.assertEqual(rb['blocked']['copy_before'], rb['blocked']['copy_after'])
            self.assertEqual(rb['clear']['scan_total'], 0)
            self.assertEqual(rb['clear']['decision'], 'allowed')
            self.assertEqual(rb['clear']['pip_invocations'], 4)
            self.assertEqual(rb['clear']['installed_before'], rb['clear']['installed_after'])
            neg = next(s for s in report['steps'] if s['id'] == 'clear_old_cannot_read_plan_ns')
            self.assertEqual(neg['kind'], 'negative')
            self.assertIn('No plan named', neg['stdout_tail'] + neg['stderr_tail'])
            # forging the saved report must be caught by the validator
            forged = copy.deepcopy(report)
            get(forged, 'help')['ok'] = False
            self.assertEqual(pc.judge(forged)['result'], 'refused')
            forged = copy.deepcopy(report)
            get(forged, 'verdict_run').update(mandatory=False, ok=False, exit=99)      # Codex P1-1 bypass 1
            self.assertEqual(pc.judge(forged)['result'], 'refused')
        finally:
            shutil.rmtree(base, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
