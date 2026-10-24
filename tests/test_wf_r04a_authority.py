"""W02 (R04) - the authority grant of a root: T17a (own part), T16a (E1, E2, E3, E10, E11, E14, E15, E16; E4 is W04's), and the gate.

The "fake action" half only proves the authority interface (T17a/T16a: "Hanh dong ghi gia: chi chung minh quyen"). The gate half runs the real
dispatch path (owned_intake.submit -> solution_gate.check -> gate.require_plan) on a temp ledger.
Mutants ("phan chung") are passed to the same assertion helpers; each helper must fail on its mutant.
"""
import hashlib
import json
import os
import unittest
from unittest.mock import patch

from onecrew import solution_gate
from onecrew.ledger import LedgerError
from onecrew.owned_intake import submit
from onecrew.v2 import authority, contract as contracts, gate, lint, plan as plans

from tests.test_v2_l1 import Fixture, plan_json

ALL_Q = list(authority.Q_IDS)
AUTH = {'edit': True, 'commands': True, 'local_branches': ['wf/x'], 'branch_at': 'pinned_head', 'apply_to_project': False,
        'edit_tests': False, 'unconfined_commands': False, 'granted_actions': ['activate_rule:suggest'], 'auto_accept': [], 'self_decide': ALL_Q}
OWNED = ['a.txt', 'src/']
CTX = {'remaining_calls': 40, 'remaining_seconds': 3600, 'deadline': '2026-10-30T10:00:00+00:00'}

Q_ACTIONS = {
    'Q1': {'q': 'Q1', 'nodes': ['N1'], 'acceptance_changed': False, 'cost': {'calls': 3}},
    'Q2': {'q': 'Q2', 'nodes': ['N2'], 'eligible': True},
    'Q3': {'q': 'Q3', 'nodes': ['N2'], 'paths': ['src/a.py']},
    'Q4': {'q': 'Q4', 'nodes': ['N2'], 'weakens': False, 'provenance': 'added from A1 by OneCrew', 'paths': ['src/test.py'], 'cost': {'calls': 0, 'seconds': 1}},
    'Q5': {'q': 'Q5', 'nodes': ['N2'], 'repairs_used': 1, 'repairs_max': 3, 'cost': {'calls': 2}},
    'Q6': {'q': 'Q6', 'nodes': ['N2'], 'mandatory': False},
    'Q7': {'q': 'Q7', 'nodes': ['N2'], 'configured': True, 'within_limit': True, 'pinned': False},
    'Q8': {'q': 'Q8', 'nodes': ['N3']},
    'Q9': {'q': 'Q9', 'nodes': ['N2'], 'evidence': ['receipt-1'], 'artifact_matches': True},
    'Q10': {'q': 'Q10'},
    'Q11': {'q': 'Q11', 'rule_kind': 'suggest'},
    'Q12': {'q': 'Q12', 'nodes': ['N2'], 'node_state': 'verified'},
}
WRITE_OUT = {'kind': 'write', 'paths': ['secret/x.txt']}
WRITE_IN = {'kind': 'write', 'paths': ['src/new.py']}
OVER_BUDGET = {'kind': 'spend', 'calls': 50}
LATER_DEADLINE = {'kind': 'deadline', 'new_deadline': '2026-11-30T10:00:00+00:00'}


def root_contract(**authority_changes):
    return contracts.validate(plan_json(scope={'owned': OWNED}, authority=dict(AUTH, **authority_changes)))


def action(q):
    return dict(Q_ACTIONS[q], kind='decision')


# ---- assertion helpers, each run on the real function and on a mutant -------------------------------------------------------

def check_scope_classified(test, decide_fn):
    contract = root_contract()
    out = decide_fn(contract, WRITE_OUT, CTX)
    test.assertFalse(out['in_authority']); test.assertEqual(out['class'], 'U2')
    test.assertTrue(decide_fn(contract, WRITE_IN, CTX)['in_authority'])


def check_ceilings(test, decide_fn):
    contract = root_contract()
    for act in (OVER_BUDGET, LATER_DEADLINE):
        got = decide_fn(contract, act, CTX)
        test.assertFalse(got['in_authority'], act); test.assertEqual(got['class'], 'U2')
    test.assertTrue(decide_fn(contract, {'kind': 'spend', 'calls': 10}, CTX)['in_authority'])


def calls_covers(decide_fn):
    contract = root_contract()
    with patch.object(authority, 'covers', wraps=authority.covers) as spy:
        decide_fn(contract, WRITE_IN, CTX); decide_fn(contract, WRITE_OUT, CTX)
    return spy.call_count


class SchemaTests(Fixture):
    def test_the_grant_is_normalized_inside_the_contract_and_a_legacy_contract_is_unchanged(self):
        contract = root_contract()
        self.assertEqual(set(contract['authority']), set(authority.FIELDS))
        self.assertEqual(contract['authority']['self_decide'], ALL_Q)
        legacy = contracts.validate(plan_json())
        self.assertNotIn('authority', legacy)                                   # byte-identical to before W02
        self.assertEqual(contracts.validate(plan_json(authority={})) ['authority']['self_decide'], [])   # empty grant: nothing delegated
        self.assertNotEqual(authority.seal(contract), authority.seal(root_contract(edit_tests=True)))

    def test_forbidden_or_foreign_fields_are_refused(self):
        bad = [dict(AUTH, authority_class='A'), dict(AUTH, push=True), dict(AUTH, auto_accept=['small']), dict(AUTH, self_decide=['Q13']),
               dict(AUTH, edit=False, apply_to_project=True), dict(AUTH, commands=False, unconfined_commands=True),
               dict(AUTH, local_branches=['bad name']), dict(AUTH, granted_actions=['Not An Id']), dict(AUTH, edit='yes'), 'all']
        for value in bad:
            with self.assertRaises(LedgerError, msg=value) as caught: contracts.validate(plan_json(authority=value))
        with self.assertRaises(LedgerError) as caught: contracts.validate(plan_json(authority=dict(AUTH, authority_class='A')))
        self.assertTrue(str(caught.exception).startswith('authority'), str(caught.exception))

    def test_lint_names_a_foreign_field_with_the_authority_code(self):
        reasons = lint.lint(self.ledger, plan_json(authority=dict(AUTH, authority_class='A')))
        self.assertEqual([code for code, _ in reasons], ['authority'])
        self.assertEqual(lint.lint(self.ledger, plan_json(authority=AUTH, scope={'owned': OWNED})), [])

    def test_e15_the_table_is_code_and_the_schema_is_the_o2_list(self):
        def review():
            o2 = {'edit', 'commands', 'local_branches', 'branch_at', 'apply_to_project', 'edit_tests', 'unconfined_commands',
                  'granted_actions', 'self_decide', 'auto_accept'}
            return set(authority.FIELDS) == o2 and authority.Q_IDS == tuple(f'Q{n}' for n in range(1, 13)) and authority.U_IDS == ('U1', 'U2', 'U3', 'U4')
        self.assertTrue(review())
        with patch.object(authority, 'FIELDS', authority.FIELDS + ('authority_class',)):
            self.assertFalse(review(), 'the review must catch a schema that accepts a rank field')
        with patch.object(authority, 'U_IDS', authority.U_IDS + ('U5',)):
            self.assertFalse(review())


class DecisionTests(Fixture):
    def anchor(self, value=None):
        self.approved('P1', value or plan_json(scope={'owned': OWNED}, authority=AUTH))
        with self.ledger.transaction() as conn:
            state = plans.derive(self.ledger, conn, 'P1')
        contract, sha = plans.load(self.ledger, state)
        return state['task_id'], contract, sha

    def requests(self):
        with self.ledger.transaction() as conn:
            return conn.execute('SELECT COUNT(*) FROM requests').fetchone()[0]

    def decisions(self, task):
        return [e['payload'] for e in self.ledger.events(task) if e['kind'] == 'decision.recorded']

    def test_e1_e3_e10_all_twelve_decisions_are_in_authority_with_a_record_and_no_request(self):
        task, contract, sha = self.anchor(root_contract(edit_tests=True))
        before = self.requests()
        for q in ALL_Q:
            result, _ = authority.enforce(self.ledger, task, contract, action(q), name='P1', revision_sha=sha, ctx=CTX)
            self.assertTrue(result['in_authority'], (q, result)); self.assertIsNone(result['class'])
        self.assertEqual(self.requests(), before)                                          # E1, E10: 0 requests
        records = self.decisions(task)
        self.assertEqual(len(records), 12)                                                 # E3
        for r in records:
            self.assertEqual(r['subject'], {'component': 'onecrew.authority', 'model': 'rule'})
            self.assertEqual(r['authority']['revision'], sha); self.assertTrue(r['authority']['grant_id'].startswith('P1:'))
            self.assertTrue(r['evidence']); self.assertTrue(r['scope']); self.assertEqual(r['validity']['outcome'], 'in_authority')
            self.assertNotEqual(r['actor'], 'owner')
        self.assertEqual(plans.show(self.ledger, 'P1')['status'], 'approved')              # E11: the contract never goes back to proposed
        self.assertNotIn('plan.amended', [e['kind'] for e in self.ledger.events(task)])

    def test_e2_e14_out_of_scope_and_over_ceiling_are_u2_and_the_mutants_are_caught(self):
        check_scope_classified(self, authority.decide)
        check_ceilings(self, authority.decide)
        everything_ok = lambda contract, act, ctx=None: {'in_authority': True, 'class': None}
        with self.assertRaises(AssertionError): check_scope_classified(self, everything_ok)
        no_ceiling = lambda contract, act, ctx=None: authority.decide(contract, dict(act, kind='write', paths=['src/x']) if act['kind'] in ('spend', 'deadline') else act, ctx)
        with self.assertRaises(AssertionError): check_ceilings(self, no_ceiling)
        reason = authority.decide(root_contract(), OVER_BUDGET, CTX)['reason']
        self.assertIn('ceiling', reason); self.assertIn('50', reason)
        self.assertIn('deadline', authority.decide(root_contract(), LATER_DEADLINE, CTX)['reason'])

    def test_not_delegated_or_owner_only_actions_have_their_class(self):
        contract = root_contract(self_decide=['Q1'])
        got = authority.decide(contract, action('Q2'), CTX)
        self.assertEqual((got['in_authority'], got['class']), (False, 'U3'))
        legacy = contracts.validate(plan_json())
        self.assertEqual(authority.decide(legacy, action('Q1'), CTX)['class'], 'U3')       # a legacy root delegates nothing
        for kind, cls in (('accept_root', 'U4'), ('approve_root', 'U4'), ('device_install', 'U4'), ('change_acceptance', 'U1'),
                          ('push', 'U2'), ('tag', 'U2'), ('deploy', 'U2'), ('preference', 'U3')):
            self.assertEqual(authority.decide(root_contract(), {'kind': kind}, CTX)['class'], cls, kind)
        self.assertEqual(authority.decide(root_contract(), dict(action('Q6'), mandatory=True), CTX)['class'], 'U4')
        self.assertEqual(authority.decide(root_contract(), dict(action('Q4'), weakens=True), CTX)['class'], 'U1')
        self.assertEqual(authority.decide(root_contract(), dict(action('Q11'), rule_kind='other'), CTX)['class'], 'U2')
        self.assertEqual(authority.decide(root_contract(), dict(action('Q7'), pinned=True), CTX)['class'], 'U2')
        self.assertEqual(authority.decide(root_contract(), dict(action('Q1'), acceptance_changed=True), CTX)['class'], 'U1')
        self.assertEqual(authority.decide(root_contract(), dict(action('Q1'), cost={'calls': 999}), CTX)['class'], 'U2')

    def test_e16_the_scope_test_goes_through_covers(self):
        self.assertGreaterEqual(calls_covers(authority.decide), 2)

        def own_path_compare(contract, act, ctx=None):          # the mutant: compares paths itself, never calls covers()
            ok = all(p.startswith('src/') or p == 'a.txt' for p in act['paths'])
            return {'in_authority': ok, 'class': None if ok else 'U2'}
        self.assertEqual(calls_covers(own_path_compare), 0, 'the integration check must be red for a decision that does not call covers()')

    def test_t17a_a_write_outside_scope_is_refused_u2_nothing_is_written_and_the_grant_is_unchanged(self):
        task, contract, sha = self.anchor()
        outside = self.root / 'secret.txt'; outside.write_text('keep')
        digest = lambda: hashlib.sha256(outside.read_bytes()).hexdigest()
        h0, seal0, requests0 = digest(), authority.seal(contract), self.requests()
        result, done = authority.enforce(self.ledger, task, contract, {'kind': 'write', 'paths': ['secret.txt']}, name='P1', revision_sha=sha,
                                         ctx=CTX, perform=lambda: outside.write_text('changed'))
        self.assertEqual((result['in_authority'], result['class'], done), (False, 'U2', None))      # E1
        self.assertEqual(digest(), h0)                                                              # E6
        with self.ledger.transaction() as conn:
            state = plans.derive(self.ledger, conn, 'P1')
        again = plans.load(self.ledger, state)[0]
        self.assertEqual(authority.seal(again), seal0); self.assertEqual(again['authority'], contract['authority'])   # E7: not widened
        record = self.decisions(task)[-1]
        self.assertEqual((record['validity']['outcome'], record['validity']['class']), ('out_of_authority', 'U2'))
        self.assertEqual(self.requests(), requests0)
        inside, done = authority.enforce(self.ledger, task, contract, WRITE_IN, name='P1', revision_sha=sha, ctx=CTX, perform=lambda: 'ran')
        self.assertEqual((inside['in_authority'], done), (True, 'ran'))                             # the counter: inside the scope it runs

    def test_write_aliases_traversal_and_missing_scope_do_not_execute(self):
        task, contract, sha = self.anchor()
        target = self.root / 'outside.txt'
        target.write_text('keep')
        invalid = [None, [], 'src/a.py', ['src/../outside.txt'], ['src\\..\\outside.txt'],
                   ['/src/a.py'], ['C:/src/a.py'], ['src//a.py'], ['src/a.py:stream'],
                   ['src/a.py.'], ['src/NUL'], ['src/*'], [None], [42]]
        for paths in invalid:
            with self.subTest(paths=paths):
                request = {'kind': 'write'} if paths is None else {'kind': 'write', 'paths': paths}
                result, done = authority.enforce(self.ledger, task, contract, request, name='P1', revision_sha=sha,
                    ctx=CTX, perform=lambda: target.write_text('outside changed'))
                self.assertEqual((False, 'U2', None), (result['in_authority'], result['class'], done))
                self.assertEqual('keep', target.read_text())
        # Normal, contained Windows separators and case still normalize correctly.
        result, done = authority.enforce(self.ledger, task, contract, {'kind': 'write', 'paths': ['SRC\\new.py']},
            name='P1', revision_sha=sha, ctx=CTX, perform=lambda: 'contained')
        self.assertEqual((True, 'contained'), (result['in_authority'], done))

    def test_q4_requires_test_write_right_scope_and_remaining_budget(self):
        task, contract, sha = self.anchor(root_contract(edit_tests=True))
        invalid = [
            (root_contract(edit=False), action('Q4'), CTX),
            (root_contract(edit_tests=False), action('Q4'), CTX),
            (contract, dict(action('Q4'), paths=['outside.py']), CTX),
            (contract, dict(action('Q4'), paths=[]), CTX),
            (contract, dict(action('Q4'), paths=['src/../outside.py']), CTX),
            (contract, dict(action('Q4'), cost={}), CTX),
            (contract, dict(action('Q4'), cost={'calls': 41}), CTX),
            (contract, dict(action('Q4'), cost={'seconds': 3601}), CTX),
            (contract, dict(action('Q4'), cost={'calls': 1}), {}),
            (contract, dict(action('Q4'), cost={'calls': -1}), CTX),
            (contract, dict(action('Q4'), cost={'calls': float('nan')}), CTX),
            (contract, dict(action('Q4'), cost={'calls': 'one'}), CTX),
        ]
        for grant, request, ctx in invalid:
            with self.subTest(request=request, grant=grant['authority']):
                executed = []
                result, done = authority.enforce(self.ledger, task, grant, request, name='P1', revision_sha=sha,
                                                ctx=ctx, perform=lambda: executed.append(True))
                self.assertFalse(result['in_authority'])
                self.assertEqual('U2', result['class'])
                self.assertIsNone(done)
                self.assertEqual([], executed)
        result, done = authority.enforce(self.ledger, task, contract, dict(action('Q4'), cost={'calls': 1}),
            name='P1', revision_sha=sha, ctx=CTX, perform=lambda: 'test edit')
        self.assertEqual((True, 'test edit'), (result['in_authority'], done))

    def test_q4_readonly_test_run_uses_command_right_not_edit_right(self):
        request = dict(action('Q4'), operation='run', cost={'seconds': 20})
        self.assertTrue(authority.decide(root_contract(edit=False, commands=True), request, CTX)['in_authority'])
        self.assertFalse(authority.decide(root_contract(commands=False), request, CTX)['in_authority'])

    def test_v1_prefix_function_is_unchanged_by_new_authority_validation(self):
        from onecrew.delivery_planner import within
        self.assertIs(within, authority.within)
        self.assertTrue(within('src/a.py', ['src/']))
        self.assertFalse(within('src2/a.py', ['src/']))


class GateTests(Fixture):
    """The grant is enforced at the dispatch gate: the sealed job is inside the root grant, or it is not dispatched."""

    def job(self, key, authority_value, paths=('src',), **limits):
        contract = {'schema_version': 1, 'goal': 'A work job', 'acceptance': ['done'], 'preserve': ['everything'], 'authority': authority_value,
                    'scope': {'repository': '', 'paths': list(paths)}, 'authorized_by': {'source': 'user', 'reference': 'test'}}
        return submit(self.ledger, None, key, mode='work', provider='kiro', model='claude-sonnet-5', contract=contract, **limits)['id']

    def make_root(self, key, **authority_changes):
        self.approved(key, plan_json(scope={'owned': OWNED}, authority=dict(AUTH, **authority_changes)))

    def test_inside_the_grant_dispatches(self):
        gate.set_enforced(self.ledger, True, 'owner', 'test')
        self.make_root('ok')
        task = self.job('ok', {'edit': True, 'commands': True, 'local_branches': ['wf/x']})
        self.assertIsNone(solution_gate.check(self.ledger, task))

    def test_each_of_the_seven_fields_and_the_paths_are_enforced(self):
        gate.set_enforced(self.ledger, True, 'owner', 'test')
        cases = [
            ('edit', {'edit': False, 'commands': True, 'apply_to_project': False}, {'edit': True}, ('src',), 'edit'),
            ('commands', {'commands': False}, {'commands': True}, ('src',), 'commands'),
            ('branch', {}, {'edit': True, 'local_branches': ['wf/y']}, ('src',), 'wf/y'),
            ('branchat', {}, {'edit': True, 'local_branches': ['wf/x'], 'branch_at': 'a' * 40}, ('src',), 'branch_at'),
            ('apply', {}, {'edit': True, 'apply_to_project': True}, ('src',), 'apply_to_project'),
            ('tests', {}, {'edit': True, 'edit_tests': True}, ('src',), 'edit_tests'),
            ('unconf', {}, {'edit': True, 'commands': True, 'unconfined_commands': True}, ('src',), 'unconfined_commands'),
            ('paths', {}, {'edit': True}, ('other',), 'outside the owned scope'),
            ('whole', {}, {'edit': True}, ('',), 'outside the owned scope'),
        ]
        for key, root_changes, child, paths, expect in cases:
            self.make_root(key, **root_changes)
            task = self.job(key, child, paths)
            with self.assertRaises(LedgerError, msg=key) as caught: solution_gate.check(self.ledger, task)
            self.assertIn('exceeds the authority', str(caught.exception), key); self.assertIn(expect, str(caught.exception), key)
        self.assertEqual(gate.sync_refusals(self.ledger), len(cases))                    # every refusal is a ledger event

    def test_a_legacy_root_without_authority_keeps_its_behaviour(self):
        gate.set_enforced(self.ledger, True, 'owner', 'test')
        self.approved('old', plan_json())
        task = self.job('old', {'edit': True, 'commands': True, 'unconfined_commands': True, 'apply_to_project': True}, ('anything',))
        self.assertIsNone(solution_gate.check(self.ledger, task))

    def test_a_job_without_a_work_contract_is_judged_by_its_permissions(self):
        gate.set_enforced(self.ledger, True, 'owner', 'test')
        self.make_root('audit')
        self.assertIsNone(solution_gate.check(self.ledger, submit(self.ledger, 'Audit it', 'audit')['id']))   # discover/report only
        self.make_root('nowrite', edit=False, commands=False)
        child = self.job('nowrite', {'edit': True})
        with self.assertRaises(LedgerError): solution_gate.check(self.ledger, child)

    def native_job(self, key, package='src'):
        from tests.test_solution_gate import approve_fixture
        recipe = dict(source_roots=[package], owned=[package + '/lib/main.dart', package + '/test/main_test.dart'],
                      extra_sources={}, package=package, flutter_root=str(self.root / 'flutter'),
                      tests=[package + '/test/main_test.dart'], reference='fixture authorized native change', trusted_native=True)
        return submit(self.ledger, 'Native change', key, mode='change', provider='claude', model='sonnet',
                      native_change=recipe, **approve_fixture(self.ledger, key + '-solution'))['id']

    def test_native_job_actual_sealed_recipe_cannot_escape_root(self):
        gate.set_enforced(self.ledger, True, 'owner', 'test')
        self.make_root('native-out', apply_to_project=True, edit_tests=True, unconfined_commands=True)
        task = self.native_job('native-out', package='other')
        with self.assertRaisesRegex(LedgerError, 'outside the owned scope'):
            solution_gate.check(self.ledger, task)
        self.make_root('native-in', apply_to_project=True, edit_tests=True, unconfined_commands=True)
        task = self.native_job('native-in')
        self.assertIsNotNone(solution_gate.check(self.ledger, task))

    def test_native_job_requires_test_and_unconfined_command_rights(self):
        gate.set_enforced(self.ledger, True, 'owner', 'test')
        for key, missing in (('no-test-right', 'edit_tests'), ('no-native-right', 'unconfined_commands')):
            grants = dict(apply_to_project=True, edit_tests=True, unconfined_commands=True)
            grants[missing] = False
            self.make_root(key, **grants)
            task = self.native_job(key)
            with self.assertRaisesRegex(LedgerError, missing):
                solution_gate.check(self.ledger, task)

    def test_generic_writer_with_no_sealed_paths_is_refused_not_given_root_scope(self):
        from tests.test_solution_gate import approve_fixture
        gate.set_enforced(self.ledger, True, 'owner', 'test')
        self.make_root('unscoped')
        task = submit(self.ledger, 'Change with later-discovered scope', 'unscoped', mode='change', provider='claude', model='sonnet',
                      image='sha256:' + 'a' * 64, **approve_fixture(self.ledger))['id']
        with self.assertRaisesRegex(LedgerError, 'explicit non-empty write scope'):
            solution_gate.check(self.ledger, task)


if __name__ == '__main__':
    unittest.main()
