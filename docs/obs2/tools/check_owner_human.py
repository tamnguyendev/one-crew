"""Installed owner-CLI refusal probe on a NEW fixture, never the trial's CODE/DOC ledger.

python -I -X utf8 -B check_owner_human.py <verified trial directory> <NEW output directory>
Retains caller AI markers and explicitly sets the child AI guard if it is absent.
It tests refusals only; owner-success behavior is covered by labelled unit fixtures,
or by the actual owner later in their terminal. No approval is recorded here.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def digest(folder):
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in folder.rglob('*') if p.is_file()}


def main(trial, output):
    trial, output = Path(trial).resolve(), Path(output).resolve()
    if output.exists(): raise ValueError('Use a new output directory.')
    if output == trial or output.is_relative_to(trial / 'state') or output.is_relative_to(trial / 'project') or output.is_relative_to(trial / 'venv'):
        raise ValueError('Output must not be inside the existing trial state/project/venv.')
    python = trial / 'venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not python.is_file(): raise ValueError('Installed trial venv is required.')
    scenario = Path(__file__).resolve().with_name('scenario_obs2.py')
    output.mkdir(parents=True)
    env = dict(os.environ)   # Do not clear actor/session markers to manufacture an owner terminal.
    for key, name in (('LOCALAPPDATA', 'local'), ('APPDATA', 'roaming'), ('TEMP', 'temp'), ('TMP', 'temp')):
        (output / name).mkdir(exist_ok=True); env[key] = str(output / name)
    setup = ('import json,runpy,sys\nfrom pathlib import Path\nfrom onecrew.ledger import Ledger\n'
             'from onecrew.v2 import plan\n'
             'root=Path(sys.argv[1]);p=root/"project";p.mkdir();(p/"a.txt").write_text("fixture\\n")\n'
             'contract=runpy.run_path(sys.argv[2])["contract"]("a.txt","Kiểm lệnh owner trên sổ thử riêng")\n'
             'ledger=Ledger(p,root/"state");value=plan.propose(ledger,"OWNER-CHECK",contract,"fixture",workflow=True)\n'
             'print(json.dumps(value))')
    result = subprocess.run([str(python), '-I', '-X', 'utf8', '-c', setup, str(output), str(scenario)],
                            env=env, cwd=output, capture_output=True, text=True, encoding='utf-8', timeout=90)
    if result.returncode: raise ValueError(result.stdout + result.stderr)
    identity_code = ('import hashlib,importlib.metadata,json,sys\nfrom pathlib import Path\n'
                     'from onecrew.v2 import owner_cli\n'
                     'p=Path(owner_cli.__file__).resolve();assert p.is_relative_to(Path(sys.prefix).resolve())\n'
                     'd=importlib.metadata.distribution("onecrew")\n'
                     'print(json.dumps({"version":d.version,"owner_cli":str(p),"sha256":hashlib.sha256(p.read_bytes()).hexdigest(),'
                     '"direct_url":json.loads(d.read_text("direct_url.json"))}))')
    identity = subprocess.run([str(python), '-I', '-X', 'utf8', '-c', identity_code],
                              env=env, cwd=output, capture_output=True, text=True, encoding='utf-8', timeout=30)
    if identity.returncode: raise ValueError(identity.stdout + identity.stderr)
    state_before = digest(output / 'state'); project_before = digest(output / 'project')
    base_before = digest(trial / 'state')
    guarded = dict(env)
    guarded.setdefault('CLAUDE_CODE_CHILD_SESSION', '1')
    report = {'kind': 'installed-owner-human-refusal-probe', 'trial': str(trial), 'fixture': str(output),
              'owner_success_tested': False, 'installed': json.loads(identity.stdout),
              'guard_forced_if_absent': 'CLAUDE_CODE_CHILD_SESSION' not in env, 'steps': [], 'pass': False}
    for human in (False, True):
        args = [str(python), '-I', '-X', 'utf8', '-m', 'onecrew.console', '--project', str(output / 'project'),
                '--state-root', str(output / 'state'), 'owner', 'approve', 'OWNER-CHECK', '--revision', '1',
                '--reference', 'Synthetic refusal probe, no approval authorized'] + (['--human'] if human else [])
        done = subprocess.run(args, env=guarded, cwd=output, capture_output=True, text=True, encoding='utf-8', timeout=90)
        good = done.returncode == 2 and 'CLAUDE_CODE_CHILD_SESSION is set' in done.stdout
        if human: good = good and 'Chưa ghi nhận' in done.stdout
        else: good = good and bool(json.loads(done.stdout).get('error'))
        report['steps'].append({'human': human, 'exit': done.returncode, 'pass': good, 'stdout': done.stdout, 'stderr': done.stderr})
    report['fixture_state_unchanged'] = digest(output / 'state') == state_before
    report['fixture_project_unchanged'] = digest(output / 'project') == project_before
    report['base_trial_state_unchanged'] = digest(trial / 'state') == base_before
    report['pass'] = all(s['pass'] for s in report['steps']) and all(report[k] for k in
        ('fixture_state_unchanged', 'fixture_project_unchanged', 'base_trial_state_unchanged'))
    (output / 'owner-human-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report['pass'] else 1


if __name__ == '__main__': raise SystemExit(main(*sys.argv[1:]))
