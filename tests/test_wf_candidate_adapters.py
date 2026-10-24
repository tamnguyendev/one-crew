"""One candidate engine runs document/data/operation checks through the existing port."""
import copy
import json
import os

from onecrew.common_handoff import handoff
from onecrew.common_verification import CandidateChecker
from onecrew.control_core import Control, migrate
from onecrew.ledger import LedgerError, canonical
from onecrew.snapshots import Snapshots
from onecrew.v2 import engine, internal_plan, plan
from tests.test_v2_l1 import Fixture, plan_json
from tests.test_wf_engine import EngineFixture, node
from tests.test_wf_rx2_adapters import DATA, TABLE, OPS, write_ops


class CandidateAdapterTests(EngineFixture):
    def setUp(self):
        Fixture.setUp(self)
        self.engine, self.ip = engine, internal_plan
        self.git('config', 'core.autocrlf', 'true')
        self.paths = ['guide.md', 'input.csv', 'output.csv', 'pre.json', 'post.json', 'operation.json', 'observation.json']
        (self.root / 'guide.md').write_text('# Before\n')
        for name in ('input.csv', 'output.csv'): (self.root / name).write_bytes(TABLE.replace('\n', '\r\n').encode())
        write_ops(self.root)
        self.git('add', '.'); self.git('commit', '-qm', 'evidence baseline')
        checks = [('Doc', 'doc', {'docs': [{'path': 'guide.md', 'headings': ['Summary']}]}),
                  ('Data', 'data', DATA), ('Ops', 'ops', OPS)]
        milestones = [{'id': mid, 'title': mid, 'covers': ['O1'], 'verifier': {'type': kind, 'config': copy.deepcopy(config)}}
                      for mid, kind, config in checks]
        value = plan_json(milestones=milestones, items=[{'id': 'I1', 'title': 'Verified output', 'tier': 'must', 'milestone': 'Doc'}],
            scope={'owned': self.paths}, authority={
            'edit': True, 'commands': False, 'apply_to_project': True,
            'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q9', 'Q12']})
        self.root_view = plan.propose(self.ledger, 'P1', value, 'codex', workflow=True,
            capabilities=['namespaced-storage', 'root-budget', 'internal-plan', 'sequential-engine'])
        plan.approve(self.ledger, 'P1', 'owner', 'fixture read-only checks and explicit apply')
        os.environ['ONECREW_ACTOR'] = 'codex'
        self.store = Snapshots(self.ledger.state_root); migrate(self.ledger); self.control = Control(self.ledger)
        self.overlays = {'guide.md': b'# Summary\nThe verified deliverable.\n'}
        rows = [node('C', write=self.paths), node('I', ['C'], integration=True, write=())]
        for item in rows:
            item['read'] = list(self.paths)
            item['checks'] = [{'id': m['id'], 'spec': 'Run the approved ' + m['id'] + ' verifier'} for m in milestones]
        self.revise(rows)

    def execute(self, ledger, control, task, item, attempt):
        control.launched(attempt['id'], attempt['generation'], {'fixture': True})
        artifact = self.store.overlay(self.store.capture(self.root, self.paths), self.overlays, self.paths)
        receipt = self.store.blob(canonical({'kind': 'fixture', 'artifact': artifact}).encode())
        control.finish(attempt['id'], attempt['generation'], {'artifact': artifact})
        return {'artifact': artifact, 'receipt': receipt}

    def test_same_engine_verifies_three_adapters_on_candidate_without_host_command_grant(self):
        self.step()
        checked = self.verify('C', CandidateChecker(self.ledger, 'P1'))
        self.assertEqual(checked['result'], 'pass')
        self.assertEqual((self.root / 'guide.md').read_text(), '# Before\n')
        for row in checked['observed']['checks']:
            proof = json.loads(self.store.read_blob(row['evidence']))
            receipt = json.loads(self.store.read_blob(proof['adapter_receipt']))
            self.assertEqual((receipt['calls'], receipt['violations']), (0, []))
            self.assertEqual(proof['evidence_binding']['artifact'], checked['artifact'])
        self.step(); self.verify('I', CandidateChecker(self.ledger, 'P1'))
        result = handoff(self.ledger, 'P1')
        self.assertTrue(engine.root_ready(self.ledger, 'P1', result['artifact']))
        self.assertEqual(plan.show(self.ledger, 'P1')['status'], 'approved')

    def test_bad_document_fails_and_unsettled_operation_remains_inconclusive(self):
        self.overlays['guide.md'] = b'# Wrong heading\n'
        self.overlays['operation.json'] = b'{"status":"unknown"}'
        self.step()
        result = self.verify('C', CandidateChecker(self.ledger, 'P1'))
        rows = {row['id']: row['result'] for row in result['observed']['checks']}
        self.assertEqual(rows, {'Doc': 'fail', 'Data': 'pass', 'Ops': 'inconclusive'})
        self.assertEqual(result['result'], 'inconclusive')
        self.assertNotIn('workflow.recovery_decided', self.kinds())
        self.assertFalse(engine.verification_ready(self.ledger, 'P1'))
