import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from onecrew.delivery_env_node import PROBLEMS, discover, map_script
from onecrew.ledger import LedgerError

REAL = Path('D:/TamNT/Workspace/9.VMAgent/nursing-assistant-linh-thuoc')

MOCK_E2E = r"""
// Headless Chrome with a throwaway profile; never the persistent profile of https://his.example.com runs.
import path from 'node:path';
const root = path.resolve('.');
const PYTHON = path.resolve(root, process.env.NA_PYTHON ?? '../backend/.venv/Scripts/python.exe');
const BACKEND_DIR = path.resolve(root, process.env.NA_BACKEND_DIR ?? '../backend');
const MOCK = `http://127.0.0.1:${process.env.NA_MOCK_PORT}`; const LOCAL = 'http://localhost:9000/x';
const results = [];
console.log(`${results.filter((r) => r.ok).length}/${results.length} checks passed`);
"""
LIVE_E2E = r"""
import path from 'node:path'; import os from 'node:os'; import { readFile } from 'node:fs/promises';
const PROFILE_DIR = process.env.NA_REAL_PROFILE ?? path.join(os.homedir(), 'profile');
const cfg = JSON.parse(await readFile(path.join('..', 'harness', 'config.json'), 'utf8'));
console.log(`ACTION: please log in to the HIS in the Chrome window that just opened. Waiting...`);
console.log(`${passed}/${results.length} checks passed`);
"""
PACKAGE = {'name': 'ext', 'type': 'module', 'scripts': {
    'build': 'node scripts/build.mjs', 'build:demo': 'node scripts/build-demo.mjs && node ./scripts/post.mjs',
    'build:pack': 'npm run build && node scripts/post.mjs', 'typecheck': 'tsc --noEmit', 'test': 'vitest run',
    'e2e': 'node e2e/run-panel.mjs', 'e2e:real': 'node e2e/run-live.mjs', 'e2e:broken': 'node e2e/probe.mjs',
    'lint': 'npx eslint .', 'gen': 'node scripts/gen.mjs > out.ts'}}
VITEST_CONFIG = """import { defineConfig } from 'vitest/config';
export default defineConfig({
  optimizeDeps: { include: ['not-a-test-glob'] },
  test: {
    environment: 'jsdom', // include: ['commented/**']
    include: ['test/**/*.test.ts'],
    exclude: ['test/fixtures/**'],
  },
});
"""


def write(root, files):
    for name, text in files.items():
        path = Path(root) / name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text if isinstance(text, str) else json.dumps(text), encoding='utf-8')


class NodeDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.project = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.project, True)
        write(self.project, {
            'ext/package.json': PACKAGE, 'ext/manifest.json': {'manifest_version': 3, 'name': 'Ext', 'version': '1.2.3'},
            'ext/tsconfig.json': '{\n  // comment\n  "compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["src/*"]},},\n  "include": ["src", "test"]\n}',
            'ext/vitest.config.ts': VITEST_CONFIG, 'ext/src/app.ts': 'export const a = 1;\n', 'ext/src/inline.test.ts': '',
            'ext/test/a.test.ts': "import '../src/app';\n", 'ext/test/b.test.ts': '', 'ext/test/helper.ts': '',
            'ext/scripts/build.mjs': 'build\n', 'ext/scripts/build-demo.mjs': 'demo\n', 'ext/scripts/post.mjs': 'post\n',
            'ext/e2e/run-panel.mjs': MOCK_E2E, 'ext/e2e/run-live.mjs': LIVE_E2E, 'ext/e2e/probe.mjs': 'console.log("probe")\n',
            'ext/e2e/_helper.mjs': 'console.log(`${a}/${b} checks passed`)\n',
            'ext/node_modules/typescript/bin/tsc': 'tsc\n', 'ext/node_modules/vitest/vitest.mjs': 'vitest\n',
            'ext/node_modules/.package-lock.json': '{"lockfileVersion":3}', 'ext/dist/manifest.json': '{}',
            'backend/.venv/Scripts/python.exe': 'python\n', 'tools/node.exe': 'node\n', 'tools/chrome.exe': 'chrome\n'})
        self.node = str(self.project / 'tools/node.exe'); self.chrome = str(self.project / 'tools/chrome.exe')
        self.env = {'CHROME_PATH': self.chrome}
        self.envelope = {'toolchain': {'node_exe': self.node, 'package': 'ext'}}

    def run_discover(self, env=None, envelope=None, roots=('ext',)):
        return discover(self.project, list(roots), self.env if env is None else env, self.envelope if envelope is None else envelope)

    def codes(self, result):
        codes = sorted(p['code'] for p in result['problems'])
        self.assertLessEqual(set(codes), set(PROBLEMS))
        return codes

    def test_scripts_map_to_node_argv(self):
        result = self.run_discover()
        self.assertEqual(result['problems'], [{'code': 'build_script_unmappable', 'detail': result['problems'][0]['detail']},
                                              {'code': 'e2e_contract_missing', 'detail': result['problems'][1]['detail']}])
        facts = result['facts']; package = facts['packages'][0]; node = os.path.abspath(self.node)
        self.assertEqual((facts['package'], facts['node_exe'], facts['node_source']), ('ext', node, 'envelope'))
        scripts = package['scripts']
        self.assertEqual(scripts['build']['argv'], [[node, 'scripts/build.mjs']])
        self.assertEqual(scripts['build:demo']['argv'], [[node, 'scripts/build-demo.mjs'], [node, './scripts/post.mjs']])
        self.assertEqual(scripts['typecheck']['argv'], [[node, 'node_modules/typescript/bin/tsc', '--noEmit']])
        self.assertEqual(scripts['test']['argv'], [[node, 'node_modules/vitest/vitest.mjs', 'run']])
        self.assertIsNone(scripts['lint']['argv']); self.assertIn('npx', scripts['lint']['reason'])
        self.assertIsNone(scripts['gen']['argv']); self.assertIn('shell syntax', scripts['gen']['reason'])
        self.assertEqual(package['build_scripts'], {'build': 'scripts/build.mjs', 'build:demo': None, 'build:pack': None})
        self.assertEqual(package['manifest'], {'path': 'manifest.json', 'name': 'Ext', 'version': '1.2.3', 'manifest_version': 3, 'mv3': True})
        self.assertEqual((package['tsconfig']['base_url'], package['tsconfig']['paths']), ('.', {'@/*': ['src/*']}))
        self.assertEqual(package['vitest'], {'path': 'vitest.config.ts', 'include': ['test/**/*.test.ts'],
                                             'exclude': ['test/fixtures/**'], 'source': 'config'})
        self.assertEqual(package['tests'], ['test/a.test.ts', 'test/b.test.ts'])
        self.assertEqual(package['tools']['tsc'], os.path.abspath(self.project / 'ext/node_modules/typescript/bin/tsc'))
        self.assertTrue(package['lock_manifest'])

    def test_map_script_cases(self):
        node = 'C:/n/node.exe'
        self.assertEqual(map_script('node "scripts/my build.mjs" --flag', node), ([[node, 'scripts/my build.mjs', '--flag']], None))
        self.assertEqual(map_script('tsc --noEmit -p . && vitest run test/a.test.ts', node)[0],
                         [[node, 'node_modules/typescript/bin/tsc', '--noEmit', '-p', '.'], [node, 'node_modules/vitest/vitest.mjs', 'run', 'test/a.test.ts']])
        for command in ('npm run build', 'npx vite build', 'pnpm build', 'yarn build', 'cross-env A=1 node x.mjs', 'FOO=1 node x.mjs',
                        'node a.mjs | tee log', 'node a.mjs > out', 'node a.mjs; node b.mjs', 'node a.mjs || exit 0', 'node a.mjs & node b.mjs',
                        'node $SCRIPT', 'esbuild src/x.ts', 'node "unbalanced', '', 'node a.mjs && '):
            sequence, reason = map_script(command, node)
            self.assertIsNone(sequence, command); self.assertTrue(reason, command)

    def test_npx_script_is_problem(self):
        result = self.run_discover()
        unmappable = [p['detail'] for p in result['problems'] if p['code'] == 'build_script_unmappable']
        self.assertEqual(len(unmappable), 1); self.assertIn('build:pack', unmappable[0]); self.assertIn('npm', unmappable[0])
        package = dict(PACKAGE, scripts={'build': 'node scripts/missing.mjs', 'lint': 'npx eslint .'})
        write(self.project, {'ext/package.json': package})
        result = self.run_discover()
        self.assertEqual(self.codes(result), ['build_script_unmappable'])  # npx in a non-build script is only a fact
        self.assertIn('scripts/missing.mjs does not exist', result['problems'][0]['detail'])

    def test_missing_node_modules_problem(self):
        write(self.project, {'ext/package.json': dict(PACKAGE, scripts={'build': 'node scripts/build.mjs'})})
        self.assertEqual(self.codes(self.run_discover()), [])
        (self.project / 'ext/node_modules/.package-lock.json').unlink()
        (self.project / 'ext/node_modules/vitest/vitest.mjs').unlink()
        self.assertEqual(self.codes(self.run_discover()), ['lock_manifest_missing', 'vitest_missing'])
        shutil.rmtree(self.project / 'ext/node_modules/typescript')
        self.assertEqual(self.codes(self.run_discover()), ['lock_manifest_missing', 'typescript_missing', 'vitest_missing'])
        shutil.rmtree(self.project / 'ext/node_modules')
        result = self.run_discover()
        self.assertEqual(self.codes(result), ['node_modules_missing'])  # not also every tool inside it
        self.assertEqual(result['facts']['packages'][0]['tools'], {'tsc': None, 'vitest': None})

    def test_node_missing_and_pinned_node_is_the_only_candidate(self):
        result = self.run_discover(envelope={'toolchain': {'package': 'ext'}}, env={'CHROME_PATH': self.chrome})
        self.assertIn('node_missing', self.codes(result)); self.assertIsNone(result['facts']['node_exe'])
        self.assertEqual(result['facts']['packages'][0]['scripts']['build']['argv'], [['node.exe', 'scripts/build.mjs']])
        found = self.run_discover(envelope={'toolchain': {'package': 'ext'}}, env={'CHROME_PATH': self.chrome, 'NODE_EXE': self.node})
        self.assertEqual(found['facts']['node_source'], 'NODE_EXE')
        pinned = self.run_discover(envelope={'toolchain': {'package': 'ext', 'node_exe': str(self.project / 'gone/node.exe')}},
                                   env={'CHROME_PATH': self.chrome, 'NODE_EXE': self.node})
        self.assertIn('node_missing', self.codes(pinned))  # an approved toolchain is never silently swapped

    def test_e2e_contract_mock_vs_live(self):
        result = self.run_discover()
        e2e = {f['script']: f for f in result['facts']['packages'][0]['e2e']}
        self.assertEqual(sorted(e2e), ['e2e/run-live.mjs', 'e2e/run-panel.mjs'])  # probe has no contract; _helper is private
        self.assertEqual((e2e['e2e/run-panel.mjs']['mode'], e2e['e2e/run-panel.mjs']['signals']), ('mock', []))
        self.assertEqual(e2e['e2e/run-panel.mjs']['npm_scripts'], ['e2e'])
        self.assertEqual(e2e['e2e/run-panel.mjs']['env'], ['NA_BACKEND_DIR', 'NA_MOCK_PORT', 'NA_PYTHON'])
        self.assertEqual(e2e['e2e/run-panel.mjs']['env_defaults'], {'NA_BACKEND_DIR': '../backend', 'NA_PYTHON': '../backend/.venv/Scripts/python.exe'})
        self.assertEqual((e2e['e2e/run-live.mjs']['mode'], e2e['e2e/run-live.mjs']['signals']),
                         ('live', ['action_line', 'persistent_profile', 'real_config']))
        sha = hashlib.sha256((self.project / 'ext/e2e/run-live.mjs').read_bytes()).hexdigest()
        self.assertEqual(e2e['e2e/run-live.mjs']['sha256'], sha)
        missing = [p['detail'] for p in result['problems'] if p['code'] == 'e2e_contract_missing']
        self.assertEqual(len(missing), 1); self.assertIn('e2e/probe.mjs (e2e:broken) never prints', missing[0])
        envelope = dict(self.envelope, stages={'e2e_mock': {'script': 'e2e/run-live.mjs'},
                                               'e2e_live': {'script': 'e2e/run-live.mjs', 'script_sha256': '0' * 64,
                                                            'build_script': 'scripts/build-demo.mjs'},
                                               'build': {'script': 'scripts/nope.mjs'}})
        result = self.run_discover(envelope=envelope)
        details = [p['code'] + ': ' + p['detail'] for p in result['problems']]
        self.assertTrue(any('stage e2e_mock' in d and 'is a live harness' in d for d in details), details)
        self.assertTrue(any(d.startswith('harness_sha_mismatch') and 'e2e_live' in d for d in details), details)
        self.assertTrue(any(d.startswith('build_script_unmappable') and 'stage build' in d for d in details), details)
        write(self.project, {'outside.mjs': MOCK_E2E})  # a pinned script outside the package is never read
        envelope['stages'] = {'e2e_mock': {'script': '../outside.mjs'}}
        details = [p['detail'] for p in self.run_discover(envelope=envelope)['problems'] if p['code'] == 'e2e_contract_missing']
        self.assertTrue(any('../outside.mjs does not exist' in d for d in details), details)
        envelope['stages'] = {'e2e_mock': {'script': 'e2e/run-panel.mjs'}, 'e2e_live': {'script': 'e2e/run-live.mjs', 'script_sha256': sha}}
        self.assertNotIn('harness_sha_mismatch', self.codes(self.run_discover(envelope=envelope)))
        self.assertEqual(sorted(self.run_discover(envelope=envelope)['facts']['packages'][0]['stages']), ['e2e_live.script', 'e2e_mock.script'])

    def test_chrome_and_backend_venv(self):
        facts = self.run_discover()['facts']
        self.assertEqual((facts['chrome'], facts['chrome_source']), (os.path.abspath(self.chrome), 'CHROME_PATH'))
        self.assertEqual(facts['backend_python'], os.path.abspath(self.project / 'ext/../backend/.venv/Scripts/python.exe'))
        self.assertEqual(facts['backend_python_source'], 'script_default')
        self.assertEqual(facts['backend_dir'], os.path.abspath(self.project / 'backend'))
        self.assertIn('chrome_missing', self.codes(self.run_discover(env={})))
        pinned = dict(self.envelope, stages={'e2e_mock': {'script': 'e2e/run-panel.mjs', 'env': {'CHROME_PATH': str(self.project / 'none.exe')}}})
        self.assertIn('chrome_missing', self.codes(self.run_discover(envelope=pinned)))  # the pin wins over CHROME_PATH
        os.remove(self.project / 'backend/.venv/Scripts/python.exe')
        self.assertIn('backend_venv_missing', self.codes(self.run_discover()))
        write(self.project, {'py/python.exe': ''})
        self.assertNotIn('backend_venv_missing', self.codes(self.run_discover(env=dict(self.env, NA_PYTHON=str(self.project / 'py/python.exe')))))

    def test_no_e2e_needs_no_browser(self):
        shutil.rmtree(self.project / 'ext/e2e')
        write(self.project, {'ext/package.json': dict(PACKAGE, scripts={'build': 'node scripts/build.mjs'})})
        result = self.run_discover(env={})
        self.assertEqual(self.codes(result), []); self.assertIsNone(result['facts']['chrome'])

    def test_fingerprint_hashes_tools(self):
        first = self.run_discover()['fingerprint']
        self.assertEqual(self.run_discover()['fingerprint'], first)
        # Sources, logs and build output are not tools: no drift from them (RC7).
        write(self.project, {'ext/src/app.ts': 'export const a = 2;\n', 'ext/build.log': 'x', 'ext/dist/manifest.json': '{"v":2}'})
        self.assertEqual(self.run_discover()['fingerprint'], first)
        seen = {first}
        for name in ('tools/node.exe', 'ext/node_modules/typescript/bin/tsc', 'ext/node_modules/vitest/vitest.mjs', 'ext/scripts/build.mjs',
                     'ext/e2e/run-panel.mjs', 'ext/e2e/run-live.mjs', 'ext/node_modules/.package-lock.json'):
            with (self.project / name).open('a', encoding='utf-8') as f:
                f.write('\n// changed\n')
            value = self.run_discover()['fingerprint']
            self.assertNotIn(value, seen, name); seen.add(value)

    def test_roots_and_packages(self):
        for root in ('../x', 'C:/x', '/abs', ''):
            with self.assertRaises(LedgerError, msg=root):
                discover(self.project, [root], self.env)
        with self.assertRaises(LedgerError):
            discover(self.project / 'nope', ['ext'], self.env)
        self.assertEqual(self.codes(self.run_discover(roots=('ext', 'gone'), envelope={'toolchain': {'node_exe': self.node}}))[-1:], ['root_missing'])
        self.assertIn('package_missing', self.codes(self.run_discover(roots=('backend',), envelope={'toolchain': {'node_exe': self.node}})))
        self.assertIn('package_missing', self.codes(self.run_discover(envelope={'toolchain': {'node_exe': self.node, 'package': 'other'}})))
        write(self.project, {'libs/one/package.json': {'name': 'one'}, 'libs/one/node_modules/x': ''})
        result = discover(self.project, ['ext', 'libs'], self.env, {'toolchain': {'node_exe': self.node}})
        self.assertEqual([p['root'] for p in result['facts']['packages']], ['ext', 'libs/one'])
        self.assertIsNone(result['facts']['package'])

    @unittest.skipUnless((REAL / 'extension/package.json').is_file(), 'real linh-thuoc project absent')
    def test_real_project_read_only(self):
        package_dir = REAL / 'extension'
        before = sorted((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in package_dir.iterdir())
        result = discover(REAL, ['extension', 'shared'])
        facts = result['facts']; package = facts['packages'][0]
        self.assertEqual(facts['package'], 'extension')
        self.assertTrue(package['tools']['tsc'].replace('\\', '/').endswith('node_modules/typescript/bin/tsc'))
        self.assertTrue(package['tools']['vitest'].replace('\\', '/').endswith('node_modules/vitest/vitest.mjs'))
        self.assertEqual(package['build_scripts']['build'], 'scripts/build.mjs')
        modes = {f['script']: f['mode'] for f in package['e2e']}
        self.assertEqual(modes['e2e/run-panel.mjs'], 'mock'); self.assertEqual(modes['e2e/run-real-panel-th.mjs'], 'live')
        self.assertTrue(package['manifest']['mv3']); self.assertGreater(package['tests_total'], 0)
        self.assertNotIn('build_script_unmappable', self.codes(result))
        self.assertEqual(sorted((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in package_dir.iterdir()), before)


if __name__ == '__main__':
    unittest.main()
