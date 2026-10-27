"""R12 (Codex round 12, P1-A): the state an output must be in is decided by the approved contract, never inferred from prose.

R11 made every write path whose name appears in the node `output` prose (or in a contract output criterion of the node acceptance) a
"required output" that had to exist and be non-empty. Codex reproduced the consequence: contract output "The obsolete a.txt is deleted",
node output "a.txt is removed", worker answers `content: null` for a.txt -> refused as "required output missing / deleted".

Invariants (docs/wf/r12-notes.md 1-3): `write` is permission; naming a path in prose creates no obligation; the worker's `content: null`
or `content: ""` is a declaration that must match the candidate, and it never exempts the candidate from acceptance; the contract's own
approved milestones judge the required state of an output. Every case runs through engine.step (artifact v1 API -> Snapshots.overlay),
the sequential engine and the real CandidateChecker via engine.verify on a real temporary Git project.
"""
import json
import os
import sys
import unittest

from onecrew.artifact_core import artifacts
from onecrew.common_verification import CandidateChecker
from onecrew.control import Control, migrate
from onecrew.snapshots import Snapshots
from onecrew.v2 import engine, internal_plan, plan as plans
from tests.test_v2_l1 import Fixture, plan_json, milestone
from tests.test_wf_engine import node

REPORT = 'docs/rep/R.md'
EMPTY = 'notes/empty.txt'
OWNED = ['a.txt', 'b.txt', REPORT, EMPTY, 'c.txt', 'z.txt']


def _probe(condition):
    """A real contract milestone: a command that prints its answer and exits 0 only when `condition` holds in the candidate checkout."""
    return 'import os,sys; ok = ' + condition + '; print("ok" if ok else "not satisfied"); sys.exit(0 if ok else 1)'   # single-line argv


def ABSENT(path): return _probe(f'not os.path.lexists({path!r})')
def NONEMPTY(path): return _probe(f'os.path.isfile({path!r}) and os.path.getsize({path!r}) > 0')
def EMPTY_FILE(path): return _probe(f'os.path.isfile({path!r}) and os.path.getsize({path!r}) == 0')
NOTHING = 'print("milestone reads none of the outputs")'


class R12Fixture(Fixture):
    contract_output = ['The sample exists']
    check_code = NOTHING

    def setUp(self):
        Fixture.setUp(self)
        self.files = {'b.txt': 'keep me\n', 'c.txt': 'third\n'}
        self.prepared = False

    def prepare(self):
        if self.prepared: return
        self.prepared = True
        for name, text in self.files.items():
            path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
        self.git('add', '-f', '.'); self.git('commit', '-qm', 'sources')
        selected = [milestone(argv=[sys.executable, '-c', self.check_code])]; self.check_ids = [row['id'] for row in selected]
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

    def revise(self, nodes):
        for one in nodes: one['checks'] = [{'id': c, 'spec': 'The exact approved root command ' + c} for c in self.check_ids]
        internal_plan.revise(self.ledger, 'P1', nodes, reason='Split work inside the approved scope', evidence=['a.txt:1'])

    def native_base(self, current):
        """What NativeExecutor.prepare builds: a capture of read+write, then the engine-recorded producer outputs, then a resumed candidate."""
        paths = sorted(set(current['read'] + current['write']))
        base = self.store.capture(self.root, paths)
        inherited = {}
        for binding in current.get('input_artifacts', {}).values():
            produced = self.store.load(binding['artifact'])['files']
            for path in binding.get('write', []):
                if path in paths and path in produced:
                    row = produced[path]['working']
                    inherited[path] = self.store.read_blob(row) if row else None
        if inherited: base = self.store.overlay(base, inherited, paths)
        if current.get('resume_artifact'):
            kept = self.store.load(current['resume_artifact'])['files']
            carried = {p: (self.store.read_blob(r['working']) if r['working'] else None) for p, r in kept.items() if p in current['write'] and p in paths}
            if carried: base = self.store.overlay(base, carried, paths)
        return base

    def step(self, build, receipt=b'fixture producer'):
        """One engine step whose executor body builds the candidate with `build(current) -> artifact`."""
        def execute(ledger, control, task, current, attempt):
            control.launched(attempt['id'], attempt['generation'], {'fixture': True})
            artifact = build(current)
            control.finish(attempt['id'], attempt['generation'], {'artifact': artifact})
            body = receipt(artifact, attempt) if callable(receipt) else receipt
            return {'artifact': artifact, 'receipt': self.store.blob(body)}
        return engine.step(self.ledger, 'P1', execute, control=self.control)

    def worker(self, files):
        """A worker answering the artifact v1 `files` list [(path, content|None)] on top of the native base."""
        def build(current):
            base = self.native_base(current)
            changes = artifacts({'summary': 'fixture worker', 'backlog': [], 'files': [{'path': p, 'content': c} for p, c in files]}, current['write'])
            return self.store.overlay(base, changes, current['write'])
        return build

    def run_node(self, files, write, output=('Evidence for O1',), read=('a.txt',)):
        self.prepare()
        item = node('C', write=write); item['output'] = list(output); item['read'] = list(read)
        self.revise([item, node('I', ['C'], integration=True, write=())])
        self.step(self.worker(files))
        return engine.verify(self.ledger, 'P1', 'C', self.checker)

    def assertPasses(self, result):
        out = result['observed']['output_check']
        self.assertEqual((result['result'], out['result']), ('pass', 'pass'), json.dumps(out))
        self.assertEqual([row['result'] for row in result['observed']['checks']], ['pass'] * len(self.check_ids))
        return out

    def assertMilestoneRefuses(self, result):
        """Refused by the contract's own approved milestone; the structural guard (declaration vs candidate) passed."""
        out = result['observed']['output_check']
        self.assertEqual((result['result'], out['result']), ('fail', 'pass'), json.dumps(out))
        self.assertEqual([row['result'] for row in result['observed']['checks']], ['fail'])
        return out

    def assertOutFails(self, result, *reasons):
        out = result['observed']['output_check']
        self.assertEqual((result['result'], out['result']), ('fail', 'fail'), json.dumps(out))
        for reason in reasons: self.assertIn(reason, out['reason'])
        return out


class ContractDecidesTheOutputState(R12Fixture):
    def test_1_correct_deletion_of_a_file_named_in_the_output_passes(self):
        # the Codex reproduction, with a contract milestone that checks the deletion and one that reads nothing
        for code in (ABSENT('a.txt'), NOTHING):
            with self.subTest(code=code[:40]):
                if self.prepared: self.setUp()
                self.files['a.txt'] = 'obsolete\n'
                self.contract_output, self.check_code = ['The obsolete a.txt is deleted'], code
                out = self.assertPasses(self.run_node([('a.txt', None)], write=['a.txt'], output=['a.txt is removed']))
                self.assertEqual(out['declared'], {'a.txt': 'deleted'})
                self.assertEqual(out['missing'], [])

    def test_2_deleting_a_file_the_contract_requires_kept_or_created_is_refused(self):
        self.files['a.txt'] = 'must stay\n'
        self.contract_output, self.check_code = ['a.txt keeps its content'], NONEMPTY('a.txt')
        out = self.assertMilestoneRefuses(self.run_node([('a.txt', None)], write=['a.txt', REPORT], output=['a.txt is kept']))
        self.assertEqual(out['declared']['a.txt'], 'deleted')
        # created: a deletion answer for a file that must be created leaves it absent; the milestone refuses it
        self.setUp()
        self.contract_output, self.check_code = ['The report ' + REPORT + ' is created'], NONEMPTY(REPORT)
        self.assertMilestoneRefuses(self.run_node([(REPORT, None), ('c.txt', 'changed\n')], write=['c.txt', REPORT], output=['Report ' + REPORT]))

    def test_3_missing_required_report_is_refused(self):
        self.contract_output, self.check_code = ['The review report ' + REPORT + ' exists'], NONEMPTY(REPORT)
        out = self.assertMilestoneRefuses(self.run_node([('c.txt', 'changed\n')], write=['c.txt', REPORT], output=['Report at ' + REPORT]))
        self.assertEqual(out['declared'][REPORT], 'unchanged')

    def test_4_valid_empty_file_per_contract_passes_also_when_it_was_already_empty(self):
        self.contract_output, self.check_code = ['An empty marker ' + EMPTY], EMPTY_FILE(EMPTY)
        out = self.assertPasses(self.run_node([(EMPTY, '')], write=[EMPTY], output=['An empty marker `' + EMPTY + '`']))
        self.assertEqual(out['declared'][EMPTY], 'empty')
        for files in ([(EMPTY, '')], [('c.txt', 'changed\n')]):   # already empty in the source: declared again / left untouched
            with self.subTest(files=files):
                self.setUp()
                self.files[EMPTY] = ''
                self.contract_output, self.check_code = ['An empty marker ' + EMPTY], EMPTY_FILE(EMPTY)
                out = self.assertPasses(self.run_node(files, write=[EMPTY, 'c.txt'], output=['An empty marker `' + EMPTY + '`']))
                self.assertEqual(out['declared'][EMPTY], 'unchanged')

    def test_5_a_report_declared_empty_is_not_exempt_from_the_contract(self):
        # The contract asks for findings in the report; the worker declares it empty. The declaration matches the candidate (OUT passes:
        # it is a structural check), and the approved milestone - not the worker's declaration - refuses it.
        self.contract_output, self.check_code = ['The report ' + REPORT + ' lists the findings'], NONEMPTY(REPORT)
        out = self.assertMilestoneRefuses(self.run_node([(REPORT, '')], write=[REPORT], output=['Findings in ' + REPORT]))
        self.assertEqual(out['declared'][REPORT], 'empty')
        self.setUp()   # the same answer for an already empty report: still refused by the contract
        self.files[REPORT] = ''
        self.contract_output, self.check_code = ['The report ' + REPORT + ' lists the findings'], NONEMPTY(REPORT)
        self.assertMilestoneRefuses(self.run_node([(REPORT, '')], write=[REPORT], output=['Findings in ' + REPORT]))

    def test_6_a_write_path_the_worker_did_not_need_creates_no_obligation(self):
        out = self.assertPasses(self.run_node([('c.txt', 'changed\n')], write=[REPORT, EMPTY, 'c.txt'],
                                              output=['Report ' + REPORT + ', marker ' + EMPTY + ' and c.txt']))
        self.assertEqual(out['declared'], {REPORT: 'unchanged', EMPTY: 'unchanged', 'c.txt': 'content'})
        self.assertNotIn('required', out)

    def test_7_different_phrasing_of_the_same_contract_gives_the_same_outcome(self):
        phrasings = [(['The obsolete a.txt is deleted'], ['a.txt is removed']),
                     (['Remove the obsolete file'], ['The old file is gone']),
                     (['`a.txt` no longer exists.'], ['Delete a.txt.']),
                     (['a.txt'], ['a.txt'])]
        outcomes = []
        for code in (ABSENT('a.txt'), NONEMPTY('a.txt')):
            for contract_output, output in phrasings:
                with self.subTest(code=code[-60:], output=output):
                    if self.prepared: self.setUp()
                    self.files['a.txt'] = 'obsolete\n'
                    self.contract_output, self.check_code = contract_output, code
                    result = self.run_node([('a.txt', None)], write=['a.txt'], output=output)
                    out = result['observed']['output_check']
                    outcomes.append((code, result['result'], out['result'], tuple(r['result'] for r in result['observed']['checks']), out['reason']))
        by_code = {}
        for code, *rest in outcomes: by_code.setdefault(code, set()).add(tuple(rest))
        self.assertEqual(by_code[ABSENT('a.txt')], {('pass', 'pass', ('pass',), '')})
        self.assertEqual(by_code[NONEMPTY('a.txt')], {('fail', 'pass', ('fail',), '')})


class DeclarationMustMatchTheCandidate(R12Fixture):
    """The valid intent of R11 stays: the declaration is checked against the real candidate tree."""
    def test_8_declared_content_and_deletion_match_the_tree(self):
        self.files['a.txt'] = 'old\n'
        out = self.assertPasses(self.run_node([('a.txt', None), (REPORT, 'Cites b.txt:1.\n')], write=['a.txt', REPORT], read=['a.txt', 'b.txt']))
        self.assertEqual(out['declared'], {'a.txt': 'deleted', REPORT: 'content'})
        self.assertEqual((out['still_present'], out['content_differs'], out['outside_scope']), ([], [], []))


if __name__ == '__main__':
    unittest.main()
