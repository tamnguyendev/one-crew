"""Codex review P1: the package verifier must not say `pass` while a mandatory step failed.

Unit tests build reports by hand and call `judge`. One integration test runs the real verifier on the real handover package.
"""
import copy
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from wfkit import package_check as pc

PACKAGE = Path(os.environ['WF_PACKAGE']) if os.environ.get('WF_PACKAGE') else None      # e.g. D:/OneCrewRuns/wf-handover-6366137


def _step(sid, **kw):
    return {'id': sid, 'step': sid.replace('_', ' '), 'ok': True, 'mandatory': True, **kw}


# The facts each step records (as the runner writes them); judge recomputes every `ok` from these (P1-1).
FACTS = {
    'sha256sums': {'files': 3, 'bad': []}, 'wheel_sha': {'sha256': 'W', 'actual_sha256': 'W'}, 'venv': {'exit': 0},
    'pip_install': {'exit': 0}, 'help': {'exit': 0, 'needles': {'plan': True}}, 'smoke_body': {'exit': 0, 'observation': True},
    'verdict_run': {'exit': 0, 'm1': 'passed', 'tail': ''}, 'plan_report': {'rendered': True}, 'modules_from_venv': {'modules': 9, 'outside': {}},
    'checkout_not_on_path': {'on_path': []}, 'blocked_copy_built': {'exit': 0, 'needles': {'built': True}},
    'blocked_scan': {'exit': 0, 'blocking': {'total': 1}}, 'blocked_refused_no_pip': {'pip_invocations': 0},
    'blocked_installed_unchanged': {'installed': 'A'}, 'blocked_copy_unchanged': {'tree_sha': 'C'},
    'clear_scan': {'exit': 0, 'blocking': {'total': 0}}, 'clear_uninstall_current': {'exit': 0},
    'clear_install_previous': {'exit': 0, 'sha256': 'P', 'actual_sha256': 'P'}, 'clear_old_digest': {'needles': {'smoke': False}},
    'clear_old_copy_unchanged': {'tree_sha': 'D', 'copy_before': 'D'}, 'clear_uninstall_previous': {'exit': 0},
    'clear_reinstall_current': {'exit': 0}, 'clear_same_build_restored': {'installed': 'A'}, 'clear_roll_forward_reads': {'exit': 0, 'needles': {'smoke': True}},
    'clear_roll_forward_copy_unchanged': {'tree_sha': 'D'},
}


def good_scope(rollback=True, **over):
    """What package_scope() derives from a verified manifest (P1-3); built by hand for the pure judge tests."""
    s = {'package': pc._norm_path('D:/OneCrewRuns/pkg-under-test'), 'kind': 'development-handover-package' if rollback else 'first-release-handover-package',
         'rollback': rollback, 'manifest_sha256': 'M' * 64, 'wheel_sha256': 'W', 'previous_wheel_sha256': 'P' if rollback else None,
         'verifier_files': {'verify/package_check.py': 'V' * 64}, 'reasons': []}
    s.update(over)
    return s


_DEFAULT = object()


def judge(report, scope=_DEFAULT):
    return pc.judge(report, good_scope() if scope is _DEFAULT else scope)


def good_report():
    steps = [_step(i, **copy.deepcopy(FACTS.get(i, {}))) for i in pc.BASE_REQUIRED + pc.ROLLBACK_REQUIRED]
    for s in steps:
        if s['id'] == 'clear_old_cannot_read_plan_ns':
            s.update(kind='negative', exit=1, expect={'exits': [1, 2], 'reason_any': ['No plan named']},
                     stdout_tail='', stderr_tail='{"error": "No plan named smoke"}')
        elif s['id'] == 'clear_old_digest':
            s.update(exit=0, stdout_tail='{"plans": []}', stderr_tail='')
    return {'steps': steps, 'result': None, 'previous_wheel_present': True, 'package_identity': pc.identity(good_scope()),
            'rollback': {
                'blocked': {'scan_total': 1, 'decision': 'refused', 'pip_invocations': 0, 'installed_before': 'A', 'installed_after': 'A',
                            'copy_before': 'C', 'copy_after': 'C'},
                'clear': {'scan_total': 0, 'decision': 'allowed', 'pip_invocations': 4, 'installed_before': 'A', 'installed_after': 'A',
                          'copy_before': 'D', 'copy_after': 'D'}}}


def get(report, sid):
    return next(s for s in report['steps'] if s['id'] == sid)


class JudgeTests(unittest.TestCase):

    def test_i_all_mandatory_ok_passes(self):
        verdict = judge(good_report())
        self.assertEqual(verdict, {'result': 'pass', 'reasons': []})

    def test_ii_mandatory_step_failed_is_refused_and_named(self):
        r = good_report()
        get(r, 'help').update(ok=False, exit=2)
        v = judge(r)
        self.assertEqual(v['result'], 'refused')
        self.assertTrue(any('mandatory step failed: help' in x for x in v['reasons']), v)
        r = good_report()
        get(r, 'pip_install')['exit'] = 1           # nonzero exit even though ok says true
        self.assertEqual(judge(r)['result'], 'refused')

    def test_iii_negative_test_failing_for_a_wrong_reason_is_refused(self):
        r = good_report()
        get(r, 'clear_old_cannot_read_plan_ns').update(exit=2, stderr_tail='{"error": "FileNotFoundError: onecrew.exe"}')
        v = judge(r)
        self.assertEqual(v['result'], 'refused')
        self.assertTrue(any('different reason' in x for x in v['reasons']), v)
        r = good_report()
        get(r, 'clear_old_cannot_read_plan_ns').update(exit=0)       # it must actually fail
        self.assertEqual(judge(r)['result'], 'refused')
        r = good_report()
        s = get(r, 'clear_old_cannot_read_plan_ns')
        del s['expect']                                              # a negative test without an expectation is not a test
        self.assertEqual(judge(r)['result'], 'refused')

    def test_iv_report_claiming_pass_with_failed_mandatory_step_is_incoherent(self):
        r = good_report()
        get(r, 'clear_old_digest').update(ok=False, exit=2)
        r['result'] = 'pass'
        v = judge(r)
        self.assertEqual(v['result'], 'refused')
        self.assertTrue(any('incoherent' in x for x in v['reasons']), v)
        # the original defect: a recorded ok=false step next to result pass
        r = good_report()
        r['steps'].append({'step': 'previous build: plan digest exit 2', 'ok': False, 'exit': 2})   # no id, mandatory by default
        r['result'] = 'pass'
        self.assertEqual(judge(r)['result'], 'refused')
        # a faithful report may say refused; claiming refused on a clean report is incoherent too
        r = good_report()
        r['result'] = 'refused'
        self.assertEqual(judge(r)['result'], 'refused')

    def test_v_encoding_error_in_a_tail_is_refused_even_with_exit_zero(self):
        r = good_report()
        get(r, 'clear_old_digest').update(
            exit=0, stderr_tail="{\"error\": \"'charmap' codec can't encode character '\\u1eae'\", \"type\": \"UnicodeEncodeError\"}")
        v = judge(r)
        self.assertEqual(v['result'], 'refused')
        self.assertTrue(any('UnicodeEncodeError' in x for x in v['reasons']), v)
        r = good_report()
        get(r, 'verdict_run')['tail'] = 'Traceback (most recent call last):\n  File "x"'
        self.assertEqual(judge(r)['result'], 'refused')

    def test_vi_blocked_branch_with_pip_activity_is_refused(self):
        for key, bad in (('pip_invocations', 1), ('installed_after', 'B'), ('copy_after', 'X')):
            r = good_report()
            r['rollback']['blocked'][key] = bad
            v = judge(r)
            self.assertEqual(v['result'], 'refused', key)
        r = good_report()
        r['rollback']['blocked'].update(scan_total=0)                 # a "blocked" copy without a block proves nothing
        self.assertEqual(judge(r)['result'], 'refused')
        r = good_report()
        r['rollback']['blocked'].update(decision='allowed')           # blocks present but rollback not refused
        self.assertEqual(judge(r)['result'], 'refused')

    def test_vii_missing_expected_steps_and_branches_are_refused(self):
        r = good_report()
        r['steps'] = [s for s in r['steps'] if s['id'] != 'blocked_refused_no_pip']
        v = judge(r)
        self.assertEqual(v['result'], 'refused')
        self.assertTrue(any('blocked_refused_no_pip' in x for x in v['reasons']), v)
        r = good_report()
        del r['rollback']['clear']
        self.assertEqual(judge(r)['result'], 'refused')
        r = good_report()
        r['previous_wheel_present'] = None
        self.assertEqual(judge(r)['result'], 'refused')

    def test_viii_non_mandatory_failure_does_not_decide_but_is_not_hidden_from_the_report(self):
        r = good_report()
        r['steps'].append({'id': 'extra_note', 'step': 'optional note', 'ok': False, 'mandatory': False})
        v = judge(r)
        self.assertEqual(v['result'], 'pass')
        self.assertEqual(v['optional'], ['optional step failed (not deciding): extra_note'])     # shown, not deciding
        # P1-1: the report cannot make an ORACLE step optional; demoting it is refused
        r = good_report()
        get(r, 'help').update(mandatory=False, ok=False, exit=2)
        v = judge(r)
        self.assertEqual(v['result'], 'refused')
        self.assertTrue(any('mandatory step demoted: help' in x for x in v['reasons']), v)

    def test_ix_judge_is_pure(self):
        r = good_report()
        before = copy.deepcopy(r)
        judge(r)
        self.assertEqual(r, before)


def base_report(scope):
    """A faithful report for a BASE scope (first-release kind): base steps only, rollback skipped."""
    r = good_report()
    r['steps'] = [s for s in r['steps'] if s['id'] in pc.BASE_REQUIRED]
    r.update(previous_wheel_present=False, rollback={'skipped': 'package carries no previous wheel'}, package_identity=pc.identity(scope))
    return r


class ScopeFromManifestTests(unittest.TestCase):
    """Codex P1-3: the mandatory scope is derived from the verified manifest + on-disk artifact, never from the report."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='wf scope '))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def make_pkg(self, name='pkg', previous=True, kind=None, verifier=True):
        pkg = self.tmp / name
        (pkg / 'wheel' / 'previous').mkdir(parents=True)
        (pkg / 'wheel' / 'cur.whl').write_bytes(b'current wheel')
        m = {'schema': 1, 'kind': kind or ('development-handover-package' if previous else 'first-release-handover-package'),
             'wheel': {'file': 'wheel/cur.whl', 'sha256': pc.sha(pkg / 'wheel' / 'cur.whl')}, 'previous_wheel': None}
        if previous:
            (pkg / 'wheel' / 'previous' / 'onecrew-2.2.0.dev3-py3-none-any.whl').write_bytes(b'previous wheel')
            m['previous_wheel'] = {'file': 'wheel/previous/onecrew-2.2.0.dev3-py3-none-any.whl', 'sha256': pc.sha(pkg / 'wheel' / 'previous' / 'onecrew-2.2.0.dev3-py3-none-any.whl')}
        if verifier:
            (pkg / 'verify').mkdir()
            (pkg / 'verify' / 'package_check.py').write_text('# v', encoding='utf-8')
            m['verifier'] = {'files': {'verify/package_check.py': pc.sha(pkg / 'verify' / 'package_check.py')}}
        (pkg / 'manifest.json').write_text(json.dumps(m), encoding='utf-8')
        return pkg, m

    def write(self, pkg, m):
        (pkg / 'manifest.json').write_text(json.dumps(m), encoding='utf-8')

    def refused(self, report, scope, text):
        v = pc.judge(report, scope)
        self.assertEqual(v['result'], 'refused', v)
        self.assertTrue(any(text in x for x in v['reasons']), v)

    def test_s1_previous_wheel_manifest_derives_rollback_scope(self):
        pkg, m = self.make_pkg()
        s = pc.package_scope(pkg)
        self.assertEqual(s['reasons'], [])
        self.assertIs(s['rollback'], True)
        self.assertEqual(s['previous_wheel_sha256'], m['previous_wheel']['sha256'])
        self.assertEqual(s['verifier_files'], m['verifier']['files'])

    def test_s2_manifest_with_previous_wheel_but_report_without_rollback_steps_is_refused(self):
        pkg, m = self.make_pkg()
        scope = pc.package_scope(pkg)
        r = good_report()
        r['package_identity'] = pc.identity(scope)
        get(r, 'wheel_sha').update(sha256=scope['wheel_sha256'], actual_sha256=scope['wheel_sha256'])
        get(r, 'clear_install_previous').update(sha256=scope['previous_wheel_sha256'], actual_sha256=scope['previous_wheel_sha256'])
        self.assertEqual(pc.judge(r, scope), {'result': 'pass', 'reasons': []})
        r['steps'] = [s for s in r['steps'] if s['id'] in pc.BASE_REQUIRED]
        self.refused(r, scope, 'expected step missing: blocked_scan')

    def test_s3_declared_first_release_kind_gives_base_scope(self):
        pkg, m = self.make_pkg(previous=False)
        scope = pc.package_scope(pkg)
        self.assertEqual(scope['reasons'], [])
        self.assertIs(scope['rollback'], False)
        r = base_report(scope)
        get(r, 'wheel_sha').update(sha256=scope['wheel_sha256'], actual_sha256=scope['wheel_sha256'])
        self.assertEqual(pc.judge(r, scope), {'result': 'pass', 'reasons': []})          # rollback steps absent: fine
        bad = copy.deepcopy(r)
        bad['steps'] += [s for s in good_report()['steps'] if s['id'] in pc.ROLLBACK_REQUIRED]
        self.refused(bad, scope, 'rollback steps recorded although the package manifest declares no previous wheel')
        bad = copy.deepcopy(r)
        bad['rollback'] = good_report()['rollback']
        self.refused(bad, scope, 'rollback facts recorded')
        bad = copy.deepcopy(r)
        bad['previous_wheel_present'] = True
        self.refused(bad, scope, 'previous_wheel_present misdeclared')

    def test_s4_missing_previous_wheel_without_a_declared_kind_is_unverifiable(self):
        pkg, m = self.make_pkg()
        m['previous_wheel'] = None                                   # a rollback kind that lost its previous wheel
        self.write(pkg, m)
        self.assertTrue(any('requires a previous wheel' in x for x in pc.package_scope(pkg)['reasons']))
        m['kind'] = 'some-other-kind'
        self.write(pkg, m)
        self.assertTrue(any('not a package kind' in x for x in pc.package_scope(pkg)['reasons']))
        pkg2, m2 = self.make_pkg('pkg2', previous=True, kind='first-release-handover-package')    # base kind but a previous wheel
        self.assertTrue(any('contradiction' in x for x in pc.package_scope(pkg2)['reasons']))

    def test_s5_manifest_missing_or_unverifiable_is_refused(self):
        r = good_report()
        self.refused(r, None, 'no verified package scope')
        self.refused(r, pc.package_scope(self.tmp / 'nothing-here'), 'manifest missing or unreadable')
        pkg, m = self.make_pkg()
        (pkg / 'wheel' / 'previous' / 'onecrew-2.2.0.dev3-py3-none-any.whl').write_bytes(b'swapped previous wheel')
        self.refused(r, pc.package_scope(pkg), 'previous wheel file bytes do not match')
        pkg, m = self.make_pkg('pkg3')
        (pkg / 'wheel' / 'cur.whl').unlink()
        self.refused(r, pc.package_scope(pkg), 'wheel file missing')
        pkg, m = self.make_pkg('pkg4')
        (pkg / 'verify' / 'package_check.py').write_text('# tampered', encoding='utf-8')
        self.refused(r, pc.package_scope(pkg), 'verifier file missing, outside verify/ or modified')
        pkg, m = self.make_pkg('pkg5')
        (pkg / 'manifest.json').write_text('{not json', encoding='utf-8')
        self.refused(r, pc.package_scope(pkg), 'manifest missing or unreadable')

    def test_s6_launcher_verifier_must_be_the_manifests(self):
        pkg, m = self.make_pkg()
        self.assertEqual(pc.package_scope(pkg, m['verifier']['files'])['reasons'], [])
        self.assertTrue(any('not the verifier this package manifest pins' in x
                            for x in pc.package_scope(pkg, {'verify/package_check.py': '0' * 64})['reasons']))

    def test_s7_manifest_without_verifier_binds_none(self):
        pkg, m = self.make_pkg(verifier=False)
        s = pc.package_scope(pkg)
        self.assertEqual(s['reasons'], [])
        self.assertIsNone(s['verifier_files'])


class RunnerFactsTests(unittest.TestCase):

    def test_pip_invocations_are_counted_only_for_install_and_uninstall(self):
        runner = pc.Runner()
        import sys
        runner.run([sys.executable, '-m', 'pip', '--version'])
        self.assertEqual(runner.pip_invocations, 0)
        runner.run([sys.executable, '-m', 'pip', 'uninstall', '--yes', 'onecrew-package-check-not-installed'])
        self.assertEqual(runner.pip_invocations, 1)

    def test_child_env_forces_utf8(self):
        import sys
        code, so, se = pc.Runner().run([sys.executable, '-c', 'import os,sys;print(os.environ["PYTHONUTF8"], sys.stdout.encoding);print("\\u1eae")'])
        self.assertEqual(code, 0, se)
        self.assertIn('1 utf-8', so)
        self.assertIn('\u1eae', so)

    def test_tree_sha_changes_with_content(self):
        d = Path(tempfile.mkdtemp())
        try:
            (d / 'a').write_text('1')
            h1 = pc.tree_sha(d)
            (d / 'a').write_text('2')
            self.assertNotEqual(h1, pc.tree_sha(d))
        finally:
            shutil.rmtree(d, ignore_errors=True)


class PreviousBuildCapabilityTests(unittest.TestCase):
    """Round 10: the plan-ns expectation follows the PREVIOUS build's own capability (dev3 baseline: no; dev8 and later: yes)."""

    def ns_scope(self):
        return good_scope(previous_reads_plan_ns=True)

    def ns_report(self, scope=None):
        scope = scope or self.ns_scope()
        r = good_report()
        r['steps'] = [s for s in r['steps'] if s['id'] != 'clear_old_cannot_read_plan_ns']
        get(r, 'clear_old_digest').update(needles={'smoke': True}, stdout_tail='{"plans": [{"name": "smoke"}]}')
        i = [s['id'] for s in r['steps']].index('clear_old_digest') + 1
        r['steps'].insert(i, _step('clear_old_reads_plan_ns', exit=0, needles={'smoke': True}, stdout_tail='smoke', stderr_tail=''))
        r['package_identity'] = pc.identity(scope)
        return r

    def test_version_to_capability(self):
        f = pc.previous_reads_plan_ns
        self.assertIs(f('wheel/previous/onecrew-2.2.0.dev3-py3-none-any.whl'), False)
        self.assertIs(f('onecrew-2.2.0.dev0-py3-none-any.whl'), False)
        self.assertIs(f('onecrew-2.1.9-py3-none-any.whl'), False)
        self.assertIs(f('wheel/previous/onecrew-2.2.0.dev4-py3-none-any.whl'), True)
        self.assertIs(f('wheel/previous/onecrew-2.2.0.dev8-py3-none-any.whl'), True)
        self.assertIs(f('onecrew-2.2.0-py3-none-any.whl'), True)
        self.assertIs(f('onecrew-2.3.0.dev1-py3-none-any.whl'), True)
        self.assertIsNone(f('wheel/previous/previous.whl'))
        self.assertIsNone(f(None))

    def test_required_steps_follow_the_capability(self):
        legacy, ns = pc.required_steps(True, False), pc.required_steps(True, True)
        self.assertIn('clear_old_cannot_read_plan_ns', legacy)
        self.assertNotIn('clear_old_reads_plan_ns', legacy)
        self.assertIn('clear_old_reads_plan_ns', ns)
        self.assertNotIn('clear_old_cannot_read_plan_ns', ns)
        self.assertEqual(len(legacy), len(ns))
        self.assertEqual(pc.required_steps(False, True), list(pc.BASE_REQUIRED))

    def test_previous_with_namespaces_passes_when_it_reads_the_root(self):
        self.assertEqual(judge(self.ns_report(), self.ns_scope()), {'result': 'pass', 'reasons': []})

    def test_previous_with_namespaces_not_listing_the_root_is_refused(self):
        r = self.ns_report()
        get(r, 'clear_old_digest').update(needles={'smoke': False}, ok=False)
        v = judge(r, self.ns_scope())
        self.assertEqual(v['result'], 'refused')
        self.assertTrue(any('mandatory step failed: clear_old_digest' in x for x in v['reasons']), v)
        r = self.ns_report()
        get(r, 'clear_old_reads_plan_ns').update(exit=1, ok=False)
        self.assertEqual(judge(r, self.ns_scope())['result'], 'refused')

    def test_legacy_report_is_refused_under_a_namespaced_previous_scope(self):
        v = judge(good_report(), self.ns_scope())          # the dev3-shaped report (negative step, smoke not listed) against a dev8 previous
        self.assertEqual(v['result'], 'refused')
        self.assertTrue(any('expected step missing: clear_old_reads_plan_ns' in x for x in v['reasons']), v)
        self.assertTrue(any('belongs to the other previous-build capability' in x for x in v['reasons']), v)

    def test_namespaced_report_is_refused_under_a_legacy_previous_scope(self):
        legacy = good_scope(previous_reads_plan_ns=False)
        r = self.ns_report()
        r['package_identity'] = pc.identity(legacy)
        v = judge(r, legacy)
        self.assertEqual(v['result'], 'refused')
        self.assertTrue(any('expected step missing: clear_old_cannot_read_plan_ns' in x for x in v['reasons']), v)

    def test_capability_is_part_of_the_bound_identity(self):
        r = good_report()                                   # identity recorded for a legacy previous
        r['package_identity']['previous_reads_plan_ns'] = False
        v = judge(r, self.ns_scope())
        self.assertTrue(any('package identity differs from the manifest: previous_reads_plan_ns' in x for x in v['reasons']), v)
        r = self.ns_report()
        r['package_identity']['previous_reads_plan_ns'] = False      # the report cannot choose the weaker (legacy) oracle
        self.assertEqual(judge(r, self.ns_scope())['result'], 'refused')

    def test_package_scope_derives_the_capability_from_the_manifest_wheel_name(self):
        import hashlib
        for name, want in (('onecrew-2.2.0.dev3-py3-none-any.whl', False), ('onecrew-2.2.0.dev8-py3-none-any.whl', True)):
            d = Path(tempfile.mkdtemp())
            try:
                (d / 'wheel' / 'previous').mkdir(parents=True)
                ent = {}
                for rel, data in (('wheel/onecrew-2.2.0.dev10-py3-none-any.whl', b'cur'), (f'wheel/previous/{name}', b'prev')):
                    (d / rel).write_bytes(data)
                    ent[rel] = {'file': rel, 'sha256': hashlib.sha256(data).hexdigest()}
                (d / 'manifest.json').write_text(json.dumps({
                    'kind': 'development-handover-package', 'wheel': ent['wheel/onecrew-2.2.0.dev10-py3-none-any.whl'],
                    'previous_wheel': ent[f'wheel/previous/{name}']}), encoding='utf-8')
                sc = pc.package_scope(d)
                self.assertEqual(sc['reasons'], [])
                self.assertIs(sc['previous_reads_plan_ns'], want)
                self.assertIs(pc.identity(sc)['previous_reads_plan_ns'], want)
                # an unreadable version is an unverifiable scope, never a silent legacy fallback
                m = json.loads((d / 'manifest.json').read_text(encoding='utf-8'))
                shutil.copy(d / m['previous_wheel']['file'], d / 'wheel' / 'previous' / 'prev.whl')
                m['previous_wheel']['file'] = 'wheel/previous/prev.whl'
                (d / 'manifest.json').write_text(json.dumps(m), encoding='utf-8')
                self.assertTrue(any('no readable version' in x for x in pc.package_scope(d)['reasons']))
            finally:
                shutil.rmtree(d, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
