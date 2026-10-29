r"""OneCrew 2.3 (fx, 29/10): the four findings that the 2.3.0.dev6 review left open in the verifiers, closed together.

  F1  doc `ids.pattern` (review dev6 section 3; same class as R9): the pattern was placed inside larger regexes. An anchored pattern (`^REQ-\d+$`)
      then finds nothing, so an id used but never defined and an id defined twice are reported by no check, and a leading `(?i)` is a re.error at run.
  F2  data/ops (and doc) `validate_config`: a Windows short name (`ENV~1.EXA`) was accepted at propose and refused only when the run read it (R10).
  F3  `Port.read_text` (review E4): a kept file was read through a hard link to it (`docs/notes.txt` linked to `.env.example`).
  F4  `artifact.identity` (beta report D8): a folder without Git that holds `.env` had no identity at all.

Marks. A test whose name has no `control` is RED on 4bb41b3 (the code before this change) for the behaviour it names; a `control` test is today's
behaviour that must not change, so it is green on both. The run on 4bb41b3 is D:/OneCrewRuns/v23/dev7/logs/fx-red-4bb41b3.txt.
"""
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from onecrew.ledger import Ledger, LedgerError, content_hash
from onecrew.snapshots import Snapshots, bytes_hash
from onecrew.v2 import plan, verdict
from onecrew.v2.verifiers import artifact, data, doc, ops, port

from tests import test_wf_rx2_adapters as rx2                   # the module, not its classes: unittest would collect those here a second time
from tests.test_v23_review_dev6_port import ShortNameVolume, short_name

SAMPLE = Path(__file__).resolve().parent / 'wf_rx1_fixture'
SECRET = 'API_KEY=do-not-read-me\n'
TABLE = 'id,amount,active\n1,0.1,true\n2,0.2,false\n'
GOOD = {
    'docs': [
        {'path': 'docs/guide.md', 'headings': ['Tổng quan', 'Cài đặt', 'Nguồn'],
         'tables': [{'under': 'Cài đặt', 'columns': ['Bước', 'Lệnh']}],
         'sources': {'section': 'Nguồn', 'min': 1, 'cite': r'S\d+', 'external': 'unverified'}},
        {'path': 'docs/design.md', 'headings': ['Kiến trúc']},
    ],
    'links': True,
    'ids': [{'name': 'REQ', 'pattern': r'REQ-\d+', 'defined_in': ['docs/design.md']}],
}
OPS = {'pre': 'pre.json', 'post': 'post.json', 'receipt': 'operation.json', 'reconcile': 'observation.json', 'operation_id': 'op-1',
       'request_sha': 'a' * 64, 'preconditions': [{'path': ['version'], 'equals': 1}], 'postconditions': [{'path': ['version'], 'equals': 2}]}
DATA = {'path': 'output.csv', 'columns': {'id': 'integer', 'amount': 'number', 'active': 'boolean'}, 'key': ['id']}


def config(pattern=None, **changes):
    value = json.loads(json.dumps(GOOD))
    if pattern is not None: value['ids'][0]['pattern'] = pattern
    value.update(changes)
    return value


def link(source, target):
    """A hard link, or a skip with the reason when this volume or account cannot make one."""
    try:
        os.link(source, target)
    except (OSError, NotImplementedError, AttributeError) as error:
        raise unittest.SkipTest(f'this volume or account cannot make a hard link: {error}')


class Tree(unittest.TestCase):
    """A scratch copy of the sample documents of tests/wf_rx1_fixture (the same ones the RX1 and R15 tests read)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'tree'
        shutil.copytree(SAMPLE, self.root)

    def reset(self):
        shutil.rmtree(self.root); shutil.copytree(SAMPLE, self.root)

    def edit(self, rel, old, new):
        path = self.root / rel
        text = path.read_text(encoding='utf-8')
        self.assertIn(old, text, 'the sample no longer contains ' + old)
        path.write_text(text.replace(old, new, 1), encoding='utf-8', newline='\n')

    def plant(self, *names):
        for rel in names:
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(SECRET, encoding='utf-8')

    def box(self):
        return port.Port(self.root, port.authority(None, 'test'), 'doc')

    def check(self, value=None, box=None):
        box = box or self.box()
        return doc.run(doc.validate_config(value or config(), 'test'), box), box

    def failing(self, report):
        return {c['id']: c['problems'] for c in report['checks'] if not c['ok']}


# ---- F1: the pattern of an `ids` check -------------------------------------------------------------------------------------

PLAIN = (r'REQ-\d+', r'\bREQ-\d+\b', r'(REQ)-(\d+)', r'(?:REQ|NFR)-\d+', r'[A-Z]{3}-\d+', r'REQ-[0-9]+',
         r'(?x: REQ - \d+ )', r'(?x:REQ-\d+)', r'(?-x:REQ-\d+)')                  # the last three: a verbose group with nothing to rewrite worked on 4bb41b3 and still does
ANCHORED = (r'^REQ-\d+$', r'^REQ-\d+', r'REQ-\d+$', r'\AREQ-\d+\Z', r'^(?:REQ)-\d+$', r'^(REQ)-(\d+)$', r'^REQ-\d+$|^NFR-\d+$', r'^(?:REQ|NFR)-\d+$',
            r'(?i)req-\d+', r'(?i)^req-\d+$', r'(?m)^REQ-\d+$', r'(?s)^REQ-\d+$', r'(?i)(?s)req-\d+', r'(?a)^REQ-\d+$',
            '(?x) ^ REQ - \\d+ $ # an id, whole\n', '(?x) ^ REQ - \\d+ $ # a [class ^ opener and a $ in a comment\n', r'(?:^|\b)REQ-\d+(?:$|\b)',
            r'^\s*REQ-\d+', r'^[ \t]*REQ-\d+$', r'^\s*(?:REQ|NFR)-\d+\s*$',           # these three take a space along with the id: the name is the id
            r'(?x)(?-x:#)?REQ-\d+ $', '(?x:REQ-\\d+ # [x and a $ in a comment\n)$', '(?x: ^ REQ - \\d+ $ # whole\n)')       # verbose switched on and off inside the pattern
# an anchor inside a NEGATIVE assertion: it keeps the meaning it had (4bb41b3 found ids with these, and these only), so they are plain patterns too
NEGATED = (r'(?<!^)REQ-\d+', r'REQ-\d+(?!$)', r'(?<!\A)REQ-\d+', r'REQ-\d+(?!\Z)', r'(?<!^)\bREQ-\d+\b', r'(?<!(?<!x)^)REQ-\d+')
# written with an anchor or a flag in them, but not anchors: an escaped caret or dollar, a class, a comment. These are plain patterns.
LOOKS_ANCHORED = (r'REQ\$\d+', r'REQ\^\d+', r'REQ[$^-]\d+', r'(?<!\^)REQ-\d+', r'[^\s]REQ-\d+', r'REQ-\d+(?#the ^ and $ here are words)', r'REQ-\d+[^a-z]?',
                  r'REQ-\d+(?#\)$)', r'REQ-\d+(?#ends with a backslash \\)') + NEGATED


def old_check_ids(spec, folder, names):
    """_check_ids of 4bb41b3, verbatim: the reference for 'an unanchored pattern keeps today's results exactly'."""
    pattern = spec['pattern']
    wrapped = r'(?<![\w-])(?:' + pattern + r')(?![\w-])'
    start = re.compile(r'^\s*(?:#{1,6}[ \t]+|[-*+][ \t]+|\d+[.)][ \t]+|\|[ \t]*)[\[\*_`(]*(' + pattern + r')(?![\w-])')
    use = re.compile(wrapped)
    problems, defined, where_ = [], {}, spec['defined_in'] or names
    for path in where_:
        if path not in folder.files:
            problems.append(f'{spec["name"]}: definition file {path} is not in the artifact')
            continue
        parsed = folder.load(path, required=path in names)
        if parsed is None: continue
        for number, text in parsed.body_lines():
            match = start.match(text)
            if match: defined.setdefault(match.group(1), []).append(f'{path}:{number}')
    for name, spots in sorted(defined.items()):
        if len(spots) > 1: problems.append(f'{spec["name"]}: {name} is defined twice ({", ".join(spots)})')
    used = {}
    for path in names:
        parsed = folder.parsed.get(path)
        if parsed is None: continue
        for number, text in parsed.body_lines():
            head = start.match(text)
            for match in use.finditer(text):
                if head and match.start() == head.start(1) and path in where_: continue
                used.setdefault(match.group(0), f'{path}:{number}')
    for name, spot in sorted(used.items()):
        if name not in defined: problems.append(f'{spot}: {name} is used but never defined ({spec["name"]})')
    return problems, len(defined) + len(used)


TRICKY = '''# Spec

## REQ-1 first
- REQ-2 second
* **REQ-3** third
+ [REQ-4] fourth
1. (REQ-5) fifth
2) `REQ-6` sixth
| REQ-7 | table |
|---|---|
| NFR-1 | row |

Text mentions REQ-1, REQ-2. and (REQ-8) and **REQ-9**, XREQ-10, REQ-11x, REQ-12-1, REQ_13, REQ-14.5, #12 and #13 and [REQ-15].
Prices REQ$1 and REQ^2 and REQ-3a and REQ-3 b.
### REQ-1 duplicate
- _REQ-16_ italic
 - REQ-17 indented list
- REQ-18
- _REQ-19 emphasis opened and never closed

```
- REQ-99 inside a block
```
'''


class IdsPatterns(Tree):
    def ids(self, pattern):
        return self.failing(self.check(config(pattern))[0]).get('ids', [])

    def test_f1_control_the_stored_pattern_is_the_one_written(self):
        for pattern in PLAIN + ANCHORED + LOOKS_ANCHORED:
            with self.subTest(pattern=pattern):
                self.assertEqual(doc.validate_config(config(pattern), 'test')['ids'][0]['pattern'], pattern)      # the stored contract (and its hash) does not change

    def test_f1a_every_pattern_reads_the_sample_and_examines_the_ids_in_it(self):
        reference = next(c['checked'] for c in self.check(config(PLAIN[0]))[0]['checks'] if c['id'] == 'ids')
        self.assertGreater(reference, 0)                                                 # REQ-1 and REQ-2: two definitions and two uses
        for pattern in PLAIN + ANCHORED:
            with self.subTest(pattern=pattern):
                report, _ = self.check(config(pattern))
                self.assertEqual(self.failing(report), {})
                self.assertEqual(next(c['checked'] for c in report['checks'] if c['id'] == 'ids'), reference)     # a check that examined nothing proves nothing

    def test_f1b_an_id_used_but_never_defined_is_reported_with_every_pattern(self):
        self.edit('docs/guide.md', 'REQ-1 và REQ-2', 'REQ-1 và REQ-3')
        for pattern in PLAIN + ANCHORED:
            with self.subTest(pattern=pattern):
                problems = self.ids(pattern)
                self.assertTrue(any('REQ-3' in p and 'never defined' in p for p in problems), problems)

    def test_f1c_an_id_defined_twice_is_reported_with_every_pattern(self):
        self.edit('docs/design.md', '### REQ-2 Kiểm được sau khi cài', '### REQ-1 Kiểm được sau khi cài')
        for pattern in PLAIN + ANCHORED:
            with self.subTest(pattern=pattern):
                problems = self.ids(pattern)
                self.assertTrue(any('REQ-1' in p and 'defined twice' in p for p in problems), problems)

    def test_f1d_a_definition_in_a_list_item_and_in_a_table_row_counts_too(self):
        (self.root / 'docs' / 'defs.md').write_text('# Định nghĩa\n\n- REQ-7 một\n\n| Mã | Ý |\n|---|---|\n| REQ-7 | hai |\n', encoding='utf-8', newline='\n')
        for pattern in PLAIN + ANCHORED:
            with self.subTest(pattern=pattern):
                value = config(pattern, docs=GOOD['docs'] + ['docs/defs.md'])
                value['ids'][0]['defined_in'] = ['docs/design.md', 'docs/defs.md']
                problems = self.failing(self.check(value)[0]).get('ids', [])
                self.assertTrue(any('REQ-7' in p and 'defined twice' in p for p in problems), problems)

    def test_f1e_a_longer_or_prefixed_token_is_not_an_id_with_any_pattern(self):
        self.edit('docs/guide.md', 'REQ-1 và REQ-2', 'REQ-1 và REQ-2 và XREQ-9 và REQ-2x và REQ-2-1 và REQ_5')
        for pattern in PLAIN + ANCHORED:
            with self.subTest(pattern=pattern):
                self.assertEqual(self.ids(pattern), [])

    def test_f1_control_unanchored_patterns_give_the_results_of_the_old_search(self):
        (self.root / 'docs' / 'tricky.md').write_text(TRICKY, encoding='utf-8', newline='\n')
        patterns = PLAIN + LOOKS_ANCHORED + (r'REQ-\d+(?:\.\d+)?', r'#\d+', r'\[REQ-\d+\]', r'T\d+', r'(?P<p>REQ)-\d+', r'(?P<c>[A-Z])(?P=c)-\d+',
                                             r'\*\*REQ-\d+\*\*', r'REQ-\d+\.?', r'(?:REQ)-(\d)+', r'REQ-(?:1|2|3)')
        for pattern in patterns:
            for defined_in in (['docs/design.md'], ['docs/tricky.md'], ['docs/design.md', 'docs/tricky.md'], []):
                with self.subTest(pattern=pattern, defined_in=defined_in):
                    value = config(pattern, docs=GOOD['docs'] + ['docs/tricky.md'])
                    value['ids'][0]['defined_in'] = defined_in
                    spec = doc.validate_config(value, 'test')['ids'][0]
                    names = ['docs/guide.md', 'docs/design.md', 'docs/tricky.md']
                    folder = doc.Folder(self.box())
                    for name in names: folder.load(name, required=True)
                    self.assertEqual(doc._check_ids(spec, folder, names), old_check_ids(spec, folder, names))

    def test_f1i_an_anchor_or_a_global_flag_at_the_edge_of_a_pattern_changes_nothing(self):
        """Written with edge anchors or a flag that does not change what matches, a pattern gives exactly the problems of the same pattern without them,
        on every shape of line (a definition after a marker, a leading underscore, a table row, a fenced block)."""
        (self.root / 'docs' / 'tricky.md').write_text(TRICKY, encoding='utf-8', newline='\n')
        decorations = (lambda p: '^' + p + '$', lambda p: '^' + p, lambda p: p + '$', lambda p: r'\A' + p + r'\Z', lambda p: '(?s)' + p, lambda p: '(?m)^' + p + '$',
                       lambda p: '^(?:' + p + ')$', lambda p: '(?u)' + p, lambda p: '(?s)(?m)' + p)
        for pattern in PLAIN:
            for defined_in in (['docs/design.md'], ['docs/tricky.md'], ['docs/design.md', 'docs/tricky.md'], []):
                value = config(pattern, docs=GOOD['docs'] + ['docs/tricky.md'])
                value['ids'][0]['defined_in'] = defined_in
                names = ['docs/guide.md', 'docs/design.md', 'docs/tricky.md']
                folder = doc.Folder(self.box())
                for name in names: folder.load(name, required=True)
                plain = doc._check_ids(doc.validate_config(value, 'test')['ids'][0], folder, names)
                for number, decorate in enumerate(decorations):
                    with self.subTest(pattern=pattern, decoration=number, defined_in=defined_in):
                        value['ids'][0]['pattern'] = decorate(pattern)
                        self.assertEqual(doc._check_ids(doc.validate_config(value, 'test')['ids'][0], folder, names), plain)

    def test_f1_control_an_anchor_inside_a_negative_assertion_keeps_its_meaning_and_the_check_still_examines_ids(self):
        """`(?<!^)REQ-\\d+` (not at the start of a line) found ids on 4bb41b3 and reported the undefined one and the doubled one; it still does, with the same
        results. Read as 'the edge of the id', the anchor would contradict what the search requires and the check would pass with nothing examined."""
        for pattern in NEGATED:
            with self.subTest(pattern=pattern):
                self.reset()
                clean, _ = self.check(config(pattern))
                self.assertEqual(self.failing(clean), {})
                self.assertGreater(next(c['checked'] for c in clean['checks'] if c['id'] == 'ids'), 0)
                self.edit('docs/guide.md', 'REQ-1 và REQ-2', 'REQ-1 và REQ-3')
                self.assertTrue(any('REQ-3' in p and 'never defined' in p for p in self.ids(pattern)))
                self.reset()
                self.edit('docs/design.md', '### REQ-2 Kiểm được sau khi cài', '### REQ-1 Kiểm được sau khi cài')
                self.assertTrue(any('REQ-1' in p and 'defined twice' in p for p in self.ids(pattern)))

    def test_f1k_flags_after_the_start_are_refused_at_propose_with_the_way_out(self):
        for pattern in (r'(?#c)(?s)REQ-\d+', r'(?x) (?i)req-\d+'):
            with self.subTest(pattern=pattern):
                with self.assertRaises(LedgerError) as caught: doc.validate_config(config(pattern), 'test')
                self.assertIn('very start', str(caught.exception))

    def test_f1m_a_verbose_flag_switched_on_or_off_inside_the_pattern_is_followed(self):
        """`(?x)(?-x:#)?REQ-\\d+ $`: verbose, but the `#` of the optional group is a character; `(?x:..)` holds for its group only, and a comment in it
        can hold brackets and dollars. Read wrongly, the scan would take the rest of the pattern for a comment or a class and leave the `$` in place,
        and the check would pass with nothing examined."""
        (self.root / 'docs' / 'hash.md').write_text('# Mã\n\n- REQ-1 một\n\nXem #REQ-9 và REQ-1.\n', encoding='utf-8', newline='\n')
        value = config(r'(?x)(?-x:#)?REQ-\d+ $', docs=['docs/hash.md'])
        value['ids'][0]['defined_in'] = []
        problems = self.failing(self.check(value)[0]).get('ids', [])
        self.assertEqual(len(problems), 1, problems)
        self.assertRegex(problems[0], r'^docs/hash\.md:5: #REQ-9 is used but never defined \(REQ\)$')               # the `#` is part of the id it found
        for pattern in ('(?x:REQ-\\d+ # [x and a $ in a comment\n)$', '(?x: ^ REQ - \\d+ $ # whole\n)'):
            with self.subTest(pattern=pattern):
                value = config(pattern, docs=['docs/hash.md'])
                value['ids'][0]['defined_in'] = []
                problems = self.failing(self.check(value)[0]).get('ids', [])
                self.assertEqual(len(problems), 1, problems)
                self.assertRegex(problems[0], r'^docs/hash\.md:5: REQ-9 is used but never defined \(REQ\)$')

    def test_f1l_a_pattern_that_takes_the_space_along_with_the_id_names_the_id_without_it(self):
        self.edit('docs/guide.md', 'REQ-1 và REQ-2', 'REQ-1 và REQ-3')
        for pattern in (r'^\s*REQ-\d+', r'^[ \t]*REQ-\d+$', r'^\s*(?:REQ|NFR)-\d+\s*$'):
            with self.subTest(pattern=pattern):
                problems = self.ids(pattern)
                self.assertEqual(len(problems), 1, problems)
                self.assertRegex(problems[0], r'^docs/guide\.md:\d+: REQ-3 is used but never defined \(REQ\)$')

    def test_f1_control_a_named_reference_to_a_group_keeps_working(self):
        (self.root / 'docs' / 'pairs.md').write_text('# Mã\n\n- AA-1 một\n- BB-2 hai\n\nXem AA-1 và BB-2 và AB-3.\n', encoding='utf-8', newline='\n')
        value = config(r'(?P<c>[A-Z])(?P=c)-\d+', docs=['docs/pairs.md'])
        value['ids'][0]['defined_in'] = []
        self.assertEqual(self.failing(self.check(value)[0]), {})
        self.edit('docs/pairs.md', 'Xem AA-1', 'Xem CC-9 và AA-1')
        problems = self.failing(self.check(value)[0]).get('ids', [])
        self.assertTrue(any('CC-9' in p and 'never defined' in p for p in problems), problems)

    def test_f1f_a_pattern_that_cannot_be_placed_in_the_search_is_refused_at_propose(self):
        """A group referred to by number (`\\1`, `(?(1)..)`) means another group in the form used for definitions (one more group opens before it):
        refused with a clear message, never met first at run. A group referred to by name is fine (control above)."""
        for pattern in (r'(\d)\1-REQ', r'([A-Z])(\d)\2', r'(a)?(?(1)b|c)'):
            with self.subTest(pattern=pattern):
                with self.assertRaises(LedgerError) as caught: doc.validate_config(config(pattern), 'test')
                text = str(caught.exception)
                self.assertIn('pattern', text); self.assertIn('name', text)

    def test_f1g_a_stored_pattern_that_cannot_be_placed_is_a_problem_of_the_ids_check_not_an_exception(self):
        """A plan approved before the change can hold such a pattern: the run says so in the ids check, and the other checks still report."""
        stored = doc.validate_config(config(), 'test')
        stored['ids'][0]['pattern'] = r'(\d)\1'
        report = doc.run(stored, self.box())
        self.assertEqual([c['id'] for c in report['checks']], ['documents', 'structure', 'sources', 'links', 'ids'])
        problems = self.failing(report)
        self.assertEqual(list(problems), ['ids'])
        self.assertIn('pattern', problems['ids'][0])

    def test_f1h_a_pattern_the_regex_module_refuses_with_a_value_error_is_refused_as_the_others_are(self):
        with self.assertRaises(LedgerError): doc.validate_config(config(r'(?a)(?u)x'), 'test')

    def test_f1_control_a_bad_regular_expression_is_still_refused_at_propose(self):
        for pattern in ('(', '[', r'(?L)x', 'a' * 300, r'^*', r'a**', r'(?P<n>a)(?P=m)'):
            with self.subTest(pattern=pattern), self.assertRaises(LedgerError):
                doc.validate_config(config(pattern), 'test')


# ---- F2: a short name at propose ------------------------------------------------------------------------------------------

ALIASES = ('ENV~1.EXA', 'env~1.exa', 'Env~1.Exa', 'ENV~1', 'GIT~1', 'SSH~1', 'AWS~1', 'ONECRE~1', 'PROGRA~1', 'AB12CD~1.TXT', 'A~1', 'ENV~12.LOC', 'ABCDE~12.CSV',
           'infra/ENV~2.LOC', 'AWS~1/CREDEN~1', 'docs/ENV~1.EXA/x.csv', 'GIT~1/config', 'data~1.csv', 'report~1.csv',
           'ENV~~1', 'cfg/ENV~~1', 'ENV~OL~1', 'ENV~BA~1.CSV', '~$K_TK~1.DOC', '~$THIT~1.DOC', '~$PHUO~4.PPT')           # the last seven: a tilde of the long name in the first part
DOC_ALIASES = ('ENV~1.MD', 'env~1.md', 'GUIDE~1.MD', 'docs/GIT~1/README.md', 'AWS~1/CREDEN~1.MD', 'docs/ENV~2.LOC/x.md', 'report~1.md', 'docs/ENV~~1.MD', '~$THIT~1.MD')
LONG_NAMES = ('notes~1-final.csv', 'backup~2024.csv', 'report-2024.csv', 'a~b.csv', 'data~.csv', '~1.csv', 'ENVIRONMENT~1.EXA', 'ENV~1.EXAMPLE', 'ENV~1.EXA.bak',
              'file~12345678.csv', 'tilde~1.json', 'abcdef~12.csv', 'x~1y.csv', 'docs/~$report.csv', 'docs/one~two/three.csv', 'ENV~1x', 'TILDE~1-OLD', 'a ~1.csv',
              'a-long-document-name.csv', 'a,b~1.csv', 'a[1]~1.csv', '~$K_TKBTLV.docx', '~$report.docx', 'a~b~c.csv')
DOC_LONG_NAMES = ('notes~1-final.md', 'backup~2024.md', 'a~b.md', 'ENVIRONMENT~1.MD', 'docs/one~two/three.md', 'ABCDEF~12.MD', 'file~12345678.md',
                  'TILDE~1-OLD.md', 'README~1.EXAMPLE.md', 'GUIDE~1.MD.md', 'docs/~$report.md', 'a~b~c.md')


class ShortNamesAtPropose(unittest.TestCase):
    """A Windows short name is an alias the volume gives to a file whose long name is longer than 8.3 characters or starts with a dot (`.env.example`
    is `ENV~1.EXA`). Whether `ENV~1.EXA` stands for a kept file is known only to the disk of one volume, and a contract is read on others, where the
    alias differs or does not exist. So the form is refused where the contract is written, with the reason, and the file is named by its long name."""

    def assertRefused(self, call, name):
        with self.assertRaises(LedgerError) as caught: call()
        text = str(caught.exception)
        self.assertIn('short', text.lower(), name); self.assertIn('long name', text, name)
        self.assertIn(next(part for part in name.split('/') if '~' in part), text)           # it names the component

    def test_f2a_data_refuses_a_short_name_for_its_path_and_for_the_reconciliation_source(self):
        for alias in ALIASES:
            with self.subTest(alias=alias):
                self.assertRefused(lambda: data.validate_config(dict(DATA, path=alias), 'test'), alias)
                self.assertRefused(lambda: data.validate_config(dict(DATA, reconcile={'path': alias}), 'test'), alias)

    def test_f2b_ops_refuses_a_short_name_in_each_of_its_four_evidence_files(self):
        for alias in ALIASES:
            for field in ('pre', 'post', 'receipt', 'reconcile'):
                with self.subTest(alias=alias, field=field):
                    self.assertRefused(lambda: ops.validate_config(dict(OPS, **{field: alias}), 'test'), alias)

    def test_f2c_doc_refuses_a_short_name_for_a_document_and_for_a_definition_file(self):
        for name in DOC_ALIASES:
            with self.subTest(alias=name):
                self.assertRefused(lambda: doc.validate_config(config(docs=[name]), 'test'), name)
                value = config(); value['ids'][0]['defined_in'] = [name]
                self.assertRefused(lambda: doc.validate_config(value, 'test'), name)

    def test_f2d_the_refusal_comes_through_the_contract_form_a_milestone_is_proposed_with(self):
        for kind, value in (('data', dict(DATA, path='ENV~1.EXA')), ('ops', dict(OPS, pre='AWS~1/CREDEN~1')), ('doc', config(docs=['GIT~1/README.md']))):
            with self.subTest(kind=kind):
                with self.assertRaises(LedgerError) as caught: port.normalize(kind, value, 'milestone M1')
                self.assertIn('short', str(caught.exception).lower())

    def test_f2_control_long_names_that_only_look_like_a_short_name_are_accepted(self):
        for name in LONG_NAMES:
            with self.subTest(name=name):
                self.assertEqual(data.validate_config(dict(DATA, path=name), 'test')['path'], name)
                self.assertEqual(data.validate_config(dict(DATA, reconcile={'path': name}), 'test')['reconcile']['path'], name)
                self.assertEqual(ops.validate_config(dict(OPS, pre=name), 'test')['pre'], name)
        for name in DOC_LONG_NAMES:
            with self.subTest(name=name):
                self.assertEqual(doc.validate_config(config(docs=[name]), 'test')['docs'][0]['path'], name)

    def test_f2_control_the_old_refusals_stay_and_an_ordinary_path_is_accepted(self):
        for bad in ('.env-sample', '../out.csv', '/abs.csv', 'C:/abs.csv', 'a\\b.csv', 'output.csv.', '.git/config', 'a//b.csv', '', None, 7):
            with self.subTest(bad=bad), self.assertRaises(LedgerError): data.validate_config(dict(DATA, path=bad), 'test')
        self.assertEqual(data.validate_config(dict(DATA, path='out/output.csv'), 'test')['path'], 'out/output.csv')

    def test_f2e_the_shape_is_never_wider_than_the_rule_node_scopes_already_use(self):
        """internal_plan.SHORT_NAME (2.3-B Q6) refuses `[^~.]{1,6}~[0-9]{1,6}(.[^.]{1,3})?` in node scopes. A short name has at most 8 characters
        before the dot and none that no volume gives, so this rule leaves alone what cannot be an alias (`abcdef~12.csv`, `file~12345678.csv`,
        `a ~1.csv`) and never refuses what that rule accepts. It is wider in one way: its first part may hold a tilde of the long name, which real
        aliases have (the lock file ~$K_TKBTLV.docx is ~$K_TK~1.DOC on this machine) and the node rule misses."""
        from onecrew.v2 import internal_plan
        for name in ALIASES + DOC_ALIASES + LONG_NAMES + DOC_LONG_NAMES:
            for part in name.split('/'):
                with self.subTest(part=part):
                    if port.short_name_part(part) is not None:
                        self.assertTrue(internal_plan.SHORT_NAME.fullmatch(part) or '~' in part.rsplit('~', 1)[0], part)
        for part in ('ENV~1.EXA', 'GIT~1', 'PROGRA~1', 'ABCDE~12.CSV', 'A~1', 'AB12CD~1.TXT', 'env~1.exa', 'ENV~~1', '~$K_TK~1.DOC', '~$PHUO~4.PPT'):
            self.assertEqual(port.short_name_part(part), part)
        for part in ('abcdef~12.csv', 'file~12345678.csv', 'a ~1.csv', 'ENV~1.EXAMPLE', 'ENV~1.EXA.bak', 'ENV~1x', '~1.csv', 'a~b.csv', 'a~b~c.csv', '~$K_TKBTLV.docx'):
            self.assertIsNone(port.short_name_part(part))


class ShortNamesOfThisVolume(ShortNameVolume):
    """The aliases the volume really gave (the temp folder on C: here makes them; D: makes none), not the shapes the tests above write by hand."""

    def test_f2f_the_aliases_this_volume_gives_are_refused_and_the_long_names_are_accepted(self):
        self.plant('.env.example', 'infra/.env.secrets.example')
        (self.root / 'a-long-document-name.csv').write_text(TABLE, encoding='utf-8')
        for rel in ('.env.example', 'infra/.env.secrets.example', 'a-long-document-name.csv'):
            alias = short_name(self.root / rel)
            self.assertTrue(alias, 'the volume made no short name for ' + rel)
            with self.subTest(alias=alias):
                with self.assertRaises(LedgerError) as caught: data.validate_config(dict(DATA, path=alias), 'test')
                self.assertIn('short', str(caught.exception).lower())
        self.assertEqual(data.validate_config(dict(DATA, path='a-long-document-name.csv'), 'test')['path'], 'a-long-document-name.csv')


# ---- F3: a hard link to a kept file ---------------------------------------------------------------------------------------

KEPT_FILES = ('.env.example', 'infra/.env.secrets.example', '.aws/credentials', '.git/config', '.ssh/config', '.onecrew/state.json')


class HardLinks(Tree):
    def replace_with_a_link(self, rel, kept='.env.example'):
        self.plant(kept)
        (self.root / rel).unlink(missing_ok=True)
        link(self.root / kept, self.root / rel)

    def test_f3a_a_kept_file_is_not_read_through_a_hard_link_to_it(self):
        self.plant('.env.example')
        link(self.root / '.env.example', self.root / 'docs' / 'notes.txt')
        box = self.box()
        with self.assertRaises(port.AdapterViolation) as caught: box.read_text('docs/notes.txt')
        self.assertEqual((caught.exception.op, caught.exception.rule), ('read', 'read_scope'))
        self.assertIn('hard link', str(caught.exception)); self.assertNotIn(SECRET.strip(), str(caught.exception))
        self.assertNotIn('outside the checkout', str(caught.exception))
        self.assertEqual((box._read, [(v['op'], v['rule']) for v in box._violations]), (set(), [('read', 'read_scope')]))

    def test_f3b_every_kept_name_is_covered_whatever_folder_holds_it(self):
        self.plant(*KEPT_FILES)
        for number, rel in enumerate(KEPT_FILES):
            link(self.root / rel, self.root / 'docs' / f'copy-{number}.txt')
        for number, rel in enumerate(KEPT_FILES):
            with self.subTest(kept=rel):
                box = self.box()
                with self.assertRaises(port.AdapterViolation): box.read_text(f'docs/copy-{number}.txt')
                self.assertEqual(box._read, set())

    def test_f3c_the_rule_is_the_link_count_so_both_names_of_a_linked_pair_are_refused(self):
        link(self.root / 'docs' / 'guide.md', self.root / 'docs' / 'copy.md')
        for name in ('docs/guide.md', 'docs/copy.md'):
            with self.subTest(name=name):
                box = self.box()
                with self.assertRaises(port.AdapterViolation) as caught: box.read_text(name)
                self.assertIn('hard link', str(caught.exception))
                self.assertTrue(port.has_other_names(box, name))
        (self.root / 'docs' / 'copy.md').unlink()                                         # one name left: an ordinary file again
        box = self.box()
        self.assertFalse(port.has_other_names(box, 'docs/guide.md'))
        self.assertIn('Hướng dẫn', box.read_text('docs/guide.md'))

    def test_f3_control_the_surface_the_core_offers_an_adapter_is_the_pinned_one(self):
        """test_wf_rx1_core (T23) pins the public names of the Port; kept here so that this module says so too: the question is a function of the
        module (has_other_names(box, rel)), not a door added to the Port."""
        self.assertEqual({n for n in dir(port.Port) if not n.startswith('_')},
                         {'read_text', 'exists', 'files', 'run_command', 'retry', 'spend', 'close_finding', 'set_status', 'workspace', 'authority', 'adapter'})

    def test_f3l_asking_whether_a_file_has_another_name_records_nothing_and_a_refused_name_is_no_question(self):
        box = self.box()
        self.assertFalse(port.has_other_names(box, 'docs/guide.md'))
        for odd in ('../x', '.git/config', 'a\\b', 'docs/missing.md', '', None):
            self.assertFalse(port.has_other_names(box, odd))               # a name the port refuses when it is read is not a question for this one
        self.assertEqual((box._violations, box._read), ([], set()))

    def test_f3_control_the_presence_of_a_hard_link_does_not_stop_the_run_or_hide_the_other_files(self):
        self.plant('.env.example')
        link(self.root / '.env.example', self.root / 'docs' / 'notes.txt')
        box = self.box()
        listing = box.files()
        self.assertIn('docs/notes.txt', listing); self.assertIn('docs/guide.md', listing); self.assertNotIn('.env.example', listing)
        self.assertTrue(box.exists('docs/notes.txt'))
        self.assertEqual(box._violations, [])

    def test_f3_control_an_ordinary_file_has_one_name_and_is_read_as_before(self):
        box = self.box()
        self.assertIn('Hướng dẫn', box.read_text('docs/guide.md'))
        self.assertEqual((box._read, box._violations), ({'docs/guide.md'}, []))
        with self.assertRaises(FileNotFoundError): box.read_text('docs/missing.md')
        for bad in ('../x', '.git/config', 'a\\b'):
            with self.assertRaises(port.AdapterViolation): box.read_text(bad)

    def test_f3d_the_data_adapter_does_not_read_a_hard_linked_file_and_the_refusal_is_kept(self):
        self.plant('.env.example')
        link(self.root / '.env.example', self.root / 'docs' / 'linked.csv')
        module = port.get('data')
        box = port.Port(self.root, port.authority(None, 'test'), 'data')
        report = module.run(module.validate_config(dict(DATA, path='docs/linked.csv', columns={'API_KEY': 'string'}, key=['API_KEY']), 'test'), box)
        self.assertEqual(box._read, set())
        self.assertEqual([(v['op'], v['rule']) for v in box._violations], [('read', 'read_scope')])
        self.assertIn('hard link', box._violations[0]['detail'])
        self.assertFalse(report['checks'][0]['ok'])
        self.assertNotIn(SECRET.strip(), json.dumps(report, ensure_ascii=False) + json.dumps(box._violations))

    def test_f3e_the_doc_verifier_reports_a_hard_linked_source_as_not_verified_and_goes_on(self):
        self.replace_with_a_link('sources/spec.md')                                       # S1 names it with an anchor: [S1] ../sources/spec.md#phạm-vi
        report, box = self.check()
        self.assertEqual(self.failing(report), {})
        self.assertEqual(box._violations, [])
        self.assertNotIn('sources/spec.md', box._read)
        notes = [n for n in report['unverified'] if 'sources/spec.md' in n]
        self.assertTrue(notes and all('hard link' in n and 'not checked' in n for n in notes), report['unverified'])
        self.assertNotIn(SECRET.strip(), json.dumps(report, ensure_ascii=False))

    def test_f3f_the_doc_verifier_reports_a_hard_linked_link_target_as_not_verified(self):
        self.replace_with_a_link('docs/extra.md')
        self.edit('docs/guide.md', 'Tham khảo thêm [S3].', 'Tham khảo thêm [S3] và [phụ lục](extra.md#phu-luc).')
        report, box = self.check()
        self.assertEqual(self.failing(report), {})
        self.assertEqual(box._violations, [])
        self.assertNotIn('docs/extra.md', box._read)
        self.assertTrue(any('docs/extra.md' in n and 'hard link' in n for n in report['unverified']), report['unverified'])

    def test_f3g_a_hard_linked_required_document_is_a_problem_of_its_own_and_every_other_check_still_runs(self):
        """A declared document that cannot be read is not verified, so the milestone cannot pass: it is said in the documents check, with the reason.
        It is neither a refused act (the run goes on, nothing is recorded as a violation) nor an exception."""
        self.replace_with_a_link('docs/design.md')
        report, box = self.check()
        self.assertEqual(box._violations, [])
        self.assertNotIn('docs/design.md', box._read)
        self.assertEqual([c['id'] for c in report['checks']], ['documents', 'structure', 'sources', 'links', 'ids'])
        problems = self.failing(report)
        self.assertTrue(any('docs/design.md' in p and 'hard link' in p for p in problems['documents']), problems)
        self.assertTrue(any('definition file docs/design.md' in p and 'hard link' in p for p in problems['ids']), problems)
        self.assertFalse(any('never defined' in p for p in problems['ids']), 'the definitions were not read: nothing is said to be undefined')
        self.assertTrue(any('docs/design.md' in n and 'hard link' in n for n in report['unverified']), report['unverified'])      # the link to its anchor
        self.assertNotIn(SECRET.strip(), json.dumps(report, ensure_ascii=False))

    def test_f3i_a_hard_linked_document_is_said_in_the_ids_check_too_when_the_definitions_come_from_the_documents(self):
        self.replace_with_a_link('docs/design.md')
        value = config(); value['ids'][0]['defined_in'] = []                                 # the default: the documents themselves
        report, box = self.check(value)
        self.assertEqual(box._violations, [])
        problems = self.failing(report)
        self.assertTrue(any('definition file docs/design.md' in p and 'hard link' in p for p in problems['ids']), problems)
        self.assertFalse(any('never defined' in p for p in problems['ids']), 'the definitions were not read: nothing is said to be undefined')

    def test_f3h_a_hard_linked_definition_file_is_a_problem_of_the_ids_check(self):
        (self.root / 'docs' / 'defs.md').write_text('# Mã\n\n- REQ-1 một\n- REQ-2 hai\n', encoding='utf-8', newline='\n')
        self.replace_with_a_link('docs/defs.md')
        value = config(); value['ids'][0]['defined_in'] = ['docs/defs.md']
        report, box = self.check(value)
        self.assertEqual(box._violations, [])
        self.assertNotIn('docs/defs.md', box._read)
        problems = self.failing(report)
        self.assertTrue(any('definition file docs/defs.md' in p and 'hard link' in p for p in problems['ids']), problems)
        notes = [n for n in report['unverified'] if 'docs/defs.md' in n]
        self.assertEqual(len(notes), 1, report['unverified'])
        self.assertTrue('hard link' in notes[0] and 'not checked' in notes[0])

    def test_f3k_a_note_that_merely_contains_the_path_does_not_stand_for_the_note_of_the_file(self):
        """A web source whose address ends in the path of a hard-linked document is another note: the document still gets its own."""
        (self.root / 'docs' / 'a.md').write_text('# A\n', encoding='utf-8', newline='\n')
        self.edit('docs/guide.md', 'https://example.invalid/tham-khao', 'https://example.invalid/docs/a.md')
        self.replace_with_a_link('docs/a.md')
        report, _ = self.check(config(docs=GOOD['docs'] + ['docs/a.md']))
        own = [n for n in report['unverified'] if n.startswith('docs/a.md ')]
        self.assertEqual(len(own), 1, report['unverified'])
        self.assertTrue(any('example.invalid/docs/a.md' in n for n in report['unverified']))

    def test_f3j_a_hard_linked_document_that_no_link_points_to_is_listed_as_not_verified_once(self):
        """Whatever its role, a file that has another name is in `unverified` (once): here a declared document, no link or source names it."""
        (self.root / 'docs' / 'alone.md').write_text('# Một mình\n', encoding='utf-8', newline='\n')
        self.replace_with_a_link('docs/alone.md')
        report, box = self.check(config(docs=GOOD['docs'] + ['docs/alone.md']))
        self.assertEqual(box._violations, [])
        self.assertNotIn('docs/alone.md', box._read)
        self.assertEqual(list(self.failing(report)), ['documents'])
        notes = [n for n in report['unverified'] if 'docs/alone.md' in n]
        self.assertEqual(len(notes), 1, report['unverified'])
        self.assertTrue('hard link' in notes[0] and 'not checked' in notes[0])


# ---- F4: the identity of a folder without Git that holds a kept name -----------------------------------------------------

class NonGitKeptNames(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'source'
        (self.root / 'docs').mkdir(parents=True)
        (self.root / 'output.csv').write_text(TABLE, encoding='utf-8', newline='\n')
        (self.root / 'docs' / 'a.md').write_text('# A\n', encoding='utf-8', newline='\n')

    def plant(self, *names, text=SECRET):
        for rel in names:
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8', newline='\n')

    def manifest_hash(self, files, kept=None):
        """The identity as 4bb41b3 computes it for a folder without kept names, written out here independently of the code under test."""
        manifest = {'version': 1, 'parent': None, 'source': str(self.root.resolve()), 'head': None,
                    'files': {rel: {'working': bytes_hash((self.root / rel).read_bytes()), 'index': []} for rel in files}}
        if kept: manifest['kept'] = kept
        return content_hash(manifest)

    def reads(self, call):
        top, seen, original = self.root.resolve(), [], Path.read_bytes
        def spy(path):
            seen.append(path.relative_to(top).as_posix() if path.is_relative_to(top) else str(path))
            return original(path)
        with mock.patch.object(Path, 'read_bytes', spy):
            result = call()
        return result, seen

    def test_f4a_a_folder_that_holds_env_has_an_identity_and_the_env_file_is_never_read(self):
        self.plant('.env')
        identity, seen = self.reads(lambda: artifact.identity(self.root))
        self.assertRegex(identity, '^[0-9a-f]{64}$')
        self.assertEqual(sorted(set(seen)), ['docs/a.md', 'output.csv'])

    def test_f4b_the_identity_depends_on_the_names_left_out_and_never_on_their_content(self):
        self.plant('.env')
        first = artifact.identity(self.root)
        self.plant('.env', text='API_KEY=another-secret\n')
        self.assertEqual(artifact.identity(self.root), first)                              # content: not hashed
        self.plant('.env.local')
        second = artifact.identity(self.root)
        self.assertNotEqual(second, first)                                                 # a name left out is part of what the identity says
        (self.root / '.env').unlink(); (self.root / '.env.local').unlink()
        self.assertNotEqual(artifact.identity(self.root), first)                           # and a folder without any kept name is another artifact
        self.assertNotEqual(artifact.identity(self.root), second)
        (self.root / 'output.csv').write_text(TABLE + '3,0.3,true\n', encoding='utf-8', newline='\n')
        self.plant('.env')
        self.assertNotEqual(artifact.identity(self.root), first)                           # the other files are still part of it

    def test_f4c_the_identity_says_which_names_were_left_out_and_the_other_files_are_identified_as_before(self):
        self.plant('.env', '.aws/credentials', 'docs/.env.local', 'x/.git/config', 'x/y.txt')
        expected = self.manifest_hash(['docs/a.md', 'output.csv', 'x/y.txt'], kept=['.aws/', '.env', 'docs/.env.local', 'x/.git/'])      # a folder is named with its slash
        self.assertEqual(artifact.identity(self.root), expected)

    def test_f4_control_a_folder_without_kept_names_has_the_identity_it_always_had(self):
        self.assertEqual(artifact.identity(self.root), self.manifest_hash(['docs/a.md', 'output.csv']))
        names = ['docs/b.md', '.hidden/c.txt', '.github/d.yml', '.gitignore', 'env/e.txt', 'environment.txt']
        self.plant(*names)
        self.assertEqual(artifact.identity(self.root), self.manifest_hash(['docs/a.md', 'output.csv'] + names))

    def test_f4_control_a_onecrew_folder_is_still_skipped_without_a_word(self):
        before = artifact.identity(self.root)
        self.plant('.onecrew/state.json', 'x/.onecrew/y.json')
        self.assertEqual(artifact.identity(self.root), before)

    def test_f4d_capture_materializes_only_the_identified_files_and_the_snapshot_names_the_rest(self):
        self.plant('.env', '.aws/credentials', 'docs/.env.local')
        ledger = Ledger(self.root, self.base / 'state')
        scratch = Path(tempfile.mkdtemp(dir=self.temp.name))
        workspace, before, proof = artifact.capture(ledger, self.root, str(scratch))
        self.assertEqual(before, artifact.identity(self.root))
        self.assertEqual(sorted(p.relative_to(workspace).as_posix() for p in workspace.rglob('*') if p.is_file()), ['docs/a.md', 'output.csv'])
        manifest = Snapshots(ledger.state_root).load(proof['artifact_snapshot'])
        self.assertEqual(manifest['kept'], ['.aws/', '.env', 'docs/.env.local'])
        self.assertEqual(sorted(manifest['files']), ['docs/a.md', 'output.csv'])
        self.assertEqual(proof['artifact_kept'], ['.aws/', '.env', 'docs/.env.local'])
        self.assertEqual(proof['artifact_snapshot'], before)

    def test_f4_control_a_snapshot_without_kept_names_has_no_kept_entry(self):
        ledger = Ledger(self.root, self.base / 'state')
        scratch = Path(tempfile.mkdtemp(dir=self.temp.name))
        _, before, proof = artifact.capture(ledger, self.root, str(scratch))
        self.assertNotIn('kept', Snapshots(ledger.state_root).load(before))
        self.assertNotIn('artifact_kept', proof)

    def test_f4e_a_verifier_runs_on_a_folder_that_holds_env_and_never_sees_it(self):
        self.plant('.env', '.aws/credentials')
        ledger = Ledger(self.root, self.base / 'state')
        milestone = {'id': 'M1', 'title': 'Check output', 'max_repairs': 2, 'covers': ['O1'],
                     'verifier': {'type': 'data', 'config': port.normalize('data', dict(DATA, row_count=2), 'test')}}
        _, receipt = port.run(ledger, 'P1', 1, 'a' * 64, milestone, self.root)
        self.assertEqual(port.expected_result(receipt), 'pass', receipt['error'])
        self.assertEqual(receipt['files_read'], ['output.csv'])
        self.assertEqual(receipt['violations'], [])
        self.assertEqual(receipt['artifact_kept'], ['.aws/', '.env'])
        self.assertTrue(artifact.validate_evidence(ledger, receipt['artifact_sha'], receipt))
        self.assertNotIn(SECRET.strip(), json.dumps(receipt, ensure_ascii=False))

    def test_f4_control_a_link_or_a_junction_still_stops_whatever_its_name(self):
        outside = self.base / 'outside'; outside.mkdir()
        (outside / 'credentials').write_text(SECRET, encoding='utf-8')
        for name in ('.aws', '.env', 'docs/plain'):
            with self.subTest(name=name):
                target = self.root / name
                if name == '.aws':
                    if os.name != 'nt': self.skipTest('junctions are a Windows feature')
                    import _winapi
                    _winapi.CreateJunction(str(outside), str(target))
                else:
                    try:
                        os.symlink(outside / 'credentials', target)
                    except (OSError, NotImplementedError):
                        self.skipTest('this account cannot create a symbolic link')
                try:
                    with self.assertRaises(LedgerError) as caught: artifact.identity(self.root)
                    self.assertIn('links', str(caught.exception))
                finally:
                    if target.is_dir(): os.rmdir(target)
                    else: os.unlink(target)

    def test_f4_control_a_junction_alone_in_a_kept_folder_still_stops_the_run(self):
        """4bb41b3 walked the kept folder and met the junction; a kept folder is named only when it holds a file, so the look at it must not let this by."""
        if os.name != 'nt': self.skipTest('junctions are a Windows feature')
        import _winapi
        outside = self.base / 'outside'; outside.mkdir()
        (self.root / '.aws').mkdir()
        _winapi.CreateJunction(str(outside), str(self.root / '.aws' / 'link'))
        try:
            with self.assertRaises(LedgerError) as caught: artifact.identity(self.root)
            self.assertIn('links', str(caught.exception))
        finally:
            os.rmdir(self.root / '.aws' / 'link')

    def test_f4f_the_200_file_limit_is_the_one_there_was_and_counts_the_identified_files_only(self):
        for number in range(198): self.plant(f'many/f{number:03}.txt', text='x\n')       # 198 + the two files of setUp = 200
        self.assertRegex(artifact.identity(self.root), '^[0-9a-f]{64}$')
        self.plant('.env', '.env.local', 'docs/.env.x')                                    # not identified files: no part of the count
        self.assertRegex(artifact.identity(self.root), '^[0-9a-f]{64}$')
        self.plant('many/one-more.txt', text='x\n')
        with self.assertRaises(LedgerError) as caught: artifact.identity(self.root)
        self.assertIn('200', str(caught.exception))

    def test_f4h_kept_names_are_judged_as_the_snapshot_rules_judge_them_in_any_case(self):
        self.plant('.ENV', '.Env.Local', '.SSH/key', '.AWS/x', 'docs/.GIT/x', '.OneCrew/state.json', 'docs/.env', 'a/b.txt')         # (a `.GIT` at the root would make the folder a Git tree)
        expected = self.manifest_hash(['docs/a.md', 'output.csv', 'a/b.txt'], kept=['.AWS/', '.ENV', '.Env.Local', '.OneCrew/', '.SSH/', 'docs/.GIT/', 'docs/.env'])
        self.assertEqual(artifact.identity(self.root), expected)

    def test_f4i_more_than_200_kept_names_are_refused_with_their_own_reason(self):
        for number in range(201): self.plant(f'.env.{number}', text='x\n')
        with self.assertRaises(LedgerError) as caught: artifact.identity(self.root)
        self.assertIn('more than 200 control or credential names', str(caught.exception))

    def test_f4j_a_hard_link_to_a_kept_file_in_the_folder_is_refused_and_nothing_is_stored(self):
        """A content snapshot dissolves the hard links of the source folder, so docs/notes.csv would carry the secret of `.env` under an ordinary name:
        while the folder holds kept names, a file that has another name stops the identity (4bb41b3 refused every folder that held a kept name)."""
        for kept, ordinary in (('.env', 'docs/notes.csv'), ('.aws/credentials', 'docs/notes.csv'), ('docs/.env.local', 'output2.csv')):
            with self.subTest(kept=kept):
                self.plant(kept)
                try:
                    link(self.root / kept, self.root / ordinary)
                    with self.assertRaises(LedgerError) as caught: artifact.identity(self.root)
                    self.assertIn('hard link', str(caught.exception))
                    ledger = Ledger(self.root, self.base / 'state')
                    with self.assertRaises(LedgerError): artifact.capture(ledger, self.root, tempfile.mkdtemp(dir=self.temp.name))
                    stored = list((Path(ledger.state_root) / 'snapshots').rglob('*')) if (Path(ledger.state_root) / 'snapshots').exists() else []
                    self.assertEqual([p.name for p in stored if p.is_file() and SECRET.encode('utf-8') in p.read_bytes()], [])
                finally:                                                                   # whatever the outcome, the next case starts from a clean tree
                    for rel in (ordinary, kept): (self.root / rel).unlink(missing_ok=True)

    def test_f4_control_hard_links_in_a_folder_without_kept_names_are_identified_as_before(self):
        link(self.root / 'docs' / 'a.md', self.root / 'docs' / 'b.md')
        self.assertEqual(artifact.identity(self.root), self.manifest_hash(['docs/a.md', 'docs/b.md', 'output.csv']))

    def test_f4_control_a_kept_name_without_a_file_in_it_changes_nothing(self):
        """An empty `.ssh`, a nested `.git` with nothing in it: 4bb41b3 identified such a folder, so its identity stays what it was (a kept folder is
        named only when it holds a file)."""
        before = artifact.identity(self.root)
        for rel in ('.ssh', 'docs/.git', 'cfg/.env.d', '.aws/sub/deeper'): (self.root / rel).mkdir(parents=True)
        self.assertEqual(artifact.identity(self.root), before)

    def test_f4_control_a_onecrew_folder_inside_a_kept_folder_is_still_nothing_even_with_a_hard_link_in_the_folder(self):
        """`.onecrew` folders are skipped at any depth, as they always were: a kept folder that holds nothing else is not named, so it changes nothing
        (and does not bring the hard-link rule of the folders that hold kept names)."""
        self.plant('.aws/.onecrew/x.json')
        link(self.root / 'docs' / 'a.md', self.root / 'docs' / 'b.md')
        self.assertEqual(artifact.identity(self.root), self.manifest_hash(['docs/a.md', 'docs/b.md', 'output.csv']))

    def test_f4m_a_kept_folder_that_holds_a_file_is_named_even_deep_below(self):
        before = artifact.identity(self.root)
        self.plant('.aws/sub/deeper/credentials')
        self.assertNotEqual(artifact.identity(self.root), before)
        self.assertEqual(artifact._paths(self.root)[1], ['.aws/'])

    def test_f4_control_a_folder_that_holds_only_kept_names_has_no_identity_as_an_empty_folder_has_none(self):
        empty = self.base / 'empty'; empty.mkdir()
        with self.assertRaises(LedgerError): artifact.identity(empty)
        (empty / '.env').write_text(SECRET, encoding='utf-8')
        with self.assertRaises(LedgerError): artifact.identity(empty)


class NonGitKeptDocs(unittest.TestCase):
    """A folder without Git that holds `infra/.env.example` and `.aws/credentials`, and documents that link to them and cite one: as in a Git checkout
    (beta report B5, D1), a kept name that exists is 'not verified', never a broken link. The checkout of a folder without Git does not hold the kept
    names (they are left out of the artifact), so the port is told which ones, and answers for them by name."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'source'
        shutil.copytree(SAMPLE, self.root)
        for rel in ('infra/.env.example', '.aws/credentials'):
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text(SECRET, encoding='utf-8')
        guide = self.root / 'docs' / 'guide.md'
        text = guide.read_text(encoding='utf-8').replace('Tham khảo thêm [S3].', 'Tham khảo thêm [S3], [mẫu](../infra/.env.example) và [khóa](../.aws/credentials).')
        guide.write_text(text.rstrip('\n') + '\n- [S4] infra/.env.example — mẫu cấu hình\n', encoding='utf-8', newline='\n')

    def test_f4k_a_link_or_a_source_to_a_kept_name_is_not_verified_and_not_a_broken_link(self):
        ledger = Ledger(self.root, self.base / 'state')
        milestone = {'id': 'M1', 'title': 'Documents', 'max_repairs': 2, 'covers': ['O1'], 'verifier': {'type': 'doc', 'config': port.normalize('doc', config(), 'test')}}
        _, receipt = port.run(ledger, 'P1', 1, 'a' * 64, milestone, self.root)
        self.assertEqual(port.expected_result(receipt), 'pass', (receipt['error'], [c['problems'] for c in receipt['checks'] if not c['ok']]))
        self.assertEqual(receipt['violations'], [])
        self.assertEqual(receipt['artifact_kept'], ['.aws/', 'infra/.env.example'])
        notes = '\n'.join(receipt['unverified'])
        self.assertIn('source S4 infra/.env.example: infra/.env.example is a control or credential path', notes)         # the source and the link, as in a Git checkout
        self.assertIn('link ../infra/.env.example: infra/.env.example is a control or credential path', notes)
        self.assertIn('.aws/credentials is a control or credential path', notes)
        self.assertNotIn('does not exist', json.dumps(receipt['checks'])); self.assertNotIn('file not found', json.dumps(receipt['checks']))
        self.assertFalse([name for name in receipt['files_read'] if '.env' in name or '.aws' in name])
        said = [note for note in receipt['unverified'] if 'control or credential' in note]
        self.assertEqual(len(said), 3, receipt['unverified'])                                # the source S4, the link to the file, the link to .aws/credentials
        for note in said:                                                                    # a left-out file exists; below a left-out folder it cannot be told
            self.assertEqual('cannot be told' in note, '.aws/' in note, note)
            self.assertEqual('it exists, what it says is not checked' in note, '.aws/' not in note, note)

    def test_f4n_below_a_file_left_out_nothing_exists_and_below_a_folder_left_out_the_port_cannot_tell(self):
        """Below a FILE that was left out nothing can exist: a link there is a broken link, as in a checkout. Below a FOLDER that was left out the port
        cannot tell (the folder is not listed): the link is 'not verified'."""
        guide = self.root / 'docs' / 'guide.md'
        text = guide.read_text(encoding='utf-8').replace('[khóa](../.aws/credentials)', '[khóa](../.aws/credentials), [lạ](../.aws/config) và [hỏng](../infra/.env.example/inner.txt)')
        guide.write_text(text, encoding='utf-8', newline='\n')
        ledger = Ledger(self.root, self.base / 'state')
        milestone = {'id': 'M1', 'title': 'Documents', 'max_repairs': 2, 'covers': ['O1'], 'verifier': {'type': 'doc', 'config': port.normalize('doc', config(), 'test')}}
        _, receipt = port.run(ledger, 'P1', 1, 'a' * 64, milestone, self.root)
        problems = [p for check in receipt['checks'] for p in check['problems']]
        self.assertEqual(len(problems), 1, problems)
        self.assertIn('infra/.env.example/inner.txt', problems[0]); self.assertIn('does not exist', problems[0])
        notes = [note for note in receipt['unverified'] if '.aws/config' in note and 'control or credential' in note]
        self.assertEqual(len(notes), 1, receipt['unverified'])
        self.assertIn('whether it exists cannot be told', notes[0]); self.assertNotIn('it exists, what it says', notes[0])      # the note does not say it exists

    def test_f4_control_the_same_tree_in_a_git_checkout_answers_the_same(self):
        """The reference: the port over a directory that holds the kept names (what a Git checkout is) says the same of the same links."""
        box = port.Port(self.root, port.authority(None, 'test'), 'doc')
        report = doc.run(doc.validate_config(config(), 'test'), box)
        self.assertEqual({c['id']: c['problems'] for c in report['checks'] if not c['ok']}, {})
        self.assertTrue(any('.aws/credentials is a control or credential path' in n and 'it exists, what it says is not checked' in n for n in report['unverified']),
                        report['unverified'])                                                  # the checkout holds the file: it is said to exist


class KeptNamesLifecycle(rx2.NonGitLifecycle):
    """The lifecycle tests of the non-Git roots (tests/test_wf_rx2_adapters.py: propose, approve, `verdict run`, the pass that the live folder takes
    back when it changes, a forged receipt), inherited unchanged, on a folder that also holds `.env`, `.aws/credentials` and `docs/.env.local`. With the
    names left out of the identity (F4) every one of them holds; before, the first step (the identity) raised."""

    def setUp(self):
        super().setUp()
        for rel in ('.env', '.aws/credentials', 'docs/.env.local'):
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text(SECRET, encoding='utf-8', newline='\n')

    def test_f4g_the_secret_is_stored_nowhere_and_the_receipt_names_what_was_left_out(self):
        plan.propose(self.ledger, 'DATA', self.contract('data', rx2.DATA), 'codex-fixture')
        plan.approve(self.ledger, 'DATA', 'owner', 'fixture')
        out = verdict.run(self.ledger, 'DATA', 'M1')
        self.assertEqual(out['milestones'][0]['state'], 'passed')
        body = json.loads(Snapshots(self.ledger.state_root).read_blob(out['milestones'][0]['last_verdict']['receipt']))
        self.assertEqual(body['artifact_kept'], ['.aws/', '.env', 'docs/.env.local'])
        self.assertFalse([name for name in body['files_read'] if '.env' in name or '.aws' in name], body['files_read'])
        stored = [p for p in (Path(self.ledger.state_root) / 'snapshots').rglob('*') if p.is_file()]
        self.assertTrue(stored)
        self.assertEqual([p.name for p in stored if SECRET.encode('utf-8') in p.read_bytes()], [])      # not in a blob, not in a manifest, not in the receipt


if __name__ == '__main__':
    unittest.main()
