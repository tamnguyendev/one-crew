"""T31 (R05, round 7): [E5] no automatic path removes an evidence ref; [E6] the hook blocks a push of refs/onecrew, with a counter-example.

[E5] (structural, over the shipped package source): the only code that deletes a ref under refs/onecrew/evidence/ is
     retention.cleanup, the only caller of retention.cleanup is the owner verb `plan retention cleanup` (plan_cli), and that verb is on
     the default deny list an AI session's hook applies, so it is refused from an AI session like the other owner verbs. The runtime
     side (pin, GC, restart keep every ref; AI actor/session refused) is tests.test_wf_retention.
[E6] the real hook judge (hook_cli.judge_shell with the exported default deny list) blocks `git push origin refs/onecrew/...` and its
     reason names refs/onecrew; the counter-example - the same hook without the push rule - lets the push through (check red).
"""
import ast
import tempfile
import unittest
from pathlib import Path

from onecrew.v2 import active_plan, hook_cli

PACKAGE = Path(__file__).resolve().parents[1] / 'onecrew'
PUSH = 'git push origin refs/onecrew/evidence/0123abcd/' + 'a' * 40


def e6_holds(plan, root):
    verdict = hook_cli.judge_shell(plan, root, root, PUSH)
    return bool(verdict) and verdict[0] == 'bash_deny' and 'refs/onecrew' in verdict[1]


class T31RetentionRefTests(unittest.TestCase):
    def sources(self):
        for path in sorted(PACKAGE.rglob('*.py')):
            yield path.relative_to(PACKAGE.parent).as_posix(), path.read_text(encoding='utf-8')

    def test_e5_only_the_owner_cleanup_verb_can_delete_evidence_refs(self):
        deleters, callers = [], []
        for name, text in self.sources():
            tree = ast.parse(text, name)
            for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
                body = ast.get_source_segment(text, fn) or ''
                if 'update-ref' in body and ('delete ' in body or "'-d'" in body or '"-d"' in body):
                    deleters.append((name, fn.name))
            for call in [n for n in ast.walk(tree) if isinstance(n, ast.Call)]:
                func = call.func
                if (isinstance(func, ast.Attribute) and func.attr == 'cleanup' and isinstance(func.value, ast.Name)
                        and func.value.id == 'retention'):
                    callers.append(name)
        self.assertIn(('onecrew/v2/retention.py', 'cleanup'), deleters)
        self.assertEqual([d for d in deleters if d[0].startswith('onecrew/v2/')], [('onecrew/v2/retention.py', 'cleanup')])
        # v1 ref deletions, if any, never touch the evidence prefix
        for name, text in self.sources():
            if name != 'onecrew/v2/retention.py':
                self.assertNotIn('refs/onecrew/evidence', text, name)
        self.assertEqual(sorted(set(callers)), ['onecrew/v2/plan_cli.py'])
        with tempfile.TemporaryDirectory() as root:
            plan = {'bash_deny': list(active_plan.DEFAULT_BASH_DENY), 'state_root': root}
            refused = hook_cli.judge_shell(plan, root, root, 'onecrew plan retention cleanup P1 --by owner')
        self.assertEqual(refused[0], 'bash_deny')

    def test_e6_hook_blocks_push_of_refs_onecrew_and_the_hook_without_the_rule_is_red(self):
        with tempfile.TemporaryDirectory() as root:
            plan = {'bash_deny': list(active_plan.DEFAULT_BASH_DENY), 'state_root': root}
            self.assertTrue(e6_holds(plan, root))
            without = {'bash_deny': [e for e in active_plan.DEFAULT_BASH_DENY if 'push' not in e], 'state_root': root}
            self.assertFalse(e6_holds(without, root))
            self.assertIsNone(hook_cli.judge_shell(without, root, root, PUSH))


if __name__ == '__main__':
    unittest.main()
