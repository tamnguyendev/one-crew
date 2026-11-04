"""Native command fail→repair→pass feeds the same learning/context adapters."""
import json
import copy

from onecrew.ledger import LedgerError, canonical
from onecrew.v2 import context, decisions, findings, incidents, lessons, plan as plans, repair_tasks
from tests.test_wf_candidate_handoff import CandidateFixture
from tests.test_wf_engine import node as node_definition


class NodeLearningTests(CandidateFixture):
    def setUp(self):
        super().setUp()
        self.output = b'broken\n'
        self.revise(self.definition())

    def execute(self, ledger, control, task, item, attempt):
        control.launched(attempt['id'], attempt['generation'], {'fixture': True})
        base = self.store.capture(self.root, ['a.txt'])
        artifact = self.store.overlay(base, {'a.txt': self.output}, ['a.txt'])
        receipt = self.store.blob(canonical({'kind': 'fixture-producer', 'artifact': artifact}).encode())
        control.finish(attempt['id'], attempt['generation'], {'artifact': artifact})
        return {'artifact': artifact, 'receipt': receipt}

    def test_real_failed_command_repair_and_pass_creates_lesson_before_root_ends(self):
        self.step()
        red = self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)
        self.assertEqual(red['result'], 'fail')
        self.assertEqual(incidents.list_incidents(self.ledger, 'P1'), [])
        source = self.engine.state(self.ledger, 'P1')['nodes']['C']['verification_receipt']
        repair_tasks.prepare(self.ledger, 'P1', 'C', 'C', reason='Repair the actual command assertion.', evidence=[source])
        self.output = b'candidate\n'; self.step()
        green = self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)
        self.assertEqual(green['result'], 'pass')
        saved = incidents.list_incidents(self.ledger, 'P1')
        self.assertEqual(len(saved), 1)
        incident = saved[0]
        self.assertIsNone(incident['finding']); self.assertTrue(incident['episode'].startswith('NEP-'))
        self.assertEqual([o['classification'] for o in incident['attempts']], ['product', 'verified'])
        self.assertEqual(len({o['attempt'] for o in incident['attempts']}), 2)
        self.assertIsNone(incident['cause']); self.assertEqual(findings.list_findings(self.ledger, 'P1'), [])
        entry = lessons.retrieve(self.ledger, name='P1')['entries'][0]
        lesson = lessons._latest(self.ledger, 'P1')[entry['lesson']]
        self.assertEqual(lesson['location']['path'], 'a.txt'); self.assertEqual(lesson['location']['test'], 'check:M1')
        self.assertEqual(lesson['location']['revision'], green['observed']['candidate_tree'])
        self.assertEqual(lesson['location']['revision_kind'], 'tree')
        self.assertFalse(lesson['automatic_promotion']); self.assertFalse(lesson['automatic_injection'])
        self.assertEqual(plans.show(self.ledger, 'P1')['status'], 'approved')
        self.assertFalse(self.engine.verification_ready(self.ledger, 'P1'))
        self.assertTrue(any(e.get('lesson') == lesson['lesson'] for e in context.retrieve(self.ledger, plan='P1')['entries']))
        pinned = next(e for e in context.retrieve(self.ledger, plan='P1', revision=green['observed']['candidate_tree'])['entries'] if e.get('lesson'))
        self.assertEqual(pinned['label'], 'verified', 'the next task can query its actual candidate input, before project apply')
        receipt = self.engine.state(self.ledger, 'P1')['nodes']['C']['verification_receipt']
        incidents.after_node(self.ledger, 'P1', 'C', receipt)
        self.assertEqual(len(incidents.list_incidents(self.ledger, 'P1')), 1)
        self.assertEqual(len(lessons._latest(self.ledger, 'P1')), 1)
        with self.assertRaises(LedgerError): incidents.observe_node(self.ledger, 'P1', 'C', source)

    def test_unsupported_fake_failure_does_not_become_product_incident_or_rule(self):
        self.step()
        def unsupported(item, artifact):
            result = self.checker(item, artifact)
            result['checks'][0]['result'] = 'fail'
            return result
        self.engine.verify(self.ledger, 'P1', 'C', unsupported)
        receipt = self.engine.state(self.ledger, 'P1')['nodes']['C']['verification_receipt']
        observation = incidents.observe_node(self.ledger, 'P1', 'C', receipt)
        self.assertEqual(observation['classification'], 'unknown')
        repair_tasks.prepare(self.ledger, 'P1', 'C', 'C', reason='Reissue the unsupported fixture result without inferring its cause.', evidence=[receipt])
        self.output = b'candidate\n'
        # Existing candidate is still broken. A later unsupported green cannot
        # turn a fixture's arbitrary bytes into a verified repair lesson.
        self.step(); self.verify('C')
        self.assertEqual(incidents.list_incidents(self.ledger, 'P1'), [])
        self.assertEqual(lessons._latest(self.ledger, 'P1'), {})

    def test_prepared_acceptance_red_is_not_a_product_failure_episode(self):
        with self.ledger.transaction() as conn:
            state = plans.anchor_events(self.ledger, conn, 'P1')
        decisions.record(self.ledger, state['task_id'], subject={'component': 'test-preparation', 'model': 'fixture'},
            authority={'grant_id': 'fixture', 'revision': state['approved']['sha']}, evidence=['approved acceptance'],
            basis='Intentional acceptance red before implementation.', scope='acceptance-test-preparation',
            validity={'node': 'C', 'internal_revision': self.ip.current(self.ledger, 'P1')['internal_revision']})
        self.step(); self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)
        observations = incidents.observations(self.ledger, 'P1')
        self.assertEqual(observations[-1]['classification'], 'intentional_red')
        self.assertEqual(incidents.list_incidents(self.ledger, 'P1'), [])

    def test_authentic_unchanged_node_receipt_survives_unrelated_internal_revision(self):
        definition = self.definition()
        independent = node_definition('B', write=()); independent['read'] = []
        independent['checks'] = copy.deepcopy(definition[0]['checks'])
        definition.insert(1, independent)
        definition[-1]['depends'].append({'node': 'B', 'requires': 'verified'})
        self.revise(definition)
        self.step(); self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)
        receipt = self.engine.state(self.ledger, 'P1')['nodes']['C']['verification_receipt']
        repair_tasks.prepare(self.ledger, 'P1', 'C', 'C', reason='Repair actual command failure.', evidence=[receipt])
        self.output = b'candidate\n'; self.step()
        original_revision = self.ip.current(self.ledger, 'P1')['internal_revision']
        def during(item, artifact):
            nodes = copy.deepcopy(self.ip.current(self.ledger, 'P1')['definition']['nodes'])
            next(n for n in nodes if n['id'] == 'B')['goal'] += ' with unrelated additional explanation'
            self.ip.revise(self.ledger, 'P1', nodes, reason='Only independent B changes.', evidence=['a.txt:1'])
            return self.production_checker(item, artifact)
        green = self.engine.verify(self.ledger, 'P1', 'C', during)
        self.assertEqual(green['result'], 'pass')
        self.assertEqual(green['internal_revision'], original_revision)
        self.assertGreater(self.ip.current(self.ledger, 'P1')['internal_revision'], original_revision)
        self.assertEqual(len(incidents.list_incidents(self.ledger, 'P1')), 1)
        self.assertEqual(len(lessons._latest(self.ledger, 'P1')), 1)
