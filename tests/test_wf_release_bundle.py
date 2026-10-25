"""T54 [E1]-[E5], [E9], [E10] (W40-R01 … W40-RX2, shared framework): the release-bundle PRODUCER writes a bundle of REAL local observations
that `wfkit.release_check` validates point by point, and says exactly what it cannot supply.

One real run of `wfkit.release_bundle.Producer` for R01 on generated fixtures (the W41 drill: previous build d3120c6 and the current
checkout as two wheels in one venv; installed scenario; events on a legacy anchor compared with the unmodified old tree; refused and
allowed rollback; roll-forward). Expected: T54.1 installed, T54.2 upgrade, T54.3 events and T54.4 rollback PASS on real receipts
(`simulated: False`, provenance real, wheel hash of the current build in every receipt — [E9]); INPUTS is REFUSED because no previous
delivery gate receipt exists (the recorded external blocker); T54.5 follows the release notes' "Fixture checks" line. Every state root the
receipts name lies inside the sandbox ([E10]); the monitored live files are unchanged. Counter-examples: a receipt changed by one byte is
refused (hash), and a bundle that claims `gate_history` from a receipt of another build is refused.
"""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from wfkit import release_bundle, release_check


class ReleaseBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='wf-bundle-test-')
        cls.out = Path(cls.temp.name) / 'bundle'
        cls.producer = release_bundle.Producer('R01', cls.out)
        cls.verdict = cls.producer.execute()
        cls.bundle = json.loads((cls.out / 'bundle.json').read_text(encoding='utf-8'))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def receipt(self, ref):
        return json.loads((self.out / ref['path']).read_text(encoding='utf-8'))

    def test_e1_e4_the_four_observed_points_pass_on_real_receipts_and_inputs_names_the_external_blocker(self):
        conditions = self.verdict['conditions']
        self.assertEqual({k: conditions[k] for k in ('T54.1', 'T54.2', 'T54.3', 'T54.4')}, {'T54.1': True, 'T54.2': True, 'T54.3': True, 'T54.4': True}, self.verdict)
        self.assertFalse(conditions['INPUTS'])
        self.assertIn('previous delivered gate history missing', {r['detail'] for r in self.verdict['reasons'] if r['code'] == 'INPUTS'})
        self.assertEqual(self.bundle['gate_history'], []); self.assertEqual(self.bundle['mode'], 'real')
        self.assertNotIn('first_release', self.bundle); self.assertFalse(self.verdict['first_release'])    # bootstrap only when asked
        self.assertEqual([b['condition'] for b in self.bundle['blockers']], ['INPUTS'])
        self.assertFalse(self.verdict['owner_acceptance'])
        self.assertNotIn('simulated_receipts_used', {k for k, v in self.verdict.items() if v is True})

    def test_e9_every_receipt_is_real_and_carries_the_current_build_identity(self):
        current = self.bundle['artifacts']['current']
        for name, ref in self.bundle['checks'].items():
            row = self.receipt(ref)
            self.assertFalse(row['simulated'], name); self.assertEqual(row['provenance']['kind'], 'real', name)
            self.assertEqual((row['commit'], row['wheel_sha256']), (current['commit'], current['wheel_sha256']), name)
            self.assertEqual(row['kind'], name); self.assertEqual(row['release'], 'R01')
        old_run = self.receipt(self.receipt(self.bundle['checks']['rollback'])['allowed']['old_run'])
        self.assertEqual(old_run['wheel_sha256'], self.bundle['artifacts']['previous']['wheel_sha256'])   # the old run really ran the previous wheel
        wheel = self.out / current['wheel']
        self.assertEqual(hashlib.sha256(wheel.read_bytes()).hexdigest(), current['wheel_sha256'])

    def test_e10_everything_ran_inside_the_sandbox_and_live_files_are_unchanged(self):
        sandbox = Path(self.bundle['sandbox']).resolve()
        for name in ('installed', 'upgrade'):
            row = self.receipt(self.bundle['checks'][name])
            self.assertTrue(Path(row['state_root']).resolve().is_relative_to(sandbox), name)
        rollback = self.receipt(self.bundle['checks']['rollback'])
        for branch in (rollback['rejected'], rollback['allowed']):
            self.assertTrue(Path(branch['scan']['state_root']).resolve().is_relative_to(sandbox))
            self.assertTrue(branch['scan']['read_only'])
        self.assertTrue(self.bundle['monitored_files'])
        for row in self.bundle['monitored_files']:
            self.assertEqual(row['before'], row['after'], row['path'])
            self.assertFalse(Path(row['path']).resolve().is_relative_to(sandbox))

    def test_e2_e3_upgrade_rows_keep_the_unknown_attempt_and_events_are_class_0_or_a_on_the_legacy_anchor(self):
        upgrade = self.receipt(self.bundle['checks']['upgrade'])
        self.assertEqual(upgrade['before'], upgrade['after'])
        self.assertTrue(any(a['status'] == 'unknown' for row in upgrade['after'] for a in row['attempts']))
        events = self.receipt(self.bundle['checks']['events'])
        legacy = [e for e in events['new_events'] if e['anchor'].startswith('plan:')]
        self.assertTrue(legacy); self.assertEqual({e['class'] for e in legacy} - {'0', 'A'}, set())
        self.assertEqual(events['class_b_on_legacy_anchor'], [])
        self.assertTrue(all(c['compare']['S'] and c['compare']['G'] and c['compare']['C'] for c in events['comparisons']))
        self.assertIn('verdict.run_started', {e['kind'] for e in legacy})                                        # class A written by the current code on the legacy anchor
        self.assertTrue({'verdict.run_started', 'verdict.receipt_issued', 'verdict.recorded'} <= set(events['observed_kinds']))
        # known limit, recorded: the legacy root was approved by the OLD build without a base artifact, so the new build's test-integrity check
        # cannot be established and the passing command is `inconclusive` -> the milestone is `failed`, with the reason in the receipt
        # P1-D: the legacy root approved by the OLD build (fixture approval, no base artifact, no commit before it) CONTINUES through the owner-recorded
        # baseline route: first verdict inconclusive with the no-baseline reason, baseline recorded from the sample project's first commit, second
        # verdict passed. Nothing is passed by default.
        route = events['baseline_route']
        self.assertIsNotNone(route, 'the fixture approval has no baseline: the route must have been exercised')
        self.assertEqual(route['first_verdict'], 'inconclusive'); self.assertIn('no approved baseline', route['reason'])
        self.assertEqual(route['second_verdict'], 'passed'); self.assertEqual(events['legacy_milestone'], 'passed')
        self.assertTrue(route['baseline']['tree'])
        # T54.3 is judged against the validator's inventory, not the producer's choice
        from wfkit import release_check
        table = release_check.inventory('R01')
        self.assertEqual(events['expected_kinds'], table['kinds']); self.assertTrue(set(table['kinds']) <= set(events['observed_kinds']))
        self.assertTrue({c['kind'] for c in events['comparisons']} >= {k for k in table['kinds']})
        self.assertTrue(all(c['compare']['S'] and c['compare']['G'] and c['compare']['C'] for c in events['comparisons']))

    def test_e1_installed_point_is_behaviour_scenarios_not_imports(self):
        installed = self.receipt(self.bundle['checks']['installed'])
        scenarios = installed['scenarios']
        self.assertGreaterEqual(len(scenarios), 3)
        for r in scenarios:
            self.assertEqual(r['result'], 'pass', (r['scenario'], r['reasons']))
            self.assertTrue(r['assertions']); self.assertTrue(all(a['ok'] for a in r['assertions']))
            self.assertEqual(r['boundary_violations'], [])
            self.assertTrue(set(r['expected_events']) <= set(r['observed_events']))
        proven = {req.split()[0] for r in scenarios for req in r['requirements']}
        from wfkit import release_check
        self.assertTrue(set(release_check.inventory('R01')['tasks']) <= proven, proven)

    def test_e5_the_notes_point_follows_the_four_state_lines(self):
        notes = self.receipt(self.bundle['checks']['notes'])
        states = dict(line.split(': ', 1) for line in notes['markdown'].splitlines() if line.split(': ', 1)[0] in ('Code', 'Fixture checks', 'Real checks', 'Acceptance'))
        self.assertEqual(set(states), {'Code', 'Fixture checks', 'Real checks', 'Acceptance'})
        self.assertEqual(states['Acceptance'], 'not-requested'); self.assertEqual(states['Real checks'], 'not-run')
        self.assertEqual(self.verdict['conditions']['T54.5'], states['Fixture checks'] == 'passed')

    def test_counter_a_changed_receipt_byte_and_a_borrowed_gate_history_are_refused(self):
        tampered = copy.deepcopy(self.bundle)
        path = self.out / tampered['checks']['upgrade']['path']
        original = path.read_bytes()
        try:
            path.write_bytes(original.replace(b'"result": "pass"', b'"result": "pass "', 1))
            verdict = release_check.decide(tampered, self.out, allow_simulated=False)
            self.assertFalse(verdict['conditions']['T54.2']); self.assertIn('receipt hash changed', ' '.join(r['detail'] for r in verdict['reasons']))
        finally:
            path.write_bytes(original)
        borrowed = copy.deepcopy(self.bundle)
        borrowed['gate_history'] = [borrowed['checks']['installed']]                 # a receipt of the CURRENT build posing as the previous delivery
        verdict = release_check.decide(borrowed, self.out, allow_simulated=False)
        self.assertFalse(verdict['conditions']['INPUTS'])
        self.assertTrue(verdict['conditions']['T54.1'])                              # the real points are unaffected by the forged history


class FirstReleaseFieldTests(unittest.TestCase):
    """Directive section 6 (vii): the producer writes the first-release (bootstrap) claim ONLY when explicitly asked, and never labels the
    baseline delivered or accepted."""
    previous = {'commit': 'd3120c65baa846a84f5c177e117d9d93fd77f2a0', 'wheel_sha256': '4c5b81fe8b5f1301c426601d1e0eca481d3e0ce602fd60252502d768a7b469a1'}

    def test_default_keeps_the_external_inputs_blocker_and_writes_no_claim(self):
        fields, blockers = release_bundle.prerequisite_fields(False, self.previous)
        self.assertEqual(fields, {}); self.assertEqual([b['condition'] for b in blockers], ['INPUTS'])
        self.assertFalse(release_bundle.parser().parse_args(['R01', '--out', 'x']).first_release)
        import inspect
        self.assertIs(inspect.signature(release_bundle.Producer).parameters['first_release'].default, False)

    def test_asked_writes_the_pinned_compat_baseline_never_delivered_or_accepted(self):
        fields, blockers = release_bundle.prerequisite_fields(True, self.previous)
        self.assertEqual(fields['first_release']['baseline'], {**self.previous, 'role': 'compat-baseline', 'delivered': False, 'accepted': False})
        self.assertTrue(fields['first_release']['reason'])
        self.assertEqual([b['condition'] for b in blockers], ['INPUTS(bootstrap)'])
        self.assertTrue(release_bundle.parser().parse_args(['R01', '--out', 'x', '--first-release']).first_release)
