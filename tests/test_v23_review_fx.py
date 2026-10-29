r"""Kept from the independent review of the verifier fixes (D:/OneCrewRuns/v23/review-dev7/review-fx.md, written by the reviewer on 04ae80b and 1cc9419;
probes D:/OneCrewRuns/v23/review-dev7/wt-fx/tests/test_v23_review_fx_probes.py). Each test asserts the behaviour decided after the review:

  FX-R01 (P2) a Git working-tree file that the artifact tree would take and that has another name on the disk (a hard link, maybe to an ignored
         .env) stops the verifier before git hashes it: nothing of it is read, stored or pinned. Decided: the run is refused with the reason (the
         doc, data, ops and command verifiers), or inconclusive with it (the reviewer), rather than "not verified, the run goes on": the tree
         cannot leave the file out without verifying a different artifact. Known limit, HOP-DONG-2.3 section 10.4.
  FX-R02 (P2) an ids check that examined nothing (no id of its pattern found) is a problem, never a pass.
  FX-R04 (P3) with a global (?i) two ids that differ only in case are one id.
  FX-R05 (P3) a kept name that is not valid Unicode is refused with a LedgerError, not a crash.
  DX-R01 (P2) a source written ./x, .\x or ../x is relative to the document only: a file of that name at the root does not stand in for it.
  DX-R02 (P3) a word that starts with a dot before the path (.NET, .csv, .5) is not taken for the locator; an ellipsis before it is dropped.

The known limits that stay open are expected failures (FX-R03, FX-R06, FX-R08) or pinned (FX-R07, the junction case), so that a change is seen.
No network, no provider, no model: git and the verifier adapters only, in temporary folders; LOCALAPPDATA and APPDATA are those of the run.
"""
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

try:
    import re._constants as C
    import re._parser as P
except ImportError:                                                    # Python 3.10
    import sre_constants as C
    import sre_parse as P

from onecrew.ledger import Ledger, LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2.verifiers import artifact, command, doc, port

SECRET = 'API_KEY=do-not-read-me\n'
TOKEN = 'do-not-read-me'
OLD_START = r'^\s*(?:#{1,6}[ \t]+|[-*+][ \t]+|\d+[.)][ \t]+|\|[ \t]*)[\[\*_`(]*('


def git(root, *args):
    done = subprocess.run(['git', '-C', str(root), '-c', 'core.autocrlf=false', *args], capture_output=True, text=True, encoding='utf-8', errors='replace')
    if done.returncode: raise AssertionError(f'git {args}: {done.stderr}')
    return done.stdout


def link(source, target):
    try:
        os.link(source, target)
    except OSError as error:
        raise unittest.SkipTest(f'no hard link on this volume: {error}')


def milestone(kind, config):
    return {'id': 'M1', 'title': 'Probe', 'max_repairs': 2, 'covers': ['O1'], 'verifier': {'type': kind, 'config': port.normalize(kind, config, 'probe')}}


def objects_holding(root, token):
    """The objects of the repository's store whose content holds `token` (every object, loose or packed)."""
    done = subprocess.run(['git', '-C', str(root), 'cat-file', '--batch-all-objects', '--batch'], capture_output=True)
    return token.encode() in done.stdout


def state_files_holding(state, token):
    return [p.name for p in Path(state).rglob('*') if p.is_file() and token.encode() in p.read_bytes()]


# ---- FX-R01: a hard link in a Git working tree --------------------------------------------------------------------------------

class GitArtifactHardLink(unittest.TestCase):
    """A Git project whose `.env` is ignored, and an ordinary name that the worker made a hard link to it (link count 2 in the working tree)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); self.root = self.base / 'repo'; (self.root / 'docs').mkdir(parents=True)
        git(self.root, 'init', '-q')
        (self.root / '.gitignore').write_text('.env\n', encoding='utf-8', newline='\n')
        (self.root / 'docs' / 'guide.md').write_text('# Guide\n\n- REQ-1 the first\n\nSee REQ-1.\n', encoding='utf-8', newline='\n')
        git(self.root, 'add', '-A'); git(self.root, '-c', 'user.name=probe', '-c', 'user.email=probe@example.invalid', 'commit', '-q', '-m', 'init')
        self.ledger = Ledger(self.root, self.base / 'state')

    def refused(self, call):
        with self.assertRaises(LedgerError) as caught:
            call()
        self.assertIn('hard link', str(caught.exception))
        self.assertNotIn(TOKEN, str(caught.exception))
        self.assertFalse(objects_holding(self.root, TOKEN), 'git hashed the linked file into the object store')
        self.assertEqual(state_files_holding(self.base / 'state', TOKEN), [])

    def test_x01_the_doc_adapter_never_reads_a_kept_file_through_a_hard_link_in_a_git_tree(self):
        (self.root / '.env').write_text(SECRET, encoding='utf-8', newline='\n')
        link(self.root / '.env', self.root / 'docs' / 'notes.md')
        config = {'docs': ['docs/guide.md', 'docs/notes.md'], 'links': True,
                  'ids': [{'name': 'K', 'pattern': r'do-not-[a-z-]+', 'defined_in': ['docs/guide.md']}]}
        self.refused(lambda: port.run(self.ledger, 'P1', 1, 'a' * 64, milestone('doc', config), self.root))

    def test_x02_the_data_adapter_never_reads_a_kept_file_through_a_hard_link_in_a_git_tree(self):
        (self.root / '.env').write_text('API_KEY\ndo-not-read-me\n', encoding='utf-8', newline='\n')
        link(self.root / '.env', self.root / 'output.csv')
        config = {'path': 'output.csv', 'columns': {'API_KEY': 'string'}, 'key': ['API_KEY'], 'row_count': 1}
        self.refused(lambda: port.run(self.ledger, 'P1', 1, 'a' * 64, milestone('data', config), self.root))

    def test_x07_the_command_verifier_never_runs_on_a_tree_holding_a_hard_linked_file(self):
        (self.root / '.env').write_text(SECRET, encoding='utf-8', newline='\n')
        link(self.root / '.env', self.root / 'docs' / 'notes.md')
        step = {'id': 'M1', 'title': 'Probe', 'max_repairs': 2, 'covers': ['O1'],
                'verifier': {'type': 'command', 'config': {'argv': [sys.executable, '-c', 'print(open("docs/notes.md").read())'], 'max_minutes': 1}}}
        self.refused(lambda: command.run(self.ledger, 'P1', 1, 'a' * 64, step, self.root))

    def test_x08_a_tracked_file_replaced_by_a_hard_link_is_seen_too(self):
        (self.root / '.env').write_text(SECRET, encoding='utf-8', newline='\n')
        stamp = os.stat(self.root / 'docs' / 'guide.md')
        os.remove(self.root / 'docs' / 'guide.md')
        link(self.root / '.env', self.root / 'docs' / 'guide.md')
        os.utime(self.root / 'docs' / 'guide.md', ns=(stamp.st_atime_ns, stamp.st_mtime_ns))       # the times the index has: they must not hide it
        self.refused(lambda: artifact.verified_identity(self.root))         # the identity a verifier makes (identity() is the views', D-R01)

    def test_x09_control_a_tree_without_hard_links_keeps_its_identity(self):
        self.assertEqual(artifact.identity(self.root), command.artifact_sha(self.root))
        (self.root / 'docs' / 'extra.md').write_text('# Extra\n', encoding='utf-8', newline='\n')
        self.assertEqual(artifact.identity(self.root), command.artifact_sha(self.root))


class GitVerdictRunHardLink(unittest.TestCase):
    """x01 through the production path: propose, approve and `verdict run` a doc milestone on a Git project (no direct port call). The link is made
    after the approval, as a worker would make it: a link already there when the owner approves stops the approval (D-R02, test_h08)."""

    def test_x06_verdict_run_keeps_no_copy_of_a_kept_file_reached_through_a_hard_link(self):
        from onecrew.v2 import plan as plans, verdict
        from tests.test_v2_l1 import plan_json
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        base = Path(temp.name); root = base / 'project'; (root / 'docs').mkdir(parents=True)
        git(root, 'init', '-q')
        (root / 'a.txt').write_text('one\n', encoding='utf-8', newline='\n')
        (root / '.gitignore').write_text('.env\n', encoding='utf-8', newline='\n')
        (root / 'docs' / 'guide.md').write_text('# Guide\n\n- REQ-1 the first\n\nSee REQ-1.\n', encoding='utf-8', newline='\n')
        git(root, 'add', '-A'); git(root, '-c', 'user.name=probe', '-c', 'user.email=probe@example.invalid', 'commit', '-q', '-m', 'base')
        (root / '.env').write_text(SECRET, encoding='utf-8', newline='\n')
        (root / 'docs' / 'notes.md').write_text('# Notes\n\nKeep REQ-1.\n', encoding='utf-8', newline='\n')
        env = patch.dict(os.environ); env.start(); self.addCleanup(env.stop)
        for name in ('ONECREW_ACTOR', 'ONECREW_V2_REQUIRE_PLAN', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION'): os.environ.pop(name, None)
        os.environ['LOCALAPPDATA'] = str(base / 'lad'); os.environ['APPDATA'] = str(base / 'ad')
        ledger = Ledger(root, base / 'state')
        config = {'docs': ['docs/guide.md', 'docs/notes.md'], 'links': True,
                  'ids': [{'name': 'K', 'pattern': r'do-not-[a-z-]+', 'defined_in': ['docs/guide.md']}]}
        value = plan_json(milestones=[{'id': 'M1', 'title': 'Docs', 'max_repairs': 2, 'verifier': {'type': 'doc', 'config': config}, 'covers': ['O1']}])
        plans.propose(ledger, 'P1', value, 'claude'); plans.approve(ledger, 'P1', 'owner', 'probe fixture')
        os.remove(root / 'docs' / 'notes.md'); link(root / '.env', root / 'docs' / 'notes.md')          # the worker's link, after the approval
        with self.assertRaises(LedgerError) as caught:
            verdict.run(ledger, 'P1', 'M1')
        self.assertIn('hard link', str(caught.exception))
        refs = [line.split() for line in git(root, 'for-each-ref', '--format=%(refname) %(objectname)').splitlines() if 'onecrew' in line.lower()]
        for ref, tree in refs:
            shown = subprocess.run(['git', '-C', str(root), 'cat-file', '-p', f'{tree}:docs/notes.md'], capture_output=True, text=True)
            self.assertFalse(shown.returncode == 0 and TOKEN in shown.stdout, ref)
        self.assertFalse(objects_holding(root, TOKEN))
        self.assertEqual(state_files_holding(base / 'state', TOKEN), [])


# ---- FX-3 / FX-4 without Git ------------------------------------------------------------------------------------------------

class NonGitFolder(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); self.root = self.base / 'source'; (self.root / 'docs').mkdir(parents=True)
        (self.root / 'docs' / 'a.md').write_text('# A\n\n- REQ-1 one\n\nSee REQ-1.\n', encoding='utf-8', newline='\n')
        (self.root / 'output.csv').write_text('id\n1\n', encoding='utf-8', newline='\n')

    @unittest.expectedFailure
    def test_x03_a_link_between_two_ordinary_files_is_not_verified_and_the_run_goes_on(self):
        """Known limit FX-R08: while the folder holds a kept name, any hard link stops the identity (it cannot tell which other name the file has)."""
        (self.root / '.env').write_text('', encoding='utf-8')
        link(self.root / 'docs' / 'a.md', self.root / 'docs' / 'b.md')
        _, receipt = port.run(Ledger(self.root, self.base / 'state'), 'P1', 1, 'a' * 64, milestone('doc', {'docs': ['docs/a.md'], 'links': True}), self.root)
        self.assertTrue(any('hard link' in n for n in receipt['unverified']))

    @unittest.expectedFailure
    def test_x04_a_kept_file_outside_the_folder_is_never_copied_into_the_ledger_through_a_hard_link(self):
        """Known limit FX-R06: a folder without kept names is identified as it always was, a hard link to a file elsewhere included."""
        elsewhere = self.base / 'home'; elsewhere.mkdir()
        (elsewhere / '.env').write_text(SECRET, encoding='utf-8', newline='\n')
        link(elsewhere / '.env', self.root / 'docs' / 'notes.md')
        port.run(Ledger(self.root, self.base / 'state'), 'P1', 1, 'a' * 64, milestone('doc', {'docs': ['docs/a.md', 'docs/notes.md'], 'links': True}), self.root)
        self.assertEqual(state_files_holding(self.base / 'state', TOKEN), [])

    def test_x05_a_kept_name_that_cannot_be_written_as_utf8_is_refused_not_a_crash(self):
        name = '.env\udc80'
        try:
            (self.root / name).write_text(SECRET, encoding='utf-8')
        except (OSError, UnicodeError) as error:
            self.skipTest(f'this volume does not take a lone surrogate name: {error}')
        with self.assertRaises(LedgerError):
            artifact.identity(self.root)

    def test_y01_a_junction_after_the_first_file_of_a_kept_folder_is_not_walked_and_nothing_is_read(self):
        """Left open on purpose (FX commit): the kept folder is named once its first file is met; nothing below it is read, a junction included."""
        if os.name != 'nt': self.skipTest('junctions are a Windows feature')
        import _winapi
        (self.root / '.aws' / 'a').mkdir(parents=True); (self.root / '.aws' / 'b').mkdir()
        (self.root / '.aws' / 'a' / 'credentials').write_text(SECRET, encoding='utf-8')
        outside = self.base / 'outside'; outside.mkdir(); (outside / 'big.txt').write_text(SECRET * 3, encoding='utf-8')
        _winapi.CreateJunction(str(outside), str(self.root / '.aws' / 'b' / 'j'))
        self.addCleanup(lambda: os.rmdir(self.root / '.aws' / 'b' / 'j'))
        workspace, _, proof = artifact.capture(Ledger(self.root, self.base / 'state'), self.root, tempfile.mkdtemp(dir=self.temp.name))
        self.assertEqual(proof.get('artifact_kept'), ['.aws/'])
        self.assertEqual(sorted(p.relative_to(workspace).as_posix() for p in workspace.rglob('*') if p.is_file()), ['docs/a.md', 'output.csv'])
        self.assertEqual(state_files_holding(self.base / 'state', TOKEN), [])


# ---- FX-1: the ids pattern --------------------------------------------------------------------------------------------------

EDGES = {C.AT_BEGINNING, C.AT_BEGINNING_STRING, C.AT_END, C.AT_END_STRING}
LEADING_FLAGS = re.compile(r'\(\?[aiLmsux]+\)')
REPEATS = tuple(getattr(C, n) for n in ('MAX_REPEAT', 'MIN_REPEAT', 'POSSESSIVE_REPEAT') if hasattr(C, n))
ATOMIC = getattr(C, 'ATOMIC_GROUP', None)


def anchors(items, negative=False, out=None):
    r"""(anchor, inside a negative assertion) for every ^ $ \A \Z in a parsed pattern: Python's own parser, not the code under test."""
    out = [] if out is None else out
    for op, av in items:
        if op is C.AT:
            if av in EDGES: out.append((str(av), negative))
        elif op is C.SUBPATTERN: anchors(av[-1], negative, out)
        elif op in (C.ASSERT, C.ASSERT_NOT): anchors(av[1], negative or op is C.ASSERT_NOT, out)
        elif op is C.BRANCH:
            for branch in av[1]: anchors(branch, negative, out)
        elif op in REPEATS: anchors(av[2], negative, out)
        elif ATOMIC is not None and op is ATOMIC: anchors(av, negative, out)
        elif op is C.GROUPREF_EXISTS:
            anchors(av[1], negative, out)
            if av[2] is not None: anchors(av[2], negative, out)
    return out


def group(items, number):
    """The parsed body of capture group `number`, or None."""
    for op, av in items:
        found = None
        if op is C.SUBPATTERN:
            if av[0] == number: return av[-1]
            found = group(av[-1], number)
        elif op in (C.ASSERT, C.ASSERT_NOT): found = group(av[1], number)
        elif op is C.BRANCH:
            for branch in av[1]:
                found = found or group(branch, number)
        elif op in REPEATS: found = group(av[2], number)
        elif ATOMIC is not None and op is ATOMIC: found = group(av, number)
        if found is not None: return found
    return None


def judge(pattern):
    """What Python's parser says about `pattern`, against the two forms _id_forms builds. None when the pattern is not a regex at all."""
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        try:
            re.compile(pattern); tree = P.parse(pattern)
        except (re.error, ValueError, OverflowError, RecursionError):
            return None
        edges = [a for a, negative in anchors(tree) if not negative]
        flagged = LEADING_FLAGS.match(pattern) is not None
        old_use, old_start = r'(?<![\w-])(?:' + pattern + r')(?![\w-])', OLD_START + pattern + r')(?![\w-])'
        try:
            use, start, tidy = doc._id_forms(pattern, 'probe')
        except LedgerError:
            return {'edges': edges, 'flagged': flagged, 'refused': True}
        left_use = [a for a, negative in anchors(P.parse(use.pattern)) if not negative]
        body = group(P.parse(start.pattern), 1)
        left_def = [a for a, negative in anchors(body) if not negative] if body is not None else ['no group 1']
        same = use.pattern == old_use and start.pattern == old_start and tidy(' x ') == ' x '
        return {'edges': edges, 'flagged': flagged, 'refused': False, 'same': same, 'left_use': left_use, 'left_def': left_def}


ATOMS = ['REQ', '-', r'\d+', r'\d', '[A-Z]', '[A-Z]+', r'[^\s]', '[$^]', r'[\^]', '[]^]', '[^]^]', '[^^]', r'[\]$]', r'\^', r'\$', r'\\', r'\b', r'\B',
         '^', '$', r'\A', r'\Z', 'x', '#', ' ', r'\#', r'\ ', '(?#c^$)', r'(?#a\)b^)', '.', r'\.', r'\(', r'\)', r'\[', r'\]', r'\w', r'\s', r'\W',
         r'\136', r'\x24', r'^', '[#]', '[(]', '[)]', r'[\\]', '\n']
HAND = [r'REQ-\d+|^NFR-\d+', r'^REQ-\d+|NFR-\d+$', r'(?:^|\s)REQ-\d+(?:\s|$)', r'(?:^|\W)REQ-\d+', r'(^|[^\w])REQ-\d+', r'(?<=^)REQ-\d+',
        r'(?=^)REQ-\d+', r'REQ-\d+(?=$)', r'REQ-\d+(?<=\d$)', r'(?<!x^)REQ', r'(?!^)REQ-\d+', r'(?<=x(?!^))REQ', r'[$]REQ', r'[^$]REQ', r'[\^$]REQ',
        r'[]$^]REQ', r'\^REQ\$', r'\\^REQ', r'\\\^REQ', r'\\\\^REQ', r'(?#^)REQ(?#$)', r'(?x)REQ#^\n$', r'(?x)[#^]REQ', r'(?x)\#^REQ', r'(?x)(?-x:#^)REQ',
        r'(?x:#^\n)REQ', r'\bREQ-\d+\b', r'\B^REQ', r'(?m)REQ-\d+$', r'(?m)^REQ', r'(?s)^REQ.$', r'(?(1)^|x)', r'(a)?(?(1)^|x)REQ', r'(?P<p>^)?REQ',
        r'(?:^)+REQ', r'(^)*REQ', r'(?>^)REQ', r'REQ$+', r'REQ\Z', r'\AREQ', r'(?i)(?m)^req$', r'(?a)\AREQ\Z', r'(?u)^REQ', r'REQ-\d+\n$', r'\136REQ',
        r'\x5eREQ', r'REQ-[0-9]+(?![0-9])$', r'(?<![\w-])^REQ', r'^(?<![\w-])REQ']


def generate(rng, depth=0):
    roll = rng.random()
    if depth > 2 or roll < 0.3: return rng.choice(ATOMS)
    if roll < 0.55: return generate(rng, depth + 1) + generate(rng, depth + 1)
    if roll < 0.65: return generate(rng, depth + 1) + '|' + generate(rng, depth + 1)
    inner = generate(rng, depth + 1)
    shape = rng.randrange(15)
    return [f'({inner})', f'(?:{inner})', f'(?P<g{rng.randrange(9)}>{inner})', f'(?={inner})', f'(?!{inner})', f'(?<={inner})', f'(?<!{inner})',
            f'(?i:{inner})', f'(?x:{inner}\n)', f'(?-x:{inner})', f'(?>{inner})', f'{inner}?', f'{inner}*', f'{inner}+', f'(?:{inner}){{1,2}}'][shape]


class IdsOracle(unittest.TestCase):
    r"""_id_forms judged by Python's own parser: a pattern with no ^ $ \A \Z outside a negative assertion and no leading flag gives exactly the regexes
    of 4bb41b3, and whatever else is accepted leaves no such anchor in the search or in the id group of the definition form. The reviewer ran 30 000
    random patterns; this keeps the hand-written ones and 4 000 of the same seed."""

    def test_x10_the_rewrite_matches_what_python_parses(self):
        rng = random.Random(20261030)
        corpus = list(HAND)
        while len(corpus) < 4000 + len(HAND):
            corpus.append(rng.choice(['', '', '', '(?i)', '(?x)', '(?m)', '(?s)', '(?a)', '(?i)(?m)', '(?x)(?i)']) + generate(rng))
        plain_diff, left, seen = [], [], 0
        for pattern in corpus:
            verdict = judge(pattern)
            if verdict is None or verdict['refused']: continue
            seen += 1
            plain = not verdict['edges'] and not verdict['flagged']
            if plain and not verdict['same']: plain_diff.append(pattern)
            if not plain and (verdict['left_use'] or verdict['left_def']): left.append(pattern)
        self.assertGreater(seen, 1000)
        self.assertEqual(plain_diff, [])
        self.assertEqual(left, [])


class IdsTree(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'tree'; (self.root / 'docs').mkdir(parents=True)

    def write(self, rel, text):
        (self.root / rel).write_text(text, encoding='utf-8', newline='\n')

    def ids(self, pattern, docs, defined_in=()):
        box = port.Port(self.root, port.authority(None, 'test'), 'doc')
        try:
            value = doc.validate_config({'docs': list(docs), 'links': False, 'ids': [{'name': 'R', 'pattern': pattern, 'defined_in': list(defined_in)}]}, 'probe')
        except LedgerError as error:
            return ['refused at propose: ' + str(error)[:140]], None
        report = doc.run(value, box)
        check = next(c for c in report['checks'] if c['id'] == 'ids')
        return check['problems'], check['checked']


VACUOUS = (r'\BREQ-\d+', r'REQ-\d+\B', r'(?<=REQ-)\d+', r'(?<=\w)REQ-\d+', r'REQ-\d+(?=-)', r'REQ-\d+(?=\w)')


class IdsResults(IdsTree):
    def test_x11_a_valid_pattern_never_passes_the_ids_check_with_nothing_examined(self):
        self.write('docs/spec.md', '# Spec\n\n- REQ-1 one\n\nSee REQ-1 and REQ-3.\n')
        for pattern in VACUOUS:
            with self.subTest(pattern=pattern):
                problems, checked = self.ids(pattern, ['docs/spec.md'])
                self.assertTrue(problems, 'the ids check passes with nothing examined while REQ-3 is used and never defined')
                if checked == 0: self.assertIn('examined nothing', problems[0])

    def test_x11b_control_documents_with_ids_are_checked_as_before(self):
        self.write('docs/spec.md', '# Spec\n\n- REQ-1 one\n\nSee REQ-1 and REQ-3.\n')
        self.assertEqual(self.ids(r'REQ-\d+', ['docs/spec.md']), (['docs/spec.md:5: REQ-3 is used but never defined (R)'], 3))
        self.write('docs/spec.md', '# Spec\n\n- REQ-1 one\n\nSee REQ-1.\n')
        self.assertEqual(self.ids(r'REQ-\d+', ['docs/spec.md']), ([], 2))

    @unittest.expectedFailure
    def test_x12_a_boundary_written_as_an_alternation_never_reports_a_wrong_id(self):
        r"""Known limit FX-R03: an anchor inside an alternation, `(?:^|\W)REQ-\d+`, takes the character in front into the id (`(REQ-2`): a loud false
        problem, never a pass; write `\bREQ-\d+` or `REQ-\d+` (HOP-DONG-2.3 section 10.4)."""
        self.write('docs/spec.md', '# Spec\n\n- **REQ-1** one\n- (REQ-2) two\n- [REQ-3] three\n- REQ-4 four\n\nSee **REQ-1**, (REQ-2), [REQ-3] and REQ-4.\n')
        for pattern in (r'(?:^|\W)REQ-\d+', r'(^|[^\w])REQ-\d+', r'(?:^|[\s(\[*])REQ-\d+'):
            problems, _ = self.ids(pattern, ['docs/spec.md'])
            self.assertEqual(problems, [])

    def test_x13_a_case_insensitive_pattern_compares_ids_without_case(self):
        self.write('docs/spec.md', '# Spec\n\n- REQ-1 one\n- req-2 two\n- REQ-2 two again\n\nSee req-1 and REQ-2.\n')
        problems, checked = self.ids(r'(?i)req-\d+', ['docs/spec.md'])
        self.assertEqual(len(problems), 1, problems)
        self.assertIn('is defined twice (docs/spec.md:4, docs/spec.md:5)', problems[0])
        self.assertEqual(checked, 4)
        self.assertEqual(self.ids(r'(?i:req)-\d+', ['docs/spec.md'])[0][-1], 'docs/spec.md:7: req-1 is used but never defined (R)')   # a scoped flag: as written

    def test_x14_a_stored_pattern_with_a_numbered_group_is_a_problem_of_the_ids_check(self):
        """What an approved 2.2 plan holding such a pattern gets at verdict time (stored configs are not validated again): a fail with the way out."""
        self.write('docs/spec.md', '# Spec\n\n- AA-1 one\n\nSee AA-1 and BB-2.\n')
        box = port.Port(self.root, port.authority(None, 'test'), 'doc')
        value = doc.validate_config({'docs': ['docs/spec.md'], 'links': False, 'ids': [{'name': 'R', 'pattern': r'[A-Z]{2}-\d+', 'defined_in': []}]}, 'probe')
        value['ids'][0]['pattern'] = r'([A-Z])\1-\d+'
        check = next(c for c in doc.run(value, box)['checks'] if c['id'] == 'ids')
        self.assertEqual((check['ok'], check['checked'], len(check['problems'])), (False, 0, 1))
        self.assertIn('a group referred to by number', check['problems'][0])


# ---- FX-2: short names, on a volume that makes them -------------------------------------------------------------------------

def short_alias(path):
    if os.name != 'nt': return None
    import ctypes
    buffer = ctypes.create_unicode_buffer(1024)
    if not ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, 1024): return None
    alias = Path(buffer.value).name
    return alias if alias.lower() != Path(path).name.lower() else None


LONG = ['.env.example', '.env', '.envrc', '.ssh', '.aws', '.git', '.onecrew', '.gitignore', 'a b.csv', 'da ta.csv', 'my.data.file.csv', 'report 2024.xlsx',
        'tài liệu.md', 'Ünïcödé name.md', 'name+plus.csv', 'name,comma.csv', 'semi;colon.csv', 'eq=uals.csv', '[brackets].csv', 'notes.markdown',
        '~$lockfile.docx', 'a~b c.csv', 'x.y.z', '.env~', 'verylongname.csv', 'UPPERCASE-LONG-NAME.TXT', 'n.ame.csv', '#hash name.md',
        "it's.csv", '(paren) x.csv', '{brace} x.csv', '@at x.csv', 'a%b c.csv', 'a&b c.csv', 'a!b c.csv', 'a^b c.csv', 'a`b c.csv', 'café.csv']


class ShortNamesOfC(unittest.TestCase):
    def test_x20_every_alias_the_volume_gives_is_refused_at_propose(self):
        base = os.environ.get('PROBE_SHORTNAME_DIR')
        if not base: self.skipTest('set PROBE_SHORTNAME_DIR to a folder on a volume that makes 8.3 names')
        temp = tempfile.TemporaryDirectory(dir=base); self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        names = list(LONG) + [f'.env.example{n}' for n in range(1, 9)] + [f'collide-long-name-{n}.csv' for n in range(1, 9)]
        missed, given = [], 0
        for name in names:
            try:
                (root / name).write_text('x', encoding='utf-8')
            except OSError:
                continue
            alias = short_alias(root / name)
            if alias is None: continue
            given += 1
            if port.short_name_part(alias) is None: missed.append((name, alias))
        if given == 0: self.skipTest('this volume made no alias')
        self.assertEqual(missed, [])

    def test_x21_real_long_names_of_the_alias_form_are_refused_at_propose(self):
        """Known limit FX-R07 (pinned): the form of an alias is judged without a file system, so a real file named like one cannot be named."""
        for name, refused in (('data~1.csv', True), ('notes~1.md', True), ('report~3.csv', True), ('v~2.json', False)):
            with self.subTest(name=name):
                try:
                    port.long_name(name, 'probe'); outcome = False
                except LedgerError:
                    outcome = True
                self.assertEqual(outcome, refused)


# ---- DX: bare source locators --------------------------------------------------------------------------------------------------

DX_CONFIG = {'docs': [{'path': 'docs/sub/page.md', 'headings': [], 'sources': {'section': 'Nguồn', 'min': 1, 'cite': r'S\d+', 'external': 'unverified'}}],
             'links': False}


class BareLocators(unittest.TestCase):
    """A small repository: README.md and CHANGELOG.md at the root, docs/guide.md, docs/sub/page.md (the page under test, one source line),
    docs/sub/page2.md, sources/notes.txt, .github/ci.yml, .env.example."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'tree'
        for rel, text in (('README.md', '# Read me\n'), ('CHANGELOG.md', '# Changes\n'), ('docs/guide.md', '# Guide\n\n## Tổng quan\n\nText.\n'),
                          ('sources/notes.txt', 'notes\n'), ('.github/ci.yml', 'on: push\n'), ('.env.example', SECRET), ('docs/sub/page2.md', '# Two\n')):
            path = self.root / rel; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text, encoding='utf-8', newline='\n')

    def page(self, line, links=False, body=''):
        path = self.root / 'docs' / 'sub' / 'page.md'
        path.write_text('# Page\n\nText [S1].' + body + '\n\n## Nguồn\n\n' + line + '\n', encoding='utf-8', newline='\n')
        box = port.Port(self.root, port.authority(None, 'test'), 'doc')
        report = doc.run(doc.validate_config(dict(DX_CONFIG, links=links), 'probe'), box)
        return {c['id']: c['problems'] for c in report['checks'] if not c['ok']}, report

    def test_d01_a_dot_slash_source_missing_next_to_the_page_is_not_found_even_when_the_root_has_that_name(self):
        for line in ('- [S1] ./README.md — the read-me of this folder', '- [S1] ./CHANGELOG.md', '- [S1] ./sources/notes.txt — notes',
                     '- [S1] .' + chr(92) + 'README.md — Windows separator', '- [S1] (./README.md) — direct form'):
            with self.subTest(line=line):
                failing, _ = self.page(line)
                self.assertIn('sources', failing, 'the page folder holds no such file; the root file of the same name was taken instead')
                self.assertIn('file not found (docs/sub/', failing['sources'][0])

    def test_d02_a_description_before_the_path_keeps_finding_the_path(self):
        for line in ('- [S1] ghi chú .NET: sources/notes.txt', '- [S1] bảng .csv: sources/notes.txt', '- [S1] mẫu .env: sources/notes.txt',
                     '- [S1] bản .5 của sources/notes.txt', '- [S1] ...sources/notes.txt — after an ellipsis', '- [S1] ghi chú: sources/notes.txt'):
            with self.subTest(line=line):
                failing, _ = self.page(line)
                self.assertEqual(failing, {})

    def test_d03_the_other_forms(self):
        bs = chr(92)
        cases = [('- [S1] ..' + bs + 'guide.md — Windows separator', None), ('- [S1] .' + bs + 'page2.md — next to the page, Windows separator', None),
                 ('- [S1] ../guide.md#tổng-quan — an anchor', None), ('- [S1] ../guide.md#khong-co — a missing anchor', 'no heading with the anchor #khong-co'),
                 ('- [S1] ./ — this folder', None), ('- [S1] ../ — the folder above', None), ('- [S1] ... — only dots', 'has no locator'),
                 ('- [S1] .. — two dots', 'has no locator'), ('- [S1] ../../../x.md — above the repository', 'leaves the project'),
                 ('- [S1] .env.example — kept', None), ('- [S1] ./.env.example — kept, but not next to the page', 'file not found (docs/sub/.env.example)'),
                 ('- [S1] README.md — a bare name: next to the page, else at the root', None)]
        for line, problem in cases:
            with self.subTest(line=line):
                failing, report = self.page(line)
                if problem is None: self.assertEqual(failing, {})
                else: self.assertIn(problem, failing['sources'][0])
        _, report = self.page('- [S1] .env.example — kept')
        self.assertTrue([n for n in report['unverified'] if '.env.example' in n and 'not checked' in n])

    def test_d04_the_same_target_as_a_link_and_as_a_source_is_reported_by_both(self):
        failing, _ = self.page('- [S1] ./README.md — the read-me of this folder', links=True, body=' See [the read-me](./README.md).')
        self.assertEqual(sorted(failing), ['links', 'sources'])


# ---- the delta review of 7a1ce5c (review-fx.md, "Delta review of 7a1ce5c"; probes test_v23_review_delta_*.py of the reviewer) -------------

def commit(root, message='c'):
    git(root, 'add', '-A'); git(root, '-c', 'user.name=probe', '-c', 'user.email=probe@example.invalid', 'commit', '-q', '-m', message)


def has_object(root, oid):
    return subprocess.run(['git', '-C', str(root), 'cat-file', '-e', oid], capture_output=True).returncode == 0


def secret_blob(root):
    return subprocess.run(['git', '-C', str(root), 'hash-object', '--stdin'], input=SECRET.encode(), capture_output=True).stdout.decode().strip()


class DeltaRepo(unittest.TestCase):
    """A Git project with an ignored .env holding the secret and an ignored private/ folder."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); self.root = self.base / 'repo'; (self.root / 'docs').mkdir(parents=True)
        git(self.root, 'init', '-q')
        (self.root / '.gitignore').write_text('.env\nprivate/\n', encoding='utf-8', newline='\n')
        (self.root / 'a.txt').write_text('one\n', encoding='utf-8', newline='\n')
        (self.root / 'docs' / 'guide.md').write_text('# Guide\n\n## Usage\n\n- REQ-1 the first\n\nSee REQ-1.\n', encoding='utf-8', newline='\n')
        commit(self.root, 'base')
        (self.root / '.env').write_text(SECRET, encoding='utf-8', newline='\n')
        env = patch.dict(os.environ); env.start(); self.addCleanup(env.stop)
        for name in ('ONECREW_ACTOR', 'ONECREW_V2_REQUIRE_PLAN', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION'): os.environ.pop(name, None)
        os.environ['LOCALAPPDATA'] = str(self.base / 'lad'); os.environ['APPDATA'] = str(self.base / 'ad')

    def plan(self, ledger, verifier):
        from onecrew.v2 import plan as plans
        from tests.test_v2_l1 import plan_json
        plans.propose(ledger, 'P1', plan_json(milestones=[{'id': 'M1', 'title': 'Check', 'max_repairs': 2, 'verifier': verifier, 'covers': ['O1']}]), 'claude')
        return plans


class DeltaHardLinks(DeltaRepo):
    def test_h01_a_force_added_ignored_hard_link_is_seen(self):
        """D-R04: names of the REAL index too (git add -f of an ignored name, and -N)."""
        from onecrew.v2 import plan as plans
        for flags in (('-f',), ('-f', '-N')):
            with self.subTest(flags=flags):
                (self.root / 'private').mkdir(exist_ok=True)
                target = self.root / 'private' / ('notes%d.md' % len(flags))
                link(self.root / '.env', target)
                git(self.root, 'add', *flags, target.relative_to(self.root).as_posix())
                self.assertIn(target.relative_to(self.root).as_posix(), command.hard_links(self.root))
                with self.assertRaises(LedgerError):
                    plans._base_tracked(Ledger(self.root, self.base / 'state'))

    def test_h04_a_hard_link_inside_onecrew_is_refused_before_git_hashes_it(self):
        """D-R05: .onecrew is looked at too, so no blob of it is written."""
        (self.root / '.onecrew').mkdir()
        link(self.root / '.env', self.root / '.onecrew' / 'x.md')
        with self.assertRaises(LedgerError):
            command.verified_sha(self.root)
        self.assertFalse(has_object(self.root, secret_blob(self.root)))

    def test_h06_a_hard_link_made_during_a_command_run_is_never_hashed_into_a_pinned_tree(self):
        """D-R05: the after-identity is made the way the before one is, so the tree it would hash is never made; since E-R01 the run is kept as an
        inconclusive receipt (test_s01)."""
        from onecrew.v2 import verdict
        argv = [sys.executable, '-c', f'import os; os.link({str(self.root / ".env")!r}, {str(self.root / "docs" / "late.md")!r})']
        ledger = Ledger(self.root, self.base / 'state')
        plans = self.plan(ledger, {'type': 'command', 'config': {'argv': argv}}); plans.approve(ledger, 'P1', 'owner', 'probe fixture')
        self.assertEqual(verdict.run(ledger, 'P1', 'M1')['milestones'][0]['last_verdict']['result'], 'inconclusive')
        self.assertFalse(objects_holding(self.root, TOKEN))
        refs = [line.split() for line in git(self.root, 'for-each-ref', '--format=%(refname) %(objectname)').splitlines() if 'onecrew' in line.lower()]
        for ref, tree in refs:
            shown = subprocess.run(['git', '-C', str(self.root), 'cat-file', '-p', f'{tree}:docs/late.md'], capture_output=True, text=True)
            self.assertFalse(shown.returncode == 0 and TOKEN in shown.stdout, ref)

    def test_j01_a_file_reached_through_a_junction_is_never_read_under_an_ordinary_name(self):
        """D-R03: a working-tree path that crosses a junction is refused like a hard link."""
        if os.name != 'nt': self.skipTest('junctions are a Windows feature')
        import _winapi
        home = self.base / 'home' / '.ssh'; home.mkdir(parents=True); (home / 'notes.md').write_text(SECRET, encoding='utf-8', newline='\n')
        _winapi.CreateJunction(str(home), str(self.root / 'docs' / 'keys'))
        self.addCleanup(lambda: os.rmdir(self.root / 'docs' / 'keys'))
        config = {'docs': ['docs/guide.md', 'docs/keys/notes.md'], 'links': True,
                  'ids': [{'name': 'K', 'pattern': r'do-not-[a-z-]+', 'defined_in': ['docs/guide.md']}]}
        with self.assertRaises(LedgerError) as caught:
            port.run(Ledger(self.root, self.base / 'state'), 'P1', 1, 'a' * 64, milestone('doc', config), self.root)
        self.assertIn('junction', str(caught.exception))
        self.assertNotIn(TOKEN, str(caught.exception))
        self.assertFalse(objects_holding(self.root, TOKEN))

    def test_j01b_control_a_directory_symlink_is_stored_as_a_link_and_not_refused(self):
        try:
            os.symlink(self.base, self.root / 'docs' / 'symdir', target_is_directory=True)
        except OSError as error:
            self.skipTest(f'this account cannot create a symbolic link: {error}')
        self.assertEqual(command.hard_links(self.root), [])


class DeltaViewsAndApproval(DeltaRepo):
    DOC = {'type': 'doc', 'config': {'docs': [{'path': 'docs/guide.md', 'headings': ['Usage']}], 'links': True}}

    def unrelated_link(self):
        (self.root / 'assets').mkdir(exist_ok=True); (self.root / 'assets' / 'a.bin').write_bytes(b'\x00')
        link(self.root / 'assets' / 'a.bin', self.root / 'assets' / 'b.bin')

    def test_h07_a_pass_on_an_older_artifact_is_not_shown_as_passed_while_a_hard_link_exists(self):
        """D-R01: the views judge the artifact as before; a hard link does not switch stale detection off."""
        from onecrew.v2 import verdict
        ledger = Ledger(self.root, self.base / 'state')
        plans = self.plan(ledger, self.DOC); plans.approve(ledger, 'P1', 'owner', 'probe fixture')
        self.assertEqual(verdict.run(ledger, 'P1', 'M1')['milestones'][0]['state'], 'passed')
        (self.root / 'docs' / 'guide.md').write_text('# Guide\n\nThe usage section was removed.\n', encoding='utf-8', newline='\n')
        self.unrelated_link()
        self.assertNotEqual(plans.show(ledger, 'P1')['milestones'][0]['state'], 'passed')

    def test_h08_approve_refuses_a_hard_link_and_then_records_both_bases(self):
        """D-R02: approve stops with the reason (nothing is recorded), and approves once the link is gone, with both base trees."""
        from onecrew.v2.verifiers import reviewer
        ledger = Ledger(self.root, self.base / 'state')
        self.unrelated_link()
        plans = self.plan(ledger, self.DOC)
        with self.assertRaises(LedgerError) as caught:
            plans.approve(ledger, 'P1', 'owner', 'probe fixture')
        self.assertIn('hard link', str(caught.exception))
        with ledger.transaction() as conn:
            task = plans.derive(ledger, conn, 'P1')['task_id']
        self.assertFalse([e for e in ledger.events(task) if e['kind'] == 'plan.approved'])
        (self.root / 'assets' / 'b.bin').unlink()
        plans.approve(ledger, 'P1', 'owner', 'probe fixture')
        approved = next(e['payload'] for e in ledger.events(task) if e['kind'] == 'plan.approved')
        self.assertTrue(approved.get('base_artifact') and approved.get('base_tracked'))
        (self.root / 'docs' / 'guide.md').write_text('# Guide\n\n## Usage\n\nChanged.\n', encoding='utf-8', newline='\n')
        self.assertIn('Changed.', reviewer.review_diff(self.root, reviewer.base_event(approved, None), None)[0])


class DeltaDocs(unittest.TestCase):
    setUp, page = BareLocators.setUp, BareLocators.page                   # the same tree, without running the BareLocators tests a second time

    def test_l02_a_dotted_locator_after_words(self):
        """D-R06: a dotfile name after words is the locator when it holds another dot or is a longer lowercase name; a short dot-word is prose;
        an ellipsis glued to a path does not make it a root path; a dotfile first is the locator."""
        (self.root / '.gitignore').write_text('*.tmp\n', encoding='utf-8', newline='\n')
        failing, report = self.page('- [S1] mẫu cấu hình .env.example')
        self.assertEqual(failing, {})
        self.assertTrue([n for n in report['unverified'] if '.env.example' in n])
        for line in ('- [S1] quy tắc bỏ qua .gitignore', '- [S1] .gitignore — the ignore rules'):
            with self.subTest(line=line):
                self.assertEqual(self.page(line)[0], {})
        failing, _ = self.page('- [S1] .../guide.md — an ellipsis glued to a path')
        self.assertNotIn('(guide.md)', json.dumps(failing, ensure_ascii=False))


class RoundFour(DeltaRepo):
    """The second delta review (review-fx.md, "Delta review of 376654d"; probes test_v23_review_delta2_probes.py of the reviewer)."""

    def test_s01_a_link_made_by_the_command_gives_an_inconclusive_receipt_and_the_next_run_goes_on(self):
        """E-R01: the command ran, so its result is kept: inconclusive with the reason, never a lost run that holds the milestone."""
        from onecrew.v2 import verdict
        argv = [sys.executable, '-c', f'import os; print("ran"); os.link({str(self.root / ".env")!r}, {str(self.root / "docs" / "late.md")!r})']
        ledger = Ledger(self.root, self.base / 'state')
        plans = self.plan(ledger, {'type': 'command', 'config': {'argv': argv}}); plans.approve(ledger, 'P1', 'owner', 'probe fixture')
        first = verdict.run(ledger, 'P1', 'M1')['milestones'][0]['last_verdict']
        self.assertEqual(first['result'], 'inconclusive')
        body = json.loads(Snapshots(ledger.state_root).read_blob(first['receipt']))
        self.assertIsNone(body['artifact_sha_after']); self.assertIn('hard link', body['error'])
        (self.root / 'docs' / 'late.md').unlink()
        self.assertIn(verdict.run(ledger, 'P1', 'M1')['milestones'][0]['last_verdict']['result'], ('pass', 'fail', 'inconclusive'))

    def test_s01b_the_after_identity_of_an_adapter_check_is_kept_the_same_way(self):
        calls = []
        real = artifact.verified_identity
        def second_refused(directory):
            calls.append(directory)
            if len(calls) > 1: raise command.HardLinked('docs/late.md has more than one name on the disk (a hard link)')
            return real(directory)
        with patch.object(artifact, 'verified_identity', second_refused):
            _, receipt = port.run(Ledger(self.root, self.base / 'state'), 'P1', 1, 'a' * 64,
                                  milestone('doc', {'docs': ['docs/guide.md'], 'links': True}), self.root)
        self.assertEqual(port.expected_result(receipt), 'inconclusive')
        self.assertIsNone(receipt['artifact_sha_after']); self.assertIn('hard link', receipt['error'])

    def test_s02_a_tracked_path_under_a_folder_that_became_a_directory_symlink_is_not_refused(self):
        """E-R02: git stores the folder as a link and hashes nothing behind it; only a junction refuses the names below it."""
        (self.root / 'vendor').mkdir(); (self.root / 'vendor' / 'lib.txt').write_text('v\n', encoding='utf-8'); commit(self.root, 'vendor')
        outside = self.base / 'shared-vendor'; outside.mkdir(); (outside / 'lib.txt').write_text('v\n', encoding='utf-8')
        (self.root / 'vendor' / 'lib.txt').unlink(); (self.root / 'vendor').rmdir()
        try:
            os.symlink(outside, self.root / 'vendor', target_is_directory=True)
        except OSError as error:
            self.skipTest(f'this account cannot create a symbolic link: {error}')
        self.assertEqual(command.hard_links(self.root), [])
        self.assertTrue(command.verified_sha(self.root))

    def test_s06_a_hard_link_at_a_path_python_cannot_stat_plainly_is_still_refused(self):
        """E-R04: beyond MAX_PATH (LongPathsEnabled 0, core.longpaths in the repository) the name is examined through the \\\\?\\ prefix."""
        if os.name != 'nt': self.skipTest('MAX_PATH is a Windows limit')
        git(self.root, 'config', 'core.longpaths', 'true')
        deep = 'docs/' + '/'.join(['d' * 50] * 5) + '/notes-with-a-long-name.md'
        prefix = '\\\\?\\'
        target = prefix + str(self.root / deep).replace('/', '\\')
        os.makedirs(os.path.dirname(target), exist_ok=True)
        self.addCleanup(shutil.rmtree, prefix + str(self.root / 'docs' / ('d' * 50)), True)      # the temporary folder's own cleanup cannot reach it
        os.link(prefix + str(self.root / '.env'), target)
        self.assertGreater(len(str(self.root / deep)), 260)
        self.assertIn(deep, command.hard_links(self.root))
        with self.assertRaises(LedgerError):
            command.verified_sha(self.root)


class RoundFourDocs(unittest.TestCase):
    """E-R05: a bare source line names the first of its readings that is there."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'tree'
        for rel, text in (('.env', SECRET), ('.env.example', SECRET), ('.gitignore', '*.tmp\n'), ('.DS_Store', 'x'), ('.vscode/settings.json', '{}'),
                          ('data/x.parquet', 'p'), ('sources/notes.txt', 'n\n'), ('docs/guide.md', '# G\n')):
            path = self.root / rel; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text, encoding='utf-8', newline='\n')

    def page(self, line):
        path = self.root / 'docs' / 'sub' / 'page.md'; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('# Page\n\nText [S1].\n\n## Nguồn\n\n' + line + '\n', encoding='utf-8', newline='\n')
        box = port.Port(self.root, port.authority(None, 'test'), 'doc')
        report = doc.run(doc.validate_config(DX_CONFIG, 'probe'), box)
        return {c['id']: c['problems'] for c in report['checks'] if not c['ok']}, report

    def test_s05_dot_led_words_and_dotfiles(self):
        for line in ('- [S1] bảng .parquet: data/x.parquet', '- [S1] bảng .jsonl: sources/notes.txt', '- [S1] tệp ẩn .DS_Store',
                     '- [S1] cấu hình trong .vscode', '- [S1] .NET guide: sources/notes.txt', '- [S1] quy tắc bỏ qua .gitignore', '- [S1] .gitignore'):
            with self.subTest(line=line):
                self.assertEqual(self.page(line)[0], {})
        for line in ('- [S1] mẫu .env', '- [S1] mẫu cấu hình .env.example'):
            with self.subTest(line=line):
                failing, report = self.page(line)
                self.assertEqual(failing, {})
                self.assertTrue([n for n in report['unverified'] if 'not checked' in n], report['unverified'])
        failing, _ = self.page('- [S1] tài liệu .csv không có ở đây')
        self.assertIn('.csv: file not found', failing['sources'][0])       # a dot-word with nothing there: reported, never a pass

    def test_f01_a_line_that_names_a_path_is_checked_on_that_path(self):
        """F-R01 (the delta review of 726aacf): a missing path written after a description is reported even when a later word names a file that is there;
        a path that leaves the project is reported; only a line that names no path at all tries its dot-led words."""
        (self.root / 'README.md').write_text('# R\n', encoding='utf-8')
        (self.root / 'data.xlsx').write_text('x', encoding='utf-8')
        for line, problem in (('- [S1] ghi chú về sources/missing.txt, xem README.md', 'sources/missing.txt: file not found'),
                              ('- [S1] tóm tắt reports/q3.md (bản gốc trong data.xlsx)', 'reports/q3.md: file not found'),
                              ('- [S1] bản tóm tắt reports/missing.md, dữ liệu .env', 'reports/missing.md: file not found'),
                              ('- [S1] cấu hình config/app.yaml dựa trên .gitignore', 'config/app.yaml: file not found'),
                              ('- [S1] tham khảo ../../../outside.md và README.md', 'leaves the project'),
                              ('- [S1] ghi chú về missing.txt, xem README.md', 'missing.txt: file not found')):
            with self.subTest(line=line):
                failing, _ = self.page(line)
                self.assertIn('sources', failing)
                self.assertIn(problem, failing['sources'][0])


class RoundFiveDocs(RoundFourDocs):
    """The check of 3f3edb7 (review-fx.md, "Check of 3f3edb7"; probes test_v23_review_check4_probes.py of the reviewer)."""

    def setUp(self):
        super().setUp()
        for rel in ('README.md', 'notes.txt', 'data.xlsx'): (self.root / rel).write_text('x\n', encoding='utf-8')

    def test_f01_a_line_that_names_a_path_is_checked_on_that_path(self):
        pass                                                                   # run once, in RoundFourDocs

    def test_s05_dot_led_words_and_dotfiles(self):
        pass                                                                   # run once, in RoundFourDocs

    def test_g02_a_word_that_only_looks_like_a_path_does_not_hide_the_path_the_line_names(self):
        """G-R01: a prose word with a slash (CI/CD, km/h) or a version number (v1.2) is not taken for the path the line names after it."""
        for line in ('- [S1] hướng dẫn CI/CD: docs/guide.md', '- [S1] dữ liệu và/hoặc tóm tắt: sources/notes.txt', '- [S1] phiên bản v1.2, xem notes.txt',
                     '- [S1] đo bằng km/h trong sources/notes.txt'):
            with self.subTest(line=line):
                self.assertEqual(self.page(line)[0], {})

    def test_g03_a_missing_dotfile_with_an_extension_is_reported_although_a_later_dotfile_is_there(self):
        """G-R02: a dot-led name with an extension (.env.example, .env.local) is a path of its own, checked on its own."""
        for line in ('- [S1] mẫu cấu hình .env.example (thêm vào .gitignore)', '- [S1] mẫu .env.local hoặc .env'):
            with self.subTest(line=line):
                (self.root / '.env.example').unlink(missing_ok=True)
                failing, _ = self.page(line)
                self.assertIn('sources', failing)
                self.assertIn('file not found', failing['sources'][0])


class DeltaIds(IdsTree):
    def test_i03_the_case_rule_is_the_flag_s_not_casefold(self):
        """D-R08: with (?i), ids differing in case are one id, as the regex flag sees them; STRASSE and STRAẞE stay two."""
        self.write('docs/spec.md', '# Spec\n\n- STRASSE-1 one\n- STRAẞE-1 two\n\nSee straße-1.\n')
        self.assertEqual(self.ids(r'(?i)[a-zß]+-\d+', ['docs/spec.md'])[0], [])

    def test_i04_the_old_search_results_are_kept_and_the_empty_check_is_a_problem_of_the_check(self):
        """D-R09: _check_ids gives the old search's results; the ids check (doc.run) adds the 'examined nothing' problem."""
        self.write('docs/spec.md', '# Spec\n\nNo requirement is listed yet.\n')
        spec = doc.validate_config({'docs': ['docs/spec.md'], 'links': False, 'ids': [{'name': 'R', 'pattern': r'REQ-\d+', 'defined_in': []}]}, 't')['ids'][0]
        box = port.Port(self.root, port.authority(None, 'test'), 'doc')
        folder = doc.Folder(box); folder.load('docs/spec.md', required=True)
        self.assertEqual(doc._check_ids(spec, folder, ['docs/spec.md']), ([], 0))
        problems, checked = self.ids(r'REQ-\d+', ['docs/spec.md'])
        self.assertEqual(checked, 0); self.assertIn('examined nothing', problems[0])


if __name__ == '__main__':
    unittest.main()
