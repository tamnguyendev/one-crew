"""W15 evidence: T01 (a decision and a review in flight on A1/R1 while R2/A2 is written) and T04b E6 (the diff the reviewer receives
lists only the snapshot's files).

T01 runs on the real engine with the rule-based decision layer (tests.test_wf_review_dispatch fixture, light policy); T04b E6 runs the real
reviewer verifier through the native CLI producer (tests.test_wf_review_snapshot_integration fixture). Reviewers/producers are explicit fixtures.
"""
import copy
import json
import re
from unittest.mock import patch

from onecrew.ledger import LedgerError
from onecrew.v2 import review_dispatch
from onecrew.v2.verifiers import reviewer
import tests.test_wf_review_dispatch as dispatch
import tests.test_wf_review_snapshot_integration as snapshot
from tests.test_v2_reviewer import answer, row


class T01InFlightTests(dispatch.ReviewDispatchTests):
    for _name in [n for n in dir(dispatch.ReviewDispatchTests) if n.startswith('test_')]:
        locals()[_name] = None
    del _name

    def policy_records(self):
        return [p for k, p in self.events() if k == 'decision.recorded' and p['subject']['component'] == 'review_policy']

    def execute(self, ledger, control, task, item, attempt):
        # each attempt yields its own snapshot (the base fixture executor is deterministic per node, so A2 would equal A1)
        control.launched(attempt['id'], attempt['generation'], {'fixture': True})
        artifact = self.store.blob(('artifact-' + item['id'] + '-' + attempt['id']).encode())
        receipt = self.store.blob(('executor-' + item['id'] + '-' + attempt['id']).encode())
        control.finish(attempt['id'], attempt['generation'], {'fixture': True, 'artifact': artifact})
        return {'artifact': artifact, 'receipt': receipt}

    def test_t01_e1_to_e5_results_of_a1_r1_stay_keyed_stale_and_never_carry_to_a2_r2(self):
        """W15 / T01 E1-E5: a rule decision (SKIP of the optional review) and the required review of C are in flight on A1/R1; the
        acceptance of C changes (R2) before the checker answers. E1: both results carry the key (A1, R1) and are stale for the
        new input. E2: C needs a new decision/review. E3/E4: no SKIP, pass or verified state is applied to A2/R2 from the old results.
        E5: both A1/R1 records are still in the ledger."""
        self.step()
        a1 = self.engine.state(self.ledger, 'P1')['nodes']['C']['artifact']
        skip = self.optional()                                                         # the rule decision on A1/R1
        self.assertEqual(skip['decision']['action'], 'SKIP')
        skip_validity = skip['decision']['validity']
        old_key = skip['decision']['record']['key']
        self.assertEqual(skip_validity['artifact_sha'], a1)                            # [E1] key (A1, R1)
        revision_one = skip_validity['revision']
        records_before = self.policy_records()

        def review_in_flight(item, artifact):
            changed = copy.deepcopy(self.nodes)
            changed[0]['goal'] = 'Revised acceptance written while the review runs'
            changed[0]['output'] = ['Revised evidence for O1']
            self.revise(changed)                                                       # R2 is written now
            return self.checker(item, artifact)                                        # the review of A1/R1 answers: pass
        with self.assertRaisesRegex(LedgerError, 'retained without verification'):
            self.verify('C', review_in_flight)

        retained = [p for k, p in self.events() if k == 'node.result_retained']
        self.assertEqual(len(retained), 1)                                             # [E1] the old result is kept, keyed to the old input
        self.assertEqual((retained[0]['internal_revision'], retained[0]['generation']), (1, 0))
        self.assertFalse(retained[0]['grants_delivery'])
        self.store.read_blob(retained[0]['receipt'])                                   # [E5] the evidence is still readable
        after = self.engine.state(self.ledger, 'P1')['nodes']['C']
        self.assertEqual((after['phase'], after['state'], after['artifact']), ('pending', None, None))   # [E2] needs a new run
        self.assertEqual(after['generation'], 1)
        self.assertNotIn('node.verification', self.kinds())                            # [E3] [E4] no pass from the old result
        self.assertFalse(self.engine.verification_ready(self.ledger, 'P1'))

        current = self.optional()                                                      # [E1] stale: the same question on the new input
        self.assertEqual(current['decision']['action'], 'DEFER')                       # [E2] a new decision is needed, not SKIP
        self.assertNotEqual(current['decision']['record']['key'], old_key)
        self.assertNotEqual(current['decision']['validity']['input_sha'], skip_validity['input_sha'])
        self.assertNotEqual(current['decision']['validity']['artifact_sha'], a1)
        self.assertFalse(current['decision']['cached'])
        required = review_dispatch.required(self.ledger, 'P1', 'C', ['check-C'])
        self.assertEqual(required['action'], 'DEFER')
        self.assertNotEqual(required['validity']['input_sha'], skip_validity['input_sha'])

        self.step()                                                                    # A2 under R2
        a2 = self.engine.state(self.ledger, 'P1')['nodes']['C']
        self.assertEqual(a2['state'], 'produced')                                      # [E4] not verified by the old pass
        fresh = review_dispatch.required(self.ledger, 'P1', 'C', ['check-C'])
        self.assertEqual(fresh['action'], 'REVIEW')
        self.assertFalse(fresh['cached'])
        self.assertEqual(fresh['validity']['artifact_sha'], a2['artifact'])
        self.assertNotEqual(a2['artifact'], a1)
        new_skip = self.optional()
        self.assertNotEqual(new_skip['decision']['record']['key'], old_key)            # [E3] never the old SKIP record
        self.assertFalse(new_skip['decision']['cached'])
        self.assertNotIn('node.verification', self.kinds())

        records_after = self.policy_records()                                          # [E5] nothing lost
        self.assertGreaterEqual(len(records_after), len(records_before))
        kept = [r for r in records_after if r['key'] == old_key]
        self.assertEqual(len(kept), 1)
        self.assertEqual((kept[0]['validity']['artifact_sha'], kept[0]['validity']['revision'], kept[0]['validity']['action']),
                         (a1, revision_one, 'SKIP'))
        self.assertTrue(any(k == 'node.result_retained' for k in self.kinds()))


def files_in(diff):
    return re.findall(r'^diff --git a/(\S+) b/', diff, re.M)


class T04bFileListTests(snapshot.ReviewSnapshotIntegrationTests):
    for _name in [n for n in dir(snapshot.ReviewSnapshotIntegrationTests) if n.startswith('test_')]:
        locals()[_name] = None
    del _name

    def factory(self, control, provider):
        """As the base worker, except that the second cut of C also writes b.txt (a file changed only in A2)."""
        case = self

        class Worker:
            def capability(self):
                return {'provider': provider, 'mode': 'fixture-tools-disabled'}

            def run(self, attempt, prompt, schema, profile):
                self.node = 'X' if ('"id":"X"' in prompt or '"id": "X"' in prompt) else 'C'
                control.launched(attempt['id'], attempt['generation'], {'fixture': True})
                control.finish(attempt['id'], attempt['generation'], {'exit_code': 0})

            def result(self, attempt):
                if self.node == 'X':
                    files = [{'path': 'b.txt', 'content': snapshot.B_CANDIDATE}]
                elif getattr(case, 'second_cut', False):
                    files = [{'path': 'a.txt', 'content': snapshot.A2_CANDIDATE}, {'path': 'b.txt', 'content': 'b only in a2' + chr(10)}]
                else:
                    files = [{'path': 'a.txt', 'content': snapshot.A_CANDIDATE}]
                return {'summary': 'producer ' + self.node, 'files': files, 'backlog': []}, []
        return Worker()

    def diff_files(self, result):
        rows = {r['id']: r for r in result['observed']['checks']}
        wrapper = json.loads(self.store.read_blob(rows['M2']['evidence']))
        proof = json.loads(self.store.read_blob(wrapper['reviewer_receipt']))
        return files_in(self.store.read_blob(proof['diff']).decode('utf-8')), proof

    def test_t04b_e6_the_diff_the_reviewer_receives_lists_only_the_snapshot_files(self):
        """W15 / T04b E6: while the review of A1 runs, independent node X produces b.txt and the project gains a new file and a changed
        a.txt; the file list of the diff R receives is exactly A1's (a.txt) and never includes the later files. The next cut A2 of C
        (which also changes b.txt) is reviewed with its own diff, which lists b.txt; A1's receipt keeps its own list."""
        definition = self.definition()
        for item in definition:
            item['executor'] = dict(self.producer)
        self.revise(definition)
        seen = {}

        def first(prompt, config, env, scratch, limit):
            seen['prompt'] = prompt
            seen['x'] = self.step_cli('X')
            (self.root / 'a.txt').write_text(snapshot.LATER)
            (self.root / 'later_only.txt').write_text('created after the snapshot' + chr(10))
            return answer(row('R1')), {}, None, False, b'fixture'
        with patch('onecrew.artifact_provider_core.make_worker', side_effect=self.factory):
            self.step_cli('C')
            with patch.object(reviewer, 'call', side_effect=first):
                result = self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)
        self.assertEqual(result['result'], 'pass', result)
        a1_files, a1_proof = self.diff_files(result)
        self.assertEqual(a1_files, ['a.txt'])
        for later in ('b.txt', 'later_only.txt'):
            self.assertNotIn(later, a1_files)
            self.assertNotIn(later, seen['prompt'])
        self.assertEqual(seen['x']['node'], 'X')

        definition = self.definition()
        for item in definition:
            item['executor'] = dict(self.producer)
        definition[0]['goal'] = 'Produce evidence for O1, second cut'
        definition[0]['write'] = ['a.txt', 'b.txt']
        self.revise(definition, reason='Second cut also changes b.txt')
        self.second_cut = True
        prompts = []

        def second(prompt, config, env, scratch, limit):
            prompts.append(prompt)
            return answer(row('R1')), {}, None, False, b'fixture'
        with patch('onecrew.artifact_provider_core.make_worker', side_effect=self.factory):
            self.step_cli('C')
            with patch.object(reviewer, 'call', side_effect=second):
                again = self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)
        self.assertEqual(again['result'], 'pass', again)
        a2_files, a2_proof = self.diff_files(again)
        self.assertIn('a.txt', a2_files)
        self.assertIn('b.txt', a2_files)                                               # the file only A2 changed is in A2's diff...
        self.assertNotIn('later_only.txt', a2_files)
        self.assertNotEqual(a2_proof['artifact_sha'], a1_proof['artifact_sha'])
        self.assertEqual(files_in(self.store.read_blob(a1_proof['diff']).decode('utf-8')), ['a.txt'])   # ...and never in A1's
        self.assertEqual(len(prompts), 1)
