"""R10: an EXTRA file in the checkout that the sealed tree does not contain is a difference too (`add -u` alone never saw it)."""
import tempfile

from onecrew.common_verification import materialized_tree
from onecrew.ledger import LedgerError
from onecrew.v2.verifiers import command
from tests.test_v2_l1 import Fixture

DIFFERS = 'Materialized candidate differs from the sealed Git tree.'


class CandidateTreeExtraFileTests(Fixture):
    def materialize_with(self, plant):
        tree = self.git('rev-parse', 'HEAD^{tree}')
        real = command._checkout
        def planted(project, wanted, destination):
            checkout = real(project, wanted, destination)
            plant(checkout)
            return checkout
        command._checkout = planted
        try:
            with tempfile.TemporaryDirectory(prefix='oc-r10-') as temp:
                return materialized_tree(self.ledger, tree, temp).exists()
        finally:
            command._checkout = real

    def test_a_an_extra_file_is_refused(self):
        with self.assertRaises(LedgerError) as raised:
            self.materialize_with(lambda checkout: (checkout / 'extra.txt').write_text('not in the tree\n'))
        self.assertEqual(DIFFERS, str(raised.exception))

    def test_b_an_extra_file_in_a_new_directory_is_refused(self):
        def plant(checkout):
            (checkout / 'deep' / 'er').mkdir(parents=True); (checkout / 'deep' / 'er' / 'x.md').write_text('x\n')
        with self.assertRaises(LedgerError) as raised: self.materialize_with(plant)
        self.assertEqual(DIFFERS, str(raised.exception))

    def test_c_an_extra_file_that_an_ignore_rule_would_hide_is_still_refused(self):
        (self.root / '.gitignore').write_text('*.log\n'); self.git('add', '.gitignore'); self.git('commit', '-qm', 'ignore')
        with self.assertRaises(LedgerError) as raised:
            self.materialize_with(lambda checkout: (checkout / 'hidden.log').write_text('ignored but extra\n'))
        self.assertEqual(DIFFERS, str(raised.exception))

    def test_d_the_faithful_checkout_still_passes(self):
        self.assertTrue(self.materialize_with(lambda checkout: None))


if __name__ == '__main__':
    import unittest; unittest.main()
