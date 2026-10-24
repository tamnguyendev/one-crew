"""Handoff reuses only authenticated, still-current candidate verification."""
import json
from unittest.mock import patch

from onecrew.common_handoff import handoff
from onecrew.v2.verifiers import command
from tests.test_wf_candidate_handoff import CandidateFixture


class HandoffReuseTests(CandidateFixture):
    def complete(self):
        self.revise(self.definition()); self.step()
        self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)
        self.step()
        result = self.engine.verify(self.ledger, 'P1', 'I', self.production_checker)
        return self.engine.state(self.ledger, 'P1')['nodes']['I']['verification_receipt'], result

    def test_exact_current_verification_delivers_without_executing_checks_again(self):
        previous, _ = self.complete()
        with patch.object(command, 'run', side_effect=AssertionError('current check must be reused')):
            result = handoff(self.ledger, 'P1', control=self.control)
        proof = json.loads(self.store.read_blob(result['receipt']))
        self.assertEqual(proof['checks']['reuse_basis']['source_receipt'], previous)
        self.assertTrue(self.engine.root_ready(self.ledger, 'P1', result['artifact']))
        self.assertEqual((self.root / 'a.txt').read_text(), 'candidate\n')

    def test_observed_environment_change_runs_the_original_check_again(self):
        self.complete()
        environment = command.verifier_env(self.root)
        environment['WF_REUSE_COUNTEREXAMPLE'] = 'changed'
        with patch.object(command, 'verifier_env', return_value=environment), patch.object(command, 'run', wraps=command.run) as run:
            result = handoff(self.ledger, 'P1', control=self.control)
        self.assertEqual(run.call_count, 1)
        proof = json.loads(self.store.read_blob(result['receipt']))
        self.assertNotIn('reuse_basis', proof['checks'])
        self.assertEqual(proof['checks']['checks'][0]['result'], 'pass')
