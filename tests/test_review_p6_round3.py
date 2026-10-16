"""OneCrew P6 round 3 (61cb8f0 follow-up): the four wiring gaps Codex flagged on the frozen 61cb8f0, each converted from a
reproduction probe into a REAL-CORE test that REQUIRES the correct behaviour. Every test drives the real runtime
(Owned.run / Owned._tool / the public resume path) with a scripted model (a synthetic reviewer and worker); none reimplements
handler logic in a test helper (last round's rejected _worker_receipt mirrored the handler and did not exercise the real path).

  LC02  an invalid-shape response (accepted a non-bool, e.g. the string "false") must not carry acceptance by truthiness and
        must not lose the rejection conclusion.
  LC05  record_rejection and keep_note _put faults route through the SAME obligation contract: a fault leaves a durable
        unprocessed obligation that survives public resume and blocks acceptance.
  LC06  (a) the caller migrates a STANDALONE unrecorded-count marker; (b) a legacy cut finding whose tail cannot be recovered
        becomes a missing obligation; (c) the migration is retry-safe (idempotent, no repeated ids / no double obligation).
  LC08  one full-text source and the string virtual id / offset survive receipt -> worker prompt -> next, so the by-id
        continuation reaches the whole finding byte-for-byte and never reports eof before it is exhausted.

The model responses are scripted; the tools, core, paging, checkpoint and the obligation/register machinery are the product's.
Nothing here is a real-model run. Fixtures are temporary; no task, host or ledger of the machine is used."""
import json
import sys
import unittest
from unittest.mock import patch

from onecrew import review_evidence as re
from onecrew.ledger import canonical
from onecrew.owned import Owned
from tests.test_review_lifecycle import LifecycleBase, Reviewer, LONG_FINDING, LONG_NOTE, FIRST_MARK, SECOND_MARK
from tests.test_work_contract import action


def obligations(state):
    return (state.get('review_register') or {}).get('unprocessed') or []


def open_obligations(state):
    return [o for o in obligations(state) if o.get('status') == 'open']


class LC02InvalidShapeTests(LifecycleBase):
    """R5 / LC02. A response whose `accepted` is not a real bool (the string "false") is an INVALID schema. Validation rejects
    the shape; the fix must ALSO preserve the rejection conclusion the response carried, so a retry cannot complete with the
    defect forgotten. The common mechanism (accepted is True) decides it, not a special-case for the literal "false"."""

    def test_an_invalid_accepted_type_keeps_the_rejection_and_does_not_complete(self):
        class BadType(Reviewer):
            def decide(self, v, ctx):
                result = super().decide(v, ctx)
                if v['kind'] == 'reject_feedback':
                    result['accepted'] = 'false'  # a STRING: invalid schema, truthy
                return result
        worker, task = self.start(self.candidate_script(finishes=2), BadType(
            {'kind': 'reject_feedback', 'feedback': 'Unfixed defect B must be fixed.'}, {'kind': 'accept'}))
        state = self.drive(worker, task, until=lambda s: s['phase'] in ('blocked', 'completed'))
        self.assertNotEqual(state['phase'], 'completed',
                            'RED-LC02: an invalid-shape accepted:"false" was read as acceptance and completed')
        self.assertTrue(re.open_findings(state) or open_obligations(state),
                        'the rejection conclusion must survive as an open finding or obligation')


class LC05PutObligationTests(LifecycleBase):
    """R4 / LC05. record_rejection and keep_note each call _put directly. A _put fault (text over MAX_TEXT, or a store that
    cannot be written) must leave a durable incomplete-processing obligation on the SAME contract record_round uses, so a
    public resume + a later generic accept cannot complete with the content silently dropped."""

    def test_a_feedback_only_rejection_whose_put_overflows_blocks_across_public_resume(self):
        worker, task = self.start(self.candidate_script(finishes=2), Reviewer(
            {'kind': 'reject_feedback', 'feedback': 'Unfixed independent defect: ' + 'x' * 700}, {'kind': 'accept'}))
        with patch.object(re, 'MAX_TEXT', 400):
            state = self.drive(worker, task)
        self.assertEqual(state['phase'], 'blocked', 'premise: the overflow blocks the first time')
        before = open_obligations(state)
        self.assertTrue(before, 'RED-LC05: the overflowing rejection left no durable obligation')
        # PUBLIC resume path (not an internal helper): a fresh runtime resumes the persisted job
        worker.runtime = Owned(self.ledger, worker)
        worker.runtime.resume(task)
        state = self.drive(worker, task, until=lambda s: s['phase'] in ('blocked', 'completed'))
        self.assertNotEqual(state['phase'], 'completed',
                            'RED-LC05: a generic accept completed after resume although a response could not be recorded')
        self.assertTrue(open_obligations(state), 'the obligation survives the public resume and still blocks')


class LC06LegacyMigrationTests(LifecycleBase):
    """R4 / LC06. The caller migrated only when review_findings/review_notes existed, so a checkpoint carrying ONLY the
    standalone unrecorded-count marker was never migrated and completed with the marker still set and no obligation. Three
    named branches, each through the real reload/resume path: (a) standalone marker, (b) legacy cut tail -> missing obligation,
    (c) migration fault/retry idempotence."""

    def test_a_standalone_unrecorded_marker_is_migrated_and_blocks(self):
        worker, task = self.start(self.candidate_script(finishes=1), Reviewer({'kind': 'accept'}))
        seq, state = worker.runtime.state(task)
        state['review_findings_unrecorded'] = 3  # a d5a0c43 checkpoint with ONLY the standalone marker
        worker.runtime.persist(task, seq, state)
        worker.runtime = Owned(self.ledger, worker)  # reload
        state = self.drive(worker, task, until=lambda s: s['phase'] in ('blocked', 'completed'))
        self.assertNotEqual(state['phase'], 'completed',
                            'RED-LC06a: a standalone marker was never migrated and the job completed')
        self.assertIsNone(state.get('review_findings_unrecorded'), 'the marker was migrated, not left standing')
        kinds = [o['kind'] for o in open_obligations(state)]
        self.assertIn('legacy_unrecorded', kinds, 'the marker became a durable missing obligation')
        self.assertTrue(all(o.get('missing') for o in open_obligations(state) if o['kind'] == 'legacy_unrecorded'))

    def test_a_legacy_cut_finding_tail_becomes_a_missing_obligation(self):
        # The migration helper is reached through the real finish gate (defence in depth): a stored acceptance carrying a
        # legacy cut finding resumes, the gate migrates it, and the cut tail blocks completion.
        worker, task = self.start(self.candidate_script(finishes=1), Reviewer({'kind': 'accept'}))
        seq, state = worker.runtime.state(task)
        state['review_findings'] = [{'id': 'RF1', 'status': 'open', 'round': 2, 'claim': 'c' * 1800, 'chars': 30000,
                                     'source': {'receipt': 0}}]  # chars > survived claim: the tail was cut
        worker.runtime.persist(task, seq, state)
        worker.runtime = Owned(self.ledger, worker)
        state = self.drive(worker, task, until=lambda s: s['phase'] in ('blocked', 'completed'))
        self.assertNotEqual(state['phase'], 'completed', 'RED-LC06b: a legacy cut finding completed with its tail lost')
        cut = [o for o in open_obligations(state) if o['kind'] == 'legacy_cut']
        self.assertTrue(cut, 'the cut tail must be a durable obligation')
        self.assertTrue(all(o.get('missing') for o in cut), 'the unrecoverable tail is reported missing, never posed as whole')

    def test_the_migration_is_retry_safe_and_idempotent(self):
        # adopt_legacy builds in full before touching the register and dedups obligations by norm: a second run (a resume after
        # an interrupted migration) repeats no id and adds no second obligation.
        from onecrew.review_evidence import adopt_legacy
        import hashlib

        class Store:
            def __init__(self): self.b = {}
            def blob(self, d):
                k = hashlib.sha256(d).hexdigest(); self.b[k] = bytes(d); return k
            def read_blob(self, k): return self.b[k]
        store = Store()
        legacy = {'id': 'RF1', 'status': 'open', 'round': 2, 'claim': 'c' * 1800, 'chars': 30000, 'source': {'receipt': 0}}
        state = {'review_findings': [dict(legacy)], 'review_findings_unrecorded': 2}
        adopt_legacy(state, store)
        after1 = canonical(state['review_register'])
        obl1 = len(open_obligations(state))
        ids1 = [f['id'] for f in state['review_register']['findings']]
        # a retry re-injects the same legacy state (as an interrupted run would see it) and migrates again
        state['review_findings'] = [dict(legacy)]
        state['review_findings_unrecorded'] = 2
        adopt_legacy(state, store)
        self.assertEqual([f['id'] for f in state['review_register']['findings']], ids1, 'no id repeated on retry')
        self.assertEqual(len(open_obligations(state)), obl1, 'no obligation duplicated on retry')
        self.assertEqual(canonical(state['review_register']), after1, 'the register is identical after the idempotent retry')


class LC08FullTextAcrossTransportTests(LifecycleBase):
    """R6 / LC08. The receipt-of-a-finding handler pre-paged to PAGE_DEFAULT and stored the CUT page; _latest_result re-paged the
    cut copy (its total shrank, its next flipped to a numeric receipt) so the tail past the first page could never be reached.
    The fix keeps ONE full-text source and the string virtual id/offset across receipt -> worker prompt -> next. Driven through
    Owned.run and the real worker prompt (the worker follows the page `next` it is given), NOT a copied helper."""

    def _run(self, worker, task):
        with patch.object(re, 'RECEIPT_BYTES', 1000):  # the rejection receipt holds only the head: the worker must page the rest
            return self.drive(worker, task, steps=120)

    def test_the_worker_reads_the_whole_finding_including_the_tail_through_the_tool(self):
        tail = 'SECRET-TAIL-NEEDED-TO-FIX'
        claim = 'r0: ' + '0123456789' * 3000 + tail  # 30,029 chars; the tail is what the worker needs and must not be pre-seeded
        worker, task = self.start(
            self.candidate_script(finishes=1) + [action('receipt', index='RF1', field='claim', offset=0)],
            Reviewer({'kind': 'reject', 'findings': [claim]}))
        self._run(worker, task)
        pages = [x for x in worker.latest if x.get('action') == 'review_finding']
        delivered = [(x.get('result') or {}).get('claim', '') for x in pages]
        emitted = [p for x in pages for p in x.get('page') or [] if p.get('field') == 'claim']
        whole = ''.join(delivered)
        self.assertIn(tail, whole, 'RED-LC08: the tail past the first page never reached the worker')
        self.assertGreaterEqual(len(whole), len(claim),
                                'RED-LC08: fewer characters than the source were delivered (a cut copy was re-paged)')
        self.assertEqual(sorted(set(p['total'] for p in emitted)), [len(claim)],
                         'RED-LC08: page.total was the cut length, not the whole source')
        self.assertTrue(all(p['next']['arguments']['index'] == 'RF1' for p in emitted if p.get('next')),
                        'RED-LC08: the next cursor flipped to a numeric receipt and lost the by-id full source')
        self.assertTrue(emitted[-1].get('eof'), 'the last page is eof only when the source is genuinely exhausted')
        # eof is reported only AT the end: no earlier page claims eof while content remains
        self.assertFalse(any(p.get('eof') for p in emitted[:-1]), 'RED-LC08: eof was reported before the source was exhausted')


class CompositeFlowTests(LifecycleBase):
    """The mandatory composite flow (LC13 + LC08) through the real core, scripted model, temp repo: detect -> reject -> finish
    unchanged still NOT completed -> PUBLIC resume -> the worker retrieves the FULL finding text (including the tail) VIA THE
    TOOL (receipt by id + next; the tail is NOT pre-seeded into the worker script) -> the worker fixes using the tail -> runs the
    test -> the reviewer closes with evidence -> the core completes and hands over the fixed candidate. Plus: an unprocessed
    obligation must NEVER complete."""

    def _fix_with_tail(self, tail):
        """A scripted step: the worker has paged the finding to its end (worker.latest holds every page); it extracts the tail it
        was given THROUGH THE TOOL and writes a fix that embeds it, then runs the check. Nothing here pre-knows the tail."""
        import hashlib
        from onecrew import work_tools as wt
        from tests.test_review_lifecycle import PATH, check_script

        def step(w):
            seen = ''.join((x.get('result') or {}).get('claim', '') for x in w.latest if x.get('action') == 'review_finding')
            assert tail in seen, 'the worker must have obtained the tail through the tool before fixing'
            data = (wt.ws_root(w.runtime.state(w.task)[1]) / PATH).read_bytes()
            new_mark = FIRST_MARK + '\n// ' + SECOND_MARK
            return action('edit', path=PATH, expected_sha256=hashlib.sha256(data).hexdigest(),
                          old='// ' + FIRST_MARK, new='// ' + new_mark)
        return step

    def test_detect_reject_resume_read_tail_via_tool_fix_close_complete(self):
        # LONG_FINDING is ~2,700 chars ending in KET-DUOI-CUA-LOI-DAI (its tail is what a 2,000-char cut loses). It is long enough
        # that RECEIPT_BYTES=1000 forces the worker to PAGE the finding (the tail is not in the head), and short enough that the
        # closing reviewer can still retrieve it whole within MAX_ROUNDS. The tail stands in for the content the worker needs.
        tail = 'K\u1ebeT-\u0110U\u00d4I-C\u1ee6A-L\u1ed6I-D\u00c0I'
        claim = 'r0: ' + LONG_FINDING
        assert tail in claim, 'premise: the tail is the end of the long finding'
        from tests.test_review_lifecycle import check_script, rewrite
        reviewer = Reviewer(
            {'kind': 'reject', 'findings': [claim]},                     # 1. detect + reject
            {'kind': 'accept'},                                          # 2. the resend reviewer accepts; the core must not
            {'kind': 'close', 'cite': 'run', 'retrieve': [('RF1', 'claim')],
             'how': 'the fix embeds the tail; receipt of the test run that checks the new marker'})  # 4-6. close on evidence
        script = (self.candidate_script(finishes=2)                      # finish twice unchanged (both must be refused)
                  + [action('receipt', index='RF1', field='claim', offset=0)]  # read the finding by id (pages via next to the tail)
                  + [self._fix_with_tail(tail),
                     rewrite('kiem_tra_tien.py', check_script(FIRST_MARK, SECOND_MARK)),
                     action('run', argv=[sys.executable, 'kiem_tra_tien.py'])]
                  + [action('finish', report='C1..C8: fixed using the retrieved tail; see the latest receipts.',
                            verification=self.verification())])
        worker, task = self.start(script, reviewer)
        with patch.object(re, 'RECEIPT_BYTES', 1000):
            state = self.drive(worker, task, until=lambda s: len(self.finishes(s)) >= 2, steps=200)
        self.assertEqual(len(self.finishes(state)), 2, 'two unchanged finishes')
        self.assertTrue(all(not f['successful'] for f in self.finishes(state)), 'both unchanged finishes were refused')
        # PUBLIC resume, then the worker reads the tail via the tool, fixes, and the reviewer closes on the run
        worker.runtime = Owned(self.ledger, worker)
        worker.runtime.resume(task)
        with patch.object(re, 'RECEIPT_BYTES', 1000):
            state = self.drive(worker, task, until=lambda s: s['phase'] == 'completed', steps=200)
        self.assertEqual(state['phase'], 'completed', str(state.get('message')))
        retrieved = ''.join((x.get('result') or {}).get('claim', '') for x in worker.latest if x.get('action') == 'review_finding')
        self.assertIn(tail, retrieved, 'the tail was obtained through the tool, not pre-seeded')
        final = state['reviews'][-1]
        self.assertTrue(final['accepted'])
        self.assertEqual([(f['id'], f['status']) for f in final['findings']], [('RF1', 'resolved')])


if __name__ == '__main__':
    unittest.main(verbosity=2)