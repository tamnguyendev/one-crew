"""R11 (Codex round 11, finding A): the output guard separates the node's write PERMISSION from its REQUIRED outputs.

Every candidate here is produced through the artifact v1 API (`artifact_core.artifacts` -> `Snapshots.overlay`, exactly as the native
executor's finish() does), sealed by the sequential engine and judged by the real CandidateChecker through `engine.verify`.
Valid: a deletion inside the write scope, an intentionally empty file, a required output declared empty.
Refused: a required report missing, a required report deleted, a required output empty that the artifact did not declare empty, and a
deletion outside the write scope (refused by the artifact API itself, and by the guard when a manifest bypasses the API).

R12 (P1-A, docs/wf/r12-notes.md invariants 1-2): naming a path in prose no longer makes it required. Tests d-i keep their intent, but
the requirement is now the contract's own milestone (a real command on the candidate), not a path token in the `output` text: the
structural guard passes (the declaration matches the tree) and the milestone refuses. `required`/`deleted_required`/`empty_required`
are gone from the OUT receipt."""
import json
import os
import sys

from onecrew.artifact_core import artifacts
from onecrew.common_verification import CandidateChecker
from onecrew.control import Control, migrate
from onecrew.ledger import LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import engine, internal_plan, plan as plans
from tests.test_v2_l1 import Fixture, plan_json, milestone
from tests.test_wf_engine import node

REPORT = 'docs/rep/R.md'


def _probe(condition):   # R12: a real contract milestone (single-line argv) that prints its answer
    return 'import os,sys; ok = ' + condition + '; print("ok" if ok else "not satisfied"); sys.exit(0 if ok else 1)'
def NONEMPTY(path): return _probe(f'os.path.isfile({path!r}) and os.path.getsize({path!r}) > 0')
def EMPTY_FILE(path): return _probe(f'os.path.isfile({path!r}) and os.path.getsize({path!r}) == 0')
EMPTY = 'notes/empty.txt'
OWNED = ['a.txt', 'b.txt', REPORT, EMPTY, 'c.txt']


class OutputGuardFixture(Fixture):
    contract_output = ['The sample exists']
    check_code = 'print("milestone reads none of the outputs")'

    def setUp(self):
        Fixture.setUp(self)
        self.files = {'b.txt': 'keep me\n', 'c.txt': 'third\n'}
        self.prepared = False

    def prepare(self):
        for name, text in self.files.items():
            path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
        self.git('add', '-f', '.'); self.git('commit', '-qm', 'sources')
        check = [sys.executable, '-c', self.check_code]
        selected = [milestone(argv=check)]; self.check_ids = [row['id'] for row in selected]
        value = plan_json(milestones=selected, output=list(self.contract_output), scope={'owned': OWNED}, authority={
            'edit': True, 'commands': True, 'apply_to_project': True, 'unconfined_commands': True,
            'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q9', 'Q12']})
        plans.propose(self.ledger, 'P1', value, 'codex', workflow=True,
                      capabilities=['namespaced-storage', 'root-budget', 'internal-plan', 'sequential-engine'])
        plans.approve(self.ledger, 'P1', 'owner', 'fixture approved command and apply')
        os.environ['ONECREW_ACTOR'] = 'codex'
        self.store = Snapshots(self.ledger.state_root)
        migrate(self.ledger); self.control = Control(self.ledger)
        self.checker = CandidateChecker(self.ledger, 'P1')

    def run_node(self, files, write, output=('Evidence for O1',), read=('a.txt',), tamper=None):
        """Node C may write `write`, names `output`, and its worker answers the artifact v1 `files` list `files` [(path, content|None)]."""
        self.prepare()
        item = node('C', write=write); item['output'] = list(output); item['read'] = list(read)
        nodes = [item, node('I', ['C'], integration=True, write=())]
        for one in nodes: one['checks'] = [{'id': c, 'spec': 'The exact approved root command ' + c} for c in self.check_ids]
        internal_plan.revise(self.ledger, 'P1', nodes, reason='Split work inside the approved scope', evidence=['a.txt:1'])
        def execute(ledger, control, task, current, attempt):
            control.launched(attempt['id'], attempt['generation'], {'fixture': True})
            base = self.store.capture(self.root, sorted(set(current['read'] + current['write'])))
            changes = artifacts({'summary': 'fixture worker', 'backlog': [], 'files': [{'path': p, 'content': c} for p, c in files]}, current['write'])
            artifact = self.store.overlay(base, changes, current['write'])
            if tamper: artifact = tamper(base, artifact)
            control.finish(attempt['id'], attempt['generation'], {'artifact': artifact})
            return {'artifact': artifact, 'receipt': self.store.blob(b'fixture producer')}
        engine.step(self.ledger, 'P1', execute, control=self.control)
        return engine.verify(self.ledger, 'P1', 'C', self.checker)

    def assertPasses(self, result):
        out = result['observed']['output_check']
        self.assertEqual((result['result'], out['result']), ('pass', 'pass'), json.dumps(out))
        self.assertEqual([row['id'] for row in result['observed']['checks']], self.check_ids)
        return out

    def assertMilestoneRefuses(self, result):
        out = result['observed']['output_check']
        self.assertEqual((result['result'], out['result']), ('fail', 'pass'), json.dumps(out))
        self.assertEqual([row['result'] for row in result['observed']['checks']], ['fail'] * len(self.check_ids))
        return out

    def assertOutFails(self, result, *reasons):
        out = result['observed']['output_check']
        self.assertEqual((result['result'], out['result']), ('fail', 'fail'), json.dumps(out))
        for reason in reasons: self.assertIn(reason, out['reason'])
        return out


class PermittedChangesPass(OutputGuardFixture):
    def test_a_deletion_inside_the_write_scope_passes(self):
        self.files['a.txt'] = 'to delete\n'
        out = self.assertPasses(self.run_node([('a.txt', None)], write=['a.txt', REPORT]))
        self.assertEqual(out['declared'], {'a.txt': 'deleted', REPORT: 'unchanged'})
        self.assertEqual(out['missing'], [])

    def test_b_intentionally_empty_file_passes(self):
        out = self.assertPasses(self.run_node([(EMPTY, ''), (REPORT, 'Cites b.txt:1.\n')], write=[EMPTY, REPORT]))
        self.assertEqual(out['declared'][EMPTY], 'empty')
        self.assertEqual(out['counts']['resolved'], 1)

    def test_c_a_write_path_the_worker_did_not_touch_is_permission_not_obligation(self):
        out = self.assertPasses(self.run_node([(REPORT, 'Done.\n')], write=[REPORT, EMPTY, 'c.txt']))
        self.assertEqual(out['declared'], {REPORT: 'content', EMPTY: 'unchanged', 'c.txt': 'unchanged'})

    def test_d_required_output_written_with_content_passes(self):
        self.check_code = NONEMPTY(REPORT)
        out = self.assertPasses(self.run_node([(REPORT, 'All good.\n')], write=[REPORT, 'c.txt'], output=['The report ' + REPORT + '.']))
        self.assertEqual(out['declared'][REPORT], 'content')

    def test_e_required_output_the_artifact_declared_empty_passes(self):
        self.check_code = EMPTY_FILE(EMPTY)
        out = self.assertPasses(self.run_node([(EMPTY, '')], write=[EMPTY], output=['An empty marker `' + EMPTY + '`']))
        self.assertEqual(out['declared'][EMPTY], 'empty')


class RequiredAndOutsideRefused(OutputGuardFixture):
    def test_f_required_report_missing_fails(self):
        self.check_code = NONEMPTY(REPORT)
        out = self.assertMilestoneRefuses(self.run_node([('c.txt', 'changed\n')], write=['c.txt', REPORT], output=['Report at ' + REPORT]))
        self.assertEqual(out['declared'][REPORT], 'unchanged')

    def test_g_required_report_named_by_the_contract_output_missing_fails(self):
        self.contract_output = ['The review report ' + REPORT + ' exists']
        self.check_code = NONEMPTY(REPORT)
        self.assertMilestoneRefuses(self.run_node([('c.txt', 'changed\n')], write=['c.txt', REPORT]))

    def test_h_required_report_deleted_by_the_artifact_fails(self):
        self.files[REPORT] = 'old report\n'
        self.check_code = NONEMPTY(REPORT)
        out = self.assertMilestoneRefuses(self.run_node([(REPORT, None)], write=[REPORT], output=['Report ' + REPORT]))
        self.assertEqual(out['declared'][REPORT], 'deleted')

    def test_i_required_output_empty_that_the_artifact_did_not_declare_empty_fails(self):
        self.files[REPORT] = ''
        self.check_code = NONEMPTY(REPORT)
        self.assertMilestoneRefuses(self.run_node([('c.txt', 'changed\n')], write=['c.txt', REPORT], output=['Report ' + REPORT]))

    def test_j_deletion_outside_the_write_scope_is_refused_by_the_artifact_api(self):
        with self.assertRaises(LedgerError):
            artifacts({'summary': 's', 'backlog': [], 'files': [{'path': 'b.txt', 'content': None}]}, ['a.txt'])
        self.prepare()
        base = self.store.capture(self.root, ['a.txt', 'b.txt'])
        with self.assertRaises(LedgerError):
            self.store.overlay(base, {'b.txt': None}, ['a.txt'])

    def test_k_deletion_outside_the_write_scope_that_bypasses_the_api_fails_the_guard(self):
        def tamper(base, artifact):
            manifest = self.store.load(artifact)
            manifest['files']['b.txt']['working'] = None   # b.txt is only READ by the node
            return self.store.save(manifest)
        self.assertOutFails(self.run_node([('a.txt', 'new\n')], write=['a.txt'], read=['a.txt', 'b.txt'], tamper=tamper),
                            'changed outside the write scope', 'b.txt')


if __name__ == '__main__':
    import unittest; unittest.main()
