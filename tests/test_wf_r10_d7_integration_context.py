"""Round 10 D7 (2.2/L0): an integration/consumer node must not inline every producer's full source.

Reproduced defect (SDK trial 26/10, both roots): `NativeExecutor.prepare` put `store.context(artifact)` of every `input_artifacts` edge in
the prompt = the WHOLE upstream manifest, its read files included, so the mandatory integration node of a plan over a few hundred KB of
source always exceeded the 80000-character cap ("Native node context exceeds 80000 characters; do not run with partial evidence."), and a
2-node chain doubled the source.

Required: provenance (artifact id, receipt, generation, state) stays in the prompt for every producer; only the producer's declared WRITE
outputs are sent as content (once: an output already in the node's own source is referenced, not repeated); its read files never. The final
prompt size is measured where the cap is checked and recorded (`prompt_chars`) in the attempt receipt; the cap is not raised, nothing is
truncated, no producer is dropped. When the outputs alone exceed the cap the step stops BEFORE the model call with the existing held outcome
and the attempt result names the size per producer.
"""
import json
import os
from unittest.mock import patch

from onecrew.common_executor import NativeExecutor
from onecrew.control_core import Control, migrate
from onecrew.snapshots import Snapshots
from onecrew.v2 import engine, internal_plan, plan
from tests.test_v2_l1 import Fixture, plan_json
from tests.test_wf_engine import EngineFixture, node
from tests import test_wf_native_executor as _native

PIN = {'role': 'worker', 'provider': 'codex', 'model': 'gpt-6.1-sol'}
PRODUCERS = ('K1', 'K2', 'K3')


class IntegrationContextTests(EngineFixture):
    factory = _native.NativeExecutorTests.factory

    def setUp(self):
        Fixture.setUp(self)
        self.engine, self.ip = engine, internal_plan
        outputs = ['o%d.txt' % i for i in (1, 2, 3)]
        value = plan_json(scope={'owned': outputs}, authority={
            'edit': True, 'commands': True, 'edit_tests': True, 'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q9', 'Q12']})
        self.root_view = plan.propose(self.ledger, 'P1', value, 'codex', workflow=True,
                                      capabilities=['namespaced-storage', 'root-budget', 'internal-plan', 'sequential-engine'])
        plan.approve(self.ledger, 'P1', 'owner', 'fixture engine approval')
        os.environ['ONECREW_ACTOR'] = 'codex'
        self.store = Snapshots(self.ledger.state_root); migrate(self.ledger); self.control = Control(self.ledger)
        self.calls, self.preflight_error, self.result_error, self.value = [], None, None, None
        self.adapter = NativeExecutor(self.ledger)
        factory = patch('onecrew.artifact_provider_core.make_worker', side_effect=self.factory)
        factory.start(); self.addCleanup(factory.stop)

    def definition(self, source_chars):
        nodes = []
        for index, nid in enumerate(PRODUCERS, start=1):
            (self.root / ('src%d.txt' % index)).write_text(('SOURCE-%s-' % nid) + 'x' * source_chars + '\n')
            item = node(nid, write=('o%d.txt' % index,)); item['read'] = ['src%d.txt' % index]; item['executor'] = dict(PIN)
            nodes.append(item)
        integration = node('KZ', PRODUCERS, integration=True, write=())
        integration['read'] = ['o%d.txt' % i for i in (1, 2, 3)]; integration['executor'] = dict(PIN)
        return nodes + [integration]

    def produce_all(self, output_chars):
        produced = {}
        for index, nid in enumerate(PRODUCERS, start=1):
            self.value = {'summary': 'part ' + nid, 'files': [{'path': 'o%d.txt' % index, 'content': ('OUT-%s-' % nid) + 'y' * output_chars}],
                          'backlog': []}
            result = self.engine.step(self.ledger, 'P1', self.adapter)
            self.assertEqual((result['node'], result['state']), (nid, 'produced'))
            self.verify(nid)
            produced[nid] = result
        return produced

    def test_a_integration_receives_only_producer_outputs_and_runs_under_the_cap(self):
        self.revise(self.definition(30000))
        produced = self.produce_all(2000)
        self.value = {'summary': 'integrated', 'evidence': [produced[nid]['receipt'] for nid in PRODUCERS]}
        result = self.engine.step(self.ledger, 'P1', self.adapter)
        self.assertEqual((result['node'], result['state']), ('KZ', 'produced'), result)
        prompt = self.calls[-1]['prompt']
        self.assertLess(len(prompt), 20000)                                    # ~6 KB inherited outputs + node JSON, not 3 x 32 KB
        self.assertNotIn('SOURCE-K', prompt)                                   # producer read files never travel
        for nid in PRODUCERS:
            self.assertIn('OUT-%s-' % nid, prompt)                             # every output is present ...
            self.assertEqual(prompt.count('OUT-%s-' % nid), 1)                 # ... exactly once
            self.assertIn(produced[nid]['artifact'], prompt)                   # (c) provenance of every producer stays
            self.assertIn(produced[nid]['receipt'], prompt)
        receipt = json.loads(self.store.read_blob(result['receipt']))
        self.assertEqual(receipt['prompt_chars'], len(prompt))
        self.assertEqual(set(receipt['inputs']), set(PRODUCERS))

    def test_b_outputs_alone_over_the_cap_hold_before_any_launch_and_name_each_producer_size(self):
        self.revise(self.definition(50))
        self.produce_all(30000)
        launches = len(self.calls)
        result = self.engine.step(self.ledger, 'P1', self.adapter)
        self.assertEqual((result['node'], result['state']), ('KZ', 'held'), result)
        self.assertIn('exceeds 80000 characters', result['reason'])
        self.assertEqual(len(self.calls), launches)                            # no model call
        view = self.engine.state(self.ledger, 'P1')
        attempt = self.control.attempt(view['nodes']['KZ']['attempt'])
        body = json.loads(attempt['result'])
        self.assertEqual(body['reason'], 'native_preflight')
        self.assertGreater(body['prompt_chars'], 80000)
        self.assertEqual(set(body['producer_chars']), set(PRODUCERS))
        for nid in PRODUCERS:
            self.assertGreaterEqual(body['producer_chars'][nid], 30000)
            self.assertIn(nid, result['reason'])
        with self.ledger.transaction() as conn:
            from onecrew.budget_core import group
            budget = group(conn, self.root_view['anchor_task'])
        self.assertEqual(budget['reserved_calls'], 0)

    def test_c_a_consumer_outside_the_output_paths_still_gets_each_output_once(self):
        nodes = self.definition(30000)
        nodes[-1]['read'] = ['src1.txt']                                       # the consumer reads none of the outputs itself
        self.revise(nodes)
        produced = self.produce_all(2000)
        self.value = {'summary': 'integrated', 'evidence': [produced['K1']['receipt']]}
        result = self.engine.step(self.ledger, 'P1', self.adapter)
        self.assertEqual(result['state'], 'produced', result)
        prompt = self.calls[-1]['prompt']
        for nid in PRODUCERS:
            self.assertEqual(prompt.count('OUT-%s-' % nid), 1)
            self.assertIn(produced[nid]['artifact'], prompt)
        self.assertEqual(prompt.count('SOURCE-K1-'), 1)                        # its own read file once, the producers' never
        self.assertNotIn('SOURCE-K2-', prompt); self.assertNotIn('SOURCE-K3-', prompt)


if __name__ == '__main__':
    import unittest
    unittest.main()
