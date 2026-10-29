"""OneCrew 2.3 (dx, 30/10): a source written bare in the sources section (`- [S1] ../guide.md — ...`, the form the doc adapter documents) lost
its leading dots when the locator was read: `../x` and `./x` became `/x` (the root of the repository), `.github/x` became `github/x`, `.env.example`
became `env.example`. So a source one folder up or next to the document was "not found", a dotted folder or file was "not found", a kept name was
"not found" instead of "not verified", and a source one folder up that is missing PASSED when the root holds a file of that name (the root was
checked instead). Seen by the FX implementer (left untouched there), reproduced on 4f6a707; the cause is the strip of the token in doc._entries
(since 1b4f4c6, also in the 2.2 beta). Each test names the behaviour it expects; all but the controls are red on 4f6a707. No model is called.
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from onecrew.v2.verifiers import doc, port

SAMPLE = Path(__file__).resolve().parent / 'wf_rx1_fixture'
SECRET = 'API_KEY=do-not-read-me\n'
PAGE = 'docs/sub/page.md'
CONFIG = {'docs': [{'path': PAGE, 'headings': ['Nguồn'], 'sources': {'section': 'Nguồn', 'min': 1, 'cite': r'S\d+', 'external': 'unverified'}}],
          'links': False}


class BareLocators(unittest.TestCase):
    """A copy of tests/wf_rx1_fixture with one more document, docs/sub/page.md, whose only source is the line under test."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'tree'
        shutil.copytree(SAMPLE, self.root)

    def page(self, line, *plant):
        for rel in plant:
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(SECRET if Path(rel).name.startswith('.env') else 'x\n', encoding='utf-8')
        path = self.root / PAGE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('# Page\n\nText [S1].\n\n## Nguồn\n\n' + line + '\n', encoding='utf-8', newline='\n')
        box = port.Port(self.root, port.authority(None, 'test'), 'doc')
        report = doc.run(doc.validate_config(CONFIG, 'test'), box)
        return {c['id']: c['problems'] for c in report['checks'] if not c['ok']}, report, box

    def test_a_a_source_one_folder_up_is_the_file_one_folder_up(self):
        failing, _, _ = self.page('- [S1] ../guide.md — the guide one folder up')
        self.assertEqual(failing, {})

    def test_b_a_missing_source_one_folder_up_is_not_found_even_when_the_root_has_that_name(self):
        failing, _, box = self.page('- [S1] ../missing.md — a page one folder up that is not there', 'missing.md')
        self.assertEqual(list(failing), ['sources'], failing)
        self.assertIn('file not found (docs/missing.md)', failing['sources'][0])
        self.assertNotIn('missing.md', {p for p in box._read if p != PAGE})

    def test_c_a_source_written_with_dot_slash_is_the_file_next_to_the_document(self):
        failing, _, _ = self.page('- [S1] ./local.md — a page next to this one', 'docs/sub/local.md')
        self.assertEqual(failing, {})

    def test_d_a_dotted_folder_keeps_its_dot(self):
        failing, _, _ = self.page('- [S1] .github/ci.yml — the CI file', '.github/ci.yml')
        self.assertEqual(failing, {})
        failing, _, _ = self.page('- [S1] .github/none.yml — a CI file that is not there')
        self.assertIn('source S1 .github/none.yml: file not found', failing['sources'][0])

    def test_e_a_kept_name_written_bare_is_not_verified_and_never_read(self):
        failing, report, box = self.page('- [S1] .env.example — sample settings', '.env.example')
        self.assertEqual(failing, {})
        self.assertTrue([n for n in report['unverified'] if '.env.example' in n and 'not checked' in n], report['unverified'])
        self.assertNotIn('.env.example', box._read)
        self.assertNotIn(SECRET.strip(), json.dumps(report, ensure_ascii=False))

    def test_f_control_punctuation_around_a_bare_locator_is_still_dropped(self):
        for line in ('- [S1] sources/notes.txt. — with a full stop', '- [S1] (sources/notes.txt) — in parentheses', '- [S1] <sources/notes.txt>, notes',
                     '- [S1] sources/notes.txt; notes', '- [S1] sources/notes.txt: notes', '- [S1] ghi chú: sources/notes.txt'):
            with self.subTest(line=line):
                failing, _, _ = self.page(line)
                self.assertEqual(failing, {})

    def test_g_control_a_source_that_leaves_the_project_is_still_refused(self):
        failing, _, _ = self.page('- [S1] ../../../outside.md — above the repository')
        self.assertIn('leaves the project', failing['sources'][0])


if __name__ == '__main__':
    unittest.main()
