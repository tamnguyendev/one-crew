"""2.3-B (L1) helper: a real controller process for the cleanup/takeover tests, and the local fixture worker they share.

Run as a script by tests/test_v23_b_*.py:  python -X utf8 tests/v23_b_controller.py '<json config>'
The controller opens the fixture ledger and runs the REAL engine (step or batch) with the REAL ManagedExecutor (or NativeExecutor) and a
local worker that runs under the REAL Supervisor (suspended create, named Windows Job, launch token before resume). No provider is called.

The worker (native python) spawns a sleeping grandchild in the same Job, appends one line `launched <attempt>` to the operations file,
writes `<started>/<attempt>.json` with its own and the grandchild's pid, sleeps `seconds`, then writes answer.json and exits 0.

Config keys: project, state, plan ('P1'), mode ('step' | 'batch' | 'native-step'), target (node id or null), slots (1|2), seconds,
timeout, ops (file), started (directory), crash_on_start (bool: os._exit(41) as soon as a worker of THIS controller started),
go (optional file: wait for it before calling the engine, so two controllers start together), out (optional file: the JSON result).
"""
import json
import os
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

WORKER = r'''
import json, os, pathlib, subprocess, sys, time
ops, started, seconds, answer, attempt = sys.argv[1:6]
grandchild = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'])
with open(ops, 'a', encoding='utf-8') as out: out.write('launched ' + attempt + '\n')
pathlib.Path(started).write_text(json.dumps({'worker': os.getpid(), 'grandchild': grandchild.pid}))
time.sleep(float(seconds))
pathlib.Path('answer.json').write_text(answer)
'''


def make_factory(ledger, cfg, launches=None):
    """The local fixture worker factory (also used in-process by the tests, with `launches` collecting attempt ids)."""
    from onecrew.process_core import Supervisor, native_python
    from onecrew.subscription import environment
    started = Path(cfg['started'])

    def factory(control, provider):
        class Worker:
            def capability(self):
                return {'provider': provider, 'mode': 'v23-b-local-fixture-no-provider'}

            def run(self, attempt, prompt, schema, profile):
                if launches is not None: launches.append(attempt['id'])
                directory = ledger.state_root / 'worker-io' / attempt['id']
                directory.mkdir(parents=True)
                files = schema.get('properties', {}).get('files')
                if files:
                    paths = files['items']['properties']['path']['enum']
                    value = {'summary': 'v23-b fixture', 'files': [{'path': p, 'content': 'candidate ' + attempt['id'] + '\n'} for p in paths],
                             'backlog': []}
                else:
                    value = {'summary': 'v23-b fixture report', 'evidence': []}
                timeout = min(float(cfg.get('timeout', 60)), float(profile['step_seconds']))
                return Supervisor(control).run(attempt, [native_python(), '-c', WORKER, str(cfg['ops']), str(started / (attempt['id'] + '.json')),
                                                         str(cfg.get('seconds', 0.2)), json.dumps(value), attempt['id']],
                                               cwd=directory, timeout=timeout, env=environment())

            def result(self, attempt):
                return json.loads((ledger.state_root / 'worker-io' / attempt['id'] / 'answer.json').read_text()), []
        return Worker()
    return factory


def _crash_when_started(started, before):
    def watch():
        while True:
            if set(os.listdir(started)) - before:
                os._exit(41)                                   # the controller dies while its worker runs
            time.sleep(.02)
    threading.Thread(target=watch, daemon=True).start()


def main(cfg):
    from onecrew.ledger import Ledger
    from onecrew.v2 import engine
    from onecrew.v2.managed_executor import ManagedExecutor
    ledger = Ledger(Path(cfg['project']), Path(cfg['state']))
    factory = make_factory(ledger, cfg)
    if cfg.get('mode') == 'native-step':
        from onecrew.common_executor import NativeExecutor
        adapter = NativeExecutor(ledger, worker_factory=factory)
    else:
        adapter = ManagedExecutor(ledger, worker_factory=factory)
    started = Path(cfg['started']); started.mkdir(parents=True, exist_ok=True)
    if cfg.get('crash_on_start'):
        _crash_when_started(started, set(os.listdir(started)))
    if cfg.get('go'):
        Path(cfg['go'] + '.ready-' + str(os.getpid())).write_text('ready')
        until = time.monotonic() + 60
        while not Path(cfg['go']).exists() and time.monotonic() < until: time.sleep(.005)
    if cfg.get('mode') == 'batch':
        result = engine.run_batch(ledger, cfg.get('plan', 'P1'), adapter, slots=cfg.get('slots', 1))
    else:
        result = engine.step(ledger, cfg.get('plan', 'P1'), adapter, slots=cfg.get('slots', 1), _target=cfg.get('target'))
    text = json.dumps(result, default=str)
    if cfg.get('out'): Path(cfg['out']).write_text(text, encoding='utf-8')
    print(text, flush=True)


if __name__ == '__main__':
    sys.path.insert(0, str(REPO))
    main(json.loads(sys.argv[1]))
