"""OBS2-T1..T7 data acceptance: real temporary ledgers, fixture executors only."""
import copy
import hashlib
import json
from unittest.mock import patch

from onecrew import conversations
from onecrew.ledger import Ledger, content_hash
from onecrew.v2 import plan as plans, tracking, repair_tasks
from tests.test_v2_l1 import Fixture, plan_json
from tests.test_wf_engine import EngineFixture, node
from tests.test_conversations import solution as sol_payload


class SolutionTests(Fixture):
    def test_approved_revision_change_marks_old_milestone_artifact_historical(self):
        from onecrew.v2 import verdict
        self.approved()
        receipt, body = self.receipt()
        self.issue(receipt)
        verdict.record(self.ledger, 'P1', 'M1', 'pass', 'command', receipt, self.tree())
        before = tracking.detail(self.ledger.state_root, 'P1')['work']
        self.assertEqual(before['outputs'][0]['level'], 'verified')
        self.assertFalse(before['outputs'][0]['stale'])
        plans.amend(self.ledger, 'P1', plan_json(title='New approved contract'), 'New contract', 'codex')
        plans.approve(self.ledger, 'P1', 'owner', 'approve second revision')
        work = tracking.detail(self.ledger.state_root, 'P1')['work']
        self.assertTrue(work['checks']['runs'][0]['stale'])
        self.assertTrue(work['outputs'][0]['stale'])

    def test_exact_sol_source_does_not_grant_root_authority_and_foreign_source_is_hidden(self):
        cid = conversations.create(self.ledger, 'Source', 'create', 'user')['id']
        sol = conversations.propose(self.ledger, cid, 'source', sol_payload(), 'codex')
        ref = {k: sol[k] for k in ('id', 'revision')}
        plans.propose(self.ledger, 'P1', plan_json(solution_ref=ref, authority={'edit': True, 'commands': True}), 'codex', workflow=True)
        work = tracking.detail(self.ledger.state_root, 'P1')['work']
        self.assertIsNone(work['solution']['approved_revision'])
        self.assertIsNone(work['solution']['effective_revision'])
        self.assertEqual(work['solution']['source_solution']['revision'], sol['revision'])
        with self.ledger.transaction(write=True) as conn:
            conn.execute("UPDATE conversations SET project_id='other-project' WHERE id=?", (cid,))
        work = tracking.detail(self.ledger.state_root, 'P1')['work']
        self.assertEqual(work['solution']['source_solution']['status'], 'unavailable')
        self.assertIsNone(work['solution']['source_solution']['payload'])

    def test_pending_revision_keeps_approved_solution_and_exposes_diff(self):
        self.approved()
        value = plan_json(title='Pending title', output=['New output password=private-secret'])
        plans.amend(self.ledger, 'P1', value, 'Reason token=private-reason', 'codex')
        work = tracking.detail(self.ledger.state_root, 'P1')['work']
        solution = work['solution']
        self.assertEqual((solution['latest_revision'], solution['approved_revision'], solution['effective_revision']), (2, 1, 1))
        self.assertEqual(solution['contract']['outputs'], ['The sample exists'])
        self.assertEqual(solution['frozen']['runnable'], ['M1'])
        self.assertIsNone(solution['source_solution'])
        self.assertTrue(work['changes'][0]['diff'])
        self.assertNotIn('private-secret', json.dumps(work))
        self.assertNotIn('private-reason', json.dumps(work))
        self.assertNotIn('work', tracking.overview(self.ledger.state_root)['projects'][0]['tasks'][0])

    def test_projection_is_read_only_even_if_ledger_construction_is_forbidden(self):
        self.approved()
        before = {str(p.relative_to(self.ledger.state_root)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in self.ledger.state_root.rglob('*') if p.is_file()}
        with patch.object(Ledger, '__init__', side_effect=AssertionError('must not initialize ledger')):
            one = tracking.detail(self.ledger.state_root, 'P1')['work']
            two = tracking.detail(self.ledger.state_root, 'P1')['work']
        self.assertEqual(one, two)
        self.assertEqual(before, {str(p.relative_to(self.ledger.state_root)): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in self.ledger.state_root.rglob('*') if p.is_file()})


class WorkTests(EngineFixture):
    def setUp(self):
        super().setUp()
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])

    def work(self, **kw):
        return tracking.detail(self.ledger.state_root, 'P1', **kw)['work']

    def emit(self, kind, **payload):
        with self.ledger.transaction(write=True) as conn:
            view = self.engine.state(self.ledger, 'P1', conn)
            self.engine._event(self.ledger, conn, view, payload.pop('node', 'A'), kind, **payload)

    def republish(self, nid='A'):
        record = self.engine.state(self.ledger, 'P1')['nodes'][nid]
        self.emit('node.produced', node=nid, artifact=record['artifact'], receipt=record['receipt'])

    def test_output_proof_is_per_artifact_and_checks_are_not_testcases(self):
        self.step(); self.verify('A')
        work = self.work()
        self.assertEqual(work['outputs'][0]['level'], 'verified')
        self.assertEqual(work['checks']['summary']['checks']['pass'], 1)
        self.assertIsNone(work['checks']['summary']['testcases'])
        self.assertTrue(work['outputs'][0]['verification'])
        self.assertIsNone(work['checks']['runs'][0]['attempt'], 'verification creates no Control attempt')
        self.assertEqual(work['checks']['runs'][0]['producer_attempt'], work['outputs'][0]['attempt'])
        self.emit('node.resumed', reason='Technical retry, not a repair round')
        self.step()
        work = self.work()
        self.assertTrue(work['outputs'][0]['stale'])
        self.assertEqual(work['outputs'][-1]['level'], 'produced')
        self.assertEqual(work['repairs'], [])
        self.assertEqual(work['changes'][-1]['kind'], 'retry')

    def test_history_beyond_display_window_and_missing_output(self):
        self.step()
        for number in range(205): self.emit('node.held', reason='fixture hold ' + str(number))
        work = self.work(timeline_limit=1)
        self.assertEqual(len(work['outputs']), 1)
        artifact = work['outputs'][0]['artifact']
        (self.store.root / 'blobs' / artifact).unlink()
        missing = self.work()['outputs'][0]
        self.assertFalse(missing['stored']); self.assertFalse(missing['openable'])

    def test_independent_reuse_and_partial_inheritance_keep_origin_and_proof(self):
        self.step(); self.verify('A')
        view = self.engine.state(self.ledger, 'P1')
        nodes = copy.deepcopy(view['definition']['nodes']); nodes[1]['goal'] += ' updated integration detail'
        self.revise(nodes)
        output = self.work()['outputs'][0]
        self.assertTrue(output['inherited']); self.assertFalse(output['stale'])
        self.assertEqual((output['level'], output['internal_revision']), ('verified', 1))
        self.emit('node.resumed', reason='Continue partial output', resume_artifact=output['artifact'], continues_attempt=output['attempt'])
        inherited = self.work()['outputs'][-1]
        self.assertTrue(inherited['inherited']); self.assertFalse(inherited['stale'])
        self.assertEqual((inherited['generation'], inherited['from_generation'], inherited['level']), (1, 0, 'produced'))

    def test_wrong_artifact_and_generation_receipt_never_promote_output(self):
        self.step()
        view = self.engine.state(self.ledger, 'P1')
        for field, wrong in [('artifact', 'f' * 64), ('generation', 77), ('root', 'other-root')]:
            body = {'kind': 'node-verifier-receipt', 'root': view['root'], 'node': 'A', 'generation': 0,
                    'internal_revision': 1, 'artifact': view['nodes']['A']['artifact'], 'result': 'pass',
                    'observed': self.checker(view['definition']['nodes'][0], view['nodes']['A']['artifact']),
                    'checks_sha': content_hash(view['definition']['nodes'][0]['checks']),
                    'evidence_errors': []}
            body[field] = wrong
            receipt = self.store.blob(json.dumps(body).encode())
            self.emit('node.verification', result='pass', receipt=receipt)
        work = self.work()
        self.assertEqual(work['outputs'][0]['level'], 'produced')
        self.assertTrue(all(not r['authentic'] for r in work['checks']['runs']))

    def test_latest_fail_overrides_old_pass_on_same_candidate(self):
        self.step(); self.verify('A')
        self.republish()
        self.verify('A', lambda item, artifact: {'artifact': artifact, 'checks': [
            {'id': 'check-A', 'result': 'fail', 'evidence': self.store.blob(b'new failure')}]})
        work = self.work()
        self.assertEqual(work['outputs'][0]['level'], 'produced')
        self.assertEqual([r['status'] for r in work['checks']['runs']], ['pass', 'fail'])

    def test_structured_case_executions_and_unique_identities_are_distinct(self):
        self.step()
        def check(item, artifact):
            return {'artifact': artifact, 'checks': [{'id': 'check-A', 'result': 'pass',
                'evidence': self.store.blob(b'case evidence'), 'testcases': [
                    {'id': 'same-case', 'suite': 'suite', 'result': 'pass'},
                    {'id': 'skipped-case', 'suite': 'suite', 'result': 'skip'}]}]}
        self.verify('A', check)
        # A new sealed receipt with the same case identities is another run.
        def again(item, artifact):
            value = check(item, artifact); value['checks'][0]['evidence'] = self.store.blob(b'case evidence rerun')
            return value
        self.republish()
        self.verify('A', again)
        summary = self.work()['checks']['summary']
        self.assertEqual(summary['runs'], 2)
        self.assertEqual(summary['testcases']['unique'], 2)
        self.assertEqual(summary['testcases']['executions'], 4)
        self.assertEqual(summary['testcases']['skip'], 2)

    def test_malformed_optional_case_identity_cannot_break_detail(self):
        self.step()
        def check(item, artifact):
            return {'artifact': artifact, 'checks': [{'id': 'check-A', 'result': 'pass',
                'evidence': self.store.blob(b'valid check, malformed metadata'), 'testcases': [
                    {'id': ['invalid'], 'status': 'pass'}, {'id': 'valid', 'suite': {}, 'result': 'pass'}]}]}
        self.verify('A', check)
        work = self.work()
        self.assertEqual(work['checks']['summary']['checks']['pass'], 1)
        self.assertIsNone(work['checks']['summary']['testcases'])
        self.assertTrue(any('metadata' in limitation for limitation in work['limitations']))

    def test_receipt_identity_can_differ_from_assigned_pin_and_nested_reviewer_is_sourced(self):
        def execute(ledger, control, task, item, attempt):
            value = self.execute(ledger, control, task, item, attempt)
            body = dict(kind='native-node-receipt', node=item['id'], attempt=attempt['id'], artifact=value['artifact'],
                        provider='claude', model='actual-worker', role='worker')
            value['receipt'] = self.store.blob(json.dumps(body).encode()); return value
        self.step(execute)
        def check(item, artifact):
            reviewer = self.store.blob(json.dumps({'kind': 'reviewer-receipt', 'provider': 'codex', 'model': 'actual-reviewer',
                'calls': 1, 'role': 'reviewer', 'milestone': 'check-A', 'revision': 1, 'artifact_sha': 'tree'}).encode())
            proof = self.store.blob(json.dumps({'kind': 'candidate-reviewer-check', 'node': 'A', 'snapshot': artifact,
                'milestone': 'check-A', 'tree': 'tree', 'reviewer_receipt': reviewer}).encode())
            return {'artifact': artifact, 'checks': [{'id': 'check-A', 'result': 'pass', 'evidence': proof}]}
        self.verify('A', check)
        actors = self.work()['actors']
        self.assertEqual(next(a for a in actors if a['role'] == 'executed')['provider'], 'claude')
        reviewer = next(a for a in actors if a['role'] == 'reviewer' and a['provider'])
        self.assertEqual((reviewer['provider'], reviewer['model']), ('codex', 'actual-reviewer'))

    def test_missing_receipt_is_explicit_and_never_a_green_proof(self):
        self.step(); self.verify('A')
        receipt = self.engine.state(self.ledger, 'P1')['nodes']['A']['verification_receipt']
        (self.store.root / 'blobs' / receipt).unlink()
        work = self.work()
        self.assertEqual(work['outputs'][0]['level'], 'produced')
        self.assertFalse(work['checks']['runs'][0]['authentic'])
        self.assertTrue(any(receipt in limitation for limitation in work['limitations']))

    def test_assignment_is_not_execution_and_unknown_reviewer_stays_unknown(self):
        definitions = copy.deepcopy(self.engine.state(self.ledger, 'P1')['definition']['nodes'])
        definitions[0]['executor'] = {'role': 'worker', 'provider': 'codex', 'model': 'gpt-6.1-sol'}
        self.revise(definitions)
        self.step(); self.verify('A')
        actors = self.work()['actors']
        assigned = next(a for a in actors if a['role'] == 'assigned' and a['node'] == 'A')
        executed = next(a for a in actors if a['role'] == 'executed')
        self.assertEqual(assigned['provider'], 'codex')
        self.assertIsNone(executed['provider'])
        self.assertIsNone(next(a for a in actors if a['role'] == 'reviewer')['provider'])

    def test_duplicate_verification_event_is_one_run_with_multiple_sources(self):
        self.step(); self.verify('A')
        receipt = self.engine.state(self.ledger, 'P1')['nodes']['A']['verification_receipt']
        self.emit('node.verification', result='pass', receipt=receipt)
        work = self.work()
        self.assertEqual(work['checks']['summary']['runs'], 1)
        self.assertEqual(len(work['checks']['runs'][0]['sources']), 2)

    def test_repair_requires_later_affected_and_integration_verification(self):
        self.step()
        self.verify('A', lambda item, artifact: {'artifact': artifact, 'checks': [
            {'id': 'check-A', 'result': 'fail', 'evidence': self.store.blob(b'actual fail')}]})
        before = self.work()
        self.assertEqual(before['repairs'], [])
        repair_tasks.prepare(self.ledger, 'P1', 'A', 'A', reason='Fix actual failed check',
                             evidence=[before['checks']['runs'][0]['receipt']])
        repair = self.work()['repairs'][0]
        self.assertEqual(repair['failed_checks'], ['check-A'])
        self.assertEqual(repair['status'], 'unverified')
        self.step(); self.verify('A')
        self.assertEqual(self.work()['repairs'][0]['status'], 'partial')
        self.step(); self.verify('I')
        self.assertEqual(self.work()['repairs'][0]['status'], 'verified')
        definitions = copy.deepcopy(self.engine.state(self.ledger, 'P1')['definition']['nodes'])
        definitions[0]['goal'] += ' with revised implementation detail'
        self.revise(definitions)
        repaired_history = self.work()['repairs']
        self.assertEqual(len(repaired_history), 1, 'order-only rebinding is not another repair round')
        self.assertEqual(repaired_history[0]['status'], 'verified', 'historical proof survives a later generation')
        self.assertFalse(repaired_history[0]['applicable'])
        self.assertTrue(repaired_history[0]['rebindings'][0]['rebinds_order_only'])


class FindingTests(EngineFixture):
    def setUp(self):
        import os
        from onecrew.control import Control, migrate
        from onecrew.snapshots import Snapshots
        from onecrew.v2 import engine, internal_plan
        Fixture.setUp(self)
        self.engine, self.ip = engine, internal_plan
        raw = plan_json(authority={'edit': True, 'commands': True, 'edit_tests': True,
                                  'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q8', 'Q9', 'Q12']})
        caps = ['namespaced-storage', 'finding-register', 'root-budget', 'internal-plan', 'sequential-engine']
        self.root_view = plans.propose(self.ledger, 'P1', raw, 'codex', workflow=True, capabilities=caps)
        plans.approve(self.ledger, 'P1', 'owner', 'fixture grant')
        self.store = Snapshots(self.ledger.state_root); migrate(self.ledger); self.control = Control(self.ledger)
        os.environ['ONECREW_ACTOR'] = 'codex'
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])

    def work(self):
        return tracking.detail(self.ledger.state_root, 'P1')['work']

    def red(self, item, artifact):
        return {'artifact': artifact, 'checks': [{'id': 'check-I', 'result': 'fail',
            'evidence': self.store.blob(b'same criterion failure'), 'testcases': [
                {'id': 'first', 'status': 'fail'}, {'id': 'second', 'status': 'fail'}]}]}

    def test_multiple_observations_retain_one_stable_finding(self):
        from onecrew.v2 import findings
        self.step(); self.verify('A'); self.step(); self.verify('I', self.red)
        view = self.engine.state(self.ledger, 'P1')
        body = json.loads(self.store.read_blob(view['nodes']['I']['verification_receipt']))
        body['observed']['fixture_repeat'] = True
        receipt = self.store.blob(json.dumps(body).encode())
        with self.ledger.transaction(write=True) as conn:
            self.engine._event(self.ledger, conn, view, 'I', 'node.verification', result='fail', receipt=receipt)
            findings.record_node_verification(self.ledger, 'P1', 'I', receipt, definition=view['definition']['nodes'], conn=conn)
        work = self.work()
        self.assertEqual(len(work['findings']), 1)
        self.assertEqual(work['findings'][0]['id'], 'RF1')
        self.assertEqual(work['findings'][0]['last_observed']['receipt'], receipt)

    def test_findings_are_stable_across_multiple_cases_and_fail_pass_recurrence(self):
        self.step(); self.verify('A'); self.step(); self.verify('I', self.red)
        work = self.work()
        self.assertEqual(len(work['findings']), 1)
        self.assertEqual(work['findings'][0]['id'], 'RF1')
        self.assertEqual(work['findings'][0]['state'], 'open')
        self.assertIsNone(work['findings'][0]['category'], 'do not call an untyped finding a bug')
        view = self.engine.state(self.ledger, 'P1')
        receipt = view['nodes']['I']['verification_receipt']
        repair_tasks.prepare(self.ledger, 'P1', 'A', 'I', reason='Repair the scoped integration failure', evidence=[receipt])
        self.step(); self.verify('A'); self.step(); self.verify('I')
        self.assertEqual(self.work()['findings'][0]['state'], 'resolved')
        with self.ledger.transaction(write=True) as conn:
            view = self.engine.state(self.ledger, 'P1', conn)
            self.engine._event(self.ledger, conn, view, 'I', 'node.resumed', reason='New fixture verification generation')
        self.step()
        self.verify('I', self.red)
        final = self.work()['findings']
        self.assertEqual([(f['id'], f['state']) for f in final], [('RF1', 'resolved'), ('RF2', 'open')])
        self.assertIsNone(final[1]['recurrence_of'], 'recur needs explicit data, not matching prose')
