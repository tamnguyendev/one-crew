"""Legacy-root continuation FROM a real handover package (WF_PACKAGE=<package dir>): the tool must pass its own judge, the first verdict must
be inconclusive, the AI session and the foreign commit must have been refused, and the milestone must pass after the owner's baseline. Skips
without WF_PACKAGE, so it is NOT in the gate registry (the gate forbids skips); run it on the built package and keep the report."""
import copy
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.test_wf_legacy_continuation_tool import get, lc

PACKAGE = Path(os.environ['WF_PACKAGE']) if os.environ.get('WF_PACKAGE') else None


@unittest.skipUnless(PACKAGE is not None and PACKAGE.is_dir(), 'WF_PACKAGE (a handover package dir) not set')
class RealPackageTests(unittest.TestCase):
    def test_real_package_passes_and_refused_the_ai_session_and_the_foreign_commit(self):
        base = Path(tempfile.mkdtemp(prefix='wf-legacy-'))
        try:
            lines = []
            report = lc.run(PACKAGE, base / 'work', out=lines.append)
            scope = lc.pc.package_scope(PACKAGE)                   # P1-3: the scope from the manifest + artifact
            self.assertEqual(report['package_identity'], lc.pc.identity(scope))
            self.assertEqual(lc.judge(report, scope), {'result': 'pass', 'reasons': []}, chr(10).join(lines[-8:]))
            first = get(report, 'legacy_passed_old_semantics')                 # decision 25/10 round 6: old root, old semantics
            self.assertEqual((first['result'], first['m1'], first['integrity']), ('pass', 'passed', None))
            self.assertNotEqual(get(report, 'baseline_ai_refused')['exit'], 0)
            self.assertNotEqual(get(report, 'baseline_bad_commit_refused')['exit'], 0)
            self.assertEqual(get(report, 'baseline_leaves_verdict_unchanged')['verdicts'], ['pass'])
            self.assertEqual(get(report, 'old_build_reads_after')['exit'], 0)
            forged = copy.deepcopy(report); get(forged, 'legacy_passed_old_semantics')['ok'] = False
            self.assertEqual(lc.judge(forged, scope)['result'], 'refused')
            forged = copy.deepcopy(report); forged['previous_wheel_present'] = False; forged['steps'] = []
            self.assertEqual(lc.judge(forged, scope)['result'], 'refused')
        finally:
            shutil.rmtree(base, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
