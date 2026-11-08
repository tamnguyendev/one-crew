"""Job 9, revision 3 of the contract: a contract proposed before the owner-rules file exists, and without any new field, is exempt; once the file
exists (or the contract uses a new field) the gate is strict. This pins the exempt side."""
from unittest.mock import patch
import unittest

from onecrew.ledger import LedgerError
from onecrew.v2 import plan as plans
from onecrew.v2.verifiers import advisor
from test_v2_advisor import ORIGIN, size_m
from test_v2_l1 import Fixture, plan_json
from test_v2_l3 import reasons


class LegacyExemptionTests(Fixture):
    def setUp(self):
        super().setUp()
        # dev11: propose refuses these form reasons first (tests/test_dev11_propose_form.py). This class tests approve's own gate, which still
        # holds for a plan recorded before that check or changed by plan amend, so the plans here are written as before dev11.
        guard = patch('onecrew.v2.plan.refuse_form'); guard.start(); self.addCleanup(guard.stop)

    def test_a_legacy_size_s_contract_is_approved_without_origin_sources_or_advice(self):
        self.propose()
        self.assertEqual(plans.approve(self.ledger, 'P1', 'owner', 'said yes')['status'], 'approved')

    def test_a_legacy_size_m_contract_is_approved_without_advice_while_no_rules_file_exists(self):
        self.propose(value=size_m())
        self.assertEqual(plans.approve(self.ledger, 'P1', 'owner', 'said yes', choose='A')['status'], 'approved')

    def test_the_same_contracts_are_refused_once_the_rules_file_exists(self):
        advisor.init_rules(self.ledger)
        self.propose(value=size_m())
        with self.assertRaises(LedgerError) as caught: plans.approve(self.ledger, 'P1', 'owner', 'said yes', choose='A')
        self.assertEqual(reasons(caught.exception), ['origin_missing', 'item_without_source', 'advice_missing'])

    def test_one_new_field_makes_a_contract_strict_without_the_rules_file(self):
        self.propose(value=plan_json(origin=dict(ORIGIN)))
        with self.assertRaises(LedgerError) as caught: plans.approve(self.ledger, 'P1', 'owner', 'said yes')
        self.assertEqual(reasons(caught.exception), ['item_without_source'])


if __name__ == '__main__':
    unittest.main()
