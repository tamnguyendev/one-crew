"""T35a (W23b, R02) — outcome of every end, orchestrator interventions, class A against the REAL old version and the v1 consumers.

Fixtures (05 T35): state 1 has three roots ended three ways (accepted / stopped_with_report / failed = "HỎNG" of `plan report`: a failure with
no repair left); state 2 has the same three plus a root stopped at revision 1 and accepted at revision 2. All of them are built with the real v2
functions (propose / approve / verdict run / accept). The old version is the UNMODIFIED archive of ee46539 (tests/wf_oldversion.py). No model
is called (a counter on every door to a model is asserted at 0). The expected values below are read from the ledger events, never from the
code under test; the v1 outcome key list is read from onecrew/learning.py:12-34.

Counter-examples each one has: a writer that only records on acceptance fails the three-way check; a key by plan only collapses the
stop-then-accept case; a writer that does not call the v1 merge rule / interventions.record fails the call counters; an outcome carrying a v1
goal's identity changes `recommend`; a late outcome that counts as activity changes `plan report` (the check is on the report text).
"""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew import interventions, outcome_core, task_intake
from onecrew.ledger import Ledger, content_hash
from onecrew.v2 import compat, outcome, plan as plans, report, verdict
import tests.wf_oldversion as ov
from wf_r02 import BAD, OK, Sandbox, anchor, approved, count_kind, events, git_log, milestone, model_calls, pass_all, plan_json, run_cli, tree

REPO = str(Path(__file__).resolve().parents[1])
BASELINE = 'ee46539'                                   # the rollback target
PRE_W23B = 'f7dfbe4'                                   # the code before W23b (the R00 base of this branch)
CONSUMERS = str(Path(__file__).resolve().parent / 'wf_r02_v1_consumers.py')

# onecrew/learning.py:12-34 — the keys of a v1 learning.outcome
V1_KEYS = ('version', 'task', 'task_revision', 'spec_revision', 'phase', 'mode', 'provider', 'model', 'provider_handoffs', 'snapshot',
           'verification', 'acceptance', 'progress', 'recovery', 'managed_calls', 'usage', 'assistance', 'quality_score', 'routing_policy',
           'device_tested', 'candidate_files', 'signature', 'procedure', 'skills', 'timing', 'budget', 'budget_policy', 'repair_rounds',
           'test_results', 'id')
CLASS_A_KINDS = ('learning.outcome', 'control.intervention', 'context.entry')


def build_three(sandbox, ledger, root, prefix=''):
    """acc: accepted. stp: stopped_with_report (max_repairs 0). bad: a failure with no repair left, not stopped (HỎNG)."""
    approved(ledger, prefix + 'acc', plan_json(title='Accepted one'))
    pass_all(ledger, prefix + 'acc', root)
    plans.accept(ledger, prefix + 'acc', 'owner', 'ok', tree(root))
    approved(ledger, prefix + 'stp', plan_json(milestones=[milestone(argv=BAD, max_repairs=0)], title='Stopped one'))
    verdict.run(ledger, prefix + 'stp', 'M1', root)
    approved(ledger, prefix + 'bad', plan_json(milestones=[milestone(argv=BAD, max_repairs=1)], title='Failed one'))
    verdict.run(ledger, prefix + 'bad', 'M1', root)


def outcomes_of(ledger, name):
    return events(ledger, name, 'learning.outcome')


def expected_end(ledger, name):
    """(end, revision, artifact, spec_revision) of the root's LAST end, read from its events."""
    evs = events(ledger, name)
    revs = {p['revision']: p['sha'] for _, k, p in evs if k in ('plan.proposed', 'plan.amended')}
    accepted = [p for _, k, p in evs if k == 'plan.accepted']
    if accepted:
        return 'accepted', accepted[-1]['revision'], accepted[-1]['artifact_sha'], revs[accepted[-1]['revision']]
    stopped = [(s, p) for s, k, p in evs if k == 'milestone.stopped']
    verdicts = [(s, p) for s, k, p in evs if k == 'verdict.recorded']
    if stopped:
        seq, p = stopped[-1]
        art = [v['artifact_sha'] for s, v in verdicts if s < seq and v['revision'] == p['revision']][-1]
        return 'stopped_with_report', p['revision'], art, revs[p['revision']]
    last = verdicts[-1][1]
    return 'failed', last['revision'], last['artifact_sha'], revs[last['revision']]


class OutcomeTestCase(unittest.TestCase):
    sandbox = None

    @classmethod
    def setUpClass(cls):
        cls.sandbox = Sandbox()
        cls.root = cls.sandbox.project('P1')

    @classmethod
    def tearDownClass(cls):
        cls.sandbox.close()


class OutcomeEndTests(OutcomeTestCase):
    """E4, E13, E14, E15, E41 — state 1 (three ends) and state 2 (the same plus stop-then-accept)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.l1 = cls.sandbox.ledger(cls.root, cls.sandbox.state('S1'))
        with model_calls() as cls.model:
            build_three(cls.sandbox, cls.l1, cls.root)
        cls.l2 = cls.sandbox.ledger(cls.root, cls.sandbox.state('S2'))
        build_three(cls.sandbox, cls.l2, cls.root)
        approved(cls.l2, 'two', plan_json(milestones=[milestone(argv=BAD, max_repairs=0)], title='Stop then accept'))
        verdict.run(cls.l2, 'two', 'M1', cls.root)                                                   # stopped at revision 1
        cls.after_stop = len(outcomes_of(cls.l2, 'two'))
        plans.amend(cls.l2, 'two', plan_json(title='Stop then accept, fixed', milestones=[milestone(argv=OK)]), 'the milestone command was wrong', 'claude')
        plans.approve(cls.l2, 'two', 'owner', 'second approval')
        pass_all(cls.l2, 'two', cls.root)
        plans.accept(cls.l2, 'two', 'owner', 'ok', tree(cls.root))

    # E4: one outcome per root, v1's event kind and v1's keys, readable by the v1 reader
    def test_e4_each_root_has_one_v1_format_outcome(self):
        for name in ('acc', 'stp', 'bad'):
            rows = outcomes_of(self.l1, name)
            self.assertEqual(len(rows), 1, name)
            payload = rows[0][2]
            self.assertTrue(set(V1_KEYS) <= set(payload), f'{name}: keys missing from the v1 format: {set(V1_KEYS) - set(payload)}')
            self.assertEqual(payload['version'], 1)
            self.assertEqual(payload['task'], anchor(self.l1, name))
        self.assertEqual(count_kind(self.l1, 'learning.outcome'), 3)
        read = task_intake.outcomes(self.l1)                         # the v1 reader (core, in the wheel)
        self.assertEqual(sorted(r['task'] for r in read), sorted(anchor(self.l1, n) for n in ('acc', 'stp', 'bad')))

    # E13: each end has exactly one outcome; plan, revision and artifact are those of THAT end
    def test_e13_three_ends_match_their_end_event(self):
        problems = self.check_ends(self.l1, ('acc', 'stp', 'bad'))
        self.assertEqual(problems, [])
        phases = {n: outcomes_of(self.l1, n)[0][2]['phase'] for n in ('acc', 'stp', 'bad')}
        self.assertEqual(phases['acc'], 'completed')
        self.assertIn(phases['stp'], ('blocked', 'failed'))
        self.assertEqual(phases['bad'], 'failed')

    def check_ends(self, ledger, names):
        problems = []
        for name in names:
            end, revision, artifact, sha = expected_end(ledger, name)
            rows = [p for _, _, p in outcomes_of(ledger, name) if p['plan_revision'] == revision and p['end'] == end]
            if len(rows) != 1:
                problems.append(f'{name}: {len(rows)} outcomes for ({revision}, {end})'); continue
            p = rows[0]
            for field, want in (('plan', name), ('plan_revision', revision), ('snapshot', artifact), ('spec_revision', sha)):
                if p.get(field) != want: problems.append(f'{name}: {field} {p.get(field)!r} != {want!r}')
        return problems

    # counter-example for E13: a writer that records only on acceptance leaves the stopped and the failed root without one
    def test_e13_counter_acceptance_only_writer_is_caught(self):
        ledger = self.sandbox.ledger(self.root, self.sandbox.state('S1c'))
        real = outcome.ending

        def accepted_only(l, n):
            found = real(l, n)
            return found if found and found['end'] == 'accepted' else None
        with patch.object(outcome, 'ending', accepted_only):
            build_three(self.sandbox, ledger, self.root)
        problems = self.check_ends(ledger, ('acc', 'stp', 'bad'))
        self.assertEqual(sorted(p.split(':')[0] for p in problems), ['bad', 'stp'], 'the check must go red exactly for the stopped and the failed root')

    # E14: dedupe by (plan, revision, end); stop at 1 then accept at 2 = two rows; the second write is merged by the v1 rule
    def test_e14_second_write_adds_nothing_and_goes_through_the_v1_merge_rule(self):
        before = count_kind(self.l2, 'learning.outcome')
        calls = []
        real = outcome_core.append_outcome

        def spy(*args, **kwargs):
            calls.append(1)
            return real(*args, **kwargs)
        with patch.object(outcome_core, 'append_outcome', spy):
            for name in ('acc', 'stp', 'bad', 'two'):
                result = outcome.record(self.l2, name)
                self.assertFalse(result['recorded'], name)
        self.assertEqual(count_kind(self.l2, 'learning.outcome'), before)
        self.assertGreaterEqual(len(calls), 4, 'the v2 writer must call the v1 merge rule')

    def test_e14_stopped_at_1_then_accepted_at_2_has_two_rows(self):
        rows = outcomes_of(self.l2, 'two')
        self.assertEqual(self.after_stop, 1)
        self.assertEqual(len(rows), 2)
        self.assertEqual({(p['plan_revision'], p['end']) for _, _, p in rows}, {(1, 'stopped_with_report'), (2, 'accepted')})
        self.assertEqual(self.check_ends(self.l2, ('two',)), [])
        keys = [(p['plan_revision'], p['end']) for _, _, p in rows]
        self.assertEqual(len(keys), len(set(keys)))

    # counter-example for E14: a key by plan only would keep one row for `two`
    def test_e14_counter_key_by_plan_only_collapses_the_two_rows(self):
        by_plan = {p['plan'] for _, _, p in outcomes_of(self.l2, 'two')}
        self.assertEqual(len(by_plan), 1)
        self.assertEqual(len(outcomes_of(self.l2, 'two')), 2, 'a (plan)-only key would have given 1')

    # E15: the outcome step writes no lesson / skill and calls no model
    def test_e15_no_lesson_no_skill_no_model(self):
        self.assertEqual(self.model, [])
        for kind in ('learning.lesson', 'skill.state'):
            self.assertEqual(count_kind(self.l1, kind), 0, kind)
        with model_calls() as calls:
            before = (count_kind(self.l2, 'learning.lesson'), count_kind(self.l2, 'skill.state'))
            outcome.record(self.l2, 'acc')
            self.assertEqual((count_kind(self.l2, 'learning.lesson'), count_kind(self.l2, 'skill.state')), before)
        self.assertEqual(calls, [])

    # E41: no request is created for the user by an outcome
    def test_e41_outcome_creates_no_request(self):
        before = len(self.l2.requests())
        for name in ('acc', 'two'): outcome.record(self.l2, name)
        self.assertEqual(len(self.l2.requests()), before)

    # the class (00 §6.1): the three kinds are class A, and the writer asks the boundary guard before it writes
    def test_class_a_and_the_boundary_guard(self):
        for kind in CLASS_A_KINDS: self.assertEqual(compat.event_class(kind), 'A', kind)
        seen = []
        real = compat.check_write
        with patch.object(compat, 'check_write', lambda kind, payload, anchor_key: (seen.append((kind, anchor_key)), real(kind, payload, anchor_key))[1]):
            ledger = self.sandbox.ledger(self.root, self.sandbox.state('S1g'))
            approved(ledger, 'g', plan_json())
            pass_all(ledger, 'g', self.root)
            plans.accept(ledger, 'g', 'owner', 'ok', tree(self.root))
        self.assertIn(('learning.outcome', 'plan-ns:g'), seen)


class OutcomeFailureTests(OutcomeTestCase):
    """E17 (a failure never blocks the command), E18 (a late outcome moves nothing), E19 (interventions), the CLI."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.state = cls.sandbox.state('S3')
        cls.ledger = cls.sandbox.ledger(cls.root, cls.state)

    def cli(self, *args):
        return run_cli(['--project', str(self.root), '--state-root', str(self.state), *args])

    # E17
    def test_e17_an_outcome_failure_does_not_block_acceptance(self):
        approved(self.ledger, 'inj', plan_json())
        pass_all(self.ledger, 'inj', self.root)
        with patch.object(outcome, 'build_payload', side_effect=RuntimeError('boom')):
            code, out, err = self.cli('plan', 'accept', 'inj', '--by', 'owner', '--reference', 'ok', '--artifact-sha', tree(self.root))
        self.assertEqual(code, 0, out + err)
        self.assertEqual(json.loads(out)['status'], 'accepted')
        lines = [l for l in err.splitlines() if l.strip()]
        self.assertEqual(len(lines), 1, err)
        self.assertRegex(lines[0], r'^Outcome not recorded: RuntimeError: boom$')
        self.assertEqual(outcomes_of(self.ledger, 'inj'), [])
        self.assertIn('inj', [m['plan'] for m in outcome.missing(self.ledger)])
        outcome.record(self.ledger, 'inj')                                           # the measuring function's gap closes when recorded
        self.assertNotIn('inj', [m['plan'] for m in outcome.missing(self.ledger)])

    # E18: an outcome written late changes neither `plan report` nor `plan digest`
    def test_e18_late_outcome_does_not_change_report_or_digest(self):
        with patch.object(outcome, 'note', lambda *a, **k: None):
            approved(self.ledger, 'late', plan_json())
            pass_all(self.ledger, 'late', self.root)
            plans.accept(self.ledger, 'late', 'owner', 'ok', tree(self.root))
            approved(self.ledger, 'later', plan_json())
        before = (report.render_report(self.state, 'late'), report.render_digest(self.state))
        outcome.record(self.ledger, 'late')
        outcome.intervene(self.ledger, 'late', 'state.fix', 'a note written long after', actor='claude')
        db = sqlite3.connect(str(self.state / 'ledger.sqlite3'))
        db.execute("UPDATE events SET created_at='2099-01-01T00:00:00+00:00' WHERE kind IN ('learning.outcome','control.intervention')")
        db.commit(); db.close()
        after = (report.render_report(self.state, 'late'), report.render_digest(self.state))
        self.assertEqual(before[0], after[0])
        self.assertEqual(before[1], after[1])

    # E19
    def test_e19_one_intervention_through_interventions_record(self):
        approved(self.ledger, 'iv', plan_json())
        calls = []
        real = interventions.record

        def spy(*args, **kwargs):
            calls.append(kwargs.get('key'))
            return real(*args, **kwargs)
        with patch.object(interventions, 'record', spy):
            first = outcome.intervene(self.ledger, 'iv', 'state.fix', 'the entry repaired a stuck state by hand', actor='claude', key='fix-1')
            again = outcome.intervene(self.ledger, 'iv', 'state.fix', 'the entry repaired a stuck state by hand', actor='claude', key='fix-1')
        self.assertGreaterEqual(len(calls), 1)
        rows = events(self.ledger, 'iv', 'control.intervention')
        self.assertEqual(len(rows), 1)
        payload = rows[0][2]
        self.assertEqual(payload['actor'], 'claude')
        self.assertEqual(payload['reason'], 'the entry repaired a stuck state by hand')
        self.assertEqual(payload['details']['kind'], 'state.fix')
        self.assertEqual(payload['key'], 'fix-1')
        self.assertEqual(first, again)
        with self.ledger.transaction() as conn:
            row = conn.execute("SELECT task_id FROM events WHERE kind='control.intervention' AND json_extract(payload,'$.key')='fix-1'").fetchone()
        self.assertEqual(row['task_id'], anchor(self.ledger, 'iv'))                  # attached to the root
        with self.assertRaises(Exception):
            outcome.intervene(self.ledger, 'iv', 'state.fix', '   ', actor='claude')  # a reason is required

    def test_e19_an_owner_actor_cannot_be_recorded_from_an_ai_session(self):
        approved(self.ledger, 'iv2', plan_json())
        with patch.dict(os.environ, {'CLAUDE_CODE_CHILD_SESSION': '1'}):
            with self.assertRaises(Exception):
                outcome.intervene(self.ledger, 'iv2', 'state.fix', 'signed as the owner', actor='owner')
        self.assertEqual(events(self.ledger, 'iv2', 'control.intervention'), [])

    # the CLI verbs (the router of the installed package)
    def test_cli_outcome_record_show_missing_intervene(self):
        approved(self.ledger, 'cli1', plan_json())
        pass_all(self.ledger, 'cli1', self.root)
        with patch.object(outcome, 'note', lambda *a, **k: None):
            plans.accept(self.ledger, 'cli1', 'owner', 'ok', tree(self.root))
        code, out, _ = self.cli('outcome', 'missing')
        self.assertEqual(code, 0)
        self.assertIn('cli1', [m['plan'] for m in json.loads(out)['missing']])
        code, out, _ = self.cli('outcome', 'record', 'cli1')
        self.assertEqual(code, 0, out)
        self.assertTrue(json.loads(out)['recorded'])
        code, out, _ = self.cli('outcome', 'record', 'cli1')
        self.assertFalse(json.loads(out)['recorded'])
        code, out, _ = self.cli('outcome', 'show', 'cli1')
        self.assertEqual(len(json.loads(out)['outcomes']), 1)
        code, out, _ = self.cli('outcome', 'intervene', 'cli1', '--kind', 'state.fix', '--reason', 'by hand', '--actor', 'claude', '--key', 'k1')
        self.assertEqual(code, 0, out)
        self.assertEqual(len(events(self.ledger, 'cli1', 'control.intervention')), 1)
        code, out, _ = self.cli('outcome', 'record', 'no-such-plan')
        self.assertEqual(code, 2)


@unittest.skipUnless(shutil.which('git'), 'git is required to archive the old version')
class OldCodeReproductionTests(unittest.TestCase):
    """E16: on the code before W23b, accepting a root leaves no learning.outcome (the test is red for exactly that); with W23b there is one."""

    PROBE = '''
import json, sys
from pathlib import Path
from onecrew.ledger import Ledger
from onecrew.v2 import plan as plans, verdict
from onecrew.v2.verifiers import command
project, state, contract = sys.argv[1:4]
ledger = Ledger(Path(project), Path(state))
plans.propose(ledger, 'p', json.load(open(contract)), 'claude')
plans.approve(ledger, 'p', 'owner', 'r')
verdict.run(ledger, 'p', 'M1', Path(project))
plans.accept(ledger, 'p', 'owner', 'r', command.artifact_sha(Path(project)))
with ledger.transaction() as c:
    print(json.dumps({'outcomes': c.execute("SELECT COUNT(*) FROM events WHERE kind='learning.outcome'").fetchone()[0]}))
'''

    @classmethod
    def setUpClass(cls):
        cls.runs = ov._short_runs()
        cls.pre = ov.archive(PRE_W23B, REPO, cls.runs)
        cls.proj = ov.git_project(cls.runs, 'PX')
        cls.script = cls.runs / 'probe.py'
        cls.script.write_text(cls.PROBE, encoding='utf-8')
        cls.contract = cls.runs / 'c.json'
        cls.contract.write_text(json.dumps(ov.contract('X')), encoding='utf-8')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.runs, ignore_errors=True)

    def run_probe(self, tree_path, tag):
        env = {k: v for k, v in os.environ.items() if k not in ('ONECREW_ACTOR', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION', 'PYTHONPATH')}
        env.update(PYTHONPATH=str(tree_path), PYTHONDONTWRITEBYTECODE='1')
        done = subprocess.run([sys.executable, '-X', 'utf8', str(self.script), str(self.proj), str(self.runs / ('state-' + tag)), str(self.contract)],
                              env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=str(self.proj))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        return json.loads(done.stdout.strip().splitlines()[-1])['outcomes']

    def test_e16_accepting_leaves_no_outcome_before_w23b_and_one_after(self):
        self.assertEqual(self.run_probe(self.pre, 'pre'), 0, 'before W23b an accepted root has no learning.outcome (the defect)')
        self.assertEqual(self.run_probe(REPO, 'new'), 1, 'with W23b an accepted root has exactly one')


@unittest.skipUnless(shutil.which('git'), 'git is required to archive the old version')
class ClassAAgainstOldVersionTests(unittest.TestCase):
    """E39: learning.outcome / control.intervention (and context.entry) written by W23b on a ledger keep S, G, C of the REAL old version, and the
    v1 consumers on the same ledger run without error and give the same answers for v1 tasks."""

    @classmethod
    def setUpClass(cls):
        cls.runs = ov._short_runs()
        cls.old_tree = ov.archive(BASELINE, REPO, cls.runs)
        cls.old = ov.OldVersion(cls.old_tree)
        cls.sandbox = Sandbox()
        cls.root = cls.sandbox.project('PO')
        cls.state = cls.sandbox.state('SO')
        cls.ledger = cls.sandbox.ledger(cls.root, cls.state)
        cls.ledger._wf_legacy = True
        cls.ledger._wf_old = cls.old
        build_three(cls.sandbox, cls.ledger, cls.root)
        approved(cls.ledger, 'open', plan_json(title='Still open'))
        for name in ('acc', 'stp', 'open'):
            outcome.intervene(cls.ledger, name, 'state.fix', f'a by-hand repair on {name}', actor='claude', key='iv-' + name)
        # the plain copy: the same ledger with every class-A event removed (the "without" reading of the old version)
        cls.plain = cls.sandbox.state('SO-plain')
        shutil.copytree(cls.state, cls.plain)
        db = sqlite3.connect(str(cls.plain / 'ledger.sqlite3'))
        db.execute(f"DELETE FROM events WHERE kind IN ({','.join('?' * len(CLASS_A_KINDS))})", CLASS_A_KINDS)
        db.commit(); db.close()

    @classmethod
    def tearDownClass(cls):
        cls.sandbox.close()
        shutil.rmtree(cls.runs, ignore_errors=True)

    def test_e39_old_version_keeps_S_G_C_with_the_class_A_events(self):
        self.assertGreaterEqual(count_kind(self.ledger, 'learning.outcome'), 3)
        self.assertGreaterEqual(count_kind(self.ledger, 'control.intervention'), 3)
        for name in ('acc', 'stp', 'bad', 'open'):
            without = ov.read(self.old, self.root, self.plain, name)
            with_a = ov.read(self.old, self.root, self.state, name)
            diff = ov.compare(without, with_a)
            self.assertTrue(diff['S'], f'{name}: S changed {without["S"]} vs {with_a["S"]}')
            self.assertTrue(diff['G'], f'{name}: G changed')
            self.assertTrue(diff['C'], f'{name}: C changed')
            self.assertFalse(with_a['read_blocked'], name)
        status = {n: ov.read(self.old, self.root, self.state, n)['S']['status'] for n in ('acc', 'stp', 'open')}
        self.assertEqual(status, {'acc': 'accepted', 'stp': 'stopped_with_report', 'open': 'approved'})

    def consumers(self, tree_path, state, v2_task, v1_tasks, goal, provider, model):
        env = {k: v for k, v in os.environ.items() if k not in ('ONECREW_ACTOR', 'CLAUDE_CODE_CHILD_SESSION', 'PYTHONPATH')}
        env.update(PYTHONPATH=str(tree_path), PYTHONDONTWRITEBYTECODE='1')
        done = subprocess.run([sys.executable, '-X', 'utf8', CONSUMERS, str(self.root), str(state), goal, provider, model, v2_task, *v1_tasks],
                              env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=str(self.root))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        return json.loads(done.stdout.strip().splitlines()[-1])

    def v1_world(self):
        """A copy of the plain state with three v1 tasks that each have a good v1 learning.outcome for the same goal (so `recommend` has history)."""
        state = self.sandbox.state('V1-' + os.urandom(3).hex())
        shutil.copytree(self.plain, state)
        ledger = Ledger(self.root, state)
        goal = 'Add the export button to the report page'
        tasks = []
        for index in range(3):
            task = task_intake.submit(ledger, goal, f'v1-goal-{index}', mode='audit')['id']
            tasks.append(task)
            data = dict.fromkeys(V1_KEYS)
            data.update(version=1, task=task, task_revision=1, spec_revision=content_hash(goal), phase='completed', mode='audit', provider='codex',
                        model='gpt-x', snapshot='s' * 40, verification='passed', acceptance='accepted', managed_calls=5 + index,
                        timing={'wall_seconds': 60 + index}, test_results={'passed': 1, 'failed': 0})
            data['id'] = content_hash({k: v for k, v in data.items() if k != 'id'})
            with ledger.transaction(write=True) as conn:
                ledger._event(conn, task, 'learning.outcome', data)
        return state, ledger, goal, tasks

    def test_e39_v1_consumers_give_the_same_answers_for_v1_tasks(self):
        state, ledger, goal, tasks = self.v1_world()
        report_rows = {}
        for label, tree_path in (('checkout', REPO), ('rollback-target', self.old_tree)):
            before = self.consumers(tree_path, state, '-', tasks, goal, 'codex', 'gpt-x')
            self.assertEqual(before['task_intake.recommend']['classification'], 'repeated_verified')
            # now the ledger also holds the v2 roots' outcomes (copied from the real state) — same project, same ledger
            mixed = self.sandbox.state('MIX-' + label)
            shutil.copytree(state, mixed)
            shutil.rmtree(mixed / 'plans', ignore_errors=True); shutil.copytree(self.state / 'plans', mixed / 'plans')
            self.merge_v2_events(mixed)
            anchors = anchor(Ledger(self.root, mixed), 'acc')
            after = self.consumers(tree_path, mixed, anchors, tasks, goal, 'codex', 'gpt-x')
            for key in ('task_intake.recommend', 'budget_policy.recommend', 'eval_observe.v1'):
                self.assertEqual(before[key], after[key], f'{label}: {key} changed for v1 tasks')
            self.assertEqual(after['skills.refresh'], before['skills.refresh'])
            self.assertEqual(after['task_intake.outcomes']['rows'], before['task_intake.outcomes']['rows'] + 3, label)
            self.assertEqual(after['skills.latest']['rows'], before['skills.latest']['rows'] + 3)
            v2_anchors = set(after['task_intake.outcomes']['tasks']) - set(before['task_intake.outcomes']['tasks'])
            self.assertEqual(set(after['skills.latest']['good']) - set(before['skills.latest']['good']), {anchor(Ledger(self.root, mixed), 'acc')},
                             'only the accepted v2 root counts as a good outcome for skills.latest (it has no signature, so refresh skips it)')
            self.assertEqual(set(before['skills.latest']['good']) - set(after['skills.latest']['good']), set())
            self.assertTrue(v2_anchors and v2_anchors.isdisjoint(tasks))
            report_rows[label] = {k: after[k] for k in ('task_intake.outcomes', 'learning.outcomes', 'skills.latest')}
        # the table the task report states: which consumer reads a v2 root's outcome, and how
        self.__class__.consumer_table = report_rows

    def merge_v2_events(self, mixed):
        """Copy the v2 roots' tasks and class-A events of the real state into `mixed` (same project id, same ledger schema)."""
        src = sqlite3.connect(str(self.state / 'ledger.sqlite3')); src.row_factory = sqlite3.Row
        dst = sqlite3.connect(str(mixed / 'ledger.sqlite3'))
        tasks = src.execute("SELECT * FROM tasks WHERE request_key LIKE 'plan:%'").fetchall()
        for row in tasks:
            columns = row.keys()
            dst.execute(f"INSERT OR IGNORE INTO tasks({','.join(columns)}) VALUES({','.join('?' * len(columns))})", tuple(row))
        marks = ','.join('?' * len(CLASS_A_KINDS))
        for row in src.execute(f"SELECT task_id, kind, payload, created_at FROM events WHERE kind IN ({marks})", CLASS_A_KINDS):
            dst.execute('INSERT INTO events(task_id, kind, payload, created_at) VALUES (?,?,?,?)', tuple(row))
        dst.commit(); dst.close(); src.close()

    # E40: the counter-example — an outcome that carries a v1 goal's identity WOULD change `recommend`; the real v2 outcome does not
    def test_e40_a_v2_outcome_never_matches_a_v1_goal_but_a_forged_one_would(self):
        state, ledger, goal, tasks = self.v1_world()
        plain = self.consumers(REPO, state, '-', tasks, goal, 'codex', 'gpt-x')['task_intake.recommend']
        forged = self.sandbox.state('FORGED')
        shutil.copytree(state, forged)
        anchor_task = task_intake.submit(Ledger(self.root, forged), 'Plan forged', 'plan:forged', mode='audit')['id']
        bad = dict.fromkeys(V1_KEYS)
        bad.update(version=1, task=anchor_task, spec_revision=content_hash(goal), phase='failed', mode='audit', provider='codex', model='gpt-x',
                   snapshot='x', verification='failed', acceptance='not_requested', managed_calls=1, timing={'wall_seconds': 1})
        bad['id'] = content_hash({k: v for k, v in bad.items() if k != 'id'})
        led = Ledger(self.root, forged)
        with led.transaction(write=True) as conn:
            led._event(conn, anchor_task, 'learning.outcome', bad)
        changed = self.consumers(REPO, forged, '-', tasks, goal, 'codex', 'gpt-x')['task_intake.recommend']
        self.assertNotEqual(plain, changed, 'the check must be able to see a v2 outcome that mimics a v1 goal')
        for _, _, payload in outcomes_of(self.ledger, 'acc'):
            self.assertNotEqual(payload['spec_revision'], content_hash(goal))
            self.assertNotIn(payload['mode'], ('audit', 'change', 'delivery', 'branch'))
            self.assertIsNone(payload['provider']); self.assertIsNone(payload['model'])
            self.assertIsNone(payload['signature'])                  # skills.refresh skips a row without a signature


if __name__ == '__main__':
    unittest.main()
