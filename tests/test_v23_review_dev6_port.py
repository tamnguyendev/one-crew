"""OneCrew 2.3: the four findings of the independent review (29/10, D:/OneCrewRuns/v23/review-dev6/review-p2b.md) of the doc verifier fixes taken
for the Codex dev5 review P2-C and P2-D (b32ae19): R9 and R13 (citations side by side), R10 (a kept file read through its 8.3 short name) and R14
(a link or a junction under a kept name).

Citations, KeptLinks and ShortNames are the reviewer's probes (tests/test_v23_review_dev6_port_probes.py of the review worktree): bodies and expected
behaviour unchanged. One difference: d03 needs a volume that makes 8.3 names (NTFS with 8dot3 creation on; D: here makes none), so ShortNameVolume
looks for one by itself and skips, naming the reason, only when there is none. CitationsMore, KeptLinksMore and ShortNamesMore are this fix's own
cases for the rules behind the probes.
"""
import ctypes
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from onecrew.ledger import LedgerError
from onecrew.snapshots import Snapshots, safe_file
from onecrew.v2.verifiers import data, doc, port

SAMPLE = Path(__file__).resolve().parent / 'wf_rx1_fixture'
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
SECRET = 'API_KEY=do-not-read-me\n'


def say(tag, *values):
    print(f'\nPROBE {tag}:', *[v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)[:1500] for v in values], flush=True)


class Tree(unittest.TestCase):
    base = None

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=self.base); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'tree'
        shutil.copytree(SAMPLE, self.root)

    def reset(self):
        shutil.rmtree(self.root); shutil.copytree(SAMPLE, self.root)

    def edit(self, rel, old, new):
        path = self.root / rel
        text = path.read_text(encoding='utf-8')
        self.assertIn(old, text, 'the sample no longer contains ' + old)
        path.write_text(text.replace(old, new, 1), encoding='utf-8', newline='\n')

    def box(self):
        return port.Port(self.root, port.authority(None, 'test'), 'doc')

    def check(self, value=None):
        box = self.box()
        return doc.run(doc.validate_config(value or json.loads(json.dumps(GOOD)), 'test'), box), box

    def failing(self, report):
        return {c['id']: c['problems'] for c in report['checks'] if not c['ok']}

    def with_cite(self, cite):
        value = json.loads(json.dumps(GOOD))
        value['docs'][0]['sources']['cite'] = cite
        return value


# ---- R9, R13: citations side by side (P2-D) -------------------------------------------------------------------------------

class Citations(Tree):
    def test_d00_control_an_undefined_citation_next_to_a_defined_one_is_reported(self):
        self.edit('docs/guide.md', 'REQ-1 và REQ-2 [S1] [S2].', 'REQ-1 và REQ-2 [S1][S9].')
        report, _ = self.check()
        say('d00 failing', self.failing(report))
        self.assertTrue(any('S9' in p or 's9' in p for ps in self.failing(report).values() for p in ps), report)

    def test_d01_an_anchored_cite_pattern_does_not_hide_an_undefined_pair(self):
        r"""validate_config accepts any regex for `cite`; `^S\d+$` reads the source list (fullmatch) but finds no citation in the text
        (the pattern is embedded in \[(...)\]); since b32ae19 the links check also skips `[S1][S9]` (re.fullmatch accepts the anchors),
        so an undefined S9 is reported by neither check."""
        clean, _ = self.check(self.with_cite(r'^S\d+$'))
        self.edit('docs/guide.md', 'REQ-1 và REQ-2 [S1] [S2].', 'REQ-1 và REQ-2 [S1][S9].')
        report, _ = self.check(self.with_cite(r'^S\d+$'))
        say('d01 clean', self.failing(clean), 'with [S1][S9]', self.failing(report))
        self.assertEqual(self.failing(clean), {})                                         # control: the sample passes with this pattern
        self.assertTrue(any('S9' in p or 's9' in p for ps in self.failing(report).values() for p in ps), report)

    def test_d02_a_padded_label_is_not_a_citation_and_stays_a_reference_link(self):
        """`[S1][ S9 ]`: the skip compares the STRIPPED label with the pattern, the citation regex needs `[S9]` exactly."""
        self.edit('docs/guide.md', 'REQ-1 và REQ-2 [S1] [S2].', 'REQ-1 và REQ-2 [S1][ S9 ].')
        report, _ = self.check()
        say('d02 failing', self.failing(report))
        self.assertTrue(any('S9' in p or 's9' in p for ps in self.failing(report).values() for p in ps), report)


class CitationsMore(Tree):
    """The rule behind d01 and d02: a bracket is a citation when the WHOLE label is accepted by `cite` (any valid pattern: anchored, flagged, with
    alternatives), and the links check skips `[a][b]` only when the sources check reads both brackets as citations of that very line. What one check
    does not read, the other still reports; a document without sources, a padded bracket or a one-sided pair keeps the Markdown rule."""

    PATTERNS = (r'S\d+', r'^S\d+$', 'S[0-9]+$', r'(?i)s\d+', r'S\d+|T\d+')

    def pair(self, text):
        self.edit('docs/guide.md', 'REQ-1 và REQ-2 [S1] [S2].', 'REQ-1 và REQ-2 ' + text + '.')

    def problems(self, cite):
        return [p for ps in self.failing(self.check(self.with_cite(cite))[0]).values() for p in ps]

    def links(self, cite):
        return self.failing(self.check(self.with_cite(cite))[0]).get('links', [])

    def test_e01_every_valid_pattern_reads_the_sample_and_two_defined_citations_side_by_side_alike(self):
        for cite in self.PATTERNS:
            with self.subTest(cite=cite):
                self.reset()
                self.assertEqual(self.problems(cite), [])                                   # the sample, citations spaced apart
                self.pair('[S1][S2]')
                self.assertEqual(self.problems(cite), [])                                   # two defined citations side by side
                self.reset(); self.pair('[S1][S2][S3]')
                self.assertEqual(self.problems(cite), [])

    def test_e02_an_undefined_citation_is_reported_whatever_the_pattern_and_the_neighbour(self):
        for cite in self.PATTERNS:
            for text in ('[S1][S9]', '[S9][S1]', '[S1] [S9]', '[S9]', '[S1][S2][S9]'):
                with self.subTest(cite=cite, text=text):
                    self.reset(); self.pair(text)
                    self.assertTrue(any('S9' in p or 's9' in p for p in self.problems(cite)), (cite, text, self.problems(cite)))

    def test_e03_a_real_missing_reference_link_is_still_reported_whatever_the_pattern(self):
        for cite in self.PATTERNS:
            for text, label in (('[S1][S2] và [đặc tả][khong-dinh-nghia]', 'khong-dinh-nghia'), ('[S1][khong-dinh-nghia]', 'khong-dinh-nghia'),
                                ('[khong-dinh-nghia][S1]', 's1')):
                with self.subTest(cite=cite, text=text):
                    self.reset(); self.pair(text)
                    links = self.links(cite)
                    self.assertTrue(any(f'reference [{label}] is used but never defined' in p for p in links), (cite, text, links))

    def test_e04_a_padded_bracket_is_never_a_citation_and_stays_a_reference_link(self):
        for cite in self.PATTERNS:
            for text, label in (('[S1][ S9 ]', 's9'), ('[ S1 ][S2]', 's2'), ('[S1][ S2 ]', 's2')):
                with self.subTest(cite=cite, text=text):
                    self.reset(); self.pair(text)
                    links = self.links(cite)
                    self.assertTrue(any(f'reference [{label}] is used but never defined' in p for p in links), (cite, text, links))

    def test_e05_a_document_without_sources_keeps_the_markdown_rule(self):
        self.edit('docs/design.md', '# ', '[S1][S2] mở đầu.\n\n# ')
        problems = self.failing(self.check()[0]).get('links', [])
        self.assertTrue(any('docs/design.md' in p and '[s2]' in p for p in problems), problems)

    def test_e06_design_note_a_pair_in_the_sources_section_is_not_read_by_the_sources_check_so_it_stays_a_reference_link(self):
        """The sources check reads the citations of the text OUTSIDE its section; a pair inside the section is nobody's citation, so the links check
        does not skip it (skipping it would leave an undefined `[S1][S9]` there reported by no check)."""
        self.edit('docs/guide.md', '— ghi chú phỏng vấn', '— ghi chú phỏng vấn, cùng với [S1][S3]')
        links = self.links(r'S\d+')
        self.assertTrue(any('reference [s3] is used but never defined' in p for p in links), links)


# ---- R14: a link or a junction under a kept name (P2-C) -------------------------------------------------------------------

class KeptLinks(Tree):
    def test_d04_a_junction_with_a_kept_name_that_leaves_the_checkout_still_stops_the_run(self):
        """Port.files() docstring: "A link or a junction still stops the run". withheld() judges the name only, so a junction named `.aws`
        that points outside the checkout is left out silently: a real scope violation reads like a kept file."""
        if os.name != 'nt': self.skipTest('junctions are a Windows feature')
        import _winapi
        outside = Path(self.temp.name) / 'outside-secrets'; outside.mkdir()
        (outside / 'credentials').write_text(SECRET, encoding='utf-8')
        _winapi.CreateJunction(str(outside), str(self.root / '.aws'))
        box = self.box()
        try:
            listing, stopped = box.files(), None
        except port.AdapterViolation as error:
            listing, stopped = None, str(error)
        exists = None
        if stopped is None:
            exists = {p: box.exists(p) for p in ('.aws', '.aws/credentials')}
        say('d04 files()', stopped or f'{len(listing)} files, no violation', 'exists', exists, 'violations', box._violations)
        self.assertIsNotNone(stopped)


class KeptLinksMore(Tree):
    """A link is refused for being a link, whatever its name or its target; a kept name that is a real file or folder is only left out."""

    def junction(self, name, target):
        if os.name != 'nt': self.skipTest('junctions are a Windows feature')
        import _winapi
        _winapi.CreateJunction(str(target), str(self.root / name))

    def symlink(self, name, target, folder=False):
        try:
            os.symlink(target, self.root / name, target_is_directory=folder)
        except (OSError, NotImplementedError):
            self.skipTest('this account cannot create a symbolic link')

    def secrets(self):
        outside = Path(self.temp.name) / 'outside-secrets'; outside.mkdir()
        (outside / 'credentials').write_text(SECRET, encoding='utf-8')
        return outside

    def test_e11_a_junction_with_a_kept_name_that_stays_inside_the_checkout_stops_the_run_and_is_recorded(self):
        self.junction('.aws', self.root / 'docs')
        box = self.box()
        with self.assertRaises(port.AdapterViolation) as caught: box.files()
        self.assertIn('link', str(caught.exception)); self.assertNotIn('outside the checkout', str(caught.exception))
        self.assertEqual([(v['op'], v['rule']) for v in box._violations], [('read', 'read_scope')])
        self.assertEqual(box._read, set())

    def test_e12_a_symbolic_link_with_a_kept_name_stops_the_run_for_a_folder_and_for_a_file(self):
        outside = self.secrets()
        self.symlink('.ssh', outside, folder=True)
        with self.assertRaises(port.AdapterViolation) as caught: self.box().files()
        self.assertIn('link', str(caught.exception))
        os.unlink(self.root / '.ssh')
        self.symlink('.env.example', outside / 'credentials')
        with self.assertRaises(port.AdapterViolation) as caught: self.box().files()
        self.assertIn('link', str(caught.exception))

    def test_e13_the_doc_adapter_and_exists_stop_on_it_and_nothing_is_read(self):
        self.junction('.aws', self.secrets())
        box = self.box()
        with self.assertRaises(port.AdapterViolation): doc.run(doc.validate_config(json.loads(json.dumps(GOOD)), 'test'), box)
        self.assertEqual(box._read, set())
        with self.assertRaises(port.AdapterViolation): self.box().exists('.aws')
        with self.assertRaises(port.AdapterViolation): self.box().read_text('.aws/credentials')

    def test_e14_control_a_real_kept_folder_and_file_are_left_out_without_a_violation(self):
        for rel in ('.aws/credentials', '.ssh/config', '.env.example'):
            path = self.root / rel; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(SECRET, encoding='utf-8')
        box = self.box()
        listing = box.files()
        self.assertIn('docs/guide.md', listing)
        self.assertFalse([f for f in listing if f.startswith(('.aws', '.ssh', '.env'))], listing)
        self.assertEqual(box._violations, [])
        self.assertTrue(box.exists('.aws') and box.exists('.env.example'))


# ---- R10: a kept file read through its 8.3 short name (P2-C) --------------------------------------------------------------

def short_name(path):
    """The 8.3 alias Windows gave `path`, or None."""
    if os.name != 'nt': return None
    buffer = ctypes.create_unicode_buffer(1024)
    if not ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, 1024): return None
    alias = Path(buffer.value).name
    return alias if alias.lower() != Path(path).name.lower() else None


def short_path(root, rel):
    """`rel` (posix, below `root`) with every component written as its 8.3 alias, or None when the volume made none."""
    if os.name != 'nt': return None
    whole, top = ctypes.create_unicode_buffer(2048), ctypes.create_unicode_buffer(2048)
    if not ctypes.windll.kernel32.GetShortPathNameW(str(Path(root) / rel), whole, 2048): return None
    if not ctypes.windll.kernel32.GetShortPathNameW(str(root), top, 2048): return None
    try:
        return Path(whole.value).relative_to(Path(top.value)).as_posix()
    except ValueError:
        return None


_VOLUME = []


def short_name_volume():
    """A folder on a volume that makes 8.3 names, or None. The verifier checkout is made in the system temp folder (C: here, NTFS with 8dot3
    creation on); the gate points TEMP at D:, which makes none, so the candidates are tried in turn: PROBE_SHORTNAME_DIR, the temp folder, then
    %LOCALAPPDATA%/Temp."""
    if _VOLUME: return _VOLUME[0]
    found = None
    if os.name == 'nt':
        local = os.environ.get('LOCALAPPDATA')
        for candidate in (os.environ.get('PROBE_SHORTNAME_DIR'), tempfile.gettempdir(), local and os.path.join(local, 'Temp')):
            if not candidate or not os.path.isdir(candidate): continue
            try:
                with tempfile.TemporaryDirectory(dir=candidate) as probe:
                    (Path(probe) / '.env.example').write_text('x', encoding='utf-8')
                    if short_name(Path(probe) / '.env.example'): found = candidate
            except OSError:
                continue
            if found: break
    _VOLUME.append(found)
    return found


class ShortNameVolume(Tree):
    """The tree lives on a volume that makes 8.3 aliases; the test is skipped, with the reason, only when no such volume is reachable."""

    def setUp(self):
        self.base = short_name_volume()
        if self.base is None:
            self.skipTest('no volume that makes 8.3 short names is reachable (not Windows, or NTFS 8dot3 creation is off for PROBE_SHORTNAME_DIR, '
                          'the temp folder and %LOCALAPPDATA%/Temp)')
        super().setUp()

    def plant(self, *names):
        for rel in names:
            path = self.root / rel; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(SECRET, encoding='utf-8')


class ShortNames(ShortNameVolume):
    def test_d03_a_kept_file_is_not_read_through_its_8dot3_alias(self):
        (self.root / '.env.example').write_text(SECRET, encoding='utf-8')
        alias = short_name(self.root / '.env.example')
        if alias is None: self.skipTest('no 8.3 alias on this volume (set PROBE_SHORTNAME_DIR to a folder on a volume that makes them)')
        box = self.box()
        try:
            text, refused = box.read_text(alias), None
        except port.AdapterViolation as error:
            text, refused = None, str(error)
        config = dict(json.loads(json.dumps({'path': alias, 'format': 'csv', 'columns': {'API_KEY': 'string'}, 'key': ['API_KEY']})))
        try:
            data.validate_config(config, 'test'); accepted = True
        except Exception as error:
            accepted = f'{type(error).__name__}: {error}'
        say('d03 alias', alias, 'read_text ->', refused or text, 'files_read', sorted(box._read), 'data config with the alias accepted:', accepted)
        self.assertIsNotNone(refused)
        self.assertNotIn(SECRET.strip(), text or '')


class ShortNamesMore(ShortNameVolume):
    """A protected file is never read, under any name: refused by what the name reaches on disk, not by how the name looks."""

    KEPT = ('.aws/credentials', '.git/config', '.ssh/config', '.env.example', 'infra/.env.secrets.example', '.onecrew/state.json')

    def test_e21_every_protected_file_is_refused_through_its_short_names(self):
        self.plant(*self.KEPT)
        for rel in self.KEPT:
            parts = rel.split('/')
            forms = {short_path(self.root, rel)}                                            # every component as its alias: AWS~1/CREDEN~1
            if len(parts) > 1:
                forms.add(short_path(self.root, parts[0]) + '/' + '/'.join(parts[1:]))      # the folder as its alias, the file by its long name
            forms.discard(rel)
            self.assertTrue(forms, 'the volume made no short name for ' + rel)
            for form in sorted(forms):
                with self.subTest(rel=rel, form=form):
                    box = self.box()
                    with self.assertRaises(port.AdapterViolation) as caught: box.read_text(form)
                    self.assertEqual((caught.exception.op, caught.exception.rule), ('read', 'read_scope'))
                    self.assertIn('control or credential path', str(caught.exception))
                    self.assertNotIn('outside the checkout', str(caught.exception))
                    self.assertEqual((box._read, len(box._violations)), (set(), 1))

    def test_e22_the_snapshot_rules_refuse_the_short_name_too(self):
        self.plant('.env.example', '.aws/credentials')
        for rel in ('.env.example', '.aws/credentials'):
            form = short_path(self.root, rel)
            with self.subTest(form=form):
                with self.assertRaises(LedgerError): safe_file(self.root, form)
                with self.assertRaises(LedgerError): Snapshots._working(self.root, [form])        # a worker snapshot would have carried the secret

    def test_e23_an_ordinary_file_is_still_read_by_its_short_name(self):
        (self.root / 'a-long-document-name.md').write_text('# Tên dài\n', encoding='utf-8', newline='\n')
        alias = short_name(self.root / 'a-long-document-name.md')
        self.assertTrue(alias, 'the volume made no short name for the ordinary file')
        box = self.box()
        self.assertEqual(box.read_text(alias), '# Tên dài\n')
        self.assertEqual(box._violations, [])

    def test_e24_the_data_adapter_given_a_short_name_reads_nothing_and_the_refusal_is_kept(self):
        """THE SETUP CHANGED ON PURPOSE, in 2.3 (fx, F2): validate_config used to accept the alias at propose, and this test ran the config it returned.
        It is now refused where it is proposed (tests/test_v23_open_verifier.py, ShortNamesAtPropose), so the stored form is written by hand: what a
        plan approved before the change can hold. What this proves is unchanged: the run reads nothing and the port keeps the refusal."""
        self.plant('.env.example')
        alias = short_name(self.root / '.env.example')
        module = port.get('data')
        box = port.Port(self.root, port.authority(None, 'test'), 'data')
        with self.assertRaises(LedgerError): module.validate_config({'path': alias, 'format': 'csv', 'columns': {'API_KEY': 'string'}, 'key': ['API_KEY']}, 'test')
        config = {'path': alias, 'format': 'csv', 'columns': {'API_KEY': 'string'}, 'key': ['API_KEY'], 'row_count': None, 'reconcile': None, 'samples': []}
        module.run(config, box)                                                           # the adapter may swallow the refusal; the port keeps it
        self.assertEqual(box._read, set())
        self.assertEqual([v['rule'] for v in box._violations], ['read_scope'])
        self.assertNotIn(SECRET.strip(), json.dumps(box._violations))

    def test_e25_listing_and_exists_never_show_a_short_name(self):
        self.plant('.env.example', '.aws/credentials')
        box = self.box()
        self.assertFalse([f for f in box.files() if '~' in f], box.files())
        self.assertTrue(box.exists('.env.example') and box.exists('.aws'))               # a kept name answers by name only
        self.assertEqual((box._read, box._violations), (set(), []))


if __name__ == '__main__':
    unittest.main()
