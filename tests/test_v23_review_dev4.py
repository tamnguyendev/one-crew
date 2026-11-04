"""Independent review (agent Opus 5.5, 29/10) of 6a8e400 = the fix of Codex dev3 review P2 (`context retrieve` judges shared/general
knowledge like the package). The reviewer's probes, kept as tests (lesson LL-10); each asserts the EXPECTED behaviour. Report and runs on
6a8e400 and on the pre-fix tree: D:/OneCrewRuns/v23/review-dev4/review-dev4.md. Fixed in 2.3.0.dev5: F1/F1b (r01, r01b, r01c: a
superseded shared record stays gone for every reader), F2/r02a and r03 (a verdict applies only to the record it judged; r03b mirrors r03).
Delta review of 9a2b453: class Delta (d01-d05), no new finding.
r02b, r02c, r02d (an old gap, expected failures in 2.3.0.dev5, Codex dev5 review P2-B): two projects of one state root that reuse the same
explicit --key for general records shared one knowledge id (ledger_id), so one record hid the other, one project's withdrawal acted on both
and the second project could not withdraw its own. Fixed in 2.3.0.dev6 (a subject belongs to the project that wrote it): plain tests now;
more cases in tests/test_v23_codex_review_dev5.py.
"""
import contextlib
import io
import json
import unittest
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import Ledger
from onecrew.v2 import context, knowledge
from onecrew.v2 import plan as plans
from tests import test_v23_a2_knowledge as a2
from tests.test_v23_a2_knowledge import A2Fixture
from tests.test_v2_l1 import plan_json

ELSEWHERE = 'linux' if sys.platform != 'linux' else 'win32'
HERE = {'type': 'env', 'key': 'platform', 'value': sys.platform}
THERE = {'type': 'env', 'key': 'platform', 'value': ELSEWHERE}


def say(tag, *values):
    print(f'\nPROBE {tag}:', *[v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)[:1500] for v in values], flush=True)


def brief(entry):
    if entry is None: return None
    return {k: entry.get(k) for k in ('label', 'stored_label', 'stale_reason', 'scope', 'key')}


class Base(A2Fixture):
    ledger_event = a2.RecordingTests.ledger_event

    # ---- CLI for any project of the state root ----
    def cli_for(self, project, *args):
        from onecrew.v2 import cli
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(['--project', str(project), '--state-root', str(self.ledger.state_root), *args])
        self.assertEqual(code, 0, out.getvalue())
        return json.loads(out.getvalue())

    def cli(self, *args):
        return self.cli_for(self.root, *args)

    def retrieved(self, *form, project=None):
        return {e['text']: e for e in self.cli_for(project or self.root, 'context', 'retrieve', *form)['entries']}

    def event_of(self, ledger):
        with ledger.transaction() as conn:
            return conn.execute("SELECT MAX(e.seq) FROM events e JOIN tasks t ON t.id=e.task_id WHERE t.project_id=?",
                                (ledger.project_id,)).fetchone()[0]

    def general(self, text, *conditions, ledger=None, plan='P1', key=None, base=None, status='verified'):
        ledger = ledger or self.ledger
        return knowledge.record(ledger, plan, kind='decision', text=text, scope='general', conditions=list(conditions), key=key, base=base,
                                evidence={'status': status, 'property': 'the retry check passed' if status == 'verified' else None,
                                          'sources': [{'type': 'event', 'id': self.event_of(ledger)}]})

    def project_record(self, text, plan='P1', files=(), **kw):
        sources = [{'type': 'event', 'id': self.ledger_event()}] + [{'type': 'file', 'path': f, 'revision': 'HEAD'} for f in files]
        return knowledge.record(self.ledger, plan, kind='decision', text=text,
                                evidence={'status': 'verified', 'property': 'agreed in review', 'sources': sources}, **kw)

    def second_project(self):
        other = Path(self.temp.name) / 'other'; other.mkdir()
        g = lambda *a: subprocess.run(['git', '-C', str(other), *a], check=True, capture_output=True, text=True).stdout.strip()
        g('init', '-q'); g('config', 'user.email', 't@localhost'); g('config', 'user.name', 'T')
        (other / 'z.txt').write_text('other\n')
        g('add', '.'); g('commit', '-qm', 'o')
        second = Ledger(other, self.ledger.state_root)
        plans.propose(second, 'Q1', plan_json(), 'codex')
        return second

    def history(self):
        return {r['id']: r for r in self.cli('wiki', 'history')['records']}


# ---- lifecycle -----------------------------------------------------------------------------------------------------------------

class Lifecycle(Base):
    def test_r01_superseded_general_record_stays_gone_for_the_rootless_reader(self):
        """A project record that supersedes a general record cites a file (as most project records do). `context retrieve` without
        --plan lists that superseder itself; the superseded general record must not come back (pre-fix: left out by status_by_id)."""
        g = self.general('Replaced shared retry rule', HERE)
        self.project_record('Project rule replacing the shared retry rule', files=('a.txt',), supersedes=[g['id']])
        self.assertEqual(self.history()[g['id']]['status'], 'superseded')
        for form in (('--scope', 'general'), ('--scope', 'both'), ('--plan', 'P1', '--scope', 'general'), ('--plan', 'P1', '--scope', 'both')):
            with self.subTest(form=form):
                entries = self.retrieved(*form)
                say('r01 ' + ' '.join(form), brief(entries.get('Replaced shared retry rule')),
                    'superseder listed:', 'Project rule replacing the shared retry rule' in entries)
                self.assertNotIn('Replaced shared retry rule', entries)

    def test_r01b_superseded_22_shared_lesson_index_stays_gone_and_keeps_the_22_rule(self):
        """A 2.2 general entry with a lesson key (visibility project by its key) superseded by a project record citing a file."""
        context.add(self.ledger, 'P1', kind='note', label='verified', text='Shared lesson index entry', scope='general', conditions=['Python'],
                    source={'type': 'event', 'id': self.ledger_event()}, key='lesson-0123abcd')
        self.project_record('Project rule replacing the shared lesson', files=('a.txt',), supersedes=['lesson-0123abcd'])
        say('r01b history', {k: v['status'] for k, v in self.history().items()})
        for form in (('--scope', 'general'), ('--scope', 'both')):
            with self.subTest(form=form):
                entries = self.retrieved(*form)
                say('r01b ' + ' '.join(form), brief(entries.get('Shared lesson index entry')))
                self.assertNotIn('Shared lesson index entry', entries)

    def test_r01c_superseded_general_record_for_a_plan_that_cannot_read_the_superseder(self):
        """Superseder on P1 cites b.txt; P2's scope is a.txt only. Lifecycle rule of the brief: superseded never comes back.
        (The package's r3 R3-2 rule makes it a lead for P2: the probe also prints what `wiki show --plan P2` says.)"""
        g = self.general('Shared rule replaced on P1', HERE)
        self.root_b('P2')
        self.project_record('P1 rule replacing the shared rule', files=('b.txt',), supersedes=[g['id']])
        package = self.cli('wiki', 'show', '--plan', 'P2')
        seen = {e['id']: e['use'] for e in package['entries']}; seen.update({r['id']: r['use'] for r in package['omitted']['index']})
        say('r01c wiki show --plan P2', seen.get(g['id']), package['omitted']['by_reason'])
        entries = self.retrieved('--plan', 'P2', '--scope', 'general')
        say('r01c retrieve --plan P2 --scope general', brief(entries.get('Shared rule replaced on P1')))
        self.assertNotIn('Shared rule replaced on P1', entries)

    def test_c01_withdrawn_general_never_comes_back_with_a_plan_that_cannot_read_anything(self):
        g = self.general('Withdrawn shared rule', HERE)
        self.root_b('P2')
        self.cli('wiki', 'withdraw', g['id'], '--plan', 'P1', '--reason', 'shown wrong', '--source', f'event:{self.ledger_event()}')
        for form in (('--scope', 'general'), ('--plan', 'P2', '--scope', 'general'), ('--plan', 'P1', '--scope', 'both')):
            with self.subTest(form=form):
                self.assertNotIn('Withdrawn shared rule', self.retrieved(*form))

    def test_c02_general_update_does_not_resurrect_the_older_version(self):
        v1 = self.general('Shared retry rule, first wording', HERE, key='retry-subject')
        v2 = self.general('Shared retry rule, second wording', THERE, key='retry-subject', base=v1['version'])
        say('c02 versions', v1, v2)
        for form in (('--scope', 'general'), ('--plan', 'P1', '--scope', 'both')):
            with self.subTest(form=form):
                entries = self.retrieved(*form)
                say('c02 ' + ' '.join(form), {t: brief(e) for t, e in entries.items() if 'Shared retry' in t})
                self.assertNotIn('Shared retry rule, first wording', entries)
                self.assertEqual(entries['Shared retry rule, second wording']['label'], 'stale')

    def test_c03_contested_general_versions_are_never_current(self):
        v1 = self.general('Contested shared rule, first', HERE, key='contested-subject')
        v2 = self.general('Contested shared rule, second', HERE, key='contested-subject', base='')        # written from "no version"
        say('c03 versions', v1, v2)
        self.assertTrue(v2.get('conflict'), v2)
        for form in (('--scope', 'general'), ('--plan', 'P1', '--scope', 'general')):
            with self.subTest(form=form):
                entries = self.retrieved(*form)
                say('c03 ' + ' '.join(form), {t: brief(e) for t, e in entries.items() if 'Contested' in t})
                for text in ('Contested shared rule, first', 'Contested shared rule, second'):
                    self.assertNotEqual(entries[text]['label'], 'verified', entries[text])

    def test_c04_root_private_superseder_acts_only_for_its_root_and_the_memo_keeps_readers_apart(self):
        g = self.general('Shared rule P1 replaced privately', HERE)
        self.project_record('P1 private replacement', visibility='root', supersedes=[g['id']])
        everyone = self.retrieved('--scope', 'both')                        # the project: P1's private note does not act (P1's verdicts are
        mine = self.retrieved('--plan', 'P1', '--scope', 'both')             # computed first in the same memo)
        say('c04 no plan', brief(everyone.get('Shared rule P1 replaced privately')), '--plan P1', brief(mine.get('Shared rule P1 replaced privately')))
        self.assertEqual(everyone['Shared rule P1 replaced privately']['label'], 'verified')
        self.assertNotIn('Shared rule P1 replaced privately', mine)


# ---- the same subject id from another record -----------------------------------------------------------------------------------

class SameSubjectId(Base):
    def test_r02a_another_projects_general_record_with_the_same_key_does_not_lend_its_verdict(self):
        """Project one: general key `retry-policy`, condition false here. Project two (same state root): a newer general record with the
        same key whose condition holds. Both are listed by retrieve; project one's must still be stale (not applicable)."""
        self.general('Shared retry rule of project one', THERE, key='retry-policy')
        second = self.second_project()
        self.general('Shared retry rule of project two', HERE, ledger=second, plan='Q1', key='retry-policy')
        for form in (('--scope', 'general'), ('--plan', 'P1', '--scope', 'general')):
            with self.subTest(form=form):
                entries = self.retrieved(*form)
                say('r02a ' + ' '.join(form), {t: brief(e) for t, e in entries.items()})
                self.assertEqual(entries['Shared retry rule of project one']['label'], 'stale', entries['Shared retry rule of project one'])
                self.assertEqual(entries['Shared retry rule of project two']['label'], 'verified')

    def test_r02b_a_valid_general_record_is_not_hidden_by_another_projects_record_with_the_same_key(self):
        self.general('Valid shared rule of project one', HERE, key='retry-policy')
        second = self.second_project()
        self.general('Elsewhere rule of project two', THERE, ledger=second, plan='Q1', key='retry-policy')
        for form in (('--scope', 'general'), ('--plan', 'P1', '--scope', 'general')):
            with self.subTest(form=form):
                entries = self.retrieved(*form)
                say('r02b ' + ' '.join(form), {t: brief(e) for t, e in entries.items()})
                self.assertEqual((entries['Valid shared rule of project one']['label'], entries['Valid shared rule of project one']['stale_reason']),
                                 ('verified', None))

    def test_r02c_another_projects_withdrawal_of_its_own_record_does_not_remove_ours(self):
        mine = self.general('Valid shared rule kept by project one', HERE, key='retry-policy')
        second = self.second_project()
        theirs = self.general('Rule project two withdraws', HERE, ledger=second, plan='Q1', key='retry-policy')
        knowledge.withdraw(second, 'Q1', theirs['id'], reason='wrong there', evidence={'sources': [{'type': 'event', 'id': self.event_of(second)}]})
        package = self.cli('wiki', 'show', '--plan', 'P1')
        seen = {e['id']: e['use'] for e in package['entries']}; seen.update({r['id']: r['use'] for r in package['omitted']['index']})
        say('r02c wiki show --plan P1', seen.get(mine['id']), package['omitted']['by_reason'])
        for form in (('--scope', 'general'), ('--plan', 'P1', '--scope', 'general')):
            with self.subTest(form=form):
                entries = self.retrieved(*form)
                say('r02c ' + ' '.join(form), {t: brief(e) for t, e in entries.items()})
                self.assertIn('Valid shared rule kept by project one', entries)
                self.assertNotIn('Rule project two withdraws', entries)

    def test_r02d_a_project_can_withdraw_its_own_general_record_when_another_project_reused_the_key(self):
        """Related write-path check (same root cause): project one withdraws its own general record after project two wrote a newer
        general record with the same --key."""
        mine = self.general('Own shared rule to withdraw', HERE, key='retry-policy')
        second = self.second_project()
        self.general('Newer rule of project two', HERE, ledger=second, plan='Q1', key='retry-policy')
        try:
            knowledge.withdraw(self.ledger, 'P1', mine['id'], reason='wrong here', evidence={'sources': [{'type': 'event', 'id': self.ledger_event()}]})
            refused = None
        except Exception as error:
            refused = f'{type(error).__name__}: {error}'
        say('r02d withdraw own record', refused)
        self.assertIsNone(refused)
        self.assertNotIn('Own shared rule to withdraw', self.retrieved('--scope', 'general'))

    def test_r03_a_project_record_with_the_key_of_a_general_record_does_not_lend_its_verdict(self):
        """Same project: general record key `reused-key` (condition false here), then a project-visible record with the same --key."""
        self.general('Shared rule under a reused key', THERE, key='reused-key')
        with patch.object(knowledge, '_key_in_other_scope', return_value=False):          # data written before the key rule (review dev6 R7)
            self.project_record('Project rule under the reused key', key='reused-key')
        for form in (('--scope', 'general'), ('--plan', 'P1', '--scope', 'general'), ('--plan', 'P1', '--scope', 'both')):
            with self.subTest(form=form):
                entries = self.retrieved(*form)
                say('r03 ' + ' '.join(form), {t: brief(e) for t, e in entries.items()})
                self.assertEqual(entries['Shared rule under a reused key']['label'], 'stale', entries['Shared rule under a reused key'])

    def test_r03b_a_general_record_with_the_key_of_a_project_record_does_not_lend_its_verdict(self):
        """Mirror of r03 (2.3.0.dev5): a project record whose condition is false here, then a NEWER general record that holds here with
        the same --key: the project record is never shown as current on the general record's verdict."""
        self.project_record('Project rule for elsewhere under a reused key', key='mirror-key', applies_to=['a.txt'], conditions=[THERE])
        with patch.object(knowledge, '_key_in_other_scope', return_value=False):          # data written before the key rule (review dev6 R7)
            self.general('Shared rule here under the reused key', HERE, key='mirror-key')
        for form in (('--plan', 'P1', '--scope', 'project'), ('--plan', 'P1', '--scope', 'both'), ('--scope', 'both'), ('--scope', 'project')):
            with self.subTest(form=form):
                entries = self.retrieved(*form)
                say('r03b ' + ' '.join(form), {t: brief(e) for t, e in entries.items()})
                entry = entries.get('Project rule for elsewhere under a reused key')
                self.assertTrue(entry is None or entry['label'] != 'verified', entry)


# ---- other projects, 2.2 entries, permission ------------------------------------------------------------------------------------

class Controls(Base):
    def test_c05_another_projects_general_record_judged_in_its_own_project_and_withdrawn_only_by_it(self):
        second = self.second_project()
        theirs = self.general('Rule shared by project two', HERE, ledger=second, plan='Q1')
        wrong = self.general('Elsewhere rule shared by project two', THERE, ledger=second, plan='Q1')
        for form in (('--scope', 'general'), ('--plan', 'P1', '--scope', 'general'), ('--plan', 'P1', '--scope', 'both', '--revision', 'HEAD')):
            with self.subTest(form=form):
                entries = self.retrieved(*form)
                say('c05 ' + ' '.join(form), {t: brief(e) for t, e in entries.items()})
                self.assertEqual((entries['Rule shared by project two']['label'], entries['Rule shared by project two']['stale_reason']), ('verified', None))
                self.assertTrue(entries['Elsewhere rule shared by project two']['stale_reason'].startswith('not applicable now'))
        knowledge.withdraw(second, 'Q1', theirs['id'], reason='wrong', evidence={'sources': [{'type': 'event', 'id': self.event_of(second)}]})
        for form in (('--scope', 'general'), ('--plan', 'P1', '--scope', 'general')):
            with self.subTest(form=form, after='withdrawal'):
                self.assertNotIn('Rule shared by project two', self.retrieved(*form))
        self.assertIn('Elsewhere rule shared by project two', self.retrieved('--scope', 'general'))
        self.assertNotIn(wrong['id'], [])

    def test_c06_22_general_entries_keep_their_label_everywhere(self):
        second = self.second_project()
        context.add(second, 'Q1', kind='note', label='verified', text='2.2 shared note of project two', scope='general', conditions=['Python'],
                    source={'type': 'event', 'id': self.event_of(second)})
        context.add(self.ledger, 'P1', kind='note', label='observed', text='2.2 shared note of project one', scope='general', conditions=['Python'],
                    source={'type': 'event', 'id': self.ledger_event()})
        context.add(self.ledger, 'P1', kind='note', label='verified', text='Shared lesson index of project one', scope='general', conditions=['Python'],
                    source={'type': 'event', 'id': self.ledger_event()}, key='lesson-89abcdef')
        for form in (('--scope', 'general'), ('--scope', 'both'), ('--plan', 'P1', '--scope', 'general'), ('--plan', 'P1', '--scope', 'both')):
            with self.subTest(form=form):
                entries = self.retrieved(*form)
                say('c06 ' + ' '.join(form), {t: brief(e) for t, e in entries.items()})
                for text, label in (('2.2 shared note of project two', 'verified'), ('2.2 shared note of project one', 'observed'),
                                    ('Shared lesson index of project one', 'verified')):
                    self.assertEqual((entries[text]['label'], entries[text]['stale_reason']), (label, None), text)
        theirs = self.retrieved('--plan', 'Q1', '--scope', 'general', project=second.project)
        self.assertEqual(theirs['2.2 shared note of project one']['label'], 'observed')

    def test_c07_a_private_contradiction_of_another_root_is_not_told(self):
        g = self.general('Shared rule contradicted privately on P2', HERE)
        self.root_b('P2')
        self.project_record('SECRET-P2 working note contradicting the shared rule', plan='P2', visibility='root', contradicts=[g['id']])
        for form in (('--scope', 'general'), ('--plan', 'P1', '--scope', 'general'), ('--plan', 'P1', '--scope', 'both')):
            with self.subTest(form=form):
                result = self.cli('context', 'retrieve', *form)
                entries = {e['text']: e for e in result['entries']}
                say('c07 ' + ' '.join(form), brief(entries.get('Shared rule contradicted privately on P2')))
                self.assertNotIn('SECRET-P2', json.dumps(result))
                self.assertEqual(entries['Shared rule contradicted privately on P2']['label'], 'verified')
        mine = self.retrieved('--plan', 'P2', '--scope', 'general')
        say('c07 --plan P2', brief(mine.get('Shared rule contradicted privately on P2')))
        self.assertEqual(mine['Shared rule contradicted privately on P2']['label'], 'stale')

    def test_c08_an_older_revision_is_judged_on_its_files_for_general_records_too(self):
        first = self.git('rev-list', '--max-parents=0', 'HEAD')
        self.general('Shared rule for elsewhere at a revision', THERE)
        self.general('Shared rule for here at a revision', HERE)
        for form in (('--scope', 'general', '--revision', first), ('--plan', 'P1', '--scope', 'both', '--revision', first)):
            with self.subTest(form=form):
                entries = self.retrieved(*form)
                say('c08 ' + ' '.join(form), {t: brief(e) for t, e in entries.items()})
                self.assertEqual(entries['Shared rule for elsewhere at a revision']['label'], 'stale')
                self.assertEqual(entries['Shared rule for here at a revision']['label'], 'verified')

    def test_c09_only_the_plan_reader_fails(self):
        project = self.project_record('Project rule judged per root')
        self.general('Shared rule when the reader fails', HERE)
        gone = self.general('Shared rule withdrawn before the reader fails', HERE)
        self.cli('wiki', 'withdraw', gone['id'], '--plan', 'P1', '--reason', 'wrong', '--source', f'event:{self.ledger_event()}')
        context.add(self.ledger, 'P1', kind='note', label='observed', text='2.2 shared note when the reader fails', scope='general',
                    conditions=['Python'], source={'type': 'event', 'id': self.ledger_event()})
        real = knowledge.for_root
        def flaky(ledger, plan, **kw):
            if plan is None or not str(plan).startswith('TASK-'): raise RuntimeError('broken general reader')
            return real(ledger, plan, **kw)
        for plan in (None, 'P1'):
            raw = context.retrieve(self.ledger, plan=plan, scope='both', raw=True)['entries']
            with patch.object(knowledge, 'for_root', side_effect=flaky):
                entries = {e['text']: e for e in context.judged(self.ledger, raw, plan=plan)}
            say(f'c09 plan={plan}', {t: brief(e) for t, e in entries.items()})
            self.assertEqual((entries['Project rule judged per root']['label'], entries['Project rule judged per root']['stale_reason']), ('verified', None))
            self.assertEqual(entries['Shared rule when the reader fails']['label'], 'stale')
            self.assertNotIn('Shared rule withdrawn before the reader fails', entries)
            self.assertEqual(entries['2.2 shared note when the reader fails']['label'], 'observed')
        self.assertTrue(project['id'])

    def test_c10_resume_pack_never_judges_general_records(self):
        self.general('Shared rule outside the pack', HERE)
        self.project_record('Project rule inside the pack')
        calls = []
        real = knowledge.for_root
        def spy(ledger, plan, **kw):
            calls.append(plan); return real(ledger, plan, **kw)
        with patch.object(knowledge, 'for_root', side_effect=spy):
            pack = context.for_pack(self.ledger, 'P1')
        say('c10 pack', [(e['text'], e['label']) for e in pack], calls)
        self.assertNotIn('Shared rule outside the pack', [e['text'] for e in pack])
        self.assertNotIn(None, calls)
        self.assertTrue(all(str(c).startswith('TASK-') for c in calls))

    def test_c11_a_malformed_23_general_record_is_never_current_and_does_not_hide_the_others(self):
        context.add(self.ledger, 'P1', kind='note', label='verified', text='Malformed shared record', scope='general', conditions=['when retrying'],
                    source={'type': 'event', 'id': self.ledger_event()}, extra={'version': 2, 'visibility': 'project', 'sources': 5})
        self.general('Healthy shared rule beside a malformed one', HERE)
        for form in (('--scope', 'general'), ('--plan', 'P1', '--scope', 'both')):
            with self.subTest(form=form):
                entries = self.retrieved(*form)
                say('c11 ' + ' '.join(form), {t: brief(e) for t, e in entries.items()})
                self.assertEqual(entries['Malformed shared record']['label'], 'stale')
                self.assertEqual(entries['Healthy shared rule beside a malformed one']['label'], 'verified')

    def test_c12_plan_and_no_plan_agree_for_general_records_without_root_effects(self):
        for name, condition in (('Agree elsewhere', THERE), ('Agree here', HERE), ('Agree model', {'type': 'env', 'key': 'model', 'value': 'm'})):
            self.general(name, condition)
        self.project_record('A P1 project rule')
        a = self.retrieved('--scope', 'general'); b = self.retrieved('--plan', 'P1', '--scope', 'both'); c = self.retrieved('--plan', 'P1', '--scope', 'general')
        for name in ('Agree elsewhere', 'Agree here', 'Agree model'):
            self.assertEqual(brief(a[name]), brief(b[name])); self.assertEqual(brief(b[name]), brief(c[name]))
        say('c12', {n: brief(a[n]) for n in ('Agree elsewhere', 'Agree here', 'Agree model')})


if __name__ == '__main__':
    import unittest
    unittest.main()


# ---- delta review of 9a2b453 (the reviewer, same session): corrections, updates by another root, reverts stay judged ----------

class Delta(Base):
    def state_version(self, ident):
        return next(r['state_version'] for r in knowledge.records(self.ledger, history=True) if r['id'] == ident)

    def forms(self):
        return (('--scope', 'general'), ('--scope', 'both'), ('--plan', 'P1', '--scope', 'general'), ('--plan', 'P1', '--scope', 'both'))

    def test_d01_a_correction_written_after_a_withdrawal_is_live(self):
        v1 = self.general('Shared rule, wrong first wording', HERE, key='corrected-subject')
        self.cli('wiki', 'withdraw', v1['id'], '--plan', 'P1', '--reason', 'wrong', '--source', f'event:{self.ledger_event()}')
        v2 = self.general('Shared rule, corrected wording', HERE, key='corrected-subject', base=self.state_version(v1['id']))
        say('d01', v1, v2, self.history()[v1['id']]['status'])
        for form in self.forms():
            with self.subTest(form=form):
                entries = self.retrieved(*form)
                say('d01 ' + ' '.join(form), {t: brief(e) for t, e in entries.items() if 'Shared rule' in t})
                self.assertNotIn('Shared rule, wrong first wording', entries)
                self.assertEqual((entries['Shared rule, corrected wording']['label'], entries['Shared rule, corrected wording']['stale_reason']),
                                 ('verified', None))

    def test_d02_a_correction_written_after_an_archive_is_live(self):
        v1 = self.general('Archived shared rule', HERE, key='archived-subject')
        knowledge.archive(self.ledger, 'P1', v1['id'], reason='old')
        v2 = self.general('Shared rule written after the archive', HERE, key='archived-subject', base=self.state_version(v1['id']))
        for form in self.forms():
            with self.subTest(form=form):
                entries = self.retrieved(*form)
                say('d02 ' + ' '.join(form), {t: brief(e) for t, e in entries.items() if 'rule' in t})
                self.assertNotIn('Archived shared rule', entries)
                self.assertEqual(entries['Shared rule written after the archive']['label'], 'verified')
        self.assertTrue(v2['id'])

    def test_d03_newest_version_written_by_another_root_is_judged_not_marked_not_judged(self):
        v1 = self.general('Shared rule from P1', HERE, key='moved-subject')
        self.root_b('P2')
        v2 = self.general('Shared rule updated on P2', HERE, plan='P2', key='moved-subject', base=v1['version'])
        bad = self.general('Elsewhere rule from P1', HERE, key='moved-elsewhere')
        self.general('Elsewhere rule updated on P2', THERE, plan='P2', key='moved-elsewhere', base=bad['version'])
        for form in self.forms() + (('--plan', 'P2', '--scope', 'both'),):
            with self.subTest(form=form):
                entries = self.retrieved(*form)
                say('d03 ' + ' '.join(form), {t: brief(e) for t, e in entries.items() if 'rule' in t})
                self.assertNotIn('Shared rule from P1', entries); self.assertNotIn('Elsewhere rule from P1', entries)
                self.assertEqual((entries['Shared rule updated on P2']['label'], entries['Shared rule updated on P2']['stale_reason']), ('verified', None))
                self.assertTrue(entries['Elsewhere rule updated on P2']['stale_reason'].startswith('not applicable now'))
        self.assertTrue(v2['id'])

    def test_d04_project_subject_updated_by_another_root_keeps_its_judgement(self):
        v1 = self.project_record('Project rule from P1', key='project-subject')
        self.root_b('P2')
        self.project_record('Project rule updated on P2', plan='P2', key='project-subject', base=v1['version'])
        for form in (('--scope', 'project'), ('--scope', 'both'), ('--plan', 'P2', '--scope', 'both')):
            with self.subTest(form=form):
                entries = self.retrieved(*form)
                say('d04 ' + ' '.join(form), {t: brief(e) for t, e in entries.items() if 'Project rule' in t})
                new = entries['Project rule updated on P2']
                self.assertEqual((new['label'], new['stale_reason']), ('verified', None))
                if 'Project rule from P1' in entries:
                    self.assertNotEqual(entries['Project rule from P1']['label'], 'verified')
                    self.assertNotIn('not judged', entries['Project rule from P1']['stale_reason'] or '')

    def test_d05_a_revert_to_an_older_identical_version_is_judged(self):
        event = self.ledger_event()
        def write(text, condition, base):
            return knowledge.record(self.ledger, 'P1', kind='decision', text=text, scope='general', conditions=[condition], key='revert-subject',
                                    base=base, evidence={'status': 'verified', 'property': 'the retry check passed', 'sources': [{'type': 'event', 'id': event}]})
        v1 = write('Reverted shared rule', HERE, '')
        v2 = write('Replaced wording of the shared rule', THERE, v1['version'])
        v3 = write('Reverted shared rule', HERE, v2['version'])
        say('d05', v1['version'] == v3['version'], v3)
        for form in self.forms():
            with self.subTest(form=form):
                entries = self.retrieved(*form)
                say('d05 ' + ' '.join(form), {t: brief(e) for t, e in entries.items() if 'shared rule' in t})
                self.assertNotIn('Replaced wording of the shared rule', entries)
                self.assertEqual((entries['Reverted shared rule']['label'], entries['Reverted shared rule']['stale_reason']), ('verified', None))
