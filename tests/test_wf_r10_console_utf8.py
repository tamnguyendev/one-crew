"""Round 10 (C): the installed `onecrew` console script must not die with UnicodeEncodeError when the process stdout/stderr
encoding is cp1252 (Windows, no PYTHONUTF8) and the output is Vietnamese. Real subprocesses, no mocks."""
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(args, **extra):
    env = {k: v for k, v in os.environ.items() if k not in ('PYTHONUTF8', 'PYTHONIOENCODING', 'ONECREW_LANG')}
    env.update(PYTHONUTF8='0', PYTHONIOENCODING='cp1252', ONECREW_LANG='vi', PYTHONPATH=str(ROOT), **extra)
    return subprocess.run([sys.executable] + args, cwd=ROOT, env=env, capture_output=True, timeout=120)


class ConsoleUtf8(unittest.TestCase):
    def test_console_script_target_is_the_utf8_wrapper(self):
        text = (ROOT / 'pyproject.toml').read_text(encoding='utf-8')
        self.assertRegex(text, r'onecrew\s*=\s*"onecrew\.console:main"')
        self.assertIn('"onecrew.console"', text)       # the wheel must ship it

    def test_help_in_cp1252_does_not_crash(self):
        done = run(['-m', 'onecrew.console', '--help'])
        self.assertNotIn(b'UnicodeEncodeError', done.stderr)
        self.assertEqual(done.returncode, 0, done.stderr.decode('utf-8', 'replace'))
        text = done.stdout.decode('utf-8')
        self.assertIn('OneCrew:', text)
        self.assertRegex(text, r'[^\x00-\x7f]')        # the Vietnamese really came out, as UTF-8

    def test_checkout_module_entry_in_cp1252_does_not_crash(self):
        done = run(['-m', 'onecrew', '--help'])
        self.assertNotIn(b'UnicodeEncodeError', done.stderr)
        self.assertEqual(done.returncode, 0, done.stderr.decode('utf-8', 'replace'))

    def test_vietnamese_lint_reason_in_cp1252_does_not_crash(self):
        lint = ROOT / 'examples' / 'contract-template.json'
        state = Path(os.environ.get('TEMP', '.')) / 'r10-utf8-state'
        done = run(['-m', 'onecrew.console', '--project', str(ROOT), '--state-root', str(state), 'plan', 'lint', '--file', str(lint)])
        self.assertNotIn(b'UnicodeEncodeError', done.stderr)
        self.assertNotIn(b'Traceback', done.stderr)

    def test_same_output_under_utf8_mode(self):
        env = {k: v for k, v in os.environ.items() if k not in ('PYTHONIOENCODING', 'ONECREW_LANG')}
        env.update(PYTHONUTF8='1', ONECREW_LANG='vi', PYTHONPATH=str(ROOT))
        a = subprocess.run([sys.executable, '-m', 'onecrew.console', '--help'], cwd=ROOT, env=env, capture_output=True, timeout=120)
        b = run(['-m', 'onecrew.console', '--help'])
        self.assertEqual(a.returncode, 0)
        self.assertEqual(a.stdout, b.stdout)

    def test_unencodable_characters_are_replaced_not_raised(self):
        from onecrew import console
        import io
        buf = io.BytesIO()
        stream = io.TextIOWrapper(buf, encoding='cp1252', errors='strict')
        console.force_utf8(stream)
        stream.write('Kết luận ✓')
        stream.flush()
        self.assertEqual(buf.getvalue().decode('utf-8'), 'Kết luận ✓')


if __name__ == '__main__':
    unittest.main()
