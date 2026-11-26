"""GSDP-A (#63, first round), the standing plan flag (decision D6): a contract may say `standing: true`; such a plan expires at the owner's approval +
budget.time minutes (a re-export never extends it) and its Stop hook neither blocks nor writes a line per turn. A plain plan keeps the 24-hour expiry and
the Stop block. Kind A cases fail BY ASSERTION on the base (2.5.0.dev33, which refuses the field): every call that the base refuses is caught and
turned into a failure, and only modules the base has are imported here.
"""
import contextlib
import datetime as dt
import io
import json
import os
import subprocess
import time
from pathlib import Path

from onecrew.ledger import LedgerError
from onecrew.v2 import active_plan, contract as contracts, hook_cli, plan as plans, verdict
from tests.v2_fixture import PY, Fixture, plan_json

REPO = Path(__file__).resolve().parents[1]
OWNED = ['a.txt']


def parse(stamp):
    return dt.datetime.fromisoformat(str(stamp))


class StandingFixture(Fixture):
    """A real git project and ledger; the hooks run as `python -m onecrew ... hook <verb>` subprocesses with the documented stdin JSON."""

    def setUp(self):
        super().setUp()
        self.state = Path(self.ledger.state_root)
        self.number = 0

    def standing(self, mode='enforce', **extra):
        """Approve a standing plan, set the hook mode and export it; a refusal (the base does not know the field) is a test failure, not an error."""
        value = plan_json(standing=True, **dict({'scope': {'owned': OWNED}}, **extra))
        try:
            self.approved('P1', value)
        except LedgerError as error:
            self.fail(f'a contract with standing: true was refused: {error}')
        active_plan.set_mode(self.ledger, mode)
        active_plan.export(self.ledger, 'P1')

    def plain(self, mode='enforce'):
        self.approved('P1', plan_json(scope={'owned': OWNED}))
        active_plan.set_mode(self.ledger, mode)
        active_plan.export(self.ledger, 'P1')

    def copies(self):
        """The two exported copies of the active plan: the project's and the state root's."""
        return [self.root / '.onecrew' / 'active-plan.json', *sorted(self.state.glob('plans/*/active-plan.json'))]

    def document(self):
        return json.loads((self.root / '.onecrew' / 'active-plan.json').read_text(encoding='utf-8'))

    def expiries(self):
        return [json.loads(p.read_text(encoding='utf-8')).get('expires') for p in self.copies()]

    def run_hook(self, verb, event=None, raw=None, extra=()):
        arguments = [PY, '-X', 'utf8', '-m', 'onecrew', '--project', str(self.root), '--state-root', str(self.state), 'hook', verb, *extra]
        data = raw if raw is not None else json.dumps(event or {}).encode('utf-8')
        env = dict({k: v for k, v in os.environ.items() if k not in ('CLAUDE_CODE_CHILD_SESSION', 'CLAUDECODE')}, PYTHONUTF8='1')
        done = subprocess.run(arguments, input=data, capture_output=True, cwd=REPO, timeout=120, env=env)
        return done.returncode, done.stdout.decode('utf-8'), done.stderr.decode('utf-8')

    def tool(self, name, **tool_input):
        self.number += 1
        return {'session_id': 's1', 'cwd': str(self.root), 'hook_event_name': 'PreToolUse', 'permission_mode': 'default',
                'tool_name': name, 'tool_input': tool_input, 'tool_use_id': f'toolu_gsdp_{self.number}'}

    def edit(self, rel):
        return self.tool('Edit', file_path=str(self.root / rel), old_string='one', new_string='two')

    def stop(self, session='s1'):
        return self.run_hook('stop', {'session_id': session, 'cwd': str(self.root), 'hook_event_name': 'Stop', 'stop_hook_active': False})

    def violations(self):
        path = self.root / '.onecrew' / 'violations.jsonl'
        return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []


class TestGsdpStanding(StandingFixture):
    def test_contract_accepts_standing_flag(self):
        try:
            value = contracts.validate(plan_json(standing=True))
        except LedgerError as error:
            self.fail(f'validate refused standing: true: {error}')
        self.assertIs(value.get('standing'), True)
        self.assertNotIn('standing', contracts.validate(plan_json()))                    # a plain contract stays byte-identical
        self.assertNotIn('standing', contracts.validate(plan_json(standing=False)))      # false is a plain plan
        self.assertEqual(contracts.validate(plan_json()), contracts.validate(plan_json(standing=False)))
        for bad in ('yes', 1, None, ['true']):
            with self.assertRaises(LedgerError, msg=repr(bad)): contracts.validate(plan_json(standing=bad))

    def test_standing_expires_at_approval_plus_budget_time(self):
        self.standing(budget={'max_calls': 100, 'time': 90})
        with self.ledger.transaction() as conn:
            approved = plans.derive(self.ledger, conn, 'P1')['approved']
        at = parse(approved.get('at') or approved.get('recorded_at'))
        want = at + dt.timedelta(minutes=90)
        self.assertEqual(len(self.copies()), 2)
        for path in self.copies():
            document = json.loads(path.read_text(encoding='utf-8'))
            self.assertIs(document.get('standing'), True, path)
            self.assertEqual(parse(document['expires']), want, path)              # the approval + budget.time, not the export + 24 hours
        self.assertLess(want - dt.datetime.now(dt.timezone.utc), dt.timedelta(hours=2))

    def test_reexport_does_not_extend_standing_expiry(self):
        self.standing(mode='log')
        first = self.expiries()
        self.assertEqual(len(set(first)), 1, first)
        time.sleep(1.2)
        active_plan.export(self.ledger, 'P1')                                         # a plain re-export
        self.assertEqual(self.expiries(), first)
        with contextlib.redirect_stdout(io.StringIO()):                              # `onecrew hook export P1`
            code = hook_cli.main(['--project', str(self.root), '--state-root', str(self.state), 'hook', 'export', 'P1'])
        self.assertEqual(code, 0)
        self.assertEqual(self.expiries(), first)
        active_plan.set_mode(self.ledger, 'enforce'); active_plan.export(self.ledger, 'P1', take_over=True)      # what `owner enforce` does
        self.assertEqual(self.expiries(), first)
        verdict.run(self.ledger, 'P1', 'M1', self.root)                               # a verdict exports again
        self.assertEqual(plans.show(self.ledger, 'P1')['milestones'][0]['state'], 'passed')
        self.assertEqual(self.expiries(), first)
        self.run_hook('session', {'session_id': 's1', 'cwd': str(self.root), 'hook_event_name': 'SessionStart', 'source': 'startup'})
        self.assertEqual(self.expiries(), first)                                     # a session start rewrites the copies, never the expiry

    def test_standing_stop_never_blocks_nor_records(self):
        self.standing(mode='enforce')
        self.assertEqual(plans.show(self.ledger, 'P1')['milestones'][0]['state'], 'pending')    # a milestone without a verdict: a plain plan would block
        for turn in range(3):
            code, out, err = self.stop()
            self.assertEqual((code, out.strip()), (0, ''), (turn, err))
        active_plan.set_mode(self.ledger, 'log'); active_plan.export(self.ledger, 'P1', take_over=True)
        code, out, err = self.stop(session='s2')
        self.assertEqual((code, out.strip()), (0, ''), err)
        self.assertEqual([v for v in self.violations() if v.get('tool') == 'Stop'], [])          # no line per turn, in either mode
        self.assertFalse((self.root / '.onecrew' / 'hook-state.json').exists() and
                         'stop_blocks' in (self.root / '.onecrew' / 'hook-state.json').read_text(encoding='utf-8'))

    def test_plain_plan_keeps_24h_expiry_and_stop_block(self):
        self.plain(mode='enforce')
        document = self.document()
        self.assertNotIn('standing', document)
        left = parse(document['expires']) - dt.datetime.now(dt.timezone.utc)
        self.assertGreater(left, dt.timedelta(hours=23, minutes=50)); self.assertLess(left, dt.timedelta(hours=24, minutes=1))
        code, out, _ = self.stop()
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)['decision'], 'block')
        self.assertIn('stop_blocked', [v['event'] for v in self.violations() if v.get('tool') == 'Stop'])

    def test_standing_keeps_edit_gate_and_expiry_block(self):
        self.standing(mode='enforce')
        code, _, err = self.run_hook('check', self.edit('other.py'))
        self.assertEqual(code, 2, err)                                                # outside the owned scope: blocked as for a plain plan
        code, _, err = self.run_hook('check', self.edit('a.txt'))
        self.assertEqual(code, 0, err)
        code, _, err = self.run_hook('check', self.tool('Bash', command='git push origin main'))
        self.assertEqual(code, 2, err)
        past = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)).isoformat()
        for path in self.copies():                                                    # the approval window is over (both copies say so)
            document = json.loads(path.read_text(encoding='utf-8'))
            document['expires'] = past
            path.write_text(json.dumps(document), encoding='utf-8')
        code, _, err = self.run_hook('check', self.edit('a.txt'))
        self.assertEqual(code, 2, err); self.assertIn('expired', err)               # an expired standing plan in enforce blocks every edit

    def test_owner_approve_shows_standing_expiry(self):
        from onecrew.v2 import cli
        self.propose('P1', plan_json(standing=True, scope={'owned': OWNED}, budget={'max_calls': 100, 'time': 600}))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = cli.main(['--project', str(self.root), '--state-root', str(self.state), 'owner', 'approve', 'P1', '--revision', '1',
                             '--reference', 'standing fixture approval', '--human'])
        text = output.getvalue()
        self.assertEqual(code, 0, text)
        self.assertIn('Đã ghi nhận duyệt', text)
        self.assertIn('THƯỜNG TRỰC', text); self.assertIn('Stop', text); self.assertIn('không chặn', text)
        local = parse(self.document()['expires']).astimezone().strftime('%Y-%m-%d %H:%M')
        self.assertIn(local, text)                                                     # the expiry itself, read back from the ledger
        self.assertIn('owner enforce P1 --mode log', text)
