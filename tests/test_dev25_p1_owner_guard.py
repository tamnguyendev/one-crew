"""2.5.0.dev25: the two P1 of the Fable 5.2 review of dev24 (D:/OneCrewRuns/v25/review-fable52/BAO-CAO-REVIEW-dev24-fable52.vi.md), design
D:/OneCrewRuns/v25/dev25/THIET-KE-dev25.vi.md approved by the owner 11/11 ("A") with the three additions of the design review.

- P1-1: a process OneCrew starts to run the project's code (a command check, a step-0 precondition, a model CLI) ran without any AI marker, so a
  check script could approve, accept or switch enforcement off as the owner. dev25: such a process carries ONECREW_VERIFIER; an owner verb there
  is refused unless every ledger the process opened lies in its temporary folder (fixed once at import). REDUCED, not closed: the LimitsAsKnown
  cases assert what still gets through (a script that removes the marker on purpose, or starts onecrew with another TEMP).
- P1.c (design review): a process that declares a non-owner actor (ONECREW_ACTOR=onecrew, a OneCrew worker) cannot switch enforcement off nor run
  the support/hotfix owner verbs.
- P1-2: `hook export <plan>` (and every other writer of the hooks' file: amend, verdict) could put another plan, an accepted or a wider one, in
  place of the plan the hooks enforce. dev25: one rule in active_plan.export; refreshing the governing plan stays open to everyone.

Red on 7052cee (the cases that need the new names fail at import or assert the old, open behaviour).
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import Ledger, LedgerError
from onecrew.v2 import active_plan, gate, hook_cli, ownership, plan as plans, verdict
from onecrew.v2 import hotfix, support, step0
from onecrew.v2 import verification_evidence
from onecrew.v2.verifiers import command
from test_v2_l1 import PY, milestone, plan_json

REPO = Path(__file__).resolve().parents[1]
AI = {'CLAUDE_CODE_CHILD_SESSION': '1'}
MARKERS = ('ONECREW_ACTOR', 'ONECREW_V2_REQUIRE_PLAN', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION', 'ONECREW_VERIFIER')


def real(path):
    return os.path.normcase(os.path.realpath(str(path)))


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'project'; self.root.mkdir()
        self.state = self.base / 'state'
        # the temporary folder a check process starts with: a sibling of the ledger, so the ledger is a REAL one for that process
        self.child_temp = self.base / 'child-temp'; self.child_temp.mkdir()
        env = patch.dict(os.environ); env.start(); self.addCleanup(env.stop)
        for name in MARKERS: os.environ.pop(name, None)
        opened = patch.object(ownership, '_OPENED', set(), create=True); opened.start(); self.addCleanup(opened.stop)
        self.git('init', '-q'); self.git('config', 'user.name', 'T'); self.git('config', 'user.email', 't@localhost')
        (self.root / 'a.txt').write_text('one\n'); (self.root / 'b.txt').write_text('one\n')
        self.extra_files()
        self.git('add', '.'); self.git('commit', '-q', '-m', 'base')
        self.ledger = Ledger(self.root, self.state)

    def extra_files(self):
        pass

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.PIPE).decode().strip()

    def approved(self, name):
        with self.ledger.transaction() as conn:
            state = plans.derive(self.ledger, conn, name)
        return bool(state and state['approved'])

    def new_plan(self, name, approve=True, **extra):
        plans.propose(self.ledger, name, plan_json(**extra), 'claude')
        if approve: plans.approve(self.ledger, name, 'owner', 'ok')

    def child_temp_env(self):
        """The check process starts with TEMP = child_temp (verifier_env keeps the caller's TEMP)."""
        return patch.dict(os.environ, {'TEMP': str(self.child_temp), 'TMP': str(self.child_temp)})


def inner_cli(repo, root, state, out, *args):
    """A check script that calls `onecrew <args>` through the installed entry (python -m onecrew), without touching the environment it got."""
    return (f"import os, subprocess, sys\n"
            f"p = subprocess.run([{PY!r}, '-X', 'utf8', '-m', 'onecrew', '--project', {str(root)!r}, '--state-root', {str(state)!r}, *{list(args)!r}],\n"
            f"                   env=dict(os.environ, PYTHONPATH={str(repo)!r}), capture_output=True, text=True, encoding='utf-8', errors='replace')\n"
            f"open({str(out)!r}, 'w', encoding='utf-8').write(str(p.returncode) + '\\n' + p.stdout + p.stderr)\n")


# ---- P1-1 --------------------------------------------------------------------------------------------------------------------------

class CheckProcessCannotTakeOwnerDecisions(Base):
    def extra_files(self):
        self.out = self.base / 'inner.txt'
        (self.root / 'check.py').write_text(inner_cli(REPO, self.root, self.state, self.out, 'plan', 'approve', 'OTHER', '--by', 'owner', '--reference', 'x'),
                                            encoding='utf-8')
        (self.root / 'off.py').write_text(f"import sys\nsys.path.insert(0, {str(REPO)!r})\n"
                                          f"from onecrew.ledger import Ledger\nfrom onecrew.v2 import gate\n"
                                          f"try:\n    gate.set_enforced(Ledger({str(self.root)!r}, {str(self.state)!r}), False, 'owner', 'x'); r = 'PASSED'\n"
                                          f"except Exception as e:\n    r = 'REFUSED ' + str(e)\n"
                                          f"open({str(self.base / 'off.txt')!r}, 'w', encoding='utf-8').write(r)\n", encoding='utf-8')

    def test_1_the_verifier_environment_carries_the_marker_and_not_claudecode(self):
        os.environ['CLAUDECODE'] = '1'; os.environ['CLAUDE_CODE_CHILD_SESSION'] = '1'
        env = command.verifier_env(self.root)
        self.assertEqual(env.get('ONECREW_VERIFIER'), '1')
        self.assertNotIn('CLAUDECODE', env)                         # a reviewer's `claude` CLI still runs (no nested-session refusal)

    def test_2_require_owner_in_the_verifier_environment_is_refused_on_a_real_ledger(self):
        with self.child_temp_env():
            env = command.verifier_env(self.root)
        probe = (f"import sys; sys.path.insert(0, {str(REPO)!r})\n"
                 f"from onecrew.ledger import Ledger, LedgerError\nfrom onecrew.v2 import plan\n"
                 f"Ledger({str(self.root)!r}, {str(self.state)!r})\n"
                 f"try:\n    plan.require_owner('owner', 'Approving a plan'); print('PASSED')\n"
                 f"except LedgerError as e:\n    print('REFUSED', e)\n")
        out = subprocess.run([PY, '-c', probe], env=env, capture_output=True, text=True, encoding='utf-8').stdout
        self.assertIn('REFUSED', out, out)
        self.assertIn('OneCrew check', out)

    def test_3_a_command_check_that_approves_another_plan_does_not_approve_it(self):
        self.new_plan('OTHER', approve=False)
        self.new_plan('P', milestones=[milestone(argv=[PY, 'check.py'])])
        with self.child_temp_env():
            verdict.run(self.ledger, 'P', 'M1', self.root)
        self.assertFalse(self.approved('OTHER'))
        text = self.out.read_text(encoding='utf-8')
        self.assertTrue(text.startswith('2'), text)
        self.assertIn('ONECREW_VERIFIER', text)

    def test_4_a_command_check_cannot_switch_enforcement_off(self):
        gate.set_enforced(self.ledger, True, 'owner', 'on')
        self.new_plan('P', milestones=[milestone(argv=[PY, 'off.py'])])
        with self.child_temp_env(), patch.dict(os.environ, {'ONECREW_V2_REQUIRE_PLAN': '0'}):
            verdict.run(self.ledger, 'P', 'M1', self.root)
        self.assertTrue(json.loads((self.state / 'plans' / 'policy.json').read_text(encoding='utf-8'))['require_plan'])
        self.assertTrue((self.base / 'off.txt').read_text(encoding='utf-8').startswith('REFUSED'))

    def test_6_a_check_that_runs_owner_verbs_on_its_own_temporary_ledger_still_works(self):
        script = (f"import os, subprocess, sys, tempfile\nsys.path[:0] = [{str(REPO)!r}, {str(REPO / 'tests')!r}]\n"
                  f"from pathlib import Path\nfrom onecrew.ledger import Ledger\nfrom onecrew.v2 import plan as plans\nfrom test_v2_l1 import plan_json\n"
                  f"base = Path(tempfile.mkdtemp()); root = base / 'p'; root.mkdir()\n"
                  f"g = lambda *a: subprocess.check_output(['git', '-C', str(root), *a])\n"
                  f"g('init', '-q'); g('config', 'user.name', 'T'); g('config', 'user.email', 't@localhost')\n"
                  f"(root / 'a.txt').write_text('one'); g('add', '.'); g('commit', '-q', '-m', 'b')\n"
                  f"ledger = Ledger(root, base / 'state')\n"
                  f"plans.propose(ledger, 'T', plan_json(), 'claude'); plans.approve(ledger, 'T', 'owner', 'ok')\n"
                  f"open({str(self.base / 'own.txt')!r}, 'w').write('APPROVED')\n")
        (self.root / 'own.py').write_text(script, encoding='utf-8'); self.git('add', '.'); self.git('commit', '-q', '-m', 'own')
        self.new_plan('P', milestones=[milestone(argv=[PY, 'own.py'])])
        with self.child_temp_env():
            result = verdict.run(self.ledger, 'P', 'M1', self.root)
        self.assertEqual((self.base / 'own.txt').read_text(), 'APPROVED', result)

    def test_11_the_owners_shell_approves_and_enforces_as_before(self):
        self.new_plan('P')
        self.assertTrue(self.approved('P'))
        gate.set_enforced(self.ledger, True, 'owner', 'on')
        self.assertIsNone(ownership.refuse_in_ai_session('x'))

    def test_12_a_model_cli_started_by_onecrew_cannot_approve(self):
        self.new_plan('OTHER', approve=False)
        fake = self.base / 'fake_cli.py'
        fake.write_text(inner_cli(REPO, self.root, self.state, self.out, 'plan', 'approve', 'OTHER', '--by', 'owner', '--reference', 'x'), encoding='utf-8')
        from onecrew.v2 import providers
        with self.child_temp_env():
            env = command.verifier_env(self.root)
        providers.run_process([PY, str(fake)], None, str(self.base), env, 1)
        self.assertFalse(self.approved('OTHER'))
        self.assertTrue(self.out.read_text(encoding='utf-8').startswith('2'))


class PreconditionCannotTakeOwnerDecisions(Base):
    def extra_files(self):
        self.out = self.base / 'pre.txt'
        (self.root / 'pre.py').write_text(inner_cli(REPO, self.root, self.state, self.out, 'plan', 'approve', 'OTHER', '--by', 'owner', '--reference', 'x'),
                                          encoding='utf-8')

    def test_5_a_step0_precondition_run_by_the_owners_approve_cannot_approve_another_plan(self):
        self.new_plan('OTHER', approve=False)
        pre = [{'id': 'P1', 'check': 'path_exists', 'args': {'path': 'a.txt'}, 'why': 'the file is there'},
               {'id': 'P2', 'check': 'command_ok', 'args': {'argv': [PY, 'pre.py'], 'cwd': '.', 'max_minutes': 1}, 'why': 'the tool runs'}]
        plans.propose(self.ledger, 'MAIN', plan_json(preconditions=pre), 'claude')
        with self.child_temp_env():
            plans.approve(self.ledger, 'MAIN', 'owner', 'ok')          # the owner's own shell: no marker at all
        self.assertTrue(self.approved('MAIN'))
        self.assertFalse(self.approved('OTHER'))
        self.assertIn('ONECREW_VERIFIER', self.out.read_text(encoding='utf-8'))

    def test_the_precondition_environment_carries_the_marker(self):
        seen = {}
        real_popen = subprocess.Popen

        def spy(argv, **kw):
            seen.update(kw.get('env') or {})
            return real_popen(argv, **kw)
        with patch.object(step0.subprocess, 'Popen', side_effect=spy):
            step0._run(self.ledger, [PY, '-c', 'print(1)'], self.root, 1)
        self.assertEqual(seen.get('ONECREW_VERIFIER'), '1')


class MarkerRule(Base):
    def test_8_with_the_marker_and_no_ledger_opened_it_is_an_ai_session(self):
        os.environ['ONECREW_VERIFIER'] = '1'
        ownership._OPENED.clear()
        self.assertTrue(ownership.in_ai_session())

    def test_only_temporary_ledgers_lift_the_marker(self):
        os.environ['ONECREW_VERIFIER'] = '1'
        with patch.object(ownership, 'TEMP_ROOT', real(self.child_temp), create=True):
            ownership._OPENED.clear(); ownership.note_state_root(self.child_temp / 'state')
            self.assertFalse(ownership.in_ai_session())
            ownership.note_state_root(self.state)                      # a real ledger opened too
            self.assertTrue(ownership.in_ai_session())
            self.assertEqual(ownership.session_info()['started_by'], 'onecrew-check')

    def test_review_addition_changing_tempfile_or_TEMP_later_does_not_widen_the_exception(self):
        os.environ['ONECREW_VERIFIER'] = '1'
        with patch.object(ownership, 'TEMP_ROOT', real(self.child_temp), create=True), patch.object(tempfile, 'tempdir', str(self.base)), \
                patch.dict(os.environ, {'TEMP': str(self.base), 'TMP': str(self.base), 'TMPDIR': str(self.base)}):
            ownership._OPENED.clear()
            Ledger(self.root, self.state)                                 # the real ledger, now "under" the moved temp folder
            with self.assertRaises(LedgerError) as caught:
                plans.require_owner('owner', 'Approving a plan')
            self.assertIn('OneCrew check', str(caught.exception))

    def test_7_router_refuses_a_real_state_root_and_a_junction_to_it_but_not_a_temporary_one(self):
        env = dict(os.environ, PYTHONPATH=str(REPO), ONECREW_VERIFIER='1', TEMP=str(self.child_temp), TMP=str(self.child_temp))
        env.pop('TMPDIR', None)

        def run(state):
            p = subprocess.run([PY, '-X', 'utf8', '-m', 'onecrew', '--project', str(self.root), '--state-root', str(state), 'plan', 'approve', 'NOPE',
                                '--by', 'owner', '--reference', 'x'], env=env, capture_output=True, text=True, encoding='utf-8', errors='replace')
            return p.returncode, p.stdout + p.stderr
        code, text = run(self.state)
        self.assertEqual(code, 2, text); self.assertIn('ONECREW_VERIFIER', text)
        code, text = run(self.child_temp / 'state')
        self.assertNotIn('ONECREW_VERIFIER', text)                         # refused for another reason (no such plan), not by the guard
        link = self.child_temp / 'link'
        made = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(self.state)], capture_output=True) if os.name == 'nt' else None
        if os.name != 'nt':
            os.symlink(self.state, link); made = True
        if made is not None and link.exists():
            code, text = run(link)
            self.assertEqual(code, 2, text); self.assertIn('ONECREW_VERIFIER', text)

    def test_9_the_marker_is_not_part_of_the_fingerprint(self):
        env = command.verifier_env(self.root)
        without = {k: v for k, v in env.items() if k != 'ONECREW_VERIFIER'}
        self.assertEqual(verification_evidence.environment(env), verification_evidence.environment(without))

    def test_9_a_pass_stays_current_after_the_run(self):
        self.new_plan('P')
        verdict.run(self.ledger, 'P', 'M1', self.root)
        view = plans.show(self.ledger, 'P')
        row = next(m for m in view['milestones'] if m['id'] == 'M1')
        self.assertEqual(row['state'], 'passed'); self.assertFalse(row.get('stale'))

    def test_10_hotfix_and_support_owner_verbs_are_refused_under_the_marker(self):
        os.environ['ONECREW_VERIFIER'] = '1'
        ownership._OPENED.clear(); ownership.note_state_root(self.state)
        with patch.object(ownership, 'TEMP_ROOT', real(self.child_temp), create=True):
            with self.assertRaises(LedgerError): hotfix._refuse_ai('support target add')
            with self.assertRaises(LedgerError): support._actor('owner')
            with self.assertRaises(LedgerError): ownership.refuse_in_ai_session('support confirm')


class DeclaredActor(Base):
    """P1.c: a OneCrew worker (ONECREW_ACTOR=onecrew, no Claude marker)."""
    def test_a_worker_cannot_switch_enforcement_off(self):
        gate.set_enforced(self.ledger, True, 'owner', 'on')
        os.environ['ONECREW_ACTOR'] = 'onecrew'
        with self.assertRaises(LedgerError) as caught:
            gate.set_enforced(self.ledger, False, 'owner', 'off')
        self.assertIn('ONECREW_ACTOR=onecrew', str(caught.exception))
        self.assertTrue(gate.enforced(self.ledger))

    def test_a_worker_cannot_run_the_support_and_hotfix_owner_verbs(self):
        os.environ['ONECREW_ACTOR'] = 'codex'
        with self.assertRaises(LedgerError): hotfix._refuse_ai('support rollback')
        with self.assertRaises(LedgerError): support._actor('owner')
        self.assertEqual(ownership.session_info()['ai_session'], True)

    def test_the_owner_declared_as_owner_is_not_refused(self):
        for actor in ('owner', 'user', ''):
            os.environ['ONECREW_ACTOR'] = actor
            self.assertFalse(ownership.in_ai_session(), actor)
            self.assertIsNone(ownership.refuse_in_ai_session('x'), actor)

    def test_a_worker_cannot_switch_the_governing_plan(self):
        self.new_plan('B'); self.new_plan('A')
        with patch.dict(os.environ, {'ONECREW_ACTOR': 'onecrew'}):
            self.assertIsNone(active_plan.export(self.ledger, 'B'))
        self.assertEqual(json.loads(active_plan.project_file(self.root).read_text(encoding='utf-8'))['plan'], 'A')

    def test_review_p2_1_a_v1_worker_command_carries_the_marker_and_cannot_approve(self):
        from types import SimpleNamespace
        from onecrew import work_tools
        self.new_plan('OTHER', approve=False)
        work_root = self.base / 'work'
        with patch.dict(os.environ, {'ONECREW_WORK_ROOT': str(work_root), 'ONECREW_ACTOR': 'onecrew'}):
            env = work_tools.environment(SimpleNamespace(ledger=self.ledger), 'task-1')
        self.assertEqual(env.get('ONECREW_VERIFIER'), '1')
        out = self.base / 'v1.txt'
        script = inner_cli(REPO, self.root, self.state, out, 'plan', 'approve', 'OTHER', '--by', 'owner', '--reference', 'x')
        subprocess.run([PY, '-c', script], env=env, capture_output=True)
        self.assertFalse(self.approved('OTHER'))
        self.assertIn('ONECREW_VERIFIER', out.read_text(encoding='utf-8'))


class OldGoverningCopy(Base):
    def test_review_p3_4_a_copy_without_anchor_is_compared_by_plan_name(self):
        self.new_plan('A')
        path = active_plan.project_file(self.root)
        value = json.loads(path.read_text(encoding='utf-8')); value.pop('anchor', None); active_plan._write(path, value)
        with patch.dict(os.environ, AI):
            self.assertIsNotNone(active_plan.export(self.ledger, 'A'))      # the AI may still refresh the governing plan


class LimitsAsKnown(Base):
    """What dev25 does NOT close (LOI-DA-BIET): asserted, so the documentation cannot claim more than the code does."""
    def test_limit_a_script_that_removes_the_marker_on_purpose_still_gets_through(self):
        self.new_plan('OTHER', approve=False)
        out = self.base / 'popped.txt'
        script = (f"import os, sys\nos.environ.pop('ONECREW_VERIFIER', None)\nsys.path.insert(0, {str(REPO)!r})\n"
                  f"from onecrew.ledger import Ledger\nfrom onecrew.v2 import plan\n"
                  f"plan.approve(Ledger({str(self.root)!r}, {str(self.state)!r}), 'OTHER', 'owner', 'x')\n"
                  f"open({str(out)!r}, 'w').write('APPROVED')\n")
        with self.child_temp_env():
            env = command.verifier_env(self.root)
        subprocess.run([PY, '-c', script], env=env, capture_output=True)
        self.assertTrue(self.approved('OTHER'))                            # known limit: only signing the owner's decisions (roadmap D4) closes it

    def test_limit_a_script_that_starts_onecrew_with_another_TEMP_still_gets_through(self):
        out = self.base / 'moved.txt'
        with self.child_temp_env():
            env = command.verifier_env(self.root)
        env = dict(env, TEMP=str(self.base), TMP=str(self.base), PYTHONPATH=str(REPO))
        probe = (f"import sys\nfrom onecrew.ledger import Ledger\nfrom onecrew.v2 import plan\nLedger({str(self.root)!r}, {str(self.state)!r})\n"
                 f"plan.require_owner('owner', 'x'); open({str(out)!r}, 'w').write('PASSED')\n")
        subprocess.run([PY, '-c', probe], env=env, capture_output=True)
        self.assertEqual(out.read_text(), 'PASSED')                          # known limit (LOI-DA-BIET): the start environment is the process's claim


# ---- P1-2 --------------------------------------------------------------------------------------------------------------------------

class GoverningPlan(Base):
    def project_plan(self):
        return json.loads(active_plan.project_file(self.root).read_text(encoding='utf-8'))['plan']

    def export_cli(self, name, env=AI):
        out = io.StringIO()
        with patch.dict(os.environ, env), contextlib.redirect_stdout(out):
            code = hook_cli.main(['--project', str(self.root), '--state-root', str(self.state), 'hook', 'export', name])
        return code, out.getvalue()

    def hook(self, event, verb='check'):
        env = dict(os.environ, PYTHONPATH=str(REPO))
        p = subprocess.run([PY, '-X', 'utf8', '-m', 'onecrew', '--project', str(self.root), '--state-root', str(self.state), 'hook', verb],
                           input=json.dumps(event).encode(), capture_output=True, env=env, cwd=str(self.root))
        return p.returncode, p.stderr.decode('utf-8', 'replace')

    def write_b(self):
        return self.hook({'session_id': 's1', 'hook_event_name': 'PreToolUse', 'cwd': str(self.root), 'tool_name': 'Write',
                          'tool_input': {'file_path': str(self.root / 'b.txt'), 'content': 'x'}})

    def accepted_old(self):
        self.new_plan('OLD')
        verdict.run(self.ledger, 'OLD', 'M1', self.root)
        plans.accept(self.ledger, 'OLD', 'owner', 'ok', verdict.artifact(self.ledger, 'OLD')['artifact_sha'])

    def test_13_the_review_scenario_hook_export_of_an_accepted_plan_is_refused(self):
        self.accepted_old()
        self.new_plan('NEW')
        active_plan.set_mode(self.ledger, 'enforce'); active_plan.export(self.ledger, 'NEW')
        self.assertEqual(self.write_b()[0], 2)
        code, text = self.export_cli('OLD')
        self.assertEqual(code, 2, text); self.assertIn('Only the owner', text)
        self.assertEqual(self.project_plan(), 'NEW')
        self.assertEqual(self.write_b()[0], 2)                               # still blocked outside NEW's owned scope

    def test_14_a_verdict_on_another_approved_plan_does_not_switch_the_governing_plan(self):
        self.new_plan('B', scope={'owned': ['a.txt', 'b.txt']})
        self.new_plan('A')                                                   # the owner approved A last: A governs
        self.assertEqual(self.project_plan(), 'A')
        with patch.dict(os.environ, AI):                                     # the AI session runs the check of B
            verdict.run(self.ledger, 'B', 'M1', self.root)
        self.assertEqual(self.project_plan(), 'A')

    def test_a_write_from_the_owners_own_process_switches_as_before(self):
        self.new_plan('B'); self.new_plan('A')
        verdict.run(self.ledger, 'B', 'M1', self.root)                       # no AI marker: the owner's terminal (as in 2.5.0.dev24)
        self.assertEqual(self.project_plan(), 'B')

    def test_15_an_amendment_of_another_plan_does_not_switch_it(self):
        self.new_plan('B'); self.new_plan('A')
        with patch.dict(os.environ, AI):
            plans.amend(self.ledger, 'B', plan_json(scope={'owned': ['a.txt', 'b.txt']}), 'wider', 'claude')
        self.assertEqual(self.project_plan(), 'A')

    def test_16_refreshing_the_governing_plan_after_it_expired_stays_open(self):
        self.new_plan('NEW'); active_plan.set_mode(self.ledger, 'enforce')
        for path in (active_plan.project_file(self.root),):
            value = json.loads(path.read_text(encoding='utf-8')); value['expires'] = '2000-01-01T00:00:00+00:00'; active_plan._write(path, value)
        code, text = self.export_cli('NEW')
        self.assertEqual(code, 0, text)
        self.assertGreater(json.loads(active_plan.project_file(self.root).read_text(encoding='utf-8'))['expires'], '2001')

    def test_17_after_the_governing_plan_is_accepted_a_live_plan_takes_over(self):
        self.new_plan('B')
        self.new_plan('OLD')
        verdict.run(self.ledger, 'OLD', 'M1', self.root)
        plans.accept(self.ledger, 'OLD', 'owner', 'ok', verdict.artifact(self.ledger, 'OLD')['artifact_sha'])
        self.assertEqual(self.project_plan(), 'OLD')
        with patch.dict(os.environ, AI):
            verdict.run(self.ledger, 'B', 'M1', self.root)                   # stricter: B holds the project again, even from the AI session
        self.assertEqual(self.project_plan(), 'B')

    def test_18_the_owner_switches_with_approve_and_with_hook_mode(self):
        self.new_plan('A'); self.new_plan('B')
        self.assertEqual(self.project_plan(), 'B')
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = hook_cli.main(['--project', str(self.root), '--state-root', str(self.state), 'hook', 'mode', 'enforce', '--plan', 'A', '--by', 'owner',
                                  '--reference', 'x'])
        self.assertEqual(code, 0, out.getvalue())
        self.assertEqual(self.project_plan(), 'A')

    def test_19_an_unreadable_governing_copy_is_switched_only_by_the_owner(self):
        self.new_plan('A'); self.new_plan('B')
        active_plan.project_file(self.root).write_text('{not json', encoding='utf-8')
        code, text = self.export_cli('A')
        self.assertEqual(code, 2, text)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = hook_cli.main(['--project', str(self.root), '--state-root', str(self.state), 'hook', 'mode', 'enforce', '--plan', 'A', '--by', 'owner',
                                  '--reference', 'x'])
        self.assertEqual(code, 0, out.getvalue())
        self.assertEqual(self.project_plan(), 'A')

    def test_20_a_re_export_of_the_governing_plan_by_an_internal_writer_still_writes(self):
        self.new_plan('A')
        before = json.loads(active_plan.project_file(self.root).read_text(encoding='utf-8'))['exported_at']
        with patch.dict(os.environ, AI):
            self.assertIsNotNone(active_plan.export(self.ledger, 'A'))
        self.assertGreaterEqual(json.loads(active_plan.project_file(self.root).read_text(encoding='utf-8'))['exported_at'], before)


if __name__ == '__main__':
    unittest.main()
