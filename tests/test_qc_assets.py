"""S2 (QC MVP-1): declared Flutter assets/fonts reach the native test workspace as bytes read from the project.

J4 evidence: capture only sees text files and native_test_workspace.prepare staged only the manifest, worker files and
omitted .dart, so a test reading assets/fonts/OpenSans-Regular.ttf could never pass the fixed gate.
"""
import json
from pathlib import Path
import unittest

from tests import test_owned as fixtures
from onecrew.native_change import install_candidate, prepare_test_environment
from onecrew.sandbox_gate import GateUnavailable
from onecrew.snapshots import bytes_hash

PUBSPEC = """name: app
# comment line
flutter:
  uses-material-design: true
  assets:
    - assets/images/   # directory: one level only
    - "assets/data.bin"
    - assets/.env.local
  fonts:
    - family: Open Sans
      fonts:
        - asset: assets/fonts/OpenSans-Regular.ttf
        - asset: assets/fonts/OpenSans-Bold.ttf
          weight: 700
dev_dependencies:
  flutter_test:
    sdk: flutter
"""
FONT = bytes([0x00, 0x01, 0x00, 0x00, 0xFF, 0xFE, 0x80, 0x81, 0xC3, 0x28, 0x00, 0x9F])  # not UTF-8, has NUL


class AssetFixture(unittest.TestCase):
    pubspec = PUBSPEC

    def build(self):
        self.f = fixtures.OwnedTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        root = self.f.root / 'app'
        (root / 'lib').mkdir(parents=True); (root / '.dart_tool').mkdir()
        (root / 'lib/main.dart').write_text('int add(int a,int b)=>a-b;\n')
        (root / 'pubspec.yaml').write_text(self.pubspec)
        (root / '.dart_tool/package_config.json').write_text(json.dumps(
            {'configVersion': 2, 'packages': [{'name': 'app', 'rootUri': '../', 'packageUri': 'lib/'}]}))
        (root / '.dart_tool/package_graph.json').write_text(json.dumps(
            {'configVersion': 1, 'roots': ['app'], 'packages': [{'name': 'app', 'version': '1.0.0', 'dependencies': []}]}))
        self.assets = root / 'assets'
        (self.assets / 'fonts').mkdir(parents=True); (self.assets / 'images/sub').mkdir(parents=True)
        (self.assets / 'fonts/OpenSans-Regular.ttf').write_bytes(FONT)
        (self.assets / 'fonts/OpenSans-Bold.ttf').write_bytes(FONT + b'bold')
        (self.assets / 'fonts/Unlisted.ttf').write_bytes(b'not declared')
        (self.assets / 'data.bin').write_bytes(b'\x89PNG\r\n\x1a\n\x00\x00')
        (self.assets / 'images/a.png').write_bytes(b'\x89PNG-a')
        (self.assets / 'images/sub/b.png').write_bytes(b'\x89PNG-b')
        (self.assets / '.env.local').write_bytes(b'\x00private')
        self.recipe = dict(source_roots=['app'], owned=['app/lib/main.dart', 'app/test/main_test.dart'], extra_sources={},
            package='app', flutter_root=str(Path(self.f.temp.name) / 'flutter'), tests=['app/test/main_test.dart'],
            reference='User requested local fix', trusted_native=True)
        self.run, self.task, self.worker = self.f.runtime([], mode='change', provider='claude', model='sonnet',
                                                          native_change=self.recipe)
        self.run.run(self.task, steps=1)
        self.state = self.run.state(self.task)[1]
        install_candidate(self.run, self.state, {'report': 'Fixed arithmetic. Device unverified.', 'question': '', 'files': [
            {'path': 'app/lib/main.dart', 'text': 'int add(int a,int b)=>a+b;\n'},
            {'path': 'app/test/main_test.dart', 'text': '// meaningful fixture test is simulated\n'}]}, self.recipe)
        prepare_test_environment(self.run, self.state, self.recipe)

    def setUp(self):
        self.build()


class AssetStagingTests(AssetFixture):
    def test_declared_assets_and_fonts_are_staged_as_exact_project_bytes(self):
        from onecrew.native_test_workspace import prepare, check_workspace
        gate, receipt = prepare(self.run, self.state, self.recipe)
        self.assertEqual((gate / 'app/assets/fonts/OpenSans-Regular.ttf').read_bytes(), FONT)
        self.assertEqual((gate / 'app/assets/fonts/OpenSans-Bold.ttf').read_bytes(), FONT + b'bold')
        self.assertEqual((gate / 'app/assets/data.bin').read_bytes(), b'\x89PNG\r\n\x1a\n\x00\x00')
        self.assertEqual((gate / 'app/assets/images/a.png').read_bytes(), b'\x89PNG-a')
        self.assertEqual(receipt['local_only_asset_count'], 4)
        check_workspace(self.state)

    def test_only_declared_files_directories_are_one_level_and_private_names_are_skipped(self):
        from onecrew.native_test_workspace import prepare
        gate, _ = prepare(self.run, self.state, self.recipe)
        self.assertTrue((gate / 'app/assets/fonts/OpenSans-Bold.ttf').is_file())  # declared one is there, so the rest is meaningful
        self.assertFalse((gate / 'app/assets/fonts/Unlisted.ttf').exists())
        self.assertFalse((gate / 'app/assets/images/sub/b.png').exists())
        self.assertFalse((gate / 'app/assets/.env.local').exists())

    def test_assets_are_hash_pinned_and_never_enter_worker_inputs(self):
        from onecrew.native_test_workspace import prepare, check_workspace
        gate, _ = prepare(self.run, self.state, self.recipe)
        native = self.state['native_change']
        pinned = native['verification_inputs']
        self.assertEqual(pinned['app/assets/fonts/OpenSans-Regular.ttf'], bytes_hash(FONT))
        manifest = json.loads(self.run.store.read_evidence(native['manifest']))['files']
        for name in pinned:
            if name.startswith('app/assets/'):
                self.assertNotIn(name, manifest)
                self.assertNotIn(name, self.state['files'])
                self.assertFalse((Path(native['workspace']) / name).exists())
        (gate / 'app/assets/fonts/OpenSans-Regular.ttf').write_bytes(b'tampered during the test')
        with self.assertRaises(GateUnavailable):
            check_workspace(self.state)

    def test_project_asset_changed_after_staging_blocks_instead_of_passing_stale_bytes(self):
        from onecrew.native_test_workspace import prepare, check_inputs
        prepare(self.run, self.state, self.recipe)
        (self.assets / 'fonts/OpenSans-Regular.ttf').write_bytes(b'user changed the font')
        with self.assertRaises(GateUnavailable):
            check_inputs(self.run, self.state)


class PubspecReaderTests(unittest.TestCase):
    def test_reads_assets_fonts_quotes_comments_and_transformer_items_only_under_flutter(self):
        from onecrew.native_test_workspace import pubspec_assets
        text = ("name: app\nassets:\n  - not/flutter.png\nflutter:\n  assets:\n    - assets/a.png\n"
                "    - 'assets/b/'\n    - path: assets/c.json\n      transformers:\n        - package: t\n"
                "  fonts:\n    - family: F\n      fonts:\n        - asset: fonts/F.ttf # note\n"
                "dev_dependencies:\n  assets:\n    - nope.png\n")
        self.assertEqual(pubspec_assets(text), ['assets/a.png', 'assets/b/', 'assets/c.json', 'fonts/F.ttf'])

    def test_list_items_at_the_key_indent_are_read(self):
        from onecrew.native_test_workspace import pubspec_assets
        self.assertEqual(pubspec_assets('flutter:\n  assets:\n  - a.png\n  - b.png\n  uses-material-design: true\n'),
                         ['a.png', 'b.png'])

    def test_no_flutter_section_declares_nothing(self):
        from onecrew.native_test_workspace import pubspec_assets
        self.assertEqual(pubspec_assets('name: app\ndependencies:\n  x: 1\n'), [])


class NoAssetsTests(AssetFixture):
    pubspec = 'name: app\n'

    def test_package_without_flutter_assets_stages_none(self):
        from onecrew.native_test_workspace import prepare
        gate, receipt = prepare(self.run, self.state, self.recipe)
        self.assertEqual(receipt['local_only_asset_count'], 0)
        self.assertFalse((gate / 'app/assets').exists())


class AssetPathAndCapTests(AssetFixture):
    pubspec = 'name: app\nflutter:\n  assets:\n    - ../outside.bin\n'

    def test_path_leaving_the_package_is_refused(self):
        from onecrew.native_test_workspace import prepare
        (self.f.root / 'outside.bin').write_bytes(b'x')
        with self.assertRaises(GateUnavailable):
            prepare(self.run, self.state, self.recipe)


class AssetCountCapTests(AssetFixture):
    pubspec = 'name: app\nflutter:\n  assets:\n    - assets/many/\n'

    def test_more_than_500_asset_files_is_refused(self):
        from onecrew.native_test_workspace import prepare
        many = self.assets / 'many'; many.mkdir()
        for index in range(501):
            (many / ('f%03d.bin' % index)).write_bytes(b'\x00')
        with self.assertRaises(GateUnavailable) as caught:
            prepare(self.run, self.state, self.recipe)
        self.assertIn('500', str(caught.exception))

    def test_exactly_500_asset_files_is_accepted(self):
        from onecrew.native_test_workspace import prepare
        many = self.assets / 'many'; many.mkdir()
        for index in range(500):
            (many / ('f%03d.bin' % index)).write_bytes(b'\x00')
        _, receipt = prepare(self.run, self.state, self.recipe)
        self.assertEqual(receipt['local_only_asset_count'], 500)


class AssetByteCapTests(AssetFixture):
    pubspec = 'name: app\nflutter:\n  assets:\n    - assets/big/\n'

    def test_more_than_20_mb_of_assets_is_refused(self):
        from onecrew.native_test_workspace import prepare
        big = self.assets / 'big'; big.mkdir()
        for index in range(21):
            (big / ('m%02d.bin' % index)).write_bytes(b'\x01' * 1_000_000)
        with self.assertRaises(GateUnavailable) as caught:
            prepare(self.run, self.state, self.recipe)
        self.assertIn('20 MB', str(caught.exception))

    def test_20_mb_of_assets_is_accepted(self):
        from onecrew.native_test_workspace import prepare
        big = self.assets / 'big'; big.mkdir()
        for index in range(20):
            (big / ('m%02d.bin' % index)).write_bytes(b'\x01' * 1_000_000)
        _, receipt = prepare(self.run, self.state, self.recipe)
        self.assertEqual(receipt['local_only_asset_count'], 20)


if __name__ == '__main__':
    unittest.main()
