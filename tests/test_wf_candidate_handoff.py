"""Production candidate verification uses real Git and commands, no provider."""
import copy
import json
import os
import sys

from onecrew.common_verification import CandidateChecker
from onecrew.common_handoff import handoff
from onecrew.control import Control, migrate
from onecrew.ledger import LedgerError, canonical
from onecrew.snapshots import Snapshots
from onecrew.v2 import engine, internal_plan, plan as plans
from tests.test_v2_l1 import Fixture, plan_json, milestone
from tests.test_wf_engine import EngineFixture, node


class CandidateFixture(EngineFixture):
    def milestones(self):
        check = [sys.executable, '-c', 'from pathlib import Path; assert Path("a.txt").read_text()=="candidate\\n"; print("candidate tested")']
        return [milestone(argv=check)]

    def setUp(self):
        Fixture.setUp(self)
        self.engine, self.ip = engine, internal_plan
        self.engine_caps = ['namespaced-storage', 'root-budget', 'internal-plan', 'sequential-engine']
        selected = self.milestones(); self.check_ids = [row['id'] for row in selected]
        value = plan_json(milestones=selected, authority={
            'edit': True, 'commands': True, 'apply_to_project': True, 'unconfined_commands': True,
            'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q9', 'Q12']})
        self.root_view = plans.propose(self.ledger, 'P1', value, 'codex', workflow=True, capabilities=self.engine_caps)
        plans.approve(self.ledger, 'P1', 'owner', 'fixture approved command and apply')
        os.environ['ONECREW_ACTOR'] = 'codex'
        self.store = Snapshots(self.ledger.state_root)
        migrate(self.ledger); self.control = Control(self.ledger)
        self.production_checker = CandidateChecker(self.ledger, 'P1')

    def definition(self):
        nodes = [node('C'), node('I', ['C'], integration=True, write=())]
        for item in nodes: item['checks'] = [{'id': check_id, 'spec': 'The exact approved root command ' + check_id} for check_id in self.check_ids]
        return nodes

    def execute(self, ledger, control, task, item, attempt):
        control.launched(attempt['id'], attempt['generation'], {'fixture': True})
        base = self.store.capture(self.root, ['a.txt'])
        artifact = self.store.overlay(base, {'a.txt': b'candidate\n'}, ['a.txt'])
        receipt = self.store.blob(canonical({'kind': 'fixture-producer', 'artifact': artifact}).encode())
        control.finish(attempt['id'], attempt['generation'], {'artifact': artifact})
        return {'artifact': artifact, 'receipt': receipt}


class CandidateCheckerTests(CandidateFixture):
    def test_native_factory_producer_and_readonly_integration_deliver_actual_snapshot(self):
        from onecrew.common_executor import NativeExecutor
        from onecrew import cli
        import contextlib
        import io
        from unittest.mock import patch
        definition = self.definition()
        for item in definition: item['executor'] = {'role': 'worker', 'provider': 'codex', 'model': 'gpt-6.1-sol'}
        self.revise(definition)
        calls = []
        def factory(control, provider):
            class Worker:
                def capability(self): return {'provider': provider, 'mode': 'fixture-tools-disabled'}
                def run(self, attempt, prompt, schema, profile):
                    calls.append(prompt)
                    control.launched(attempt['id'], attempt['generation'], {'fixture': True})
                    control.finish(attempt['id'], attempt['generation'], {'exit_code': 0})
                def result(self, attempt):
                    value = ({'summary': 'producer', 'files': [{'path':'a.txt','content':'candidate\n'}], 'backlog': []}
                             if len(calls) == 1 else {'summary': 'integration report', 'evidence': []})
                    return value, []
            return Worker()
        with patch('onecrew.artifact_provider_core.make_worker', side_effect=factory):
            def public(*args):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    code = cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'engine', *args])
                self.assertEqual(code, 0, out.getvalue())
                return json.loads(out.getvalue())
            public('step', 'plan-ns:P1')
            public('verify', 'plan-ns:P1', 'C')
            integrated = public('step', 'plan-ns:P1')
            self.assertEqual(self.store.context(integrated['artifact'])['a.txt'], 'candidate\n')
            public('verify', 'plan-ns:P1', 'I')
            result = public('handoff', 'plan-ns:P1')
        self.assertTrue(self.engine.root_ready(self.ledger, 'P1', result['artifact']))
        self.assertEqual(len(calls), 2)
        self.assertEqual((self.root / 'a.txt').read_text(), 'candidate\n')

    def complete_nodes(self):
        self.revise(self.definition()); self.step()
        self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)
        self.step(); self.engine.verify(self.ledger, 'P1', 'I', self.production_checker)

    def test_real_cas_handoff_then_real_root_verdict_and_owner_acceptance(self):
        from onecrew.v2 import verdict
        from unittest.mock import patch
        self.complete_nodes()
        self.assertFalse(self.engine.root_ready(self.ledger, 'P1'))
        before_index = self.git('write-tree')
        result = handoff(self.ledger, 'P1', control=self.control)
        self.assertEqual(result['state'], 'delivered')
        self.assertEqual((self.root / 'a.txt').read_text(), 'candidate\n')
        self.assertEqual(self.git('write-tree'), before_index)
        self.assertTrue(self.engine.root_ready(self.ledger, 'P1', result['artifact']))
        self.assertEqual(handoff(self.ledger, 'P1', control=self.control)['idempotent'], True)
        self.assertEqual(plans.show(self.ledger, 'P1')['status'], 'approved')
        verdict.run(self.ledger, 'P1', 'M1')
        with patch.dict(os.environ, {'ONECREW_ACTOR': ''}):
            accepted = plans.accept(self.ledger, 'P1', 'owner', 'Verified delivered candidate accepted', result['artifact'])
        self.assertEqual(accepted['status'], 'accepted')

    def test_user_edit_between_verification_and_handoff_is_preserved(self):
        self.complete_nodes()
        (self.root / 'a.txt').write_text('user concurrent edit\n')
        with self.assertRaisesRegex(LedgerError, 'changed since the pin'):
            handoff(self.ledger, 'P1', control=self.control)
        self.assertEqual((self.root / 'a.txt').read_text(), 'user concurrent edit\n')
        self.assertNotIn('workflow.handoff', self.kinds())
        self.assertFalse(self.engine.root_ready(self.ledger, 'P1'))

    def test_real_root_command_checks_candidate_bytes_in_clean_checkout(self):
        from onecrew.v2.verifiers import command
        from unittest.mock import patch
        self.revise(self.definition())
        produced = self.step()
        self.assertEqual((self.root / 'a.txt').read_text(), 'one\n')
        with patch.object(command, 'verifier_env', wraps=command.verifier_env) as environment_snapshot:
            result = self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)
        self.assertEqual(environment_snapshot.call_count, 1, 'receipt binding and actual process must share one effective environment snapshot')
        self.assertEqual(result['result'], 'pass')
        proof = result['observed']
        self.assertEqual(proof['artifact'], produced['artifact'])
        self.assertNotEqual(proof['candidate_tree'], self.tree())
        self.assertEqual((self.root / 'a.txt').read_text(), 'one\n')
        retained = json.loads(self.store.read_blob(proof['checks'][0]['evidence']))
        command_receipt = json.loads(self.store.read_blob(retained['command_receipt']))
        self.assertEqual(command_receipt['artifact_sha'], proof['candidate_tree'])
        self.assertEqual(command_receipt['exit_code'], 0)
        self.assertEqual(proof['evidence_binding']['checks'], ['M1'])
        self.assertFalse(self.engine.root_ready(self.ledger, 'P1'))

    def test_textual_unknown_check_or_report_cannot_substitute_for_configured_command(self):
        definition = self.definition(); definition[0]['checks'][0]['id'] = 'Invented'
        self.revise(definition); self.step()
        with self.assertRaisesRegex(LedgerError, 'approved command milestone'):
            self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)
        self.assertNotIn('node.verification', self.kinds())

    def test_mandatory_integration_rejects_omitted_producer_content(self):
        self.revise(self.definition()); self.step()
        self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)
        def omission(ledger, control, task, item, attempt):
            control.launched(attempt['id'], attempt['generation'], {'fixture': True})
            artifact = self.store.capture(self.root, ['a.txt'])
            control.finish(attempt['id'], attempt['generation'], {'fixture': True})
            return {'artifact': artifact, 'receipt': self.store.blob(b'fixture integration omitted upstream content')}
        self.step(omission)
        with self.assertRaisesRegex(LedgerError, 'lost producer output'):
            self.engine.verify(self.ledger, 'P1', 'I', self.production_checker)
        self.assertFalse(self.engine.verification_ready(self.ledger, 'P1'))


class RepairCandidateTests(CandidateFixture):
    def milestones(self):
        return [milestone('M2', argv=[sys.executable, '-c', 'print("affected check ran")']),
                milestone('M1', argv=[sys.executable, '-c', 'from pathlib import Path; assert Path("a.txt").read_text()=="fixed\\n"; print("failed prerequisite fixed")'])]

    def test_diagnostic_replan_rebinds_failed_first_once_and_replays_stored_plan_after_crash(self):
        from onecrew.v2 import recovery_policy, repair_tasks
        from onecrew.v2.verifiers import command
        from unittest.mock import patch
        self.revise(self.definition()); self.step()
        self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)
        repair_tasks.prepare(self.ledger, 'P1', 'C', 'C', reason='First bounded actual repair', evidence=['a.txt:1'])
        self.step(); self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)
        diagnosis = recovery_policy.assess(self.ledger, 'P1', 'C')
        self.assertEqual(diagnosis['disposition'], 'diagnose')
        proposal = copy.deepcopy(self.ip.current(self.ledger, 'P1')['definition']['nodes'])
        proposal[0]['goal'] = 'Diagnose the different input conversion supported by the actual failed command'
        kwargs = {'reason':'Use one different bounded diagnostic approach', 'evidence':[diagnosis['source_receipt']]}
        original_revise = self.ip.revise
        def crash_after_plan(*args, **values):
            original_revise(*args, **values)
            raise OSError('fixture crash after plan publication')
        with patch.object(self.ip, 'revise', side_effect=crash_after_plan):
            with self.assertRaises(OSError): recovery_policy.replan(self.ledger, 'P1', 'C', proposal, **kwargs)
        retained_revision = self.ip.current(self.ledger, 'P1')['internal_revision']
        with patch.object(repair_tasks, 'rebind_order', side_effect=AssertionError('must load stored rebased bytes')):
            replay = recovery_policy.replan(self.ledger, 'P1', 'C', proposal, **kwargs)
        self.assertEqual(replay['internal_revision'], retained_revision)
        self.step()
        ran = []; actual_run = command.run
        def capture(*args, **values):
            ran.append(args[4]['id']); return actual_run(*args, **values)
        with patch.object(command, 'run', side_effect=capture):
            observed = self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)
        self.assertEqual(ran, ['M1'])
        self.assertEqual(observed['observed']['checks'][1]['result'], 'blocked')
        self.assertEqual(recovery_policy.assess(self.ledger, 'P1', 'C')['disposition'], 'blocked')

    def test_actual_failed_command_runs_first_and_blocks_other_checks_until_fixed(self):
        from onecrew.v2 import repair_tasks
        from onecrew.v2.verifiers import command
        from unittest.mock import patch
        self.revise(self.definition()); self.step()
        first = self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)
        self.assertEqual(first['result'], 'fail')
        repair_tasks.prepare(self.ledger, 'P1', 'C', 'C', reason='Repair the actual failed acceptance command', evidence=['a.txt:1'])
        self.step()
        ran = []
        actual_run = command.run
        def capture(*args, **kwargs):
            ran.append(args[4]['id'])
            return actual_run(*args, **kwargs)
        with patch.object(command, 'run', side_effect=capture):
            failed = self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)
        self.assertEqual(ran, ['M1'])
        self.assertEqual(failed['result'], 'fail')
        self.assertEqual([(row['id'], row['result']) for row in failed['observed']['checks']], [('M1','fail'),('M2','blocked')])
        with self.assertRaisesRegex(LedgerError, 'requires diagnose'):
            repair_tasks.prepare(self.ledger, 'P1', 'C', 'C', reason='Repeat unchanged repair', evidence=['a.txt:1'])

    def test_fixed_prerequisite_then_runs_every_remaining_required_command(self):
        from onecrew.v2 import repair_tasks
        from onecrew.v2.verifiers import command
        from unittest.mock import patch
        self.revise(self.definition()); self.step()
        self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)
        repair_tasks.prepare(self.ledger, 'P1', 'C', 'C', reason='Repair actual failed command using bound feedback', evidence=['a.txt:1'])
        def fixed(ledger, control, task, item, attempt):
            result = self.execute(ledger, control, task, item, attempt)
            result['artifact'] = self.store.overlay(result['artifact'], {'a.txt': b'fixed\n'}, ['a.txt'])
            return result
        self.step(fixed); ran = []
        actual_run = command.run
        def capture(*args, **kwargs):
            ran.append(args[4]['id'])
            return actual_run(*args, **kwargs)
        with patch.object(command, 'run', side_effect=capture):
            passed = self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)
        self.assertEqual(ran, ['M1','M2'])
        self.assertEqual(passed['result'], 'pass')
