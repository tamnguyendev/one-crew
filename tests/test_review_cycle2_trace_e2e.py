"""Cycle 2 integration: 2.5-A's review_trace reads what 2.5-B's real doors recorded, on the coding and the document/data loop.

Neither agent exercised this pair: A tested the trace with its own fixtures, B never consumed it.
"""
import json

from onecrew.common_verification import CandidateChecker
from onecrew.v2 import engine, findings, repair_tasks, tracking_work
from tests.test_review_b2_e2e import CodingCase, DocumentDataCase


class Trace:
    test_t7_coding_output_check_finding_repair_recheck_delivery = None
    test_t7_document_data_same_workflow_with_existing_adapters = None

    def loop(self):
        checker = CandidateChecker(self.ledger, 'P1')
        self.step()
        self.assertEqual(self.verify('C', checker)['result'], 'fail')
        [finding] = findings.list_findings(self.ledger, 'P1', open_only=True)
        failed = engine.state(self.ledger, 'P1')['nodes']['C']['verification_receipt']
        repair_tasks.prepare(self.ledger, 'P1', 'C', 'C', reason='Fix the failed check', evidence=[failed])
        self.overlays.update(self.good)
        self.step()
        self.assertEqual(self.verify('C', checker)['result'], 'pass')
        green = engine.state(self.ledger, 'P1')['nodes']['C']['verification_receipt']
        return finding, failed, green

    def events_count(self):
        with self.ledger.transaction() as conn:
            return conn.execute('SELECT COUNT(*) FROM events').fetchone()[0]

    def test_the_trace_shows_the_real_doors_from_output_to_recheck(self):
        finding, failed, green = self.loop()
        before = self.events_count()
        trace = tracking_work.review_trace(self.ledger, 'P1')
        self.assertEqual(self.events_count(), before)                    # read-only
        text = json.dumps(trace, ensure_ascii=False, default=str)
        runs = [r for r in trace['runs'] if r.get('node') == 'C' and r.get('door') == 'engine.verify']
        self.assertEqual(len(runs), 2, text[:3000])                      # two generations, two runs: a recheck is not the same run
        self.assertEqual({r['door_source'] for r in runs}, {'recorded'})
        self.assertNotEqual(runs[0]['request_id'], runs[1]['request_id'])  # the repaired output is a new request
        [row] = [f for f in trace['findings'] if f['id'] == finding['id']]
        detail = json.dumps(row, ensure_ascii=False, default=str)
        self.assertEqual(row['status'], 'resolved', detail)
        self.assertEqual(row['source_receipt'], failed, detail)          # the failing evidence stays linked
        self.assertEqual(row['from_run'], {'link': 'known', 'run_id': runs[0]['run_id']}, detail)
        self.assertEqual(row['repair']['link'], 'known', detail)         # assignment
        self.assertEqual(row['output']['link'], 'known', detail)         # repair output
        self.assertEqual((row['recheck']['link'], row['recheck']['receipt'], row['recheck']['closed']), ('known', green, True), detail)
        self.assertEqual(row['recheck']['request'], {'link': 'known', 'request_id': runs[1]['request_id']}, detail)

    def test_no_pass_is_invented_when_the_recheck_failed(self):
        checker = CandidateChecker(self.ledger, 'P1')
        self.step()
        self.assertEqual(self.verify('C', checker)['result'], 'fail')
        [finding] = findings.list_findings(self.ledger, 'P1', open_only=True)
        trace = tracking_work.review_trace(self.ledger, 'P1')
        [row] = [f for f in trace['findings'] if f['id'] == finding['id']]
        self.assertEqual(row['status'], 'open')
        self.assertEqual(row['recheck']['link'], 'unknown')


class CodingTrace(Trace, CodingCase):
    pass


class DocumentDataTrace(Trace, DocumentDataCase):
    pass
