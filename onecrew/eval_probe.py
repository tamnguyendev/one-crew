"""Subprocess entrypoint for fixed, repository-reviewed unittest probes only.

Executed with Python -I. Target runtime and frozen test harness live in a disposable
checkout. No external case file can supply executable commands to the parent runner.
"""
import contextlib
import importlib
import io
import json
from pathlib import Path
import sys
import time
import traceback
import unittest


def main():
    runtime, harness, selector, result_path = sys.argv[1:]
    sys.path[:0] = [runtime, harness]
    started = time.monotonic()
    captured = io.StringIO()
    value = {'selector': selector, 'tests': 0, 'status': 'harness_error'}
    with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
        try:
            mod, cls, method = selector.rsplit('.', 2)
            module = importlib.import_module(mod)
            suite = unittest.TestSuite([getattr(module, cls)(method)])
            result = unittest.TextTestRunner(stream=captured, verbosity=2).run(suite)
            status = ('runtime_error' if result.errors else 'assertion_failed' if result.failures
                      else 'skipped' if result.skipped else 'passed' if result.testsRun == 1
                      else 'harness_error')
            value.update(status=status, tests=result.testsRun, skipped=len(result.skipped))
        except ImportError:
            # API compatibility gap, not proof of a reproduced behavioral failure.
            value['status'] = 'capability_unavailable'
            traceback.print_exc()
        except Exception:
            traceback.print_exc()
    value['elapsed_seconds'] = round(time.monotonic()-started, 6)
    value['diagnostic'] = captured.getvalue()[-16000:]
    Path(result_path).write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main()
