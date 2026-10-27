"""T28 [E1] as a gate check (round 12, Codex review 27/10: a C-class gap must not stay "manual evidence").

E1 asks that the two v1 register suites (tests.test_review_lifecycle, tests.test_review_p6) give the same test list and the same
results on the commit BEFORE onecrew/finding_core.py was split out (1b4f4c6^ = 54b802c) and after. The before-split run costs ~50
minutes and its subject is a FIXED historical commit, so rerunning it in every gate proves nothing new. What a gate CAN prove
cheaply, on every build, is:
  1. the retained evidence (docs/wf/evidence/t28-e1-before-split/) is intact and says what the registry claims: 114 tests on the
     before-split commit, 114 on the after-split integration commit, both OK, identical test lists, empty diff;
  2. the before-split commit is a real ancestor in this repository and is exactly the parent of the split commit;
  3. the CURRENT build's two suites still enumerate exactly the retained test list (collected with the unittest loader, no run), so
     the comparison is tied to this snapshot, not to a log of some other suite;
  4. the after-split side is still executed by the gate (registry R05 check.register_v1_guard / check.register_v1_guard_p6 name
     exactly these two modules).
A retained log is evidence of one recorded run; this check never upgrades it into a claim about any other commit.
"""
import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'docs' / 'wf' / 'evidence' / 't28-e1-before-split'
SUITES = ('tests.test_review_lifecycle', 'tests.test_review_p6')
SPLIT_COMMIT = '1b4f4c6'
_OK = re.compile(r'^(?P<name>\S+) \((?P<id>[\w.]+)\) \.\.\. ok$')


def parse_log(path):
    text = path.read_text(encoding='utf-8', errors='replace')
    ids = sorted(m.group('id') for m in (_OK.match(line.rstrip()) for line in text.splitlines()) if m)
    ran = re.search(r'^Ran (\d+) tests? in', text, re.M)
    return ids, int(ran.group(1)) if ran else None, bool(re.search(r'^OK\s*$', text, re.M)), bool(re.search(r'^exit 0\s*$', text, re.M))


def current_ids():
    loader = unittest.TestLoader()
    out = []

    def walk(suite):
        for item in suite:
            if isinstance(item, unittest.TestSuite):
                walk(item)
            else:
                out.append(item.id())
    for module in SUITES:
        walk(loader.loadTestsFromName(module))
    return sorted(out)


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


class T28E1EvidenceTests(unittest.TestCase):
    def test_e1_retained_before_and_after_split_runs_have_the_same_114_tests_and_both_passed(self):
        before_ids, before_ran, before_ok, before_exit = parse_log(EVIDENCE / 'before-split-54b802c.log')
        after_ids, after_ran, after_ok, after_exit = parse_log(EVIDENCE / 'after-split-e61b2c2.log')
        self.assertEqual((before_ran, after_ran), (114, 114))
        self.assertEqual((len(before_ids), len(after_ids)), (114, 114))
        self.assertTrue(before_ok and after_ok)
        self.assertTrue(before_exit)            # the before-split log also recorded the process exit code; the after log ends at unittest's OK
        self.assertEqual(before_ids, after_ids)
        self.assertEqual((EVIDENCE / 'test-list-diff.txt').read_text(encoding='utf-8').strip(), '')
        self.assertTrue((EVIDENCE / 'README.md').is_file())

    def test_e1_the_before_split_commit_is_the_parent_of_the_split_commit_in_this_repository(self):
        recorded = (EVIDENCE / 'commit-before-split.txt').read_text(encoding='utf-8').strip()
        self.assertTrue(recorded.startswith('54b802c'))
        self.assertEqual(git('cat-file', '-t', recorded), 'commit')
        self.assertEqual(git('rev-parse', SPLIT_COMMIT + '^'), recorded)
        self.assertEqual(git('merge-base', '--is-ancestor', recorded, 'HEAD'), '')   # exit 0 == ancestor

    def test_e1_the_current_build_enumerates_exactly_the_retained_test_list(self):
        before_ids, _, _, _ = parse_log(EVIDENCE / 'before-split-54b802c.log')
        self.assertEqual(current_ids(), before_ids)
        self.assertEqual({i.rsplit('.', 2)[0] for i in before_ids}, set(SUITES))

    def test_e1_the_gate_still_runs_the_after_split_side(self):
        registry = json.loads((ROOT / 'wfkit' / 'development-testcases.json').read_text(encoding='utf-8'))
        checks = registry['releases']['R05']['testcases']
        gate_modules = set(checks['check.register_v1_guard']['modules']) | set(checks['check.register_v1_guard_p6']['modules'])
        self.assertEqual(gate_modules, set(SUITES))
        self.assertIn('tests.test_wf_r12_t28_e1_evidence', checks['check.r12_t28_e1_evidence']['modules'])
        t28 = registry['releases']['R05']['acceptance']['T28']
        self.assertIn('check.r12_t28_e1_evidence', t28['checks'])


if __name__ == '__main__':
    unittest.main()
