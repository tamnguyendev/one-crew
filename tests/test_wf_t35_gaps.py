"""T35d [E3] guard (R03 W23c, TD27): the v1 evaluation guard tests are green BEFORE and AFTER the v1 classifiers were split into
onecrew.evaluation_core for the W23c adapter, with the same result.

Labelled as the guard: this does not re-test the adapter (tests/test_wf_r03a_metrics counts the v1 calls). "Before" is the archive of
038a0b3, the parent of 54b802c ("refactor(eval): share v1 evidence classifiers for W23c"), run UNMODIFIED from its own tree;
"after" is this checkout. Both run `tests.test_eval_scorecard` (unchanged between the two) in a child process.
Only test_eval_scorecard is run; the other TD27 guard modules of 02 §3 are not part of this check.
"""
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests import wf_oldversion as ov

REPO = Path(__file__).resolve().parents[1]
BEFORE_SPLIT = '038a0b3'
GUARD = 'tests.test_eval_scorecard'


def run_guard(tree):
    env = {k: v for k, v in os.environ.items() if k not in ('ONECREW_ACTOR', 'PYTHONPATH', 'CLAUDE_CODE_CHILD_SESSION', 'CLAUDECODE')}
    env.update(PYTHONPATH=str(tree), PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1')
    child = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'unittest', '-v', GUARD], cwd=str(tree), env=env,
                           capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=600)
    tail = child.stderr.strip().splitlines()
    ran = next((int(m.group(1)) for line in tail if (m := re.match(r'Ran (\d+) tests?', line))), None)
    names = sorted(line.split(' ... ')[0] for line in tail if ' ... ' in line)
    return child.returncode, ran, names, tail[-1] if tail else '', child.stderr[-2000:]


class EvalScorecardGuard(unittest.TestCase):
    def test_t35d_e3_guard_v1_eval_scorecard_green_before_and_after_the_split(self):
        with tempfile.TemporaryDirectory() as temp:
            before = run_guard(ov.archive(BEFORE_SPLIT, REPO, temp))
        after = run_guard(REPO)
        for label, (code, ran, names, last, log) in (('before ' + BEFORE_SPLIT, before), ('after (this checkout)', after)):
            self.assertEqual(code, 0, f'{label}: {log}')
            self.assertEqual(last, 'OK', f'{label}: {log}')                              # green, no skips / expected failures
            self.assertTrue(ran and ran > 0, f'{label}: {log}')
        self.assertEqual(before[1], after[1])                                            # same number of guard tests
        self.assertEqual(before[2], after[2])                                            # the same tests, same (green) result
