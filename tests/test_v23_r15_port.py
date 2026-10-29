"""OneCrew 2.3: the doc verifier fixes taken from the beta R15 fix (wf-codex `e432be2`, 29/10) for the Codex dev5 review P2-C and P2-D.

P2-C (onecrew/v2/verifiers/port.py): a repository that holds `.env.example` stopped the doc verifier with AdapterViolation ("outside the
checkout") before any document was checked. P2-D (onecrew/v2/verifiers/doc.py): with a citation pattern, `[S1][S2]` was read as a
reference link `[s2]` that is never defined. Codex evidence: D:/OneCrewRuns/codex-dev5-handover-review-20261029/installed-verifier.json.

The classes B5PortTests, B5DocTests, B5OtherAdaptersTests, B5VerdictTests and B3CitationTests are copied unchanged from
tests/test_wf_r15_beta_signsdk.py at e432be2 (lines 33-262 and 411-432); the hook classes of that file (B6, B1, B2) and B4 belong to
fixes not taken into 2.3. CodexDev5Cases adds the two review cases on the same fixture (tests/wf_rx1_fixture).
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import LedgerError                              # noqa: E402
from onecrew.snapshots import Snapshots                             # noqa: E402
from onecrew.v2 import verdict                                      # noqa: E402
from onecrew.v2.verifiers import artifact, data, doc, ops, port     # noqa: E402

from tests.test_v2_l1 import Fixture, plan_json                     # noqa: E402

SAMPLE = Path(__file__).resolve().parent / 'wf_rx1_fixture'
GOOD = {
    'docs': [
        {'path': 'docs/guide.md', 'headings': ['Tổng quan', 'Cài đặt', 'Nguồn'],
         'tables': [{'under': 'Cài đặt', 'columns': ['Bước', 'Lệnh']}],
         'sources': {'section': 'Nguồn', 'min': 1, 'cite': 'S\\d+', 'external': 'unverified'}},
        {'path': 'docs/design.md', 'headings': ['Kiến trúc']},
    ],
    'links': True,
    'ids': [{'name': 'REQ', 'pattern': 'REQ-\\d+', 'defined_in': ['docs/design.md']}],
}
SECRET = 'API_KEY=do-not-read-me\n'
KEPT = ('.env-sample', 'infra/.env.secrets.example', '.ssh/config', '.aws/credentials')     # the files of the report, and two more kept names


def config(**changes):
    value = json.loads(json.dumps(GOOD))
    value.update(changes)
    return value


class Tree(unittest.TestCase):
    """A scratch copy of the sample documents of tests/wf_rx1_fixture (the same ones the RX1 tests read)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'tree'
        shutil.copytree(SAMPLE, self.root)

    def plant(self, names=KEPT):
        for rel in names:
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(SECRET, encoding='utf-8')

    def edit(self, rel, old, new):
        path = self.root / rel
        text = path.read_text(encoding='utf-8')
        self.assertIn(old, text, 'the sample no longer contains ' + old)
        path.write_text(text.replace(old, new, 1), encoding='utf-8', newline='\n')

    def box(self):
        return port.Port(self.root, port.authority(None, 'test'), 'doc')

    def check(self, value=None, box=None):
        box = box or self.box()
        return doc.run(doc.validate_config(value or config(), 'test'), box), box

    def failing(self, report):
        return {c['id']: c['problems'] for c in report['checks'] if not c['ok']}


# ---- B5: the doc verifier and the names kept from readers -----------------------------------------------------------------

class B5PortTests(Tree):
    def test_kept_names_are_left_out_of_the_listing_and_do_not_stop_the_run(self):
        self.plant()
        box = self.box()
        listing = box.files()                                                       # dev18: AdapterViolation read_scope on '.aws'
        self.assertFalse([f for f in listing if any(part.startswith(('.env', '.ssh', '.aws')) for part in f.split('/'))], listing)
        self.assertIn('docs/guide.md', listing)
        self.assertEqual(box._violations, [])

    def test_a_kept_file_is_still_never_read_and_the_refusal_names_the_real_reason(self):
        self.plant()
        box = self.box()
        for rel in KEPT:
            with self.subTest(rel=rel):
                with self.assertRaises(port.AdapterViolation) as caught: box.read_text(rel)
                self.assertEqual((caught.exception.op, caught.exception.rule), ('read', 'read_scope'))
                self.assertIn('control or credential path', str(caught.exception))
                self.assertNotIn('outside the checkout', str(caught.exception))
        self.assertEqual(box._read, set())
        self.assertEqual(len(box._violations), len(KEPT))                             # an adapter that tries is still recorded

    def test_paths_that_leave_the_checkout_are_still_refused_as_outside(self):
        box = self.box()
        for rel in ('../outside.txt', str(Path(sys.executable)), '/etc/passwd', 'C:/Windows/win.ini', 'docs/../../x.md'):
            with self.subTest(rel=rel):
                with self.assertRaises(port.AdapterViolation) as caught: box.read_text(rel)
                self.assertIn('outside the checkout', str(caught.exception))
                with self.assertRaises(port.AdapterViolation): box.exists(rel)

    def test_exists_answers_a_kept_name_by_name_only(self):
        self.plant()
        box = self.box()
        self.assertTrue(box.exists('.env-sample')); self.assertTrue(box.exists('infra/.env.secrets.example'))
        self.assertTrue(box.exists('.ssh')); self.assertTrue(box.exists('.ssh/config'))
        self.assertFalse(box.exists('.env.missing')); self.assertFalse(box.exists('infra/.env.other'))
        self.assertEqual((box._read, box._violations), (set(), []))

    def test_hypothesis_device_names_reserved_characters_and_long_paths_are_kept_not_fatal(self):
        """Names Windows cannot create here (a device name, a colon, a trailing dot) and a path over 240 characters: the listing of a POSIX
        checkout is simulated, every one of them is left out and the run goes on; a kept name that is a folder is not walked."""
        long_dir = 'deep/' + 'a' * 120 + '/' + 'b' * 120
        root = self.root.resolve()
        fake = [(base, list(dirs), list(names)) for base, dirs, names in os.walk(root)]
        top = fake[0]
        top[2].extend(['con.txt', 'AUX', 'a:b.md', 'trailing.', 'q?.md'])
        top[1].append('deep')
        fake.append((str(root / 'deep'), [], ['short.md']))
        fake.append((str(root / long_dir), [], ['x.md']))
        with patch.object(port.os, 'walk', return_value=iter(fake)):
            box = self.box()
            listing = box.files()
        self.assertIn('deep/short.md', listing)
        for name in ('con.txt', 'AUX', 'a:b.md', 'trailing.', 'q?.md', long_dir + '/x.md'):
            self.assertNotIn(name, listing)
        self.assertEqual(box._violations, [])
        with self.assertRaises(port.AdapterViolation) as caught: box.read_text('con.txt')
        self.assertIn('may not read', str(caught.exception)); self.assertNotIn('outside', str(caught.exception))
        with self.assertRaises(port.AdapterViolation) as caught: box.read_text(long_dir + '/x.md')
        self.assertIn('240', str(caught.exception))

    def test_a_link_or_junction_in_the_checkout_still_stops_the_run(self):
        target = Path(self.temp.name) / 'elsewhere'; target.mkdir()
        try:
            os.symlink(target, self.root / 'docs' / 'linked', target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('this account cannot create a symbolic link')
        with self.assertRaises(port.AdapterViolation) as caught: self.box().files()
        self.assertIn('link', str(caught.exception))


class B5DocTests(Tree):
    def test_the_report_case_tracked_env_files_change_nothing(self):
        clean, _ = self.check()
        self.plant()
        planted, box = self.check()                                                   # dev18: AdapterViolation from Folder.__init__
        self.assertEqual(planted, clean)
        self.assertEqual(self.failing(planted), {})
        self.assertFalse(any('.env' in f or '.ssh' in f or '.aws' in f for f in box._read), box._read)
        self.assertEqual(box._violations, [])

    def test_a_link_to_a_kept_file_that_exists_is_named_unverified_with_the_reason(self):
        self.plant()
        self.edit('docs/guide.md', 'Tham khảo thêm [S3].', 'Tham khảo thêm [S3]. Mẫu cấu hình: [mẫu](../.env-sample).')
        report, box = self.check()
        self.assertEqual(self.failing(report), {})
        notes = [u for u in report['unverified'] if '.env-sample' in u]
        self.assertEqual(len(notes), 1, report['unverified'])
        self.assertIn('control or credential path', notes[0]); self.assertIn('docs/guide.md:', notes[0])
        self.assertNotIn('.env-sample', box._read)

    def test_a_source_that_is_a_kept_file_is_named_unverified_and_a_missing_one_fails(self):
        self.plant()
        self.edit('docs/guide.md', '- [S3] https://', '- [S4] infra/.env.secrets.example — mẫu biến môi trường\n- [S3] https://')
        self.edit('docs/guide.md', 'Tham khảo thêm [S3].', 'Tham khảo thêm [S3] [S4].')
        report, _ = self.check()
        self.assertEqual(self.failing(report), {})
        self.assertTrue(any('S4' in u and 'infra/.env.secrets.example' in u and 'control or credential path' in u for u in report['unverified']), report['unverified'])
        self.edit('docs/guide.md', 'infra/.env.secrets.example', 'infra/.env.gone')
        report, _ = self.check()
        problems = self.failing(report).get('sources', [])
        self.assertEqual(len(problems), 1, problems)
        self.assertIn('infra/.env.gone', problems[0]); self.assertIn('not found', problems[0]); self.assertNotIn('outside', problems[0])

    def test_a_link_to_a_missing_kept_file_is_a_broken_link(self):
        self.edit('docs/guide.md', 'Tham khảo thêm [S3].', 'Tham khảo thêm [S3]. Mẫu: [mẫu](../.env-sample).')
        report, _ = self.check()
        problems = self.failing(report).get('links', [])
        self.assertEqual(len(problems), 1, report)
        self.assertIn('.env-sample', problems[0]); self.assertIn('does not exist', problems[0]); self.assertNotIn('outside the checkout', problems[0])

    def test_control_without_kept_files_the_report_is_the_rx1_one(self):
        report, box = self.check()
        self.assertEqual(self.failing(report), {})
        self.assertEqual([c['id'] for c in report['checks']], ['documents', 'structure', 'sources', 'links', 'ids'])
        self.assertEqual(box._violations, [])


class B5OtherAdaptersTests(unittest.TestCase):
    """data and ops read only the paths their config names (checked at propose by scoped_path), never the listing: a kept file in the checkout
    changes nothing for them, and a config that names one is refused at propose with the snapshot rule, not at run time."""

    def setUp(self):
        from tests.test_wf_rx2_adapters import DATA, OPS, TABLE, write_ops
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'source'; self.root.mkdir()
        for name in ('input.csv', 'output.csv'): (self.root / name).write_text(TABLE, encoding='utf-8')
        write_ops(self.root)
        (self.root / '.env-sample').write_text(SECRET, encoding='utf-8')
        self.configs = {'data': DATA, 'ops': OPS}

    def test_data_and_ops_pass_with_a_kept_file_beside_them(self):
        for kind, value in self.configs.items():
            with self.subTest(kind=kind):
                module = port.get(kind)
                box = port.Port(self.root, port.authority(None, 'test'), kind)
                report = module.run(module.validate_config(json.loads(json.dumps(value)), 'test'), box)
                self.assertTrue(all(c['ok'] for c in report['checks']), report)
                self.assertEqual(box._violations, [])

    def test_a_config_naming_a_kept_file_is_refused_at_propose(self):
        with self.assertRaises(LedgerError): data.validate_config(dict(self.configs['data'], path='.env-sample'), 'test')
        with self.assertRaises(LedgerError): ops.validate_config(dict(self.configs['ops'], pre='.env-sample'), 'test')
        with self.assertRaises(LedgerError): doc.validate_config(config(docs=['.env/notes.md']), 'test')

    def test_d8_a_folder_without_git_that_holds_env_has_an_artifact_identity_without_it(self):
        """D8 (dev19 contract) was a known limit that this test pinned (named test_known_limit_d8_...): the same rule refused a non-Git artifact whose
        folder holds `.env`, with 'Control or credential'. THE EXPECTATION CHANGED ON PURPOSE, in 2.3 (fx, F4): the kept names are left out of the
        identity as Port.files() leaves them out of a checkout (never read, never hashed) and the identity names them. The cases are in
        tests/test_v23_open_verifier.py (NonGitKeptNames); this keeps the one the R15 fixture gives (`.env-sample` beside the data and ops files)."""
        identity = artifact.identity(self.root)
        self.assertRegex(identity, '^[0-9a-f]{64}$')
        (self.root / '.env-sample').write_text('API_KEY=another-secret\n', encoding='utf-8')
        self.assertEqual(artifact.identity(self.root), identity)                      # the content of a kept file is not part of it
        (self.root / '.env-sample').unlink()
        self.assertNotEqual(artifact.identity(self.root), identity)                   # its name is


class B5VerdictTests(Fixture):
    """The real path of the report: a Git project that tracks `.env-sample` and `infra/.env.secrets.example`, `verdict run` on a doc
    milestone. dev18: inconclusive, error "'.env-sample' is outside the checkout ...", files_read empty."""

    def setUp(self):
        super().setUp()
        shutil.copytree(SAMPLE, self.root, dirs_exist_ok=True)
        for rel in ('.env-sample', 'infra/.env.secrets.example'):
            path = self.root / rel; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(SECRET, encoding='utf-8')
        self.git('add', '-f', '.'); self.git('commit', '-q', '-m', 'documents and env samples')
        self.assertIn('.env-sample', self.git('ls-files'))
        milestone = {'id': 'M1', 'title': 'Document M1', 'verifier': {'type': 'doc', 'config': config()}, 'covers': ['O1']}
        self.approved('P1', plan_json(milestones=[milestone]))

    def test_the_milestone_passes_and_the_env_files_are_not_read(self):
        view = verdict.run(self.ledger, 'P1', 'M1', self.root)
        row = view['milestones'][0]
        receipt = json.loads(Snapshots(self.ledger.state_root).read_blob(row['last_verdict']['receipt']).decode('utf-8'))
        self.assertEqual((receipt['error'], receipt['violations']), (None, []))
        self.assertEqual(row['state'], 'passed')
        self.assertIn('docs/guide.md', receipt['files_read'])
        self.assertFalse([f for f in receipt['files_read'] if '.env' in f])
        self.assertEqual(self.kinds().count('adapter.violation'), 0)


# ---- B3: two citations side by side ---------------------------------------------------------------------------------------

class B3CitationTests(Tree):
    def test_adjacent_citations_are_not_reference_links(self):
        self.edit('docs/guide.md', 'REQ-1 và REQ-2 [S1] [S2].', 'REQ-1 và REQ-2 [S1][S2].')
        report, _ = self.check()                                                  # dev18: links "reference [s2] is used but never defined"
        self.assertEqual(self.failing(report), {})
        self.assertIn('[S1][S2]', (self.root / 'docs' / 'guide.md').read_text(encoding='utf-8'))

    def test_a_real_undefined_reference_link_is_still_reported(self):
        self.edit('docs/guide.md', 'Tham khảo thêm [S3].', 'Tham khảo thêm [S3] và [bản đặc tả][spec-thieu].')
        problems = self.failing(self.check()[0]).get('links', [])
        self.assertEqual(len(problems), 1); self.assertIn('spec-thieu', problems[0])
        self.edit('docs/guide.md', '[bản đặc tả][spec-thieu]', '[S1][spec-thieu]')     # only one side is a citation: still a reference link
        self.assertIn('spec-thieu', ' '.join(self.failing(self.check()[0]).get('links', [])))

    def test_a_document_without_a_sources_section_keeps_the_markdown_rule(self):
        self.edit('docs/design.md', '# ', '[S1][S2] mở đầu.\n\n# ')
        problems = self.failing(self.check()[0]).get('links', [])
        self.assertTrue(any('docs/design.md' in p and '[s2]' in p for p in problems), problems)


# ---- the Codex dev5 review cases (P2-C, P2-D), on the same fixture ---------------------------------------------------------

class CodexDev5Cases(Tree):
    def test_p2c_a_root_env_example_does_not_stop_the_doc_verifier_and_is_never_read(self):
        clean, _ = self.check()
        (self.root / '.env.example').write_text('SAMPLE=not-secret' + chr(10), encoding='utf-8')
        report, box = self.check()                                                # dev5: AdapterViolation "'.env.example' is outside the checkout"
        self.assertEqual(report, clean)
        self.assertEqual(self.failing(report), {})
        self.assertEqual(box._violations, [])
        self.assertNotIn('.env.example', box._read)
        self.assertNotIn('not-secret', json.dumps(report, ensure_ascii=False))

    def test_p2c_reading_the_kept_file_is_still_refused_with_its_real_reason(self):
        (self.root / '.env.example').write_text('SAMPLE=not-secret' + chr(10), encoding='utf-8')
        with self.assertRaises(port.AdapterViolation) as caught: self.box().read_text('.env.example')
        self.assertIn('control or credential', str(caught.exception))
        self.assertNotIn('outside the checkout', str(caught.exception))

    def test_p2d_adjacent_citations_in_the_codex_text_are_two_citations(self):
        self.edit('docs/guide.md', 'REQ-1 và REQ-2 [S1] [S2].', 'REQ-1 và REQ-2 [S1][S2].')
        report, _ = self.check()                                                  # dev5: links "docs/guide.md:5: reference [s2] is used but never defined"
        self.assertEqual(self.failing(report), {})

    def test_p2d_a_missing_markdown_reference_link_next_to_a_citation_is_still_caught(self):
        self.edit('docs/guide.md', 'REQ-1 và REQ-2 [S1] [S2].', 'REQ-1 và REQ-2 [S1][S2] và [đặc tả][khong-dinh-nghia].')
        problems = self.failing(self.check()[0]).get('links', [])
        self.assertEqual(len(problems), 1, problems)
        self.assertIn('khong-dinh-nghia', problems[0])


if __name__ == '__main__':
    unittest.main()
