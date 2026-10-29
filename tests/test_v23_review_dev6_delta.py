"""Delta review (agent Opus 5.5, 29/10) of 926bdcf, the fixes of the independent review of the Codex dev5 P2-B fix, kept as tests. Report:
D:/OneCrewRuns/v23/review-dev6/review-p2b.md, section "Delta review of 926bdcf". Fixed in 2.3.0.dev6 (D3-D8): the key rule compares
subjects; an old two-scope subject is withdrawn with a project record (the owner's sources and reason) and a neutral general record; another
project's shared version replaced by a newer unshared version is not current; another project's conflict under a lesson- key names its own
subject; an id that names nothing is refused. Changed to the chosen design, each saying why: dl01/dl02 (D1/D2: a page has no time, so a plain
reference that another project's general record also matches is reported from the start, in `wiki pages` and in packages, with what it
names now), dl07 (D3: a 2.2 `context add` general note is its own subject `ctx-<key>.r<root>`; withdrawing the project record publishes
nothing).
"""
import contextlib
import io
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import Ledger, LedgerError, canonical
from onecrew.snapshots import Snapshots
from onecrew.v2 import context, knowledge
from onecrew.v2 import plan as plans
from tests.test_v2_l1 import plan_json
from tests.test_v23_a1_knowledge import fence
from tests.test_v23_review_dev4 import Base, HERE, brief, say


class ReviewDev6Delta(Base):
    # ---- helpers ------------------------------------------------------------------------------------------------------------
    def project(self, name):
        other = Path(self.temp.name) / name; other.mkdir()
        g = lambda *a: subprocess.run(['git', '-C', str(other), *a], check=True, capture_output=True, text=True).stdout.strip()
        g('init', '-q'); g('config', 'user.email', 't@localhost'); g('config', 'user.name', 'T')
        (other / 'z.txt').write_text(name + '\n')
        g('add', '.'); g('commit', '-qm', 'o')
        ledger = Ledger(other, self.ledger.state_root)
        plans.propose(ledger, 'Q1', plan_json(), 'codex')
        return ledger

    def rows(self, ledger=None):
        return {r['text']: r for r in knowledge.records(ledger or self.ledger, history=True)}

    def seen(self, plan='P1'):
        pkg = knowledge.package(self.ledger, knowledge.consumer(self.ledger, plan), cap_chars=12000)
        out = {e['title']: e for e in pkg['entries']}
        out.update({r['title']: r for r in pkg['omitted']['index'] if r['title'] not in out})
        return out, pkg

    def uses(self, seen):
        return {t: (e.get('use'), e.get('id')) for t, e in seen.items()}

    def evidence(self, ledger):
        return {'sources': [{'type': 'event', 'id': self.event_of(ledger)}]}

    def old_data(self):
        """Write as data written before the 926bdcf key rule (both scopes under one key)."""
        return patch.object(knowledge, '_key_in_other_scope', return_value=False, create=True)

    def old_lesson_keys(self):
        return patch.object(knowledge, 'RESERVED_KEY_PREFIXES', (), create=True)

    def replacement_page(self):
        self.page('rules.md', '## Project replacement of the shared retry rule\n' + fence({'id': 'retry-replacement', 'kind': 'decision',
                  'supersedes': ['ctx-retry-policy']}) + 'Use the project retry rule here.\n')

    # ---- R6: old wiki references ---------------------------------------------------------------------------------------------
    def warnings(self, pkg=None):
        found = [p['problem'] for p in (pkg or self.seen()[1])['problems'] if 'retry-replacement' in p.get('problem', '')]
        lint = [p['problem'] for p in knowledge.pages_report(self.ledger)['problems'] if 'retry-replacement' in p.get('problem', '')]
        return found, lint

    def test_dl01_an_aliased_wiki_reference_is_reported_from_the_start_and_when_it_changes(self):
        """Changed (D1). A page has no time, so what an old plain reference meant cannot be known; the reference is read in the project's
        namespace and reported from the start, in packages and in `wiki pages`, with what it names now and the id to write."""
        second = self.second_project()
        self.general('Rule of project two', HERE, ledger=second, plan='Q1', key='retry-policy')
        self.replacement_page()
        before, pkg = self.seen()
        found, lint = self.warnings(pkg)
        say('dl01 before', self.uses(before), found, lint)
        self.assertNotIn('Rule of project two', before)                                    # the alias acts while the project has no record
        self.assertTrue(found and lint and 'while this project has no record under that key' in found[0], (found, lint))
        self.general('Own shared rule written later', HERE, key='retry-policy')
        after, pkg = self.seen()
        found, lint = self.warnings(pkg)
        say('dl01 after', self.uses(after), found, lint)
        self.assertTrue(found and lint and 'names the record of this project' in found[0], (found, lint))   # the change is reported, never silent

    def test_dl02_a_third_project_reusing_the_key_is_reported_by_the_lint(self):
        """Changed (D2). Before the third project writes, the lint already says the reference depends on another project's record; after,
        the reference names nothing and both the package and `wiki pages` say which id to write."""
        second = self.second_project()
        self.general('Rule of project two', HERE, ledger=second, plan='Q1', key='retry-policy')
        self.replacement_page()
        found, lint = self.warnings()
        self.assertTrue(lint and 'while this project has no record under that key' in lint[0], lint)
        third = self.project('third')
        self.general('Rule of project three', HERE, ledger=third, plan='Q1', key='retry-policy')
        after, pkg = self.seen()
        found, lint = self.warnings(pkg)
        say('dl02 after a third project wrote the key', self.uses(after), found, lint)
        self.assertTrue(found and lint and 'names nothing' in found[0] and 'names nothing' in lint[0], (found, lint))

    # ---- R7: the key rule and the forced general lifecycle record ----------------------------------------------------------
    def both_scopes(self):
        shared = self.general('Shared rule under the reused key', HERE, key='reused-key')
        with self.old_data(): self.project_record('Project rule under the reused key', key='reused-key')
        return shared

    def test_dl03_old_data_the_owner_withdraws_its_project_record_citing_a_file_line(self):
        """Control first: a plain project record can be withdrawn citing a file line. With old data (a general version under the same key)
        the withdrawal is written as a general record, which may cite events or receipts only."""
        self.project_record('Plain project rule', key='plain-key')
        source = {'type': 'file_line', 'path': 'a.txt', 'line': 1, 'revision': 'HEAD'}
        knowledge.withdraw(self.ledger, 'P1', 'ctx-plain-key', reason='shown wrong', evidence={'sources': [source]})      # control
        shared = self.both_scopes()
        try:
            knowledge.withdraw(self.ledger, 'P1', shared['id'], reason='shown wrong', evidence={'sources': [source]}); refused = None
        except LedgerError as error:
            refused = str(error)
        say('dl03 withdraw with a file_line source', refused)
        self.assertIsNone(refused)

    def test_dl04_old_data_the_owner_withdraws_its_project_record_with_a_reason_naming_a_project_file(self):
        self.project_record('Plain project rule', key='plain-key')
        reason = 'a.txt changed: this rule no longer holds'
        knowledge.withdraw(self.ledger, 'P1', 'ctx-plain-key', reason=reason, evidence=self.evidence(self.ledger))         # control
        shared = self.both_scopes()
        second = self.second_project()
        try:
            knowledge.withdraw(self.ledger, 'P1', shared['id'], reason=reason, evidence=self.evidence(self.ledger)); refused = None
        except LedgerError as error:
            refused = str(error)
        two = self.retrieved('--scope', 'general', project=second.project)
        say('dl04 withdraw with a reason naming a.txt', refused, 'project two still gets', brief(two.get('Shared rule under the reused key')))
        self.assertIsNone(refused)

    def test_dl05_old_data_the_owner_sees_in_its_history_the_version_other_projects_receive(self):
        """Changed (D6, then E2). The review offered two answers; the first chosen one (other projects stop receiving a version its project
        replaced) let other projects observe the writer's unshared records (E2) and read them on every package (E3). Now: other projects keep
        receiving the published version as before, and the owner's `wiki history` shows it under `published`, so the owner can withdraw it
        (p02b: the withdrawal reaches every project)."""
        self.both_scopes()
        second = self.second_project()
        one = self.rows()
        two = self.retrieved('--scope', 'general', project=second.project)
        row = one.get('Project rule under the reused key') or {}
        say('dl05 owner history', {t: (r['id'], r['scope'], r['status'], r.get('published')) for t, r in one.items()}, 'project two gets',
            {t: brief(e) for t, e in two.items()})
        self.assertEqual((row.get('published') or {}).get('text'), 'Shared rule under the reused key')
        self.assertIn('Shared rule under the reused key', two)

    def test_dl06_a_root_working_note_under_a_key_does_not_block_a_general_record_with_that_key(self):
        """_key_in_other_scope compares raw keys; a root-visible record is `ctx-<key>.r<root>`, another subject than `ctx-<key>`."""
        knowledge.record(self.ledger, 'P1', kind='note', text='Root working note under a key', visibility='root', key='note-key',
                         evidence={'status': 'observed', 'sources': [{'type': 'event', 'id': self.ledger_event()}]})
        try:
            out, refused = self.general('Shared rule under the same key', HERE, key='note-key'), None
        except LedgerError as error:
            out, refused = None, str(error)
        say('dl06', {r['text']: r['id'] for r in knowledge.records(self.ledger, history=True)}, refused)
        self.assertIsNone(refused)

    def test_dl07_a_22_general_note_under_a_key_is_its_own_subject_and_nothing_private_is_published(self):
        """Changed (D3). `context add --scope general --key K` writes a 2.2-style entry, root-visible: its id is `ctx-K.r<root>`, another
        subject than the 2.3 project record `ctx-K`, so the one-key-one-subject rule holds. Withdrawing the project record stays a project
        record: its reason is never published to other projects."""
        self.project_record('Project rule under a key', key='k7')
        out = io.StringIO()
        from onecrew.v2 import cli
        with contextlib.redirect_stdout(out):
            code = cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'context', 'add', 'P1', '--kind', 'note',
                             '--label', 'observed', '--text', 'Shared note under the same key', '--source', f'event:{self.ledger_event()}',
                             '--scope', 'general', '--condition', 'when retrying', '--key', 'k7'])
        second = self.second_project()
        withdrawal = knowledge.withdraw(self.ledger, 'P1', 'ctx-k7', reason='INTERNAL-ONLY reason', evidence=self.evidence(self.ledger))
        two = self.cli_for(second.project, 'context', 'retrieve', '--scope', 'general')
        published = [e['text'] for e in two['entries'] if 'INTERNAL-ONLY' in e['text']]
        ids = {r['text']: r['id'] for r in knowledge.records(self.ledger, history=True)}
        say('dl07 context add exit', code, 'withdrawal', {k: withdrawal.get(k) for k in ('id', 'recorded', 'published')}, 'project two receives', published, ids)
        self.assertEqual(code, 0)
        self.assertEqual(published, [])
        self.assertIsNone(withdrawal.get('published'))
        self.assertIn('Shared note under the same key', [e['text'] for e in two['entries']])
        self.assertNotEqual(ids.get('Shared note under the same key'), 'ctx-k7')

    # ---- R8 + R3: old lesson-keyed data ------------------------------------------------------------------------------------
    def test_dl08_another_projects_conflict_under_a_lesson_key_does_not_contest_our_record(self):
        """conflict_with of a lesson-keyed 2.3 record is stored as `lesson-<key>` (unqualified); _in_reader_terms leaves lesson- ids as
        written and _lesson_targets maps withdraws/archives only, so the R8 contest loop marks the READER's own subject."""
        with self.old_lesson_keys(): self.general('Lesson-keyed rule of project one', HERE, key='lesson-shared')
        second = self.second_project()
        with self.old_lesson_keys():
            self.general('Lesson-keyed rule of project two, first', HERE, ledger=second, plan='Q1', key='lesson-shared')
            v2 = self.general('Lesson-keyed rule of project two, concurrent', HERE, ledger=second, plan='Q1', key='lesson-shared', base='')
        self.assertTrue(v2.get('conflict'), v2)
        seen, _ = self.seen()
        say('dl08 package of project one', self.uses(seen))
        self.assertEqual(seen.get('Lesson-keyed rule of project one', {}).get('use'), 'fact')

    # ---- R1: what is still recorded although it names nothing ------------------------------------------------------------
    def test_dl09_a_withdrawal_of_a_lesson_or_wiki_id_that_names_nothing_is_refused(self):
        results = {}
        for target in ('lesson-0123456789abcdef0123456789abcdef', 'no-such-wiki-section'):
            try:
                out = knowledge.withdraw(self.ledger, 'P1', target, reason='typo', evidence=self.evidence(self.ledger))
                results[target] = {'recorded': out.get('recorded')}
            except LedgerError as error:
                results[target] = {'refused': str(error)[:120]}
        say('dl09', results)
        for target, result in results.items():
            with self.subTest(target=target):
                self.assertIn('refused', result)

    # ---- R4: a package sealed before the upgrade --------------------------------------------------------------------------
    def test_dl10_a_rejection_from_a_package_sealed_by_dev5_names_the_subject_judged(self):
        current = getattr(knowledge, '_current_id', None)
        if current is None: self.skipTest('no _current_id before 926bdcf')
        second = self.second_project()
        self.general('Rule of project two', HERE, ledger=second, plan='Q1', key='retry-policy')
        mine = self.general('Rule of project one', HERE, key='own-policy')
        rows = self.rows()
        theirs_event, mine_event = rows['Rule of project two']['event'], rows['Rule of project one']['event']
        store = Snapshots(self.ledger.state_root)
        view = {'entries': [{'id': 'ctx-retry-policy', 'origin': {'type': 'ledger', 'event': theirs_event}},
                            {'id': 'ctx-own-policy', 'origin': {'type': 'ledger', 'event': mine_event}}]}
        record = {'package': store.blob(canonical(view).encode('utf-8'))}
        got = {i: current(self.ledger, store, record, i) for i in ('ctx-retry-policy', 'ctx-own-policy', 'ctx-not-delivered')}
        expected = rows['Rule of project two']['id']
        say('dl10', got, 'expected for the shared one', expected, mine['id'])
        self.assertEqual(got, {'ctx-retry-policy': expected, 'ctx-own-policy': 'ctx-own-policy', 'ctx-not-delivered': 'ctx-not-delivered'})


class ReviewDev6LastDelta(Base):
    """el01 and el02 of the last delta review (review-p2b.md, "Delta review of 4516cc5 and a87389f"), kept as written."""

    def rows(self, ledger=None):
        return {r['text']: r for r in knowledge.records(ledger or self.ledger, history=True)}

    def seen(self, plan='P1'):
        pkg = knowledge.package(self.ledger, knowledge.consumer(self.ledger, plan), cap_chars=12000)
        out = {e['title']: e for e in pkg['entries']}
        out.update({r['title']: r for r in pkg['omitted']['index'] if r['title'] not in out})
        return out, pkg

    def reference_lint(self):
        return [p['problem'] for p in knowledge.pages_report(self.ledger)['problems'] if 'plain id' in p['problem']]

    def test_el01_a_reference_to_our_own_record_can_be_written_without_a_permanent_problem(self):
        self.general('Own shared rule', HERE, key='retry-policy')
        second = self.second_project()
        self.general('Rule of project two', HERE, ledger=second, plan='Q1', key='retry-policy')
        own_tag = knowledge.project_tags(self.ledger)[self.ledger.project_id]
        results = {}
        for spelling in ('ctx-retry-policy', 'ctx-retry-policy@' + own_tag):
            self.page('rules.md', '## Project replacement of our own retry rule\n' + fence({'id': 'own-replacement', 'kind': 'decision',
                      'supersedes': [spelling]}) + 'Use the replacement here.\n')
            seen, pkg = self.seen()
            results[spelling] = {'own record superseded': 'Own shared rule' not in seen, 'lint': self.reference_lint(),
                                 'package problems': [p['problem'][:90] for p in pkg['problems'] if 'plain id' in p['problem']]}
        say('el01', results)
        self.assertTrue(any(r['own record superseded'] and not r['lint'] for r in results.values()), results)

    def test_el02_another_projects_private_writes_are_not_observable_through_its_shared_record(self):
        second = self.second_project()
        self.general('Shared rule of project two', HERE, ledger=second, plan='Q1', key='reused-key')
        before = self.rows()['Shared rule of project two']
        with patch.object(knowledge, '_key_in_other_scope', return_value=False):
            knowledge.record(second, 'Q1', kind='decision', text='Private rule of project two', key='reused-key',
                             evidence={'status': 'observed', 'sources': [{'type': 'event', 'id': self.event_of(second)}]})
        after = self.rows()['Shared rule of project two']
        say('el02 project one sees project two shared record', {k: before[k] for k in ('status', 'status_reason')}, '->',
            {k: after[k] for k in ('status', 'status_reason')})
        self.assertEqual((after['status'], after['status_reason']), (before['status'], before['status_reason']))

    def test_el01b_a_ledger_reference_in_the_own_tag_form_names_our_own_record(self):
        own = self.general('Own shared rule to replace', HERE, key='own-policy')
        tag = knowledge.project_tags(self.ledger)[self.ledger.project_id]
        written = self.project_record('Project rule replacing our own shared rule', supersedes=[own['id'] + '@' + tag])
        rows = self.rows()
        self.assertEqual(rows['Project rule replacing our own shared rule']['supersedes'], [own['id']])
        self.assertEqual(rows['Own shared rule to replace']['status'], 'superseded')
        self.assertTrue(written['id'])


if __name__ == "__main__":
    import unittest
    unittest.main()
