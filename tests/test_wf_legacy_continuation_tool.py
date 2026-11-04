"""docs/wf/audit/tools/legacy_continuation.py — the package-level legacy-root continuation check (review a2476ab P1-D, directive 25/10).

The judge decides from the mandatory steps only; the report's own `result` is compared, never trusted. Negative steps must have failed the
command for the expected reason and written nothing. An encoding error in any tail refuses the report. The run against a real package lives in
tests/test_wf_legacy_continuation_real.py (needs WF_PACKAGE; not in the gate registry because it must skip without a package).
"""
import copy
import importlib.util
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('legacy_continuation', REPO / 'docs' / 'wf' / 'audit' / 'tools' / 'legacy_continuation.py')
lc = importlib.util.module_from_spec(spec); spec.loader.exec_module(lc)


# The facts each step records (as the runner writes them); judge recomputes every `ok` from these (oracle principle, Codex P1-1).
FACTS = {
    'wheel_sha': {'sha256': 'W', 'actual_sha256': 'W'},
    'venv': {'exit': 0},
    'pip_install': {'exit': 0},
    'old_venv_previous_wheel': {'exit': 0, 'venv_exit': 0, 'previous': {'file': 'p.whl', 'sha256': 'P'}, 'previous_actual_sha256': 'P'},
    'legacy_root_by_old_build': {'exit': 0},
    'legacy_root_built': {'exit': 0, 'observation': True},
    'legacy_passed_old_semantics': {'exit': 0, 'm1': 'passed', 'result': 'pass', 'integrity': None},
    'legacy_handover_no_baseline_required': {'baseline_in_page': False, 'o1_line': 'O1 «The sample exists» — đạt (M1 passed)'},
    'baseline_owner_recorded': {'exit': 0, 'baselines': 1, 'recorded': [{'tree': 'T', 'from_commit': 'H'}], 'tree': 'T', 'head': 'H'},
    'baseline_leaves_verdict_unchanged': {'exit': 0, 'm1': 'passed', 'verdicts': ['pass'], 'baselines': 1},
    'legacy_identity_unchanged': {'anchor': 'A', 'anchor_built': 'A', 'anchor_counted_before': 'A', 'revision': 1, 'revision_built': 1,
                                  'approved_rows': 1, 'approved_rows_built': 1},
    'old_build_reads_after': {'exit': 0, 'needles': {'legacy': True}},
    'modules_from_venv': {'modules': 9, 'outside': {}},
}


def good_scope(rollback=True, **over):
    """What package_scope() derives from a verified manifest (Codex P1-3); hand-built for the pure judge tests."""
    s = {'package': lc.pc._norm_path('D:/OneCrewRuns/pkg-under-test'), 'kind': 'development-handover-package' if rollback else 'first-release-handover-package',
         'rollback': rollback, 'manifest_sha256': 'M' * 64, 'wheel_sha256': 'W', 'previous_wheel_sha256': 'P' if rollback else None,
         'verifier_files': None, 'reasons': []}
    s.update(over)
    return s


_DEFAULT = object()


def judge(report, scope=_DEFAULT):
    return lc.judge(report, good_scope() if scope is _DEFAULT else scope)


def good_report():
    steps = []
    for sid in lc.REQUIRED:
        s = {'id': sid, 'step': sid, 'ok': True, 'mandatory': True, 'stdout_tail': '', 'stderr_tail': '', **copy.deepcopy(FACTS.get(sid, {}))}
        if sid in lc.NEGATIVE:
            s.update(kind='negative', exit=1, events_added=0, baselines=0,
                     stderr_tail='refused: ' + lc.NEGATIVE[sid] + ' decision / commit not in the repository')
        steps.append(s)
    return {'steps': steps, 'result': None, 'previous_wheel_present': True, 'package_identity': lc.pc.identity(good_scope())}


def get(report, sid):
    return next(s for s in report['steps'] if s['id'] == sid)


class JudgeTests(unittest.TestCase):
    def test_all_mandatory_ok_passes(self):
        self.assertEqual(judge(good_report()), {'result': 'pass', 'reasons': []})

    def test_failed_or_missing_mandatory_step_is_refused_and_named(self):
        r = good_report(); get(r, 'legacy_passed_old_semantics').update(ok=False, m1='pending', result='fail')
        self.assertIn('mandatory step failed: legacy_passed_old_semantics', judge(r)['reasons'])
        r = good_report(); r['steps'] = [s for s in r['steps'] if s['id'] != 'legacy_handover_no_baseline_required']
        self.assertIn('mandatory step missing: legacy_handover_no_baseline_required', judge(r)['reasons'])

    def test_report_claiming_pass_with_a_failed_step_is_incoherent(self):
        r = good_report(); get(r, 'baseline_owner_recorded').update(ok=False, exit=1, baselines=0); r['result'] = 'pass'
        reasons = judge(r)['reasons']
        self.assertIn('mandatory step failed: baseline_owner_recorded', reasons)
        self.assertTrue(any('incoherent' in x for x in reasons))

    def test_negative_step_that_did_not_fail_or_failed_for_another_reason_or_wrote_events_is_refused(self):
        r = good_report(); get(r, 'baseline_ai_refused')['exit'] = 0
        self.assertTrue(any('did not fail' in x for x in judge(r)['reasons']))
        r = good_report(); get(r, 'baseline_bad_commit_refused')['stderr_tail'] = 'Traceback: KeyError'
        self.assertTrue(any('another reason' in x for x in judge(r)['reasons']))
        r = good_report(); get(r, 'baseline_ai_refused')['events_added'] = 1
        self.assertTrue(any('wrote events' in x for x in judge(r)['reasons']))

    def test_encoding_error_in_a_tail_is_refused_even_when_the_step_says_ok(self):
        r = good_report(); get(r, 'legacy_root_built')['stderr_tail'] = "UnicodeEncodeError: 'charmap' codec can't encode"
        self.assertIn('encoding error in step output: legacy_root_built', judge(r)['reasons'])

    # ---- oracle counter-examples (the report supplies observations only; Codex P1-1 principle) ----
    def test_demoted_required_step_is_refused(self):
        r = good_report(); get(r, 'legacy_passed_old_semantics').update(mandatory=False, ok=False, m1='pending', result='fail')
        v = judge(r)
        self.assertEqual(v['result'], 'refused')
        self.assertTrue(any('mandatory step demoted: legacy_passed_old_semantics' in x for x in v['reasons']), v)

    def test_ok_true_on_an_inconclusive_or_integrity_judged_old_root_is_refused(self):
        # decision 25/10 round 6: a schema-2 root keeps the old rule; an inconclusive verdict or a T19 integrity record on it is a failure
        for facts in ({'result': 'inconclusive', 'm1': 'pending'}, {'integrity': {'classification': 'insufficient', 'error': 'no approved baseline'}}):
            r = good_report(); get(r, 'legacy_passed_old_semantics').update(facts)
            v = judge(r)
            self.assertEqual(v['result'], 'refused', facts)
            self.assertTrue(any('legacy_passed_old_semantics' in x and 'disagrees' in x for x in v['reasons']), v)

    def test_handover_naming_a_baseline_route_or_o1_not_achieved_is_refused(self):
        for facts in ({'baseline_in_page': True}, {'o1_line': 'O1 «The sample exists» — chưa có'}, {'o1_line': 'O1 — cần kiểm lại'}):
            r = good_report(); get(r, 'legacy_handover_no_baseline_required').update(facts)
            self.assertEqual(judge(r)['result'], 'refused', facts)

    def test_baseline_that_changes_the_verdict_or_old_build_that_cannot_read_is_refused(self):
        for sid, facts in (('baseline_leaves_verdict_unchanged', {'verdicts': ['pass', 'pass']}), ('baseline_leaves_verdict_unchanged', {'m1': 'pending'}),
                           ('baseline_leaves_verdict_unchanged', {'baselines': 2}), ('old_build_reads_after', {'exit': 1}),
                           ('old_build_reads_after', {'needles': {'legacy': False}})):
            r = good_report(); get(r, sid).update(facts)
            v = judge(r)
            self.assertEqual(v['result'], 'refused', (sid, facts))
            self.assertTrue(any(sid in x for x in v['reasons']), v)

    def test_old_step_ids_cannot_stand_in_for_the_new_ones(self):
        r = good_report()
        for s in r['steps']:
            if s['id'] == 'legacy_passed_old_semantics':
                s['id'] = 'legacy_passed_after_baseline'
        v = judge(r)
        self.assertIn('mandatory step missing: legacy_passed_old_semantics', v['reasons'])

    def test_duplicate_step_id_is_refused_in_either_order(self):
        for bad_first in (False, True):
            r = good_report()
            i = next(n for n, s in enumerate(r['steps']) if s['id'] == 'legacy_passed_old_semantics')
            good = r['steps'][i]; bad = dict(good, ok=False, m1='pending', result='fail')
            r['steps'][i:i + 1] = [bad, good] if bad_first else [good, bad]
            v = judge(r)
            self.assertEqual(v['result'], 'refused')
            self.assertTrue(any('duplicate step id' in x for x in v['reasons']), v)

    def test_ok_true_while_recorded_facts_fail_is_refused(self):
        cases = [('legacy_passed_old_semantics', {'m1': 'pending'}), ('baseline_ai_refused', {'baselines': 1}),
                 ('baseline_owner_recorded', {'baselines': 2}), ('legacy_identity_unchanged', {'revision': 2}),
                 ('legacy_identity_unchanged', {'approved_rows': 2}), ('modules_from_venv', {'outside': {'onecrew': 'D:/checkout'}}),
                 ('wheel_sha', {'actual_sha256': 'X'}), ('old_venv_previous_wheel', {'previous_actual_sha256': 'X'}),
                 ('legacy_handover_no_baseline_required', {'baseline_in_page': True})]
        for sid, facts in cases:
            r = good_report(); get(r, sid).update(facts)
            v = judge(r)
            self.assertEqual(v['result'], 'refused', (sid, facts))
            self.assertTrue(any(sid in x for x in v['reasons']), (sid, v))

    def test_ok_false_while_facts_pass_is_refused(self):
        r = good_report(); get(r, 'modules_from_venv')['ok'] = False
        self.assertTrue(any('disagrees' in x for x in judge(r)['reasons']))

    def test_missing_fact_is_refused(self):
        r = good_report(); del get(r, 'legacy_passed_old_semantics')['integrity']
        self.assertTrue(any('fact missing' in x and 'legacy_passed_old_semantics' in x for x in judge(r)['reasons']))
        r = good_report(); del get(r, 'baseline_ai_refused')['events_added']
        self.assertTrue(any('fact missing' in x and 'baseline_ai_refused' in x for x in judge(r)['reasons']))

    def test_judge_is_pure(self):
        r = good_report(); before = copy.deepcopy(r); judge(r); self.assertEqual(r, before)

    # ---- Codex P1-3: the scope is the manifest's, never the report's ----
    def refused(self, report, text, scope=_DEFAULT):
        v = judge(report, scope)
        self.assertEqual(v['result'], 'refused', v)
        self.assertTrue(any(text in x for x in v['reasons']), v)
        return v

    def test_p13_flag_flipped_and_steps_removed_is_refused(self):
        r = good_report(); r['previous_wheel_present'] = False; r['steps'] = []
        self.refused(r, 'previous_wheel_present misdeclared')
        r = good_report(); r['previous_wheel_present'] = False                       # steps retained: still misdeclared
        self.refused(r, 'previous_wheel_present misdeclared')
        r = good_report(); r['steps'] = [s for s in r['steps'] if s['id'] != 'old_venv_previous_wheel']
        self.refused(r, 'mandatory step missing: old_venv_previous_wheel')

    def test_p13_declared_first_release_kind_is_not_applicable_never_pass(self):
        base = good_scope(rollback=False)
        r = {'steps': [], 'result': None, 'previous_wheel_present': False, 'package_identity': lc.pc.identity(base)}
        v = judge(r, base)
        self.assertEqual(v['result'], 'not-applicable', v)
        bad = good_report(); bad.update(previous_wheel_present=False, package_identity=lc.pc.identity(base))
        self.refused(bad, 'steps recorded although the package manifest declares no previous wheel', base)
        bad = dict(r, result='pass')
        self.refused(bad, 'incoherent', base)
        bad = dict(r, previous_wheel_present=True)
        self.refused(bad, 'previous_wheel_present misdeclared', base)

    def test_p13_swapped_identities_and_wheels_are_refused(self):
        for key, value in (('package', 'D:/elsewhere'), ('manifest_sha256', '0' * 64), ('wheel_sha256', '1'), ('previous_wheel_sha256', '2'),
                           ('verifier_files', {'verify/legacy_core.py': '3' * 64}), ('kind', 'first-release-handover-package')):
            r = good_report(); r['package_identity'][key] = value
            self.refused(r, 'package identity differs from the manifest: ' + key)
        r = good_report(); del r['package_identity']
        self.refused(r, 'no package identity')
        r = good_report(); get(r, 'old_venv_previous_wheel').update(previous={'file': 'x.whl', 'sha256': 'Q'}, previous_actual_sha256='Q')
        self.refused(r, 'different previous wheel')
        r = good_report(); get(r, 'wheel_sha').update(sha256='Z', actual_sha256='Z')
        self.refused(r, 'different wheel')

    def test_p13_missing_or_unverifiable_scope_is_refused(self):
        self.refused(good_report(), 'no verified package scope', None)
        self.refused(good_report(), 'package scope unverifiable', good_scope(reasons=['manifest missing or unreadable']))
        self.refused(good_report(), 'manifest missing or unreadable', lc.pc.package_scope(REPO / 'no-such-package-dir'))
class LegacyRootLocatorTests(unittest.TestCase):
    """Round 10: the OLD build's root is located by name in either namespace (a previous build with namespaces writes plan-ns:legacy)."""

    def setUp(self):
        import shutil
        import sqlite3
        import subprocess
        import tempfile
        self.sqlite3 = sqlite3
        self.tmp = Path(tempfile.mkdtemp(prefix='wf locator '))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.project, self.state = self.tmp / 'project', self.tmp / 'state'
        self.project.mkdir()
        for args in (['init', '-q'], ['config', 'user.name', 'v'], ['config', 'user.email', 'v@localhost']):
            subprocess.run(['git', '-C', str(self.project), *args], check=True, capture_output=True)
        (self.project / 'a.txt').write_text('base\n')
        subprocess.run(['git', '-C', str(self.project), 'add', '.'], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(self.project), 'commit', '-qm', 'base'], check=True, capture_output=True)
        ns = {}
        exec(lc.LOCATOR_SRC, ns)
        self.locate = ns['locate_root']

    def propose(self, name='legacy'):
        import json
        import sys
        from onecrew.ledger import Ledger
        from onecrew.v2 import plan
        contract = {'schema_version': 2, 'title': 'Legacy root', 'size': 'S',
                    'understanding': {'restated_goal': 'A root approved by an older build.', 'target': {'repo': '.', 'ref': 'HEAD', 'paths': ['a.txt']},
                                      'assumptions': [], 'confidence': 'high', 'unknowns': []},
                    'preconditions': [{'id': 'P1', 'check': 'path_exists', 'args': {'path': 'a.txt'}, 'why': 'the file is there'}],
                    'output': ['The sample exists'], 'scope': {'owned': ['a.txt']}, 'non_goals': ['Nothing else'],
                    'items': [{'id': 'I1', 'title': 'Do it', 'tier': 'must', 'milestone': 'M1'}],
                    'milestones': [{'id': 'M1', 'title': 'Milestone M1', 'verifier': {'type': 'command', 'config': {'argv': [sys.executable, '-c', 'print("ok")']}},
                                    'covers': ['O1']}],
                    'budget': {'max_calls': 100, 'time': 120}, 'attention': {'questions': 1}, 'profile_version': None}
        ledger = Ledger(self.project, self.state)
        plan.propose(ledger, name, contract, 'old-build-fixture')
        return ledger

    def db(self):
        return self.sqlite3.connect(str(self.state / 'ledger.sqlite3'))

    def test_root_proposed_by_a_build_with_namespaces_is_found_with_its_real_key(self):
        ledger = self.propose()
        task_id, key = self.locate(self.db, ledger.project_id)
        self.assertEqual(key, 'plan-ns:legacy')
        self.assertTrue(task_id.startswith('TASK-'))

    def test_root_proposed_by_a_build_without_namespaces_is_found_with_its_real_key(self):
        ledger = self.propose()
        c = self.db()
        c.execute("UPDATE tasks SET request_key='plan:legacy' WHERE request_key='plan-ns:legacy'")
        c.commit()
        self.assertEqual(self.locate(self.db, ledger.project_id)[1], 'plan:legacy')

    def test_missing_or_ambiguous_root_is_an_error_never_a_guess(self):
        ledger = self.propose('other')
        with self.assertRaises(RuntimeError):
            self.locate(self.db, ledger.project_id)
        self.propose('legacy')
        c = self.db()
        c.execute("INSERT INTO tasks SELECT * FROM tasks WHERE 0")      # no-op: keep the schema check honest
        c.close()
        self.assertEqual(self.locate(self.db, ledger.project_id)[1], 'plan-ns:legacy')

    def test_the_inline_scripts_use_the_located_key_not_a_hard_coded_legacy_key(self):
        src = (REPO / 'docs' / 'wf' / 'audit' / 'tools' / 'legacy_continuation.py').read_text(encoding='utf-8')
        for hard in ("--plan', 'plan:legacy'", "conn, 'plan:legacy')", "ledger, 'plan:legacy')", "request_key=?', (ledger.project_id, 'plan:legacy')"):
            self.assertNotIn(hard, src)
        self.assertIn('locate_root(db, ledger.project_id)', src)


if __name__ == '__main__':
    unittest.main()
