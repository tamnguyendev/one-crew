"""2.5.0.dev14 — issue #4 (tamnguyendev/one-crew, from MEP 09/11; review DANH-GIA-ISSUE-2-10.vi.md; owner: "Đưa vào").

The command verifier runs on a checkout of the artifact. Its line endings followed the machine's git config (core.autocrlf, core.eol), which is
not part of the artifact's identity: one artifact sha, different bytes on two machines. The checkout now sets core.autocrlf=false and
core.eol=lf, so its bytes depend only on the tree and its .gitattributes (both hashed). Times of change are not kept (documented). Red on 698e118.
"""
import subprocess
import tempfile
from pathlib import Path

from onecrew.v2.verifiers import command
from tests.test_v2_l1 import Fixture


class CheckoutBytes(Fixture):
    def checked_out(self, name):
        tree = command.verified_sha(self.root)
        scratch = tempfile.mkdtemp(prefix='ocv-test-'); self.addCleanup(lambda: __import__('shutil').rmtree(scratch, ignore_errors=True))
        return (command._checkout(self.root, tree, scratch) / name).read_bytes(), tree

    def blob(self, tree, name):
        return subprocess.check_output(['git', '-C', str(self.root), 'cat-file', 'blob', f'{tree}:{name}'])

    def test_core_autocrlf_true_does_not_change_the_bytes(self):
        self.git('config', 'core.autocrlf', 'true')
        (self.root / 'lf.txt').write_bytes(b'one\ntwo\nthree\n')                   # not committed: part of the working-tree artifact
        data, tree = self.checked_out('lf.txt')
        self.assertEqual(data, b'one\ntwo\nthree\n')
        self.assertEqual(data, self.blob(tree, 'lf.txt'))

    def test_core_eol_crlf_with_text_auto_does_not_change_the_bytes(self):
        (self.root / '.gitattributes').write_text('* text=auto\n'); self.git('add', '.gitattributes'); self.git('commit', '-q', '-m', 'attrs')
        self.git('config', 'core.eol', 'crlf')
        (self.root / 'b.txt').write_bytes(b'x\ny\n')
        data, tree = self.checked_out('b.txt')
        self.assertEqual(data, b'x\ny\n')
        self.assertEqual(data, self.blob(tree, 'b.txt'))

    def test_the_guide_says_times_of_change_are_not_kept(self):
        guide = (Path(command.__file__).resolve().parents[3] / 'docs' / 'obs2' / 'su-dung' / 'BAT-DAU-SU-DUNG.vi.md').read_text(encoding='utf-8')
        self.assertIn('giờ sửa tệp', guide); self.assertIn('core.autocrlf', guide)
