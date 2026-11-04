"""Kept from the delta review of dev7 (D:/OneCrewRuns/v23/review-dev7/review-wi.md, "Delta review of 1c0c0f4", written by the reviewer); DA1 follows the author's decision on R7-15, DC5 pins the known limit R7-17. Delta review probes of 7633bb6..1c0c0f4 (the answers to review-wi.md R7-01..R7-14). Same convention as the first round: each test asserts
the EXPECTED behaviour (a failure is a finding, a pass held); `measure` tests only record. Facts go to PROBE_LOG (default
D:/OneCrewRuns/v23/review-dev7/logs/delta-probes.jsonl). The knowledge probes go through the real seal: for_native or a sealed package
blob, a retained receipt, previous_requests, then a package."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import Ledger, LedgerError, canonical
from onecrew.v2 import context, install, knowledge, namespaces, wiki
from tests import test_v23_wiki_init as wi
from tests.test_v23_review_dev4 import Base as KBase, HERE

LOG = Path(os.environ.get('PROBE_LOG') or Path(tempfile.gettempdir()) / 'onecrew-review-dev7-delta-probes.jsonl')     # kept as a test: the run's temp folder
CHECKOUT = Path(__file__).resolve().parents[1]
HEAD = subprocess.run(['git', '-C', str(CHECKOUT), 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True).stdout.strip()


def say(probe, **facts):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({'commit': HEAD, 'probe': probe, **facts}, ensure_ascii=False, default=str)
    with LOG.open('a', encoding='utf-8') as stream: stream.write(line + '\n')
    print('PROBE', line[:1800])


def md_files(folder):
    folder = Path(folder)
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob('*.md')) if folder.is_dir() else []


def junction(link, target):
    done = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)], capture_output=True)
    if done.returncode != 0: raise unittest.SkipTest('mklink /J failed')


def old_page(commit, key, language='en'):
    """The skeleton page an init of `commit` wrote (its messages.py, read from git)."""
    source = subprocess.run(['git', '-C', str(CHECKOUT), 'show', f'{commit}:onecrew/v2/messages.py'], capture_output=True, check=True).stdout.decode('utf-8')
    names = {}
    exec(compile(source, f'messages@{commit}', 'exec'), names)
    return (install.SKELETON_MARK + '\n' + names['TEXT'][key][language].format()).encode('utf-8')


# ---- DA: init, the skeleton test and the path judgement ------------------------------------------------------------------------------

class DA_Skeleton(wi.Base):
    def names(self):
        return sorted(p.name for p in (self.repo / 'docs' / 'wiki').iterdir())

    def test_da1_a_page_an_unreleased_earlier_build_wrote_is_the_users(self):
        """Changed (the author's decision on R7-15): only the skeleton of a released version is init's. 7633bb6 was a trial build, never released
        (2.3.0.dev7 is the first that writes a skeleton), so its README is a page of the user: the wiki is used as it is, nothing is added."""
        folder = self.repo / 'docs' / 'wiki'; folder.mkdir(parents=True)
        data = old_page('7633bb6', 'wiki.page_readme')                        # the README the 7633bb6 init wrote (its example had must: true)
        (folder / 'README.md').write_bytes(data)                               # ... and the init stopped after it
        code, out = self.init()
        say('DA1-older-skeleton', exit=code, names=self.names(), old_readme_has_must=b'"must": true' in data, tail=out[-200:])
        self.assertIn(code, (0, 1), out)
        self.assertEqual(self.names(), ['README.md'])
        self.assertEqual((folder / 'README.md').read_bytes(), data)

    def test_da2_a_page_cut_short_by_an_interrupted_write(self):
        folder = self.repo / 'docs' / 'wiki'; folder.mkdir(parents=True)
        whole = install.skeleton_text('README.md', 'en').encode('utf-8')
        (folder / 'README.md').write_bytes(whole[:len(whole) // 2])
        code, out = self.init()
        say('DA2-truncated-page', exit=code, names=self.names(), tail=out[-200:])
        self.assertEqual(self.names(), sorted(wi.NAMES))

    def test_da2b_an_empty_page_left_by_an_interrupted_write(self):
        folder = self.repo / 'docs' / 'wiki'; folder.mkdir(parents=True)
        (folder / 'README.md').write_bytes(b'')
        code, out = self.init()
        say('DA2b-empty-page', exit=code, names=self.names(), tail=out[-200:])
        self.assertEqual(self.names(), sorted(wi.NAMES))

    def test_da3_crlf_converted_skeleton_pages_are_inits(self):
        folder = self.repo / 'docs' / 'wiki'; folder.mkdir(parents=True)
        (folder / 'README.md').write_bytes(install.skeleton_text('README.md', 'vi').encode('utf-8').replace(b'\n', b'\r\n'))
        code, out = self.init()
        say('DA3-crlf-skeleton', exit=code, names=self.names())
        self.assertEqual((code, self.names()), (0, sorted(wi.NAMES)))


class DA_Paths(wi.Base):
    def test_da6_a_rooted_folder_among_several_is_read_by_the_reader_and_refused_by_init(self):
        shared = self.base / 'shared wiki'; shared.mkdir(); (shared / 'team.md').write_text('## Team rule\nKeep a.txt short.\n', encoding='utf-8')
        (self.repo / 'docs' / 'wiki').mkdir(parents=True); (self.repo / 'docs' / 'wiki' / 'own.md').write_text('## Own\nText.\n', encoding='utf-8')
        raw = '/' + shared.relative_to(shared.anchor).as_posix()
        self.config({'wiki': {'paths': ['docs/wiki', raw]}})
        read = [p['path'] for p in knowledge.pages_report(Ledger(self.repo, self.state))['pages']]
        code, out = self.init()
        say('DA6-rooted-among-several', reader_reads=read, exit=code, hooks=(self.repo / '.claude').exists(), tail=out[-250:])
        self.assertEqual(code, 0, 'init refuses a configuration the reader reads (only reused folders, nothing to write)')

    def test_da7_a_real_folder_whose_name_looks_like_a_short_name(self):
        folder = self.repo / 'kb~1'; folder.mkdir(); (folder / 'page.md').write_text('## A rule\nKeep a.txt short.\n', encoding='utf-8')
        self.config({'wiki': {'paths': ['kb~1']}})
        read = [p['path'] for p in knowledge.pages_report(Ledger(self.repo, self.state))['pages']]
        code, out = self.init()
        say('DA7-tilde-name', reader_reads=read, exit=code, tail=out[-250:])
        self.assertEqual(code, 0, 'a name that is on disk as written is refused as "another spelling"')

    def test_da8_device_names(self):
        for raw in ('NUL', 'docs/CON', 'docs/wiki/AUX'):
            with self.subTest(raw=raw):
                shutil.rmtree(self.repo / '.onecrew', ignore_errors=True); shutil.rmtree(self.repo / '.claude', ignore_errors=True)
                shutil.rmtree(self.repo / 'docs', ignore_errors=True); shutil.rmtree(self.state, ignore_errors=True)
                self.config({'wiki': {'paths': [raw]}})
                code, out = self.init()
                say('DA8-device-name', raw=raw, exit=code, tail=out[-250:], docs=md_files(self.repo / 'docs'))
                self.assertIn(code, (2, 3), out)                                  # refused or reported as a failed write, never "created"

    def test_da9_measure_the_window_between_the_last_check_and_the_writes(self):
        outside = self.base / 'elsewhere'; (outside / 'wiki').mkdir(parents=True)
        real, swapped = install._create_new_file, []
        def racing(path, text):
            if not swapped:                                                  # another process swaps the folder after init's last check
                shutil.rmtree(self.repo / 'docs'); junction(self.repo / 'docs', outside); swapped.append(True)
            return real(path, text)
        with patch.object(install, '_create_new_file', racing):
            code, out = self.init()
        say('DA9-residual-window', exit=code, written_outside=md_files(outside))
        if swapped: os.rmdir(self.repo / 'docs')

    def test_da10_a_linked_wiki_whose_pages_are_gone_is_refused_and_nothing_is_written(self):
        shared = self.base / 'shared wiki'; shared.mkdir(); (shared / 'team.md').write_text('## Team rule\nText.\n', encoding='utf-8')
        (self.repo / 'docs').mkdir(); junction(self.repo / 'docs' / 'wiki', shared)
        first, _ = self.init()
        (shared / 'team.md').unlink()
        again, out = self.init()
        say('DA10-linked-emptied', first_exit=first, second_exit=again, outside=md_files(shared), tail=out[-200:])
        os.rmdir(self.repo / 'docs' / 'wiki')
        self.assertEqual((first, md_files(shared)), (0, []))
        self.assertEqual(again, 2)

    def test_da11_a_linked_parent_whose_wiki_has_only_skeleton_pages_is_never_completed_through_the_link(self):
        shared = self.base / 'shared'; (shared / 'wiki').mkdir(parents=True)
        (shared / 'wiki' / 'README.md').write_bytes(install.skeleton_text('README.md', 'en').encode('utf-8'))
        junction(self.repo / 'docs', shared)
        code, out = self.init()
        say('DA11-linked-skeleton', exit=code, outside=md_files(shared), tail=out[-200:])
        os.rmdir(self.repo / 'docs')
        self.assertEqual(md_files(shared), ['wiki/README.md'])


# ---- DC: knowledge, through the real seal ---------------------------------------------------------------------------------------------

class DC_Knowledge(KBase):
    def setUp(self):
        super().setUp()
        self.second = self.second_project()

    def tag2(self):
        return knowledge.project_tags(self.ledger)[self.second.project_id]

    def retain(self, record, requests, attempt):
        receipt = self.store.blob(canonical({'kind': 'native-node-receipt', 'knowledge': record, 'knowledge_requests': requests}).encode('utf-8'))
        with self.ledger.transaction(write=True) as conn:
            root = namespaces.resolve(self.ledger, conn, 'P1')
            self.ledger._event(conn, root['id'], 'node.result_retained', {'attempt': attempt, 'node': 'C', 'candidate': {'receipt': receipt}})

    def sealed_v2(self, rows):
        """A package blob as 2.3.0.dev6 sealed it: version 2, omitted index rows without an event."""
        view = {'kind': 'knowledge-package', 'version': 2, 'entries': [], 'requested': [], 'requests_refused': [],
                'omitted': {'total': len(rows), 'by_reason': {'not_relevant': len(rows)}, 'index': rows, 'cursor': None, 'eof': True}}
        return {'package': self.store.blob(canonical(view).encode('utf-8'))}

    def continued(self, attempt):
        hints = knowledge.previous_requests(self.ledger, self.store, 'P1', attempt)
        pkg = knowledge.package(self.ledger, knowledge.consumer(self.ledger, 'P1'), cap_chars=12000, requested=hints)
        return hints, [(e['id'], e['title'][:40]) for e in pkg['requested']], [(r['id'], r['reason']) for r in pkg['requests_refused']]

    def our_version(self):
        return next(r for r in knowledge.records(self.ledger) if r['id'] == 'ctx-retry')['state_version']

    def test_dc1_a_version_3_seal_names_our_subject_exactly(self):
        self.page('notes.md', '## Keep a.txt short\nThe team keeps a.txt to one short line.\n')
        self.general('Shared wording of the retry rule', HERE, key='retry')
        view, record = knowledge.for_native(self.ledger, self.store, 'P1', self.item(goal='Keep a.txt short'), None)
        rows = {e['id']: ('entry', (e.get('origin') or {}).get('event')) for e in (view or {}).get('entries', [])}
        rows.update({r['id']: ('index', r.get('event')) for r in (view or {}).get('omitted', {}).get('index', [])})
        self.retain(record, ['ctx-retry'], 'ATT-dc1')
        self.general('Shared wording of the retry rule', HERE, ledger=self.second, plan='Q1', key='retry')   # project two: same key, same words
        self.general('Shared wording of the retry rule, revised', HERE, key='retry', base=self.our_version())
        hints, got, refused = self.continued('ATT-dc1')
        say('DC1-v3-real-seal', package_version=(view or {}).get('version'), rows=rows, hints=hints, requested=got, refused=refused)
        self.assertEqual([i for i, _ in got], ['ctx-retry'])
        self.assertIn('revise', got[0][1])

    def test_dc2_a_dev6_seal_that_listed_both_subjects_never_turns_ours_into_theirs(self):
        self.general('Shared wording of the retry rule', HERE, key='retry')
        self.general('Shared wording of the retry rule', HERE, ledger=self.second, plan='Q1', key='retry')
        title = 'Shared wording of the retry rule'
        record = self.sealed_v2([{'id': 'ctx-retry', 'title': title, 'use': 'fact', 'reason': 'not_relevant'},
                                 {'id': 'ctx-retry@' + self.tag2(), 'title': title, 'use': 'fact', 'reason': 'not_relevant'}])
        self.retain(record, ['ctx-retry'], 'ATT-dc2')                          # dev6 named project two's subject with its tag: the plain id was ours
        self.general('Shared wording of the retry rule, revised', HERE, key='retry', base=self.our_version())
        hints, got, refused = self.continued('ATT-dc2')
        say('DC2-dev6-seal-both-listed', hints=hints, requested=got, refused=refused, tag2=self.tag2())
        self.assertNotIn('ctx-retry@' + self.tag2(), [i for i, _ in got])

    def test_dc3_measure_a_dev6_seal_of_our_subject_whose_title_changed(self):
        self.general('Rule of project one', HERE, key='retry')
        self.retain(self.sealed_v2([{'id': 'ctx-retry', 'title': 'Rule of project one', 'use': 'fact', 'reason': 'not_relevant'}]), ['ctx-retry'], 'ATT-dc3')
        self.general('Rule of project one, revised', HERE, key='retry', base=self.our_version())
        hints, got, refused = self.continued('ATT-dc3')
        say('DC3-dev6-seal-own-title-changed', hints=hints, requested=got, refused=refused)

    def test_dc4_a_dev5_seal_of_the_other_projects_subject_withdrawn_since(self):
        self.general('Rule of project two', HERE, ledger=self.second, plan='Q1', key='retry')
        self.general('Rule of project one', HERE, key='retry')
        self.retain(self.sealed_v2([{'id': 'ctx-retry', 'title': 'Rule of project two', 'use': 'fact', 'reason': 'not_relevant'}]), ['ctx-retry'], 'ATT-dc4')
        knowledge.withdraw(self.second, 'Q1', 'ctx-retry', reason='replaced', evidence={'sources': [{'type': 'event', 'id': self.event_of(self.second)}]})
        hints, got, refused = self.continued('ATT-dc4')
        say('DC4-dev5-seal-withdrawn-other', hints=hints, requested=got, refused=refused)
        self.assertEqual(got, [])

    def test_dc4b_a_dev6_seal_of_a_lesson_keyed_22_note_of_the_other_project(self):
        for ledger, plan, text in ((self.ledger, 'P1', 'Note of project one'), (self.second, 'Q1', 'Note of project two')):
            context.add(ledger, plan, kind='note', label='hypothesis', text=text, source={'type': 'event', 'id': self.event_of(ledger)},
                        scope='general', conditions=['on this machine'], key='lesson-shared')
        self.retain(self.sealed_v2([{'id': 'lesson-shared', 'title': 'Note of project two', 'use': 'lead', 'reason': 'not_relevant'}]),
                    ['lesson-shared'], 'ATT-dc4b')                             # 4bb41b3 named the colliding pair by the newest: project two's
        hints, got, refused = self.continued('ATT-dc4b')
        say('DC4b-dev6-seal-lesson-key', hints=hints, requested=got, refused=refused)
        self.assertEqual([t for _, t in got], ['Note of project two'])

    def test_dc5_our_22_note_under_another_projects_general_lesson_key(self):
        logical = 'cd' * 16
        with self.second.transaction(write=True) as conn:
            root = namespaces.resolve(self.second, conn, 'Q1')
            self.second._event(conn, root['id'], 'learning.lesson', {'version': 1, 'lesson': logical, 'scope': 'general', 'status': 'proposed',
                                                                     'text': 'General lesson of project two', 'conditions': ['on this machine'], 'location': None})
            event = conn.execute('SELECT MAX(seq) FROM events').fetchone()[0]
        context.add(self.second, 'Q1', kind='note', label='hypothesis', text='General lesson of project two', source={'type': 'event', 'id': event},
                    scope='general', conditions=['on this machine'], key='lesson-' + logical)          # what lessons._index writes for a general candidate
        context.add(self.ledger, 'P1', kind='note', label='hypothesis', text='Note of project one', scope='general', conditions=['on this machine'],
                    source={'type': 'event', 'id': self.event_of(self.ledger)}, key='lesson-' + logical)   # a 2.2 note under that key
        one = {r['text']: (r['id'], r['kind']) for r in knowledge.records(self.ledger, history=True)}
        two = {r['text']: (r['id'], r['kind']) for r in knowledge.records(self.second, history=True)}
        say('DC5-own-note-vs-general-lesson', reader_one=one, reader_two=two)
        # Known limit R7-17 (HUONG-DAN-WIKI §7, limits-final.md): our 2.2 note under the exact 32-hex key of another project's general lesson takes
        # that lesson's id for us. Pinned so that a change is seen; reader two keeps both apart (its lesson, our note as lesson-<key>@<tag>).
        self.assertEqual(sorted(one), ['Note of project one'])
        self.assertEqual(sorted(two), ['General lesson of project two', 'Note of project one'])
        self.assertNotEqual(two['General lesson of project two'][0], two['Note of project one'][0])

    def test_dc6_a_section_past_the_budget_with_an_unreadable_page_among_the_first(self):
        (self.wiki_dir / 'p000.md').write_bytes(b'\xff\xfe\x00broken')
        for i in range(1, 5): (self.wiki_dir / f'p{i:03d}.md').write_text(f'## Section {i}\nText {i}.\n', encoding='utf-8')
        self.git('add', '.'); self.git('commit', '-q', '-m', 'pages')
        evidence = {'sources': [{'type': 'event', 'id': self.event_of(self.ledger)}]}
        outcome = {}
        with patch.object(wiki, 'MAX_PAGES', 2):
            for target in ('p003-section-3', 'p004-section-4', 'p004-no-such'):
                try:
                    knowledge.withdraw(self.ledger, 'P1', target, reason='shown wrong', evidence=evidence); outcome[target] = 'recorded'
                except LedgerError as error:
                    outcome[target] = 'refused'
        say('DC6-section-scan-skip', outcome=outcome)
        self.assertEqual(outcome, {'p003-section-3': 'recorded', 'p004-section-4': 'recorded', 'p004-no-such': 'refused'})

    def test_dc7_measure_the_event_in_index_rows_and_a_small_cap(self):
        for i in range(25): self.general(f'Shared rule number {i} about retries', HERE, key=f'rule{i}')
        cons = knowledge.consumer(self.ledger, 'P1')
        sizes = {}
        for cap in (16000, 4000, 1500, 900):
            try:
                pkg = knowledge.package(self.ledger, cons, cap_chars=cap)
                rows = pkg['omitted']['index']
                stripped = dict(pkg, omitted=dict(pkg['omitted'], index=[{k: v for k, v in r.items() if k != 'event'} for r in rows]))
                sizes[cap] = {'chars': len(canonical(knowledge.prompt_view(pkg))), 'within_cap': len(canonical(pkg)) <= cap,
                              'index_rows': len(rows), 'event_chars': len(canonical(pkg)) - len(canonical(stripped))}
            except LedgerError as error:
                sizes[cap] = f'{type(error).__name__}: {str(error)[:100]}'
        say('DC7-index-event-size', sizes=sizes)
        self.assertTrue(all(v['within_cap'] for v in sizes.values() if isinstance(v, dict)))


if __name__ == '__main__':
    unittest.main()
