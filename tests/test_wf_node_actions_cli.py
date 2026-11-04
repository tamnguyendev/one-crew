"""Public common-engine commands reuse the same bounded preparation/repair policy."""
import contextlib
import copy
import io
import json
from pathlib import Path

from onecrew.v2 import cli, plan
from tests.test_wf_engine import EngineFixture, node


class NodeActionsCliTests(EngineFixture):
    def call(self, command, body=None, extra=()):
        args = ['--project', str(self.root), '--state-root', str(self.ledger.state_root),
                'engine', command, 'P1', *extra]
        if body is not None:
            path = Path(self.temp.name) / 'action.json'
            path.write_text(json.dumps(body), encoding='utf-8')
            args += ['--file', str(path)]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            status = cli.main(args)
        return status, json.loads(out.getvalue())

    def fail(self):
        self.step()
        def checker(item, artifact):
            result = self.checker(item, artifact)
            result['checks'][0]['result'] = 'fail'
            return result
        self.verify('A', checker)

    def test_prepare_tests_cli_blocks_implementation_until_preparation_verified(self):
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])
        before = plan.show(self.ledger, 'P1')['sha']
        code, result = self.call('prepare-tests', {
            'implementation': 'A', 'node_id': 'Tests', 'write': ['b.txt'],
            'checks': [{'id': 'prep', 'spec': 'Acceptance cases are ready'}],
            'estimate_seconds': [1, 2], 'execution_cap_seconds': 60, 'budget_calls': 1,
            'reason': 'Prepare acceptance cases before implementation', 'evidence': ['a.txt:1']})
        self.assertEqual(code, 0, result)
        self.assertEqual([n['id'] for n in self.engine.ready(self.ledger, 'P1')], ['Tests'])
        self.step()
        self.assertEqual(self.engine.ready(self.ledger, 'P1'), [])
        self.verify('Tests')
        self.assertEqual(self.step()['node'], 'A')
        self.assertEqual(plan.show(self.ledger, 'P1')['sha'], before)

    def test_repair_diagnose_replan_cli_finishes_with_bounded_blocker_without_owner_question(self):
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])
        self.fail()
        code, first = self.call('diagnose', extra=['A'])
        self.assertEqual((code, first['disposition']), (0, 'repair'))
        code, result = self.call('repair', {'target': 'A', 'failed_node': 'A',
            'reason': 'Repair the observed failing test', 'evidence': [first['source_receipt']]})
        self.assertEqual(code, 0, result)
        self.fail()
        code, second = self.call('diagnose', extra=['A'])
        self.assertEqual((code, second['disposition']), (0, 'diagnose'))
        code, refused = self.call('repair', {'target': 'A', 'failed_node': 'A',
            'reason': 'Repeat without new progress', 'evidence': [second['source_receipt']]})
        self.assertEqual(code, 2, refused)
        nodes = copy.deepcopy(self.ip.current(self.ledger, 'P1')['definition']['nodes'])
        nodes[0]['goal'] = 'Investigate the alternative supported by the same failed acceptance test'
        code, revised = self.call('replan', {'failed_node': 'A', 'nodes': nodes,
            'reason': 'One materially different bounded diagnosis', 'evidence': [second['source_receipt']]})
        self.assertEqual(code, 0, revised)
        self.assertFalse(revised['resets_budget'])
        self.fail()
        code, third = self.call('diagnose', extra=['A'])
        self.assertEqual((code, third['disposition']), (0, 'blocked'))
        self.assertEqual(self.ledger.requests(self.root_view['anchor_task']), [])

    def test_cli_cannot_smuggle_authority_or_fake_failure(self):
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])
        before = self.kinds()
        code, result = self.call('repair', {'target': 'A', 'failed_node': 'A',
            'authority': {'edit': True}, 'reason': 'smuggle grant', 'evidence': ['a.txt:1']})
        self.assertEqual(code, 2, result)
        self.assertIn('authority', result['error'])
        self.assertEqual(self.kinds(), before)
        code, result = self.call('diagnose', extra=['A'])
        self.assertEqual(code, 2, result)
        self.assertEqual(self.kinds(), before)
