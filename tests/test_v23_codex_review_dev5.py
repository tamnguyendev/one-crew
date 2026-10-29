"""Codex review of 2.3.0.dev5 (29/10, package on b3ecc57), P2-B: two projects of one state root that reuse a --key for general records.
Evidence: D:/OneCrewRuns/codex-dev5-handover-review-20261029/installed-collision.json (dev5: one id for both, the other project's withdrawal
removed ours, ours could not be withdrawn). Fixed in 2.3.0.dev6: a subject belongs to the project that wrote it. The reader's own subjects
keep `ctx-<key>`; another project's general subject is `ctx-<key>@<tag>`; withdrawal/archive targets and references are read in the
namespace of the project that wrote them; an old reference of the reader that names no own subject and exactly one other project's general
subject keeps naming it. r02b-r02d in tests/test_v23_review_dev4.py are the review's three cases; these are the rest of the matrix: ids seen
from both sides, ownership both ways, history, a summary across projects, old data, a project record under the other project's key,
delivery and the declaration check.
"""
import json
import unittest
from unittest.mock import patch

from onecrew.ledger import LedgerError
from onecrew.v2 import knowledge
from tests.test_v23_review_dev4 import Base, HERE, THERE, say


class TwoProjectsOneKey(Base):
    def setUp(self):
        super().setUp()
        self.second = self.second_project()
        self.tag1 = knowledge.project_tag(self.ledger.project_id)
        self.tag2 = knowledge.project_tag(self.second.project_id)

    def rows(self, ledger):
        return {r['text']: r for r in knowledge.records(ledger, history=True)}

    def withdraw(self, ledger, plan, target):
        return knowledge.withdraw(ledger, plan, target, reason='wrong here', evidence={'sources': [{'type': 'event', 'id': self.event_of(ledger)}]})

    def both_forms(self, project=None):
        return {form: self.retrieved(*form, project=project) for form in (('--scope', 'general'), ('--plan', 'P1', '--scope', 'general'))}

    def test_e_each_project_keeps_its_own_id_and_sees_the_other_one_qualified(self):
        mine = self.general('Rule of project one', HERE, key='retry-policy')
        theirs = self.general('Rule of project two', HERE, ledger=self.second, plan='Q1', key='retry-policy')
        self.assertEqual((mine['id'], theirs['id']), ('ctx-retry-policy', 'ctx-retry-policy'))        # what each writer is told
        one, two = self.rows(self.ledger), self.rows(self.second)
        say('e ids', {t: r['id'] for t, r in one.items()}, {t: r['id'] for t, r in two.items()})
        self.assertEqual(one['Rule of project one']['id'], 'ctx-retry-policy')
        self.assertEqual(one['Rule of project two']['id'], 'ctx-retry-policy@' + self.tag2)
        self.assertEqual(two['Rule of project two']['id'], 'ctx-retry-policy')
        self.assertEqual(two['Rule of project one']['id'], 'ctx-retry-policy@' + self.tag1)
        self.assertNotEqual(self.tag1, self.tag2)
        for path in (str(self.root), str(self.second.project)):                                 # the tag is a hash, never the path
            self.assertNotIn(path.replace('\\', '/').lower(), json.dumps(one, ensure_ascii=False).replace('\\\\', '/').lower())

    def test_f_only_the_writer_withdraws_and_a_withdrawal_never_crosses_projects(self):
        self.general('Rule of project one', HERE, key='retry-policy')
        self.general('Rule of project two', HERE, ledger=self.second, plan='Q1', key='retry-policy')
        with self.assertRaises(LedgerError) as caught:
            self.withdraw(self.ledger, 'P1', 'ctx-retry-policy@' + self.tag2)                       # not ours
        self.assertIn('only the project that wrote a general entry', str(caught.exception))
        self.withdraw(self.ledger, 'P1', 'ctx-retry-policy')                                       # ours
        one, two = self.rows(self.ledger), self.rows(self.second)
        self.assertEqual((one['Rule of project one']['status'], one['Rule of project two']['status']), ('withdrawn', 'active'))
        self.assertEqual((two['Rule of project two']['status'], two['Rule of project one']['status']), ('active', 'withdrawn'))
        for project, kept, gone in ((self.root, 'Rule of project two', 'Rule of project one'),
                                    (self.second.project, 'Rule of project two', 'Rule of project one')):
            for form, entries in self.both_forms(project).items() if project == self.root else \
                    {('--scope', 'general'): self.retrieved('--scope', 'general', project=project)}.items():
                with self.subTest(project=str(project)[-6:], form=form):
                    self.assertIn(kept, entries); self.assertNotIn(gone, entries)
                    self.assertEqual(entries[kept]['label'], 'verified', entries[kept])

    def test_g_history_keeps_each_subject_apart_and_an_update_names_its_own_base(self):
        v1 = self.general('Rule of project one, first', HERE, key='retry-policy')
        v2 = self.general('Rule of project one, second', HERE, key='retry-policy', base=v1['version'])
        self.assertFalse(v2.get('conflict'), v2)
        self.general('Rule of project two, newest', HERE, ledger=self.second, plan='Q1', key='retry-policy')
        history = self.history()
        say('g history', {i: (r['text'], r['status']) for i, r in history.items()})
        self.assertEqual(history['ctx-retry-policy']['text'], 'Rule of project one, second')
        self.assertEqual(history['ctx-retry-policy']['state_version'], v2['version'])
        self.assertEqual(history['ctx-retry-policy@' + self.tag2]['text'], 'Rule of project two, newest')
        v3 = self.general('Rule of project one, third', HERE, key='retry-policy', base=v2['version'])   # the other project's write is not ours
        self.assertFalse(v3.get('conflict'), v3)

    def test_h_a_summary_cannot_cite_another_projects_record_and_says_why(self):
        """Unchanged boundary (not part of P2-B): a summary inherits the evidence events of its sources, and events of another project are
        not this project's evidence, so `summarize` refuses openly. No summary across projects can exist, old or new."""
        self.general('Rule of project two', HERE, ledger=self.second, plan='Q1', key='retry-policy')
        with self.assertRaises(LedgerError) as caught:
            knowledge.summarize(self.ledger, 'P1', ['ctx-retry-policy@' + self.tag2], text='Summary of the shared retry rule')
        self.assertIn('not an event of', str(caught.exception))

    def old_format(self):
        """Records written as 2.3.0.dev5 wrote them: knowledge format 2 (one namespace per key)."""
        return patch.object(knowledge, 'FORMAT', 2)

    def supersede(self, text, target, **kw):
        return self.project_record(text, supersedes=[target], **kw)

    def test_i_old_data_a_plain_supersedes_keeps_naming_the_record_the_project_saw(self):
        """dev5 showed project two's general record to project one as `ctx-retry-policy`; `wiki record --supersedes ctx-retry-policy`
        stored that id. It keeps naming that record (superseded for project one only); project two's own view is unchanged."""
        self.general('Rule of project two', HERE, ledger=self.second, plan='Q1', key='retry-policy')
        with self.old_format(): self.supersede('Old project rule replacing the shared one', 'ctx-retry-policy')
        one, two = self.rows(self.ledger), self.rows(self.second)
        self.assertEqual(one['Old project rule replacing the shared one']['supersedes'], ['ctx-retry-policy@' + self.tag2])
        self.assertEqual(one['Rule of project two']['status'], 'superseded')
        self.assertEqual(two['Rule of project two']['status'], 'active')
        self.assertNotIn('Rule of project two', self.retrieved('--plan', 'P1', '--scope', 'general'))

    def test_i2_old_data_two_candidates_the_newest_before_the_reference_is_the_one_seen(self):
        self.general('Rule of project two', HERE, ledger=self.second, plan='Q1', key='retry-policy')
        third = self.second_project_named('third')
        self.general('Rule of project three', HERE, ledger=third, plan='Q1', key='retry-policy')
        with self.old_format(): self.supersede('Old rule replacing what it saw', 'ctx-retry-policy')
        tag3 = knowledge.project_tag(third.project_id)
        one = self.rows(self.ledger)
        self.assertEqual(one['Old rule replacing what it saw']['supersedes'], ['ctx-retry-policy@' + tag3])
        self.assertEqual((one['Rule of project three']['status'], one['Rule of project two']['status']), ('superseded', 'active'))

    def test_i3_old_data_a_record_written_after_the_reference_never_takes_it_over(self):
        self.general('Rule of project two', HERE, ledger=self.second, plan='Q1', key='retry-policy')
        with self.old_format(): self.supersede('Old rule replacing the shared one', 'ctx-retry-policy')
        self.general('Own shared rule written later', HERE, key='retry-policy')                       # now project one has its own subject
        one = self.rows(self.ledger)
        self.assertEqual(one['Old rule replacing the shared one']['supersedes'], ['ctx-retry-policy@' + self.tag2])
        self.assertEqual((one['Own shared rule written later']['status'], one['Rule of project two']['status']), ('active', 'superseded'))

    def test_i4_new_data_a_plain_reference_names_only_the_writers_own_subject(self):
        self.general('Rule of project two', HERE, ledger=self.second, plan='Q1', key='retry-policy')
        self.supersede('New rule naming the plain id', 'ctx-retry-policy')                            # format 3: exact
        one = self.rows(self.ledger)
        self.assertEqual(one['New rule naming the plain id']['supersedes'], ['ctx-retry-policy'])
        self.assertEqual(one['Rule of project two']['status'], 'active')
        self.supersede('New rule naming the shown id', 'ctx-retry-policy@' + self.tag2)
        self.assertEqual(self.rows(self.ledger)['Rule of project two']['status'], 'superseded')
        self.assertEqual(self.rows(self.second)['Rule of project two']['status'], 'active')

    def test_j_a_project_record_under_the_key_of_the_other_projects_general_record_is_its_own_subject(self):
        self.project_record('Project rule of project one', key='retry-policy')
        self.general('Elsewhere rule of project two', THERE, ledger=self.second, plan='Q1', key='retry-policy')
        self.withdraw(self.second, 'Q1', 'ctx-retry-policy')
        one = self.rows(self.ledger)
        self.assertEqual((one['Project rule of project one']['id'], one['Project rule of project one']['status']), ('ctx-retry-policy', 'active'))
        self.assertEqual(one['Elsewhere rule of project two']['status'], 'withdrawn')
        entries = self.retrieved('--plan', 'P1', '--scope', 'both')
        self.assertIn('Project rule of project one', entries)
        self.assertNotIn('Elsewhere rule of project two', entries)

    def test_k_delivery_names_both_records_apart_and_the_declaration_check_accepts_the_qualified_id(self):
        self.general('Rule of project one', HERE, key='retry-policy')
        self.general('Rule of project two', HERE, ledger=self.second, plan='Q1', key='retry-policy')
        package = self.cli('wiki', 'show', '--plan', 'P1')
        seen = {e['id']: e for e in package['entries']}; seen.update({r['id']: r for r in package['omitted']['index']})
        say('k wiki show', {i: e.get('use') for i, e in seen.items()})
        self.assertEqual(seen['ctx-retry-policy']['use'], 'fact')
        self.assertIn('ctx-retry-policy@' + self.tag2, seen)
        view = {'entries': [dict(e, use=e.get('use')) for e in package['entries']], 'requested': []}
        delivered = set(knowledge.delivered_ids(view))
        declared = {'used': sorted(i for i in ('ctx-retry-policy', 'ctx-retry-policy@' + self.tag2) if i in delivered), 'rejected': [], 'requests': []}
        self.assertEqual(knowledge.check_use(view, declared)['violations'], [])

    def second_project_named(self, name):
        import subprocess
        from pathlib import Path
        from onecrew.ledger import Ledger
        from onecrew.v2 import plan as plans
        from tests.test_v2_l1 import plan_json
        other = Path(self.temp.name) / name; other.mkdir()
        g = lambda *a: subprocess.run(['git', '-C', str(other), *a], check=True, capture_output=True, text=True).stdout.strip()
        g('init', '-q'); g('config', 'user.email', 't@localhost'); g('config', 'user.name', 'T')
        (other / 'z.txt').write_text(name + '\n')
        g('add', '.'); g('commit', '-qm', 'o')
        ledger = Ledger(other, self.ledger.state_root)
        plans.propose(ledger, 'Q1', plan_json(), 'codex')
        return ledger


if __name__ == '__main__':
    unittest.main()
