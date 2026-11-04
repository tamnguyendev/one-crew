"""T18b: shared repeat rules, sourced liveness, bounded hypotheses; no model."""
import copy
import unittest
from unittest.mock import patch

from onecrew import progress as legacy, progress_core
from onecrew.v2 import progress_track as track
from onecrew.ledger import LedgerError
from tests.test_v2_l1 import Fixture


class ProgressRulesTests(unittest.TestCase):
    def test_recovery_decision_remains_the_exact_v1_implementation(self):
        from onecrew import recovery_core, delivery_recovery
        self.assertIs(delivery_recovery.decide, recovery_core.decide)
        history = {'nodes': {}, 'generation': 0, 'source': {'hash': 'same'}}
        with patch.object(recovery_core, 'runtime_tree', return_value='runtime'):
            self.assertEqual(recovery_core.decide(history, 'N1', 'product', {'failed': 'T1'}, 'still fails')[0], 'repair')
            self.assertEqual(recovery_core.decide(history, 'N1', 'product', {'failed': 'T1'}, 'still fails')[0], 'ask')

    def test_v1_and_v2_use_same_counter_and_new_source_resets_exploration(self):
        self.assertIs(legacy.observe_counters, progress_core.observe_counters)
        value = None
        with patch.object(progress_core, 'observe_counters', wraps=progress_core.observe_counters) as shared:
            for i in range(2):
                value = track.advance(value, {'kind': 'tool', 'action': 'search', 'args': {'query': str(i)},
                    'result': {'matches': []}, 'snapshot': 'same'})
            value = track.advance(value, {'kind': 'tool', 'action': 'read', 'args': {'path': 'A'},
                'result': {'text': 'new source'}, 'snapshot': 'same'})
            self.assertEqual(value['counters']['progress']['observations'], 0)
            for i in range(2):
                value = track.advance(value, {'kind': 'tool', 'action': 'read', 'args': {'path': 'A'},
                    'result': {'text': 'new source'}, 'snapshot': 'same'})
            self.assertEqual(value['status'], 'blocked')
            self.assertIn('same result 3 times', value['reason'])
            self.assertEqual(shared.call_count, 5)

    def test_long_command_with_new_output_runs_until_its_cap(self):
        value = None
        for seconds in range(0, 2401, 300):
            value = track.advance(value, {'kind': 'command', 'elapsed_seconds': seconds,
                'output_hash': 'chunk-' + str(seconds)}, command_cap_seconds=2400)
            self.assertEqual(value['status'], 'blocked' if seconds == 2400 else 'progressing')
        self.assertIn('execution cap', value['reason'])

    def test_quiet_output_is_unknown_not_proof_of_no_progress_and_receipt_advances(self):
        value = track.advance(None, {'kind': 'command', 'elapsed_seconds': 0, 'output_hash': 'same'}, command_cap_seconds=2400)
        value = track.advance(value, {'kind': 'command', 'elapsed_seconds': 1500, 'output_hash': 'same'}, command_cap_seconds=2400)
        self.assertEqual(value['status'], 'unknown')
        value = track.advance(value, {'kind': 'command', 'elapsed_seconds': 1800, 'output_hash': 'same', 'receipt_ref': 'fresh'}, command_cap_seconds=2400)
        self.assertEqual(value['status'], 'progressing')

    def test_wait_and_unknown_do_not_consume_repeat_budget(self):
        value = track.advance(None, {'kind': 'tool', 'action': 'read', 'args': {}, 'result': {'text': 'a'}, 'snapshot': 'same'})
        before = copy.deepcopy(value['counters'])
        for _ in range(20):
            value = track.advance(value, {'kind': 'wait', 'reason': 'owner'})
            self.assertEqual(value['status'], 'waiting')
            value = track.advance(value, {'kind': 'unknown'})
            self.assertEqual(value['status'], 'unknown')
        self.assertEqual(value['counters'], before)

    def test_fourth_rejected_hypothesis_blocks_with_evidence(self):
        value = None
        for i in range(4):
            value = track.advance(value, {'kind': 'hypothesis', 'hypothesis': 'H' + str(i),
                'rejected_by': ['receipt:' + str(i)]})
        self.assertEqual(value['status'], 'blocked')
        self.assertEqual(len(value['rejected_hypotheses']), 4)
        self.assertEqual(value['rejected_hypotheses'][-1]['rejected_by'], ['receipt:3'])

    def test_invalid_or_cosmetic_measurements_cannot_be_progress(self):
        for data in ({'kind': 'command', 'elapsed_seconds': float('nan'), 'output_hash': 'x'},
                     {'kind': 'command', 'elapsed_seconds': -1, 'output_hash': 'x'},
                     {'kind': 'lines_changed', 'count': 1000},
                     {'kind': 'hypothesis', 'hypothesis': 'H', 'rejected_by': []}):
            with self.assertRaises(LedgerError): track.advance(None, data, command_cap_seconds=2400)


class ProgressLedgerTests(Fixture):
    def test_cli_records_and_reads_real_evidence_without_claiming_control(self):
        from onecrew.snapshots import Snapshots
        from onecrew.v2 import executors
        from contextlib import redirect_stdout
        import io
        import json
        self.approved()
        blob = Snapshots(self.ledger.state_root).blob(b'CLI tool evidence')
        file = self.root / 'observation.json'
        file.write_text(json.dumps({'kind': 'unknown'}))
        prefix = ['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'executor']
        out = io.StringIO()
        with redirect_stdout(out):
            code = executors.main(prefix + ['progress', '--plan', 'P1', '--node', 'M1', '--executor', 'claude-code-hook',
                '--attempt', 'A1', '--key', 'K1', '--source', 'receipt', '--ref', blob, '--file', str(file)])
        self.assertEqual(code, 0, out.getvalue())
        result = json.loads(out.getvalue())
        self.assertEqual(result['checkpoint']['status'], 'unknown')
        self.assertFalse(result['grants_execution'])
        before = self.events()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(executors.main(prefix + ['progress-show', '--plan', 'P1', '--node', 'M1']), 0)
        self.assertEqual(self.events(), before)
        with self.assertRaises(LedgerError):
            track.observe(self.ledger, 'P1', 'M1', executors.HookAdapter(), 'A1', 'K2',
                {'kind': 'command', 'elapsed_seconds': 120, 'output_hash': 'reported'}, source='receipt', ref=blob, command_cap_seconds=2400)

    def test_restart_idempotency_and_readonly_projection_with_real_receipt(self):
        from onecrew.snapshots import Snapshots
        from onecrew.v2.executors import HookAdapter
        self.approved()
        blob = Snapshots(self.ledger.state_root).blob(b'actual tool receipt')
        obs = {'kind': 'tool', 'action': 'read', 'args': {'path': 'a.txt'}, 'result': {'text': 'a'}, 'snapshot': 'tree'}
        first = track.observe(self.ledger, 'P1', 'M1', HookAdapter(), 'attempt1', 'obs1', obs, source='receipt', ref=blob)
        again = track.observe(self.ledger, 'P1', 'M1', HookAdapter(), 'attempt1', 'obs1', obs, source='receipt', ref=blob)
        self.assertEqual(first['checkpoint'], again['checkpoint'])
        self.assertEqual(len([p for k, p in self.events() if k == 'executor.observed']), 1)
        changed = dict(obs, result={'text': 'b'})
        with self.assertRaises(LedgerError): track.observe(self.ledger, 'P1', 'M1', HookAdapter(), 'attempt1', 'obs1', changed, source='receipt', ref=blob)
        before = self.events()
        self.assertEqual(track.read(self.ledger, 'P1', 'M1')['checkpoint'], first['checkpoint'])
        self.assertEqual(self.events(), before)
        with self.assertRaises(LedgerError): track.observe(self.ledger, 'P1', 'M1', HookAdapter(), 'attempt1', 'fake', obs, source='internal_reasoning', ref=blob)
