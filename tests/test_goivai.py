"""GOIVAI: the six role templates ship inside the wheel (onecrew/templates/vai3/). `onecrew mau list|lint` find them on a machine that has only the
install (no docs/vai3 beside the code); a project's docs/vai3 overrides a same-named packaged template. Only names the base has are imported and `mau`
runs as a subprocess from a COPY of the onecrew package (no docs beside it: an install), so a new behaviour is red BY ASSERTION on the base.
"""
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.v2_fixture import PY

REPO = Path(__file__).resolve().parents[1]
PACKAGED = REPO / 'onecrew' / 'templates' / 'vai3'
DOCS = REPO / 'docs' / 'vai3'
FILES = sorted(f'{role}.{lang}.md' for role in ('dieu-phoi', 'kiem', 'trao-doi') for lang in ('en', 'vi'))
ROLES = sorted(f'vai-{role}-{lang}' for role in ('dieu-phoi', 'kiem', 'trao-doi') for lang in ('en', 'vi'))
ALL = sorted(['mau-giao-viec', 'mau-loi-chu', *ROLES])
HEADER = re.compile(r'onecrew-mau: ten=([a-z0-9-]+) phien-ban=(\d+)')


def snapshot(*folders):
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else 'dir' for folder in folders for p in sorted(Path(folder).rglob('*'))}


class TestGoiVai(unittest.TestCase):
    """`site` = a copy of the onecrew package alone (what an install holds: no docs/ beside it); `project` = an empty project folder."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.site, self.project, self.state = self.base / 'site', self.base / 'project', self.base / 'state'
        shutil.copytree(REPO / 'onecrew', self.site / 'onecrew', ignore=shutil.ignore_patterns('__pycache__'))
        self.project.mkdir()
        (self.state / 'plans').mkdir(parents=True)
        self.packaged = self.site / 'onecrew' / 'templates' / 'vai3'

    def mau(self, command):
        env = dict(os.environ, PYTHONUTF8='1', ONECREW_LANG='vi',PYTHONDONTWRITEBYTECODE='1', LOCALAPPDATA=str(self.base / 'local'))
        done = subprocess.run([PY, '-X', 'utf8', '-m', 'onecrew', '--project', str(self.project), '--state-root', str(self.state), 'mau', command],
                              capture_output=True, cwd=self.site, timeout=120, env=env)
        return done.returncode, done.stdout.decode('utf-8'), done.stderr.decode('utf-8', 'replace')

    def listing(self):
        code, out, err = self.mau('list')
        self.assertEqual(code, 0, err)
        return {line.split()[0]: line for line in out.splitlines() if line.strip() and not line.startswith('GHI CH')}, out

    def project_roles(self):
        folder = self.project / 'docs' / 'vai3'
        folder.mkdir(parents=True)
        return folder

    # ---- kind A -------------------------------------------------------------------------------------------------------------

    def test_pyproject_package_data_includes_vai3(self):
        text = (REPO / 'pyproject.toml').read_text(encoding='utf-8')
        data = re.search(r'"onecrew\.templates"\s*=\s*\[([^\]]*)\]', text)
        self.assertTrue(data and 'vai3/*.md' in data.group(1), 'package-data of onecrew.templates must take vai3/*.md')

    def test_packaged_folder_holds_the_six_role_templates(self):
        self.assertEqual(sorted(p.name for p in PACKAGED.glob('*.md')), FILES)
        for path in PACKAGED.glob('*.md'):
            self.assertTrue(HEADER.search(path.read_text(encoding='utf-8-sig').splitlines()[0]), path.name)

    def test_packaged_templates_equal_the_docs_copy(self):
        self.assertEqual(sorted(p.name for p in PACKAGED.glob('*.md')), sorted(p.name for p in DOCS.glob('*.md')))
        for path in DOCS.glob('*.md'): self.assertEqual((PACKAGED / path.name).read_bytes(), path.read_bytes(), path.name)

    def test_mau_list_on_an_install_without_docs_shows_eight(self):
        lines, out = self.listing()
        self.assertEqual(sorted(lines), ALL, out)
        for name, line in lines.items(): self.assertRegex(line, r'^\S+  phien-ban=\d+  [0-9a-f]{12}  ', name)
        for name in ROLES: self.assertIn(str(self.packaged), lines[name], name)
        self.assertNotIn('GHI CHÚ', out)

    def test_mau_lint_on_an_install_without_docs_passes(self):
        code, out, err = self.mau('lint')
        self.assertEqual(code, 0, out + err)
        self.assertIn('ĐẠT: 8', out)

    def test_project_template_wins_over_packaged_and_names_its_source(self):
        mine = self.project_roles() / 'kiem.vi.md'
        mine.write_text((DOCS / 'kiem.vi.md').read_text(encoding='utf-8').replace('phien-ban=1', 'phien-ban=9', 1), encoding='utf-8')
        lines, out = self.listing()
        self.assertEqual(sorted(lines), ALL, out)
        self.assertIn('vai-kiem-vi  phien-ban=9  ', lines['vai-kiem-vi'])
        self.assertIn(str(mine), lines['vai-kiem-vi'])
        for name in ROLES:
            if name != 'vai-kiem-vi': self.assertIn(str(self.packaged), lines[name], name)
        mine.write_text(mine.read_text(encoding='utf-8').replace('## Báo cho', '## Khác'), encoding='utf-8')      # lint reads the project's copy
        code, out, err = self.mau('lint')
        self.assertEqual(code, 1, out + err)
        self.assertIn(str(mine), out); self.assertIn('Báo cho', out)

    def test_note_appears_only_when_neither_has_role_templates(self):
        shutil.rmtree(self.packaged, ignore_errors=True)
        _, out = self.listing()
        self.assertIn('GHI CHÚ', out)
        shutil.copytree(DOCS, self.packaged)        # docs/vai3 equals the packaged folder (checked by another case); reading it keeps the base's failure an assertion
        lines, out = self.listing()
        self.assertNotIn('GHI CHÚ', out)
        self.assertEqual(sorted(lines), ALL, out)

    # ---- kind B -------------------------------------------------------------------------------------------------------------

    def test_project_extra_template_is_listed_besides_packaged(self):
        (self.project_roles() / 'rieng.vi.md').write_text('<!-- onecrew-mau: ten=vai-rieng-vi phien-ban=2 -->\n# Mẫu riêng\n', encoding='utf-8')
        lines, out = self.listing()
        self.assertEqual(sorted(lines), sorted([*ALL, 'vai-rieng-vi']), out)

    def test_list_and_lint_write_nothing(self):
        before = snapshot(self.site, self.project, self.state)
        self.mau('list')
        self.mau('lint')
        self.assertEqual(snapshot(self.site, self.project, self.state), before)

    # ---- kind C (controls: green on the base too) ---------------------------------------------------------------------------

    def test_project_copy_of_the_templates_still_lists_eight(self):
        folder = self.project_roles()
        for path in DOCS.glob('*.md'): (folder / path.name).write_bytes(path.read_bytes())
        lines, out = self.listing()
        self.assertEqual(sorted(lines), ALL, out)

    def test_role_template_names_keep_their_headers(self):
        names = sorted(HEADER.search(p.read_text(encoding='utf-8-sig').splitlines()[0]).group(1) for p in DOCS.glob('*.md'))
        self.assertEqual(names, ROLES)
