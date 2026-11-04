"""T48b / T25 storage slice: real new roots and an unmodified archived old CLI.

Only temporary projects/state are used. Workflow v1 currently declares the
implemented namespaced-storage capability; node revision semantics are separate.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from onecrew.ledger import Ledger, LedgerError, content_hash
from onecrew.v2 import active_plan, contract as contracts, namespaces, plan as plans, report, retention, verdict
from tests.test_v2_l1 import Fixture, plan_json
from tests import wf_oldversion as ov

REPO = Path(__file__).resolve().parents[1]
OLD = 'd3120c6'


class NamespaceTests(Fixture):
    @classmethod
    def setUpClass(cls):
        cls.archive_temp = tempfile.TemporaryDirectory(prefix='ocns-old-')
        cls.old = ov.OldVersion(ov.archive(OLD, REPO, cls.archive_temp.name))

    @classmethod
    def tearDownClass(cls):
        cls.archive_temp.cleanup()

    def legacy(self, name='alpha', title='Legacy document'):
        path = Path(self.temp.name) / ('old-' + name + '.json')
        path.write_text(json.dumps(ov.contract(title)), encoding='utf-8')
        code, output = self.old.run(self.root, self.ledger.state_root, 'plan', 'propose', name,
                                    '--file', str(path), '--author', 'codex')
        self.assertEqual(code, 0, output)
        return json.loads(output)

    def cli(self, *args):
        return subprocess.run([sys.executable, '-X', 'utf8', '-m', 'onecrew.v2.cli', '--project', str(self.root),
                               '--state-root', str(self.ledger.state_root), *args], cwd=REPO,
                              capture_output=True, text=True, encoding='utf-8', timeout=60)

    def files(self, root):
        return {p.relative_to(root).as_posix(): (content_hash(p.read_bytes().hex()), p.stat().st_mtime_ns)
                for p in root.rglob('*') if p.is_file()} if root.exists() else {}

    def test_new_schema2_roots_share_name_across_projects_without_sharing_paths(self):
        other = Ledger(ov.git_project(self.temp.name, 'P2'), self.ledger.state_root)
        first = plans.propose(self.ledger, 'beta', plan_json(title='First project'), 'codex')
        second = plans.propose(other, 'beta', plan_json(title='Second project'), 'codex')
        self.assertEqual((first['anchor'], second['anchor']), ('plan-ns:beta', 'plan-ns:beta'))
        for ledger, title in ((self.ledger, 'First project'), (other, 'Second project')):
            directory = Path(ledger.state_root) / 'plans' / ledger.project_id / 'beta'
            self.assertEqual(contracts.plan_dir(ledger, 'beta'), directory)
            self.assertEqual(contracts.read_revision(ledger, 'plan-ns:beta', 1)[0]['title'], title)
            self.assertTrue((directory / 'v1.json').is_file())
            with ledger.transaction() as conn:
                self.assertEqual(plans.derive(ledger, conn, 'beta')['selector'], 'plan-ns:beta')
        self.assertFalse((Path(self.ledger.state_root) / 'plans' / 'beta').exists())
        self.assertIn('First project', report.render_report(self.ledger.state_root, 'beta', project_id=self.ledger.project_id))
        self.assertIn('Second project', report.render_report(self.ledger.state_root, 'beta', project_id=other.project_id))
        with self.assertRaisesRegex(LedgerError, 'ambiguous'):
            report.render_report(self.ledger.state_root, 'beta')
        digest = report.render_digest(self.ledger.state_root)
        self.assertIn(self.ledger.project_id[:12], digest)
        self.assertIn(other.project_id[:12], digest)

    def test_workflow_roots_declare_only_implemented_version_and_capability(self):
        other = Ledger(ov.git_project(self.temp.name, 'P2'), self.ledger.state_root)
        for ledger in (self.ledger, other):
            view = plans.propose(ledger, 'beta', plan_json(), 'codex', workflow=True)
            self.assertEqual(view['contract']['schema_version'], 2)
            self.assertEqual(view['workflow_version'], 1)
            self.assertEqual(view['capabilities'], ['namespaced-storage', 'finding-register', 'root-budget'])
            self.assertEqual(view['anchor'], 'plan-ns:beta')
            self.assertEqual(contracts.plan_dir(ledger, 'beta'), Path(ledger.state_root) / 'plans' / ledger.project_id / 'beta')
        self.assertIn('namespaced-storage', report.render_report(self.ledger.state_root, 'beta', project_id=self.ledger.project_id))
        for metadata in ({'workflow_version': 2, 'capabilities': ['namespaced-storage']},
                         {'workflow_version': True, 'capabilities': ['namespaced-storage']},
                         {'workflow_version': 1, 'capabilities': ['automatic-execution']},
                         {'workflow_version': 1, 'capabilities': [{}]}):
            with self.assertRaisesRegex(LedgerError, 'Unsupported workflow'):
                namespaces.check_workflow(metadata)
        with self.assertRaises(LedgerError):
            plans.propose(self.ledger, 'unsupported', plan_json(), 'codex', workflow={'version': 2})

    def test_legacy_read_and_report_leave_old_files_paths_hashes_and_mtimes_unchanged(self):
        old_view = self.legacy()
        old_dir = Path(self.ledger.state_root) / 'plans' / 'alpha'
        before = self.files(old_dir)
        new_view = plans.show(self.ledger, 'alpha')
        for field in ('plan', 'status', 'revision', 'latest_revision', 'sha', 'contract', 'milestones'):
            self.assertEqual(new_view[field], old_view[field])
        self.assertEqual(new_view['anchor'], 'plan:alpha')
        code, old_report = self.old.run(self.root, self.ledger.state_root, 'plan', 'report', 'alpha')
        self.assertEqual(code, 0, old_report)
        self.assertEqual(report.render_report(self.ledger.state_root, 'alpha').strip(), old_report)
        self.assertEqual(contracts.plan_dir(self.ledger, 'alpha'), old_dir)
        self.assertEqual(self.files(old_dir), before)
        self.assertFalse((Path(self.ledger.state_root) / 'plans' / self.ledger.project_id / 'alpha').exists())

    def test_legacy_schema2_item_change_stays_amend_and_old_reader_still_reads_it(self):
        self.legacy()
        plans.approve(self.ledger, 'plan:alpha', 'owner', 'fixture approved original legacy revision')
        old = contracts.read_revision(self.ledger, 'plan:alpha', 1)[0]
        changed = json.loads(json.dumps(old))
        changed['items'][0]['title'] = 'Clarified legacy item'
        view = plans.amend(self.ledger, 'plan:alpha', changed, 'Owner clarified the item', 'codex')
        self.assertEqual((view['revision'], view['status']), (2, 'proposed'))
        self.assertEqual(view['approved_revision'], 1)
        self.assertIn('plan.amended', self.kinds('plan:alpha'))
        self.assertNotIn('plan.revised', self.kinds('plan:alpha'))
        self.assertTrue((Path(self.ledger.state_root) / 'plans' / 'alpha' / 'v2.json').exists())
        code, output = self.old.run(self.root, self.ledger.state_root, 'plan', 'show', 'alpha')
        self.assertEqual(code, 0, output)
        self.assertEqual(json.loads(output)['revision'], 2)

    def test_new_schema2_item_change_still_requires_amend_and_new_approval(self):
        self.approved()
        changed = plan_json()
        changed['items'][0]['title'] = 'Clarified schema 2 item'
        view = plans.amend(self.ledger, 'P1', changed, 'Owner clarified the item', 'codex')
        self.assertEqual((view['contract']['schema_version'], view['revision'], view['status']), (2, 2, 'proposed'))
        self.assertIn('plan.amended', self.kinds())
        self.assertNotIn('plan.revised', self.kinds())
        self.assertTrue((Path(self.ledger.state_root) / 'plans' / self.ledger.project_id / 'P1' / 'v2.json').exists())

    def test_active_copy_uses_one_project_level_and_old_hook_can_find_it(self):
        self.approved()
        copy = Path(self.ledger.state_root) / 'plans' / self.ledger.project_id / 'active-plan.json'
        document = json.loads(copy.read_text(encoding='utf-8'))
        self.assertEqual(document['project'], str(self.root.resolve()))
        self.assertEqual(document['anchor'], 'plan-ns:P1')
        self.assertFalse((copy.parent / 'P1' / 'active-plan.json').exists())
        active_plan.set_mode(self.ledger, 'enforce')
        active_plan.export(self.ledger, 'P1')
        event = {'session_id': 'namespace-fixture', 'cwd': str(self.root), 'hook_event_name': 'PreToolUse',
                 'tool_name': 'Bash', 'tool_input': {'command': 'git push origin main'}}
        env = dict(self.old.env)
        done = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'onecrew.v2.hook_cli',
                               '--project', str(self.root), '--state-root', str(self.ledger.state_root), 'hook', 'check'],
                              input=json.dumps(event), cwd=self.root, env=env,
                              capture_output=True, text=True, encoding='utf-8', timeout=60)
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)

    def test_bare_dual_anchor_refuses_and_explicit_selectors_read_amend_export_and_pin_exact_root(self):
        plans.propose(self.ledger, 'beta', plan_json(title='Namespaced document'), 'codex')
        self.legacy('beta', 'Legacy document')
        for action in (lambda: plans.show(self.ledger, 'beta'),
                       lambda: contracts.read_revision(self.ledger, 'beta', 1),
                       lambda: report.render_report(self.ledger.state_root, 'beta', project_id=self.ledger.project_id),
                       lambda: retention.list_refs(self.ledger, 'beta')):
            with self.assertRaisesRegex(LedgerError, 'ambiguous') as caught:
                action()
            self.assertIn('plan:beta', str(caught.exception))
            self.assertIn('plan-ns:beta', str(caught.exception))
        for selector, title in (('plan:beta', 'Legacy document'), ('plan-ns:beta', 'Namespaced document')):
            view = plans.show(self.ledger, selector)
            self.assertEqual(view['contract']['title'], title)
            plans.approve(self.ledger, selector, 'owner', 'fixture explicit approval')
            active = active_plan.build(self.ledger, selector)
            self.assertEqual(active['anchor'], selector)
            self.assertTrue(retention.list_refs(self.ledger, selector))
            shown = self.cli('plan', 'show', selector)
            self.assertEqual(shown.returncode, 0, shown.stdout + shown.stderr)
            self.assertEqual(json.loads(shown.stdout)['anchor'], selector)
        bare = self.cli('plan', 'show', 'beta')
        self.assertEqual(bare.returncode, 2, bare.stdout + bare.stderr)
        self.assertIn('ambiguous', bare.stdout)
        old_refs = retention.list_refs(self.ledger, 'plan:beta')
        retention.cleanup(self.ledger, 'plan-ns:beta', 'owner')
        self.assertEqual(retention.list_refs(self.ledger, 'plan:beta'), old_refs)

    def test_old_cli_cannot_see_or_continue_new_roots_and_does_not_rewrite_their_files(self):
        self.approved()
        directory = contracts.plan_dir(self.ledger, 'P1')
        before = self.files(directory)
        for args in (('plan', 'show', 'P1'), ('plan', 'report', 'P1'),
                     ('verdict', 'run', '--plan', 'P1', '--milestone', 'M1')):
            code, output = self.old.run(self.root, self.ledger.state_root, *args)
            self.assertEqual(code, 2, output)
            self.assertIn('No plan named', output)
            self.assertNotIn('Traceback', output)
        code, output = self.old.run(self.root, self.ledger.state_root, 'plan', 'digest')
        self.assertEqual(code, 0, output)
        self.assertNotIn('P1 ', output)
        self.assertEqual(self.files(directory), before)

    def test_bad_names_fail_before_writes_in_both_creation_modes(self):
        before = self.files(Path(self.ledger.state_root))
        parent = sorted(p.name for p in Path(self.temp.name).iterdir())
        for workflow in (False, True):
            for invalid in ('a:b', '../x', 'x/y', 'x\\y', 'C:x', 'D:\\x', '/absolute'):
                with self.subTest(workflow=workflow, invalid=invalid):
                    with self.assertRaises(LedgerError):
                        plans.propose(self.ledger, invalid, plan_json(), 'codex', workflow=workflow)
        self.assertEqual(self.files(Path(self.ledger.state_root)), before)
        self.assertEqual(sorted(p.name for p in Path(self.temp.name).iterdir()), parent)
