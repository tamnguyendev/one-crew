import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from onecrew import delivery_git
from onecrew.delivery_git import GitRefusal, baseline, check_paths, commit, reconcile, render_message, restore_baseline, version_bump
from onecrew.ledger import LedgerError

GIT = shutil.which('git')
APP = 'extension/src/app.ts'
NEW = 'extension/src/new.ts'
OLD = 'extension/src/old.ts'
MANIFEST = 'extension/manifest.json'
MANIFEST_BYTES = ('{\r\n    "manifest_version": 3,\r\n    "name": "Trợ lý điều dưỡng",\r\n    "version" :  "0.6.10",\r\n'
                  '    "background": {"version": "9.9.9", "service_worker": "background.js"},\r\n'
                  '    "permissions": ["sidePanel", "storage"]\r\n}\r\n').encode('utf-8')
FORBIDDEN = re.compile(r'(?i)\b(push|send-pack|receive-pack|remote|ls-remote|fetch|pull)\b')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def remove(base):
    def writable(function, path, error):
        os.chmod(path, 0o700)
        function(path)
    shutil.rmtree(base, onexc=writable)


def run_git(root, *args):
    environment = {k: v for k, v in os.environ.items() if not k.upper().startswith('GIT_')}
    return subprocess.run(['git', '-C', str(root), *args], env=environment, capture_output=True, check=True).stdout


@unittest.skipUnless(GIT, 'needs git on PATH')
class DeliveryGitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # One template repository per run, copied per test: git start-up dominates the run time on Windows.
        cls.template = Path(tempfile.mkdtemp(prefix='oc-dgit-')).resolve()/'repo'
        cls.addClassCleanup(remove, cls.template.parent)
        template = cls('test_baseline_head_branch_status')
        template.root = cls.template
        template.root.mkdir()
        run_git(cls.template, 'init', '-q', '-b', 'main')
        with (cls.template/'.git/config').open('a', encoding='utf-8') as config:
            config.write('[user]\n\tname = Fixture\n\temail = fixture@example.invalid\n[core]\n\tautocrlf = true\n'
                         '\thooksPath = .git/hooks\n[commit]\n\tgpgSign = false\n')
        template.write(APP, b'export const a = 1;\r\nexport const b = 2;\r\n')
        template.write(OLD, b'export const old = true;\r\n')
        template.write(MANIFEST, MANIFEST_BYTES)
        template.write('backend/app/main.py', b'print("base")\r\n')
        template.write('docs/harness/traceability.md', b'# trace\r\n')
        template.write('.gitignore', b'dist/\r\n*.log\r\n')
        run_git(cls.template, 'add', '.')
        run_git(cls.template, 'commit', '-q', '-m', 'base')
        cls.base = run_git(cls.template, 'rev-parse', 'HEAD').decode().strip()
        # Another writer's pre-existing work: one unstaged edit, one staged edit, one untracked file.
        template.write('backend/app/main.py', b'print("user edit")\r\n')
        template.write('docs/harness/traceability.md', b'# trace\r\nstaged by user\r\n')
        run_git(cls.template, 'add', 'docs/harness/traceability.md')
        template.write('notes.txt', b'scratch\r\n')

    def setUp(self):
        base = Path(tempfile.mkdtemp(prefix='oc-dgit-')).resolve()
        self.addCleanup(remove, base)
        self.root = base/'repo'
        shutil.copytree(self.template, self.root)

    def git(self, *args):
        return run_git(self.root, *args)

    def write(self, path, data):
        target = self.root/path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def read(self, path):
        return (self.root/path).read_bytes()

    def apply(self):
        self.write(APP, b'export const a = 1;\r\nexport const b = 3;\r\n')
        self.write(NEW, b'export const added = 1;\r\n')
        return {APP: sha(self.read(APP)), NEW: sha(self.read(NEW))}

    def count(self):
        return int(self.git('rev-list', '--count', 'HEAD'))

    def unrelated(self):
        names = ('backend/app/main.py', 'docs/harness/traceability.md', 'notes.txt')
        index = self.git('ls-files', '-s', '--', 'backend/app/main.py', 'docs/harness/traceability.md')
        return {n: self.read(n) for n in names}, index

    def test_baseline_head_branch_status(self):
        b = baseline(self.root, [APP, NEW])
        json.dumps(b)
        self.assertEqual((b['head'], b['branch'], b['detached'], b['autocrlf'], b['operation']), (self.base, 'main', False, 'true', None))
        kinds = {e['path']: (e['kind'], e['xy']) for e in b['status']['entries']}
        self.assertEqual(kinds, {'backend/app/main.py': ('changed', '.M'), 'docs/harness/traceability.md': ('changed', 'M.'),
                                 'notes.txt': ('untracked', '??')})
        self.assertEqual(b['dirty'], {'backend/app/main.py': sha(self.read('backend/app/main.py')),
                                      'docs/harness/traceability.md': sha(self.read('docs/harness/traceability.md'))})
        self.assertEqual(b['untracked'], {'notes.txt': sha(self.read('notes.txt'))})
        self.assertEqual((b['eol'][APP]['index'], b['eol'][APP]['worktree'], b['eol'][APP]['filter']), ('lf', 'crlf', 'unspecified'))
        self.assertEqual(b['files'][APP]['sha256'], sha(self.read(APP)))
        self.assertEqual(b['files'][NEW], {'sha256': None, 'data': None})
        self.git('checkout', '-q', '--detach')
        detached = baseline(self.root)
        self.assertEqual((detached['branch'], detached['detached'], detached['head']), (None, True, self.base))
        self.apply()
        with self.assertRaises(GitRefusal) as refused:
            commit(self.root, detached, [APP], 'feat: x', 'I-1')
        self.assertEqual(refused.exception.kind, 'detached')
        with self.assertRaises(GitRefusal) as refused:
            baseline(self.root, ['../outside.txt'])
        self.assertEqual(refused.exception.problems[0]['problem'], 'outside_repo')

    def test_no_eol_churn(self):
        b = baseline(self.root, [APP])
        self.apply()
        working = self.read(APP)
        receipt = commit(self.root, b, [APP, NEW], 'feat(panel): change b', 'I-eol')
        self.assertEqual(self.git('show', receipt['commit'] + ':' + APP), b'export const a = 1;\nexport const b = 3;\n')
        self.assertEqual(self.git('show', receipt['commit'] + ':' + NEW), b'export const added = 1;\n')
        self.assertEqual(self.git('diff', '--numstat', self.base, receipt['commit'], '--', APP).split(b'\t')[:2], [b'1', b'1'])
        self.assertEqual(self.read(APP), working)
        self.assertEqual(self.git('status', '--porcelain', '--', APP, NEW), b'')
        self.assertIn(b'i/lf', self.git('ls-files', '--eol', '--', APP))

    def test_unrelated_dirty_untracked_byte_identical_and_staged_kept(self):
        b = baseline(self.root, [APP, NEW])
        before, index = self.unrelated()
        self.apply()
        receipt = commit(self.root, b, [APP, NEW], 'feat(panel): change b', 'I-keep')
        self.assertEqual((receipt['parent'], receipt['branch'], receipt['paths'], receipt['pushed']), (self.base, 'main', [APP, NEW], False))
        self.assertEqual(receipt['author'], 'Fixture <fixture@example.invalid>')
        self.assertEqual(self.unrelated(), (before, index))
        self.assertEqual(self.git('diff', '--cached', '--name-only'), b'docs/harness/traceability.md\n')
        self.assertEqual(self.git('diff', '--name-only', '--', 'backend'), b'backend/app/main.py\n')
        self.assertEqual(self.git('ls-files', '--others', '--exclude-standard'), b'notes.txt\n')
        self.assertEqual(self.git('show', 'HEAD:docs/harness/traceability.md'), b'# trace\n')
        self.assertEqual(self.git('show', 'HEAD:backend/app/main.py'), b'print("base")\n')

    def test_cas_refuses_moved_head_and_branch(self):
        b = baseline(self.root, [APP])
        self.apply()
        self.git('commit', '-q', '-m', 'user commit')
        moved = self.git('rev-parse', 'HEAD')
        index = self.read('.git/index')
        with self.assertRaises(GitRefusal) as refused:
            commit(self.root, b, [APP], 'feat: x', 'I-moved')
        self.assertEqual(refused.exception.kind, 'head_moved')
        self.assertEqual((self.git('rev-parse', 'HEAD'), self.read('.git/index')), (moved, index))
        self.git('reset', '-q', '--soft', self.base)
        self.git('checkout', '-q', '-b', 'other')
        with self.assertRaises(GitRefusal) as refused:
            commit(self.root, b, [APP], 'feat: x', 'I-branch')
        self.assertEqual(refused.exception.kind, 'branch_changed')
        self.assertEqual(self.git('rev-parse', 'HEAD').decode().strip(), self.base)
        self.git('checkout', '-q', 'main')
        self.git('reset', '-q', '--', APP)
        (self.root/'.git/MERGE_HEAD').write_text(self.base + '\n')
        with self.assertRaises(GitRefusal) as refused:
            commit(self.root, b, [APP], 'feat: x', 'I-merge')
        self.assertEqual(refused.exception.kind, 'operation_in_progress')
        (self.root/'.git/MERGE_HEAD').unlink()
        self.write(APP, b'export const a = 1;\r\nexport const b = 2;\r\n')
        with self.assertRaises(GitRefusal) as refused:
            commit(self.root, b, [APP], 'feat: x', 'I-same')
        self.assertEqual(refused.exception.kind, 'nothing_to_commit')
        self.assertEqual(self.git('rev-parse', 'HEAD').decode().strip(), self.base)

    def test_lost_ack_no_second_commit(self):
        b = baseline(self.root, [APP, NEW])
        self.apply()
        original = subprocess.run

        def lost(command, *args, **kwargs):
            result = original(command, *args, **kwargs)
            if 'commit' in command and '--only' in command:
                raise subprocess.TimeoutExpired(command, 1)
            return result
        with patch.object(delivery_git.subprocess, 'run', lost):
            first = commit(self.root, b, [APP, NEW], 'feat: once', 'I-lost')
        self.assertTrue(first['reconciled'])
        self.assertEqual((self.count(), first['parent']), (2, self.base))
        again = commit(self.root, b, [APP, NEW], 'feat: once', 'I-lost')
        self.assertEqual((again['commit'], again['reconciled'], self.count()), (first['commit'], True, 2))
        self.assertEqual(reconcile(self.root, 'I-lost', self.base)['commit'], first['commit'])
        self.assertIsNone(reconcile(self.root, 'I-other', self.base))
        with self.assertRaises(GitRefusal) as refused:
            commit(self.root, b, [APP], 'feat: once', 'I-lost')
        self.assertEqual(refused.exception.kind, 'intent_conflict')

    def test_deny_list_and_typed_path_problems(self):
        self.write('.gitattributes', b'*.dat filter=fake\r\n')
        self.git('add', '.gitattributes')
        self.git('commit', '-q', '-m', 'attributes', '--', '.gitattributes')
        b = baseline(self.root)
        for path in ('extension/secret/key.ts', 'build.log', 'secret.dat'):
            self.write(path, b'x\r\n')
        paths = ['extension/secret/key.ts', '.gitattributes', '../outside.txt', 'C:/abs.txt', 'backend/app/main.py',
                 'docs/harness/traceability.md', 'notes.txt', 'build.log', 'secret.dat', '.env', 'extension']
        problems = check_paths(b, paths, ['extension/secret/**'])
        self.assertEqual([(p['path'], p['problem']) for p in problems], [
            ('../outside.txt', 'outside_repo'), ('.env', 'denied'), ('.gitattributes', 'denied'), ('C:/abs.txt', 'outside_repo'),
            ('backend/app/main.py', 'dirty_at_baseline'), ('build.log', 'ignored'), ('docs/harness/traceability.md', 'staged_at_baseline'),
            ('extension', 'not_a_file'), ('extension/secret/key.ts', 'denied'), ('notes.txt', 'dirty_at_baseline'),
            ('secret.dat', 'external_filter')])
        self.assertTrue({p['problem'] for p in problems} <= set(delivery_git.PROBLEMS))
        self.assertEqual(check_paths(b, [APP, NEW], ['extension/secret/**']), [])
        head, index = self.git('rev-parse', 'HEAD'), self.read('.git/index')
        self.apply()
        with self.assertRaises(GitRefusal) as refused:
            commit(self.root, b, [APP, *paths], 'feat: x', 'I-deny', expected_head=head.decode().strip(), deny_globs=['extension/secret/**'])
        self.assertEqual((refused.exception.kind, refused.exception.problems), ('path_problems', problems))
        for path in ('extension/secret/key.ts', '.gitattributes', 'secret.dat'):
            with self.assertRaises(GitRefusal) as refused:
                commit(self.root, b, [APP, path], 'feat: x', 'I-deny', expected_head=head.decode().strip(), deny_globs=['extension/secret/**'])
            self.assertEqual(refused.exception.kind, 'path_problems')
        self.assertEqual((self.git('rev-parse', 'HEAD'), self.read('.git/index')), (head, index))
        self.write(APP, b'changed by user after apply\r\n')
        with self.assertRaises(GitRefusal) as refused:
            commit(self.root, b, [APP], 'feat: x', 'I-applied', expected_head=head.decode().strip(), applied={APP: sha(b'onecrew bytes')})
        self.assertEqual(refused.exception.problems[0]['problem'], 'changed_since_applied')
        with self.assertRaises(GitRefusal) as refused:
            commit(self.root, b, ['extension/src/missing.ts'], 'feat: x', 'I-missing', expected_head=head.decode().strip())
        self.assertEqual(refused.exception.problems[0]['problem'], 'not_found')

    def test_pre_commit_hook_runs_on_exactly_the_commit(self):
        hook = self.root/'.git/hooks/pre-commit'
        hook.write_bytes(b'#!/bin/sh\ngit diff --cached --name-only > .git/hook-staged\n')
        os.chmod(hook, 0o755)
        b = baseline(self.root, [APP, NEW])
        self.apply()
        commit(self.root, b, [APP, NEW], 'feat: hooked', 'I-hook')
        self.assertEqual(self.read('.git/hook-staged').replace(b'\r\n', b'\n'), (APP + '\n' + NEW + '\n').encode())
        rejecting = baseline(self.root, [APP])
        head, index = self.git('rev-parse', 'HEAD'), self.git('ls-files', '-s')
        hook.write_bytes(b'#!/bin/sh\necho rejected by policy >&2\nexit 1\n')
        self.write(APP, b'export const a = 2;\r\n')
        self.write('extension/src/other.ts', b'new file\r\n')
        with self.assertRaises(GitRefusal) as refused:
            commit(self.root, rejecting, [APP, 'extension/src/other.ts'], 'feat: rejected', 'I-reject')
        self.assertEqual(refused.exception.kind, 'commit_failed')
        self.assertIn('rejected by policy', str(refused.exception))
        self.assertEqual((self.git('rev-parse', 'HEAD'), self.git('ls-files', '-s')), (head, index))
        self.assertEqual(self.git('status', '--porcelain', '--', 'extension/src/other.ts'), b'?? extension/src/other.ts\n')
        # A hook that touches another writer's file: the commit exists but is never reported as verified.
        hook.write_bytes(b'#!/bin/sh\nprintf hook >> backend/app/main.py\n')
        with self.assertRaises(GitRefusal) as refused:
            commit(self.root, rejecting, [APP], 'feat: touches others', 'I-touch')
        self.assertEqual((refused.exception.kind, refused.exception.facts['failed']), ('verification_failed', ['other_worktree_changed']))

    def test_version_bump_preserves_format_and_eol(self):
        b = baseline(self.root, [MANIFEST])
        result = version_bump(self.root, MANIFEST)
        self.assertEqual(self.read(MANIFEST), MANIFEST_BYTES.replace(b'"0.6.10"', b'"0.6.11"'))
        self.assertEqual(result, {'path': MANIFEST, 'field': 'version', 'old': '0.6.10', 'new': '0.6.11',
                                  'sha_before': sha(MANIFEST_BYTES), 'sha_after': sha(self.read(MANIFEST))})
        with self.assertRaises(GitRefusal) as refused:
            version_bump(self.root, MANIFEST, expected_sha=result['sha_before'])
        self.assertEqual(refused.exception.kind, 'cas_mismatch')
        self.assertEqual(sha(self.read(MANIFEST)), result['sha_after'])
        self.assertEqual(version_bump(self.root, MANIFEST, bump='minor', expected_sha=result['sha_after'])['new'], '0.7.0')
        tabbed = b'\xef\xbb\xbf{\n\t"version": "1.2",\n\t"x": [1, {"version": 7}]\n}'
        self.write('package.json', tabbed)
        self.assertEqual(version_bump(self.root, 'package.json')['new'], '1.2.1')
        self.assertEqual(self.read('package.json'), tabbed.replace(b'"1.2"', b'"1.2.1"'))
        self.assertEqual(version_bump(self.root, 'package.json', bump='major')['new'], '2.0.0')
        for bad in (b'{"version": "1.0", "version": "1.1"}', b'{"version": 3}', b'{"version": "1.0-beta"}', b'[1]', b'{'):
            self.write('bad.json', bad)
            with self.assertRaises(GitRefusal):
                version_bump(self.root, 'bad.json')
            self.assertEqual(self.read('bad.json'), bad)
        self.git('add', 'package.json', 'bad.json')
        self.git('reset', '-q', '--', 'package.json', 'bad.json')
        receipt = commit(self.root, b, [MANIFEST], 'chore(release): 0.7.0', 'I-version')
        self.assertEqual(self.git('diff', '--numstat', self.base, receipt['commit']).split(b'\t')[:2], [b'1', b'1'])

    def test_version_commit_separate(self):
        b = baseline(self.root, [APP, NEW, MANIFEST])
        self.apply()
        code = commit(self.root, b, [APP, NEW], 'feat(panel): code', 'T-1:code')
        version_bump(self.root, MANIFEST)
        release = commit(self.root, b, [MANIFEST], 'chore(release): 0.6.11', 'T-1:version', expected_head=code['commit'])
        self.assertEqual((release['parent'], release['paths'], self.count()), (code['commit'], [MANIFEST], 3))
        with self.assertRaises(GitRefusal) as refused:
            commit(self.root, b, [MANIFEST], 'chore(release): again', 'T-1:again')
        self.assertEqual(refused.exception.kind, 'head_moved')
        self.assertEqual(commit(self.root, b, [APP, NEW], 'feat(panel): code', 'T-1:code')['commit'], code['commit'])

    def test_restore_baseline_cas(self):
        b = baseline(self.root, [APP, NEW, OLD])
        original_app, original_old = self.read(APP), self.read(OLD)
        applied = self.apply()
        (self.root/OLD).unlink()
        self.write('extension/src/extra.ts', b'extra\r\n')
        applied.update({OLD: None, 'extension/src/extra.ts': sha(b'extra\r\n')})
        self.write(APP, b'user changed it again\r\n')
        with self.assertRaises(GitRefusal) as refused:
            restore_baseline(self.root, b, applied)
        self.assertEqual([(p['path'], p['problem']) for p in refused.exception.problems], [(APP, 'changed_since_applied')])
        self.assertTrue((self.root/NEW).exists())
        self.write(APP, b'export const a = 1;\r\nexport const b = 3;\r\n')
        for path in ('backend/app/main.py', MANIFEST, 'notes.txt'):
            with self.assertRaises(GitRefusal) as refused:
                restore_baseline(self.root, b, {path: sha(self.read(path))})
            self.assertEqual(refused.exception.problems[0]['problem'], 'not_in_baseline')
        result = restore_baseline(self.root, b, applied)
        self.assertEqual(result['restored'], sorted(applied))
        self.assertEqual((self.read(APP), self.read(OLD)), (original_app, original_old))
        self.assertFalse((self.root/NEW).exists() or (self.root/'extension/src/extra.ts').exists())
        self.assertEqual(self.read('backend/app/main.py'), b'print("user edit")\r\n')

    def test_message_trailers(self):
        template = {'subject': 'feat(panel): {TASK} ward flag', 'body': ['Vitest {passed}/{total} passed.', 'Literal {{x}}.'],
                    'trailers': [['OneCrew-Task', '{TASK}'], ['Co-Authored-By', 'Claude Opus 5.5 <noreply@anthropic.com>']]}
        message = render_message(template, {'TASK': 'TASK-1', 'passed': 12, 'total': 12})
        self.assertEqual(message, 'feat(panel): TASK-1 ward flag\n\nVitest 12/12 passed.\nLiteral {x}.\n\n'
                                  'OneCrew-Task: TASK-1\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\n')
        for bad, fields in (({'subject': '{missing}'}, {}), ({'subject': 'a\nb'}, {}), ({'subject': 'x', 'trailers': [['OneCrew-Intent', 'y']]}, {}),
                            ({'subject': 'x', 'trailers': [['bad key', 'y']]}, {}), ({'subject': 'x', 'extra': 1}, {}),
                            ({'subject': '{v}'}, {'v': ['list']})):
            with self.assertRaises(LedgerError):
                render_message(bad, fields)
        with self.assertRaises(LedgerError):
            commit(self.root, baseline(self.root), [APP], 'x\n\nOneCrew-Intent: forged', 'I-msg')
        b = baseline(self.root, [APP])
        self.apply()
        receipt = commit(self.root, b, [APP], message, 'TASK-1:code')
        body = self.git('log', '-1', '--format=%B', receipt['commit']).decode()
        self.assertTrue(body.endswith('Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\nOneCrew-Intent: TASK-1:code\n\n'), body)
        self.assertEqual(self.git('log', '-1', '--format=%(trailers:key=OneCrew-Intent,valueonly)', receipt['commit']).strip(), b'TASK-1:code')
        self.assertEqual(delivery_git._with_intent('subject only', 'I-2'), 'subject only\n\nOneCrew-Intent: I-2\n')
        second = commit(self.root, b, [NEW], 'subject only', 'I-2', expected_head=receipt['commit'])
        self.assertEqual((second['paths'], second['parent']), ([NEW], receipt['commit']))
        self.assertEqual(self.git('log', '-1', '--format=%B', second['commit']).decode(), 'subject only\n\nOneCrew-Intent: I-2\n\n')

    def test_no_push_code_path(self):
        source = Path(delivery_git.__file__).read_text(encoding='utf-8')
        self.assertIsNone(FORBIDDEN.search(source))
        commands = []
        original = subprocess.run

        def spy(command, *args, **kwargs):
            commands.append(list(command))
            return original(command, *args, **kwargs)
        with patch.object(delivery_git.subprocess, 'run', spy):
            b = baseline(self.root, [APP, NEW, MANIFEST])
            applied = self.apply()
            code = commit(self.root, b, [APP, NEW], 'feat: spy', 'I-spy', applied=applied)
            version_bump(self.root, MANIFEST)
            commit(self.root, b, [MANIFEST], 'chore: version', 'I-spy-v', expected_head=code['commit'])
            reconcile(self.root, 'I-spy', self.base)
            commit(self.root, b, [APP, NEW], 'feat: spy', 'I-spy')
            self.write(APP, b'export const a = 1;\r\nexport const b = 3;\r\n')
        self.assertTrue(commands)
        self.assertTrue(all(c[0] == 'git' for c in commands))
        self.assertFalse([c for c in commands if any(FORBIDDEN.fullmatch(a) for a in c)])
        commits = [c for c in commands if 'commit' in c and '--only' in c]
        self.assertEqual(len(commits), 2)
        self.assertFalse([c for c in commits if '--no-verify' in c or '-n' in c or any(a.startswith('core.hooksPath') for a in c)])
        self.assertFalse([c for c in commits if any(a.startswith('user.') for a in c)])
        self.assertEqual(code['pushed'], False)


if __name__ == '__main__':
    unittest.main()
