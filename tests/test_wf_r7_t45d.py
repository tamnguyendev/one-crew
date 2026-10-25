"""T45d (PL, round 7) [E13] local kit rule: a monitored hook/config change is accepted by CG-KET (wfkit.finalgate KQ5) only with an
owner U2 that names the path and covers exactly that before/after hash pair, granted before the change.

Fixture bundle of tests.test_wf_finalgate (simulated receipts, gate rules only). Each variant breaks one property of the U2 on an
otherwise passing change and asserts KQ5 refuses with the matching reason. Not proven here (recorded in docs/wf/r7-c2-matrix.json):
the per-phase before/after hash (KQ5 compares one pair per file over the whole program) and the U2's count in the report's AC1 line.
"""
import unittest

from tests import test_wf_finalgate as base


class T45dHookConfigU2Tests(unittest.TestCase):
    def setUp(self):
        self.fx = base.FinalGateTests()
        self.addCleanup(self.fx.doCleanups)
        self.fx.setUp()
        self.row = self.fx.bundle['monitored_files'][0]
        self.row.update(after_sha256='f' * 64, changed_at='2026-10-24T13:00:00Z')

    def authorize(self, **override):
        values = dict(kind='U2', actor='owner', path=self.row['path'], before_sha256=self.row['before_sha256'],
                      after_sha256=self.row['after_sha256'])
        values.update(override)
        self.row['authorization'] = self.fx.receipt(self.fx.a, **values)

    def kq5(self):
        result = self.fx.run_gate()
        return result, [r['detail'] for r in result['reasons'] if r['code'] == 'KQ5']

    def test_e13_u2_must_be_the_owners_name_the_path_and_cover_the_exact_change(self):
        self.authorize()
        result, details = self.kq5()
        self.assertEqual(result['decision'], 'pass', result)
        for override, reason in (({'actor': 'codex'}, 'hook/config changed without U2'),
                                 ({'kind': 'U1'}, 'hook/config changed without U2'),
                                 ({'path': 'other/settings.json'}, 'hook/config changed without U2'),
                                 ({'result': 'fail'}, 'hook/config changed without U2'),
                                 ({'after_sha256': '1' * 64}, 'U2 does not cover this change'),
                                 ({'before_sha256': '1' * 64}, 'U2 does not cover this change')):
            with self.subTest(override=override):
                self.authorize(**override)
                result, details = self.kq5()
                self.assertEqual(result['decision'], 'refused', result)
                self.assertTrue(any(reason in d for d in details), details)


if __name__ == '__main__':
    unittest.main()
