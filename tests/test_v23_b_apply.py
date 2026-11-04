"""2.3-B T7b (design §7 case 5): a REAL process death inside the project-apply effect, after the project file is written and before the
receipt. The action stays `executing` and keeps the root's writer exclusion; the next handoff reconciles it by observation and never
writes the project a second time. Real Git, real root commands, real CAS apply; no provider."""
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

from onecrew import project_apply_core
from onecrew.common_handoff import handoff
from onecrew.ledger import LedgerError
from onecrew.process_core import native_python
from tests.test_wf_candidate_handoff import CandidateFixture

REPO = Path(__file__).resolve().parents[1]

CHILD = r'''
import os, sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from onecrew import project_apply_core
from onecrew.common_handoff import handoff
from onecrew.ledger import Ledger
project = Path(sys.argv[2]).resolve()
real = project_apply_core.durable_write
def write(path, data):
    real(path, data)
    if Path(path).resolve().is_relative_to(project):
        os._exit(44)                     # the project file is written, the receipt is not: the controller dies inside the effect
project_apply_core.durable_write = write
handoff(Ledger(Path(sys.argv[2]), Path(sys.argv[3])), 'P1')
'''


class ApplyKillTests(CandidateFixture):
    def complete_nodes(self):
        self.revise(self.definition()); self.step()
        self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)
        self.step(); self.engine.verify(self.ledger, 'P1', 'I', self.production_checker)

    def apply_actions(self):
        with self.ledger.transaction() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM actions WHERE json_extract(payload,'$.kind')='apply'")]

    def test_t7b_kill_inside_the_apply_effect_is_reconciled_by_observation_without_a_second_write(self):
        self.complete_nodes()
        env = {k: v for k, v in os.environ.items() if k not in ('CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION')}
        child = subprocess.run([native_python(), '-X', 'utf8', '-c', CHILD, str(REPO), str(self.root), str(self.ledger.state_root)],
                               capture_output=True, env=env, timeout=300, creationflags=0x08000000)
        self.assertEqual(child.returncode, 44, child.stderr.decode('utf-8', 'replace')[-2000:])
        self.assertEqual((self.root / 'a.txt').read_text(), 'candidate\n')          # the effect happened before the death
        actions = self.apply_actions()
        self.assertEqual([a['status'] for a in actions], ['executing'])
        self.assertNotIn('workflow.handoff', self.kinds())
        # the ambiguous effect keeps the root's writer exclusion: no other effect of this root starts
        child_task = self.engine.state(self.ledger, 'P1')['nodes']['I']['child']
        other = self.control.propose_action(child_task, 'v23b-probe-writer', {'kind': 'probe'})
        self.control.authorize_action(other['id'], other['revision'])
        ran = []
        with self.assertRaisesRegex(LedgerError, 'live writer'):
            self.control.execute_action(other['id'], lambda payload: ran.append(payload) or {'verified': True})
        self.assertEqual(ran, [])
        # restart: the handoff observes the written file, records the reconciled receipt and writes nothing again
        stamp = (self.root / 'a.txt').stat().st_mtime_ns
        writes = []
        real = project_apply_core.durable_write
        def counted(path, data):
            writes.append(str(path)); return real(path, data)
        with patch.object(project_apply_core, 'durable_write', side_effect=counted):
            result = handoff(self.ledger, 'P1', control=self.control)
        self.assertEqual(result['state'], 'delivered', result)
        self.assertEqual(writes, [], 'reconciliation observes; it never repeats the effect')
        self.assertEqual((self.root / 'a.txt').stat().st_mtime_ns, stamp)
        actions = self.apply_actions()
        self.assertEqual([a['status'] for a in actions], ['verified'])
        self.assertTrue(json.loads(actions[0]['receipt'])['reconciled'])
        self.assertTrue(self.engine.root_ready(self.ledger, 'P1', result['artifact']))
