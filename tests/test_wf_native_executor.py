"""Actual checkout adapter/factory path with fake CLI workers, no provider calls.

Proves sealed pins, Control accounting, scoped snapshots and observed progress;
does not prove installed/native CLI availability or candidate verification/apply.
"""
import copy
import json
from unittest.mock import patch

from onecrew.common_executor import NativeExecutor
from onecrew.ledger import LedgerError
from onecrew.v2 import progress_track
from tests.test_wf_engine import EngineFixture, node


class NativeExecutorTests(EngineFixture):
    def setUp(self):
        super().setUp()
        self.calls = []
        self.value = {'summary': 'Fixture producer', 'files': [{'path': 'a.txt', 'content': 'candidate\n'}], 'backlog': []}
        self.preflight_error = None
        self.result_error = None
        self.adapter = NativeExecutor(self.ledger)
        factory = patch('onecrew.artifact_provider_core.make_worker', side_effect=self.factory)
        factory.start(); self.addCleanup(factory.stop)

    def factory(self, control, provider):
        case = self
        class Worker:
            def capability(self):
                if case.preflight_error: raise LedgerError(case.preflight_error)
                return {'provider': provider, 'mode': 'fixture-no-tools'}

            def run(self, attempt, prompt, schema, profile):
                case.calls.append({'provider': provider, 'profile': profile, 'prompt': prompt, 'schema': schema, 'attempt': attempt['id']})
                control.launched(attempt['id'], attempt['generation'], {'fixture': True})
                control.finish(attempt['id'], attempt['generation'], {'exit_code': 0, 'fixture': True})

            def result(self, attempt):
                if case.result_error: raise LedgerError(case.result_error)
                return copy.deepcopy(case.value), [{'source': 'fixture'}]
        return Worker()

    def definition(self, readonly=False):
        first = node('C', write=() if readonly else ('a.txt',))
        first['executor'] = {'role': 'worker', 'provider': 'codex', 'model': 'gpt-6.1-sol'}
        integration = node('I', ['C'], integration=True, write=())
        integration['executor'] = {'role': 'worker', 'provider': 'claude', 'model': 'claude-haiku-5-5'}
        return [first, integration]

    def native_step(self):
        return self.engine.step(self.ledger, 'P1', self.adapter)

    def test_actual_factory_receives_sealed_pin_and_publishes_candidate_without_project_apply(self):
        self.revise(self.definition())
        before = (self.root / 'a.txt').read_bytes()
        result = self.native_step()
        self.assertEqual(result['state'], 'produced')
        call = self.calls[0]
        self.assertEqual((call['provider'], call['profile']['model']), ('codex', 'gpt-6.1-sol'))
        self.assertEqual(self.store.context(result['artifact'])['a.txt'], 'candidate\n')
        self.assertEqual((self.root / 'a.txt').read_bytes(), before)
        receipt = json.loads(self.store.read_blob(result['receipt']))
        self.assertEqual((receipt['role'], receipt['provider'], receipt['model']), ('worker', 'codex', 'gpt-6.1-sol'))
        self.assertEqual(receipt['changed_paths'], ['a.txt'])
        observed = progress_track.read(self.ledger, 'P1', 'C')
        self.assertEqual(observed['basis']['ref'], result['receipt'])
        self.assertEqual(observed['checkpoint']['status'], 'progressing')
        self.assertFalse(self.engine.root_ready(self.ledger, 'P1'))

    def test_upstream_snapshot_candidate_is_the_next_worker_input_with_its_own_role_pin(self):
        self.revise(self.definition())
        first = self.native_step()
        self.verify('C')
        self.value = {'summary': 'Fixture integration report', 'evidence': [first['receipt']]}
        second = self.native_step()
        self.assertEqual(second['node'], 'I')
        self.assertEqual((self.calls[1]['provider'], self.calls[1]['profile']['model']), ('claude', 'claude-haiku-5-5'))
        self.assertIn('candidate\\n', self.calls[1]['prompt'])
        receipt = json.loads(self.store.read_blob(second['receipt']))
        self.assertEqual(receipt['inputs']['C']['artifact'], first['artifact'])
        self.assertEqual((self.root / 'a.txt').read_text(), 'one\n')

    def test_no_worker_pin_or_outside_owned_output_cannot_publish_a_candidate(self):
        plain = [node('C'), node('I', ['C'], integration=True, write=())]
        self.revise(plain)
        with self.assertRaisesRegex(LedgerError, 'pinned executor'):
            self.native_step()
        self.assertEqual(self.calls, [])
        self.revise(self.definition())
        self.value['files'][0]['path'] = 'outside.txt'
        result = self.native_step()
        self.assertEqual(result['state'], 'held')
        self.assertFalse((self.root / 'outside.txt').exists())
        self.assertNotIn('node.produced', self.kinds())

    def test_preflight_is_not_charged_and_quota_never_switches_provider(self):
        self.revise(self.definition())
        self.preflight_error = 'Pinned Codex CLI/auth unavailable'
        self.assertEqual(self.native_step()['state'], 'held')
        self.assertEqual(self.calls, [])
        with self.ledger.transaction() as conn:
            from onecrew.budget_core import group
            budget = group(conn, self.root_view['anchor_task'])
        self.assertEqual((budget['used_calls'], budget['reserved_calls']), (0, 0))
        definition = self.definition(); definition[0]['goal'] += ' after a verified environment repair'
        self.revise(definition)
        self.preflight_error = None
        self.result_error = 'usage limit reached; pinned provider quota'
        self.assertEqual(self.native_step()['state'], 'held')
        self.assertEqual([call['provider'] for call in self.calls], ['codex'])

    def test_rewriting_readonly_report_prose_is_unknown_without_new_observed_evidence(self):
        definition = self.definition(readonly=True)
        for number in range(3):
            changed = copy.deepcopy(definition); changed[0]['goal'] += ' wording ' + str(number)
            self.revise(changed)
            self.value = {'summary': 'Different model prose ' + str(number), 'evidence': ['unverified external claim']}
            self.assertEqual(self.native_step()['state'], 'produced')
            observation = progress_track.read(self.ledger, 'P1', 'C')
            self.assertEqual(observation['checkpoint']['status'], 'unknown')
        self.assertEqual(len(self.calls), 3)

    def test_repeat_observer_blocks_engine_even_when_worker_summary_changes(self):
        definition = self.definition()
        for number in range(3):
            changed = copy.deepcopy(definition); changed[0]['goal'] += ' wording ' + str(number)
            self.revise(changed)
            self.value['summary'] = 'Prose rewrite ' + str(number)
            result = self.native_step()
        self.assertEqual(result['state'], 'held')
        self.assertEqual(result['progress'], 'blocked')
        self.assertEqual(self.engine.state(self.ledger, 'P1')['nodes']['C']['classification'], 'progress_blocked')
        self.assertEqual(progress_track.read(self.ledger, 'P1', 'C')['checkpoint']['status'], 'blocked')
