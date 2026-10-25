"""W41 (T41): guard_swap decides from the installed build's `compat scan --json` report, not only from the checkout's in-process scan.

Counter-example: on a real temporary ledger the checkout scan reports 0 blocks; a forged venv report with the same ledger/input fence but
blocking.total 1 used to pass (ran True -> the install would be swapped). It must refuse. No installation runs here (the full drill is
tests.test_wf_upgrade_drill).
"""
import copy

from onecrew import task_intake
from onecrew.ledger import LedgerError
from onecrew.v2 import compat_scan
from tests.test_v2_l1 import Fixture
from wfkit.upgrade_drill import guard_swap


class GuardSwapTests(Fixture):
    def setUp(self):
        super().setUp()
        task_intake.submit(self.ledger, 'A v1 audit task the old scanner reads', 'v1-task', mode='audit')   # no v2 root: 0 blocks
        self.state = self.ledger.state_root
        self.clean = compat_scan.scan(self.state)
        self.assertEqual(self.clean['blocking']['total'], 0)

    def test_w41_venv_report_with_blocks_refuses_even_when_checkout_scan_is_clean(self):
        forged = copy.deepcopy(self.clean)
        forged['blocking'] = {'read': 0, 'continue': 1, 'total': 1}
        result = guard_swap(self.state, forged)
        self.assertFalse(result['ran'])                                                      # was True: the install would be swapped
        self.assertEqual(result['reason'], 'installed_scan_blocked')
        self.assertEqual(result['scan'], forged)

    def test_w41_venv_report_without_a_blocking_total_refuses(self):
        forged = copy.deepcopy(self.clean)
        forged.pop('blocking')
        with self.assertRaisesRegex(LedgerError, 'blocking total'):
            guard_swap(self.state, forged)

    def test_w41_clean_matching_venv_report_still_allows(self):
        self.assertTrue(guard_swap(self.state, copy.deepcopy(self.clean))['ran'])
