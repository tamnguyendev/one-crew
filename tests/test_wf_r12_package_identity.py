"""Round 12 finding P2-D: every REQUIRED gate receipt must name the build's commit AND wheel; a good checksum proves bytes, not consistency.

Counterexamples run on temp COPIES of a small package built by build_package.py from a fake gate dir (never on a real package):
  (a) right commit, wrong wheel in one receipt        (b) right wheel, wrong commit
  (c) a required field missing                         (d) invalid JSON / not an object / unreadable receipt
  (e) a receipt or bundle of another run mixed in      (f) SHA256SUMS rewritten so bytes match, inner identities contradictory
  (g) a consistent evidence set passes                 (h) refused/blocked bundle results are kept and the package still passes
The same cases run BEFORE the build (build_package.check_one_build) against the gate dir.
"""
import json
import shutil
import sys
import unittest
from pathlib import Path

from wfkit import package_check as pc
from tests import test_wf_r11_build_package as r11

ROOT = Path(__file__).resolve().parents[1]
FULL, OTHER, jwrite, sha = r11.FULL, r11.OTHER, r11.jwrite, r11.sha
verify_kit = sys.modules['build_package'].verify_kit
BAD_WHEEL = 'f' * 64


def sums_step_bad(pkg):
    """The shipped verifier's `sha256sums` step, as written in package_check._verify: files listed in SHA256SUMS that are missing or changed."""
    sums = dict(line.split('  ', 1)[::-1] for line in (Path(pkg) / 'SHA256SUMS').read_text(encoding='utf-8').splitlines() if line.strip())
    return [f for f, h in sums.items() if not (Path(pkg) / f).exists() or sha(Path(pkg) / f) != h]


def read(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


class PackageCopyBase(r11.BuildPackageBase):
    """A built, consistent package plus a fresh copy per test to tamper with."""

    def setUp(self):
        super().setUp()
        self.built = self.build()
        self.pkg = self.tmp / 'copy'
        shutil.copytree(self.built, self.pkg)
        self.rdir = self.pkg / 'gate' / 'receipts'

    def reasons(self):
        return pc.package_scope(self.pkg)['reasons']

    def assert_refused(self, *needles):
        r = self.reasons()
        self.assertTrue(any(all(n in x for n in needles) for x in r), (needles, r))

    def receipt(self, name):
        return read(self.rdir / name)

    def put(self, name, **fields):
        d = self.receipt(name)
        d.update(fields)
        jwrite(self.rdir / name, d)

    def drop(self, name, field):
        d = self.receipt(name)
        del d[field]
        jwrite(self.rdir / name, d)


class ReceiptIdentityInThePackageTests(PackageCopyBase):
    # (g)
    def test_consistent_evidence_set_passes(self):
        self.assertEqual(self.reasons(), [])
        self.assertEqual(sums_step_bad(self.pkg), [])

    # (a)
    def test_right_commit_wrong_wheel_in_one_receipt_is_refused_naming_it(self):
        self.put('KN-a.json', wheel_sha256=BAD_WHEEL)
        self.assert_refused('KN-a.json', 'wheel sha256', self.wsha)
        self.assertEqual(self.receipt('KN-a.json')['commit'], FULL)             # the commit alone was right: that is the P2-D hole

    # (b)
    def test_right_wheel_wrong_commit_is_refused(self):
        self.put('KN-i.json', commit=OTHER)
        self.assert_refused('KN-i.json', 'commit')

    # (c)
    def test_each_missing_required_field_is_refused_not_skipped(self):
        for field in ('commit', 'wheel_sha256'):
            with self.subTest(field=field):
                shutil.rmtree(self.pkg)
                shutil.copytree(self.built, self.pkg)
                self.drop('KN-a.json', field)
                self.assert_refused('KN-a.json', 'no ' + field)

    def test_non_string_field_is_refused(self):
        self.put('KN-a.json', wheel_sha256=None)
        self.assert_refused('KN-a.json', 'wheel_sha256')

    # (d)
    def test_invalid_json_empty_non_object_and_unreadable_receipts_are_refused(self):
        for label, write in (('invalid', lambda p: p.write_text('{ not json', encoding='utf-8')),
                             ('empty', lambda p: p.write_bytes(b'')),
                             ('non-utf8', lambda p: p.write_bytes(b'\xff\xfe\x00{')),
                             ('list', lambda p: p.write_text('[]', encoding='utf-8'))):
            with self.subTest(label):
                shutil.rmtree(self.pkg)
                shutil.copytree(self.built, self.pkg)
                write(self.rdir / 'KN-a.json')
                self.assert_refused('KN-a.json')

    def test_unreadable_receipt_a_directory_in_its_place_is_refused(self):
        (self.rdir / 'KN-a.json').unlink()
        (self.rdir / 'KN-a.json').mkdir()
        self.assert_refused('KN-a.json')

    # wheel_used
    def test_wheel_used_of_another_wheel_or_not_a_list_is_refused(self):
        self.put('KN-i.json', wheel_used=[BAD_WHEEL])
        self.assert_refused('KN-i.json', 'wheel_used')
        self.put('KN-i.json', wheel_used=self.wsha)
        self.assert_refused('KN-i.json', 'wheel_used')

    # (e)
    def test_receipt_of_another_run_with_foreign_identity_is_refused(self):
        jwrite(self.rdir / 'KN-zzz.json', {'check': 'KN/zzz', 'commit': OTHER, 'wheel_sha256': BAD_WHEEL, 'wheel_used': []})
        r = self.reasons()
        self.assertTrue(any('KN-zzz.json' in x and 'commit' in x for x in r), r)
        self.assertTrue(any('KN-zzz.json' in x and 'wheel sha256' in x for x in r), r)

    def test_a_receipt_count_that_contradicts_the_gate_decision_is_refused(self):
        (self.rdir / 'KN-a.json').unlink()
        self.assert_refused('2 receipts', 'holds 1')

    def test_bundle_of_another_run_is_refused(self):
        rc = self.pkg / 'bundles' / 'R01' / 'release-check.json'
        d = read(rc)
        d['wheel_sha256'] = BAD_WHEEL
        jwrite(rc, d)
        self.assert_refused('bundles/R01/release-check.json', 'wheel')

    def test_bundle_json_of_another_build_is_refused(self):
        bj = self.pkg / 'bundles' / 'R01' / 'bundle.json'
        jwrite(bj, {'schema': 1, 'release': 'R01', 'artifacts': {'current': {'commit': OTHER, 'wheel_sha256': self.wsha}}})
        self.assert_refused('bundles/R01/bundle.json', 'commit')
        jwrite(bj, {'schema': 1, 'release': 'R01', 'artifacts': {'current': {'commit': FULL, 'wheel_sha256': BAD_WHEEL}}})
        self.assert_refused('bundles/R01/bundle.json', 'wheel_sha256')

    def test_produced_bundle_without_its_release_check_or_with_unreadable_one_is_refused(self):
        rc = self.pkg / 'bundles' / 'R01' / 'release-check.json'
        rc.write_text('{ broken', encoding='utf-8')
        self.assert_refused('R01', 'release-check.json')
        rc.unlink()
        self.assert_refused('R01', 'release-check.json', 'missing')

    # (f)
    def test_checksum_valid_but_inner_identities_contradictory_is_refused_by_identity(self):
        self.put('KN-a.json', wheel_sha256=BAD_WHEEL)                         # exactly the Codex P2-D reproduction
        self.assertNotEqual(sums_step_bad(self.pkg), [])                      # before: the checksum step notices the changed bytes
        verify_kit.write_sums(self.pkg)                                       # ... so the attacker rewrites SHA256SUMS
        self.assertEqual(sums_step_bad(self.pkg), [])                         # the byte-integrity step now PASSES
        self.assert_refused('KN-a.json', 'wheel sha256')                      # the identity step still refuses
        self.assertNotEqual(pc.package_scope(self.pkg)['reasons'], [])

    # (h)
    def test_refused_bundle_result_is_kept_and_the_package_still_passes_identity(self):
        res = self.pkg / 'bundles' / 'RP' / 'bundle-result.json'
        self.assertTrue(res.is_file())
        self.assertNotIn('commit', read(res))                                  # produced:false has no commit / wheel: that is fine
        self.assertIs(self.manifest(self.pkg)['bundles']['RP']['produced'], False)
        self.assertEqual(self.reasons(), [])

    def test_refused_bundle_result_must_still_match_the_manifest_decision(self):
        res = self.pkg / 'bundles' / 'RP' / 'bundle-result.json'
        d = read(res)
        d['decision'] = 'pass'
        jwrite(res, d)
        self.assert_refused('bundle RP', 'bundle-result.json')

    def test_refused_bundle_claiming_to_be_produced_is_refused(self):
        res = self.pkg / 'bundles' / 'RP' / 'bundle-result.json'
        d = read(res)
        d['produced'] = True
        jwrite(res, d)
        self.assert_refused('bundle RP', 'produced')


class RequiredReceiptsFromTheGateExpectationTests(PackageCopyBase):
    """The required set is the gate's own: registry snapshot (docs/development-testcases.json) x decision.releases, trusted when its size is
    decision.implementation_checks.expected; else the receipts directory listing, whose size must equal decision.implementation_checks.receipted."""

    def use_registry(self):
        registry = {'releases': {'KN': {'testcases': {'check.a': {'modules': ['tests.test_a']}, 'check.i': {'modules': ['tests.test_i'], 'installed': True}}}}}
        jwrite(self.pkg / 'docs' / 'development-testcases.json', registry)
        for name in ('decision.json',):
            d = read(self.pkg / 'gate' / name)
            d['releases'] = ['KN']
            jwrite(self.pkg / 'gate' / name, d)
        (self.rdir / 'KN-a.json').rename(self.rdir / 'KN-check.a.json')
        (self.rdir / 'KN-i.json').rename(self.rdir / 'KN-check.i.json')

    def test_registry_names_the_required_receipts_and_a_consistent_set_passes(self):
        self.use_registry()
        self.assertEqual(self.reasons(), [])

    def test_a_required_receipt_that_is_missing_is_refused(self):
        self.use_registry()
        (self.rdir / 'KN-check.i.json').unlink()
        self.assert_refused('KN-check.i.json', 'required by the gate', 'missing')

    def test_a_receipt_outside_the_gate_expectation_is_refused(self):
        self.use_registry()
        shutil.copy2(self.rdir / 'KN-check.a.json', self.rdir / 'KN-check.x.json')
        self.assert_refused('KN-check.x.json', 'not an expected check')

    def test_installed_check_must_record_the_wheel_it_consumed(self):
        self.use_registry()
        self.put('KN-check.i.json', wheel_used=[])
        self.assert_refused('KN-check.i.json', 'consumed')
        self.drop('KN-check.i.json', 'wheel_used')
        self.assert_refused('KN-check.i.json', 'wheel_used')

    def test_registry_of_another_size_is_not_trusted_and_the_listing_applies(self):
        self.use_registry()
        d = read(self.pkg / 'gate' / 'decision.json')
        d['implementation_checks']['expected'] = 5
        jwrite(self.pkg / 'gate' / 'decision.json', d)
        self.assertEqual(pc.required_receipt_names(d, read(self.pkg / 'docs' / 'development-testcases.json'))[0], None)


class DecisionAndGateIdentityTests(PackageCopyBase):
    def test_gate_decision_of_another_wheel_is_refused(self):
        d = read(self.pkg / 'gate' / 'decision.json')
        d['wheel_sha256'] = BAD_WHEEL
        jwrite(self.pkg / 'gate' / 'decision.json', d)
        self.assert_refused('gate/decision.json wheel_sha256')


class ReceiptsBeforeTheBuildTests(r11.BuildPackageBase):
    """The same rule in build_package.check_one_build: refused before anything is written."""

    def receipt_path(self, name='KN-a.json'):
        return self.gate / 'gate' / 'receipts' / name

    def tamper(self, name='KN-a.json', **fields):
        d = read(self.receipt_path(name))
        d.update(fields)
        jwrite(self.receipt_path(name), d)

    def assert_build_refused(self, *needles):
        with self.assertRaises(SystemExit) as cm:
            self.build()
        for n in needles:
            self.assertIn(n, str(cm.exception))
        self.assertFalse((self.tmp / 'pkg').exists())

    def test_consistent_inputs_build(self):                                    # (g)
        self.assertTrue(self.build().is_dir())

    def test_right_commit_wrong_wheel_is_refused_before_build(self):          # (a)
        self.tamper(wheel_sha256=BAD_WHEEL)
        self.assert_build_refused('KN-a.json', 'wheel sha256')

    def test_right_wheel_wrong_commit_is_refused_before_build(self):          # (b)
        self.tamper('KN-i.json', commit=OTHER)
        self.assert_build_refused('KN-i.json', 'commit')

    def test_missing_fields_are_refused_before_build(self):                   # (c)
        for field in ('commit', 'wheel_sha256'):
            with self.subTest(field=field):
                d = read(self.receipt_path())
                saved = dict(d)
                del d[field]
                jwrite(self.receipt_path(), d)
                self.assert_build_refused('KN-a.json', 'no ' + field)
                jwrite(self.receipt_path(), saved)

    def test_invalid_json_and_unreadable_receipts_are_refused_before_build(self):   # (d)
        self.receipt_path().write_text('{ nope', encoding='utf-8')
        self.assert_build_refused('KN-a.json')
        self.receipt_path().unlink()
        self.receipt_path().mkdir()
        self.assert_build_refused('KN-a.json')

    def test_receipt_of_another_run_is_refused_before_build(self):            # (e)
        jwrite(self.receipt_path('KN-zzz.json'), {'check': 'KN/zzz', 'commit': OTHER, 'wheel_sha256': BAD_WHEEL, 'wheel_used': []})
        self.assert_build_refused('KN-zzz.json')

    def test_wheel_used_of_another_wheel_is_refused_before_build(self):
        self.tamper('KN-i.json', wheel_used=[BAD_WHEEL])
        self.assert_build_refused('KN-i.json', 'wheel_used')

    def test_missing_receipt_against_the_decision_count_is_refused_before_build(self):
        self.receipt_path('KN-a.json').unlink()
        self.assert_build_refused('2 receipts', 'holds 1')

    def test_decision_of_another_wheel_is_refused_before_build(self):
        d = read(self.gate / 'decision.json')
        d['wheel_sha256'] = BAD_WHEEL
        jwrite(self.gate / 'decision.json', d)
        self.assert_build_refused('decision.json', 'wheel')

    def test_refused_bundle_results_do_not_block_the_build(self):             # (h)
        pkg = self.build()
        self.assertTrue((pkg / 'bundles' / 'RP' / 'bundle-result.json').is_file())
        self.assertEqual(pc.package_scope(pkg)['reasons'], [])


if __name__ == '__main__':
    unittest.main()
