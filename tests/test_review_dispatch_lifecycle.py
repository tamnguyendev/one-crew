"""2.5-B optional review lifecycle: actual ledger concurrency, no provider calls."""
import concurrent.futures
import copy
import json
import threading
from unittest.mock import patch

from onecrew.ledger import LedgerError
from onecrew.v2 import review_dispatch
from tests import test_wf_review_dispatch as fixtures


EXECUTION = {'method': 'adapter', 'implementation': 'fixture-checker-v1',
             'configuration': {}, 'environment': {'fixture': 'local'},
             'provenance': {'adapter': 'test_review_dispatch_lifecycle'}}


class OptionalLifecycle(fixtures.ReviewDispatchTests):
    depth = 'deep'
    test_light_optional_skip_does_not_complete_node_and_required_engine_checker_runs = None

    def invoke(self, checker, execution=EXECUTION):
        artifact = self.engine.state(self.ledger, 'P1')['nodes']['C']['artifact']
        return review_dispatch.optional(self.ledger, 'P1', 'C', 'extra', checker, artifact,
                                        execution=execution)

    def result(self, item, artifact):
        return {'result': 'pass', 'artifact': artifact}

    def test_concurrent_requests_dispatch_once_and_follow_original_run(self):
        self.step()
        entered, release = threading.Event(), threading.Event()
        calls = []
        def checker(item, artifact):
            calls.append(artifact); entered.set()
            if not release.wait(20): raise RuntimeError('fixture release missing')
            return self.result(item, artifact)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.invoke, checker)
            self.assertTrue(entered.wait(20))
            try:
                second = self.invoke(checker)
                self.assertEqual(second['status'], 'pending')
                self.assertFalse(second['executed'])
            finally: release.set()
            done = first.result(timeout=20)
        self.assertEqual(len(calls), 1)
        self.assertEqual(done['run_id'], second['run_id'])
        again = self.invoke(lambda *args: self.fail('cached evidence must not dispatch'))
        self.assertEqual(again['receipt'], done['receipt'])
        self.assertTrue(again['cached_observation'])
        self.assertEqual(self.kinds().count('review.run_started'), 1)
        self.assertNotIn('node.verification', self.kinds())

    def test_unknown_exception_is_held_after_restart_and_cannot_be_claimed_success(self):
        self.step()
        def lost(*args): raise OSError('ambiguous acknowledgement')
        with self.assertRaises(OSError): self.invoke(lost)
        again = self.invoke(lambda *args: self.fail('unknown must not replay'))
        self.assertEqual(again['status'], 'held')
        reconciled = review_dispatch.reconcile_optional(self.ledger, 'P1', again['run_id'])
        self.assertEqual(reconciled['status'], 'held')
        self.assertFalse(reconciled['executed'])
        self.assertEqual(self.kinds().count('review.run_started'), 1)
        self.assertNotIn('review.observed', self.kinds())
        self.assertEqual(self.ledger.requests(), [])

    def test_issued_result_is_reconciled_after_interrupted_publication_without_replay(self):
        self.step()
        with patch.object(review_dispatch, '_publish_optional', side_effect=RuntimeError('publication interrupted')):
            with self.assertRaises(RuntimeError): self.invoke(self.result)
        issued = [p for k, p in self.events() if k == 'review.run_result'][0]
        result = review_dispatch.reconcile_optional(self.ledger, 'P1', issued['run_id'])
        self.assertEqual(result['status'], 'observed')
        self.assertFalse(result['executed'])
        again = self.invoke(lambda *a: self.fail('issued result must not run again'))
        self.assertEqual(again['receipt'], result['receipt'])
        self.assertEqual(self.kinds().count('review.observed'), 1)

    def test_changed_input_retains_result_without_applicability(self):
        self.step()
        def changed(item, artifact):
            nodes = copy.deepcopy(self.nodes); nodes[0]['goal'] = 'Changed during review'
            self.revise(nodes)
            return self.result(item, artifact)
        result = self.invoke(changed)
        self.assertEqual(result['status'], 'stale_observation')
        self.assertNotIn('node.verification', self.kinds())
        self.assertEqual(self.engine.state(self.ledger, 'P1')['nodes']['C']['state'], None)

    def test_unknown_checker_never_gets_authenticated_completed_reuse(self):
        self.step(); calls = []
        def checker(item, artifact): calls.append(artifact); return self.result(item, artifact)
        first = self.invoke(checker, execution=None)
        second = self.invoke(checker, execution=None)
        self.assertEqual(len(calls), 2)
        self.assertFalse(first['cache_reusable'])
        self.assertFalse(second['cached_observation'])
        self.assertNotEqual(first['run_id'], second['run_id'])

    def test_corrupt_issued_blob_is_not_reused_or_replayed(self):
        self.step(); first = self.invoke(self.result)
        real_read = self.store.read_blob
        def corrupt(key):
            return b'{"authority":"pass"}' if key == first['receipt'] else real_read(key)
        with patch('onecrew.snapshots.Snapshots.read_blob', side_effect=corrupt):
            with self.assertRaises(LedgerError):
                self.invoke(lambda *args: self.fail('corruption is not permission to redispatch'))

    def test_distinct_execution_identity_does_not_reuse_other_reviewer(self):
        self.step(); first = self.invoke(self.result)
        other = copy.deepcopy(EXECUTION); other['implementation'] = 'fixture-checker-v2'
        second = self.invoke(self.result, execution=other)
        self.assertFalse(second['cached_observation'])
        self.assertNotEqual(first['request_id'], second['request_id'])

    def test_lost_process_has_no_automatic_lease_retry(self):
        self.step()
        with patch.object(review_dispatch, '_publish_optional', side_effect=RuntimeError('pause after issue')):
            with self.assertRaises(RuntimeError): self.invoke(self.result)
        # This one has issued evidence: recovery is valid without checker replay.
        issued = [p for k, p in self.events() if k == 'review.run_result'][0]
        with patch('onecrew.v2.verdict.process_alive', return_value=False):
            result = review_dispatch.reconcile_optional(self.ledger, 'P1', issued['run_id'])
        self.assertEqual(result['status'], 'observed')
        self.assertTrue(result['reconciled'])

    def test_unissued_result_after_controller_loss_stays_held(self):
        self.step()
        def lost(*args): raise OSError('simulate process loss before receipt')
        # A killed controller cannot record its exception. Leave its start
        # durable, then let another invocation observe that process as dead.
        with patch.object(review_dispatch, '_hold'):
            with self.assertRaises(OSError): self.invoke(lost)
        with patch('onecrew.v2.verdict.process_alive', return_value=False):
            result = self.invoke(lambda *a: self.fail('dead controller does not permit replay'))
        self.assertEqual(result['status'], 'held')
        self.assertIsNone(result['receipt'])
        self.assertEqual(self.kinds().count('review.run_started'), 1)

    def test_cache_can_be_read_without_a_new_callable(self):
        self.step(); first = self.invoke(self.result)
        cached = self.invoke(None)
        self.assertTrue(cached['cached_observation'])
        self.assertEqual(cached['receipt'], first['receipt'])

    def test_execution_secrets_are_not_persisted_and_unknown_recovery_is_not_cache(self):
        self.step()
        declared = copy.deepcopy(EXECUTION)
        declared['configuration']['secret'] = 'private-config-value'
        declared['environment']['TOKEN'] = 'private-env-value'
        self.invoke(self.result, execution=declared)
        serialized = json.dumps(self.events())
        self.assertNotIn('private-config-value', serialized)
        self.assertNotIn('private-env-value', serialized)
        with patch.object(review_dispatch, '_publish_optional', side_effect=RuntimeError('interrupted')):
            with self.assertRaises(RuntimeError): self.invoke(self.result, execution=None)
        issued = [p for k, p in self.events() if k == 'review.run_result'][-1]
        recovered = review_dispatch.reconcile_optional(self.ledger, 'P1', issued['run_id'])
        self.assertTrue(recovered['reconciled'])
        self.assertFalse(recovered['cached_observation'])
        self.assertFalse(recovered['cache_reusable'])

    def test_run_records_are_neutral_and_unknown_event_guard_is_preserved(self):
        from onecrew.v2 import compat
        self.step(); self.invoke(self.result)
        for kind in review_dispatch._RUN_KINDS:
            self.assertEqual(compat.event_class(kind), 'A')
            compat.check_write(kind, {}, 'plan:old-reader')
        with self.assertRaises(LedgerError): compat.check_write('review.unknown_kind', {}, 'plan:old-reader')
        self.assertEqual(self.engine.state(self.ledger, 'P1')['nodes']['C']['state'], 'produced')
