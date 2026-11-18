"""DEV31 slice D (#41): one owner-approved skill delivered to one worker attempt, pinned, bound and traceable.

The fixture builds a real skill candidate through skills.refresh from three completed outcomes (synthetic outcomes written with the core
helpers, so this module also runs against the installed wheel). The owner's approval is written as the ledger event the other skill tests
write; owner verbs (rollback, revoke) run in a process that is not an AI session, and a test shows they still refuse inside one.
Only temp ledgers and temp directories; LOCALAPPDATA/APPDATA point into the temp dir."""
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from onecrew import control_core, interventions, outcome_core, skill_delivery, skills, task_intake
from onecrew.ledger import Ledger, LedgerError, content_hash
from onecrew.snapshots import durable_write

GOAL = 'Inspect calculation implementation and report subtraction evidence'
OTHER_GOAL = 'Review database migration rollback safety permissions'
GRANT = {'permissions': ['discover', 'report'], 'owned_paths': ['src/**'], 'tools': ['read', 'finish'], 'budget': {'max_calls': 5}}


def owner_env():
    """An owner's own terminal: no AI-session marker. The guard itself is untouched."""
    env = {k: v for k, v in os.environ.items() if k not in interventions.AI_SESSION_MARKERS}
    return mock.patch.dict(os.environ, env, clear=True)


def ai_env():
    """Inside an AI tool session: the marker the guard looks for."""
    return mock.patch.dict(os.environ, {interventions.AI_SESSION_MARKERS[0]: '1'})


class Fixture(unittest.TestCase):
    history_goal, history_file = GOAL, 'calc.py'           # what the three completed outcomes (and so the skill's signature) are about

    def setUp(self):
        # A skill file lives at state/skills/<project hash>/<id>/<revision hash>/ (about 200 characters); on Windows a long TEMP overflows
        # MAX_PATH, so the temp tree is made as short as the drive allows (still a throw-away directory, removed after each test).
        short = Path(tempfile.gettempdir()).anchor
        try: self.temp = tempfile.TemporaryDirectory(prefix='d', dir=short or None)
        except OSError: self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        patch = mock.patch.dict(os.environ, {'LOCALAPPDATA': str(base / 'local'), 'APPDATA': str(base / 'roaming')})
        patch.start(); self.addCleanup(patch.stop)
        self.root = base / 'project'; self.root.mkdir(); (self.root / self.history_file).write_text('def add(a, b): return a - b\n')
        self.state = base / 'state'
        self.ledger = Ledger(self.root, self.state)
        self.tasks = []
        for i in range(3):
            self.tasks.append(task_intake.submit(self.ledger, self.history_goal, 'history-' + str(i))['id'])
        control_core.migrate(self.ledger)
        sig = skills.signature(self.history_goal, 'audit', {self.history_file: 'h'})
        with self.ledger.transaction(write=True) as conn:
            for i, task in enumerate(self.tasks):
                row = self.ledger._task(conn, task)
                conn.execute('INSERT INTO executions(task_id,configuration,revision,status) VALUES(?,?,?,?)', (task, '{}', 'r' + str(i), 'completed'))
                data = {'version': 1, 'task': task, 'task_revision': row['revision'], 'phase': 'completed', 'mode': 'audit',
                        'snapshot': 'snap' + str(i), 'verification': 'passed', 'signature': sig, 'procedure': ['read', 'finish']}
                data['id'] = outcome_core.outcome_id(data)
                outcome_core.append_outcome(conn, self.ledger, task, data)
        self.assertEqual(len(skills.refresh(self.ledger)), 1)
        self.skill = self.records()[next(iter(self.records()))]

    def records(self):
        with self.ledger.transaction() as conn:
            return skills.records(self.ledger, conn)

    def write_state(self, value):
        with self.ledger.transaction(write=True) as conn:
            self.ledger._event(conn, value['tasks'][0], 'skill.state', value)

    def approve(self, **changes):
        """The owner's approval as the ledger event the existing skill tests write."""
        value = dict(self.records()[self.skill['id']], status='approved', operator_reference='owner review', **changes)
        self.write_state(value); return value

    def new_revision(self, body):
        """A later revision of the same skill (its own file), approved."""
        value = dict(self.records()[self.skill['id']], body=body, status='approved', operator_reference='owner review 2')
        value['revision'] = content_hash({k: v for k, v in value.items() if k != 'revision'})
        durable_write(skills.skill_path(self.ledger, value), body.encode('utf-8'))
        self.write_state(value); return value

    def args(self, attempt=1, **over):
        a = dict(plan='p', plan_revision=1, node='N1', attempt=attempt)
        a.update(over); return a

    def deliver(self, attempt=1, ledger=None, **over):
        kw = dict(self.args(attempt), goal=GOAL, profile={'mode': 'audit'}, files={'calc.py': 'h'}, grant=copy.deepcopy(GRANT), skill_id=self.skill['id'])
        kw.update(over)
        return skill_delivery.deliver(ledger or self.ledger, self.tasks[0], **kw)


class DeliveryTests(Fixture):
    def test_selected_pinned_skill_is_delivered_with_its_hash_and_exact_content(self):
        value = self.approve()
        got = self.deliver()
        self.assertTrue(got['delivered']); self.assertEqual(got['status'], 'delivered')
        self.assertEqual(got['skill']['body'], value['body'])
        self.assertEqual(got['skill']['revision'], value['revision'])
        self.assertEqual(got['skill']['hash'], hashlib.sha256(value['body'].encode('utf-8')).hexdigest())
        self.assertEqual(got['binding'], {'project': self.ledger.project_id, 'task': self.tasks[0], 'plan': 'p', 'plan_revision': '1', 'node': 'N1', 'attempt': 1})
        # without a skill id the same approved skill is selected for a matching task
        auto = self.deliver(attempt=2, skill_id=None)
        self.assertEqual(auto['skill']['revision'], value['revision'])

    def test_candidate_without_owner_approval_is_not_delivered(self):
        got = self.deliver()
        self.assertFalse(got['delivered']); self.assertEqual(got['reason'], 'not_approved'); self.assertNotIn('skill_body', got)
        self.assertNotIn('body', (got['skill'] or {}))

    def test_wrong_permission_skill_is_refused_not_delivered(self):
        self.approve(required_permissions=['git.push'])
        got = self.deliver()
        self.assertFalse(got['delivered']); self.assertEqual(got['reason'], 'wrong_permission')
        self.assertIn('git.push', got['detail']); self.assertEqual([s['step'] for s in got['steps']], ['refused'])
        self.assertNotIn('body', got['skill'])

    def test_wrong_project_skill_is_refused(self):
        self.approve()
        other_root = Path(self.temp.name) / 'other'; other_root.mkdir()
        other = Ledger(other_root, self.state)
        anchor = task_intake.submit(other, GOAL, 'anchor')['id']
        got = skill_delivery.deliver(other, anchor, **dict(self.args(), goal=GOAL, profile={'mode': 'audit'}, files={'calc.py': 'h'},
                                                           grant=copy.deepcopy(GRANT), skill_id=self.skill['id']))
        self.assertFalse(got['delivered']); self.assertEqual(got['reason'], 'wrong_project')
        # a record in this project that names another project is refused as well
        self.approve(project='some-other-project')
        got = self.deliver()
        self.assertFalse(got['delivered']); self.assertEqual(got['reason'], 'wrong_project')

    def test_stale_revision_and_stale_evidence_are_refused(self):
        first = self.approve(); second = self.new_revision('Second reviewed procedure. Task acceptance overrides it.\n')
        got = self.deliver(expected_revision=first['revision'])
        self.assertFalse(got['delivered']); self.assertEqual(got['reason'], 'stale')
        self.assertEqual(got['skill']['revision'], second['revision'])
        ok = self.deliver(attempt=2, expected_revision=second['revision'])
        self.assertTrue(ok['delivered'])
        # the evidence the approval stood on stops being true
        with self.ledger.transaction(write=True) as conn:
            conn.execute("UPDATE executions SET status='failed' WHERE task_id=?", (self.skill['evidence'][0]['task'],))
        late = self.deliver(attempt=3)
        self.assertFalse(late['delivered']); self.assertEqual(late['reason'], 'stale')

    def test_tampered_content_is_refused(self):
        value = self.approve()
        bad = self.deliver(expected_hash='0' * 64)
        self.assertFalse(bad['delivered']); self.assertEqual(bad['reason'], 'tampered')
        path = skills.skill_path(self.ledger, value)
        path.write_text('Changed instructions after approval', encoding='utf-8')
        got = self.deliver(attempt=2)
        self.assertFalse(got['delivered']); self.assertEqual(got['reason'], 'tampered')
        path.write_bytes(value['body'].encode('utf-8'))
        fine = self.deliver(attempt=3, expected_hash=hashlib.sha256(value['body'].encode('utf-8')).hexdigest())
        self.assertTrue(fine['delivered'])

    def test_revoked_skill_is_never_delivered(self):
        self.approve()
        with owner_env(): skill_delivery.revoke(self.ledger, self.skill['id'], 'no longer wanted')
        got = self.deliver()
        self.assertFalse(got['delivered']); self.assertEqual(got['reason'], 'revoked')
        newer = self.new_revision('Another revision after the revoke.\n')
        self.assertEqual(newer['status'], 'approved')
        self.assertEqual(self.deliver(attempt=2)['reason'], 'revoked')
        with ai_env(), self.assertRaises(LedgerError): skill_delivery.revoke(self.ledger, self.skill['id'], 'from an AI session')

    def test_revoked_rejected_status_is_never_delivered(self):
        self.write_state(dict(self.skill, status='rejected', operator_reference='not useful'))
        got = self.deliver()
        self.assertFalse(got['delivered']); self.assertEqual(got['reason'], 'revoked')
        auto = self.deliver(attempt=2, skill_id=None)
        self.assertFalse(auto['delivered'])

    def test_rollback_to_previous_approved_revision_is_used_and_recorded(self):
        first = self.approve(); second = self.new_revision('Second reviewed procedure. Task acceptance overrides it.\n')
        before = self.deliver()
        self.assertEqual(before['skill']['revision'], second['revision'])
        with ai_env(), self.assertRaises(LedgerError): skill_delivery.rollback(self.ledger, self.skill['id'], first['revision'], 'AI session')
        with owner_env():
            with self.assertRaises(LedgerError): skill_delivery.rollback(self.ledger, self.skill['id'], 'no-such-revision', 'x')
            skill_delivery.rollback(self.ledger, self.skill['id'], first['revision'], 'second revision was wrong')
        after = self.deliver(attempt=2)
        self.assertTrue(after['delivered']); self.assertEqual(after['skill']['revision'], first['revision'])
        self.assertEqual(after['skill']['body'], first['body'])
        self.assertEqual(after['rollback'], {'from': second['revision'], 'to': first['revision'], 'reference': 'second revision was wrong'})
        # the attempt delivered before the rollback keeps what it was given
        again = self.deliver()
        self.assertEqual(again['skill']['revision'], second['revision'])

    def test_not_suitable_skill_is_not_delivered_and_the_reason_is_recorded(self):
        self.approve()
        got = self.deliver(goal=OTHER_GOAL)
        self.assertFalse(got['delivered']); self.assertEqual(got['reason'], 'not_suitable')
        self.assertIn('scope', got['detail'])
        shown = skill_delivery.record_of(self.ledger, self.tasks[0], **self.args())
        self.assertEqual((shown['status'], shown['reason']), ('refused', 'not_suitable'))
        none = self.deliver(attempt=2, goal=OTHER_GOAL, skill_id=None)
        self.assertEqual(none['reason'], 'not_suitable'); self.assertIsNone(none['skill'])
        wrong_tech = self.deliver(attempt=3, files={'calc.dart': 'h'})
        self.assertEqual(wrong_tech['reason'], 'not_suitable')

    def test_restart_keeps_binding_and_nothing_reselects_mid_attempt(self):
        first = self.approve()
        got = self.deliver()
        self.new_revision('A newer revision arrives while attempt 1 is running.\n')
        restarted = Ledger(self.root, self.state)
        again = self.deliver(ledger=restarted)
        self.assertEqual(again['binding'], got['binding']); self.assertEqual(again['skill'], got['skill'])
        self.assertEqual(again['steps'], got['steps']); self.assertEqual(again['skill']['revision'], first['revision'])
        read = skill_delivery.record_of(restarted, self.tasks[0], **self.args())
        self.assertEqual(read['skill']['hash'], got['skill']['hash'])
        self.assertEqual(self.event_count('skill.delivery'), 2)           # the replay wrote nothing
        # only a new attempt selects again, and then picks the revision in force
        self.assertNotEqual(self.deliver(attempt=2, ledger=restarted)['skill']['revision'], first['revision'])
        # another node has no record yet
        self.assertIsNone(skill_delivery.record_of(restarted, self.tasks[0], **self.args(node='other-node')))

    def event_count(self, kind):
        with self.ledger.transaction() as conn:
            return conn.execute('SELECT COUNT(*) FROM events WHERE kind=?', (kind,)).fetchone()[0]

    def test_selected_delivered_evaluated_are_three_ordered_steps_and_evaluation_is_separate(self):
        self.approve()
        got = self.deliver()
        self.assertEqual([s['step'] for s in got['steps']], ['selected', 'delivered'])
        self.assertNotIn('outcome', got)
        shown = skill_delivery.record_of(self.ledger, self.tasks[0], **self.args())
        self.assertEqual(shown['status'], 'delivered'); self.assertNotIn('outcome', shown)
        done = skill_delivery.evaluate(self.ledger, self.tasks[0], outcome='success', note='tests green', **self.args())
        self.assertEqual([s['step'] for s in done['steps']], ['selected', 'delivered', 'evaluated'])
        times = [s['at'] for s in done['steps']]
        self.assertEqual(times, sorted(times)); self.assertTrue(all(times))
        self.assertEqual((done['status'], done['outcome']), ('evaluated', 'success'))
        self.assertEqual(skill_delivery.evaluate(self.ledger, self.tasks[0], outcome='success', **self.args())['steps'], done['steps'])
        with self.assertRaises(LedgerError): skill_delivery.evaluate(self.ledger, self.tasks[0], outcome='failure', **self.args())
        with self.assertRaises(LedgerError): skill_delivery.evaluate(self.ledger, self.tasks[0], outcome='great', **self.args(attempt=5))
        with self.assertRaises(LedgerError): skill_delivery.evaluate(self.ledger, self.tasks[0], outcome='success', **self.args(attempt=5))
        refused = self.deliver(attempt=2, goal=OTHER_GOAL)
        self.assertFalse(refused['delivered'])
        with self.assertRaises(LedgerError): skill_delivery.evaluate(self.ledger, self.tasks[0], outcome='success', **self.args(attempt=2))

    def test_no_grant_widening_by_a_delivered_skill(self):
        self.approve()
        grant = copy.deepcopy(GRANT)
        got = skill_delivery.deliver(self.ledger, self.tasks[0], **dict(self.args(), goal=GOAL, profile={'mode': 'audit'}, files={'calc.py': 'h'},
                                                                         grant=grant, skill_id=self.skill['id']))
        self.assertTrue(got['delivered'])
        self.assertEqual(grant, GRANT); self.assertEqual(got['grant'], GRANT)          # nothing added: permissions, owned paths, tools, budget
        self.assertEqual(got['grant_digest'], content_hash(GRANT))
        self.assertEqual(set(got['skill']), {'id', 'revision', 'hash', 'body'})
        self.assertTrue(set(self.skill['required_permissions']) <= set(GRANT['permissions']))
        stored = skill_delivery.record_of(self.ledger, self.tasks[0], **self.args())
        self.assertNotIn('permissions', json.dumps({k: v for k, v in stored.items() if k not in ('skill', 'grant_digest', 'binding')}))
        # a skill that would need more than the contract grants is refused, never lets the grant grow
        self.approve(required_permissions=['git.push', 'git.commit'])
        late = self.deliver(attempt=2)
        self.assertEqual(late['reason'], 'wrong_permission'); self.assertEqual(late['grant'], GRANT)


class ReplayTests(Fixture):
    """F5/F6: a replay of a recorded binding is narrowed by revoke and re-checked against the request."""

    def test_replay_after_revoke_hands_out_no_body_and_records_a_refused_step(self):
        self.approve()
        first = self.deliver()
        self.assertTrue(first['delivered'])
        with owner_env(): skill_delivery.revoke(self.ledger, self.skill['id'], 'owner: this skill is wrong')
        again = self.deliver()
        self.assertFalse(again['delivered']); self.assertEqual((again['status'], again['reason']), ('refused', 'revoked'))
        self.assertEqual(again['detail'], 'revoked_after_delivery')
        self.assertNotIn('body', again['skill'])
        self.assertEqual([s['step'] for s in again['steps']], ['selected', 'delivered', 'refused'])      # the delivered step stays as history
        shown = skill_delivery.record_of(self.ledger, self.tasks[0], **self.args())
        self.assertFalse(shown['delivered']); self.assertNotIn('body', shown['skill'])
        replay_again = self.deliver()
        self.assertEqual(replay_again['steps'], again['steps'])                                          # recorded once
        self.assertEqual(self.deliver(attempt=2)['reason'], 'revoked')

    def test_read_after_revoke_withholds_the_body_even_before_any_replay(self):
        self.approve(); self.deliver()
        with owner_env(): skill_delivery.revoke(self.ledger, self.skill['id'], 'owner: wrong')
        shown = skill_delivery.record_of(self.ledger, self.tasks[0], **self.args())
        self.assertFalse(shown['delivered']); self.assertNotIn('body', shown['skill']); self.assertEqual(shown['reason'], 'revoked')

    def test_rollback_replay_keeps_the_pinned_revision_and_says_superseded(self):
        first = self.approve(); second = self.new_revision('Second reviewed procedure. Task acceptance overrides it.\n')
        got = self.deliver()
        self.assertEqual((got['skill']['revision'], got['superseded']), (second['revision'], False))
        with owner_env(): skill_delivery.rollback(self.ledger, self.skill['id'], first['revision'], 'second revision was wrong')
        again = self.deliver()
        self.assertTrue(again['delivered']); self.assertEqual(again['skill']['revision'], second['revision'])
        self.assertTrue(again['superseded'])

    def test_replay_with_a_grant_lacking_the_required_permission_is_refused_as_binding_mismatch(self):
        self.approve(required_permissions=['report'])
        self.deliver()
        narrow = dict(copy.deepcopy(GRANT), permissions=[])
        again = self.deliver(grant=narrow)
        self.assertFalse(again['delivered']); self.assertEqual(again['reason'], 'binding_mismatch')
        self.assertNotIn('body', again['skill'] or {})
        self.assertEqual(again['grant'], narrow)
        # recorded, but the real binding is untouched: the honest caller still gets the skill
        honest = self.deliver()
        self.assertTrue(honest['delivered']); self.assertIn('body', honest['skill'])
        self.assertEqual(self.deliver(grant=narrow)['steps'], again['steps'])                            # one record per distinct bad request
        self.assertEqual(self.event_count('skill.delivery'), 3)

    def test_replay_with_another_grant_or_another_skill_id_is_refused(self):
        self.approve(); self.deliver()
        wider = dict(copy.deepcopy(GRANT), tools=['read', 'finish', 'write'])
        self.assertEqual(self.deliver(grant=wider)['reason'], 'binding_mismatch')
        other = self.deliver(skill_id='some-other-skill')
        self.assertFalse(other['delivered']); self.assertEqual(other['reason'], 'binding_mismatch')
        self.assertNotEqual((other['skill'] or {}).get('id'), 'some-other-skill')
        same = self.deliver()
        self.assertTrue(same['delivered']); self.assertEqual(same['skill']['id'], self.skill['id'])

    def test_replay_without_a_skill_id_is_the_same_binding(self):
        self.approve(); self.deliver()
        self.assertTrue(self.deliver(skill_id=None)['delivered'])

    def test_plan_label_prefix_is_one_binding(self):
        self.approve()
        got = self.deliver(plan='plan-ns:P1')
        again = self.deliver(plan='P1')
        self.assertTrue(got['delivered']); self.assertEqual(again['skill'], got['skill'])
        self.assertEqual(again['binding']['plan'], 'P1')
        self.assertEqual(self.deliver(plan='plan:P1')['steps'], got['steps'])
        self.assertEqual(self.event_count('skill.delivery'), 2)

    def event_count(self, kind):
        with self.ledger.transaction() as conn:
            return conn.execute('SELECT COUNT(*) FROM events WHERE kind=?', (kind,)).fetchone()[0]


NODE_GOAL = 'Produce evidence for O1'
CAPS = ['namespaced-storage', 'root-budget', 'internal-plan', 'sequential-engine']


def plan_value():
    return {'schema_version': 2, 'title': 'Sample', 'size': 'S',
            'understanding': {'restated_goal': 'Do the sample and prove it.', 'target': {'repo': '.', 'ref': 'HEAD', 'paths': ['a.txt']},
                              'assumptions': [], 'confidence': 'high', 'unknowns': []},
            'preconditions': [{'id': 'P1', 'check': 'path_exists', 'args': {'path': 'a.txt'}, 'why': 'the file to work on is there'}],
            'output': ['The sample exists'], 'scope': {'owned': ['a.txt', 'b.txt']}, 'non_goals': ['Nothing else'],
            'items': [{'id': 'I1', 'title': 'Do it', 'tier': 'must', 'milestone': 'M1'}, {'id': 'S1', 'title': 'Nice to have', 'tier': 'should'},
                      {'id': 'W1', 'title': 'Never', 'tier': 'wont'}],
            'milestones': [{'id': 'M1', 'title': 'Milestone M1', 'covers': ['O1'],
                            'verifier': {'type': 'command', 'config': {'argv': [sys.executable, '-c', 'print("ok")']}}}],
            'budget': {'max_calls': 100, 'time': 120}, 'attention': {'questions': 1}, 'profile_version': None,
            'authority': {'edit': True, 'commands': True, 'edit_tests': True, 'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q9', 'Q12']}}


def plan_node():
    return {'id': 'C', 'goal': NODE_GOAL, 'input': [], 'output': ['Evidence for O1'], 'acceptance': ['O1'], 'depends': [],
            'read': ['a.txt'], 'write': ['a.txt'], 'resources': [], 'estimate_seconds': [1, 2], 'execution_cap_seconds': 60, 'budget_calls': 1,
            'checks': [{'id': 'check-C', 'spec': 'Check the declared O1 output of C'}], 'integration': False,
            'executor': {'role': 'worker', 'provider': 'codex', 'model': 'gpt-6.1-sol'}}


class NativeWorkerPathTests(Fixture):
    """#41 wired into the native worker: a real plan, the real executor and a fixture worker (no model call) that captures its input."""
    history_goal, history_file = NODE_GOAL, 'a.txt'

    def setUp(self):
        super().setUp()
        from onecrew.common_executor import NativeExecutor
        from onecrew.snapshots import Snapshots
        from onecrew.v2 import engine, internal_plan, plan as plans
        self.engine, self.plans, self.store = engine, plans, Snapshots(self.ledger.state_root)
        env = mock.patch.dict(os.environ); env.start(); self.addCleanup(env.stop)
        for name in ('ONECREW_V2_REQUIRE_PLAN',) + tuple(interventions.AI_SESSION_MARKERS): os.environ.pop(name, None)
        git = lambda *a: subprocess.check_output(['git', '-C', str(self.root), *a], stderr=subprocess.PIPE)
        git('init', '-q'); git('config', 'user.name', 'T'); git('config', 'user.email', 't@localhost')
        (self.root / 'a.txt').write_text('one\n'); git('add', 'a.txt'); git('commit', '-q', '-m', 'base')
        plans.propose(self.ledger, 'P1', plan_value(), 'codex', workflow=True, capabilities=CAPS)
        plans.approve(self.ledger, 'P1', 'owner', 'fixture approval')           # a temp ledger, like the existing engine tests
        os.environ['ONECREW_ACTOR'] = 'codex'
        control_core.migrate(self.ledger)
        last = dict(plan_node(), id='I', depends=[{'node': 'C', 'requires': 'verified'}], write=[], integration=True,
                    executor={'role': 'worker', 'provider': 'claude', 'model': 'claude-haiku-5-5'}, checks=[{'id': 'check-I', 'spec': 'Check the report of I'}])
        internal_plan.revise(self.ledger, 'P1', [plan_node(), last], reason='Split work inside the approved scope', evidence=['a.txt:1'])
        self.inputs, self.seen = [], {}
        case = self

        class Executor(NativeExecutor):
            def prepare(self, ledger, control, task, node, attempt):
                case.seen = dict(ledger=ledger, control=control, task=task, node=node, attempt=attempt)
                return super().prepare(ledger, control, task, node, attempt)
        self.executor = Executor(self.ledger, worker_factory=self.factory)

    def factory(self, control, provider):
        case = self

        class Worker:
            def capability(self): return {'provider': provider, 'mode': 'fixture-no-tools'}

            def run(self, attempt, prompt, schema, profile):
                case.inputs.append(prompt)
                control.launched(attempt['id'], attempt['generation'], {'fixture': True})
                control.finish(attempt['id'], attempt['generation'], {'exit_code': 0, 'fixture': True})

            def result(self, attempt):
                return {'summary': 'Fixture producer', 'files': [{'path': 'a.txt', 'content': 'candidate\n'}], 'backlog': []}, [{'source': 'fixture'}]
        return Worker()

    def run_node(self):
        return self.engine.step(self.ledger, 'P1', self.executor)

    def body_of(self, prompt):
        return json.loads(prompt[prompt.index('\n') + 1:])

    def checker(self, result):
        def check(item, artifact):
            return {'artifact': artifact, 'checks': [{'id': c['id'], 'result': result, 'evidence': self.store.blob(b'fixture check')} for c in item['checks']]}
        return check

    def deliveries(self):
        with self.ledger.transaction() as conn:
            return [json.loads(r['payload']) for r in conn.execute("SELECT payload FROM events WHERE kind='skill.delivery' ORDER BY seq")]

    def test_approved_skill_text_reaches_the_worker_input_pinned_and_the_grant_is_unchanged(self):
        value = self.approve()
        result = self.run_node()
        self.assertEqual(result['state'], 'produced')
        section = self.body_of(self.inputs[0])['approved_skill']
        self.assertEqual((section['id'], section['revision'], section['sha256']), (value['id'], value['revision'], skill_delivery.body_hash(value['body'])))
        self.assertEqual(section['text'], value['body']); self.assertIn('adds no permission', section['rule'])
        receipt = json.loads(self.store.read_blob(result['receipt']))
        self.assertEqual(receipt['approved_skill'], {'id': value['id'], 'revision': value['revision'], 'sha256': section['sha256']})
        steps = self.deliveries()[-1]
        self.assertEqual((steps['status'], steps['binding']['node'], steps['binding']['attempt']), ('delivered', 'C', 1))
        # the worker's grant and scope are what the contract gave: same permissions, the node's own paths, no tool
        handoff = self.ledger.task(self.seen['task']['id'], full=True)['handoff']
        self.assertEqual(skill_delivery.native_grant(handoff, self.seen['node']), {'permissions': ['discover', 'report'], 'owned_paths': ['a.txt'],
                                                                                    'read_paths': ['a.txt'], 'tools': []})
        self.assertEqual(handoff['grant']['permissions'], ['discover', 'report'])
        self.assertEqual(steps['grant_digest'], content_hash(skill_delivery.native_grant(handoff, self.seen['node'])))

    def test_revoked_skill_leaves_the_worker_input_without_skill_text_and_records_the_refusal(self):
        self.approve()
        with owner_env(): skill_delivery.revoke(self.ledger, self.skill['id'], 'owner: wrong')
        self.assertEqual(self.run_node()['state'], 'produced')
        body = self.body_of(self.inputs[0])
        self.assertNotIn('approved_skill', body); self.assertNotIn(self.skill['body'], self.inputs[0])
        last = self.deliveries()[-1]
        self.assertEqual(last['status'], 'refused'); self.assertIsNone(last['skill'])      # the automatic selection no longer sees the revoked skill

    def test_revoke_after_delivery_withdraws_the_text_when_the_same_attempt_is_prepared_again(self):
        self.approve()
        self.run_node()
        self.assertIn('approved_skill', self.body_of(self.inputs[0]))
        with owner_env(): skill_delivery.revoke(self.ledger, self.skill['id'], 'owner: wrong')
        again = self.executor.prepare(self.ledger, self.seen['control'], self.seen['task'], self.seen['node'], self.seen['attempt'])['prompt']
        self.assertNotIn('approved_skill', self.body_of(again)); self.assertNotIn(self.skill['body'], again)
        last = self.deliveries()[-1]
        self.assertEqual((last['status'], last['reason'], last['detail']), ('refused', 'revoked', 'revoked_after_delivery'))

    def test_project_without_an_approved_skill_sees_no_change_and_no_ledger_write(self):
        before = self.run_node()                                # the candidate skill of the fixture is only proposed: not approved
        self.assertEqual(before['state'], 'produced')
        self.assertNotIn('approved_skill', self.body_of(self.inputs[0]))
        self.assertEqual(self.deliveries(), [])
        self.assertNotIn('approved_skill', json.loads(self.store.read_blob(before['receipt'])))
        # the same attempt prepared again without the skill layer gives the byte-identical input
        with mock.patch.object(skill_delivery, 'for_native', return_value=(None, None)):
            plain = self.executor.prepare(self.ledger, self.seen['control'], self.seen['task'], self.seen['node'], self.seen['attempt'])['prompt']
        self.assertEqual(plain, self.inputs[0])

    def test_restart_of_the_same_attempt_gets_the_same_skill_even_after_a_newer_revision(self):
        first = self.approve()
        self.run_node()
        self.new_revision('A newer revision arrives while the attempt exists.\n')
        again = self.executor.prepare(self.ledger, self.seen['control'], self.seen['task'], self.seen['node'], self.seen['attempt'])['prompt']
        self.assertEqual(self.body_of(again)['approved_skill'], self.body_of(self.inputs[0])['approved_skill'])
        self.assertEqual(self.body_of(again)['approved_skill']['revision'], first['revision'])
        self.assertEqual(len(self.deliveries()), 2)             # selected, delivered: the restart wrote nothing

    def test_selected_delivered_evaluated_outcome_comes_from_the_node_verification_not_the_caller(self):
        self.approve()
        self.run_node()
        with self.assertRaises(LedgerError): skill_delivery.evaluate_node(self.ledger, 'P1', 'C')       # nothing verified yet
        self.engine.verify(self.ledger, 'P1', 'C', self.checker('pass'))
        done = skill_delivery.evaluate_node(self.ledger, 'P1', 'C')
        self.assertEqual((done['status'], done['outcome']), ('evaluated', 'success'))
        self.assertEqual([s['step'] for s in done['steps']], ['selected', 'delivered', 'evaluated'])
        self.assertEqual(skill_delivery.evaluate_node(self.ledger, 'P1', 'C')['steps'], done['steps'])

    def test_selected_delivered_evaluated_by_the_engine_itself_after_verify(self):
        # coordinator (Codex R2): nobody has to call evaluate_node; engine.verify records it from the published result
        self.approve()
        self.run_node()
        self.engine.verify(self.ledger, 'P1', 'C', self.checker('pass'))
        self.assertEqual(len(self.deliveries()), 3)              # selected, delivered and evaluated, without anyone calling evaluate_node
        done = skill_delivery.evaluate_node(self.ledger, 'P1', 'C')                                     # already done: a no-op
        self.assertEqual(len(self.deliveries()), 3)
        self.assertEqual([s['step'] for s in done['steps']], ['selected', 'delivered', 'evaluated'])
        self.assertEqual(done['outcome'], 'success')

    def test_failed_verification_is_evaluated_as_failure(self):
        self.approve()
        self.run_node()
        self.engine.verify(self.ledger, 'P1', 'C', self.checker('fail'))
        self.assertEqual(skill_delivery.evaluate_node(self.ledger, 'P1', 'C')['outcome'], 'failure')


if __name__ == '__main__':
    unittest.main()
