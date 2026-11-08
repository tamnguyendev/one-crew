"""2.5-A cycle 2: finding -> repair -> recheck on real temporary ledgers (no fake events, no AI claim closes a finding).

Node findings use the engine fixtures (real verify / repair_tasks.prepare); milestone findings use the reviewer receipt fixture.
`close_from_recheck` is the explicit, request-bound closure; the engine's own automatic closure is switched off in the node tests
(as if its hook was unavailable) so that the door itself is what is exercised.
"""
import copy
import json
import os
import re
from unittest.mock import patch

from onecrew.control_core import Control, migrate
from onecrew.ledger import LedgerError, content_hash
from onecrew.snapshots import Snapshots
from onecrew.v2 import engine, findings, internal_plan, plan, repair_tasks, review_dispatch
from onecrew.v2 import review_request as rr
from tests.test_v2_l1 import Fixture, milestone, plan_json
from tests.test_wf_engine import EngineFixture, node
from tests import test_wf_findings as reviewer_fixture


def raw_inputs(artifact, checks, revision):
    return dict(artifact=artifact, revision=revision, acceptance={'O1': 'works'}, inputs={'src': artifact},
                configuration={'verifier': 'fixture'}, environment={'python': 'fixture'}, checks=list(checks))


EXECUTION = {'method': 'command', 'implementation': 'fixture-v1', 'configuration': {}, 'environment': {'tool': 'fixture'},
             'provenance': {'source': 'test'}}


class NodeRecheck(EngineFixture):
    def setUp(self):
        Fixture.setUp(self)
        self.engine, self.ip = engine, internal_plan
        raw = plan_json(milestones=[milestone()], scope={'owned': ['a.txt', 'b.txt', 'x.txt']},
                        authority={'edit': True, 'commands': True, 'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q8', 'Q9', 'Q12']})
        caps = ['namespaced-storage', 'finding-register', 'root-budget', 'internal-plan', 'sequential-engine']
        plan.propose(self.ledger, 'P1', raw, 'codex', workflow=True, capabilities=caps)
        plan.approve(self.ledger, 'P1', 'owner', 'temporary fixture grant')
        self.store = Snapshots(self.ledger.state_root); migrate(self.ledger); self.control = Control(self.ledger)
        os.environ['ONECREW_ACTOR'] = 'codex'
        n1 = node('N1'); n2 = node('N2', write=('b.txt',)); n2['read'] = ['b.txt']
        x = node('X', write=('x.txt',)); x['read'] = ['x.txt']
        integration = node('I', ['N1', 'N2', 'X'], integration=True, write=()); integration['read'] = ['a.txt', 'b.txt']
        self.revise([n1, n2, x, integration])
        for nid in ('N1', 'N2', 'X'):
            self.assertEqual(self.step()['node'], nid); self.verify(nid)
        self.assertEqual(self.step()['node'], 'I')
        self.verify('I', self.red)
        [self.finding] = findings.list_findings(self.ledger, 'P1', open_only=True)
        self.red_receipt = engine.state(self.ledger, 'P1')['nodes']['I']['verification_receipt']
        self.red_request = self.request('I')

    def execute(self, ledger, control, task, item, attempt):
        # unlike the base fixture, every generation produces a DIFFERENT artifact (a repair changes the output)
        self.runs = getattr(self, 'runs', {}); self.runs[item['id']] = self.runs.get(item['id'], 0) + 1
        control.launched(attempt['id'], attempt['generation'], {'fixture': True})
        artifact = self.store.blob(('artifact-%s-run%s' % (item['id'], self.runs[item['id']])).encode())
        receipt = self.store.blob(('executor-%s-run%s' % (item['id'], self.runs[item['id']])).encode())
        control.finish(attempt['id'], attempt['generation'], {'fixture': True, 'artifact': artifact})
        return {'artifact': artifact, 'receipt': receipt}

    def red(self, item, artifact):
        return {'artifact': artifact, 'checks': [{'id': c['id'], 'result': 'fail', 'evidence': self.store.blob(b'integration: a.txt and b.txt disagree')}
                                                 for c in item['checks']]}

    def repair_and_pass(self):
        """Repair N1, re-produce N1 and I, verify I green with the engine's automatic closure unavailable."""
        repair_tasks.prepare(self.ledger, 'P1', 'N1', 'I', reason='a.txt must agree with b.txt', evidence=[self.red_receipt])
        self.assertEqual(self.step()['node'], 'N1'); self.verify('N1')
        self.assertEqual(self.step()['node'], 'I')
        with patch.object(findings, 'record_node_verification', side_effect=LedgerError('closure hook unavailable')):
            self.assertEqual(self.verify('I')['result'], 'pass')
        self.assertEqual([f['status'] for f in findings.list_findings(self.ledger, 'P1')], ['open'], 'the finding is still open')
        return engine.state(self.ledger, 'P1')['nodes']['I']['verification_receipt']

    def request(self, nid, mutate=None, inputs_mutate=None, contract_revision=None, root_task=None, execution=EXECUTION):
        root, contract, item, facts = review_dispatch._context(self.ledger, 'P1', nid)
        facts = copy.deepcopy(facts)
        if mutate: mutate(facts)
        inputs = raw_inputs(facts['artifact'], [c['id'] for c in item['checks']], root['approved']['revision'])
        if inputs_mutate: inputs_mutate(inputs)
        criteria = copy.deepcopy(item['checks'])
        return rr.build_check(kind='node', root={'project_id': self.ledger.project_id, 'task_id': root_task or root['task_id']},
                              contract_revision=contract_revision or root['approved']['revision'], contract_sha=root['approved']['sha'],
                              subject=facts, required=False, criteria=criteria, scope={k: item.get(k, []) for k in ('read', 'write', 'acceptance')},
                              policy={'depth': 'fixture'}, authority={}, budget={'max_calls': 5}, inputs=inputs, execution=execution,
                              review_id='recheck-' + nid)

    def last_register_event(self):
        with self.ledger.transaction() as conn:
            task = plan.derive(self.ledger, conn, 'P1')['task_id']
        return [e['payload'] for e in self.ledger.events(task) if e['kind'] == findings.KIND][-1]

    def assertRefused(self, result, text):
        self.assertEqual(result['closed'], [])
        self.assertTrue(any(text in r for r in result['refused']), result)
        self.assertEqual(findings.list_findings(self.ledger, 'P1', open_only=True)[0]['id'], self.finding['id'])
        self.assertEqual(self.last_register_event()['refused'], result['refused'])      # the refusal is durable

    def test_closes_with_an_authentic_recheck_bound_to_the_repaired_output_and_links_the_repair(self):
        receipt = self.repair_and_pass()
        request = self.request('I')
        result = findings.close_from_recheck(self.ledger, 'P1', self.finding['id'], run_receipt=receipt, request=request)
        self.assertEqual(result, {'closed': [self.finding['id']], 'refused': []})
        [closed] = findings.list_findings(self.ledger, 'P1')
        self.assertEqual(closed['status'], 'resolved')
        resolution = closed['resolution']
        self.assertEqual((resolution['receipt'], resolution['recheck']['request']), (receipt, request['id']))
        self.assertNotEqual(resolution['artifact_sha'], self.finding['artifact_sha'])      # the repaired output, not the failed one
        self.assertIsNotNone(resolution['repair']); self.assertEqual(resolution['repair']['target'], 'N1')
        self.assertGreater(resolution['produced_seq'], 0)
        self.assertEqual(self.engine.state(self.ledger, 'P1')['finding_blockers'], {})
        again = findings.close_from_recheck(self.ledger, 'P1', self.finding['id'], run_receipt=receipt, request=request)
        self.assertEqual(again['closed'], [])                                                # idempotent: no second closure

    def test_ai_self_report_unrelated_old_and_failing_receipts_never_close(self):
        receipt = self.repair_and_pass()
        good = self.request('I')
        forged = self.store.blob(json.dumps({'kind': 'node-verifier-receipt', 'root': 'x', 'node': 'I', 'result': 'pass'}).encode())
        for label, rec, req, text in (
                ('claim, not a receipt', 'worker says: fixed', good, ''),
                ('forged blob', forged, good, 'node verifier receipt'),
                ('empty', '', good, 'not a claim'),
                ('the failing receipt itself', self.red_receipt, self.red_request, 'Stale recheck'),
                ('failing receipt with the new request', self.red_receipt, good, 'x|y'),
                ('an unrelated node receipt', engine.state(self.ledger, 'P1')['nodes']['N2']['verification_receipt'], good, 'node verifier receipt'),
        ):
            with self.subTest(label):
                result = findings.close_from_recheck(self.ledger, 'P1', self.finding['id'], run_receipt=rec, request=req)
                self.assertEqual(result['closed'], [])
                self.assertTrue(result['refused'])
                if text and '|' not in text: self.assertTrue(any(text in r for r in result['refused']), result)
                self.assertEqual(findings.list_findings(self.ledger, 'P1', open_only=True)[0]['id'], self.finding['id'])

    def test_requests_that_are_not_bound_to_this_finding_and_output_are_refused(self):
        receipt = self.repair_and_pass()
        cases = [
            ('another node', self.request('N1'), 'another node|does not cover'),
            ('another root', self.request('I', root_task='other-root'), 'another root'),
            ('another contract revision', self.request('I', contract_revision=99, inputs_mutate=lambda i: i.update(revision=99)), 'another contract revision'),
            ('another generation', self.request('I', mutate=lambda f: f.update(generation=f['generation'] + 5)), 'another generation'),
            ('another candidate', self.request('I', mutate=lambda f: f.update(artifact='f' * 64), inputs_mutate=lambda i: i.update(artifact='f' * 64)),
             'another candidate'),
            ('malformed', {'version': 2, 'id': 'review-x'}, 'malformed'),
            ('none', None, 'malformed'),
        ]
        for label, req, text in cases:
            with self.subTest(label):
                result = findings.close_from_recheck(self.ledger, 'P1', self.finding['id'], run_receipt=receipt, request=req)
                self.assertEqual(result['closed'], [])
                self.assertTrue(any(re.search(text, r) for r in result['refused']), result)
        self.assertEqual(findings.list_findings(self.ledger, 'P1', open_only=True)[0]['id'], self.finding['id'])

    def test_v1_node_descriptor_cannot_close(self):
        receipt = self.repair_and_pass()
        root, contract, item, facts = review_dispatch._context(self.ledger, 'P1', 'I')
        v1 = rr.build(root={'project_id': self.ledger.project_id, 'task_id': root['task_id']}, contract_revision=root['approved']['revision'],
                      contract_sha=root['approved']['sha'], review_id='recheck-I', required=False, facts=facts,
                      scope={k: item.get(k, []) for k in ('read', 'write', 'acceptance')}, criteria=item['checks'],
                      policy={'depth': 'fixture'}, authority={}, budget={'max_calls': 5}, execution=EXECUTION)
        self.assertRefused(findings.close_from_recheck(self.ledger, 'P1', self.finding['id'], run_receipt=receipt, request=v1), 'legacy descriptor')

    def test_recheck_of_an_unrepaired_candidate_is_refused_even_when_green(self):
        """A passing receipt on the SAME candidate that failed cannot close (e.g. a flaky pass without any repair)."""
        self.assertEqual(self.finding['artifact_sha'], engine.state(self.ledger, 'P1')['nodes']['I']['artifact'])   # nothing was repaired yet
        result = findings.close_from_recheck(self.ledger, 'P1', self.finding['id'], run_receipt=self.red_receipt, request=self.red_request)
        self.assertRefused(result, 'same candidate')


class RerunByImpact(NodeRecheck):
    """repair_tasks.rerun_order consuming evidence_status: impact decides, a missing basis widens, an old PASS never covers a new snapshot."""
    for _inherited in [n for n in dir(NodeRecheck) if n.startswith('test')]:
        locals()[_inherited] = None
    del _inherited

    def evidence(self, nid, before, after=None):
        return {'previous': before, 'current': after or self.request(nid)}

    def test_without_evidence_the_order_is_the_recorded_scope_exactly_as_before(self):
        order = repair_tasks.rerun_order(self.ledger, 'P1', self.finding['id'])
        self.assertEqual(order['ordered'], ['check-I', 'check-N1', 'check-N2'])
        self.assertEqual((order['widened'], order['reusable'], order['evidence_status']), ([], [], {}))

    def test_a_scope_node_whose_evidence_applies_is_not_rerun_and_a_changed_one_is(self):
        n1_before, n2_before = self.request('N1'), self.request('N2')
        self.repair_and_pass()
        order = repair_tasks.rerun_order(self.ledger, 'P1', self.finding['id'],
                                         evidence={'N1': self.evidence('N1', n1_before), 'N2': self.evidence('N2', n2_before)})
        self.assertEqual(order['evidence_status'], {'N1': 'recheck', 'N2': 'applies'})          # N1 was repaired: new candidate
        self.assertEqual(order['ordered'], ['check-I', 'check-N1']); self.assertEqual(order['widened'], [])
        [reused] = order['reusable']
        self.assertEqual((reused['node'], reused['checks']), ('N2', ['check-N2']))
        self.assertTrue(reused['request'].startswith('review-') and reused['previous_request'].startswith('review-'))   # provenance of the reuse
        self.assertNotEqual(reused['request'], reused['previous_request'])    # the workflow moved on (target echo), the evidence did not
        self.assertTrue(order['smaller_than_suite'])
        self.assertIn('check-I', order['ordered'])                                                # the failed check is never reused

    def test_insufficient_evidence_widens_to_the_whole_suite_and_an_old_pass_is_not_reused(self):
        n2_before = self.request('N2')
        incomplete = lambda nid: self.request_with(nid, execution=None)
        order = repair_tasks.rerun_order(self.ledger, 'P1', self.finding['id'],
                                         evidence={'N2': {'previous': incomplete('N2'), 'current': incomplete('N2')}})
        self.assertEqual(order['evidence_status'], {'N2': 'insufficient'})
        self.assertEqual(order['ordered'][0], 'check-I'); self.assertEqual(set(order['ordered']), set(order['whole_suite']))
        self.assertFalse(order['smaller_than_suite']); self.assertEqual(order['reusable'], [])
        self.assertEqual(order['widened'][0]['node'], 'N2'); self.assertIn('incomplete', order['widened'][0]['reason'])
        self.assertIsNotNone(n2_before)

    def test_a_finding_without_a_recorded_scope_widens_instead_of_narrowing(self):
        register = findings._read
        def unscoped(*args, **kwargs):
            value = copy.deepcopy(register(*args, **kwargs))
            for f in value['findings']: f.pop('scope_nodes', None)
            return value
        with patch.object(findings, '_read', side_effect=unscoped):
            order = repair_tasks.rerun_order(self.ledger, 'P1', self.finding['id'])
        self.assertEqual(order['ordered'][0], 'check-I'); self.assertEqual(set(order['ordered']), set(order['whole_suite']))
        self.assertFalse(order['smaller_than_suite']); self.assertIn('impact cannot be established', order['widened'][0]['reason'])

    def test_a_supplied_status_is_not_trusted(self):
        with self.assertRaises(LedgerError):
            repair_tasks.rerun_order(self.ledger, 'P1', self.finding['id'], evidence={'N2': {'status': 'applies'}})

    def request_with(self, nid, execution):
        return self.request(nid, execution=execution)


class MilestoneRecheck(reviewer_fixture.FindingTests):
    """Reviewer-receipt (milestone) findings: same door, authenticated by verdict.receipt_issued / verdict.recorded."""
    for _inherited in [n for n in dir(reviewer_fixture.FindingTests) if n.startswith('test')]:
        locals()[_inherited] = None          # reuse only the fixture, not the 30+ inherited register tests
    del _inherited

    def setUp(self):
        super().setUp()
        self.red = self.receipt('fail')
        self.assertEqual(self.open(self.red)['opened'], ['RF1'])
        self.fixed = 'b' * 40

    def request(self, artifact=None, **changes):
        sha = plan_sha(self)
        artifact = artifact or self.fixed
        args = dict(kind='milestone', root={'project_id': self.ledger.project_id, 'task_id': self.task}, contract_revision=1, contract_sha=sha,
                    subject={'plan': 'P1', 'milestone': 'M1', 'candidate': artifact, 'plan_sha': sha}, required=True,
                    criteria=copy.deepcopy(reviewer_fixture.CRITERIA), scope={'read': ['a.txt'], 'write': ['a.txt'], 'acceptance': ['O1']},
                    policy={'depth': 'fixture'}, authority={}, budget={'max_calls': 5},
                    inputs=raw_inputs(artifact, ['R1', 'R2'], 1), execution=EXECUTION)
        args.update(changes)
        return rr.build_check(**args)

    def test_closes_on_a_passing_reviewer_receipt_of_the_repaired_candidate(self):
        passing = self.receipt('pass', artifact=self.fixed)
        result = findings.close_from_recheck(self.ledger, 'P1', 'RF1', run_receipt=passing, request=self.request())
        self.assertEqual(result, {'closed': ['RF1'], 'refused': []})
        self.assertEqual(self.rows()[0]['status'], 'resolved')
        self.assertEqual(self.rows()[0]['resolution']['recheck']['candidate'], self.fixed)

    def test_refusals_leave_the_finding_open(self):
        old_pass = self.receipt('pass')                       # green but on the candidate that failed
        unissued = self.receipt('pass', artifact=self.fixed, issued=False, calls=7)         # content-addressed: vary the body
        unrecorded = self.receipt('pass', artifact=self.fixed, issued=False, recorded=False, calls=8)
        failing = self.receipt('fail', artifact=self.fixed, calls=9)
        sha = plan_sha(self)
        for label, receipt, request in (
                ('old candidate', old_pass, self.request(self.artifact)),
                ('request for another candidate', self.receipt('pass', artifact='c' * 40), self.request()),
                ('not issued by the core', unissued, self.request()),
                ('never recorded', unrecorded, self.request()),
                ('still failing', failing, self.request()),
                ('another milestone', self.receipt('pass', artifact=self.fixed, revision=1), self.request(subject={
                    'plan': 'P1', 'milestone': 'M9', 'candidate': self.fixed, 'plan_sha': sha})),
                ('criterion not covered', self.receipt('pass', artifact=self.fixed), self.request(criteria=[{'id': 'R2', 'question': 'x'}],
                    inputs=raw_inputs(self.fixed, ['R2'], 1))),
                ('stale contract', self.receipt('pass', artifact=self.fixed), self.request(contract_revision=2, inputs=raw_inputs(self.fixed, ['R1', 'R2'], 2))),
        ):
            with self.subTest(label):
                result = findings.close_from_recheck(self.ledger, 'P1', 'RF1', run_receipt=receipt, request=request)
                self.assertEqual(result['closed'], [], result); self.assertTrue(result['refused'])
        self.assertEqual(self.rows(open_only=True)[0]['id'], 'RF1')

    def test_the_same_defect_after_a_resolved_closure_is_a_recurrence_not_a_new_bug(self):
        self.assertEqual(findings.close_from_recheck(self.ledger, 'P1', 'RF1', run_receipt=self.receipt('pass', artifact=self.fixed),
                                                     request=self.request())['closed'], ['RF1'])
        again = self.receipt('fail', artifact='d' * 40, generation=2)
        self.assertEqual(self.open(again, generation=2)['opened'], ['RF2'])
        rows = {r['id']: r for r in self.rows()}
        self.assertEqual(rows['RF2']['recurrence_of'], 'RF1'); self.assertEqual(rows['RF1']['recurred_as'], ['RF2'])
        self.assertEqual((rows['RF1']['status'], rows['RF2']['status']), ('resolved', 'open'))

    def test_recurrence_link_also_after_the_existing_resolve_door(self):
        findings.resolve(self.ledger, 'P1', 'RF1', self.receipt('pass', artifact=self.fixed), reason='fixed', artifact_sha=self.fixed)
        self.assertEqual(self.open(self.receipt('fail', artifact='d' * 40, generation=2), generation=2)['opened'], ['RF2'])
        rows = {r['id']: r for r in self.rows()}
        self.assertEqual(rows['RF2']['recurrence_of'], 'RF1'); self.assertEqual(rows['RF1']['recurred_as'], ['RF2'])

    def test_a_rejected_finding_is_not_linked_when_the_same_text_returns(self):
        findings.resolve(self.ledger, 'P1', 'RF1', self.receipt('pass', artifact=self.fixed), reason='not a defect', artifact_sha=self.fixed, reject=True)
        self.assertEqual(self.rows()[0]['status'], 'rejected')
        self.assertEqual(self.open(self.receipt('fail', artifact='d' * 40, generation=2), generation=2)['opened'], ['RF2'])
        self.assertNotIn('recurrence_of', {r['id']: r for r in self.rows()}['RF2'])


def plan_sha(case):
    from onecrew.v2 import contract as contracts
    return contracts.read_revision(case.ledger, 'P1', 1)[1]
