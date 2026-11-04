"""W40-RX1 / RX2 (T54j, T54k) [E8]: drive ONE document root, ONE data root and ONE ops root on the INSTALLED build.

`run_installed_adapters(python, runs_dir, ctx, ...)` builds, per adapter, a temporary git project and state root under `runs_dir`
(fake data only), proposes and approves a namespaced root in a body executed by the venv interpreter (installed code, tests/wf_wheel.run_case),
then runs `verdict run` through the venv's `onecrew` console script (never `python -m`, never the checkout). Each row is what the T54
release bundle's `adapter_runs` needs. The module-boundary check of the body is part of the row (`boundary_violations`).
"""
import copy
import json
import os
import subprocess
from pathlib import Path

from onecrew.v2 import boundary
from tests import wf_wheel as wh
from tests.test_v2_l1 import plan_json
import tests.test_wf_rx2_adapters as rx2

ADAPTERS = ('doc', 'data', 'ops')
GOOD_GUIDE = '# Guide\n\nSee [the sample](a.txt) and [the data](output.csv).\n'
BROKEN_GUIDE = '# Guide\n\nSee [a missing file](missing.txt).\n'
AI_MARKERS = ('ONECREW_ACTOR', 'CLAUDE_CODE_CHILD_SESSION', 'CLAUDECODE')

BODY = '''
import json, os, subprocess, sys
from pathlib import Path
from onecrew.ledger import Ledger
from onecrew.v2 import plan, verdict
for marker in ('ONECREW_ACTOR', 'CLAUDE_CODE_CHILD_SESSION', 'CLAUDECODE'):
    os.environ.pop(marker, None)
spec = json.loads(SPEC)
root, state = Path(spec['project']), Path(spec['state'])
ledger = Ledger(root, state)
name = spec['name']
plan.propose(ledger, name, spec['contract'], 'codex', workflow=True, capabilities=['namespaced-storage', 'finding-register'])
plan.approve(ledger, name, 'owner', 'fixture', estimate={'execution_seconds': [60, 120], 'evidence': ['fixture decomposition']})
exe = Path(sys.executable).with_name('onecrew' + ('.exe' if os.name == 'nt' else ''))
assert exe.exists(), exe
command = [str(exe), '--project', str(root), '--state-root', str(state), 'verdict', 'run', '--plan', name, '--milestone', 'M1']
done = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', env={**os.environ, 'PYTHONUTF8': '1'})
shown = plan.show(ledger, name)
out = {'command': command, 'returncode': done.returncode, 'stdout': done.stdout[-400:], 'stderr': done.stderr[-400:],
       'state': shown['milestones'][0]['state'], 'artifact': verdict.artifact(ledger, name)['artifact_sha']}
Path(spec['out']).write_text(json.dumps(out), encoding='utf-8')
'''


def _git(root, *args):
    subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True)


def _fixture(adapter, root, variant):
    """Write the fixture files and return (milestone, owned paths)."""
    if adapter == 'doc':
        (root / 'guide.md').write_text(BROKEN_GUIDE if variant == 'broken-doc' else GOOD_GUIDE, encoding='utf-8')
        (root / 'output.csv').write_text(rx2.TABLE, encoding='utf-8')
        return ({'id': 'M1', 'title': 'Check guide', 'max_repairs': 2, 'verifier': {'type': 'doc', 'config': {'docs': ['guide.md']}},
                 'covers': ['O1']}, ['guide.md'])
    if adapter == 'data':
        for file in ('input.csv', 'output.csv'):
            (root / file).write_text(rx2.TABLE, encoding='utf-8')
        return rx2.milestone('data', copy.deepcopy(rx2.DATA)), ['output.csv']
    if adapter == 'ops':
        rx2.write_ops(root)
        return rx2.milestone('ops', copy.deepcopy(rx2.OPS)), ['operation.json', 'post.json']
    raise ValueError('unknown adapter ' + repr(adapter))


def run_installed_adapters(python, runs_dir, ctx, *, adapters=ADAPTERS, commit=None, wheel_sha256=None, variant=None):
    """One row per adapter: {'adapter', 'root', 'result', 'artifact', 'commit', 'wheel_sha256', 'command', 'state_root',
    'boundary_violations'} (+ 'milestone_state', 'returncode', 'output_tail'). `variant='broken-doc'` breaks a link in the doc fixture,
    so the milestone really fails (result 'fail')."""
    runs_dir = Path(runs_dir)
    saved = {n: os.environ.pop(n) for n in AI_MARKERS if n in os.environ}
    try:
        rows = []
        for adapter in adapters:
            base = runs_dir / ('adapter-' + adapter + ('-' + variant if variant else ''))
            root, state = base / 'project', base / 'state'
            root.mkdir(parents=True)
            _git(root, 'init', '-q'); _git(root, 'config', 'user.name', 'Fixture'); _git(root, 'config', 'user.email', 'fixture@localhost')
            (root / 'a.txt').write_text('one\n', encoding='utf-8')
            milestone, owned = _fixture(adapter, root, variant)
            _git(root, 'add', '.'); _git(root, 'commit', '-qm', 'fixture')
            name = 'ns-' + adapter
            contract = plan_json(milestones=[milestone], scope={'owned': owned})
            spec = {'project': str(root), 'state': str(state), 'name': name, 'contract': contract, 'out': str(base / 'result.json')}
            body = 'SPEC = ' + repr(json.dumps(spec)) + '\n' + BODY
            dump, tail = wh.run_case(python, body, cwd=runs_dir)
            if dump is None or not (base / 'result.json').is_file():
                raise RuntimeError('installed adapter body failed for %s: %s' % (adapter, tail))
            out = json.loads((base / 'result.json').read_text(encoding='utf-8'))
            rows.append({'adapter': adapter, 'root': 'plan-ns:' + name,
                         'result': 'pass' if out['state'] == 'passed' else 'fail',
                         'artifact': out['artifact'], 'commit': commit, 'wheel_sha256': wheel_sha256,
                         'command': out['command'], 'state_root': str(state),
                         'boundary_violations': boundary.violations(dump['end'], ctx),
                         'milestone_state': out['state'], 'returncode': out['returncode'],
                         'output_tail': (out['stdout'] + out['stderr'])[-300:]})
        return rows
    finally:
        os.environ.update(saved)
