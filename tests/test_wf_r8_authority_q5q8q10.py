"""Round 8 G: Q5 / Q8 / Q10 when a WORKFLOW root's explicit grant does not delegate the class (owner night directive 25/10, item 1).

Defect (Codex, ae8a67f): internal_plan.self_decided returned None for a class missing from grant.self_decide and every caller went on, so a
workflow root whose grant does not list Q5 still had its repair created - a decision outside the delegated authority, taken silently.
The three classes are not the same kind of move (00 §2.2, HD-25, HD-32), so each caller follows its own semantics:
  * Q5 (an ACTION that changes the plan): not delegated -> U3 recorded, the repair is NOT created (no receipt blob, no plan.revised), the
    affected nodes are held and the owner gets the one v2.workflow_hold card; recovery goes on only through the answered request.
  * Q8 (the finding hold is the SAFE default): the branch is held whatever the grant; not delegated -> the U3 record of that safety hold
    (scope + reopen condition), no card (an owner `continue` cannot reopen a finding-held branch; the register closes it).
  * Q10 (an outcome is EVIDENCE): always written; not delegated -> the U3 record marks it evidence only / proposals only; nothing applied.
  * A root with no workflow grant (no `authority` field): nothing new is recorded, behaviour as before.
Every case runs through the REAL caller (repair_tasks.prepare, engine.verify -> findings.record_node_verification, outcome.record) on a
temporary ledger with the engine fixtures (fixture worker/checker = interface only).
"""
import os
from unittest.mock import patch

from onecrew.control_core import Control, migrate
from onecrew.ledger import LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import engine, findings, internal_plan, outcome, plan, questions, repair_tasks
from tests.test_v2_l1 import Fixture, milestone, plan_json
from tests.test_wf_engine import EngineFixture, node

WITHOUT = ['Q1', 'Q2', 'Q3', 'Q4', 'Q9', 'Q12']                 # the grant most engine fixtures carry: no Q5, Q8, Q10
ENGINE = ['namespaced-storage', 'root-budget', 'internal-plan', 'sequential-engine']
REGISTER = ENGINE[:1] + ['finding-register'] + ENGINE[1:]


class _Root(EngineFixture):
    SELF_DECIDE = WITHOUT
    CAPS = ENGINE
    AUTHORITY = True

    def setUp(self):
        Fixture.setUp(self)
        self.engine, self.ip = engine, internal_plan
        extra = {'authority': {'edit': True, 'commands': True, 'edit_tests': True, 'self_decide': list(self.SELF_DECIDE)}} if self.AUTHORITY else {}
        raw = plan_json(milestones=[milestone()], scope={'owned': ['a.txt', 'b.txt']}, **extra)
        self.root_view = plan.propose(self.ledger, 'P1', raw, 'codex', workflow=True, capabilities=list(self.CAPS))
        plan.approve(self.ledger, 'P1', 'owner', 'temporary fixture grant')
        self.store = Snapshots(self.ledger.state_root); migrate(self.ledger); self.control = Control(self.ledger)
        os.environ['ONECREW_ACTOR'] = 'codex'

    def decisions(self, component):
        return [p for k, p in self.events() if k == 'decision.recorded' and p['subject']['component'] == component]

    def requests(self):
        with self.ledger.transaction() as conn:
            return [dict(r) for r in conn.execute('SELECT * FROM requests')]

    def repair_blobs(self):
        found = []
        for path in (self.store.root / 'blobs').iterdir():
            try:
                if b'"node-repair-plan"' in path.read_bytes(): found.append(path.name)
            except OSError:
                pass
        return found

    def failure(self, item, artifact):
        return {'artifact': artifact, 'checks': [{'id': c['id'], 'result': 'fail' if c['id'] == 'F1' else 'pass',
                'evidence': self.store.blob(('actual check ' + c['id']).encode())} for c in item['checks']]}

    def fail_c(self):
        changed = node('C'); changed['checks'] = [{'id': cid, 'spec': 'Mandatory ' + cid} for cid in ['A1', 'F1']]
        independent = node('B', write=['b.txt']); independent['read'] = ['b.txt']
        integration = node('I', ['C', 'B'], integration=True, write=()); integration['read'] = []
        self.revise([changed, independent, integration])
        self.step(); self.verify('C', self.failure)
        self.step(); self.verify('B')
        return self.engine.state(self.ledger, 'P1')


class Q5NotDelegatedTests(_Root):
    def test_1_repair_is_not_created_u3_is_recorded_and_the_owner_gets_one_hold_card(self):
        before = self.fail_c()
        receipt = before['nodes']['C']['verification_receipt']
        kinds_before = self.kinds()
        with self.assertRaisesRegex(LedgerError, r'^U3: Q5 is not delegated to OneCrew by this root \(self_decide\); the repair was not created'):
            repair_tasks.prepare(self.ledger, 'P1', 'C', 'C', reason='Fix the actual F1 failure', evidence=[receipt])
        after = self.engine.state(self.ledger, 'P1')
        # no partial write of the repair: same internal revision, no plan.revised, no repair receipt blob, no repair marker on any node
        self.assertEqual(after['internal_revision'], before['internal_revision'])
        new = self.kinds()[len(kinds_before):]
        self.assertNotIn('plan.revised', new)
        self.assertEqual(self.repair_blobs(), [])
        self.assertFalse([i for n in after['definition']['nodes'] for i in n['input'] if i.startswith(repair_tasks.PREFIX)])
        # the U3 verdict is the HD-05 record of the repair component
        [decision] = self.decisions('onecrew.repair_tasks')
        self.assertEqual(decision['validity']['outcome'], 'out_of_authority')
        self.assertEqual(decision['validity']['class'], 'U3')
        self.assertEqual(set(decision['scope'].split(',')), {'C', 'I'})
        self.assertTrue(decision['key'].startswith('q5-repair-'))
        # the affected scope is held, the independent node is not; nothing is ready
        self.assertEqual({nid for nid, r in after['nodes'].items() if r['phase'] == 'held'}, {'C', 'I'})
        self.assertEqual(after['nodes']['B']['state'], 'verified')
        self.assertEqual(self.engine.ready(self.ledger, 'P1'), [])
        # ONE v2.workflow_hold request card for the owner, naming the Q5 action and U3
        [request] = questions.list_for_plan(self.ledger, 'P1', pending=True)
        action = request['question']['action']
        self.assertEqual(action['type'], 'v2.workflow_hold')
        params = action['parameters']
        self.assertEqual(params['reason_class'], 'U3')
        self.assertEqual(params['requested_action']['q'], 'Q5')
        self.assertEqual(params['affected'], ['C', 'I'])
        self.assertTrue(params['card']['evidence'])
        # asking again is the same request and the same record, not a second repair or card
        with self.assertRaises(LedgerError):
            repair_tasks.prepare(self.ledger, 'P1', 'C', 'C', reason='Fix the actual F1 failure', evidence=[receipt])
        self.assertEqual(len(self.requests()), 1)
        self.assertEqual(len(self.decisions('onecrew.repair_tasks')), 1)
        self.assertEqual(self.repair_blobs(), [])

    def test_1b_recovery_continues_only_through_the_answered_request_and_never_runs_the_repair(self):
        before = self.fail_c()
        with self.assertRaises(LedgerError):
            repair_tasks.prepare(self.ledger, 'P1', 'C', 'C', reason='Fix the actual F1 failure',
                                 evidence=[before['nodes']['C']['verification_receipt']])
        self.assertEqual(self.step()['state'], 'waiting')                       # no answer: the held work does not move
        [request] = questions.list_for_plan(self.ledger, 'P1', pending=True)
        with patch.dict(os.environ, {'ONECREW_ACTOR': ''}):
            effect = questions.answer(self.ledger, request['id'], request['revision'], 'continue', 'owner decision fixture')['controller_effect']
        self.assertEqual(effect['effect'], 'continued_within_grant')
        self.assertFalse(effect['grants_authority'])
        after = self.engine.state(self.ledger, 'P1')
        for nid in ('C', 'I'):
            self.assertEqual(after['nodes'][nid]['generation'], before['nodes'][nid]['generation'] + 1)
            self.assertEqual(after['nodes'][nid]['phase'], 'pending')
        self.assertEqual(after['internal_revision'], before['internal_revision'])   # the answer did not create the repair either
        self.assertEqual(self.repair_blobs(), [])
        self.assertEqual(self.step()['node'], 'C')


class Q5DelegatedTests(_Root):
    SELF_DECIDE = WITHOUT + ['Q5']

    def test_2_repair_is_created_with_its_in_authority_hd05_record_and_no_request(self):
        before = self.fail_c()
        made = repair_tasks.prepare(self.ledger, 'P1', 'C', 'C', reason='Fix the actual F1 failure',
                                    evidence=[before['nodes']['C']['verification_receipt']])
        self.assertEqual(made['affected_nodes'], ['C', 'I'])
        self.assertEqual(self.engine.state(self.ledger, 'P1')['internal_revision'], before['internal_revision'] + 1)
        self.assertEqual(self.repair_blobs(), [made['receipt']])
        [decision] = self.decisions('onecrew.repair_tasks')
        self.assertEqual(decision['validity']['outcome'], 'in_authority')
        self.assertIn(made['receipt'], decision['evidence'][0]['action'])
        self.assertEqual(self.requests(), [])


class _FindingRoot(_Root):
    CAPS = REGISTER

    def red(self, item, artifact):
        return {'artifact': artifact, 'checks': [{'id': c['id'], 'result': 'fail', 'evidence': self.store.blob(b'integration disagrees')}
                                                 for c in item['checks']]}

    def run_to_finding(self):
        c = node('C'); d = node('D', write=('b.txt',)); d['read'] = ['b.txt']
        integration = node('I', ['C', 'D'], integration=True, write=()); integration['read'] = ['a.txt', 'b.txt']
        self.revise([c, d, integration])
        for nid in ('C', 'D'):
            self.assertEqual(self.step()['node'], nid); self.verify(nid)
        self.assertEqual(self.step()['node'], 'I')
        self.assertEqual(self.verify('I', self.red)['result'], 'fail')        # engine.verify -> findings.record_node_verification
        [finding] = findings.list_findings(self.ledger, 'P1', open_only=True)
        return finding


class Q8NotDelegatedTests(_FindingRoot):
    def test_3_branch_is_still_held_and_the_safety_hold_is_recorded_out_of_authority(self):
        finding = self.run_to_finding()
        view = self.engine.state(self.ledger, 'P1')
        self.assertEqual(set(view['finding_blockers']), {'C', 'D', 'I'})          # the hold never depends on delegation
        self.assertFalse(self.engine.verification_ready(self.ledger, 'P1'))
        [decision] = self.decisions('onecrew.findings')
        self.assertEqual(decision['validity']['outcome'], 'out_of_authority')
        self.assertEqual(decision['validity']['class'], 'U3')
        self.assertEqual(set(decision['scope'].split(',')), {'C', 'D', 'I'})
        self.assertIn(finding['id'], decision['evidence'][0]['action'])
        self.assertIn('"hold":"safety"', decision['evidence'][0]['action'])
        self.assertIn('Q8 is not delegated', decision['basis'])
        # no card: an owner `continue` cannot reopen a finding-held branch (resume_held refuses while it is open); the register closes it
        self.assertEqual(self.requests(), [])
        self.assertIn('resolve on a passing receipt or reject with evidence', findings.REOPEN)


class Q8DelegatedTests(_FindingRoot):
    SELF_DECIDE = WITHOUT + ['Q8']

    def test_3b_delegated_q8_records_the_same_hold_in_authority(self):
        self.run_to_finding()
        self.assertEqual(set(self.engine.state(self.ledger, 'P1')['finding_blockers']), {'C', 'D', 'I'})
        [decision] = self.decisions('onecrew.findings')
        self.assertEqual(decision['validity']['outcome'], 'in_authority')
        self.assertEqual(self.requests(), [])


class _Ended(_Root):
    def close(self):
        with self.ledger.transaction(write=True) as conn:
            root = plan.anchor_events(self.ledger, conn, 'P1')
            plan.emit(self.ledger, conn, root['task_id'], 'plan.closed',
                      {'revision': root['approved']['revision'], 'reason': 'owner stopped the fixture'})


class Q10NotDelegatedTests(_Ended):
    def test_4_outcome_is_recorded_marked_evidence_and_proposal_only_and_nothing_is_applied(self):
        self.close()
        kinds_before = self.kinds()
        written = outcome.record(self.ledger, 'P1')
        self.assertTrue(written['recorded'], written)
        self.assertEqual(written['q10'], {'delegation': internal_plan.NOT_DELEGATED, 'proposal_only': True, 'applied': []})
        [decision] = self.decisions('onecrew.outcome')
        self.assertEqual(decision['validity']['outcome'], 'out_of_authority')
        self.assertEqual(decision['validity']['class'], 'U3')
        for marker in ('"proposals":"proposal_only"', '"recorded":"evidence"', '"applied":[]', written['id']):
            self.assertIn(marker, decision['evidence'][0]['action'])
        new = self.kinds()[len(kinds_before):]
        self.assertEqual(new.count('learning.outcome'), 1)
        # nothing auto-applied: no lesson, rule, skill or request event beside the outcome, its record and its context entry
        self.assertFalse([k for k in new if k not in ('learning.outcome', 'decision.recorded', 'context.entry')], new)
        self.assertEqual(self.requests(), [])

class Q10DelegatedTests(_Ended):
    SELF_DECIDE = WITHOUT + ['Q10']

    def test_4b_delegated_q10_is_in_authority_and_still_applies_nothing(self):
        self.close()
        written = outcome.record(self.ledger, 'P1')
        self.assertEqual(written['q10']['delegation'], internal_plan.DELEGATED)
        [decision] = self.decisions('onecrew.outcome')
        self.assertEqual(decision['validity']['outcome'], 'in_authority')
        self.assertEqual(self.requests(), [])


class LegacyRootTests(_Root):
    """5: a workflow root whose contract has no `authority` field (authority.effective declared=False)."""
    AUTHORITY = False

    def test_5_outcome_is_recorded_exactly_as_before_without_a_decision_record(self):
        with self.ledger.transaction(write=True) as conn:
            root = plan.anchor_events(self.ledger, conn, 'P1')
            plan.emit(self.ledger, conn, root['task_id'], 'plan.closed', {'revision': 1, 'reason': 'owner stopped the fixture'})
        written = outcome.record(self.ledger, 'P1')
        self.assertTrue(written['recorded'])
        self.assertEqual(written['q10']['delegation'], internal_plan.NO_GRANT)
        self.assertEqual([k for k in self.kinds() if k == 'decision.recorded'], [])
        self.assertEqual(self.requests(), [])

    def test_5b_no_class_is_recorded_and_the_engine_never_reaches_a_repair(self):
        for q in ('Q5', 'Q8', 'Q10'):
            verdict = internal_plan.self_decided(self.ledger, 'P1', q, ['C'], 'onecrew.test', key='legacy-' + q)
            self.assertEqual(verdict, {'delegation': internal_plan.NO_GRANT, 'decision': None, 'result': None})
        self.assertEqual([k for k in self.kinds() if k == 'decision.recorded'], [])
        # unchanged old rule: a root without a grant delegates nothing, so its internal plan (and any repair of it) is refused
        with self.assertRaisesRegex(LedgerError, 'Q1 is not delegated'):
            self.revise([node('C'), node('I', ['C'], integration=True, write=())])


if __name__ == '__main__':
    import unittest
    unittest.main()
