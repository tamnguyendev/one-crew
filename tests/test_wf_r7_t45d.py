"""T45d (PL, round 7) [E13] local kit rule: a monitored hook/config change is accepted by CG-KET (wfkit.finalgate KQ5) only with an
owner U2 that names the path and covers exactly that before/after hash pair, granted before the change.

Fixture bundle of tests.test_wf_finalgate (simulated receipts, gate rules only). Each variant breaks one property of the U2 on an
otherwise passing change and asserts KQ5 refuses with the matching reason.

Round 7 D (GAP 4): the hashes are checked PER PHASE. A monitored row that changed carries `phases` {PL-A, PL-B: before/after} whose
ends match the program pair; each changed segment (inside PL-A, between the phases, inside PL-B) needs its own owner U2 covering that
exact pair, granted before the change, the change inside the segment's window. A change without per-phase hashes cannot be located
and is refused; a change made in PL-A and reverted before the end is no longer invisible. A U2 that authorises a change is counted in
the AC1 owner-decision count of the pilot report (the T35c completion receipt's `owner_decisions`, the pilot_report schema): exactly
one U2 action names that U2 receipt and the job's AC1 table counts it; the same U2 cannot authorise two changes. An unchanged row
keeps the old two-hash format (every other finalgate fixture).
"""
import unittest

from tests import test_wf_finalgate as base

E, F = 'e' * 64, 'f' * 64


class T45dHookConfigU2Tests(unittest.TestCase):
    def setUp(self):
        self.fx = base.FinalGateTests()
        self.addCleanup(self.fx.doCleanups)
        self.fx.setUp()
        self.row = self.fx.bundle['monitored_files'][0]
        # The change happens inside PL-B (2026-10-23 13:00-14:00), one hash pair per phase.
        self.row.update(after_sha256=F, phases={'PL-A': {'before_sha256': E, 'after_sha256': E},
                                                'PL-B': {'before_sha256': E, 'after_sha256': F}},
                        changes={'PL-B': {'changed_at': '2026-10-23T13:30:00Z'}})

    def u2(self, before=E, after=F, **override):
        values = dict(kind='U2', actor='owner', path=self.row['path'], before_sha256=before, after_sha256=after, at='2026-10-23T13:10:00Z')
        values.update(override)
        return self.fx.receipt(self.fx.a, **values)

    def authorize(self, segment='PL-B', **override):
        ref = self.u2(**override)
        self.row['changes'][segment]['authorization'] = ref
        return ref

    def count(self, *refs, per_job=None, job='J1'):
        """The pilot report's AC1 section (pilot_report schema) on the T35c completion receipt: one U2 action per authorising U2."""
        actions = [{'job': job, 'at': '2026-10-23T13:10:00Z', 'verb': 'request reply', 'kind': 'U2', 'sources': ['ledger'],
                    'authorization': ref['sha256']} for ref in refs]
        table = per_job if per_job is not None else {job: {'U2': len(refs)}}
        self.fx.edit(self.fx.bundle['phases']['PL-B']['completion']['T35c'],
                     owner_decisions={'actions': actions, 'mismatches': [], 'per_job': table,
                                      'ac1': {'max_per_job': 2, 'outside_u1_u4': 0, 'status': 'đạt'}})

    def kq5(self):
        result = self.fx.run_gate()
        return result, [r['detail'] for r in result['reasons'] if r['code'] == 'KQ5']

    def assert_kq5(self, reason):
        result, details = self.kq5()
        self.assertEqual(result['decision'], 'refused', result)
        self.assertTrue(any(reason in d for d in details), details)

    def test_e13_u2_must_be_the_owners_name_the_path_and_cover_the_exact_change(self):
        self.count(self.authorize())
        result, details = self.kq5()
        self.assertEqual(result['decision'], 'pass', result)
        for override, reason in (({'actor': 'codex'}, 'hook/config changed without U2'),
                                 ({'kind': 'U1'}, 'hook/config changed without U2'),
                                 ({'path': 'other/settings.json'}, 'hook/config changed without U2'),
                                 ({'result': 'fail'}, 'hook/config changed without U2'),
                                 ({'after': '1' * 64}, 'U2 does not cover this change'),
                                 ({'before': '1' * 64}, 'U2 does not cover this change'),
                                 ({'at': '2026-10-23T13:40:00Z'}, 'U2 granted after hook change')):
            with self.subTest(override=override):
                self.count(self.authorize(**override))
                self.assert_kq5(reason)

    def test_e13_a_change_without_per_phase_hashes_is_refused(self):
        # the old whole-program pair: changed, with an otherwise valid U2 - the change cannot be located in a phase
        del self.row['phases'], self.row['changes']
        self.row.update(changed_at='2026-10-23T13:30:00Z', authorization=self.u2())
        self.assert_kq5('per-phase hook/config hashes missing')

    def test_e13_a_change_in_pl_a_reverted_before_the_end_is_refused_without_u2(self):
        self.row.update(after_sha256=E, phases={'PL-A': {'before_sha256': E, 'after_sha256': F},
                                                'PL-B': {'before_sha256': F, 'after_sha256': E}}, changes={})
        self.assert_kq5('PL-A: hook/config changed without U2')

    def test_e13_a_change_between_the_phases_needs_its_own_u2(self):
        self.row['phases'] = {'PL-A': {'before_sha256': E, 'after_sha256': E}, 'PL-B': {'before_sha256': F, 'after_sha256': F}}
        self.row['changes'] = {}
        self.assert_kq5('between PL-A and PL-B: hook/config changed without U2')
        self.row['changes'] = {'between': {'changed_at': '2026-10-23T12:30:00Z'}}
        self.count(self.authorize('between', at='2026-10-23T12:10:00Z'))
        result, details = self.kq5()
        self.assertEqual(result['decision'], 'pass', result)

    def test_e13_phase_hashes_must_join_the_program_pair(self):
        self.count(self.authorize())
        self.row['phases']['PL-A']['before_sha256'] = '1' * 64
        self.assert_kq5('per-phase hashes do not join the program before/after')

    def test_e13_the_change_must_lie_in_its_phase_window(self):
        self.row['changes']['PL-B']['changed_at'] = '2026-10-23T15:30:00Z'
        self.count(self.authorize())
        self.assert_kq5('PL-B: change time outside the phase window')

    def test_e13_e10_u2_is_counted_once_in_ac1(self):
        ref = self.authorize()
        self.count(ref)
        self.assertEqual(self.kq5()[0]['decision'], 'pass')
        self.count()                                                             # the report does not count it
        self.assert_kq5('U2 not counted in AC1')
        self.count(ref, ref)                                                     # counted twice
        self.assert_kq5('U2 counted 2 times in AC1')
        self.count(ref, per_job={'J1': {'U2': 0}})                               # the action is there, the AC1 table misses it
        self.assert_kq5('AC1 table of J1 does not count its U2')
        self.fx.edit(self.fx.bundle['phases']['PL-B']['completion']['T35c'], owner_decisions=None)
        self.assert_kq5('AC1 owner decisions missing')

    def test_e13_one_u2_cannot_authorise_two_changes(self):
        # the same pair e -> f happens twice (in PL-A, and again in PL-B after a revert between the phases)
        self.row['phases'] = {'PL-A': {'before_sha256': E, 'after_sha256': F}, 'PL-B': {'before_sha256': E, 'after_sha256': F}}
        self.row['changes'] = {'PL-A': {'changed_at': '2026-10-23T10:30:00Z'}, 'between': {'changed_at': '2026-10-23T12:30:00Z'},
                               'PL-B': {'changed_at': '2026-10-23T13:30:00Z'}}
        a = self.authorize('PL-A', at='2026-10-23T10:10:00Z')
        between = self.authorize('between', before=F, after=E, at='2026-10-23T12:10:00Z')
        b = self.authorize('PL-B')
        self.count(a, between, b, per_job={'J1': {'U2': 3}})
        self.assertEqual(self.kq5()[0]['decision'], 'pass', self.kq5())
        self.row['changes']['PL-B']['authorization'] = a                         # the PL-A U2 reused for the second change
        self.count(a, between, per_job={'J1': {'U2': 2}})
        self.assert_kq5('one U2 authorises one change')


if __name__ == '__main__':
    unittest.main()
