"""2.5.0.dev24 — Kiro round 5 on 1d29b43 (P1, owner 10/11 stop rule: a P1 always blocks).
A command line that names a FOLDER (`pytest tool`, or `.`) runs what is inside it, so an inputs_unscanned exemption equal to, under or above a path
the command line names is refused by the contract and dropped at the run: the file is scanned for an absolute path into the live tree.
Red on 1d29b43.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from onecrew.ledger import LedgerError
from onecrew.v2 import contract as contracts
from onecrew.v2.verifiers import command
from tests.test_v2_l1 import Fixture, plan_json, milestone

PY = sys.executable


class FolderOnTheCommandLine(Fixture):
    def contract(self, argv, unscanned, cwd=None):
        m = milestone(argv=argv); m['verifier']['config'].update(inputs=['tool', 'docs'], inputs_unscanned=unscanned)
        if cwd: m['verifier']['config']['cwd'] = cwd
        return plan_json(milestones=[m])

    def test_the_contract_refuses_an_exemption_under_a_folder_the_command_line_names(self):
        for argv, cwd in (([PY, '-m', 'pytest', 'tool'], None), ([PY, '-m', 'pytest', 'tool/'], None), ([PY, '-m', 'pytest', '.'], None),
                          ([PY, '-m', 'pytest', '.'], 'tool'), ([PY, '-m', 'pytest', '--rootdir=tool'], None)):
            with self.subTest(argv=argv, cwd=cwd), self.assertRaises(LedgerError):
                contracts.validate(self.contract(argv, ['tool/check.py'], cwd))

    def test_an_exemption_beside_the_named_folder_stays(self):
        got = contracts.validate(self.contract([PY, '-m', 'pytest', 'tool'], ['docs/ghi-chu.md']))
        self.assertEqual(got['milestones'][0]['verifier']['config']['inputs_unscanned'], ['docs/ghi-chu.md'])

    def workspace(self):
        workspace = Path(self.temp.name) / 'ban-chep'; (workspace / 'tool').mkdir(parents=True, exist_ok=True)
        (workspace / 'tool' / 'check.py').write_text('open(r"' + str(self.root / 'live.txt') + '")\n')
        return workspace

    def test_at_the_run_a_file_inside_a_named_folder_is_scanned(self):
        for argv in (['python', '-m', 'pytest', 'tool'], ['python', '-m', 'pytest', '.']):
            with self.subTest(argv=argv), self.assertRaises(LedgerError):
                command.check_live_tree_named(self.root, argv, self.workspace(), ['tool/check.py'])
