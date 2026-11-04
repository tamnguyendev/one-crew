"""T36b [E11] through the real CLI, after the Codex review of 9aca8be (P1 W32a).

`onecrew estimate additional --file` with nodes=["A"], still_running=["B"]: A is held, B goes on. An unknown node or a wrong type is refused
before anything is written (no work.additional, no request, no unknown). A hold that fails midway is reported as a failure (exit 2), never as
"held"; the retry completes idempotently (one work.additional, one U2 request, one unknown). Resending the same work adds nothing. Resolving
the unknown releases the dependents but grants nothing: an edit outside the approved scope is still out of authority (U2) and the U2 request
stays pending until the owner answers it.
"""
import contextlib
import io
import json
import os
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import LedgerError
from onecrew.v2 import authority, estimates, plan, runtime_unknowns
import tests.test_wf_t36b_additional_u2 as base


class AdditionalCliTests(base.AdditionalWorkTests):
    for _name in [n for n in dir(base.AdditionalWorkTests) if n.startswith('test_')]:
        locals()[_name] = None
    del _name

    def cli(self, body):
        path = Path(self.temp.name) / 'additional.json'
        path.write_text(json.dumps(body), encoding='utf-8')
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = estimates.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'estimate', 'additional', 'P1', '--file', str(path)])
        return code, json.loads(out.getvalue())

    def body(self, **extra):
        return dict({'key': 'db-grant', 'category': 'outside_authority', 'reason': 'needs a write on the shared DB repo outside the scope',
                     'acceptance': ['O1'], 'execution_seconds': [3600, 7200], 'evidence': ['a.txt:1'], 'nodes': ['A'], 'still_running': ['B']}, **extra)

    def counts(self):
        kinds = self.kinds()
        return {'additional': kinds.count('work.additional'), 'requests': len(self.ledger.requests(self.task)),
                'unknowns': len([u for u in runtime_unknowns.read(self.ledger, 'P1') if u['state'] == 'open'])}

    def test_cli_passes_nodes_and_still_running_so_a_is_held_and_b_runs(self):
        code, result = self.cli(self.body())
        self.assertEqual(code, 0, result)
        self.assertEqual(result['u2']['held_nodes'], ['A']); self.assertEqual(result['u2']['unknown']['state'], 'open')
        view = self.engine.state(self.ledger, 'P1')
        self.assertEqual(set(view['unknown_blockers']), {'A'})
        self.assertEqual([n['id'] for n in self.engine.ready(self.ledger, 'P1')], ['B'])
        self.assertEqual(self.step()['node'], 'B')
        self.assertEqual(self.counts(), {'additional': 1, 'requests': 1, 'unknowns': 1})

    def test_an_unknown_node_or_a_wrong_type_is_refused_before_any_write(self):
        before = self.counts()
        for bad in (self.body(nodes=['Z']), self.body(nodes='A'), self.body(still_running=['Q']), self.body(nodes=[1])):
            code, result = self.cli(bad)
            self.assertEqual(code, 2, result); self.assertIn('error', result)
            self.assertEqual(self.counts(), before, bad)

    def test_a_failed_hold_is_a_failure_not_a_success_and_the_retry_completes_once(self):
        with patch.object(runtime_unknowns, 'open_unknown', side_effect=LedgerError('fixture: the hold could not be written')):
            code, result = self.cli(self.body())
        self.assertEqual(code, 2, result); self.assertIn('hold could not be written', result['error'])
        self.assertEqual(self.engine.state(self.ledger, 'P1')['unknown_blockers'], {})
        code, result = self.cli(self.body())                                                        # retry
        self.assertEqual(code, 0, result)
        self.assertEqual(self.counts(), {'additional': 1, 'requests': 1, 'unknowns': 1})
        self.assertEqual(set(self.engine.state(self.ledger, 'P1')['unknown_blockers']), {'A'})
        code, again = self.cli(self.body())                                                         # resend: nothing doubles
        self.assertEqual(code, 0); self.assertEqual(again['u2']['request'], result['u2']['request'])
        self.assertEqual(self.counts(), {'additional': 1, 'requests': 1, 'unknowns': 1})

    def test_resolving_the_unknown_grants_nothing(self):
        code, result = self.cli(self.body())
        self.assertEqual(code, 0, result)
        actor = os.environ.pop('ONECREW_ACTOR', None)
        try:
            runtime_unknowns.resolve(self.ledger, 'P1', 'additional-db-grant', by='owner', evidence='a.txt:1', answer='Owner will amend; for now the branch may continue inside the scope')
        finally:
            if actor is not None: os.environ['ONECREW_ACTOR'] = actor
        self.assertEqual(self.engine.state(self.ledger, 'P1')['unknown_blockers'], {})
        with self.ledger.transaction() as conn:
            state = plan.anchor_events(self.ledger, conn, 'P1')
            contract, sha = plan.load(self.ledger, state, state['approved']['revision'])
        decision = authority.decide(contract, {'kind': 'write', 'paths': ['shared-db/schema.sql']})
        self.assertFalse(decision['in_authority']); self.assertEqual(decision['class'], 'U2')             # the grant did not move
        self.assertEqual(plan.show(self.ledger, 'P1')['sha'], sha)
        self.assertEqual(self.ledger.request(result['u2']['request'])['state'], 'pending')              # the U2 still waits for the owner
