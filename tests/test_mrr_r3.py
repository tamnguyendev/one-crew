"""MR-R round 3: counterexamples for what a real folder of repositories does that the first fixtures did not do.

r301 a declared source that is a LINKED WORKTREE of a repository the root never declared (the Git directory with its index lives inside the
      main repository, outside the coordination folder): read and cited, and neither the worktree nor the main repository is written;
r302 the main repository and one of its linked worktrees declared as two aliases are two different sources (their own branch, tree and
      citations), never mixed;
r303 one folder declared twice under two spellings (a relative path and its absolute path) is one source: the alias that sorts first is
      read, the other is a named same_repository gap, so two aliases of one repository are never counted as two repositories read;
r304 a repository folder with spaces and accented letters, a file whose name has accents and whose text is UTF-8 with a byte order mark and
      CRLF line ends: read, searched and cited on the lines Git counts, and the report keeps the real name.

Fixture repositories only, the in-process fixture worker (no model). These are counterexamples the first fixtures never ran, NOT red-to-green
behaviour tests: all four pass on the unchanged source of a8a0253 (r303 because the pin already turns the second spelling into a named
same_repository gap). They are kept as regression cover. The process-kill test is in the installed-wheel e2e (scenario S8), not here.
"""
import os
import unittest
from unittest.mock import patch


from tests.test_mrr_sources import MrrFixture, REPO_A, REPO_B, REPORT, git, make_repo, write
from tests.test_v24_a_sources import ask, body_of, done

class R3Fixture(MrrFixture):
    def declare(self, repos, why):
        """An amendment that declares more repositories, approved from the owner's own terminal (an AI shell cannot approve)."""
        from onecrew.v2 import plan as plans
        plans.amend(self.ledger, 'P1', self.contract(repos=repos), why, 'codex')
        with patch.dict(os.environ):
            os.environ.pop('ONECREW_ACTOR', None)
            plans.approve(self.ledger, 'P1', 'owner', 'fixture approval: ' + why)


MAIN_FILES = {'src/main.py': b'MAIN = 1\n# NEEDLE-MAIN lives in the main repository\n', 'README.md': b'main readme\n'}


class LinkedWorktreeTests(R3Fixture):
    repos = {'core': ('repo-a', REPO_A)}

    def prepare_repos(self):
        self.main = self.base / 'main'
        make_repo(self.main, MAIN_FILES)
        git(self.main, 'worktree', 'add', '-q', '-b', 'side', str(self.work / 'wt'))
        write(self.work / 'wt', {'src/side.py': b'SIDE = 2\n# NEEDLE-SIDE exists only on the side branch\n'})
        git(self.work / 'wt', 'add', '-A'); git(self.work / 'wt', 'commit', '-q', '-m', 'side work')
        self.paths['wt'] = self.work / 'wt'

    def also_watched(self):
        return {'main': self.main}

    def test_r301_a_linked_worktree_of_an_undeclared_repository_is_read_without_writing_either_repository(self):
        repos = self.declared() + [{'alias': 'linked', 'path': 'wt', 'read': ['src/**']}]
        self.declare(repos, 'a linked worktree is declared')
        self.plan(self.item(patterns=('core:src/', 'linked:src/')))
        seen = {}
        def first(prompt, schema):
            return ask({'op': 'search', 'repo': 'linked', 'query': 'needle'}, {'op': 'read', 'repo': 'linked', 'path': 'src/side.py'})
        def second(prompt, schema):
            seen['tools'] = body_of(prompt)['source_tools']
            return done('analysis\n', path=REPORT)
        self.values += [first, second]
        self.assertEqual(self.step()['state'], 'continuing')
        produced = self.step()
        self.assertEqual(produced['state'], 'produced', produced)
        tools = seen['tools']
        self.assertEqual([(r['repo'], r['status']) for r in tools['repos']], [('core', 'pinned'), ('linked', 'pinned')], tools['coverage_gaps'])
        self.assertEqual(tools['coverage_gaps'], [])
        found = [m for r in tools['results'] if r['action'] == 'search' for m in r['result']['matches']]
        self.assertEqual([m['path'] for m in found], ['src/main.py', 'src/side.py'])        # the worktree holds the main files too
        receipt = self.receipt(produced)
        pin = receipt['source']['repos']['linked']
        self.assertEqual(pin['head'], git(self.work / 'wt', 'rev-parse', 'HEAD'))
        self.assertEqual(pin['branch'], 'refs/heads/side')
        self.assertFalse(pin['dirty'])
        for match in found:
            self.assertIn('NEEDLE-' + match['path'][4:8].upper(), ''.join(self.cite_lines(match['cite'], receipt)))


class MainAndWorktreeTests(R3Fixture):
    repos = {'core': ('repo-a', REPO_A)}

    def prepare_repos(self):
        git(self.paths['core'], 'worktree', 'add', '-q', '-b', 'feature', str(self.work / 'repo-a-feature'))
        write(self.work / 'repo-a-feature', {'src/alpha.py': b'ALPHA = 99\n# NEEDLE-ALPHA of the feature branch\n'})
        git(self.work / 'repo-a-feature', 'add', '-A'); git(self.work / 'repo-a-feature', 'commit', '-q', '-m', 'feature')
        self.paths['feature'] = self.work / 'repo-a-feature'

    def test_r302_the_main_repository_and_its_linked_worktree_are_two_sources_with_their_own_snapshots(self):
        repos = self.declared() + [{'alias': 'feature', 'path': 'repo-a-feature', 'read': ['src/**']}]
        self.declare(repos, 'main and its worktree')
        self.plan(self.item(patterns=('core:src/', 'feature:src/')))
        seen = {}
        self.values += [lambda p, s: ask({'op': 'read', 'repo': 'core', 'path': 'src/alpha.py'}, {'op': 'read', 'repo': 'feature', 'path': 'src/alpha.py'}),
                        lambda p, s: seen.update(tools=body_of(p)['source_tools']) or done('x\n', path=REPORT)]
        self.step()
        produced = self.step()
        self.assertEqual(produced['state'], 'produced', produced)
        reads = self.by_repo(seen['tools']['results'], 'read')
        self.assertIn('ALPHA = 1', reads['core']['text']); self.assertIn('ALPHA = 99', reads['feature']['text'])
        self.assertNotEqual(reads['core']['cite'], reads['feature']['cite'])
        receipt = self.receipt(produced)
        self.assertNotEqual(receipt['source']['repos']['core']['tree'], receipt['source']['repos']['feature']['tree'])
        self.assertNotEqual(receipt['source']['repos']['core']['head'], receipt['source']['repos']['feature']['head'])


class DuplicateFolderTests(R3Fixture):
    repos = {'core': ('repo-a', REPO_A)}

    def test_r303_one_folder_under_two_spellings_is_one_source_and_the_second_alias_is_a_named_gap(self):
        absolute = self.paths['core'].as_posix()
        self.declare(self.declared() + [{'alias': 'again', 'path': absolute, 'read': ['src/**']}], 'the same folder, spelled as an absolute path')
        self.plan(self.item(patterns=('core:src/', 'again:src/')))
        seen = {}
        self.values += [lambda p, s: ask({'op': 'search', 'repo': 'again', 'query': 'needle'}, {'op': 'search', 'repo': 'core', 'query': 'needle'}),
                        lambda p, s: seen.update(tools=body_of(p)['source_tools']) or done('x' + chr(10), path=REPORT)]
        self.step()
        produced = self.step()
        self.assertEqual(produced['state'], 'produced', produced)
        tools = seen['tools']
        self.assertEqual([(g['repo'], g['state']) for g in tools['coverage_gaps']], [('core', 'same_repository')], tools['coverage_gaps'])
        self.assertIn('the same folder as the repository again', tools['coverage_gaps'][0]['reason'])      # the alias that sorts first wins, the other is the gap
        self.assertEqual([r['repo'] for r in tools['repos'] if r['status'] == 'pinned'], ['again'])


UNI = 'kho mã nguồn'
UNI_FILE = 'tài liệu/hướng dẫn.md'
UNI_TEXT = '﻿Tiêu đề\r\nDòng hai: NEEDLE-VIỆT đây\r\nDòng ba\r\n'.encode('utf-8')


class UnicodeTests(MrrFixture):
    repos = {'core': ('repo-a', REPO_A), 'app': (UNI + '/ứng dụng', {**REPO_B, 'src/' + UNI_FILE.split('/')[1]: UNI_TEXT})}
    grants = dict(MrrFixture.grants)

    def prepare_repos(self):
        pass

    def test_r304_a_folder_with_spaces_and_accents_and_a_utf8_bom_file_are_read_and_cited_on_git_lines(self):
        self.plan(self.item(patterns=('core:src/', 'app:src/')))
        seen = {}
        name = 'src/' + UNI_FILE.split('/')[1]
        self.values += [lambda p, s: ask({'op': 'search', 'repo': 'app', 'query': 'needle-việt'}, {'op': 'read', 'repo': 'app', 'path': name}),
                        lambda p, s: seen.update(tools=body_of(p)['source_tools']) or done('x\n', path=REPORT)]
        self.step()
        produced = self.step()
        self.assertEqual(produced['state'], 'produced', produced)
        tools = seen['tools']
        self.assertEqual(tools['coverage_gaps'], [], tools['coverage_gaps'])
        found = [m for r in tools['results'] if r['action'] == 'search' for m in r['result']['matches']]
        self.assertEqual([m['path'] for m in found], [name])
        receipt = self.receipt(produced)
        self.assertEqual(self.cite_lines(found[0]['cite'], receipt), ['Dòng hai: NEEDLE-VIỆT đây'])
        read = self.by_repo(tools['results'], 'read')['app']
        self.assertEqual(read['path'], name)
        self.assertIn('Tiêu đề', read['text'])


if __name__ == '__main__':
    unittest.main()
