"""Kept from the independent review of dev7 (D:/OneCrewRuns/v23/review-dev7/review-wi.md, written by the reviewer on 7633bb6); three probes follow the reviewed design (ask: the hints a sealed package carries; G1: the language the package steps run with). Independent review probes of dededc5..7633bb6 (2.3 WI-01..05 `onecrew init` wiki, KN-1..KN-4, package steps V15/V16).

Each test asserts the EXPECTED behaviour (HOP-DONG-2.3 section 10, HUONG-DAN-WIKI section 0): a failing test is a finding, a passing
test is a property that held. Tests marked `measure` only record numbers. Facts are appended as JSON lines to PROBE_LOG (default: the temp folder) with the commit they ran on. Probes of the init wiki skip on a commit without it.
"""
import contextlib
import ctypes
import inspect
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import Ledger, LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import context, install, knowledge, namespaces, wiki
from tests import test_v23_wiki_init as wi
from tests.test_v23_review_dev4 import Base as KBase, HERE

LOG = Path(os.environ.get('PROBE_LOG') or Path(tempfile.gettempdir()) / 'onecrew-review-dev7-probes.jsonl')     # kept as a test: the run's temp folder
CHECKOUT = Path(__file__).resolve().parents[1]
HEAD = subprocess.run(['git', '-C', str(CHECKOUT), 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True).stdout.strip()
HAS_WIKI_INIT = hasattr(install, 'wiki_plan')
TITLED_REQUESTS = 'hint' in inspect.getsource(knowledge._build)        # 7633bb6: a request may carry the title its sealed package showed


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


def short_name(path):
    buffer = ctypes.create_unicode_buffer(1024)
    count = ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, 1024)
    return Path(buffer.value).name if count else Path(path).name


# ---- A: where init writes the wiki -------------------------------------------------------------------------------------------------

@unittest.skipUnless(HAS_WIKI_INIT, 'init has no wiki at this commit')
class A_InitPaths(wi.Base):
    def control_case(self, raw, control):
        self.config({'wiki': {'paths': [raw]}})
        before = md_files(self.repo / control)
        code, out = self.init()
        added = sorted(set(md_files(self.repo / control)) - set(before))
        say('A1-control-folder', raw=raw, exit=code, added_in_control_folder=added, tail=out[-300:])
        return code, added

    def test_a1_git_with_a_trailing_dot_is_a_control_folder(self):
        self.assertEqual(self.control_case('.git./wiki', '.git'), (2, []))

    def test_a1_git_itself_with_a_trailing_dot(self):
        self.assertEqual(self.control_case('.git.', '.git'), (2, []))

    def test_a1_onecrew_with_a_trailing_dot(self):
        self.assertEqual(self.control_case('.onecrew./wiki', '.onecrew'), (2, []))

    def test_a1_claude_with_a_trailing_dot(self):
        self.assertEqual(self.control_case('.claude./wiki', '.claude'), (2, []))

    def test_a1_git_with_a_trailing_space(self):
        self.assertEqual(self.control_case('.git ', '.git'), (2, []))

    def test_a1_git_named_by_its_index_allocation_stream(self):
        self.assertEqual(self.control_case('.git::$INDEX_ALLOCATION/wiki', '.git'), (2, []))

    def test_a1_control_the_plain_control_names_are_refused(self):
        for raw in ('.git/wiki', '.GIT/wiki', '.onecrew/wiki', '.claude/wiki', 'docs/.claude/wiki', '.env.d/wiki', '.ssh/wiki'):
            with self.subTest(raw=raw):
                self.config({'wiki': {'paths': [raw]}})
                code, out = self.init()
                say('A1-control-plain', raw=raw, exit=code)
                self.assertEqual(code, 2, out)
                self.assertFalse((self.state / 'ledger.sqlite3').exists())

    def test_a2_the_8dot3_name_of_git_is_a_control_folder(self):
        root = os.environ.get('PROBE_C_ROOT')
        if not root: self.skipTest('PROBE_C_ROOT (a folder on a volume that makes 8.3 names) not set')
        base = Path(tempfile.mkdtemp(prefix='r7 short ', dir=root)); self.addCleanup(shutil.rmtree, base, True)
        repo = base / 'proj'; repo.mkdir()
        g = lambda *a: subprocess.run(['git', '-C', str(repo), *a], check=True, capture_output=True)
        g('init', '-q'); g('config', 'user.email', 'r7@localhost'); g('config', 'user.name', 'r7')
        (repo / 'a.txt').write_text('base\n', encoding='utf-8'); g('add', '.'); g('commit', '-qm', 'base')
        short = short_name(repo / '.git')
        if short.casefold() == '.git': self.skipTest('the volume made no 8.3 name for .git')
        (repo / '.onecrew').mkdir(); (repo / '.onecrew' / 'config.json').write_text(json.dumps({'wiki': {'paths': [short + '/wiki']}}), encoding='utf-8')
        with patch.dict(os.environ, {'LOCALAPPDATA': str(base / 'lad'), 'APPDATA': str(base / 'ad')}):
            code, out = wi.run(install.init, project=repo, state_root=base / 'state', yes=True, exe=self.exe, claude=wi.LOGGED_IN)
        added = md_files(repo / '.git')
        say('A2-8dot3', short=short, exit=code, added_in_git=added, tail=out[-300:])
        self.assertEqual((code, added), (2, []))

    def test_a3_a_drive_rooted_folder_is_the_folder_the_reader_reads(self):
        far = self.base / 'far wiki'                                    # not there; on the drive of the repository
        raw = '/' + far.relative_to(far.anchor).as_posix()
        self.config({'wiki': {'paths': [raw]}})
        code, out = self.init()
        inside = self.repo.joinpath(*far.relative_to(far.anchor).parts)
        report = knowledge.pages_report(Ledger(self.repo, self.state))
        say('A3-drive-rooted', raw=raw, exit=code, created_in_repo=md_files(inside), reader_folders=report['folders'],
            reader_pages=[p['path'] for p in report['pages']], reader_problems=report['problems'][:3], init_tail=out[-400:])
        self.assertFalse(code in (0, 1) and md_files(inside) and not report['pages'],
                         'init created a skeleton the reader never reads: ' + out[-300:])

    def test_a4_a_junction_made_while_init_waits_for_the_answer_is_not_written_through(self):
        outside = self.base / 'elsewhere'; outside.mkdir()
        made = []
        def ask(_):
            junction(self.repo / 'docs', outside); made.append(True)
            return 'y'
        code, out = self.init(yes=False, ask=ask)
        written = md_files(outside)
        say('A4-toctou-junction', exit=code, written_outside=written, tail=out[-300:])
        if made: os.rmdir(self.repo / 'docs')
        self.assertEqual(written, [])

    def test_a5_a_skeleton_page_the_user_deleted_stays_deleted_once_the_wiki_has_their_entries(self):
        self.init()
        folder = self.repo / 'docs' / 'wiki'
        page = folder / 'project.md'
        page.write_text(page.read_text(encoding='utf-8') + '\n## Our rule\nKeep a.txt short.\n', encoding='utf-8')
        (folder / 'README.md').unlink(); (folder / 'lessons.md').unlink()
        code, out = self.init()
        names = sorted(p.name for p in folder.iterdir())
        say('A5-deleted-page-comes-back', exit=code, names=names, tail=out[-300:])
        self.assertEqual(names, ['project.md'])

    def test_a6_nothing_is_written_before_the_answer_and_no_writes_nothing(self):
        lad = Path(os.environ['LOCALAPPDATA'])
        snapshot = lambda: (wi.tree(self.repo), wi.tree(self.state), wi.tree(lad), self.state.exists(), lad.exists())
        before, seen = snapshot(), []
        def ask(_):
            seen.append(snapshot()); return 'n'
        code, out = self.init(yes=False, ask=ask)
        after = snapshot()
        say('A6-before-answer', exit=code, unchanged_at_prompt=seen == [before], unchanged_after=after == before)
        self.assertEqual((code, seen == [before], after == before), (2, True, True))

    def test_a7_configurations_init_cannot_use_are_refused_with_nothing_written(self):
        cases = [('a folder named config.json', None), ('utf-16', None), ('{"wiki": null}', {'wiki': None}),
                 ('blank path', {'wiki': {'paths': ['   ']}}), ('a number', {'wiki': {'paths': ['docs/wiki', 3]}}),
                 ('drive relative', {'wiki': {'paths': ['C:kb']}}), ('dot dot', {'wiki': {'paths': ['docs/../../kb']}})]
        for name, value in cases:
            with self.subTest(case=name):
                shutil.rmtree(self.repo / '.onecrew', ignore_errors=True)
                config = self.repo / '.onecrew' / 'config.json'
                if name == 'a folder named config.json': config.mkdir(parents=True); data = None
                elif name == 'utf-16':
                    config.parent.mkdir(parents=True); config.write_bytes(json.dumps({'wiki': {'paths': ['kb']}}).encode('utf-16')); data = config.read_bytes()
                else: data = self.config(value).read_bytes()
                code, out = self.init()
                say('A7-config', case=name, exit=code)
                self.assertEqual(code, 2, out)
                self.assertFalse((self.state / 'ledger.sqlite3').exists()); self.assertFalse((self.repo / '.claude').exists())
                self.assertFalse((self.repo / 'docs').exists()); self.assertFalse((self.repo / 'kb').exists())
                if data is not None: self.assertEqual(config.read_bytes(), data)

    def test_a8_a_dangling_link_where_a_skeleton_page_goes_is_never_written_through(self):
        folder = self.repo / 'docs' / 'wiki'; folder.mkdir(parents=True)
        (folder / 'README.md').write_text(install.SKELETON_MARK + '\n# part of an interrupted init\n', encoding='utf-8')
        target = self.base / 'outside' / 'project.md'; target.parent.mkdir()
        try:
            os.symlink(target, folder / 'project.md')
        except OSError:
            self.skipTest('no symlink privilege')
        code, out = self.init()
        say('A8-dangling-link', exit=code, outside=md_files(target.parent), names=sorted(p.name for p in folder.iterdir()))
        self.assertFalse(target.exists())

    def test_a9_a_junction_inside_the_wiki_folder_makes_it_a_wiki_of_the_user(self):
        outside = self.base / 'outside'; outside.mkdir(); (outside / 'x.md').write_text('# x\n', encoding='utf-8')
        folder = self.repo / 'docs' / 'wiki'; folder.mkdir(parents=True)
        junction(folder / 'linked', outside)
        before = wi.tree(outside)
        code, out = self.init()
        names = sorted(p.name for p in folder.iterdir())
        say('A9-junction-inside', exit=code, names=names, outside_unchanged=wi.tree(outside) == before)
        os.rmdir(folder / 'linked')
        self.assertEqual((code, wi.tree(outside) == before), (0, True))


@unittest.skipUnless(HAS_WIKI_INIT, 'init has no wiki at this commit')
class A10_LinkedWikiOnUpgrade(wi.Base):
    def test_a10_a_project_whose_wiki_is_a_junction_still_gets_its_hooks_repointed(self):
        shared = self.base / 'shared wiki'; shared.mkdir(); (shared / 'team.md').write_text('## Team rule\nKeep a.txt short.\n', encoding='utf-8')
        old_exe = self.base / 'old venv' / 'onecrew.exe'; old_exe.parent.mkdir(); old_exe.write_text('old')
        code0, _ = self.init(exe=old_exe)                                # as the previous install left it ...
        shutil.rmtree(self.repo / 'docs')                                # ... a 2.2 init writes no wiki
        (self.repo / 'docs').mkdir(); junction(self.repo / 'docs' / 'wiki', shared)
        read_before = [p['path'] for p in knowledge.pages_report(Ledger(self.repo, self.state))['pages']]
        code, out = self.init()                                          # the new install: hooks must point to self.exe now
        settings = json.loads((self.repo / '.claude' / 'settings.local.json').read_text(encoding='utf-8'))
        commands = sorted({h.get('command') for entries in settings['hooks'].values() for e in entries for h in e.get('hooks', [])})
        say('A10-linked-wiki-upgrade', first_exit=code0, reader_reads=read_before, exit=code, hook_commands=commands, tail=out[-300:])
        os.rmdir(self.repo / 'docs' / 'wiki')
        self.assertEqual(commands, [str(self.exe.resolve())], 'init refused the whole upgrade over a wiki it would not have written into')


class A3b_ReaderDriveRooted(wi.Base):                                     # the reader only: runs on every commit
    def test_a3b_the_reader_on_an_existing_drive_rooted_folder(self):
        far = self.base / 'far wiki'; far.mkdir(); (far / 'page.md').write_text('## A rule\nKeep a.txt short.\n', encoding='utf-8')
        raw = '/' + far.relative_to(far.anchor).as_posix()
        self.config({'wiki': {'paths': [raw]}})
        ledger = Ledger(self.repo, self.state)
        try:
            outcome = ('ok', [p['path'] for p in knowledge.pages_report(ledger)['pages']])
        except Exception as error:                                       # noqa: BLE001 - the probe records what escapes
            outcome = ('raised', f'{type(error).__name__}: {str(error)[:200]}')
        say('A3b-reader-drive-rooted', raw=raw, outcome=outcome)
        self.assertEqual(outcome[0], 'ok', outcome)


# ---- B: the empty skeleton yields no knowledge in any reader path ----------------------------------------------------------------

@unittest.skipUnless(HAS_WIKI_INIT, 'init has no wiki at this commit')
class B_SkeletonYieldsNothing(wi.Base):
    def judge(self, label):
        code, out = self.init()
        ledger = Ledger(self.repo, self.state)
        declared = knowledge.declares_mandatory(ledger)
        hits = {n: bool(wiki.MUST_BYTES.search(p.read_bytes())) for n in wi.NAMES for p in [self.repo / 'docs' / 'wiki' / n] if p.is_file()}
        store = Snapshots(ledger.state_root)
        with patch.object(knowledge, 'consumer', side_effect=RuntimeError('a fault of the knowledge layer')):
            try:
                outcome = ('ran on its inputs', knowledge.for_native(ledger, store, 'P1', {'id': 'C'}, None)[1].get('error'))
            except knowledge.KnowledgeIncomplete as error:
                outcome = ('held', str(error)[:200])
        say('B1-skeleton-must', case=label, init_exit=code, declares_mandatory=declared, must_pattern_in=hits, node=outcome)
        return declared, outcome

    def test_b1_the_english_skeleton_declares_no_mandatory_knowledge(self):
        declared, outcome = self.judge('en')
        self.assertEqual((declared, outcome[0]), (False, 'ran on its inputs'), outcome)

    def test_b1_the_vietnamese_skeleton_declares_no_mandatory_knowledge(self):
        os.environ['ONECREW_LANG'] = 'vi'
        declared, outcome = self.judge('vi')
        self.assertEqual((declared, outcome[0]), (False, 'ran on its inputs'), outcome)

    def test_b1_control_without_the_readme_page(self):
        self.init(); (self.repo / 'docs' / 'wiki' / 'README.md').unlink()
        ledger = Ledger(self.repo, self.state)
        declared = knowledge.declares_mandatory(ledger)
        say('B1-control-no-readme', declares_mandatory=declared)
        self.assertFalse(declared)


@unittest.skipUnless(HAS_WIKI_INIT, 'init has no wiki at this commit')
class B2_SkeletonPackage(KBase):
    def test_b2_the_skeleton_in_a_package_wiki_show_and_pages(self):
        for language in ('en', 'vi'):
            with self.subTest(language=language):
                for name in wi.NAMES: self.page(name, install.skeleton_text(name, language))
                pkg = knowledge.package(self.ledger, self.consumer(), cap_chars=12000)
                pages = knowledge.pages_report(self.ledger)
                say('B2-skeleton-package', language=language, entries=pkg['entries'], omitted=pkg['omitted']['total'], problems=pkg['problems'],
                    page_entries=sum(len(p['entries']) for p in pages['pages']), undelivered=pages['coverage'].get('undelivered'))
                self.assertEqual((pkg['entries'], pkg['omitted']['total'], pkg['problems']), ([], 0, []))
                self.assertEqual(sum(len(p['entries']) for p in pages['pages']), 0)
                self.assertIn('Không có mục tri thức nào', knowledge.render_text(pkg))


@unittest.skipUnless(HAS_WIKI_INIT, 'init has no wiki at this commit')
class B3_SkeletonHoldsANode(KBase):
    """No patch: a configured folder the reader cannot handle (a drive-rooted path, A3b, pre-existing) next to the skeleton."""
    def outcome(self, with_readme):
        for name in wi.NAMES: self.page(name, install.skeleton_text(name, 'en'))
        if not with_readme:
            (self.wiki_dir / 'README.md').unlink(); self.git('add', '-A'); self.git('commit', '-q', '-m', 'no readme')
        far = Path(self.temp.name) / 'shared wiki'; far.mkdir(); (far / 'x.md').write_text('## Shared note\nA note.\n', encoding='utf-8')
        raw = '/' + far.relative_to(far.anchor).as_posix()
        (self.root / '.onecrew').mkdir(exist_ok=True)
        (self.root / '.onecrew' / 'config.json').write_text(json.dumps({'wiki': {'paths': ['docs/wiki', raw]}}), encoding='utf-8')
        try:
            view, record = knowledge.for_native(self.ledger, self.store, 'P1', self.item(), None)
            return ('ran on its inputs', record.get('error'))
        except knowledge.KnowledgeIncomplete as error:
            return ('held', str(error)[:200])

    def test_b3_a_reader_fault_holds_the_node_only_because_of_the_skeleton(self):
        got = self.outcome(True)
        say('B3-skeleton-holds-node', with_readme=True, node=got)
        self.assertEqual(got[0], 'ran on its inputs', got)

    def test_b3_control_without_the_readme_page(self):
        got = self.outcome(False)
        say('B3-skeleton-holds-node', with_readme=False, node=got)
        self.assertEqual(got[0], 'ran on its inputs', got)


# ---- C: KN-1 requests across the upgrade -------------------------------------------------------------------------------------------

class C_KN1(KBase):
    def setUp(self):
        super().setUp()
        self.second = self.second_project()

    def tag2(self):
        return knowledge.project_tags(self.ledger)[self.second.project_id]

    def ask(self, ident, title, event=None):
        """The request as previous_requests hands it on (review dev7 answer): with no event, what a package sealed before version 3 says of an
        index row (its title); with an event, what a version-3 package says. 4bb41b3 passes plain ids (previous_requests had no hints)."""
        if not TITLED_REQUESTS: return ident
        return (ident, {'event': event, 'title': title, 'legacy': event is None})

    def requested(self, *items):
        pkg = knowledge.package(self.ledger, knowledge.consumer(self.ledger, 'P1'), cap_chars=12000, requested=items)
        return ([(e['id'], e['title'][:40]) for e in pkg['requested']], [(r['id'], r['reason']) for r in pkg['requests_refused']])

    def test_c1_the_subject_the_worker_saw_withdrawn_after_the_seal_is_never_replaced_by_ours(self):
        self.general('Rule of project two', HERE, ledger=self.second, plan='Q1', key='retry')
        self.general('Rule of project one', HERE, key='retry')
        before = self.requested(self.ask('ctx-retry', 'Rule of project two'))
        knowledge.withdraw(self.second, 'Q1', 'ctx-retry', reason='replaced in project two',
                           evidence={'sources': [{'type': 'event', 'id': self.event_of(self.second)}]})
        after = self.requested(self.ask('ctx-retry', 'Rule of project two'))
        say('C1-kn1-withdrawn-other', titled=TITLED_REQUESTS, before=before, after_withdrawal=after)
        self.assertNotIn('Rule of project one', json.dumps(after[0]))

    def test_c2_a_request_from_a_dev7_package_for_our_subject(self):
        self.general('Shared wording of the retry rule', HERE, key='retry')
        sealed = knowledge.package(self.ledger, knowledge.consumer(self.ledger, 'P1'), cap_chars=12000)
        shown = {e['id']: e['title'][:60] for e in sealed['entries']}
        shown.update({r['id']: r['title'] for r in sealed['omitted']['index']})
        title = shown.get('ctx-retry')
        events = {e['id']: (e.get('origin') or {}).get('event') for e in sealed['entries']}
        events.update({r['id']: r.get('event') for r in sealed['omitted']['index']})
        event = events.get('ctx-retry')                                          # a version-3 package names the subject by its event
        self.general('Shared wording of the retry rule', HERE, ledger=self.second, plan='Q1', key='retry')
        same_words = self.requested(self.ask('ctx-retry', title, event))
        ours = next(r for r in knowledge.records(self.ledger) if r['id'] == 'ctx-retry')
        self.general('Shared wording of the retry rule, revised', HERE, key='retry', base=ours['state_version'])
        moved = self.requested(self.ask('ctx-retry', title, event))
        say('C2-kn1-dev7-package', titled=TITLED_REQUESTS, sealed_ids=sorted(shown), title=title, same_words=same_words, after_our_update=moved,
            tag2=self.tag2())
        self.assertNotIn('ctx-retry@' + self.tag2(), json.dumps(moved[0]))       # never another project's subject for our own id
        self.assertEqual([i for i, _ in same_words[0]], ['ctx-retry'])         # an unambiguous id is not refused as ambiguous

    def test_c3_a_lesson_keyed_22_note_requested_from_a_package_sealed_before(self):
        for ledger, plan, text in ((self.ledger, 'P1', 'Note of project one'), (self.second, 'Q1', 'Note of project two')):
            context.add(ledger, plan, kind='note', label='hypothesis', text=text, source={'type': 'event', 'id': self.event_of(ledger)},
                        scope='general', conditions=['on this machine'], key='lesson-shared')
        sealed = knowledge.package(self.ledger, knowledge.consumer(self.ledger, 'P1'), cap_chars=12000)
        listed = [(e['id'], e['title'][:40]) for e in sealed['entries']] + [(r['id'], r['title'][:40]) for r in sealed['omitted']['index']]
        got = self.requested(self.ask('lesson-shared', 'Note of project two'))
        say('C3-kn1-lesson-key', titled=TITLED_REQUESTS, listed_now=listed, request_lesson_shared_seen_as_project_two=got)
        self.assertNotIn('Note of project one', json.dumps(got[0]))


# ---- D: KN-2 lesson keys -------------------------------------------------------------------------------------------------------------

class D_KN2(KBase):
    def test_d1_another_projects_22_note_under_our_lesson_key_never_replaces_our_lesson(self):
        second = self.second_project()
        other = second.project
        git = lambda *a: subprocess.run(['git', '-C', str(other), *a], check=True, capture_output=True, text=True).stdout.strip()
        commit, blob = git('rev-parse', 'HEAD'), git('rev-parse', 'HEAD:z.txt')
        logical = 'ab' * 16
        with second.transaction(write=True) as conn:
            root = namespaces.resolve(second, conn, 'Q1')
            second._event(conn, root['id'], 'learning.lesson', {
                'version': 1, 'lesson': logical, 'scope': 'project', 'status': 'verified', 'text': 'Lesson of project two',
                'location': {'path': 'z.txt', 'line': 1, 'revision': commit, 'revision_kind': 'commit', 'test': 't', 'symbol': None},
                'file_blob': blob, 'verified_repair': True})
            event = conn.execute('SELECT MAX(seq) FROM events').fetchone()[0]
        context.add(second, 'Q1', kind='note', label='verified', text='Lesson of project two', source={'type': 'event', 'id': event},
                    scope='project', key='lesson-' + logical)                    # what lessons._index writes
        context.add(self.ledger, 'P1', kind='note', label='hypothesis', text='Note of project one', scope='general', conditions=['on this machine'],
                    source={'type': 'event', 'id': self.event_of(self.ledger)}, key='lesson-' + logical)   # a 2.2 `context add` under that key
        two = {r['text']: (r['id'], r['kind']) for r in knowledge.records(second, history=True)}
        one = {r['text']: (r['id'], r['kind']) for r in knowledge.records(self.ledger, history=True)}
        say('D1-kn2-lesson-key', reader_two=two, reader_one=one)
        self.assertIn('Lesson of project two', two)
        self.assertNotEqual(two.get('Note of project one', (None,))[0], 'lesson-' + logical)
        self.assertEqual(one.get('Note of project one', (None, None))[1], 'note')


    def test_d2_context_retrieve_and_the_knowledge_reader_name_a_lesson_keyed_22_note_alike(self):
        second = self.second_project()
        context.add(second, 'Q1', kind='note', label='hypothesis', text='Shared note of project two', scope='general', conditions=['on this machine'],
                    source={'type': 'event', 'id': self.event_of(second)}, key='lesson-shared')       # a 2.2 `context add --scope general`
        knowledge.withdraw(second, 'Q1', 'lesson-shared', reason='wrong', evidence={'sources': [{'type': 'event', 'id': self.event_of(second)}]})
        history = {r['text']: (r['id'], r['status']) for r in knowledge.records(self.ledger, history=True)}
        shown = {' '.join(form): sorted(self.retrieved(*form)) for form in (('--scope', 'general'), ('--scope', 'both'), ('--plan', 'P1', '--scope', 'both'))}
        say('D2-judged-old-lesson-rule', history_of_reader=history, retrieve=shown)
        for form, texts in shown.items():
            self.assertNotIn('Shared note of project two', texts, form)


# ---- E: KN-3 what `wiki history` shows of another project ----------------------------------------------------------------------------

class E_KN3(KBase):
    def test_e1_wiki_history_of_another_projects_record(self):
        second = self.second_project()
        self.general('Rule of project two', HERE, ledger=second, plan='Q1', key='retry')
        shown = self.cli('wiki', 'history')
        row = next(r for r in shown['records'] if r['text'] == 'Rule of project two')
        with second.transaction() as conn:
            tasks = [r[0] for r in conn.execute('SELECT id FROM tasks WHERE project_id=?', (second.project_id,)).fetchall()]
        text = json.dumps(shown)
        say('E1-kn3', project=row['project'], root=row['root'], other_task_ids_shown=[t for t in tasks if t in text],
            full_id_shown=second.project_id in text, path_shown=str(second.project) in text or second.project.as_posix() in text)
        self.assertNotIn(second.project_id, text)
        self.assertNotIn(second.project.as_posix(), text.replace('\\\\', '/'))


# ---- F: KN-4 withdrawing a section past the reading budget ---------------------------------------------------------------------------

class F_KN4(KBase):
    def pages_(self, count):
        for i in range(count): self.page(f'p{i:03d}.md', f'## Section {i}\nText {i}.\n', commit=False)
        self.git('add', '.'); self.git('commit', '-q', '-m', 'pages')

    def evidence(self):
        return {'sources': [{'type': 'event', 'id': self.event_of(self.ledger)}]}

    def test_f1_measure_a_refused_withdrawal_parses_every_page(self):
        self.pages_(60)
        calls, real = [], wiki.parse
        def counting(text, path, *a, **k):
            calls.append(path); return real(text, path, *a, **k)
        with patch.object(wiki, 'MAX_PAGES', 5), patch.object(wiki, 'parse', counting):
            try:
                knowledge.withdraw(self.ledger, 'P1', 'p059-no-such-section', reason='typo', evidence=self.evidence()); refused = False
            except LedgerError:
                refused = True
        say('F1-kn4-cost', pages=60, max_pages=5, refused=refused, parse_calls=len(calls), distinct_pages_parsed=len(set(calls)))
        self.assertTrue(refused)

    def test_f2_measure_the_section_scan_ignores_the_scan_byte_limit(self):
        self.pages_(30)
        reads, real = [], Path.read_bytes
        def counting(path):
            reads.append(path.name); return real(path)
        with patch.object(wiki, 'MAX_PAGES', 2), patch.object(wiki, 'MAX_SCAN_BYTES', 200), patch.object(Path, 'read_bytes', counting):
            try:
                knowledge.withdraw(self.ledger, 'P1', 'p029-section-29', reason='shown wrong', evidence=self.evidence()); recorded = True
            except LedgerError as error:
                recorded = f'refused: {str(error)[:120]}'
        say('F2-kn4-scan-limit', pages=30, max_scan_bytes=200, recorded=recorded, page_reads=len([r for r in reads if r.endswith('.md')]))

    def test_f3_a_withdrawn_section_past_the_budget_stays_withdrawn_once_it_is_read(self):
        self.pages_(4)
        with patch.object(wiki, 'MAX_PAGES', 2):
            knowledge.withdraw(self.ledger, 'P1', 'p003-section-3', reason='shown wrong', evidence=self.evidence())
        pkg = knowledge.package(self.ledger, self.consumer(self.item(goal='Section 3 Text 3')), cap_chars=12000)
        delivered = [e['id'] for e in pkg['entries']]
        listed = delivered + [r['id'] for r in pkg['omitted']['index']]
        say('F3-kn4-effect', delivered=delivered, listed=listed, by_reason=pkg['omitted']['by_reason'])
        self.assertNotIn('p003-section-3', listed)
        self.assertGreaterEqual(pkg['omitted']['by_reason'].get('withdrawn', 0), 1)
        self.assertIn('p002-section-2', listed)


# ---- G: the package steps V15 / V16 --------------------------------------------------------------------------------------------------

def _verify_module():
    sys.path.insert(0, str(CHECKOUT / 'docs' / 'v23' / 'tools'))
    try:
        import verify_milestone
        return verify_milestone
    finally:
        sys.path.pop(0)


@unittest.skipUnless(HAS_WIKI_INIT, 'init has no wiki at this commit')
class G_PackageSteps(wi.Base):
    def test_g1_v15_reads_english_words_that_the_environment_may_turn_vietnamese(self):
        vm = _verify_module()
        if not hasattr(vm, 'init_wiki_cases'): self.skipTest('no V15 at this commit')
        with patch.dict(os.environ, {'ONECREW_LANG': 'vi'}):
            given = vm.env_for(self.base, self.base).get('ONECREW_LANG')     # what every package step runs with (review dev7 answer)
            with patch.dict(os.environ, {'ONECREW_LANG': given or ''}):
                code, out = self.init()
                again_code, again = self.init()
        words = {'plan line': 'create the wiki skeleton in docs/wiki' in out, 'nothing to change': 'nothing to change' in again}
        say('G1-v15-language', env_for_gives=given, exits=[code, again_code], words_v15_looks_for=words)
        self.assertTrue(given == 'en' and all(words.values()), 'V15 fails on a machine with ONECREW_LANG=vi')

    def test_g2_measure_v15_judges_kw07_by_the_exit_code_alone(self):
        vm = _verify_module()
        if not hasattr(vm, 'initwiki_problems'): self.skipTest('no V15 at this commit')
        good = {'new': {'exit': 0, 'files': vm.SKELETON, 'marked': vm.SKELETON, 'plan_line': True,
                        'pages': {'pages': ['docs/wiki/' + n for n in vm.SKELETON], 'entries': 0, 'problems': []}},
                'again': {'exit': 0, 'unchanged': True, 'nothing': True, 'pages': {'entries': 1}},
                'configured': {'exit': 0, 'kb': vm.SKELETON, 'docs': False, 'wiki_config': {'paths': ['kb']}},
                'bad_config': {'exit': 2, 'config_unchanged': True, 'said': True, 'wrote': []},
                'interrupted': {'exit': 0, 'files': vm.SKELETON, 'kept': True},
                'old_project': {'previous_install': 0, 'old_exit': 0, 'old_had_wiki': False, 'exit': 0, 'ledger_unchanged': True, 'custom_kept': True,
                                'state_root_kept': True, 'hook_commands': ['x'], 'new_exe': 'x', 'wiki': vm.SKELETON}}
        other_reason = dict(good, junction={'made': True, 'exit': 2, 'outside': [], 'ledger': False})     # e.g. "no installed command": same facts
        crashed = dict(other_reason, new=dict(good['new'], exit=1))                                       # a traceback after the writes exits 1 too
        say('G2-v15-oracle', junction_fact_keys=sorted(other_reason['junction']), problems_other_reason=vm.initwiki_problems(other_reason),
            problems_exit_1=vm.initwiki_problems(crashed))


if __name__ == '__main__':
    unittest.main()
