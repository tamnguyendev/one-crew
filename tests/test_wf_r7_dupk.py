"""Round 7 / R7-E: DUPk (T49 S2 fixture, 05 T49 table) is readable and acceptable by the current code.

DUPk is P3's `plan:dup` whose files sit in the per-project layout plans/<P3>/dup/ ("root đường dẫn mới mang anchor cũ", EV-J), a name
duplicate of DUPa (P1's `plan:dup` under the shared plans/dup/). Before R7-E the resolver mapped every `plan:` anchor to plans/<name>/, so
`plan show` on DUPk read P1's file and failed with "revision 1 does not match the recorded hash", and `plan digest` listed it as "mốc ?/?".
Contract: T49d N5 (R4 and DUPk accepted, rollback succeeds), T49c "tên trùng, không chặn", T49d [E7] (every root readable by the new code).
Same S2 fixture as tests.test_wf_namespace_compat (built with the REAL archived d3120c6 CLI); no owner verb runs (ov writes the events).
"""
import hashlib
import json
import unittest
from unittest.mock import patch

from onecrew.ledger import Ledger, LedgerError
from onecrew.v2 import active_plan, compat_scan, namespaces, plan, report, verdict
import tests.test_wf_namespace_compat as base
from tests import wf_oldversion as ov


def tree_hash(path):
    digest = hashlib.sha256()
    for p in sorted(path.rglob('*')):
        if p.is_file(): digest.update(p.relative_to(path).as_posix().encode() + b'\0' + p.read_bytes() + b'\0')
    return digest.hexdigest()


def file_content_sha(path):
    return json.loads(path.read_text(encoding='utf-8'))['content_sha']


class DupkReadable(base.NamespaceCompatTests):
    for _name in [n for n in dir(base.NamespaceCompatTests) if n.startswith('test_')]:
        locals()[_name] = None
    del _name

    def tearDown(self):
        for project in self.projects:
            (project / '.onecrew' / 'active-plan.json').unlink(missing_ok=True)

    def p3(self, state):
        return Ledger(self.projects[2], state)

    def own_dir(self, state):
        return state / 'plans' / self.pids[2] / 'dup'

    def recorded_sha(self, state, label, revision=1):
        return ov._sha(state, self.ids[label], revision)

    # ---- counter-example: the pre-fix rule (every plan: anchor -> plans/<name>/) ----------------------------------------------
    def test_counter_pre_fix_rule_reads_p1_file_and_fails_with_the_hash_text(self):
        state = self.copy()
        shared = lambda ledger, name: (state / 'plans' / name, None)            # the resolver as it was at c9b1e97
        with patch.object(namespaces, 'legacy_location', shared):
            with self.assertRaises(LedgerError) as caught:
                plan.show(self.p3(state), 'plan:dup')
            self.assertEqual(str(caught.exception), 'Plan plan:dup revision 1 does not match the recorded hash; the file was changed.')
            self.assertIn('mốc ?/?', report.render_digest(state))

    # ---- the fix ------------------------------------------------------------------------------------------------------------
    def test_dupk_show_reads_p3_files_and_the_hash_matches(self):
        state = self.copy()
        p1_before = tree_hash(state / 'plans' / 'dup')
        shown = plan.show(self.p3(state), 'plan:dup')
        self.assertEqual(shown['anchor_task'], self.ids['DUPk'])
        self.assertEqual((shown['anchor'], shown['status'], shown['latest_revision']), ('plan:dup', 'proposed', 1))
        self.assertEqual(shown['sha'], self.recorded_sha(state, 'DUPk'))
        self.assertEqual(shown['sha'], file_content_sha(self.own_dir(state) / 'v1.json'))
        self.assertNotEqual(shown['sha'], file_content_sha(state / 'plans' / 'dup' / 'v1.json'))
        self.assertEqual(shown['contract']['title'], 'P3-dup')
        self.assertEqual([m['id'] for m in shown['milestones']], ['M1'])
        self.assertEqual(tree_hash(state / 'plans' / 'dup'), p1_before)

    def test_dupa_still_reads_the_shared_path_exactly_as_before(self):
        state = self.copy()
        self.assertEqual(namespaces.legacy_location(Ledger(self.projects[0], state), 'dup'), (state / 'plans' / 'dup', None))
        shown = plan.show(Ledger(self.projects[0], state), 'plan:dup')
        self.assertEqual(shown['anchor_task'], self.ids['DUPa'])
        self.assertEqual(shown['sha'], file_content_sha(state / 'plans' / 'dup' / 'v1.json'))
        self.assertEqual(shown['contract']['title'], 'DUP')
        for label, index, name in (('R1', 0, 'r1'), ('R4', 0, 'r4')):          # the other legacy roots keep plans/<name>/
            self.assertEqual(namespaces.legacy_location(Ledger(self.projects[index], state), name), (state / 'plans' / name, None), label)

    def test_digest_shows_dupk_with_real_milestones(self):
        state = self.copy()
        lines = [l for l in report.render_digest(state).splitlines() if 'plan:dup' in l and self.pids[2][:12] in l]
        self.assertEqual(len(lines), 1, report.render_digest(state))
        self.assertIn('mốc 0/1', lines[0])
        self.assertNotIn('?/?', report.render_digest(state))

    def test_dupk_verdict_runs_and_is_accepted_on_its_own_files(self):
        state = self.copy()
        p1_before = tree_hash(state / 'plans' / 'dup')
        ov.make_approved(state, self.ids['DUPk'], 'dup')
        with patch.object(active_plan, 'export', lambda *a, **k: None):
            verdict.run(self.p3(state), 'plan:dup', 'M1', self.projects[2])
        shown = plan.show(self.p3(state), 'plan:dup')
        self.assertEqual(shown['status'], 'approved')
        self.assertEqual(sum(m['runs'] for m in shown['milestones']), 1)
        self.accept(state, 'DUPk')                                               # N5: DUPk accepted
        accepted = plan.show(self.p3(state), 'plan:dup')
        self.assertEqual((accepted['status'], accepted['sha']), ('accepted', self.recorded_sha(state, 'DUPk')))
        self.assertEqual(tree_hash(state / 'plans' / 'dup'), p1_before)
        self.assertEqual(plan.show(Ledger(self.projects[0], state), 'plan:dup')['anchor_task'], self.ids['DUPa'])

    def test_dupk_amend_writes_only_its_own_directory_and_active_file(self):
        state = self.copy()
        p1_before = tree_hash(state / 'plans' / 'dup')
        plan.amend(self.p3(state), 'plan:dup', dict(ov.contract('P3-dup'), title='P3 dup amended'), 'fixture', 'codex-fixture')
        self.assertTrue((self.own_dir(state) / 'v2.json').is_file())
        self.assertFalse((state / 'plans' / 'dup' / 'v2.json').exists())
        self.assertEqual(tree_hash(state / 'plans' / 'dup'), p1_before)
        self.assertEqual(plan.show(self.p3(state), 'plan:dup')['latest_revision'], 2)
        self.assertEqual(namespaces.active_file(self.p3(state), 'plan:dup'), state / 'plans' / self.pids[2] / 'active-plan.json')
        self.assertEqual(namespaces.active_file(Ledger(self.projects[0], state), 'plan:dup'), state / 'plans' / 'dup' / 'active-plan.json')

    def test_reads_other_root_warning_for_dupa_stays_a_warning(self):
        state = self.copy()
        rep = compat_scan.scan(state)
        dupa = [w for w in rep['warnings'] if w['anchor'] == 'plan:dup' and w['project_id'] == self.pids[0]]
        self.assertEqual(len(dupa), 1, rep['warnings'])
        self.assertEqual((dupa[0]['label'], dupa[0]['blocking']), (compat_scan.READS_OTHER_ROOT, False))
        self.assertEqual(dupa[0]['reads']['project_id'], self.pids[2])
        self.assertEqual([b['id'] for b in self.root(rep, 'DUPk')['blocks']], ['B3'])     # the OLD binary still branches DUPk: unchanged

    # ---- negative / mutant ------------------------------------------------------------------------------------------------
    def test_mutant_per_project_file_absent_fails_naming_the_project_not_p1_file(self):
        state = self.copy()
        (self.own_dir(state) / 'v1.json').unlink()
        with self.assertRaises(LedgerError) as caught:
            plan.show(self.p3(state), 'plan:dup')
        text = str(caught.exception)
        self.assertIn(f'of project {self.pids[2]}', text)
        self.assertIn('is unreadable', text)
        self.assertIn(str(self.own_dir(state) / 'v1.json'), text)
        self.assertIn(f'belongs to plan:dup of project {self.pids[0]}', text)
        self.assertNotIn('does not match the recorded hash', text)               # P1's plans/dup/v1.json is not read

    def test_mutant_identical_content_in_p1_does_not_make_p1_file_dupk(self):
        """Even a same-hash file of another project's root is never DUPk's: the shared directory belongs to DUPa."""
        state = self.copy()
        own = self.own_dir(state) / 'v1.json'
        shared = state / 'plans' / 'dup' / 'v1.json'
        shared.write_bytes(own.read_bytes())          # P1's directory now holds a file that hashes to DUPk's sha
        own.unlink()
        with self.assertRaisesRegex(LedgerError, f'of project {self.pids[2]}'):
            plan.show(self.p3(state), 'plan:dup')

    def test_legacy_root_with_a_namespaced_peer_in_its_project_and_no_directory_is_refused(self):
        state = self.copy()
        conn = ov._db(state)                           # P3 now also has plan-ns:dup: plans/<P3>/dup/ is that root's directory
        try:
            with conn:
                conn.execute("INSERT INTO tasks (id, project_id, project_path, request_key, revision, payload, created_at, deadline) "
                             "SELECT 'p3-ns-dup', project_id, project_path, 'plan-ns:dup', revision, payload, created_at, deadline FROM tasks WHERE id=?",
                             (self.ids['DUPk'],))
        finally:
            conn.close()
        with self.assertRaisesRegex(LedgerError, 'has no directory of its own'):
            plan.show(self.p3(state), 'plan:dup')


if __name__ == '__main__':
    unittest.main()
