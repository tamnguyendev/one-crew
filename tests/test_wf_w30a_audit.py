"""W30a audit counter-examples (T47a): a technical choice is decided silently only on a grant that resolves to the root's approved grant.

A choice that declares class 'technical' with any authority {'grant_id': 'x', 'revision': '1'} used to be decided and never shown. Now the
grant must be the approved root's grant (authority.grant_ref of the approved revision) and the root must declare an `authority` field;
otherwise the choice goes on the owner's card.
"""
from onecrew.v2 import authority, cards, plan as plans
from tests.test_v2_l3 import Step0, step0_json
from tests.test_wf_r01_card import SUBJECT, csv_choice, technical

GRANT = {'edit': True, 'self_decide': ['Q10']}


class GrantResolutionTests(Step0):
    def setUp(self):
        super().setUp()

    def anchor(self):
        with self.ledger.transaction() as conn:
            return plans.derive(self.ledger, conn, 'P1')

    def decisions(self):
        return [p for k, p in self.events('P1') if k == 'decision.recorded']

    def card_parts(self):
        state = self.anchor()
        shown = [r for r in self.ledger.requests(state['task_id']) if r['question']['action']['type'] == cards.KIND]
        return [p['id'] for p in shown[-1]['question']['action']['parameters']['card']['parts']] if shown else []

    def real_grant(self):
        state = self.anchor()
        contract, sha = plans.load(self.ledger, state, state['approved']['revision'])
        return authority.grant_ref(state['selector'], contract, state['approved']['sha'])

    def test_a_made_up_grant_is_shown_on_the_card_not_decided(self):
        self.propose('P1', step0_json(size='S', authority=GRANT))
        out = cards.present(self.ledger, 'P1', [csv_choice(), technical('T1', authority={'grant_id': 'x', 'revision': '1'})], SUBJECT)
        self.assertEqual(self.decisions(), []); self.assertEqual(out['escalated'], ['T1'])
        self.assertEqual(self.card_parts(), ['B1', 'T1'])

    def test_a_grant_of_an_unapproved_root_is_shown(self):
        self.propose('P1', step0_json(size='S', authority=GRANT))
        out = cards.present(self.ledger, 'P1', [technical('T1')], SUBJECT)
        self.assertEqual(self.decisions(), []); self.assertEqual(out['escalated'], ['T1']); self.assertEqual(self.card_parts(), ['T1'])

    def test_the_real_approved_grant_decides_silently(self):
        """Counter-example: the approved root's own grant still decides a technical choice without asking."""
        self.propose('P1', step0_json(size='S', authority=GRANT))
        plans.approve(self.ledger, 'P1', 'owner', 'said yes')
        out = cards.present(self.ledger, 'P1', [technical('T1', authority=self.real_grant())], SUBJECT)
        self.assertIsNone(out['card']); self.assertEqual(out['escalated'], [])
        self.assertEqual([d['authority'] for d in self.decisions()], [self.real_grant()])

    def test_a_stale_revision_or_a_root_without_authority_is_shown(self):
        self.propose('P1', step0_json(size='S'))               # legacy root: no `authority` field delegates nothing
        plans.approve(self.ledger, 'P1', 'owner', 'said yes')
        out = cards.present(self.ledger, 'P1', [technical('T1', authority=self.real_grant())], SUBJECT)
        self.assertEqual(out['escalated'], ['T1']); self.assertEqual(self.decisions(), [])

    def test_a_wrong_revision_of_the_real_grant_id_is_shown(self):
        self.propose('P1', step0_json(size='S', authority=GRANT))
        plans.approve(self.ledger, 'P1', 'owner', 'said yes')
        forged = dict(self.real_grant(), revision='0' * 64)
        out = cards.present(self.ledger, 'P1', [technical('T1', authority=forged)], SUBJECT)
        self.assertEqual(out['escalated'], ['T1']); self.assertEqual(self.decisions(), [])
