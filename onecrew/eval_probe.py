"""Subprocess entrypoint for fixed, repository-reviewed unittest probes only.

Executed with Python -I. Target runtime and frozen test harness live in a disposable
checkout. No external case file can supply executable commands to the parent runner.
"""
import contextlib
import functools
import importlib
import io
import json
from pathlib import Path
import re
import sys
import time
import traceback
import unittest

# The interpreter's message, and unittest.mock's when a patch target lacks the attribute.
MISSING = re.compile(r"module 'onecrew(\.[A-Za-z0-9_.]+)?' has no attribute '[A-Za-z_][A-Za-z0-9_]*'|"
                     r"<module 'onecrew(\.[A-Za-z0-9_.]+)?' from .*> does not have the attribute '[A-Za-z_][A-Za-z0-9_]*'\Z")


def capability_gap(error):
    """Missing onecrew module/attribute: an API gap, not a reproduced behavioural failure."""
    # "partially initialized module ..." is a circular import, i.e. a runtime bug.
    if 'partially initialized module' in str(error):
        return False
    if isinstance(error, ImportError):
        return (error.name or '').split('.')[0] == 'onecrew'
    return isinstance(error, AttributeError) and bool(MISSING.match(str(error)))


def ran_runtime(tb, runtime):
    """Whether runtime code was executing when the error was raised (frozen importlib frames excluded)."""
    return any(not f.f_code.co_filename.startswith('<') and Path(f.f_code.co_filename).resolve().is_relative_to(runtime)
               for f, _ in traceback.walk_tb(tb))


def kind(error, gap=None):
    return {'type': type(error).__name__, 'capability': capability_gap(error) if gap is None else gap}


class Result(unittest.TextTestResult):
    def __init__(self, *args, runtime, **kwargs):
        super().__init__(*args, **kwargs)
        self.kinds, self.runtime = [], runtime

    def record(self, err):
        # Inside a test only the harness's own reference names a gap; a failing lookup or lazy import
        # in runtime code (a renamed function, say) is behaviour.
        self.kinds.append(kind(err[1], capability_gap(err[1]) and not ran_runtime(err[2], self.runtime)))

    def addError(self, test, err):
        self.record(err); super().addError(test, err)

    def addSubTest(self, test, subtest, err):
        if err is not None and not issubclass(err[0], test.failureException): self.record(err)
        super().addSubTest(test, subtest, err)


def main():
    runtime, harness, selector, result_path = sys.argv[1:]
    sys.path[:0] = [runtime, harness]
    started = time.monotonic()
    captured = io.StringIO()
    value = {'selector': selector, 'tests': 0, 'status': 'harness_error', 'errors': []}
    with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
        try:
            target = importlib.import_module('onecrew')
            if not Path(target.__file__).resolve().is_relative_to(Path(runtime).resolve()):
                raise ImportError('Target runtime absent; refusing harness fallback.', name='onecrew')
            mod, cls, method = selector.rsplit('.', 2)
            module = importlib.import_module(mod)
            suite = unittest.TestSuite([getattr(module, cls)(method)])
            result = unittest.TextTestRunner(stream=captured, verbosity=2,
                                             resultclass=functools.partial(Result, runtime=Path(runtime).resolve())).run(suite)
            value['errors'] = result.kinds
            gap = result.kinds and all(k['capability'] for k in result.kinds) and len(result.kinds) == len(result.errors)
            status = ('capability_unavailable' if result.errors and gap else 'runtime_error' if result.errors
                      else 'assertion_failed' if result.failures or result.unexpectedSuccesses
                      else 'skipped' if result.skipped or result.expectedFailures else 'passed' if result.testsRun == 1 and result.wasSuccessful()
                      else 'harness_error')
            value.update(status=status, tests=result.testsRun, skipped=len(result.skipped))
        except Exception as error:
            # Loading failed before any test ran. Only an onecrew API gap is not a harness defect.
            value['errors'] = [kind(error)]
            value['status'] = 'capability_unavailable' if capability_gap(error) else 'harness_error'
            traceback.print_exc()
    value['elapsed_seconds'] = round(time.monotonic()-started, 6)
    value['diagnostic'] = captured.getvalue()[-16000:]
    Path(result_path).write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main()
