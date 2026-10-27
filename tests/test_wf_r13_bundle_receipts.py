"""Round 13 finding P2-B: the receipts INSIDE a bundle (bundles/<R>/receipts/*.json) are part of the evidence chain and are identity-checked by ROLE.

A correct SHA256SUMS proves bytes, not that the receipts a bundle certifies its result with belong to the build. Counterexamples run on temp COPIES of
a small package built by build_package.py from a fake gate dir (tests.test_wf_r11_build_package), never on a real package; the same cases run
BEFORE the build (build_package.check_one_build) against the producer's output directory, and through the verifier SHIPPED in the package:

  (a) checksums valid, one sub-receipt names the wrong wheel / commit (the Codex case)   -> refused, naming bundles/R01/receipts/<file>
  (b) a sub-receipt missing / invalid JSON / empty / a directory / not an object / undeclared, or a referenced hash that does not match -> refused
  (c) a consistent evidence set                                                          -> passes
  (d) previous-build receipts carry the PREVIOUS identity: correct for their role -> pass; the CURRENT wheel where the previous is expected, or the
      previous where the current is expected -> refused (role mismatch); a previous identity that is not the one the bundle pins -> refused
  (e) a bundle the producer refused (produced:false) stays in the package, with whatever receipts it has; it still passes identity
"""
import copy
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from wfkit import package_check as pc
from tests import test_wf_r11_build_package as r11
from tests import test_wf_r12_package_identity as r12

FULL, OTHER, jwrite, sha = r11.FULL, r11.OTHER, r11.jwrite, r11.sha
BAD_WHEEL = 'f' * 64
CURRENT_FILES = ('installed.json', 'upgrade.json', 'events.json', 'rollback.json', 'notes.json', 'rollback-forward-run.json')


def read(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def dump(path, obj):
    Path(path).write_bytes(json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=1).encode('utf-8'))


def repin(bdir):
    """What an attacker who also fixes the bundle's own hashes does: recompute rollback's old_run/forward_run refs, then bundle.json's checks."""
    bdir = Path(bdir)
    rb = read(bdir / 'receipts' / 'rollback.json')
    for holder, key in ((rb['allowed'], 'old_run'), (rb, 'forward_run')):
        holder[key]['sha256'] = sha(bdir / holder[key]['path'])
    dump(bdir / 'receipts' / 'rollback.json', rb)
    bj = read(bdir / 'bundle.json')
    for ref in bj['checks'].values():
        ref['sha256'] = sha(bdir / ref['path'])
    jwrite(bdir / 'bundle.json', bj)


class BundleCopyBase(r12.PackageCopyBase):
    """A built, consistent package (R01 produced with its evidence set, RP refused) plus a fresh copy per test."""

    def setUp(self):
        super().setUp()
        self.bdir = self.pkg / 'bundles' / 'R01'

    def edit(self, name, fn, pin=True, sums=True):
        path = self.bdir / 'receipts' / name
        d = read(path)
        fn(d)
        dump(path, d)
        if pin:
            repin(self.bdir)
        if sums:
            r12.verify_kit.write_sums(self.pkg)            # the checksums are consistent with the new bytes: they prove bytes only
        return d

    def refused(self, *needles):
        self.assert_refused(*needles)

    def rewrite_sums(self):
        r12.verify_kit.write_sums(self.pkg)


class SubReceiptIdentityTests(BundleCopyBase):
    # (c)
    def test_consistent_evidence_set_passes_with_previous_receipts_of_the_previous_build(self):
        self.assertEqual(self.reasons(), [])
        self.assertEqual(read(self.bdir / 'receipts' / 'rollback-old-run.json')['wheel_sha256'], r11.PREV_SHA)
        self.assertNotEqual(r11.PREV_SHA, self.wsha)

    # (a) the Codex finding, exactly: wheel_sha256 of events.json -> f*64, SHA256SUMS rewritten, nothing else touched
    def test_codex_case_events_wheel_changed_and_checksums_rewritten(self):
        path = self.bdir / 'receipts' / 'events.json'
        d = read(path)
        d['wheel_sha256'] = BAD_WHEEL
        dump(path, d)
        self.rewrite_sums()
        self.assertEqual(r12.sums_step_bad(self.pkg), [])          # the bytes are consistent
        self.refused('bundles/R01/receipts/events.json')
        self.refused('bundles/R01/receipts/events.json', 'wheel sha256', BAD_WHEEL)

    def test_same_case_with_the_bundle_hashes_fixed_too_is_still_refused_by_identity(self):
        self.edit('events.json', lambda d: d.update(wheel_sha256=BAD_WHEEL))
        self.assertEqual(r12.sums_step_bad(self.pkg), [])
        self.refused('bundles/R01/receipts/events.json', 'wheel sha256', BAD_WHEEL)
        self.assertFalse(any('bytes do not match' in x for x in self.reasons()), self.reasons())

    def test_every_current_receipt_with_a_wrong_wheel_or_commit_is_refused_naming_it(self):
        for name in CURRENT_FILES:
            for key, bad, needle in (('wheel_sha256', BAD_WHEEL, 'wheel sha256'), ('commit', OTHER, 'commit')):
                with self.subTest(file=name, key=key):
                    saved = read(self.bdir / 'receipts' / name)
                    self.edit(name, lambda d: d.update({key: bad}))
                    self.refused(f'bundles/R01/receipts/{name}', needle)
                    dump(self.bdir / 'receipts' / name, saved)
                    repin(self.bdir)
                    self.rewrite_sums()
                    self.assertEqual(self.reasons(), [])

    def test_missing_commit_or_wheel_field_is_refused_not_skipped(self):
        for name in CURRENT_FILES + ('rollback-old-run.json',):
            for key in ('commit', 'wheel_sha256'):
                with self.subTest(file=name, key=key):
                    saved = read(self.bdir / 'receipts' / name)
                    self.edit(name, lambda d: d.pop(key))
                    self.refused(f'bundles/R01/receipts/{name}', 'no ' + key)
                    dump(self.bdir / 'receipts' / name, saved)
                    repin(self.bdir)
                    self.rewrite_sums()

    def test_nested_current_identities_are_checked(self):
        cases = (('installed.json', lambda d: d['scenarios'][1].update(wheel_sha256=BAD_WHEEL), 'scenarios[1]'),
                 ('installed.json', lambda d: d['scenarios'][0].update(commit=OTHER), 'scenarios[0]'),
                 ('upgrade.json', lambda d: d['to'].update(wheel_sha256=BAD_WHEEL), ' to'),
                 ('notes.json', lambda d: d['gate_decision'].update(wheel_sha256=BAD_WHEEL), 'gate_decision'),
                 ('notes.json', lambda d: d['gate_decision']['snapshot'].update(commit=OTHER), 'gate_decision.snapshot'))
        for name, fn, where in cases:
            with self.subTest(file=name, where=where):
                saved = read(self.bdir / 'receipts' / name)
                self.edit(name, fn)
                self.refused(f'bundles/R01/receipts/{name}', where)
                dump(self.bdir / 'receipts' / name, saved)
                repin(self.bdir)
                self.rewrite_sums()
                self.assertEqual(self.reasons(), [])

    # (b)
    def test_missing_invalid_empty_non_object_and_unreadable_sub_receipts_are_refused(self):
        for name in CURRENT_FILES + ('rollback-old-run.json',):
            path = self.bdir / 'receipts' / name
            saved = path.read_bytes()
            for how in ('missing', 'invalid', 'empty', 'list', 'directory'):
                with self.subTest(file=name, how=how):
                    if path.is_dir():
                        path.rmdir()
                    elif path.exists():
                        path.unlink()
                    if how == 'invalid':
                        path.write_text('{ nope', encoding='utf-8')
                    elif how == 'empty':
                        path.write_bytes(b'')
                    elif how == 'list':
                        path.write_text('[]', encoding='utf-8')
                    elif how == 'directory':
                        path.mkdir()
                    self.rewrite_sums() if how != 'directory' else None
                    self.refused(f'bundles/R01/receipts/{name}')
                    if path.is_dir():
                        path.rmdir()
                    path.write_bytes(saved)
            self.rewrite_sums()
            self.assertEqual(self.reasons(), [])

    def test_a_referenced_hash_that_does_not_match_is_refused(self):
        bj = read(self.bdir / 'bundle.json')
        bj['checks']['notes']['sha256'] = 'a' * 64
        jwrite(self.bdir / 'bundle.json', bj)
        self.rewrite_sums()
        self.refused('bundles/R01/receipts/notes.json', 'bytes do not match')

    def test_rollback_receipt_hash_of_the_old_or_forward_run_must_match(self):
        for key in ('old_run', 'forward_run'):
            with self.subTest(key=key):
                path = self.bdir / 'receipts' / 'rollback.json'
                saved = path.read_bytes()
                d = read(path)
                (d['allowed'] if key == 'old_run' else d)[key]['sha256'] = 'a' * 64
                dump(path, d)
                repin_bj = read(self.bdir / 'bundle.json')
                repin_bj['checks']['rollback']['sha256'] = sha(path)
                jwrite(self.bdir / 'bundle.json', repin_bj)
                self.rewrite_sums()
                self.refused('bytes do not match')
                path.write_bytes(saved)
                repin(self.bdir)
                self.rewrite_sums()

    def test_a_receipt_nobody_declares_is_refused(self):
        dump(self.bdir / 'receipts' / 'events-02.json', {'kind': 'events', 'release': 'R01', 'commit': FULL, 'wheel_sha256': self.wsha})
        self.rewrite_sums()
        self.refused('bundles/R01/receipts/events-02.json', 'not declared')

    def test_a_declared_check_that_is_missing_from_bundle_json_is_refused(self):
        bj = read(self.bdir / 'bundle.json')
        del bj['checks']['upgrade']
        jwrite(self.bdir / 'bundle.json', bj)
        self.rewrite_sums()
        self.refused('bundles/R01/bundle.json', 'declares no upgrade receipt')

    def test_receipt_of_another_release_or_kind_is_refused(self):
        self.edit('events.json', lambda d: d.update(release='R02'))
        self.refused('bundles/R01/receipts/events.json', "belongs to release 'R02'")
        self.edit('events.json', lambda d: d.update(release='R01', kind='upgrade'))
        self.refused('bundles/R01/receipts/events.json', 'kind')

    def test_produced_bundle_without_bundle_json_or_with_unreadable_one_is_refused(self):
        (self.bdir / 'bundle.json').unlink()
        self.rewrite_sums()
        self.refused('bundles/R01/bundle.json', 'missing')
        (self.bdir / 'bundle.json').write_text('{ nope', encoding='utf-8')
        self.rewrite_sums()
        self.refused('bundles/R01/bundle.json')

    # (d) roles
    def test_previous_build_receipts_are_judged_against_the_previous_pin_not_the_current_wheel(self):
        self.assertEqual(self.reasons(), [])                       # rollback-old-run / upgrade.from / events.old_artifact carry r11.PREV_*
        self.edit('rollback-old-run.json', lambda d: d.update(wheel_sha256=self.wsha, commit=FULL))
        self.refused('bundles/R01/receipts/rollback-old-run.json', 'previous build')
        self.assertEqual([x for x in self.reasons() if 'rollback-old-run.json' in x and 'commit' in x and 'previous build commit' in x][:1] != [], True)

    def test_old_run_with_the_current_wheel_is_refused_even_when_commit_is_previous(self):
        self.edit('rollback-old-run.json', lambda d: d.update(wheel_sha256=self.wsha))
        self.refused('bundles/R01/receipts/rollback-old-run.json', 'wheel sha256', 'previous build wheel')

    def test_events_old_artifact_and_upgrade_from_must_be_the_previous_build(self):
        self.edit('events.json', lambda d: d['old_artifact'].update(wheel_sha256=self.wsha))
        self.refused('bundles/R01/receipts/events.json old_artifact', 'previous build wheel')
        self.edit('events.json', lambda d: d['old_artifact'].update(wheel_sha256=r11.PREV_SHA))
        self.edit('upgrade.json', lambda d: d['from'].update(commit=FULL))
        self.refused('bundles/R01/receipts/upgrade.json from', 'previous build commit')

    def test_forward_run_with_the_previous_identity_is_refused_current_role(self):
        self.edit('rollback-forward-run.json', lambda d: d.update(wheel_sha256=r11.PREV_SHA, commit=r11.PREV_COMMIT))
        self.refused('bundles/R01/receipts/rollback-forward-run.json', 'current build')

    def test_every_current_role_receipt_carrying_the_previous_identity_is_refused_naming_it(self):
        for name in CURRENT_FILES:
            with self.subTest(file=name):
                saved = read(self.bdir / 'receipts' / name)
                self.edit(name, lambda d: d.update(wheel_sha256=r11.PREV_SHA, commit=r11.PREV_COMMIT))
                self.refused(f'bundles/R01/receipts/{name}', 'current build')
                dump(self.bdir / 'receipts' / name, saved)
                repin(self.bdir)
                self.rewrite_sums()
                self.assertEqual(self.reasons(), [])

    def test_receipts_and_bundle_json_agreeing_on_an_unpinned_previous_are_refused_by_the_manifest_pin(self):
        # bundle.json (artifacts.previous AND first_release.baseline), release-check.json and every receipt name ANOTHER previous build; only the manifest pins
        other = {'commit': OTHER, 'wheel_sha256': '9' * 64}
        for name, keys in (('upgrade.json', ('from',)), ('events.json', ('old_artifact',)), ('rollback-old-run.json', ())):
            def swap(d, keys=keys):
                for k in keys:
                    d[k] = dict(other)
                if not keys:
                    d.update(other)
            self.edit(name, swap, pin=False)
        d = read(self.bdir / 'receipts' / 'rollback.json')
        d['allowed']['scan']['old_version'] = d['rejected']['scan']['old_version'] = OTHER
        dump(self.bdir / 'receipts' / 'rollback.json', d)
        repin(self.bdir)
        bj = read(self.bdir / 'bundle.json')
        bj['artifacts']['previous'].update(other)
        bj['first_release']['baseline'].update(other)
        jwrite(self.bdir / 'bundle.json', bj)
        rc = read(self.bdir / 'release-check.json')
        rc['first_release_baseline'].update(other)
        jwrite(self.bdir / 'release-check.json', rc)
        self.rewrite_sums()
        self.refused('manifest.bundles[R01].first_release_baseline')
        self.assertFalse(any('receipts/' in x and 'previous build' in x for x in self.reasons()), self.reasons())

    def test_scan_old_version_must_be_the_previous_commit(self):
        self.edit('rollback.json', lambda d: d['allowed']['scan'].update(old_version=FULL))
        self.refused('bundles/R01/receipts/rollback.json allowed.scan.old_version')

    def test_a_previous_identity_the_bundle_does_not_pin_is_refused_even_when_all_receipts_agree(self):
        # everything in the bundle consistently names ANOTHER previous build, but release-check.json / the manifest pin the baseline
        other_prev = {'commit': OTHER, 'wheel_sha256': '9' * 64}

        def swap(d):
            for k in ('from', 'old_artifact'):
                if k in d:
                    d[k] = dict(other_prev)
            if 'commit' in d and d['commit'] == r11.PREV_COMMIT:
                d.update(other_prev)
        for name in ('upgrade.json', 'events.json', 'rollback-old-run.json'):
            self.edit(name, swap, pin=False)
        d = read(self.bdir / 'receipts' / 'rollback.json')
        d['allowed']['scan']['old_version'] = d['rejected']['scan']['old_version'] = OTHER
        dump(self.bdir / 'receipts' / 'rollback.json', d)
        repin(self.bdir)
        bj = read(self.bdir / 'bundle.json')
        bj['artifacts']['previous'].update(other_prev)
        jwrite(self.bdir / 'bundle.json', bj)
        self.rewrite_sums()
        self.refused('bundles/R01/bundle.json artifacts.previous', 'pinned by')
        self.assertFalse(any('receipts/' in x and 'previous build' in x for x in self.reasons()), self.reasons())    # the receipts are consistent with the bundle

    # (e)
    def test_refused_bundle_with_leftover_receipts_and_no_bundle_json_still_passes(self):
        rp = self.pkg / 'bundles' / 'RP'
        r11.bundle_evidence(rp, 'RP', FULL, self.wsha)
        (rp / 'bundle.json').unlink()
        for n in ('notes', 'rollback', 'upgrade'):
            (rp / 'receipts' / f'{n}.json').unlink()
        self.rewrite_sums()
        self.assertTrue((rp / 'bundle-result.json').is_file())
        self.assertEqual(self.reasons(), [])

    def test_refused_bundle_receipts_are_still_judged_by_role(self):
        rp = self.pkg / 'bundles' / 'RP'
        r11.bundle_evidence(rp, 'RP', FULL, self.wsha)
        (rp / 'bundle.json').unlink()
        d = read(rp / 'receipts' / 'events.json')
        d['wheel_sha256'] = BAD_WHEEL
        dump(rp / 'receipts' / 'events.json', d)
        self.rewrite_sums()
        self.refused('bundles/RP/receipts/events.json', 'wheel sha256')
        d['wheel_sha256'] = self.wsha
        dump(rp / 'receipts' / 'events.json', d)
        (rp / 'receipts' / 'installed.json').write_text('{ nope', encoding='utf-8')
        self.rewrite_sums()
        self.refused('bundles/RP/receipts/installed.json')
        r11.bundle_evidence(rp, 'RP', FULL, self.wsha)
        (rp / 'bundle.json').unlink()
        o = read(rp / 'receipts' / 'rollback-old-run.json')
        o.update(wheel_sha256='7' * 64)
        dump(rp / 'receipts' / 'rollback-old-run.json', o)
        self.rewrite_sums()
        self.refused('bundles/RP', 'previous-build statements', 'contradict')

    def test_refused_bundle_result_alone_is_kept_and_passes(self):
        self.assertTrue((self.pkg / 'bundles' / 'RP' / 'bundle-result.json').is_file())
        self.assertEqual(self.reasons(), [])


class NotFirstReleaseBundleTests(unittest.TestCase):
    """A bundle that is not a first release is pinned to the package's previous wheel (manifest.previous_wheel)."""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix='wf r13 bundle '))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.prev = {'commit': r11.PREV_COMMIT, 'sha256': r11.PREV_SHA}

    def test_previous_must_equal_the_manifest_previous_wheel(self):
        r11.bundle_evidence(self.tmp, 'R01', FULL, 'c' * 64, first_release=False)
        self.assertEqual(pc.bundle_receipt_problems(self.tmp, 'R01', FULL, 'c' * 64, True, self.prev), [])
        r = pc.bundle_receipt_problems(self.tmp, 'R01', FULL, 'c' * 64, True, {'commit': r11.PREV_COMMIT, 'sha256': '1' * 64})
        self.assertTrue(any('manifest.previous_wheel' in x for x in r), r)
        r = pc.bundle_receipt_problems(self.tmp, 'R01', FULL, 'c' * 64, True, {'commit': OTHER, 'sha256': r11.PREV_SHA})
        self.assertTrue(any('manifest.previous_wheel' in x for x in r), r)

    def test_previous_commit_unknown_in_the_manifest_is_matched_by_wheel_only(self):
        r11.bundle_evidence(self.tmp, 'R01', FULL, 'c' * 64, first_release=False)
        self.assertEqual(pc.bundle_receipt_problems(self.tmp, 'R01', FULL, 'c' * 64, True, {'commit': None, 'sha256': r11.PREV_SHA}), [])


class ReceiptsBeforeTheBuildTests(r11.BuildPackageBase):
    """(f) The same function in build_package.check_one_build: refused before anything is written, the reason in the SystemExit."""

    def rpath(self, name, rel='R01'):
        return self.bdir / rel / 'receipts' / name

    def tamper(self, name, fn, rel='R01'):
        d = read(self.rpath(name, rel))
        fn(d)
        dump(self.rpath(name, rel), d)
        repin(self.bdir / rel)

    def assert_build_refused(self, *needles):
        with self.assertRaises(SystemExit) as cm:
            self.build()
        for n in needles:
            self.assertIn(n, str(cm.exception))
        self.assertFalse((self.tmp / 'pkg').exists())

    def test_consistent_inputs_build_and_the_package_passes_identity(self):            # (c)
        pkg = self.build()
        self.assertEqual(pc.package_scope(pkg)['reasons'], [])
        self.assertTrue((pkg / 'bundles' / 'R01' / 'receipts' / 'rollback-old-run.json').is_file())

    def test_wrong_wheel_or_commit_in_a_sub_receipt_is_refused_before_build(self):      # (a)
        for name in CURRENT_FILES:
            for key, bad in (('wheel_sha256', BAD_WHEEL), ('commit', OTHER)):
                with self.subTest(file=name, key=key):
                    saved = self.rpath(name).read_bytes()
                    self.tamper(name, lambda d: d.update({key: bad}))
                    self.assert_build_refused(f'bundles/R01/receipts/{name}')
                    self.rpath(name).write_bytes(saved)
                    repin(self.bdir / 'R01')

    def test_missing_invalid_and_mismatching_hash_are_refused_before_build(self):       # (b)
        p = self.rpath('upgrade.json')
        saved = p.read_bytes()
        p.unlink()
        self.assert_build_refused('bundles/R01/receipts/upgrade.json')
        p.write_text('{ nope', encoding='utf-8')
        self.assert_build_refused('bundles/R01/receipts/upgrade.json')
        p.write_bytes(saved)
        bj = read(self.bdir / 'R01' / 'bundle.json')
        bj['checks']['events']['sha256'] = 'a' * 64
        jwrite(self.bdir / 'R01' / 'bundle.json', bj)
        self.assert_build_refused('bundles/R01/receipts/events.json', 'bytes do not match')

    def test_previous_role_receipts_are_judged_against_the_previous_pin_before_build(self):   # (d)
        self.tamper('rollback-old-run.json', lambda d: d.update(wheel_sha256=self.wsha))
        self.assert_build_refused('bundles/R01/receipts/rollback-old-run.json', 'previous build wheel')

    def test_bundle_without_bundle_json_is_refused_before_build(self):
        (self.bdir / 'R01' / 'bundle.json').unlink()
        self.assert_build_refused('bundles/R01/bundle.json', 'missing')

    def test_previous_wheel_to_be_packaged_pins_a_bundle_that_is_not_a_first_release(self):
        r11.bundle_evidence(self.bdir / 'R01', 'R01', FULL, self.wsha, first_release=False)
        self.assert_build_refused('manifest.previous_wheel')

    def test_refused_bundle_results_do_not_block_the_build(self):                       # (e)
        r11.bundle_evidence(self.bdir / 'RP', 'RP', FULL, self.wsha)
        (self.bdir / 'RP' / 'bundle.json').unlink()
        pkg = self.build()
        self.assertTrue((pkg / 'bundles' / 'RP' / 'bundle-result.json').is_file())
        self.assertTrue((pkg / 'bundles' / 'RP' / 'receipts' / 'events.json').is_file())
        self.assertEqual(pc.package_scope(pkg)['reasons'], [])

    def test_leftover_receipt_of_a_refused_bundle_with_another_wheel_is_refused_before_build(self):
        r11.bundle_evidence(self.bdir / 'RP', 'RP', FULL, BAD_WHEEL)
        (self.bdir / 'RP' / 'bundle.json').unlink()
        self.assert_build_refused('bundles/RP/receipts/')


class ThroughTheShippedVerifierTests(BundleCopyBase):
    """The shipped launcher refuses a tampered bundle receipt before it creates any venv (its identity step is package_scope of the SHIPPED copy)."""

    def run_launcher(self, tool):
        work = self.tmp / ('work-' + tool)
        env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION', 'ONECREW_ACTOR')}
        r = subprocess.run([sys.executable, '-I', '-X', 'utf8', str(self.pkg / 'verify' / (tool + '.py')), str(self.pkg), str(work)],
                           capture_output=True, text=True, encoding='utf-8', errors='replace', env=env, timeout=300, cwd=str(self.tmp))
        return r, work

    def test_verify_package_refuses_the_codex_case_before_running_anything(self):
        d = read(self.bdir / 'receipts' / 'events.json')
        d['wheel_sha256'] = BAD_WHEEL
        dump(self.bdir / 'receipts' / 'events.json', d)
        self.rewrite_sums()
        r, work = self.run_launcher('verify_package')
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('bundles/R01/receipts/events.json', r.stdout + r.stderr)
        self.assertFalse((work / 'venv').exists())


class ContradictoryReferenceTests(BundleCopyBase):
    """Round 13b (Codex review 27/10 on the R13 tree): two references to the SAME file with DIFFERENT sha256 passed, because the chain
    follower memoised by path and never looked at the second hash. Invariant: every (path, sha256) reference in the chain is checked
    against the bytes AND against every other reference to that path, whatever its position or how many times the file is named;
    a reference that cannot be verified (malformed) is refused for a produced bundle, never skipped."""

    def bj(self):
        return read(self.bdir / 'bundle.json')

    def put_bj(self, bj):
        jwrite(self.bdir / 'bundle.json', bj)
        self.rewrite_sums()

    def good(self, name='events.json'):
        return {'path': f'receipts/{name}', 'sha256': sha(self.bdir / 'receipts' / name)}

    def bad(self, name='events.json', h='a' * 64):
        return {'path': f'receipts/{name}', 'sha256': h}

    # the Codex case exactly: notes.real_checks names receipts/events.json with 'a'*64, notes + bundle.json + SHA256SUMS re-hashed
    def test_codex_case_notes_real_checks_contradicts_checks_events(self):
        self.edit('notes.json', lambda d: d.update(real_checks=[self.bad()]))
        self.assertEqual(r12.sums_step_bad(self.pkg), [])
        self.refused('bundles/R01/receipts/notes.json real_checks[0]', 'receipts/events.json')

    def test_codex_variant_gate_history_contradicts_checks_events(self):
        bj = self.bj()
        bj['gate_history'] = [self.bad()]
        self.put_bj(bj)
        self.refused('gate_history[0]', 'receipts/events.json')

    def test_every_reference_site_is_judged_whatever_the_order_or_count(self):
        def extra(bj, ref):
            bj['checks']['extra'] = ref

        def history(bj, ref):
            bj['gate_history'] = [self.good(), ref]

        def comparison(bj, ref):
            bj['comparison'] = {'items': [{'original': ref}]}
        sites = {'checks.extra': extra, 'gate_history[1]': history, 'comparison.items[0].original': comparison}
        for site, place in sites.items():
            for name in ('events.json', 'installed.json', 'notes.json'):
                with self.subTest(site=site, file=name):
                    saved = (self.bdir / 'bundle.json').read_bytes()
                    bj = self.bj()
                    place(bj, self.bad(name))
                    self.put_bj(bj)
                    self.refused(site, f'receipts/{name}')
                    (self.bdir / 'bundle.json').write_bytes(saved)
                    self.rewrite_sums()
                    self.assertEqual(self.reasons(), [])

    def test_contradiction_inside_a_receipt_chain_is_judged_too(self):
        # rollback.forward_run re-points to a file bundle.json already declared (loaded first) but with another hash
        def fwd(d):
            d['forward_run'] = self.bad('events.json', 'b' * 64)
        self.edit('rollback.json', fwd, pin=False)
        bj = self.bj()
        bj['checks']['rollback']['sha256'] = sha(self.bdir / 'receipts' / 'rollback.json')
        self.put_bj(bj)
        self.refused('rollback.json forward_run', 'receipts/events.json')
        # and the mirror: a second real_checks entry contradicting the FIRST one (both after bundle.json)
        self.edit('rollback.json', lambda d: d.update(forward_run=self.good('rollback-forward-run.json')))
        self.assertEqual(self.reasons(), [])
        self.edit('notes.json', lambda d: d.update(real_checks=[self.good('upgrade.json'), self.bad('upgrade.json', 'c' * 64)]))
        self.refused('real_checks[1]', 'receipts/upgrade.json')

    def test_wrong_hash_first_and_right_hash_later_is_still_refused(self):
        bj = self.bj()
        bj['checks']['events']['sha256'] = 'a' * 64
        bj['gate_history'] = [self.good()]
        self.put_bj(bj)
        self.refused('checks.events', 'receipts/events.json')

    def test_malformed_real_checks_entry_is_refused_not_skipped(self):
        for entry in ({'path': 'receipts/events.json', 'sha256': 'zz'}, {'path': 'receipts/events.json'}, {'sha256': 'a' * 64},
                      'receipts/events.json', None, {'path': '../outside.json', 'sha256': 'a' * 64}):
            with self.subTest(entry=entry):
                self.edit('notes.json', lambda d: d.update(real_checks=[entry]))
                self.refused('bundles/R01/receipts/notes.json real_checks[0]')

    def test_a_dangling_real_checks_reference_is_refused(self):
        self.edit('notes.json', lambda d: d.update(real_checks=[{'path': 'receipts/never-written.json', 'sha256': 'a' * 64}]))
        self.refused('bundles/R01/receipts/never-written.json', 'real_checks[0]', 'missing')

    # valid controls: the same file named many times with the SAME, true hash, at every site, passes; history files outside receipts/ too
    def test_consistent_repeated_references_pass(self):
        self.edit('notes.json', lambda d: d.update(real_checks=[self.good(), self.good(), self.good('installed.json')]))
        bj = self.bj()
        bj['gate_history'] = [self.good(), self.good('upgrade.json')]
        bj['comparison'] = {'items': [{'original': self.good('notes.json')}]}
        bj['checks']['extra'] = self.good('rollback.json')
        self.put_bj(bj)
        self.assertEqual(self.reasons(), [])
        hist = self.bdir / 'history'
        hist.mkdir()
        dump(hist / 'gate-1.json', {'kind': 'gate', 'commit': OTHER, 'wheel_sha256': '9' * 64})       # another build's history: hash + readability only
        bj = self.bj()
        bj['gate_history'].append({'path': 'history/gate-1.json', 'sha256': sha(hist / 'gate-1.json')})
        self.put_bj(bj)
        self.assertEqual(self.reasons(), [])
        bj = self.bj()
        bj['gate_history'][-1]['sha256'] = 'd' * 64
        self.put_bj(bj)
        self.refused('gate_history[2]', 'history/gate-1.json')

    def test_refused_bundle_keeps_its_result_and_its_contradictions_are_still_named(self):
        rp = self.pkg / 'bundles' / 'RP'
        r11.bundle_evidence(rp, 'RP', FULL, self.wsha)
        self.rewrite_sums()
        self.assertEqual(self.reasons(), [])
        self.assertIs(read(rp / 'bundle-result.json').get('produced'), False)
        d = read(rp / 'receipts' / 'notes.json')
        d['real_checks'] = [{'path': 'receipts/events.json', 'sha256': 'a' * 64}]
        dump(rp / 'receipts' / 'notes.json', d)
        repin(rp)
        self.rewrite_sums()
        self.refused('bundles/RP/receipts/notes.json real_checks[0]', 'receipts/events.json')
        self.assertIs(read(rp / 'bundle-result.json').get('produced'), False)


class ContradictoryReferenceBeforeBuildTests(r11.BuildPackageBase):
    """The same class of contradiction is refused by build_package.check_one_build before anything is written."""

    def test_notes_real_checks_contradiction_refuses_the_build(self):
        rdir = self.bdir / 'R01' / 'receipts'
        d = read(rdir / 'notes.json')
        d['real_checks'] = [{'path': 'receipts/events.json', 'sha256': 'a' * 64}]
        dump(rdir / 'notes.json', d)
        repin(self.bdir / 'R01')
        with self.assertRaises(SystemExit) as cm:
            self.build()
        self.assertIn('real_checks[0]', str(cm.exception))
        self.assertIn('receipts/events.json', str(cm.exception))
        self.assertFalse((self.tmp / 'pkg').exists())

    def test_gate_history_contradiction_refuses_the_build_and_a_consistent_one_builds(self):
        bj = read(self.bdir / 'R01' / 'bundle.json')
        bj['gate_history'] = [{'path': 'receipts/events.json', 'sha256': 'a' * 64}]
        jwrite(self.bdir / 'R01' / 'bundle.json', bj)
        with self.assertRaises(SystemExit) as cm:
            self.build()
        self.assertIn('gate_history[0]', str(cm.exception))
        bj['gate_history'] = [{'path': 'receipts/events.json', 'sha256': sha(self.bdir / 'R01' / 'receipts' / 'events.json')}]
        jwrite(self.bdir / 'R01' / 'bundle.json', bj)
        pkg = self.build()
        self.assertEqual(pc.package_scope(pkg)['reasons'], [])


class ContradictoryReferenceThroughTheShippedVerifierTests(ThroughTheShippedVerifierTests):
    def test_verify_package_refuses_the_notes_contradiction_before_running_anything(self):
        self.edit('notes.json', lambda d: d.update(real_checks=[{'path': 'receipts/events.json', 'sha256': 'a' * 64}]))
        r, work = self.run_launcher('verify_package')
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('real_checks[0]', r.stdout + r.stderr)
        self.assertFalse((work / 'venv').exists())

if __name__ == '__main__':
    unittest.main()
