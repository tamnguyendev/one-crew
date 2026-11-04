"""Independent review (agent Opus 5.5, 29/10) of ebcfa20 = the Codex dev5 review P2-B fix, kept as tests (lesson LL-10). Report and runs on
ebcfa20 and b3ecc57: D:/OneCrewRuns/v23/review-dev6/review-p2b.md. The probes assert the EXPECTED behaviour; findings R1, R3, R4, R5, R6, R8,
R11, R12 and R15 were fixed in 2.3.0.dev6 and these probes are their tests. Changed from the reviewer's file, each saying why: p02/p02b (R7:
one key names one subject of a project; writing it in the other scope is refused, and old data that has both is withdrawn for every
project), p10 (R12: the tag is not derived from the path at all), p12 (R15: an old reference to a key nobody had keeps its old reading);
the timing probes p11/p11b are not kept (no assertion beyond a count; numbers in the report).
"""
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import Ledger, LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import context, knowledge
from onecrew.v2 import plan as plans
from tests.test_v2_l1 import plan_json
from tests.test_v23_a1_knowledge import fence
from tests.test_v23_review_dev4 import Base, HERE, brief, say


class ReviewDev6(Base):
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
        """title -> delivered entry or omitted index row of the plan package of project one."""
        pkg = knowledge.package(self.ledger, knowledge.consumer(self.ledger, plan), cap_chars=12000)
        out = {e['title']: e for e in pkg['entries']}
        out.update({r['title']: r for r in pkg['omitted']['index'] if r['title'] not in out})
        return out, pkg

    def uses(self, seen):
        return {t: (e.get('use'), e.get('id'), [r[:70] for r in (e.get('applicability') or {}).get('reasons', [])]) for t, e in seen.items()}

    def old_format(self):
        """Write as 2.3.0.dev5 wrote (knowledge format 2). On b3ecc57 there is no FORMAT: records are format 2 there anyway."""
        return patch.object(knowledge, 'FORMAT', 2, create=True)

    def evidence(self, ledger):
        return {'sources': [{'type': 'event', 'id': self.event_of(ledger)}]}

    # ---- id rule: keys that start with `lesson-` ----------------------------------------------------------------------------
    def old_lesson_keys(self):
        """2.3.0.dev5 accepted `--key lesson-...` for a 2.3 record; 2.3.0.dev6 refuses it for new records (R3). Old ones stay readable and
        follow the project rule; the probes below write them as old data."""
        return patch.object(knowledge, 'RESERVED_KEY_PREFIXES', ())

    def test_p01_new_records_cannot_take_a_lesson_key(self):
        with self.assertRaises(LedgerError) as caught:
            self.general('Rule under a lesson key', HERE, key='lesson-retry-policy')
        self.assertIn('lesson-', str(caught.exception))

    def test_p01a_lesson_prefixed_key_reused_by_two_projects_keeps_two_subjects(self):
        """ledger_id returns a key starting with `lesson-` unqualified, before the project rule: `wiki record --scope general --key
        lesson-...` from two projects is the P2-B case again (key_field accepts the name; 2.2 general lesson index entries exist too)."""
        with self.old_lesson_keys(): self.general('Rule of project one under a lesson key', HERE, key='lesson-retry-policy')
        second = self.second_project()
        with self.old_lesson_keys(): self.general('Rule of project two under a lesson key', HERE, ledger=second, plan='Q1', key='lesson-retry-policy')
        one = self.rows()
        say('p01 history of project one', {t: (r['id'], r['status']) for t, r in one.items()})
        entries = self.retrieved('--plan', 'P1', '--scope', 'general')
        say('p01 retrieve --plan P1 --scope general', {t: brief(e) for t, e in entries.items()})
        self.assertIn('Rule of project one under a lesson key', one)
        self.assertIn('Rule of project two under a lesson key', one)
        self.assertNotEqual(one['Rule of project one under a lesson key']['id'], one['Rule of project two under a lesson key']['id'])
        self.assertEqual(entries['Rule of project one under a lesson key']['label'], 'verified', entries['Rule of project one under a lesson key'])

    def test_p01b_the_owner_withdraws_its_own_lesson_keyed_general_record(self):
        with self.old_lesson_keys(): mine = self.general('Own rule under a lesson key', HERE, key='lesson-retry-policy')
        second = self.second_project()
        with self.old_lesson_keys(): self.general('Newer rule of project two under a lesson key', HERE, ledger=second, plan='Q1', key='lesson-retry-policy')
        try:
            knowledge.withdraw(self.ledger, 'P1', mine['id'], reason='wrong here', evidence=self.evidence(self.ledger)); refused = None
        except LedgerError as error:
            refused = str(error)
        say('p01b withdraw own', mine['id'], refused)
        self.assertIsNone(refused)
        two = self.retrieved('--scope', 'general', project=second.project)
        self.assertIn('Newer rule of project two under a lesson key', two)
        self.assertNotIn('Own rule under a lesson key', two)

    def test_p01c_another_projects_withdrawal_of_its_lesson_keyed_record_does_not_remove_ours(self):
        with self.old_lesson_keys(): self.general('Kept rule of project one under a lesson key', HERE, key='lesson-retry-policy')
        second = self.second_project()
        with self.old_lesson_keys(): theirs = self.general('Rule project two withdraws under a lesson key', HERE, ledger=second, plan='Q1', key='lesson-retry-policy')
        knowledge.withdraw(second, 'Q1', theirs['id'], reason='wrong there', evidence=self.evidence(second))
        for form in (('--scope', 'general'), ('--plan', 'P1', '--scope', 'general')):
            with self.subTest(form=form):
                entries = self.retrieved(*form)
                say('p01c ' + ' '.join(form), {t: brief(e) for t, e in entries.items()})
                self.assertIn('Kept rule of project one under a lesson key', entries)
                self.assertNotIn('Rule project two withdraws under a lesson key', entries)

    # ---- one project: a general and a project record under one --key (pre-existing, same root cause: ids without the scope) --
    def test_p02_one_projects_general_and_project_record_under_one_key_is_refused_at_write(self):
        """Changed (R7). A key names one subject of a project; the write path compared versions per (key, scope) while the read path named
        the subject by key, so a general and a project record under one --key were one id with two meanings. Now the second scope is refused
        at write time with what to do."""
        shared = self.general('Shared rule of project one', HERE, key='reused-key')
        with self.assertRaises(LedgerError) as caught:
            self.project_record('Project rule of project one', key='reused-key')
        self.assertIn('already names a general record of this project', str(caught.exception))
        knowledge.record(self.ledger, 'P1', kind='decision', text='Project rule first', key='other-key',
                         evidence={'status': 'observed', 'sources': [{'type': 'event', 'id': self.ledger_event()}]})
        with self.assertRaises(LedgerError) as mirror:
            self.general('Shared rule under the project key', HERE, key='other-key')
        self.assertIn('already names a project record of this project', str(mirror.exception))
        self.assertEqual(shared['id'], 'ctx-reused-key')

    def test_p02b_old_data_withdrawing_the_subject_reaches_every_project(self):
        """Changed (R7). Data written before the key rule (both scopes under one key): the subject is one; withdrawing it is written as a
        general record, so the general version is gone for the other project too (before: a project-scope withdrawal, the general version
        stayed current elsewhere)."""
        shared = self.general('Shared rule withdrawn by its owner', HERE, key='reused-key')
        with patch.object(knowledge, '_key_in_other_scope', return_value=False):
            self.project_record('Project rule under the same key', key='reused-key')
        second = self.second_project()
        out = knowledge.withdraw(self.ledger, 'P1', shared['id'], reason='wrong everywhere', evidence=self.evidence(self.ledger))
        two = self.retrieved('--scope', 'general', project=second.project)
        mine = self.retrieved('--plan', 'P1', '--scope', 'both')
        say('p02b withdrawal', {k: out.get(k) for k in ('id', 'key', 'recorded')}, 'project two sees', {t: brief(e) for t, e in two.items()},
            'project one sees', {t: brief(e) for t, e in mine.items()})
        self.assertNotIn('Shared rule withdrawn by its owner', two)          # the general version is gone for the other project
        self.assertNotIn('Shared rule withdrawn by its owner', mine)
        self.assertNotIn('Project rule under the same key', mine)            # one subject: its versions go with it

    # ---- old data (format <= 2) ---------------------------------------------------------------------------------------------
    def contradiction(self, target, text='The worker of node C rejected the shared retry rule: wrong here'):
        """What after_verification writes when a worker rejects a delivered entry (contradicts=[the delivered id])."""
        return knowledge.record(self.ledger, 'P1', kind='finding', text=text, visibility='project', contradicts=[target],
                                evidence={'status': 'observed', 'sources': [{'type': 'event', 'id': self.ledger_event()}]})

    def test_p03_an_old_contradiction_of_another_projects_general_record_keeps_acting_on_it(self):
        """dev5 delivered project two's general record to project one's worker as `ctx-retry-policy`; the worker rejected it and the
        engine stored contradicts=['ctx-retry-policy'] (format 2). _legacy_aliases maps supersedes/derived_from/conflict_with only."""
        second = self.second_project()
        self.general('Rule of project two', HERE, ledger=second, plan='Q1', key='retry-policy')
        before, _ = self.seen()
        with self.old_format(): self.contradiction('ctx-retry-policy')
        after, _ = self.seen()
        say('p03 before', self.uses(before), 'after', self.uses(after))
        self.assertEqual(before['Rule of project two']['use'], 'fact')                 # control
        self.assertEqual(after['Rule of project two']['use'], 'lead')                  # the rejection still applies to the record judged

    def test_p03b_an_old_contradiction_is_not_taken_over_by_a_later_own_subject(self):
        second = self.second_project()
        self.general('Rule of project two', HERE, ledger=second, plan='Q1', key='retry-policy')
        with self.old_format(): self.contradiction('ctx-retry-policy')
        self.general('Own shared rule written later', HERE, key='retry-policy')
        after, _ = self.seen()
        say('p03b', self.uses(after))
        self.assertEqual(after['Own shared rule written later']['use'], 'fact')

    def test_p04_an_old_conflict_version_contests_the_writers_own_subject_not_another_projects(self):
        """record() stores conflict_with=[ctx-<key>] for the WRITER's own subject (context.add compared the writer's own newest version).
        _legacy_aliases resolves that old reference by time to another project's newer general record."""
        self.general('Own shared rule, first', HERE, key='retry-policy')
        second = self.second_project()
        self.general('Rule of project two', HERE, ledger=second, plan='Q1', key='retry-policy')
        with self.old_format(): concurrent = self.general('Own shared rule, concurrent', HERE, key='retry-policy', base='')
        self.assertTrue(concurrent.get('conflict'), concurrent)
        seen, _ = self.seen()
        one = self.rows()
        say('p04 package', self.uses(seen), 'conflict_with in history', {t: r['conflict_with'] for t, r in one.items()})
        self.assertEqual((seen.get('Rule of project two', {}).get('use'), seen.get('Own shared rule, first', {}).get('use')), ('fact', 'lead'))

    def test_p05_another_projects_contested_general_versions_are_not_current_for_other_projects(self):
        """c03 (same project): contested general versions are never current. Pre-existing: another project's conflict record does not act
        for a reader (_acts_for), so both of its concurrent versions are delivered as verified elsewhere."""
        second = self.second_project()
        self.general('Contested rule of project two, first', HERE, ledger=second, plan='Q1', key='contested-subject')
        v2 = self.general('Contested rule of project two, second', HERE, ledger=second, plan='Q1', key='contested-subject', base='')
        self.assertTrue(v2.get('conflict'), v2)
        theirs = self.retrieved('--plan', 'Q1', '--scope', 'general', project=second.project)
        ours = self.retrieved('--plan', 'P1', '--scope', 'general')
        say('p05 writer', {t: brief(e) for t, e in theirs.items()}, 'other project', {t: brief(e) for t, e in ours.items()})
        for text in ('Contested rule of project two, first', 'Contested rule of project two, second'):
            with self.subTest(text=text):
                self.assertNotEqual(theirs[text]['label'], 'verified')                 # control: the writer's own view (c03)
                self.assertNotEqual(ours[text]['label'], 'verified')

    def test_p06_a_summary_of_another_projects_receipt_sourced_record_exists_and_follows_its_withdrawal(self):
        """test_h (codex_review_dev5) says no summary across projects can exist: true for event-sourced records only; a general record
        may cite a receipt of the shared state root, and then summarize accepts it. Its lifecycle must still follow the owner."""
        second = self.second_project()
        receipt = Snapshots(self.ledger.state_root).blob(b'probe receipt of project two')
        theirs = knowledge.record(second, 'Q1', kind='decision', text='Receipt-backed rule of project two', scope='general', conditions=[HERE],
                                  key='retry-policy', evidence={'status': 'verified', 'property': 'the retry check passed',
                                                                'sources': [{'type': 'receipt', 'key': receipt}]})
        ident = next(r['id'] for r in knowledge.records(self.ledger, history=True) if r['text'] == 'Receipt-backed rule of project two')
        summary = knowledge.summarize(self.ledger, 'P1', [ident], text='Summary of the shared receipt-backed rule')
        say('p06 summary written', ident, {k: summary.get(k) for k in ('id', 'recorded')})
        self.assertEqual(self.rows()['Summary of the shared receipt-backed rule']['status'], 'active')
        knowledge.withdraw(second, 'Q1', theirs['id'], reason='wrong there', evidence=self.evidence(second))
        one = self.rows()
        seen, _ = self.seen()
        say('p06 after the owner withdrew', {t: (r['status'], r['derived_from']) for t, r in one.items()}, self.uses(seen))
        self.assertEqual(one['Summary of the shared receipt-backed rule']['status'], 'source_withdrawn')
        self.assertNotIn('Summary of the shared receipt-backed rule', seen)

    def test_p07_an_old_wiki_section_that_superseded_the_shared_record_it_saw_keeps_superseding_it(self):
        """A wiki page of project one written under dev5 with `supersedes: ["ctx-retry-policy"]`: then the only subject with that id was
        project two's general record. Wiki pages carry no format or time; _legacy_aliases reads ledger records only."""
        second = self.second_project()
        self.general('Rule of project two', HERE, ledger=second, plan='Q1', key='retry-policy')
        self.page('rules.md', '## Project replacement of the shared retry rule\n' + fence({'id': 'retry-replacement', 'kind': 'decision',
                  'supersedes': ['ctx-retry-policy']}) + 'Use the project retry rule here.\n')
        seen, pkg = self.seen()
        say('p07 package', self.uses(seen), pkg['omitted']['by_reason'])
        self.assertIn('Project replacement of the shared retry rule', seen)              # control: the wiki section is read
        self.assertNotIn('Rule of project two', seen)

    def test_p08_a_record_with_a_non_integer_knowledge_version_does_not_take_the_readers_down(self):
        """_legacy_aliases compares `knowledge.version` with FORMAT outside the per-entry try (c11 keeps a malformed record from hiding
        the others)."""
        second = self.second_project()
        self.general('Rule of project two', HERE, ledger=second, plan='Q1', key='retry-policy')
        context.add(self.ledger, 'P1', kind='note', label='observed', text='Own record from another writer', key='odd-version',
                    source={'type': 'event', 'id': self.ledger_event()}, extra={'version': '2', 'visibility': 'project'})
        try:
            rows, failure = self.rows(), None
        except Exception as error:
            rows, failure = {}, f'{type(error).__name__}: {error}'
        try:
            self.seen(); package_failure = None
        except Exception as error:
            package_failure = f'{type(error).__name__}: {error}'
        say('p08 records', failure, 'package', package_failure)
        self.assertIsNone(failure)
        self.assertIsNone(package_failure)
        self.assertIn('Rule of project two', rows)

    def test_p12_an_old_reference_to_a_key_nobody_had_keeps_its_old_reading(self):
        """Changed (R15). The reviewer read the old docstring ("a reference that named nothing still names nothing") as a promise; the rule is
        now stated as it is: an old reference to a key no subject had when it was written is left as written, so it names the reader's OWN
        subject of that key, also one written later (as format 3, and as before P2-B). Another project's record written later is not named."""
        second = self.second_project()
        with self.old_format(): self.project_record('Old project rule naming a subject that did not exist yet', supersedes=['ctx-retry-policy'])
        self.general('Rule of project two written later', HERE, ledger=second, plan='Q1', key='retry-policy')
        self.general('Own shared rule written later', HERE, key='retry-policy')
        one = self.rows()
        say('p12', {t: (r['id'], r['status'], r['supersedes']) for t, r in one.items()})
        self.assertEqual((one.get('Own shared rule written later', {}).get('status'), one.get('Rule of project two written later', {}).get('status')),
                         ('superseded', 'active'))

    # ---- write path and permission -------------------------------------------------------------------------------------------
    def test_p09_the_owner_withdrawing_with_the_id_another_project_shows_is_refused_or_acts(self):
        self.general('Rule of project one', HERE, key='retry-policy')
        second = self.second_project()
        self.general('Rule of project two', HERE, ledger=second, plan='Q1', key='retry-policy')
        shown = next(r['id'] for r in knowledge.records(self.ledger, history=True) if r['text'] == 'Rule of project two')
        try:
            out, refused = knowledge.withdraw(second, 'Q1', shown, reason='wrong', evidence=self.evidence(second)), None
        except LedgerError as error:
            out, refused = None, str(error)
        two, one = self.rows(second), self.rows()
        say('p09 id shown to project one', shown, 'withdraw in project two:', refused or {k: out.get(k) for k in ('id', 'recorded')},
            'status for project two', two['Rule of project two']['status'], 'for project one', one['Rule of project two']['status'])
        self.assertTrue(refused is not None or two['Rule of project two']['status'] == 'withdrawn',
                        'the withdrawal was recorded and acts on nothing')

    def test_p09b_the_refusal_in_the_reader_project_then_the_same_command_in_the_writer_project(self):
        """The natural owner flow: `wiki withdraw <id from wiki history>` in project one is refused ("only the project that wrote a general
        entry can withdraw it"); the owner runs the same command with the same id in project two."""
        self.general('Rule of project one', HERE, key='retry-policy')
        second = self.second_project()
        self.general('Wrong rule of project two', HERE, ledger=second, plan='Q1', key='retry-policy')
        shown = next(r['id'] for r in self.cli('wiki', 'history')['records'] if r['text'] == 'Wrong rule of project two')
        from onecrew.v2 import cli
        import contextlib, io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'wiki', 'withdraw', shown, '--plan', 'P1',
                             '--reason', 'wrong everywhere', '--source', f'event:{self.ledger_event()}'])
        first = (code, out.getvalue().strip()[:200])
        again = self.cli_for(second.project, 'wiki', 'withdraw', shown, '--plan', 'Q1', '--reason', 'wrong everywhere', '--source',
                             f'event:{self.event_of(second)}')
        delivered = self.retrieved('--plan', 'P1', '--scope', 'general')
        say('p09b id shown in project one', shown, 'project one:', first, 'project two:', {k: again.get(k) for k in ('id', 'recorded')},
            'project one still gets', brief(delivered.get('Wrong rule of project two')))
        self.assertNotEqual(first[0], 0)                                                   # control: refused where it does not belong
        self.assertNotIn('Wrong rule of project two', delivered)

    def test_p10_another_projects_subject_id_carries_no_confirmable_hash_of_its_path(self):
        """Changed (R12): the tag comes from the project's first task id (random), so neither a hash of a guessed path nor the project id
        (itself a hash of the path) appears in another project's worker view."""
        second = self.second_project()
        self.general('Rule of project two', HERE, ledger=second, plan='Q1', key='retry-policy')
        _, pkg = self.seen()
        text = json.dumps(knowledge.prompt_view(pkg), ensure_ascii=False)
        guess = hashlib.sha256(os.path.normcase(str(Path(second.project).resolve())).encode('utf-8')).hexdigest()[:12]
        say('p10 sha256(normcase(path))[:12] of project two', guess, 'in the worker view of project one:', guess in text)
        self.assertNotIn(guess, text)
        self.assertNotIn(second.project_id[:12], text)
        self.assertIn('ctx-retry-policy@' + knowledge.project_tags(self.ledger)[second.project_id], text)


if __name__ == "__main__":
    import unittest
    unittest.main()
