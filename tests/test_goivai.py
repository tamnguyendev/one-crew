"""GOIVAI: the six role templates ship inside the wheel as flat files onecrew/templates/role-<coordinator|checker|liaison>.<lang>.md (the hotfix flow's
check_wheel takes onecrew/templates/*.md one level only). `onecrew mau list|lint` find them on a machine that has only the install (no docs/vai3 beside
the code); a project's docs/vai3 replaces the packaged template of the same template name. Only names the base has are imported and `mau` runs as a
subprocess from a COPY of the onecrew package (no docs beside it: an install), so a new behaviour is red BY ASSERTION on the base.
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
PACKAGED = REPO / 'onecrew' / 'templates'
DOCS = REPO / 'docs' / 'vai3'
ENGLISH = {'dieu-phoi': 'coordinator', 'kiem': 'checker', 'trao-doi': 'liaison'}        # docs/vai3 role name -> packaged role name
FLAT = sorted(f'role-{new}.{lang}.md' for new in ENGLISH.values() for lang in ('en', 'vi'))
ROLES = sorted(f'vai-{role}-{lang}' for role in ENGLISH for lang in ('en', 'vi'))
ALL = sorted(['mau-giao-viec', 'mau-loi-chu', *ROLES])
HEADER = re.compile(r'onecrew-mau: ten=([a-z0-9-]+) phien-ban=(\d+)')


def packaged_name(docs_name):
    role, lang, _ = docs_name.rsplit('.', 2)
    return f'role-{ENGLISH[role]}.{lang}.md'


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
        self.packaged = self.site / 'onecrew' / 'templates'

    def mau(self, command):
        env = dict(os.environ, PYTHONUTF8='1', ONECREW_LANG='vi', PYTHONDONTWRITEBYTECODE='1', LOCALAPPDATA=str(self.base / 'local'))
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

    def test_packaged_role_templates_are_six_flat_prefixed_files(self):
        self.assertEqual(sorted(p.name for p in PACKAGED.glob('role-*.md')), FLAT)
        for path in PACKAGED.glob('role-*.md'):
            self.assertTrue(HEADER.search(path.read_text(encoding='utf-8-sig').splitlines()[0]), path.name)

    def test_packaged_templates_equal_the_docs_copy(self):
        self.assertEqual(sorted(p.name for p in PACKAGED.glob('role-*.md')), sorted(packaged_name(p.name) for p in DOCS.glob('*.md')))
        for path in DOCS.glob('*.md'): self.assertEqual((PACKAGED / packaged_name(path.name)).read_bytes(), path.read_bytes(), path.name)

    def test_mau_list_on_an_install_without_docs_shows_eight(self):
        lines, out = self.listing()
        self.assertEqual(sorted(lines), ALL, out)                          # owner-rules.*.md and the other files of the folder are not role templates
        for name, line in lines.items(): self.assertRegex(line, r'^\S+  phien-ban=\d+  [0-9a-f]{12}  ', name)
        for name in ROLES: self.assertIn(str(self.packaged / 'role-'), lines[name], name)
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
            if name != 'vai-kiem-vi': self.assertIn(str(self.packaged / 'role-'), lines[name], name)
        mine.write_text(mine.read_text(encoding='utf-8').replace('## Báo cho', '## Khác'), encoding='utf-8')      # lint reads the project's copy
        code, out, err = self.mau('lint')
        self.assertEqual(code, 1, out + err)
        self.assertIn(str(mine), out)
        self.assertIn('Báo cho', out)

    def test_project_template_without_header_still_overrides_by_its_file_name(self):
        mine = self.project_roles() / 'kiem.vi.md'
        mine.write_text('# Mẫu kiểm của dự án\n\n## Role\nx\n', encoding='utf-8')                      # no valid header line
        lines, out = self.listing()
        self.assertEqual(sorted(lines), ALL, out)                                                  # still eight: it replaced the packaged one
        self.assertIn(str(mine), lines['vai-kiem-vi'])
        self.assertIn('phien-ban=chua-ghi', lines['vai-kiem-vi'])
        code, lint, err = self.mau('lint')
        self.assertEqual(code, 1, lint + err)
        self.assertTrue(any('vai-kiem-vi' in l and 'dòng đầu' in l for l in lint.splitlines()), lint)

    def test_note_appears_only_when_neither_has_role_templates(self):
        for path in self.packaged.glob('role-*.md'): path.unlink()
        _, out = self.listing()
        self.assertIn('GHI CHÚ', out)
        for path in DOCS.glob('*.md'): shutil.copyfile(path, self.packaged / packaged_name(path.name))   # reading docs/vai3 keeps the base's failure an assertion
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

    def test_pyproject_package_data_is_unchanged(self):
        text = (REPO / 'pyproject.toml').read_text(encoding='utf-8')
        self.assertIn('"onecrew.templates" = ["*.md"]', text)           # test_g2_install reads this exact text

    def test_templates_folder_has_no_subfolder(self):
        self.assertEqual([p.name for p in PACKAGED.iterdir() if p.is_dir() and p.name != '__pycache__'], [])   # hotfix check_wheel: one level only
