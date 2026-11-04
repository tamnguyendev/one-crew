"""The open knowledge findings of docs/v23/HOP-DONG-2.3.vi.md §10.4 (left open by the dev6 report §3), each a counterexample that fails on
4bb41b3 plus its control: KN-1 a request from a package sealed before 2.3.0.dev6, KN-2 a 2.2 `context add` note under a lesson- key,
KN-3 the full project id of another project in `wiki history`, KN-4 withdrawing a section on a page past the reading budget."""
import json
from unittest.mock import patch

from onecrew.ledger import LedgerError, canonical
from onecrew.snapshots import Snapshots
from onecrew.v2 import context, knowledge, namespaces, wiki
from tests.test_v23_review_dev4 import Base, HERE


class KN1RequestsAcrossTheUpgrade(Base):
    """A worker asked for `ctx-retry` from a package sealed by 2.3.0.dev5, which named project two's general record that way. After the
    upgrade the reader's own subject is `ctx-retry`; the request must still bring what the worker saw, or be refused, never the other one."""

    def setUp(self):
        super().setUp()
        self.second = self.second_project()
        self.general('Rule of project two', HERE, ledger=self.second, plan='Q1', key='retry')
        self.general('Rule of project one', HERE, key='retry')
        self.tag2 = knowledge.project_tags(self.ledger)[self.second.project_id]

    def requested(self, *items):
        pkg = knowledge.package(self.ledger, knowledge.consumer(self.ledger, 'P1'), cap_chars=12000, requested=items)
        return [e['id'] for e in pkg['requested']], [(r['id'], r['reason']) for r in pkg['requests_refused']]

    def test_kn1_a_request_sealed_before_dev6_brings_the_subject_its_package_showed(self):
        legacy = lambda title: {'event': None, 'title': title, 'legacy': True}          # an index row of a package sealed before version 3
        self.assertEqual(self.requested(('ctx-retry', legacy('Rule of project two'))), (['ctx-retry@' + self.tag2], []))
        self.assertEqual(self.requested(('ctx-retry', legacy('Rule of project one'))), (['ctx-retry'], []))

    def test_kn1_a_title_that_tells_no_subject_is_refused_never_guessed(self):
        self.assertEqual(self.requested(('ctx-retry', {'event': None, 'title': 'A title nobody wrote', 'legacy': True})),
                         ([], [('ctx-retry', 'not_available')]))                    # review dev7 R7-05: never answered with another subject

    def test_kn1_control_a_plain_request_is_the_own_subject(self):
        self.assertEqual(self.requested('ctx-retry'), (['ctx-retry'], []))

    def test_kn1_previous_requests_come_with_the_titles_of_the_sealed_package(self):
        store = Snapshots(self.ledger.state_root)
        package = {'kind': 'knowledge-package', 'entries': [], 'requested': [],
                   'omitted': {'index': [{'id': 'ctx-retry', 'title': 'Rule of project two', 'use': 'fact', 'reason': 'cap'}]}}
        sealed = store.blob(canonical(package).encode('utf-8'))
        receipt = store.blob(canonical({'kind': 'native-node-receipt', 'knowledge': {'package': sealed},
                                        'knowledge_requests': ['ctx-retry', 'never-listed']}).encode('utf-8'))
        with self.ledger.transaction(write=True) as conn:
            root = namespaces.resolve(self.ledger, conn, 'P1')
            self.ledger._event(conn, root['id'], 'node.result_retained', {'attempt': 'ATT-kn1', 'node': 'C', 'candidate': {'receipt': receipt}})
        self.assertEqual(knowledge.previous_requests(self.ledger, store, 'P1', 'ATT-kn1'),
                         [('ctx-retry', {'event': None, 'title': 'Rule of project two', 'legacy': True}), 'never-listed'])


class KN2LessonKeyedNotes(Base):
    def test_kn2_a_22_note_under_a_lesson_key_is_its_writers_subject_not_a_lesson(self):
        second = self.second_project()
        for ledger, plan, text in ((self.ledger, 'P1', 'Note of project one'), (second, 'Q1', 'Note of project two')):
            context.add(ledger, plan, kind='note', label='hypothesis', text=text, source={'type': 'event', 'id': self.event_of(ledger)},
                        scope='general', conditions=['on this machine'], key='lesson-shared')                # what 2.2 `context add --scope general --key lesson-shared` wrote
        rows = {r['text']: r for r in knowledge.records(self.ledger, history=True)}
        one, two = rows.get('Note of project one'), rows.get('Note of project two')
        self.assertTrue(one and two, rows.keys())
        self.assertNotEqual(one['id'], two['id'])
        self.assertEqual((one['kind'], two['kind']), ('note', 'note'))
        self.assertEqual((one['status'], two['status']), ('active', 'active'))


class KN3OtherProjectByTag(Base):
    def test_kn3_wiki_history_names_another_project_by_its_tag(self):
        second = self.second_project()
        self.general('Rule of project two', HERE, ledger=second, plan='Q1', key='retry')
        self.general('Own rule', HERE, key='own')
        records = knowledge.records(self.ledger, history=True)
        rows = {r['text']: r for r in records}
        self.assertEqual(rows['Rule of project two']['project'], '@' + knowledge.project_tags(self.ledger)[second.project_id])
        self.assertNotIn(second.project_id, json.dumps(records))
        self.assertEqual(rows['Own rule']['project'], self.ledger.project_id)            # control: our own records keep our id


class KN4PastTheReadingBudget(Base):
    def test_kn4_a_section_on_a_page_past_the_reading_budget_can_be_withdrawn(self):
        for i in range(3): self.page(f'p{i}.md', f'## Section {i}\nText {i}.\n')
        evidence = {'sources': [{'type': 'event', 'id': self.event_of(self.ledger)}]}
        with patch.object(wiki, 'MAX_PAGES', 2):
            written = knowledge.withdraw(self.ledger, 'P1', 'p2-section-2', reason='shown wrong', evidence=evidence)
            self.assertTrue(written.get('recorded', True))
            with self.assertRaises(LedgerError):                                              # control: an id that names nothing
                knowledge.withdraw(self.ledger, 'P1', 'p2-no-such-section', reason='shown wrong', evidence=evidence)


if __name__ == '__main__':
    import unittest
    unittest.main()
