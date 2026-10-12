from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from onecrew import node_imports
from onecrew.ledger import LedgerError
from onecrew.node_imports import Graph, affected_tests, glob_regex, specifiers, test_files, tsconfig

REAL = Path('D:/TamNT/Workspace/9.VMAgent/nursing-assistant-linh-thuoc/extension')

SOURCE = r"""
import def from './a';
import {
  one,
  two,
} from "./b.js";
import * as ns from '../up/c';
import type { T } from './types';
import './side-effect.css';
export * from './re';
export { x as y } from './named';
// import { gone } from './commented';
/* import { gone2 } from './block-commented'; */
const url = 'http://127.0.0.1:8765/x'; import late from './after-url';
const lazy = await import('./lazy');
const tpl = await import(`./tpl`);
const cjs = require('./legacy.cjs');
vi.mock('./mocked', () => ({}));
const real = await vi.importActual('./actual');
const html = await import('../src/panel.html?raw');
import pkg from 'vitest';
const text = "not an import: from './x'";
"""


def write(root, files):
    for name, text in files.items():
        path = Path(root) / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text, encoding='utf-8')


class SpecifierTests(unittest.TestCase):
    def test_static_dynamic_imports(self):
        found = specifiers(SOURCE)
        for spec in ('./a', './b.js', '../up/c', './types', './side-effect.css', './re', './named', './after-url', './lazy',
                     './tpl', './legacy.cjs', './mocked', './actual', '../src/panel.html?raw', 'vitest'):
            self.assertIn(spec, found)
        self.assertNotIn('./commented', found); self.assertNotIn('./block-commented', found)
        self.assertEqual(len(found), len(set(found)))
        self.assertEqual(specifiers("const u = `${base}/x`; import(`./dyn/${name}`);"), [])  # computed: not static

    def test_glob_regex(self):
        default = glob_regex(node_imports.DEFAULT_TEST_GLOBS[0])
        for name in ('test/a.test.ts', 'a.spec.js', 'src/x/y.test.mjs', 'b.test.cts', 'c.spec.tsx'):
            self.assertTrue(default.match(name), name)
        for name in ('test/a.ts', 'test/a.test.ts.snap', 'a.test.py', 'test/a.test.mts.bak'):
            self.assertFalse(default.match(name), name)
        only = glob_regex('./test/**/*.test.ts')
        self.assertTrue(only.match('test/a.test.ts')); self.assertTrue(only.match('test/deep/er/a.test.ts'))
        self.assertFalse(only.match('src/a.test.ts')); self.assertFalse(only.match('test/a.test.tsx'))
        self.assertTrue(glob_regex('test/[!x]*.{unit,int}.ts').match('test/a.int.ts'))
        self.assertFalse(glob_regex('test/[!x]*.{unit,int}.ts').match('test/xa.int.ts'))
        self.assertEqual(test_files({'test/a.test.ts', 'test/b.ts', 'src/c.spec.ts', 'test/z.test.ts'}, ['test/**/*.test.ts']),
                         ['test/a.test.ts', 'test/z.test.ts'])


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()) / 'ext'; self.addCleanup(shutil.rmtree, self.root.parent, True)

    def test_resolution_forms(self):
        write(self.root, {
            'src/app.ts': "import { b } from './b.js';\nimport cfg from '/src/config';\nimport idx from './lib';\n"
                          "import html from './panel.html?raw';\nimport Case from './CASED';\nimport gone from './missing';\n"
                          "import shared from '../../shared/words.json';\nimport ext from 'esbuild';\n",
            'src/b.ts': 'export const b = 1;\n', 'src/config.mts': 'export default {};\n', 'src/lib/index.ts': 'export default 1;\n',
            'src/panel.html': '<div></div>\n', 'src/Cased.ts': 'export default 1;\n'})
        graph = Graph(self.root)
        self.assertEqual(graph.edges['src/app.ts'], ['src/Cased.ts', 'src/b.ts', 'src/config.mts', 'src/lib/index.ts', 'src/panel.html'])
        self.assertEqual(graph.unresolved, {'src/app.ts': ['./missing']})
        self.assertEqual(graph.outside, {'src/app.ts': ['../../shared/words.json']})

    def test_tsconfig_paths(self):
        write(self.root, {
            'tsconfig.base.json': '{\n  // shared options\n  "compilerOptions": {"baseUrl": "src", "paths": {"@/*": ["*"]},},\n}\n',
            # an inherited baseUrl applies: paths resolve against it, and the extending file's paths replace the base ones
            'tsconfig.json': '{"extends": "./tsconfig.base", "compilerOptions": {"paths": {"@/*": ["*"], "@lib/*": ["lib/*", "../vendor/*"],'
                             ' "~config": ["config.ts"]}}, "include": ["src", "test"]}',
            'src/config.ts': 'export {};\n', 'src/lib/a.ts': 'export {};\n', 'vendor/v.ts': 'export {};\n', 'src/util.ts': 'export {};\n',
            'src/main.ts': "import a from '@lib/a';\nimport v from '@lib/v';\nimport c from '~config';\nimport u from 'util';\n"
                           "import s from '@/util';\n"})
        config = tsconfig(self.root)
        self.assertEqual(config['base_url'], 'src'); self.assertEqual(config['include'], ['src', 'test'])
        self.assertEqual(Graph(self.root).edges['src/main.ts'], ['src/config.ts', 'src/lib/a.ts', 'src/util.ts', 'vendor/v.ts'])
        # paths without baseUrl resolve against the tsconfig directory
        write(self.root, {'tsconfig.json': '{"compilerOptions": {"paths": {"@/*": ["src/*"]}}}'})
        self.assertEqual(Graph(self.root).edges['src/main.ts'], ['src/util.ts'])

    def test_affected_tests_transitive(self):
        write(self.root, {
            'src/owned.ts': 'export const x = 1;\n', 'src/mid.ts': "export * from './owned';\n",
            'src/top.ts': "import { x } from './mid.js';\n", 'src/other.ts': 'export const o = 1;\n',
            'test/direct.test.ts': "import { x } from '../src/owned';\n", 'test/two.test.ts': "import '../src/mid';\n",
            'test/three.test.ts': "const t = await import('../src/top');\n", 'test/a-three.test.ts': "import '../src/top';\n",
            'test/unrelated.test.ts': "import '../src/other';\n", 'test/raw.test.ts': "import s from '../src/owned.ts?raw';\n",
            'test/owned.test.ts': "import '../src/owned';\n", 'test/helper.ts': "import '../src/owned';\n",
            'node_modules/pkg/index.test.ts': "import '../../src/owned';\n", 'dist/x.test.ts': "import '../src/owned';\n"})
        owned = ['src/owned.ts', str(self.root / 'test/owned.test.ts'), '../outside.ts']
        expected = ['test/direct.test.ts', 'test/raw.test.ts', 'test/two.test.ts', 'test/a-three.test.ts', 'test/three.test.ts']
        self.assertEqual(affected_tests(self.root, owned), expected)
        self.assertEqual(affected_tests(self.root, owned, ['test/**/*.test.ts'], limit=2), expected[:2])
        self.assertEqual(affected_tests(self.root, ['src/other.ts']), ['test/unrelated.test.ts'])
        self.assertEqual(affected_tests(self.root, ['src/nothing.ts']), [])
        self.assertEqual(Graph(self.root).distances({'src/owned.ts'})['src/top.ts'], 2)

    def test_deterministic_order(self):
        files = {'src/owned.ts': 'export {};\n'}
        for i in (9, 3, 7, 1):
            files['test/t%d.test.ts' % i] = "import '../src/owned';\n"
        write(self.root, files)
        first = affected_tests(self.root, ['src/owned.ts'])
        self.assertEqual(first, ['test/t1.test.ts', 'test/t3.test.ts', 'test/t7.test.ts', 'test/t9.test.ts'])
        self.assertEqual(affected_tests(self.root, ['src/owned.ts']), first)

    def test_bounded_by_file_count_and_size(self):
        write(self.root, {'src/owned.ts': 'export {};\n', 'src/big.ts': "import './owned';\n" + '//' + 'x' * 3000 + '\n',
                          'test/big.test.ts': "import '../src/big';\n", 'test/a.test.ts': "import '../src/owned';\n"})
        with self.assertRaises(LedgerError):
            Graph(self.root, max_files=3)
        graph = Graph(self.root, max_file_bytes=1000)
        self.assertEqual(graph.skipped, ['src/big.ts'])
        self.assertEqual(affected_tests(self.root, ['src/owned.ts'], graph=graph), ['test/a.test.ts'])
        with patch.object(node_imports, 'MAX_TOTAL_BYTES', 100):
            with self.assertRaises(LedgerError):
                Graph(self.root)

    @unittest.skipUnless((REAL / 'package.json').is_file(), 'real linh-thuoc extension absent')
    def test_real_project_read_only(self):
        graph = Graph(REAL)
        tests = affected_tests(REAL, ['src/sidepanel/flow.ts'], ['test/**/*.test.ts'], graph=graph)
        self.assertIn('test/linh-panel.test.ts', tests)
        self.assertEqual(graph.distances({'src/sidepanel/flow.ts'})[tests[0]], 1)
        self.assertGreater(len(tests), 30)  # the child keeps the nearest 30; the root regression runs them all
        self.assertEqual(tests, affected_tests(REAL, ['src/sidepanel/flow.ts'], ['test/**/*.test.ts'], graph=graph))


if __name__ == '__main__':
    unittest.main()
