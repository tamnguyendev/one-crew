"""T15b (W33a, R03) - an adapter declares what its executor can do; OneCrew promises nothing else and observes with a source.

The hook is simulated by fake tool calls and hook events: this proves the interface, not a real Claude Code session. The "managed worker" is a
fake that declares every capability: it shows the interface works for a capable executor, not that a real worker pauses (W33b / T15c).
"""
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v2_l1 import Fixture                                    # noqa: E402

from onecrew.ledger import LedgerError                            # noqa: E402
from onecrew.snapshots import Snapshots                           # noqa: E402
from onecrew.v2 import compat, executors as ex, plan as plans     # noqa: E402
import tests.wf_oldversion as ov                                  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
PY = sys.executable
BASELINE = 'ee46539'
HOOK = ex.HookAdapter()


class FakeWorker(ex.Executor):
    """A managed worker that declares everything (fake: only the interface is shown)."""
    declaration = ex.Declaration('fake-worker', 'managed', ex.CAPABILITIES, ex.MEASURES)

    def __init__(self):
        self.paused = []

    def pause_at_safe_point(self, target):
        self.paused.append(target)
        return 'pause requested'


class DeclarationTests(unittest.TestCase):
    # [E1] the hook adapter declares no pause (and nothing else it cannot do)
    def test_e1_the_hook_adapter_declares_nothing_it_cannot_do(self):
        d = HOOK.declaration
        self.assertEqual(d.kind, 'external_hook')
        self.assertEqual([c for c in ex.CAPABILITIES if d.supports(c)], [])
        self.assertEqual(d.measures, frozenset())
        self.assertFalse(HOOK.supports('pause_at_safe_point'))
        self.assertEqual(FakeWorker.declaration.capabilities, frozenset(ex.CAPABILITIES))

    def test_a_declaration_is_checked(self):
        for bad in (dict(capabilities=('fly',)), dict(capabilities=('measure',)), dict(measures=('time',)), dict(capabilities=('measure',), measures=('mood',))):
            with self.assertRaises(LedgerError, msg=str(bad)): ex.Declaration('x', 'managed', **bad)
        with self.assertRaises(LedgerError): ex.Declaration('x', 'robot')

    # [E1][E4][E9] no pause is promised or sent to an executor that did not declare it
    def test_e1_e9_the_core_sends_no_pause_to_an_executor_without_the_capability(self):
        door = ex.Dispatcher()
        plan = ex.hold_plan(HOOK)
        self.assertEqual((plan['action'], plan['command'], plan['state']), ('revoke_write', None, 'write_revoked'))
        with self.assertRaises(ex.CapabilityMissing):
            door.send(HOOK, 'pause_at_safe_point', 'B')                       # the "send pause to every executor" shortcut is refused at the door
        self.assertEqual(door.sent, [])
        self.assertNotIn('pause', plan['state'])

    def test_a_capable_executor_is_asked_and_the_state_is_only_requested(self):
        worker, door = FakeWorker(), ex.Dispatcher()
        plan = ex.hold_plan(worker)
        self.assertEqual((plan['action'], plan['command'], plan['state']), ('pause_at_safe_point', 'pause_at_safe_point', 'pause_requested'))
        door.send(worker, plan['command'], 'C')
        self.assertEqual((worker.paused, [s['command'] for s in door.sent]), (['C'], ['pause_at_safe_point']))
        self.assertNotIn('đã dừng', ex.hold_text(plan))                       # "stopped" needs the executor's confirmation (W33b)

    # [E3] the words of the report
    def test_e3_the_report_says_write_permission_was_withdrawn_not_that_it_stopped(self):
        text = ex.hold_text(ex.hold_plan(HOOK), 'vi')
        self.assertIn('đã ngừng cấp quyền ghi', text)
        self.assertNotIn('đã dừng', text)
        self.assertNotIn('pause', text.lower())
        self.assertIn('withdrawn', ex.hold_text(ex.hold_plan(HOOK), 'en'))
        self.assertNotIn('stopped', ex.hold_text(ex.hold_plan(HOOK), 'en').replace('is not stopped', ''))


class ObservationTests(Fixture):
    def setUp(self):
        super().setUp()
        self.approved()

    def kinds_of(self, kind='executor.observed'):
        return [p for k, p in self.events() if k == kind]

    def tool(self, what, ref, **extra):
        return ex.observe(self.ledger, 'P1', HOOK, 'A1', what, source=extra.pop('source', 'tool_call'), ref=ref, **extra)

    # observations are written with the source and the moment of receipt, as class A
    def test_an_observation_has_its_source_the_declared_capabilities_and_the_time_it_was_received(self):
        self.assertEqual(compat.event_class('executor.observed'), 'A')
        self.tool('start', 'toolu_01', at='2026-10-24T08:00:00+00:00')
        row = self.kinds_of()[0]
        self.assertEqual((row['executor'], row['attempt'], row['what'], row['time_source'], row['basis']), ('claude-code-hook', 'A1', 'start', 'tool_call', {'type': 'tool_call', 'ref': 'toolu_01'}))
        self.assertEqual(row['capabilities'], [])                              # the declaration the observation was made under: no capability
        self.assertTrue(row['received_at'])
        self.assertNotEqual(row['received_at'], row['observed_at'])

    def test_repeating_an_observation_writes_nothing(self):
        self.tool('start', 'toolu_01', at='2026-10-24T08:00:00+00:00')
        again = self.tool('start', 'toolu_01', at='2026-10-24T08:00:00+00:00')
        self.assertFalse(again['written'])
        self.assertEqual(len(self.kinds_of()), 1)

    # an external session is reported only from a receipt, a tool call or a hook event that is real
    def test_an_external_session_is_not_inferred(self):
        for source in ex.NOT_SOURCES:
            with self.assertRaises(LedgerError, msg=source) as caught: self.tool('end', 'x', source=source)
            self.assertIn('not an observation', str(caught.exception))
        with self.assertRaises(LedgerError): self.tool('end', 'x', source='executor_clock')             # an external session has no clock OneCrew can read
        with self.assertRaises(LedgerError): self.tool('end', '   ')
        with self.assertRaises(LedgerError): self.tool('end', 'nothing', source='receipt')               # a receipt must be a blob of this state root
        self.assertEqual(self.kinds_of(), [])

    def test_a_receipt_that_is_a_blob_of_the_state_root_is_a_source(self):
        blob = Snapshots(self.ledger.state_root).blob(b'{"kind": "command-receipt"}')
        self.tool('end', blob, source='receipt', at='2026-10-24T08:05:00+00:00')
        self.assertEqual(self.kinds_of()[0]['basis'], {'type': 'receipt', 'ref': blob})

    # [E6] no call count, time or budget for an executor that does not measure
    def test_e6_a_number_the_adapter_does_not_measure_is_refused_and_reported_as_not_measured(self):
        for measured in ({'calls': 0}, {'calls': 7}, {'seconds': 12}):
            with self.assertRaises(LedgerError, msg=str(measured)) as caught: self.tool('end', 'toolu_02', measured=measured)
            self.assertIn('does not declare measuring', str(caught.exception))
        self.tool('start', 'toolu_01', at='2026-10-24T08:00:00+00:00')
        self.tool('end', 'toolu_03', at='2026-10-24T08:10:00+00:00')
        attempt = ex.summary(self.ledger, 'P1')['attempts'][0]
        self.assertEqual((attempt['calls'], attempt['elapsed_seconds']), (ex.NOT_MEASURED, ex.NOT_MEASURED))       # even with a start and an end, 10 minutes is not "the time spent"
        text = ex.render(ex.summary(self.ledger, 'P1'), 'vi')
        self.assertIn('call: không đo', text)
        self.assertIn('thời gian chạy: không đo', text)
        self.assertNotRegex(text, r'call: \d')
        self.assertFalse([p for p in self.kinds_of() if 'measured' in p])
        self.assertNotIn('budget', json.dumps(self.kinds_of()).lower())

    def test_e6_a_measuring_executor_may_report_what_it_measures_and_only_that(self):
        class Meter(ex.Executor):
            declaration = ex.Declaration('meter', 'managed', ('measure',), ('time',))
        ex.observe(self.ledger, 'P1', Meter, 'W1', 'end', source='executor_clock', ref='clock-1', at='2026-10-24T09:00:00+00:00', measured={'seconds': 42})
        with self.assertRaises(LedgerError): ex.observe(self.ledger, 'P1', Meter, 'W1', 'end', source='executor_clock', ref='clock-2', measured={'calls': 3})   # it measures time, not calls
        attempt = [a for a in ex.summary(self.ledger, 'P1')['attempts'] if a['executor'] == 'meter'][0]
        self.assertEqual((attempt['elapsed_seconds'], attempt['calls']), (42, ex.NOT_MEASURED))

    # missing data is unknown, never 0
    def test_missing_data_is_unknown_not_zero(self):
        self.tool('start', 'toolu_01')                                          # the hook saw a call but could not say when it happened
        attempt = ex.summary(self.ledger, 'P1')['attempts'][0]
        self.assertEqual((attempt['start']['at'], attempt['end'], attempt['wait_seconds']), (ex.UNKNOWN, ex.UNKNOWN, ex.UNKNOWN))
        text = ex.render(ex.summary(self.ledger, 'P1'), 'vi')
        self.assertIn('kết thúc: không rõ', text)
        self.assertNotIn(' 0 ', text)
        self.assertEqual(self.kinds_of()[0]['observed_at'], None)

    def test_waits_have_a_reason_and_are_apart_from_the_attempt(self):
        with self.assertRaises(LedgerError): self.tool('wait', 'toolu_w')                                  # a wait names its reason
        with self.assertRaises(LedgerError): self.tool('start', 'toolu_x', wait_reason='owner')
        self.tool('start', 'toolu_01', at='2026-10-24T08:00:00+00:00')
        self.tool('wait', 'toolu_w', at='2026-10-24T08:10:00+00:00', wait_reason='owner')                  # open: nothing says when it ended
        attempt = ex.summary(self.ledger, 'P1')['attempts'][0]
        self.assertEqual((attempt['waits'][0]['reason'], attempt['waits'][0]['until'], attempt['wait_seconds']), ('owner', ex.UNKNOWN, ex.UNKNOWN))
        self.tool('wait', 'toolu_w', at='2026-10-24T08:10:00+00:00', until='2026-10-24T08:40:00+00:00', wait_reason='owner')
        attempt = ex.summary(self.ledger, 'P1')['attempts'][0]
        self.assertEqual(attempt['wait_seconds'], 1800)

    # the command verifier's attempts are read from verdict.run's own events: no second write
    def test_verifier_attempts_are_read_from_the_run_events(self):
        from onecrew.v2 import verdict
        self.ledger  # approved in setUp with the default OK milestone
        before = len(self.events())
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        written = len(self.events()) - before
        report = ex.summary(self.ledger, 'P1')
        self.assertEqual(len(self.events()) - before, written)               # reading the summary wrote nothing
        mine = [a for a in report['attempts'] if a['executor'] == 'command-verifier']
        self.assertEqual(len(mine), 1)
        self.assertEqual((mine[0]['start']['time_source'], mine[0]['ended_by']), ('ledger_event', 'receipt'))
        self.assertIsInstance(mine[0]['elapsed_seconds'], float)
        self.assertEqual(mine[0]['calls'], ex.NOT_MEASURED)

    def test_the_cli_observes_and_summarises(self):
        env = dict({k: v for k, v in os.environ.items() if k != 'CLAUDECODE'}, PYTHONUTF8='1')
        base = [PY, '-X', 'utf8', '-m', 'onecrew', '--project', str(self.root), '--state-root', str(self.ledger.state_root), 'executor']
        done = subprocess.run(base + ['observe', '--plan', 'P1', '--executor', 'claude-code-hook', '--attempt', 'A1', '--what', 'start', '--source', 'tool_call',
                                      '--ref', 'toolu_cli', '--at', '2026-10-24T08:00:00+00:00'], cwd=REPO, capture_output=True, timeout=120, env=env)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        refused = subprocess.run(base + ['observe', '--plan', 'P1', '--executor', 'claude-code-hook', '--attempt', 'A1', '--what', 'end', '--source', 'inferred', '--ref', 'x'],
                                 cwd=REPO, capture_output=True, timeout=120, env=env)
        self.assertEqual(refused.returncode, 2)
        shown = subprocess.run(base + ['summary', '--plan', 'P1'], cwd=REPO, capture_output=True, timeout=120, env=env)
        self.assertEqual(shown.returncode, 0, shown.stderr)
        text = shown.stdout.decode('utf-8')
        self.assertIn('claude-code-hook', text)
        self.assertIn('call: không đo', text)
        listed = subprocess.run(base + ['list'], cwd=REPO, capture_output=True, timeout=120, env=env)
        # 2.3-B (M4): the list also shows the two runtime executors the engine starts, exactly as they declare themselves
        self.assertEqual(sorted(d['executor'] for d in json.loads(listed.stdout)),
                         ['claude-code-hook', 'command-verifier', 'common-native-artifact', 'managed-native-artifact'])


def _have_git():
    try:
        return subprocess.run(['git', '--version'], capture_output=True).returncode == 0
    except OSError:
        return False


@unittest.skipUnless(_have_git(), 'git is required to archive the old version')
class OldVersionTests(Fixture):
    """executor.observed is class A: the REAL old version (archive of ee46539) keeps S, G, C."""

    @classmethod
    def setUpClass(cls):
        cls.runs = ov._short_runs()
        cls.old = ov.OldVersion(ov.archive(BASELINE, str(REPO), cls.runs))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.runs, ignore_errors=True)

    def test_the_old_version_ignores_executor_observed(self):
        self.approved()
        ex.observe(self.ledger, 'P1', HOOK, 'A1', 'start', source='tool_call', ref='toolu_01', at='2026-10-24T08:00:00+00:00')
        ex.observe(self.ledger, 'P1', HOOK, 'A1', 'wait', source='hook_event', ref='hk_1', at='2026-10-24T08:10:00+00:00', wait_reason='owner')
        harvested = [p for k, p in self.events() if k == 'executor.observed']
        self.assertEqual(len(harvested), 2)
        proj = ov.git_project(self.runs, 'proj')
        cfile = self.runs / 'c.json'
        cfile.write_text(json.dumps(ov.contract('Old')), encoding='utf-8')
        state = self.runs / 'state'
        code, out = self.old.run(proj, state, 'plan', 'propose', 'P1', '--file', str(cfile), '--author', 'claude-probe')
        self.assertEqual(code, 0, out)
        task = ov.anchor_id(state, ov.project_id(state, proj), 'plan:P1')
        ov.make_approved(state, task, 'P1')
        base = ov.read(self.old, proj, state, 'P1')
        shutil.copytree(state, self.runs / 'with')
        for payload in harvested: ov.insert_event(self.runs / 'with', task, 'executor.observed', payload)
        after = ov.read(self.old, proj, self.runs / 'with', 'P1')
        diff = ov.compare(base, after)
        self.assertTrue(diff['S'] and diff['G'] and diff['C'], (base, after))
        self.assertFalse(after['read_blocked'])


if __name__ == '__main__':
    unittest.main()
