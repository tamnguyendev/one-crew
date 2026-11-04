"""T54.1 / T54.3 — installed-build BEHAVIOUR scenarios declared per release, one shared runner (W40 framework, review a2476ab P1).

A scenario is a declaration, not a pipeline: which release and requirements (task ids / DoD lines) it proves, which event kinds the behaviour
MUST write, and a body that runs INSIDE the installed build's venv (``-I``, cwd outside the checkout, no PYTHONPATH). The runner prepares a
fresh temporary git project + state root per scenario, prepends the helper preamble below, executes the body with the venv interpreter, and
turns what the body observed into one receipt: assertions (each with a name and a result), the event kinds really written to the ledger, the
module inventory (boundary check: every ``onecrew.*`` module from the venv, never a checkout), exit code and output tail. A scenario PASSES
only when every assertion passed, every expected event kind was written, and the boundary check is clean. A body that merely imports a module
proves nothing and cannot pass: a scenario must declare at least one assertion and at least one expected event kind, or — for a release that
adds no event — declare ``no_new_events`` with the reason and still assert the regression behaviour.

Body helpers (defined by the preamble):
    root, state            Path of the temporary git project and state root (already created; a.txt committed)
    ledger                 onecrew.ledger.Ledger(root, state)
    exe                    the venv's ``onecrew`` console script (str)
    cli(*args, expect=0)   run the console script on this project/state; returns stdout; records the step; asserts the exit code
    check(name, ok, detail='')      record an assertion (never raises; the receipt carries it)
    must(name, ok, detail='')       record and stop the body on failure (raises AssertionError)
    kinds()                sorted set of event kinds written on EVERY task of this state root so far
    git(*args)             run git in the project
    contract()             a fresh schema-2 contract dict (tests.test_v2_l1.plan_json shape, one command milestone that prints ok) — the body
                           edits it as needed (``contract(milestones=[...], **extra)`` is NOT available inside the venv; build dicts by hand
                           or edit the returned dict)
The body ends by itself; the preamble's trailer prints the observation. A body may ``raise`` — the error becomes a failed scenario with the
traceback tail in the receipt.

Register scenarios from ``tests/wf_scenarios_*.py`` modules with ``register(release, id, requirements, expected_events, body, no_new_events=None)``;
``load()`` imports every such module. ``run_release(release, python, ctx, out_dir, commit, wheel_sha256)`` runs all scenarios of a release and
returns the receipts; ``wfkit.release_bundle`` uses it for T54.1 and takes the observed kinds for T54.3.
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from tests import wf_wheel as wh

SCENARIOS = {}
RELEASES = ('R01', 'R02', 'R03', 'R04', 'R05', 'R06', 'R07', 'R08', 'RP', 'RX1', 'RX2')
_LOADED = False


def register(release, id, requirements, expected_events, body, no_new_events=None):
    """Declare one scenario. `requirements`: task ids / DoD lines it proves (nonempty). `expected_events`: kinds the body must write (nonempty
    unless `no_new_events` gives the reason the release adds none — the body then asserts the regression behaviour instead)."""
    if release not in RELEASES: raise ValueError('unknown release ' + str(release))
    if not re.fullmatch(r'[A-Za-z0-9_.-]{3,80}', id): raise ValueError('scenario id must be a short slug: ' + str(id))
    if not requirements or not all(isinstance(r, str) and r.strip() for r in requirements): raise ValueError(id + ': requirements must name what is proven')
    if not expected_events and not no_new_events: raise ValueError(id + ': declare expected event kinds, or no_new_events with the reason')
    if expected_events and no_new_events: raise ValueError(id + ': expected_events and no_new_events exclude each other')
    if not isinstance(body, str) or 'check(' not in body and 'must(' not in body: raise ValueError(id + ': the body must record at least one assertion')
    # T54.1 reads the task a requirement proves as its FIRST whitespace token (release_check.installed). A DoD line without a task is allowed
    # (the release's tasks must be covered across its scenarios), but a token that LOOKS like a task and is not one ("W17:", "W36/W18")
    # would silently prove nothing — refused here, at declaration.
    for t in (r.split()[0] for r in requirements):
        if re.match(r'W\d', t) and not re.fullmatch(r'W\d+[a-z]?', t):
            raise ValueError(id + ': a requirement names its task id as a clean first token followed by a space (W12b text), not ' + t)
    entries = SCENARIOS.setdefault(release, [])
    if any(e['id'] == id for e in entries): raise ValueError('duplicate scenario id ' + id)
    entries.append({'release': release, 'id': id, 'requirements': list(requirements), 'expected_events': sorted(set(expected_events or [])),
                    'no_new_events': no_new_events, 'body': body})


def load():
    """Import every tests/wf_scenarios_*.py once (they call register at import)."""
    global _LOADED
    if _LOADED: return SCENARIOS
    here = Path(__file__).resolve().parent
    for module in sorted(p.stem for p in here.glob('wf_scenarios_*.py')):
        __import__('tests.' + module)
    _LOADED = True
    return SCENARIOS


def scenarios(release):
    return list(load().get(release, []))


PREAMBLE = r'''
import json, os, subprocess, sys, traceback
from pathlib import Path
for _key in ('ONECREW_ACTOR', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION'): os.environ.pop(_key, None)
root, state = Path(__ROOT__), Path(__STATE__)
exe = __EXE__
_obs = {'assertions': [], 'steps': [], 'error': None}
def check(name, ok, detail=''):
    _obs['assertions'].append({'name': str(name), 'ok': bool(ok), 'detail': str(detail)[:400]})
    return bool(ok)
def must(name, ok, detail=''):
    if not check(name, ok, detail): raise AssertionError(str(name) + ': ' + str(detail)[:300])
def git(*args):
    return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True, encoding='utf-8', errors='replace').stdout
def cli(*args, expect=0):
    done = subprocess.run([exe, '--project', str(root), '--state-root', str(state), *args], capture_output=True, text=True, encoding='utf-8',
                          errors='replace', env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'})
    _obs['steps'].append({'command': ['onecrew', *args], 'exit_code': done.returncode, 'tail': (done.stdout + done.stderr)[-300:]})
    must('cli ' + ' '.join(args) + ' exits ' + str(expect), done.returncode == expect, (done.stdout + done.stderr)[-400:])
    return done.stdout
def kinds():
    import sqlite3
    conn = sqlite3.connect((state / 'ledger.sqlite3').as_uri() + '?mode=ro', uri=True)
    try: return sorted({r[0] for r in conn.execute('SELECT DISTINCT kind FROM events')})
    finally: conn.close()
def event_samples():
    import sqlite3
    conn = sqlite3.connect((state / 'ledger.sqlite3').as_uri() + '?mode=ro', uri=True)
    try:
        samples = {}
        for kind, payload, anchor in conn.execute('SELECT e.kind, e.payload, t.request_key FROM events e JOIN tasks t ON t.id = e.task_id ORDER BY e.seq'):
            if kind not in samples:
                try: value = json.loads(payload) if payload else {}
                except ValueError: value = {'unparsed': True}
                samples[kind] = {'kind': kind, 'payload': value, 'anchor': anchor or ''}
        return list(samples.values())
    finally: conn.close()
def contract():
    return json.loads(__CONTRACT__)
from onecrew.ledger import Ledger, LedgerError
ledger = Ledger(root, state)
try:
    exec(compile(__BODY__, '<scenario>', 'exec'))
except BaseException as _error:
    _obs['error'] = traceback.format_exc()[-1500:]
try:
    _written = kinds(); _samples = event_samples()
except Exception as _error:
    _written = []; _samples = []; _obs['kinds_error'] = str(_error)[:200]
import _imp
_mods = {}
for _n, _m in list(sys.modules.items()):
    _spec = getattr(_m, '__spec__', None)
    _mods[_n] = {'file': getattr(_m, '__file__', None), 'origin': getattr(_spec, 'origin', None) if _spec else None,
                 'frozen': bool(_imp.is_frozen(_n)), 'builtin': _n in sys.builtin_module_names}
print('@@SCN@@' + json.dumps({'observation': _obs, 'kinds': _written, 'modules': _mods, 'events': _samples}, default=str))
'''


def _contract(python_for_argv):
    sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from test_v2_l1 import plan_json
    value = plan_json()
    value['milestones'][0]['verifier']['config']['argv'] = [str(python_for_argv), '-c', 'print("ok")']
    return value


def run_scenario(entry, python, ctx, out_dir, commit, wheel_sha256):
    """One scenario on the installed build: returns the receipt dict (release_check reads it inside the `installed` receipt)."""
    python = Path(python); out_dir = Path(out_dir)
    work = out_dir / entry['id']; work.mkdir(parents=True)
    project, state = work / 'project', work / 'state'; project.mkdir()
    for args in (['init', '-q'], ['config', 'user.name', 'scenario'], ['config', 'user.email', 'scenario@localhost']):
        subprocess.run(['git', '-C', str(project), *args], check=True, capture_output=True)
    (project / 'a.txt').write_text('base\n', encoding='utf-8')
    subprocess.run(['git', '-C', str(project), 'add', '.'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(project), 'commit', '-qm', 'base'], check=True, capture_output=True)
    exe = python.with_name('onecrew' + ('.exe' if os.name == 'nt' else ''))
    code = (PREAMBLE.replace('__ROOT__', repr(str(project))).replace('__STATE__', repr(str(state))).replace('__EXE__', repr(str(exe)))
            .replace('__CONTRACT__', repr(json.dumps(_contract(python)))).replace('__BODY__', repr(entry['body'])))
    (work / 'scenario.py').write_text(code, encoding='utf-8', newline='\n')
    env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP', 'ONECREW_ACTOR', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION')}
    env.update({'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'})
    started = time.monotonic()
    done = subprocess.run([str(python), '-I', '-X', 'utf8', '-c', code], capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=str(work), env=env, timeout=900)
    (work / 'stdout.txt').write_text(done.stdout, encoding='utf-8'); (work / 'stderr.txt').write_text(done.stderr, encoding='utf-8')
    line = next((l for l in done.stdout.splitlines() if l.startswith('@@SCN@@')), None)
    observed = json.loads(line[len('@@SCN@@'):]) if line else {'observation': {'assertions': [], 'steps': [], 'error': 'no observation: ' + (done.stderr or done.stdout)[-600:]}, 'kinds': [], 'modules': {}, 'events': []}
    from onecrew.v2 import boundary
    violations = boundary.violations(observed['modules'], ctx) if observed['modules'] else ['no onecrew module was loaded']
    obs = observed['observation']
    missing_events = sorted(set(entry['expected_events']) - set(observed['kinds']))
    failed = [a for a in obs['assertions'] if not a['ok']]
    reasons = []
    if obs.get('error'): reasons.append('body error: ' + obs['error'][-300:])
    if not obs['assertions']: reasons.append('no assertion recorded (an import proves nothing)')
    if failed: reasons.append('failed assertions: ' + ', '.join(a['name'] for a in failed)[:300])
    if missing_events: reasons.append('expected events not written: ' + ', '.join(missing_events))
    if violations: reasons.append('module boundary violations: ' + '; '.join(violations[:3]))
    if done.returncode != 0 and not reasons: reasons.append(f'interpreter exit {done.returncode}')
    return {'kind': 'behavior', 'scenario': entry['id'], 'release': entry['release'], 'requirements': entry['requirements'],
            'expected_events': entry['expected_events'], 'no_new_events': entry['no_new_events'], 'observed_events': observed['kinds'],
            'missing_events': missing_events, 'assertions': obs['assertions'], 'steps': obs['steps'], 'error': obs.get('error'), 'event_samples': observed.get('events', []),
            'boundary_violations': violations, 'exit_code': done.returncode, 'seconds': round(time.monotonic() - started, 1),
            'result': 'pass' if not reasons else 'fail', 'reasons': reasons, 'command': [str(python), '-I', '-X', 'utf8', '-c', '<scenario.py>'],
            'script': str(work / 'scenario.py'), 'state_root': str(state), 'project': str(project), 'commit': commit, 'wheel_sha256': wheel_sha256,
            'modules': [{'name': n, 'path': info.get('file')} for n, info in sorted(observed['modules'].items()) if (n == 'onecrew' or n.startswith('onecrew.')) and info.get('file')]}


def run_release(release, python, ctx, out_dir, commit, wheel_sha256):
    return [run_scenario(e, python, ctx, out_dir, commit, wheel_sha256) for e in scenarios(release)]
