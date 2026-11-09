"""MEP hotfix, seventh pass (mep7): issues #2, #3 and #5 from the MEP machine (09/11/2026).

#2: a milestone whose argv[0] is the Windows app execution alias of Python (%LOCALAPPDATA%\\Microsoft\\WindowsApps\\python.exe) made `verdict run` raise
OSError [Errno 22] in `tool_identity` (the alias has no readable bytes). The error came out of the block before the verifier without `verifier_started = False`,
so the run was recorded as abandoned in phase 'verifier', reconciled as unknown and held until a manual `verdict release-run`.
mep7: the alias is fingerprinted by the program it starts; an unreadable program is recorded, not raised; any error before the Popen is a known outcome.
#5: the refusal of an input that spells the live tree names `inputs_unscanned`.
Owner steps use the suite's own fixture (the suite's process is not an AI session): fixture evidence, not an owner's approval."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v2_l2 import HookFixture, owned_plan                                          # noqa: E402
from test_v2_l1 import milestone                                                         # noqa: E402
from onecrew.ledger import LedgerError                                                   # noqa: E402
from onecrew.v2 import plan as plans, verdict                                            # noqa: E402
from onecrew.v2.verifiers import command                                                 # noqa: E402

PY = sys.executable
COUNT = "import sys; open(sys.argv[1],'a').write('x\\n'); print('x ran')"
ALIAS = Path(os.environ.get('LOCALAPPDATA', '')) / 'Microsoft' / 'WindowsApps' / 'python.exe'


def have_alias():
    if os.name != 'nt' or not ALIAS.is_file(): return False
    try:
        return getattr(os.lstat(ALIAS), 'st_reparse_tag', 0) == 0x8000001B                    # IO_REPARSE_TAG_APPEXECLINK
    except OSError:
        return False


def reparse_buffer(strings, version=3, tag=None):
    body = version.to_bytes(4, 'little') + ''.join(s + '\0' for s in strings).encode('utf-16-le')
    return (tag if tag is not None else 0x8000001B).to_bytes(4, 'little') + len(body).to_bytes(2, 'little') + b'\0\0' + body


class ParseAlias(unittest.TestCase):
    TARGET = str(Path(tempfile.gettempdir()) / 'WindowsApps' / 'Vendor.Python_3.13.0.0_x64__publisher' / 'python3.13.exe')

    def test_the_third_string_is_the_program(self):
        data = reparse_buffer(['Vendor.Python_publisher', 'Vendor.Python_publisher!Python', self.TARGET, '0'])
        self.assertEqual(command.parse_app_alias(data), self.TARGET)

    def test_other_data_is_not_an_alias(self):
        self.assertIsNone(command.parse_app_alias(reparse_buffer(['a', 'b', self.TARGET], version=2)))
        self.assertIsNone(command.parse_app_alias(reparse_buffer(['a', 'b', self.TARGET], tag=0xA000000C)))      # a symbolic link
        self.assertIsNone(command.parse_app_alias(reparse_buffer(['a', 'b', 'relative.exe'])))
        self.assertIsNone(command.parse_app_alias(reparse_buffer(['a', 'b'])))
        self.assertIsNone(command.parse_app_alias(b'\x1b\x00'))

    def test_an_ordinary_file_is_not_an_alias(self):
        self.assertIsNone(command.app_alias_target(PY))


class Identity(unittest.TestCase):
    def test_an_unreadable_program_is_recorded_not_raised_and_never_carries_a_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            program = Path(folder) / 'tool.exe'; program.write_bytes(b'MZ')
            with patch.object(command, 'app_alias_target', return_value=folder):     # the "program" is a folder: reading it raises OSError
                tool = command.tool_identity(str(program), {})
        self.assertIsNone(tool['sha256'])
        self.assertIn('unreadable', tool)
        self.assertEqual(tool['path'], str(Path(folder)))
        self.assertTrue(command.tool_changed(tool))

    def test_an_ordinary_program_is_unchanged(self):
        tool = command.tool_identity(PY, {})
        self.assertNotIn('alias', tool)
        self.assertRegex(tool['sha256'], '^[0-9a-f]{64}$')
        self.assertFalse(command.tool_changed(tool))

    @unittest.skipUnless(have_alias(), 'needs the Windows app execution alias of Python')
    def test_the_alias_is_fingerprinted_by_the_program_it_starts(self):
        with self.assertRaises(OSError): ALIAS.read_bytes()                                # the failure of #2, on this machine
        tool = command.tool_identity(str(ALIAS), {})
        self.assertEqual(tool['alias'], str(ALIAS))
        self.assertNotEqual(Path(tool['path']), ALIAS)
        self.assertRegex(tool['sha256'], '^[0-9a-f]{64}$')
        self.assertFalse(command.tool_changed(tool))


class Run(HookFixture):
    def setUp(self):
        super().setUp()
        top = str(Path(command.toplevel(self.root)))
        for rel, text in (('tool/cfg.txt', 'tot\n'), ('tool/so.md', f'Repo nam o `{top}` (ghi chep).\n'), ('a.txt', 'a\n')):
            p = self.root / rel; p.parent.mkdir(exist_ok=True); p.write_text(text, encoding='utf-8')
        subprocess.run(['git', '-C', str(self.root), '-c', 'user.name=t', '-c', 'user.email=t@t', 'add', '-A'], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(self.root), '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'nguon'], check=True, capture_output=True)
        self.counter = Path(self.temp.name) / 'dem' / 'n.txt'; self.counter.parent.mkdir()
        self.scratch = Path(self.temp.name) / 'tam'; self.scratch.mkdir()
        old = tempfile.tempdir; tempfile.tempdir = str(self.scratch)
        self.addCleanup(setattr, tempfile, 'tempdir', old)

    def plan(self, program=PY, unscanned=None):
        m = milestone('M1', argv=[program, '-c', COUNT, str(self.counter)])
        m['verifier']['config']['inputs'] = ['tool']
        if unscanned is not None: m['verifier']['config']['inputs_unscanned'] = list(unscanned)
        self.enforce(value=owned_plan(milestones=[m]))

    def runs(self):
        return len(self.counter.read_text().splitlines()) if self.counter.exists() else 0

    def events(self, kind):
        with self.ledger.transaction() as conn:
            task = plans.derive(self.ledger, conn, 'P1')['task_id']
            rows = conn.execute('SELECT kind, payload FROM events WHERE task_id=? ORDER BY seq', (task,)).fetchall()
        return [json.loads(r[1]) for r in rows if r[0] == kind]

    def receipt(self):
        from onecrew.snapshots import Snapshots
        with self.ledger.transaction() as conn:
            state = plans.anchor_events(self.ledger, conn, 'P1')
        return json.loads(Snapshots(self.ledger.state_root).read_blob(state['verdicts'][-1]['receipt']))

    def test_an_error_before_the_verifier_is_a_known_outcome_and_the_next_run_needs_no_release(self):
        self.plan(unscanned=['tool/so.md'])
        with patch.object(command, 'tool_identity', side_effect=OSError(22, 'Invalid argument', str(ALIAS))):
            with self.assertRaises(OSError): verdict.run(self.ledger, 'P1', 'M1')
        self.assertEqual(self.runs(), 0, 'the verifier was not called')
        self.assertEqual([a['phase'] for a in self.events('verdict.run_abandoned')], ['before_dispatch'])
        verdict.run(self.ledger, 'P1', 'M1')                                                # old code: held as unknown, needs `verdict release-run`
        self.assertEqual(self.runs(), 1)
        self.assertEqual(self.events('verdict.run_held'), [])
        self.assertEqual(self.events('verdict.run_released'), [])
        self.assertEqual([v['result'] for v in self.events('verdict.recorded')], ['pass'])

    @unittest.skipUnless(have_alias(), 'needs the Windows app execution alias of Python')
    def test_a_milestone_started_by_the_alias_runs_and_its_receipt_names_both(self):
        self.plan(program=str(ALIAS), unscanned=['tool/so.md'])
        verdict.run(self.ledger, 'P1', 'M1')                                                # old code: OSError [Errno 22], run held
        self.assertEqual(self.runs(), 1)
        self.assertEqual(plans.show(self.ledger, 'P1')['milestones'][0]['state'], 'passed')
        tool = self.receipt()['input_scope']['tool']
        self.assertEqual(tool['alias'], str(ALIAS))
        self.assertRegex(tool['sha256'], '^[0-9a-f]{64}$')

    def test_the_refusal_of_an_input_names_inputs_unscanned(self):
        self.plan()
        with self.assertRaises(LedgerError) as caught: verdict.run(self.ledger, 'P1', 'M1')
        message = str(caught.exception)
        self.assertIn("'tool/so.md' spells the live tree", message)
        self.assertIn('"inputs_unscanned": ["tool/so.md"]', message)
        self.assertIn('the command line is never exempt', message)
        self.assertEqual(self.runs(), 0)


if __name__ == '__main__':
    unittest.main()
