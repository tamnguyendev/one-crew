"""S1 (QC MVP-1): gate/runner/worker-tool processes must speak UTF-8 even under a legacy console codepage.

Root cause (J4, 'charmap' codec can't encode 'ắ'): workspace_tools prints canonical() JSON, which keeps non-ASCII
text, to a stdout the Windows child inherited as cp1252. Every spawn point also hands its children UTF-8 settings.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
UTF8 = {'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}


class WorkspaceToolsUtf8Tests(unittest.TestCase):
    def test_vietnamese_detail_survives_a_legacy_stdout_codepage(self):
        env = {k: v for k, v in os.environ.items() if k not in ('PYTHONUTF8', 'PYTHONIOENCODING')}
        env['PYTHONIOENCODING'] = 'cp1252'  # what a Windows child of the CLI gets when it is not UTF-8
        missing = Path(tempfile.gettempdir()) / 'không-có-ngữ-cảnh-ắ.json'  # error detail echoes this name
        done = subprocess.run([sys.executable, str(ROOT / 'onecrew' / 'workspace_tools.py'), str(missing)],
                              capture_output=True, env=env, cwd=str(ROOT), timeout=60)
        text = done.stdout.decode('utf-8')
        self.assertIn('ắ', text, done.stderr.decode('utf-8', 'replace'))
        self.assertNotIn('charmap', done.stderr.decode('utf-8', 'replace'))
        self.assertEqual(done.returncode, 1)  # the documented failure code, not an encoder crash


class SpawnEnvironmentUtf8Tests(unittest.TestCase):
    def test_subscription_environment_sets_utf8(self):
        from onecrew.subscription import environment
        env = environment({'PATH': 'x', 'PYTHONUTF8': '0', 'PYTHONIOENCODING': 'cp1252'})
        for key, value in UTF8.items():
            self.assertEqual(env[key], value)

    def test_work_tools_environment_sets_utf8_for_both_roles(self):
        from onecrew import work_tools
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'ONECREW_WORK_ROOT': tmp}):
            runtime = SimpleNamespace(ledger=SimpleNamespace(state_root=Path(tmp) / 'state'))
            for verification in (False, True):
                env = work_tools.environment(runtime, 'TASK-1', None, verification)
                for key, value in UTF8.items():
                    self.assertEqual(env[key], value, verification)

    def test_runner_start_passes_utf8_to_the_runner_process(self):
        from onecrew import runner

        class Stop(Exception):
            pass

        seen = {}

        def popen(argv, **kwargs):
            seen.update(kwargs['env'])
            raise Stop()

        with tempfile.TemporaryDirectory() as tmp:
            ledger = SimpleNamespace(state_root=Path(tmp), project=Path(tmp))
            with patch.object(runner, 'status', return_value={'status': 'stopped'}), \
                    patch.object(runner, 'workflow_for', return_value=SimpleNamespace(state=lambda t: (1, {'phase': 'running'}))), \
                    patch.object(runner.subprocess, 'Popen', popen), \
                    patch('onecrew.host.lease', return_value=None), \
                    patch.dict(os.environ, {'PYTHONUTF8': '0', 'PYTHONIOENCODING': 'cp1252'}):
                with self.assertRaises(Stop):
                    runner.start(ledger, 'TASK-1', 'user')
        for key, value in UTF8.items():
            self.assertEqual(seen.get(key), value)

    def test_gate_command_allows_utf8_overrides_and_child_receives_them(self):
        from onecrew.sandbox_gate import command
        from onecrew.supervisor import native_python
        script = "import os;print(os.environ.get('PYTHONUTF8'),os.environ.get('PYTHONIOENCODING'))"
        with tempfile.TemporaryDirectory() as tmp:
            code, out, err = command([native_python(), '-c', script], Path(tmp) / 'run', 60, None, dict(UTF8))
        self.assertEqual(code, 0, err)
        self.assertEqual(out.strip(), '1 utf-8')


if __name__ == '__main__':
    unittest.main()
