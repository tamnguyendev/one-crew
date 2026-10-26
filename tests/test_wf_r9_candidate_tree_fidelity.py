"""R9: the sealed candidate tree is compared with its faithful checkout without letting the platform or the machine change the answer
(executable bit, ignore rules, gitlinks) while a real content change is still caught."""
import os
import tempfile
from pathlib import Path

from onecrew.common_verification import materialized_tree
from onecrew.ledger import LedgerError
from tests.test_v2_l1 import Fixture

DIFFERS = 'Materialized candidate differs from the sealed Git tree.'


class CandidateTreeFidelityTests(Fixture):
    def seal(self):
        self.git('add', '-f', '-A'); self.git('commit', '-qm', 'seal')
        return self.git('rev-parse', 'HEAD^{tree}')

    def verify(self, tree):
        with tempfile.TemporaryDirectory(prefix='oc-r9-') as temp:
            return materialized_tree(self.ledger, tree, temp)

    def test_a_executable_bit_is_kept(self):
        (self.root / 'run.sh').write_text('#!/bin/sh\n')
        self.git('add', 'run.sh'); self.git('update-index', '--chmod=+x', 'run.sh')
        self.assertIn('100755', self.git('ls-files', '-s', 'run.sh'))
        self.verify(self.seal())

    def test_b_tracked_file_matching_an_ignore_rule_or_its_directory_name_case_insensitively(self):
        folder = self.root / 'src' / 'Helpers.Pdf'; folder.mkdir(parents=True)
        (folder / 'Code.cs').write_text('class A {}\n'); (self.root / 'doc.pdf').write_bytes(b'%PDF\n')
        self.git('add', '-f', '-A'); self.git('commit', '-qm', 'tracked')
        (self.root / '.gitignore').write_text('*.pdf\n')
        self.verify(self.seal())

    def test_c_tracked_file_matching_the_global_excludes_is_kept(self):
        config = Path(self.temp.name) / 'xdg'; (config / 'git').mkdir(parents=True)
        (config / 'git' / 'ignore').write_text('**/.claude/settings.local.json\n')
        os.environ['XDG_CONFIG_HOME'] = str(config)
        target = self.root / '.claude'; target.mkdir()
        (target / 'settings.local.json').write_text('{}\n')
        self.verify(self.seal())

    def test_d_gitlink_without_gitmodules_is_kept(self):
        commit = self.git('rev-parse', 'HEAD')
        self.git('update-index', '--add', '--cacheinfo', '160000,' + commit + ',sub')
        self.git('commit', '-qm', 'gitlink')
        tree = self.git('rev-parse', 'HEAD^{tree}')
        self.assertIn('160000', self.git('ls-tree', tree, 'sub'))
        self.verify(tree)

    def test_e_a_changed_tracked_file_is_still_refused(self):
        tree = self.git('rev-parse', 'HEAD^{tree}')
        original = self.git('rev-parse', tree + ':a.txt')
        with tempfile.TemporaryDirectory(prefix='oc-r9-') as temp:
            from onecrew.v2.verifiers import command
            real = command._checkout
            def tampered(project, wanted, destination):
                checkout = real(project, wanted, destination)
                (checkout / 'a.txt').write_text('tampered\n')
                return checkout
            command._checkout = tampered
            try:
                with self.assertRaises(LedgerError) as raised: materialized_tree(self.ledger, tree, temp)
            finally:
                command._checkout = real
        self.assertEqual(DIFFERS, str(raised.exception)); self.assertTrue(original)


    def test_f_a_regular_entry_missing_from_the_checkout_is_refused(self):
        tree = self.git('rev-parse', 'HEAD^{tree}')
        with tempfile.TemporaryDirectory(prefix='oc-r9-') as temp:
            from onecrew.v2.verifiers import command
            real = command._checkout
            def broken(project, wanted, destination):
                checkout = real(project, wanted, destination)
                (checkout / 'a.txt').unlink()
                return checkout
            command._checkout = broken
            try:
                with self.assertRaises(LedgerError) as raised: materialized_tree(self.ledger, tree, temp)
            finally:
                command._checkout = real
        self.assertEqual(DIFFERS, str(raised.exception))


if __name__ == '__main__':
    import unittest; unittest.main()
