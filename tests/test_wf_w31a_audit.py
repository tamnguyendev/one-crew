"""W31a audit counter-examples (T27): an open unknown of a new root is recorded with affected and required_by at proposal.

`plan propose` with an open unknown that has neither field was accepted, so the 'recorded at proposal' clause was optional. New (plan-ns)
roots now refuse it; a closed unknown needs neither; an old revision on disk still loads (reads never re-validate).
"""
import json

from onecrew.ledger import LedgerError
from onecrew.v2 import contract as contracts, plan as plans
from tests.test_v2_l3 import Step0, step0_json


def bare(*ids):
    value = step0_json(size='S', unknowns=list(ids))
    for unknown in value['understanding']['unknowns']:
        unknown.pop('affected', None); unknown.pop('required_by', None)
    return value


class UnknownScopeAtProposalTests(Step0):
    def test_an_open_unknown_without_affected_and_required_by_is_refused_at_propose(self):
        with self.assertRaises(LedgerError) as caught: plans.propose(self.ledger, 'P1', bare('U1'), 'claude')
        self.assertIn('affected', str(caught.exception)); self.assertIn('required_by', str(caught.exception))
        with self.ledger.transaction() as conn: self.assertIsNone(plans.derive(self.ledger, conn, 'P1'))   # no anchor at all: a refused proposal leaves nothing (round 5)
        self.assertFalse(contracts.revision_path(self.ledger, 'plan-ns:P1', 1).exists())
        fixed = bare('U1'); fixed['understanding']['unknowns'][0].update(affected=['O1'], required_by='approval')
        plans.propose(self.ledger, 'P1', fixed, 'claude')                                    # the scoped proposal then goes through
        with self.ledger.transaction() as conn: self.assertEqual(plans.derive(self.ledger, conn, 'P1')['latest'], 1)

    def test_a_scoped_open_unknown_and_a_closed_unknown_are_accepted(self):
        value = bare('U1'); value['understanding']['unknowns'][0].update(affected=['O1'], required_by='approval')
        view = plans.propose(self.ledger, 'P1', value, 'claude')
        self.assertEqual(view['contract']['understanding']['unknowns'][0]['required_by'], 'approval')
        closed = bare('U1'); closed['understanding']['unknowns'][0].update(status='closed', closed_by='doc', evidence='x/y.py:1')
        plans.propose(self.ledger, 'P2', closed, 'claude')

    def test_an_amend_adding_an_unscoped_open_unknown_is_refused(self):
        plans.propose(self.ledger, 'P1', step0_json(size='S'), 'claude')
        with self.assertRaises(LedgerError): plans.amend(self.ledger, 'P1', bare('U9'), 'add an unknown', 'claude')

    def test_an_old_revision_with_an_unscoped_unknown_still_loads_and_can_be_amended(self):
        """Legacy: a revision written before the rule (simulated on disk) still loads, and an amend that leaves its unknown unchanged passes."""
        value = step0_json(size='S'); plans.propose(self.ledger, 'P1', value, 'claude')
        path = contracts.revision_path(self.ledger, 'plan-ns:P1', 1)
        document = json.loads(path.read_text(encoding='utf-8'))
        legacy = contracts.validate(bare('U1'))
        from onecrew.ledger import content_hash
        document['contract'], document['content_sha'] = legacy, content_hash(legacy)
        path.write_text(json.dumps(document), encoding='utf-8')
        self.assertEqual(contracts.read_revision(self.ledger, 'plan-ns:P1', 1)[0]['understanding']['unknowns'][0]['id'], 'U1')
        again = bare('U1'); again['title'] = 'Sample, reworded'
        contracts.require_unknown_scope(contracts.validate(again), legacy)            # the unchanged legacy unknown is left as it was
