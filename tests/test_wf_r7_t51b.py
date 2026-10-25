"""Round 7 / T51b (W48b, R02) — E5 / E12 with a REAL mutant of the project filter.

tests.test_wf_r02_retrieval.test_e5_projects_are_not_mixed shows that the ledger holds the entries of both projects and that the real retrieval
separates them; it does not run a retrieval WITHOUT the filter. 05 T51 [E5] evidence asks for that counter-proof: "bản phản chứng (bỏ lọc
project) làm test đỏ". Here the check is a function of the retrieval; the mutant is the source of `context.retrieve` with the project condition
removed (the line is rewritten and compiled in the module's namespace), and the same check must go red on it.
"""
import inspect
import textwrap
import unittest
from unittest.mock import patch

from onecrew.v2 import context
from tests.test_wf_r02_retrieval import RetrievalBase

PROJECT_FILTER = "mine = p.get('scope') == 'project' and row['project_id'] == ledger.project_id and p.get('project') == ledger.project_id"
NO_FILTER = "mine = p.get('scope') == 'project'"


def unfiltered_retrieve():
    source = textwrap.dedent(inspect.getsource(context.retrieve))
    if PROJECT_FILTER not in source: raise AssertionError('the project filter line moved: the mutant must be rebuilt, not skipped')
    namespace = {}
    exec(compile(source.replace(PROJECT_FILTER, NO_FILTER), context.__file__, 'exec'), context.__dict__, namespace)
    return namespace['retrieve']


class ProjectFilterMutantTests(RetrievalBase):
    def mixing_problems(self):
        """The T51b E5/E12 check: P1 gets its own + the general entry and never P2's private one; P2 never gets P1's project entries."""
        problems = []
        mine = {e['text']: e for e in context.retrieve(self.l1)['entries']}
        theirs = {e['text']: e for e in context.retrieve(self.l2)['entries']}
        if self.private_text in mine: problems.append('P1 received the private entry of P2')
        if self.general_text not in mine: problems.append('P1 lost the general entry')
        if 'Keep the column order of the old export.' not in mine: problems.append('P1 lost its own decision')
        leaked = {t for t, e in theirs.items() if e['scope'] == 'project'} & {t for t, e in mine.items() if e['scope'] == 'project'}
        if leaked: problems.append(f'project entries shared by P1 and P2: {sorted(leaked)}')
        general = [t for t, e in mine.items() if e['scope'] == 'general']
        if general != [self.general_text]: problems.append(f'general scope of P1 is {general}')
        return problems

    def test_e5_real_retrieval_passes_the_check(self):
        self.assertEqual(self.mixing_problems(), [])

    def test_e5_counter_without_the_project_filter_the_check_is_red(self):
        with patch.object(context, 'retrieve', unfiltered_retrieve()):
            problems = self.mixing_problems()
        self.assertIn('P1 received the private entry of P2', problems)
        self.assertTrue(any(p.startswith('project entries shared by P1 and P2') for p in problems), problems)

    def test_e12_the_private_entry_never_enters_the_general_scope(self):
        for ledger in (self.l1, self.l2):
            general = context.retrieve(ledger, scope='general')['entries']
            self.assertEqual([e['text'] for e in general], [self.general_text])
            self.assertNotIn(self.private_text, [e['text'] for e in general])


if __name__ == '__main__':
    unittest.main()
