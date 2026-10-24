"""Counterexamples for candidate verification reuse (W07/W08 law on the node receipt path).

A handoff may reuse a node's own verification only when every retained proof is the
approved check, on this candidate tree, under this contract, with the binding the
checker observed. Each test forges ONE field of an otherwise genuine receipt and
expects reuse to be refused; the unforged receipt is the positive control.
"""
import copy
import json

from onecrew import common_verification as cv
from onecrew.ledger import canonical
from onecrew.v2 import internal_plan as ip
from tests.test_wf_candidate_handoff import CandidateFixture


class ReuseCounterexampleTests(CandidateFixture):
    def complete(self):
        self.revise(self.definition()); self.step()
        self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)
        self.step()
        self.engine.verify(self.ledger, 'P1', 'I', self.production_checker)
        view = self.engine.state(self.ledger, 'P1')
        with self.ledger.transaction() as conn:
            root, contract, sha = ip.context(self.ledger, conn, 'P1', 'sequential-engine')
        self.view, self.sha, self.contract = view, sha, contract
        self.item = next(n for n in view['definition']['nodes'] if n['id'] == 'I')
        self.record = view['nodes']['I']
        self.receipt = json.loads(self.store.read_blob(self.record['verification_receipt']))
        self.observed = self.receipt['observed']

    def reuse(self, receipt_body, view=None):
        """Run the reuse law on a (possibly forged) receipt the engine points at."""
        blob = self.store.blob(canonical(receipt_body).encode())
        view = copy.deepcopy(view or self.view)
        view['nodes']['I']['verification_receipt'] = blob
        return cv._reuse(self.ledger, view, self.item, self.record['artifact'], blob,
                         self.observed['candidate_tree'], self.observed['evidence_binding'],
                         self.sha, {m['id']: m for m in self.contract['milestones']})

    def forged(self, wrapper_edit=None, proof_edit=None, index=0):
        """Copy the receipt, rewrite one retained wrapper and/or its proof, return the new receipt body."""
        body = copy.deepcopy(self.receipt)
        row = body['observed']['checks'][index]
        wrapper = json.loads(self.store.read_blob(row['evidence']))
        field = {'candidate-command-check': 'command_receipt', 'candidate-adapter-check': 'adapter_receipt',
                 'candidate-reviewer-check': 'reviewer_receipt'}[wrapper['kind']]
        proof = json.loads(self.store.read_blob(wrapper[field]))
        if proof_edit:
            proof_edit(proof)
            wrapper[field] = self.store.blob(canonical(proof).encode())
        if wrapper_edit:
            wrapper_edit(wrapper)
        row['evidence'] = self.store.blob(canonical(wrapper).encode())
        return body

    def test_genuine_receipt_is_reused_positive_control(self):
        self.complete()
        result = self.reuse(self.receipt)
        self.assertIsNotNone(result)
        self.assertEqual(result['reuse_basis']['source_receipt'], self.record['verification_receipt'])

    def test_receipt_of_another_command_cannot_stand_in_for_the_approved_check(self):
        self.complete()
        approved = self.contract['milestones'][0]['verifier']['config']['argv']
        def noop(proof):
            proof['argv'] = [approved[0], '-c', 'pass']   # a passing receipt, but not the approved command
        self.assertIsNone(self.reuse(self.forged(proof_edit=noop)))

    def test_receipt_of_another_milestone_is_refused(self):
        self.complete()
        def other(proof): proof['milestone'] = 'M2'
        self.assertIsNone(self.reuse(self.forged(proof_edit=other)))

    def test_receipt_under_another_contract_sha_or_revision_is_refused(self):
        self.complete()
        def sha(proof): proof['plan_sha'] = '0' * 64
        def rev(proof): proof['revision'] = proof['revision'] + 1
        self.assertIsNone(self.reuse(self.forged(proof_edit=sha)))
        self.assertIsNone(self.reuse(self.forged(proof_edit=rev)))

    def test_wrapper_binding_must_equal_the_observed_binding(self):
        self.complete()
        def drift(wrapper):
            wrapper['evidence_binding'] = dict(wrapper['evidence_binding'], configuration='f' * 64)
        self.assertIsNone(self.reuse(self.forged(wrapper_edit=drift)))

    def test_proof_kind_must_match_the_approved_verifier_type(self):
        self.complete()
        def relabel(wrapper):
            # a wrapper that claims an adapter check for a command milestone, pointing at the same passing proof
            wrapper['kind'] = 'candidate-adapter-check'
            wrapper['adapter_receipt'] = wrapper.pop('command_receipt')
        self.assertIsNone(self.reuse(self.forged(wrapper_edit=relabel)))
        def mislabeled_proof(proof): proof['kind'] = 'reviewer-receipt'
        self.assertIsNone(self.reuse(self.forged(proof_edit=mislabeled_proof)))

    def test_effective_time_cap_may_only_shrink_within_the_approved_cap(self):
        self.complete()
        approved = self.contract['milestones'][0]['verifier']['config']['max_minutes']
        def over(wrapper): wrapper['effective_max_minutes'] = approved * 10
        def under(wrapper): wrapper['effective_max_minutes'] = approved / 2
        def zero(wrapper): wrapper['effective_max_minutes'] = 0
        self.assertIsNone(self.reuse(self.forged(wrapper_edit=over)))
        self.assertIsNone(self.reuse(self.forged(wrapper_edit=zero)))
        self.assertIsNotNone(self.reuse(self.forged(wrapper_edit=under)))

    def test_failed_proof_recorded_as_pass_is_refused(self):
        self.complete()
        def failed(proof): proof['exit_code'] = 1
        self.assertIsNone(self.reuse(self.forged(proof_edit=failed)))

    def test_proof_on_another_tree_is_refused(self):
        self.complete()
        def moved(proof): proof['artifact_sha'] = proof['artifact_sha_after'] = 'a' * 40
        self.assertIsNone(self.reuse(self.forged(proof_edit=moved)))
