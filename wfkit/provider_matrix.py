"""W45 / T40b — the REAL provider × role matrix, run once per cell from an INSTALLED build.

  python -m wfkit.provider_matrix --venv <venv python> --wheel <wheel> --commit <sha> --out <new dir> [--providers claude,codex,kiro]

For each of the six cells (claude, codex, kiro × reviewer, advisor) the harness builds a tiny sample project + temporary ledger, pins the
cell's provider/model in the contract, and runs the product's own path from the venv: `verdict run` of a reviewer milestone (the real CLI reviews a
two-line diff, read-only) or `plan advise` (the real CLI answers the advisor questions). What is recorded per cell: the product's receipt (provider,
model, role, calls, result), the CLI identity (path, sha256 of the executable and of every prefix file, `--version`), the wheel hash and commit of
the installed build, and the time. A cell whose CLI is missing, not logged in or out of quota is `blocked` with its reason — never `pass`, never
another provider. A cell is `pass` when the real CLI answered and the product recorded a verdict/advice from it (`fail` when it answered but the
product could not use the answer). The six rows are then judged by the SHARED evaluator (wfkit.provider_evidence.evaluate) exactly as the RP
release notes and the final gate judge them, and written as matrix.json + matrix.md + receipts/*.json. Pins come from the program kit
(tests/test_wf_rp_providers MODELS / ADVISOR_MODELS) because the program contract itself is not approved yet; the matrix says so.

Authority: the owner's chat message "cho chạy W45" (24/10/2026 night). Uses the owner's existing accounts; buys nothing; each cell runs once
(one retry only on an infrastructure error, recorded). Nothing here is owner acceptance or P1.0 "đủ".
"""
import argparse
import datetime as _dt
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from onecrew.ledger import LedgerError
from onecrew.v2 import providers
from wfkit import provider_evidence
from wfkit.finalgate import Evidence, evidence_status

ROOT = Path(__file__).resolve().parents[1]
ROLES = ('reviewer', 'advisor')


def now():
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pins():
    """Provider/model pins and contract shapes from the program kit (the tests), read in THIS process (checkout + tests on sys.path)."""
    sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'tests'))
    import test_wf_rp_providers as rp           # noqa: E402  (fixture constants only; no test runs)
    import test_v2_reviewer as tr               # noqa: E402
    import test_v2_advisor as ta                # noqa: E402
    import test_v2_l1 as l1                     # noqa: E402
    return {'MODELS': rp.MODELS, 'ADVISOR_MODELS': rp.ADVISOR_MODELS, 'AUTHOR': rp.AUTHOR, 'ADVISOR_AUTHOR': ta.AUTHOR,
            'reviewer_contract': lambda p: l1.plan_json(milestones=[tr.reviewer_milestone(rp.MODELS[p], provider=p)]),
            'advisor_contract': lambda p: ta.sourced(l1.plan_json(), decisions=[ta.DECISION], advisor={'provider': p, 'model': rp.ADVISOR_MODELS[p]})}


class Matrix:
    def __init__(self, venv_python, wheel, commit, out, providers_=('claude', 'codex', 'kiro')):
        self.python, self.wheel, self.commit = Path(venv_python), Path(wheel), commit
        self.out = Path(out).resolve()
        if self.out.exists(): raise LedgerError('out must be a NEW directory')
        if not self.commit or len(self.commit) < 40: raise LedgerError('commit must be the full 40-hex sha of the installed build')
        self.out.mkdir(parents=True); (self.out / 'receipts').mkdir(); (self.out / 'cells').mkdir()
        self.wheel_sha = sha(self.wheel); self.providers = list(providers_)
        self.identity_of = {'commit': self.commit, 'wheel_sha256': self.wheel_sha}
        self.pins = pins()

    # -- one cell ------------------------------------------------------------------------------------------------------------------------------
    def run_in_venv(self, label, body):
        """Run `body` with the INSTALLED build only (-I, cwd outside the checkout): returns the @@ json the body prints."""
        work = self.out / 'cells' / label; work.mkdir()
        code = 'import json, sys\n' + body + '\n'
        env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP', 'ONECREW_ACTOR', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION')}
        done = subprocess.run([str(self.python), '-I', '-X', 'utf8', '-c', code], capture_output=True, text=True, encoding='utf-8', errors='replace',
                              cwd=str(work), env=env, timeout=900)
        (work / 'stdout.txt').write_text(done.stdout, encoding='utf-8'); (work / 'stderr.txt').write_text(done.stderr, encoding='utf-8')
        line = next((l for l in done.stdout.splitlines() if l.startswith('@@')), None)
        if not line: raise LedgerError(label + ': the cell body produced no observation: ' + (done.stderr or done.stdout)[-600:])
        return json.loads(line[2:]), work

    def cell(self, provider, role):
        label = f'{provider}-{role}'
        key = f'{provider}:{role}'
        model = (self.pins['MODELS'] if role == 'reviewer' else self.pins['ADVISOR_MODELS'])[provider]
        vendor = providers.reviewer_vendor(provider, model)
        # the CLI identity first (read-only); a missing CLI is a blocked cell, nothing is called
        try:
            prefix = (__import__('onecrew.v2.claude_cli', fromlist=['cli_argv']).cli_argv(dict(os.environ)) if provider == 'claude'
                      else providers.cli_prefix(provider, dict(os.environ)))
            identity = providers.cli_identity(provider, dict(os.environ), prefix)
        except LedgerError as problem:
            return self.receipt(key, provider, role, model, vendor, 'blocked', reason='CLI not found: ' + str(problem)[:300], cli_identity=None, run=None)
        work_project = self.out / 'cells' / (label + '-project'); work_project.mkdir()
        state = self.out / 'cells' / (label + '-state')
        for args in (['init', '-q'], ['config', 'user.name', 'w45'], ['config', 'user.email', 'w45@localhost']):
            subprocess.run(['git', '-C', str(work_project), *args], check=True, capture_output=True)
        (work_project / 'a.txt').write_text('one\n', encoding='utf-8')
        subprocess.run(['git', '-C', str(work_project), 'add', '.'], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(work_project), 'commit', '-qm', 'base'], check=True, capture_output=True)
        contract = (self.pins['reviewer_contract'] if role == 'reviewer' else self.pins['advisor_contract'])(provider)
        (self.out / 'cells' / (label + '-contract.json')).write_text(json.dumps(contract, ensure_ascii=False, indent=1), encoding='utf-8')
        author = self.pins['AUTHOR'] if role == 'reviewer' else self.pins['ADVISOR_AUTHOR']
        if role == 'reviewer':
            body = f'''
import os, time
from pathlib import Path
from onecrew.ledger import Ledger
from onecrew.snapshots import Snapshots
from onecrew.v2 import plan, verdict
root, state = Path({str(work_project)!r}), Path({str(state)!r})
ledger = Ledger(root, state)
contract = json.load(open({str(self.out / 'cells' / (label + '-contract.json'))!r}, encoding='utf-8'))
plan.propose(ledger, 'P1', contract, {author!r})
plan.approve(ledger, 'P1', 'owner', 'W45 sample on a temporary ledger; not an owner action')
(root / 'a.txt').write_text('one\\ntwo\\n', encoding='utf-8')          # the two-line diff the reviewer reads
t0 = time.monotonic()
shown = verdict.run(ledger, 'P1', 'M1', root)
seconds = round(time.monotonic() - t0, 1)
last = shown['milestones'][0].get('last_verdict') or {{}}
body = {{}}
try:
    body = json.loads(Snapshots(state).read_blob(last['receipt'])) if last.get('receipt') else {{}}
except Exception as error:   # noqa: BLE001
    body = {{'unreadable': str(error)[:200]}}
with ledger.transaction() as conn:
    task = plan.anchor_events(ledger, conn, 'P1')['task_id']
    recorded = [json.loads(r[0]) for r in conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='verdict.recorded' ORDER BY seq", (task,))]
rec = recorded[-1] if recorded else {{}}
print('@@' + json.dumps({{'milestone': shown['milestones'][0]['state'], 'result': rec.get('result'), 'provider': rec.get('provider') or body.get('provider'),
      'model': rec.get('model') or body.get('model'), 'calls': rec.get('calls', body.get('calls')), 'role': body.get('role'), 'error': body.get('error') or body.get('provider_error'),
      'receipt_blob': last.get('receipt'), 'seconds': seconds, 'usage': body.get('usage'), 'verdicts': body.get('verdicts') or body.get('answers')}}))
'''
        else:
            body = f'''
import os, time
from pathlib import Path
from onecrew.ledger import Ledger
from onecrew.snapshots import Snapshots
from onecrew.v2 import plan
from onecrew.v2.verifiers import advisor
root, state = Path({str(work_project)!r}), Path({str(state)!r})
ledger = Ledger(root, state)
contract = json.load(open({str(self.out / 'cells' / (label + '-contract.json'))!r}, encoding='utf-8'))
advisor.init_rules(ledger)
plan.propose(ledger, 'P1', contract, {author!r})
t0 = time.monotonic()
advisor.advise(ledger, 'P1')
seconds = round(time.monotonic() - t0, 1)
with ledger.transaction() as conn:
    advice = plan.derive(ledger, conn, 'P1')['advice'].get(1) or {{}}
body = {{}}
try:
    body = json.loads(Snapshots(state).read_blob(advice['receipt'])) if advice.get('receipt') else {{}}
except Exception as error:   # noqa: BLE001
    body = {{'unreadable': str(error)[:200]}}
print('@@' + json.dumps({{'usable': advice.get('usable'), 'provider': advice.get('provider'), 'model': advice.get('model'), 'error': advice.get('provider_error'),
      'calls': body.get('calls'), 'role': body.get('role'), 'receipt_blob': advice.get('receipt'), 'seconds': seconds, 'usage': body.get('usage'),
      'answers': body.get('answers') or body.get('verdicts')}}))
'''
        observed, work = self.run_in_venv(label, body)
        error = observed.get('error') or ''
        if role == 'reviewer':
            ran = observed.get('result') in ('pass', 'fail') and observed.get('calls') == 1
        else:
            ran = observed.get('usable') is True and observed.get('calls') == 1
        if ran: result, reason = 'pass', None
        elif error and (error.startswith(providers.QUOTA + ':') or 'not found' in error.lower() or 'login' in error.lower() or 'not logged' in error.lower()
                        or 'unauthorized' in error.lower() or 'credential' in error.lower() or 'account' in error.lower()):
            result, reason = 'blocked', error[:300]                              # missing account / quota / tool: unverified, never pass
        else:
            result, reason = 'fail', (error or f'the product recorded no usable verdict/advice from the CLI: {json.dumps(observed)[:200]}')[:300]
        return self.receipt(key, provider, role, model, vendor, result, reason=reason, cli_identity=identity, run=observed, work=str(work))

    def receipt(self, key, provider, role, model, vendor, result, *, reason, cli_identity, run, work=None):
        body = {'kind': 'behavior', 'item': key, 'provider': provider, 'role': role, 'model': model, 'vendor': vendor, 'result': result,
                'reason': reason, 'cli_identity': cli_identity, 'run': run, 'work': work, 'at': now(), 'simulated': False,
                'provenance': {'kind': 'real', 'source': 'wfkit.provider_matrix: real CLI call from the installed build on a temporary sample project (W45)',
                               'authorized_by': 'owner chat "cho chạy W45", 24/10/2026 night'},
                'pins_source': 'program kit (tests/test_wf_rp_providers MODELS/ADVISOR_MODELS); program contract not yet approved',
                **self.identity_of}
        raw = json.dumps(body, ensure_ascii=False, sort_keys=True, indent=1).encode('utf-8')
        path = self.out / 'receipts' / (key.replace(':', '-') + '.json'); path.write_bytes(raw)
        return {'ref': {'path': path.relative_to(self.out).as_posix(), 'sha256': hashlib.sha256(raw).hexdigest()}, 'body': body}

    # -- the six rows -------------------------------------------------------------------------------------------------------------------------
    def execute(self):
        receipts = {}
        for provider in ('claude', 'codex', 'kiro'):
            for role in ROLES:
                key = f'{provider}:{role}'
                if provider not in self.providers:
                    model = (self.pins['MODELS'] if role == 'reviewer' else self.pins['ADVISOR_MODELS'])[provider]
                    receipts[key] = self.receipt(key, provider, role, model, providers.reviewer_vendor(provider, model), 'blocked',
                                                 reason='not run in this session (provider excluded by the operator)', cli_identity=None, run=None)
                else:
                    receipts[key] = self.cell(provider, role)
                print(key, receipts[key]['body']['result'], (receipts[key]['body']['reason'] or '')[:160], flush=True)
        rows, items = [], []
        for key, rec in receipts.items():
            b = rec['body']
            state = evidence_status(b, [], self.identity_of, None, key)
            row = {'id': key, 'provider': b['provider'], 'role': b['role'], 'model': b['model'], 'vendor': b['vendor'], 'status': state['status'],
                   'reason': b['reason'], 'receipt': rec['ref'], 'limits': 'one read-only call on a two-line sample diff / three advisor questions; proves the cell runs, not review quality'}
            if b['result'] == 'pass':
                row['cli_sha256'] = b['cli_identity']['sha256']; row['cli_files'] = b['cli_identity']['files']; row['cli_version'] = b['cli_identity']['version']
            rows.append(row); items.append({'id': key, 'original': rec['ref'], 'supplements': []})
        evaluated = provider_evidence.evaluate(rows, items, Evidence(self.out, fixture=False), self.identity_of, self.identity_of, None)
        usable = sorted(k for k, s in evaluated.items() if s['status'] == 'usable')
        matrix = {'schema': 1, 'kind': 'provider-matrix', 'task': 'W45', 'testcase': 'T40b', 'at': now(), **self.identity_of, 'wheel': str(self.wheel),
                  'rows': rows, 'items': items, 'states': evaluated, 'usable': usable, 'p1': {'count': len(usable), 'label': 'full' if len(usable) == 6 else 'subset'},
                  'owner_acceptance': False, 'simulated': False, 'provenance': {'kind': 'real', 'source': 'wfkit.provider_matrix (W45)'}}
        (self.out / 'matrix.json').write_text(json.dumps(matrix, ensure_ascii=False, indent=1), encoding='utf-8')
        words = {'usable': 'đạt (dùng được)', 'failed': 'không đạt', 'unverified': 'chưa kiểm chứng', 'recheck': 'cần kiểm lại'}
        lines = [f'# Ma trận provider × vai trò (W45 / T40b) — bản dựng `{self.commit[:12]}`, wheel `{self.wheel_sha[:16]}…`', '',
                 f'Chạy thật từ bản cài (venv `{self.python.parent.parent}`), mỗi ô một lần, {matrix["at"]}. Ô `dùng được`: {len(usable)}/6 → P1.0: **{matrix["p1"]["label"]}**. '
                 'Không phải nghiệm thu; chất lượng review không được chứng minh ở đây.', '',
                 '| Provider | Vai trò | Model pin | Trạng thái | Biên nhận (sha256) | sha256 CLI | Giới hạn / lý do |', '|---|---|---|---|---|---|---|']
        for row in rows:
            lines.append(f"| {row['provider']} | {row['role']} | `{row['model']}` | {words[row['status']]} | `{row['receipt']['sha256'][:16]}` | "
                         f"{('`' + row['cli_sha256'][:16] + '` (' + row.get('cli_version', '') + ')') if row.get('cli_sha256') else '—'} | {row['reason'] or row['limits']} |")
        (self.out / 'matrix.md').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
        return matrix


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--venv', required=True, help='python.exe of the venv where the wheel is installed')
    ap.add_argument('--wheel', required=True); ap.add_argument('--commit', required=True); ap.add_argument('--out', required=True)
    ap.add_argument('--providers', default='claude,codex,kiro')
    a = ap.parse_args(argv)
    try:
        m = Matrix(a.venv, a.wheel, a.commit, a.out, a.providers.split(',')).execute()
        print(json.dumps({'usable': m['usable'], 'p1': m['p1'], 'out': a.out}, ensure_ascii=False)); return 0
    except (LedgerError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({'error': str(error)[-800:]}, ensure_ascii=False)); return 1


if __name__ == '__main__':
    raise SystemExit(main())
