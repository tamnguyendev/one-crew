"""Codex finding P1-1: the package verifier's oracle belongs to the EVALUATOR, never to the report.

Base fixture: a verbatim copy of the real report of package wf-handover-6366137 (tests/fixtures/wf_verify_report_6366137.json).
That report was written by the runner before P1-1, so it lacks a few facts the judge now recomputes `ok` from; `real_report()` adds
exactly those facts (values taken from the same report where they exist) as the current runner records them. Every counter-example
below starts from that report and must be REFUSED.
"""
import copy
import json
import unittest
from pathlib import Path

from wfkit import package_check as pc

FIXTURE = Path(__file__).with_name('fixtures') / 'wf_verify_report_6366137.json'


def verbatim():
    return json.loads(FIXTURE.read_text(encoding='utf-8'))


def get(report, sid):
    return next(s for s in report['steps'] if s['id'] == sid)


# The scope package_scope() derives from that package's manifest (values of D:/OneCrewRuns/wf-handover-6366137/manifest.json, 25/10). That
# manifest predates the shipped verifier, so verifier_files is None (the binding is required only when the manifest declares `verifier`).
REAL_SCOPE = {'package': pc._norm_path('D:/OneCrewRuns/wf-handover-6366137'), 'kind': 'development-handover-package', 'rollback': True,
              'manifest_sha256': '7f70cc301daf2cef05b93d0098c8973da582059880e61e98a62ab75c94e92321',
              'wheel_sha256': '503f624f8912857f9fff2e51a725bcaa161c7c0c296dfade0ca271b7a4b31237',
              'previous_wheel_sha256': '4c5b81fe8b5f1301c426601d1e0eca481d3e0ce602fd60252502d768a7b469a1', 'verifier_files': None, 'reasons': []}


def scope(**over):
    return {**copy.deepcopy(REAL_SCOPE), **over}


def judge(report, sc=None):
    return pc.judge(report, scope() if sc is None else sc)


def real_report():
    """The real report plus the facts the post-P1-1/P1-3 runner records (names in package_check.run/_verify/_rollback)."""
    r = verbatim()
    rb = r['rollback']
    r['package_identity'] = pc.identity(scope())
    get(r, 'wheel_sha')['actual_sha256'] = get(r, 'wheel_sha')['sha256']
    get(r, 'help')['needles'] = {'plan': True}
    get(r, 'smoke_body')['observation'] = True
    get(r, 'plan_report')['rendered'] = True
    get(r, 'checkout_not_on_path')['on_path'] = []
    get(r, 'blocked_copy_built')['needles'] = {'built': True}
    prev = REAL_SCOPE['previous_wheel_sha256']
    get(r, 'clear_install_previous').update(sha256=prev, actual_sha256=prev)
    get(r, 'clear_old_digest')['needles'] = {'smoke': False}
    get(r, 'clear_old_copy_unchanged').update(tree_sha=rb['clear']['copy_before'], copy_before=rb['clear']['copy_before'])
    get(r, 'clear_roll_forward_reads')['needles'] = {'smoke': True}
    get(r, 'clear_roll_forward_copy_unchanged')['tree_sha'] = rb['clear']['copy_before']
    return r


def reasons_with(verdict, text):
    return [x for x in verdict['reasons'] if text in x]


class OracleTests(unittest.TestCase):

    def assertRefused(self, report, text=None):
        v = judge(report)
        self.assertEqual(v['result'], 'refused', v)
        if text:
            self.assertTrue(reasons_with(v, text), v)
        return v

    def test_real_report_with_recorded_facts_passes(self):
        self.assertEqual(judge(real_report()), {'result': 'pass', 'reasons': []})

    def test_verbatim_pre_p1_report_is_refused_for_facts_it_does_not_record(self):
        v = self.assertRefused(verbatim(), 'fact missing')
        self.assertTrue(reasons_with(v, 'clear_old_copy_unchanged'), v)

    # ---- the two Codex bypasses ----
    def test_codex_bypass_1_demoted_verdict_run_is_refused(self):
        r = real_report()
        get(r, 'verdict_run').update(mandatory=False, ok=False, exit=99)
        self.assertRefused(r, 'mandatory step demoted: verdict_run')

    def test_codex_bypass_2_replaced_negative_expectation_is_refused(self):
        r = real_report()
        get(r, 'clear_old_cannot_read_plan_ns').update(expect={'exits': [0], 'reason_any': ['anything']}, exit=0,
                                                       stdout_tail='anything', stderr_tail='')
        v = self.assertRefused(r, 'expectation replaced')
        self.assertTrue(reasons_with(v, 'exited 0'), v)

    # ---- direct variants ----
    def test_a_each_required_step_removed_is_refused(self):
        for sid in pc.BASE_REQUIRED + pc.ROLLBACK_REQUIRED:
            r = real_report()
            r['steps'] = [s for s in r['steps'] if s['id'] != sid]
            self.assertRefused(r, f'expected step missing: {sid}')

    def test_b_duplicated_required_step_is_refused_in_either_order(self):
        for first_ok in (True, False):
            r = real_report()
            i = next(n for n, s in enumerate(r['steps']) if s['id'] == 'verdict_run')
            good = r['steps'][i]
            bad = dict(good, ok=False, exit=99, m1='failed')
            r['steps'][i:i + 1] = [good, bad] if first_ok else [bad, good]
            self.assertRefused(r, 'duplicate step id')

    def test_c_widened_expectation_is_refused_even_when_the_real_exit_matches(self):
        r = real_report()
        get(r, 'clear_old_cannot_read_plan_ns')['expect'] = {'exits': [1, 2, 3], 'reason_any': ['No plan named']}
        self.assertRefused(r, 'expectation replaced')
        r = real_report()
        get(r, 'clear_old_cannot_read_plan_ns')['kind'] = 'positive'
        self.assertRefused(r)

    def test_d_negative_step_exit_zero_is_refused_whatever_its_text(self):
        r = real_report()
        get(r, 'clear_old_cannot_read_plan_ns').update(exit=0)          # text still says "No plan named", expect unchanged, ok true
        self.assertRefused(r, 'exited 0')

    def test_e_ok_true_while_recorded_facts_fail_is_refused(self):
        cases = [
            ('verdict_run', {'exit': 99}),
            ('verdict_run', {'m1': 'failed'}),
            ('blocked_scan', {'blocking': {'read': 0, 'continue': 0, 'total': 0}}),
            ('clear_scan', {'blocking': {'read': 0, 'continue': 1, 'total': 1}}),
            ('sha256sums', {'bad': ['wheel.whl']}),
            ('wheel_sha', {'actual_sha256': '0' * 64}),
            ('modules_from_venv', {'outside': {'onecrew': 'D:/checkout/onecrew/__init__.py'}}),
            ('blocked_refused_no_pip', {'pip_invocations': 1}),
            ('blocked_installed_unchanged', {'installed': 'other'}),
            ('clear_same_build_restored', {'installed': 'other'}),
            ('clear_old_digest', {'needles': {'smoke': True}}),
            ('clear_roll_forward_reads', {'needles': {'smoke': False}}),
            ('clear_old_copy_unchanged', {'tree_sha': 'other'}),
            ('help', {'exit': 2}),
        ]
        for sid, facts in cases:
            r = real_report()
            get(r, sid).update(facts)
            self.assertTrue(get(r, sid)['ok'])
            self.assertRefused(r, sid)
        r = real_report()
        r['rollback']['clear']['pip_invocations'] = 2
        self.assertRefused(r, 'uninstall/install twice')

    def test_f_ok_false_while_facts_pass_is_refused_and_a_pass_claim_is_incoherent(self):
        r = real_report()
        get(r, 'verdict_run')['ok'] = False
        self.assertRefused(r, 'disagrees')
        r['result'] = 'pass'
        self.assertRefused(r, 'incoherent')

    def test_g_optional_step_outside_the_oracle_does_not_decide(self):
        r = real_report()
        r['steps'].append({'id': 'extra_note', 'step': 'optional note', 'ok': False, 'mandatory': False, 'exit': 3,
                           'stderr_tail': 'Traceback (most recent call last):'})
        v = judge(r)
        self.assertEqual(v['result'], 'pass', v)
        self.assertEqual(v['reasons'], [])
        self.assertEqual(v['optional'], ['optional step failed (not deciding): extra_note'])

    def test_h_report_cannot_add_or_drop_requirements(self):
        r = real_report()
        r['expected_steps'] = []                                         # ignored: the oracle is the module's
        get(r, 'plan_report')['mandatory'] = False
        self.assertRefused(r, 'mandatory step demoted: plan_report')
        r = real_report()
        r['previous_wheel_present'] = False                              # rollback steps then contradict the report
        self.assertRefused(r, 'previous_wheel_present')

    def test_i_step_without_id_is_refused(self):
        r = real_report()
        r['steps'].append({'step': 'previous build: plan digest exit 2', 'ok': False, 'exit': 2})
        self.assertRefused(r, 'without id')

    def test_j_forbidden_marker_in_a_mandatory_tail_is_refused(self):
        r = real_report()
        get(r, 'clear_uninstall_current')['stderr_tail'] = "UnicodeEncodeError: 'charmap' codec can't encode"
        self.assertRefused(r, 'UnicodeEncodeError')

    def test_k_judge_is_pure(self):
        r = real_report()
        before = copy.deepcopy(r)
        sc = scope()
        judge(r, sc)
        self.assertEqual(r, before)
        self.assertEqual(sc, REAL_SCOPE)


class ScopeBindingTests(unittest.TestCase):
    """Codex finding P1-3 (round 6): the mandatory scope and the package identity come from the manifest-derived scope, never the report."""

    assertRefused = OracleTests.assertRefused

    def test_p13_codex_bypass_flag_flipped_and_rollback_steps_removed_is_refused(self):
        r = real_report()
        r['previous_wheel_present'] = False
        r['steps'] = [s for s in r['steps'] if s['id'] not in pc.ROLLBACK_REQUIRED]
        del r['rollback']
        v = self.assertRefused(r, 'previous_wheel_present misdeclared')
        for sid in pc.ROLLBACK_REQUIRED:
            self.assertTrue(reasons_with(v, f'expected step missing: {sid}'), (sid, v))

    def test_p13_flag_flipped_with_rollback_facts_retained_is_refused(self):
        r = real_report()
        r['previous_wheel_present'] = False
        r['steps'] = [s for s in r['steps'] if s['id'] not in pc.ROLLBACK_REQUIRED]      # rollback facts block kept: contradiction
        self.assertRefused(r, 'previous_wheel_present misdeclared')
        r = real_report()
        r['previous_wheel_present'] = False                                              # everything kept, only the flag flipped
        self.assertRefused(r, 'previous_wheel_present misdeclared')

    def test_p13_previous_wheel_manifest_report_without_rollback_steps_is_refused(self):
        r = real_report()
        r['steps'] = [s for s in r['steps'] if s['id'] not in pc.ROLLBACK_REQUIRED]
        r['rollback'] = {'skipped': 'package carries no previous wheel'}
        v = self.assertRefused(r, 'expected step missing: clear_install_previous')
        self.assertTrue(reasons_with(v, 'rollback facts missing') or reasons_with(v, 'not exercised'), v)

    def test_p13_base_scope_of_a_declared_first_release_kind(self):
        base = scope(kind='first-release-handover-package', rollback=False, previous_wheel_sha256=None)
        r = real_report()
        r['steps'] = [s for s in r['steps'] if s['id'] in pc.BASE_REQUIRED]
        r.update(previous_wheel_present=False, rollback={'skipped': 'package carries no previous wheel'}, package_identity=pc.identity(base))
        self.assertEqual(judge(r, base), {'result': 'pass', 'reasons': []})
        bad = real_report()                                                              # rollback steps present under a base scope
        bad.update(previous_wheel_present=False, package_identity=pc.identity(base))
        v = self.assertRefused_with(bad, base, 'rollback steps recorded although the package manifest declares no previous wheel')
        self.assertTrue(reasons_with(v, 'rollback facts recorded'), v)

    def assertRefused_with(self, report, sc, text):
        v = pc.judge(report, sc)
        self.assertEqual(v['result'], 'refused', v)
        self.assertTrue(reasons_with(v, text), v)
        return v

    def test_p13_swapped_identities_are_refused(self):
        for key, value in (('package', 'D:/OneCrewRuns/wf-handover-other'), ('kind', 'first-release-handover-package'),
                           ('manifest_sha256', '0' * 64), ('wheel_sha256', '1' * 64), ('previous_wheel_sha256', '2' * 64),
                           ('verifier_files', {'verify/package_check.py': '3' * 64})):
            r = real_report()
            r['package_identity'][key] = value
            self.assertRefused(r, f'package identity differs from the manifest: {key}')
        r = real_report()
        del r['package_identity']
        self.assertRefused(r, 'no package identity')
        r = real_report()
        del r['package_identity']['verifier_files']
        self.assertRefused(r, 'verifier_files')
        # the report's identity matches a DIFFERENT package's scope: the judged package wins
        r = real_report()
        self.assertRefused_with(r, scope(wheel_sha256='4' * 64), 'wheel_sha256')
        self.assertRefused_with(r, scope(verifier_files={'verify/package_check.py': '5' * 64}), 'verifier_files')

    def test_p13_step_facts_about_another_wheel_are_refused(self):
        r = real_report()
        get(r, 'wheel_sha').update(sha256='6' * 64, actual_sha256='6' * 64)
        self.assertRefused(r, 'checked a different wheel')
        r = real_report()
        get(r, 'clear_install_previous').update(sha256='7' * 64, actual_sha256='7' * 64)
        self.assertRefused(r, 'installed a different previous wheel')

    def test_p13_missing_or_unverifiable_scope_is_refused(self):
        r = real_report()
        self.assertRefused_with(r, None, 'no verified package scope')
        self.assertRefused_with(r, {}, 'no verified package scope')
        self.assertRefused_with(r, scope(reasons=['manifest missing or unreadable: FileNotFoundError']), 'package scope unverifiable')
        self.assertRefused_with(r, scope(rollback=None), 'does not say whether a previous wheel')

    def test_p13_report_self_claims_never_decide(self):
        r = real_report()
        r.update(result='pass', judge={'result': 'pass', 'reasons': []}, report_sha256='f' * 64, previous_wheel_present=False)
        self.assertRefused(r, 'previous_wheel_present misdeclared')


if __name__ == '__main__':
    unittest.main()
