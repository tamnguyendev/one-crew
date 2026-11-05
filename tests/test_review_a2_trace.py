"""2.5-A cycle 2: tracking_work.review_trace on real temporary ledgers written by the real writers.

Read-only; `unknown` wherever no event or receipt establishes a link; no verdict or applicability is computed.
"""
import copy

from onecrew.ledger import LedgerError
from onecrew.v2 import findings, review_dispatch, tracking_work
from tests import test_review_a2_findings as chain
from tests import test_review_dispatch_lifecycle as lifecycle
from tests import test_wf_review_dispatch as dispatch_fixtures


def snapshot(case):
    with case.ledger.transaction() as conn:
        return [tuple(r) for r in conn.execute('SELECT seq, task_id, kind, payload FROM events ORDER BY seq')]


class FindingChainTrace(chain.NodeRecheck):
    for _inherited in [n for n in dir(chain.NodeRecheck) if n.startswith('test')]:
        locals()[_inherited] = None
    del _inherited

    def test_open_finding_before_any_repair_has_unknown_downstream_links(self):
        before = snapshot(self)
        trace = tracking_work.review_trace(self.ledger, 'P1')
        self.assertEqual(snapshot(self), before, 'the projection writes nothing')
        self.assertTrue(trace['read_only'])
        [row] = trace['findings']
        self.assertEqual((row['id'], row['status'], row['node']), (self.finding['id'], 'open', 'I'))
        self.assertEqual(row['source_receipt'], self.red_receipt)
        for link in ('repair', 'output', 'recheck', 'from_run'):
            self.assertEqual(row[link]['link'], 'unknown', link); self.assertTrue(row[link]['reason'])
        self.assertIn(self.red_receipt, [r['receipt'] for r in trace['receipts']])
        red = next(r for r in trace['receipts'] if r['receipt'] == self.red_receipt)
        self.assertEqual((red['origin'], red['node'], red['result']), ('node.verification', 'I', 'fail'))
        self.assertEqual(red['request_link']['link'], 'unknown')

    def test_repaired_rechecked_and_closed_finding_is_fully_linked_to_events(self):
        receipt = self.repair_and_pass()
        mid = tracking_work.review_trace(self.ledger, 'P1')['findings'][0]
        self.assertEqual(mid['repair']['link'], 'known'); self.assertEqual(mid['repair']['target'], 'N1')
        self.assertEqual(mid['output']['link'], 'known'); self.assertEqual(mid['output']['node'], 'N1')
        self.assertEqual((mid['recheck']['link'], mid['recheck']['result'], mid['recheck']['closed']), ('known', 'pass', False))
        self.assertEqual(mid['recheck']['request']['link'], 'unknown')       # an engine pass names no request
        request = self.request('I')
        self.assertEqual(findings.close_from_recheck(self.ledger, 'P1', self.finding['id'], run_receipt=receipt, request=request)['closed'],
                         [self.finding['id']])
        row = tracking_work.review_trace(self.ledger, 'P1')['findings'][0]
        self.assertEqual(row['status'], 'resolved')
        self.assertEqual((row['recheck']['receipt'], row['recheck']['closed']), (receipt, True))
        self.assertEqual(row['recheck']['request'], {'link': 'known', 'request_id': request['id']})
        self.assertEqual(row['repair']['source']['kind'], 'plan.revised'); self.assertEqual(row['output']['source']['kind'], 'node.produced')
        self.assertGreater(row['output']['source']['seq'], row['repair']['source']['seq'])
        self.assertGreater(row['recheck']['source']['seq'], row['output']['source']['seq'])

    def test_without_optional_review_runs_requests_and_runs_are_empty_not_invented(self):
        trace = tracking_work.review_trace(self.ledger, 'P1')
        self.assertEqual(trace['requests'], []); self.assertEqual(trace['runs'], [])


class OptionalRunTrace(lifecycle.OptionalLifecycle):
    for _inherited in [n for n in dir(lifecycle.OptionalLifecycle) if n.startswith('test')]:
        locals()[_inherited] = None
    del _inherited

    def test_request_run_receipt_chain_and_held_run_come_from_the_run_events(self):
        self.step()
        done = self.invoke(self.result)
        trace = tracking_work.review_trace(self.ledger, 'P1')
        [request] = trace['requests']
        self.assertEqual(request['id'], done['request_id']); self.assertEqual(request['kind'], 'node')
        self.assertEqual(request['runs'], [done['run_id']]); self.assertTrue(request['execution_complete'])
        [run] = trace['runs']
        self.assertEqual((run['run_id'], run['status'], run['receipt']), (done['run_id'], 'observed', done['receipt']))
        self.assertEqual((run['door'], run['door_source']), ('review_dispatch.optional', 'event-kind'))
        self.assertEqual(run['actor_status'], 'unknown')                      # no event records who ran it: not invented
        self.assertEqual([s['kind'] for s in run['sources']], ['review.run_started', 'review.run_result', 'review.run_finished'])
        receipt = next(r for r in trace['receipts'] if r['receipt'] == done['receipt'])
        self.assertEqual((receipt['origin'], receipt['run_id'], receipt['request_link']),
                         ('review.run', done['run_id'], {'link': 'known', 'request_id': request['id']}))

    def test_a_run_with_unknown_outcome_is_reported_held_and_a_second_request_is_a_second_request(self):
        self.step()
        def lost(*args): raise OSError('ambiguous acknowledgement')
        with self.assertRaises(OSError): self.invoke(lost)
        trace = tracking_work.review_trace(self.ledger, 'P1')
        [run] = trace['runs']
        self.assertEqual((run['status'], run['receipt']), ('held', None)); self.assertIn('Outcome', run['hold_reason'])
        self.assertEqual(trace['receipts'], [])
        other = dict(lifecycle.EXECUTION, implementation='fixture-checker-v2')
        self.invoke(self.result, execution=other)
        trace = tracking_work.review_trace(self.ledger, 'P1')
        self.assertEqual(len(trace['requests']), 2); self.assertEqual(len(trace['runs']), 2)
        self.assertEqual({r['status'] for r in trace['runs']}, {'held', 'observed'})
