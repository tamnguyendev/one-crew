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
        self.refused(lambda: artifact.identity(self.root))

    def test_x09_control_a_tree_without_hard_links_keeps_its_identity(self):
        self.assertEqual(artifact.identity(self.root), command.artifact_sha(self.root))
        (self.root / 'docs' / 'extra.md').write_text('# Extra\n', encoding='utf-8', newline='\n')
        self.assertEqual(artifact.identity(self.root), command.artifact_sha(self.root))


class GitVerdictRunHardLink(unittest.TestCase):
    """x01 through the production path: propose, approve and `verdict run` a doc milestone on a Git project (no direct port call)."""

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
        link(root / '.env', root / 'docs' / 'notes.md')
        env = patch.dict(os.environ); env.start(); self.addCleanup(env.stop)
        for name in ('ONECREW_ACTOR', 'ONECREW_V2_REQUIRE_PLAN', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION'): os.environ.pop(name, None)
        os.environ['LOCALAPPDATA'] = str(base / 'lad'); os.environ['APPDATA'] = str(base / 'ad')
        ledger = Ledger(root, base / 'state')
        config = {'docs': ['docs/guide.md', 'docs/notes.md'], 'links': True,
                  'ids': [{'name': 'K', 'pattern': r'do-not-[a-z-]+', 'defined_in': ['docs/guide.md']}]}
        value = plan_json(milestones=[{'id': 'M1', 'title': 'Docs', 'max_repairs': 2, 'verifier': {'type': 'doc', 'config': config}, 'covers': ['O1']}])
        plans.propose(ledger, 'P1', value, 'claude'); plans.approve(ledger, 'P1', 'owner', 'probe fixture')
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


if __name__ == '__main__':
    unittest.main()
