"""compare_wiki.py <out.json> [--repeat N] [--real-model MODEL --real-repeat N] - 2.3-A1 KE-01 (MEM-05): the same task under four
knowledge conditions, run from the INSTALLED wheel of this checkout (fresh venv, scenario process with -I, cwd outside the checkout).

Conditions (same task, input, acceptance, node, pin, cap, harness and machine; only the wiki differs):
  none     no wiki                                     the check expects "right": the worker has no way to know it
  correct  verified fact "right", source unchanged     the check expects "right"
  stale    fact "right" recorded against an older a.txt; a.txt changed and now says the required word is "bright"
           (A1 delivers it as a lead, `recheck`)       the check expects "bright"
  wrong    verified fact "wrong", source unchanged     the check expects "right": a wiki that is simply wrong
Measured per run: verdict of the node's real command check, seconds of the step (dispatch to candidate), prompt and knowledge characters,
the uses delivered, what the worker declared it relied on, and `misled` = the check failed while the worker relied on a delivered entry.
"Rework needed" = the first candidate failed its check (the repair loop is not run here). The FAKE claude (tests/v23_fake_claude.py)
is a deterministic policy: its rows prove the plumbing and the labels, not model behaviour. `--real-model` runs the real Claude Code CLI
already logged in on this machine (subscription auth; the adapter strips API keys), bounded by --real-repeat; it is skipped unless asked.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
for name in ('CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION', 'ONECREW_ACTOR'):
    os.environ.pop(name, None)

from tests import v23_harness as hx      # noqa: E402
from tests import wf_wheel as wh         # noqa: E402
from tests.test_v2_l1 import plan_json   # noqa: E402
from tests.test_wf_engine import node    # noqa: E402

BODY = r'''
import json, os, subprocess, sys, time
from pathlib import Path
from onecrew.ledger import Ledger
from onecrew.snapshots import Snapshots
from onecrew.common_executor import NativeExecutor
from onecrew.common_verification import CandidateChecker
from onecrew.v2 import plan, engine, internal_plan
work = Path(WORK); condition = CONDITION
root = work / 'project'; root.mkdir()
def git(*args): return subprocess.run(['git','-C',str(root),*args],check=True,capture_output=True,text=True).stdout.strip()
git('init','-q'); git('config','user.name','fixture'); git('config','user.email','fixture@localhost')
(root/'a.txt').write_text('base\n'); (root/'.gitignore').write_text('.onecrew/\n')
git('add','.'); git('commit','-qm','base'); old = git('rev-parse','HEAD')
expected = 'right'
if condition == 'stale':
    (root/'a.txt').write_text('The required word is now bright.\n'); git('commit','-qam','requirement changed'); expected = 'bright'
head = git('rev-parse','HEAD')
if condition != 'none':
    value = 'wrong' if condition == 'wrong' else 'right'
    meta = {'id': 'a-word', 'kind': 'constraint', 'label': 'verified', 'must': True, 'applies_to': ['a.txt'],
            'sources': [{'type': 'file', 'path': 'a.txt', 'revision': old if condition == 'stale' else head}]}
    (root/'docs'/'wiki').mkdir(parents=True)
    (root/'docs'/'wiki'/'rules.md').write_text('## Required word in a.txt\n```onecrew\n' + json.dumps(meta) + '\n```\n'
        f'a.txt must contain exactly one lowercase word: {value} (VALUE: {value}).\n', encoding='utf-8')
    git('add','.'); git('commit','-qm','wiki')
ledger = Ledger(root, work/'state')
contract = json.loads(CONTRACT)
contract['milestones'][0]['verifier']['config']['argv'] = [sys.executable, '-c', f'from pathlib import Path; v = Path("a.txt").read_text().strip().lower(); assert v == "{expected}", v; print("ok")']
plan.propose(ledger, 'P1', contract, 'codex', workflow=True, capabilities=['namespaced-storage','root-budget','internal-plan','sequential-engine'])
plan.approve(ledger, 'P1', 'owner', 'temporary comparison fixture')
internal_plan.revise(ledger, 'P1', json.loads(DEFINITION), reason='Wiki comparison fixture', evidence=['a.txt:1'])
started = time.perf_counter()
produced = engine.step(ledger, 'P1', NativeExecutor(ledger))
seconds = time.perf_counter() - started
out = {'condition': condition, 'state': produced['state'], 'seconds': round(seconds, 3)}
if produced['state'] == 'produced':
    verdict = engine.verify(ledger, 'P1', 'C', CandidateChecker(ledger, 'P1'))
    store = Snapshots(ledger.state_root)
    receipt = json.loads(store.read_blob(produced['receipt']))
    view = json.loads(store.read_blob(receipt['knowledge']['package'])) if receipt['knowledge'].get('package') else None
    written = store.context(produced['artifact']).get('a.txt')
    out.update(verdict=verdict['result'], written=(written or '').strip()[:80], prompt_chars=receipt.get('prompt_chars'),
               knowledge_chars=receipt['knowledge'].get('chars', 0),
               delivered=[[e['id'], e['use'], e['applicability']['state']] for e in (view or {}).get('entries', [])],
               declared_used=receipt['knowledge_use']['used'], violations=receipt['knowledge_use']['violations'],
               usage=receipt.get('usage'))
    out['misled'] = out['verdict'] != 'pass' and bool(out['declared_used'])
    out['rework_needed'] = out['verdict'] != 'pass'
Path(OUT).write_text(json.dumps(out, ensure_ascii=False), encoding='utf-8')
'''


def run(python, work, condition, model, fake, timeout_cap):
    work.mkdir(parents=True)
    item = node('C', write=('a.txt',))
    item['goal'] = 'Write a.txt containing the word the project requires.'
    item['checks'] = [{'id': 'M1', 'spec': 'a.txt holds the required word.'}]
    item['executor'] = {'role': 'worker', 'provider': 'claude', 'model': model}
    item['execution_cap_seconds'] = timeout_cap; item['estimate_seconds'] = [1, timeout_cap]
    integration = node('I', ['C'], integration=True, write=())
    integration['checks'] = [{'id': 'M1', 'spec': 'Integration keeps a.txt.'}]
    contract = plan_json(authority={'edit': True, 'commands': True, 'unconfined_commands': True,
                                    'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q9', 'Q12']})
    out = work / 'out.json'
    body = (BODY.replace('WORK', repr(str(work))).replace('CONDITION', repr(condition)).replace('OUT', repr(str(out)))
            .replace('CONTRACT', repr(json.dumps(contract))).replace('DEFINITION', repr(json.dumps([item, integration]))))
    if fake:
        policy = work / 'policy.json'; policy.write_text(json.dumps({'target': 'a.txt', 'default': 'naive', 'careful': True}))
        env = hx.scenario_env(python, work, policy=policy, log=work / 'fake.jsonl')
    else:
        env = {'PATH': os.environ.get('PATH', '')}            # the real claude on PATH or ~/.local/bin; real user profile for its login
    dump, tail = wh.run_case(python, body, env_extra=env, cwd=work)
    if not out.exists(): return {'condition': condition, 'error': tail[-400:]}
    return json.loads(out.read_text(encoding='utf-8'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('out'); parser.add_argument('--repeat', type=int, default=2)
    parser.add_argument('--real-model'); parser.add_argument('--real-repeat', type=int, default=1)
    args = parser.parse_args()
    runs, python, wheel, ctx = hx.runtime('ke01')
    wheel_sha = __import__('hashlib').sha256(Path(wheel).read_bytes()).hexdigest()
    rows = []
    try:
        for condition in ('none', 'correct', 'stale', 'wrong'):
            for i in range(args.repeat):
                rows.append(dict(run(python, runs / f'fake-{condition}-{i}', condition, 'claude-haiku-5-5', True, 60), provider='fake', repeat=i))
                print(json.dumps(rows[-1], ensure_ascii=False)[:400], flush=True)
        if args.real_model:
            for condition in ('none', 'correct', 'stale', 'wrong'):
                for i in range(args.real_repeat):
                    rows.append(dict(run(python, runs / f'real-{condition}-{i}', condition, args.real_model, False, 300), provider='claude-cli', repeat=i))
                    print(json.dumps(rows[-1], ensure_ascii=False)[:400], flush=True)
    finally:
        hx.cleanup(runs)
    result = {'kind': 'v23-ke01-wiki-comparison', 'checkout': subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip(),
              'dirty': bool(subprocess.run(['git', '-C', str(ROOT), 'status', '--porcelain', '--', 'onecrew', 'pyproject.toml'], capture_output=True, text=True).stdout.strip()),
              'wheel_sha256_built_for_run': wheel_sha, 'rows': rows,
              'limits': 'fake rows: deterministic test double, plumbing only; real rows: one task, few repeats, no statistical claim'}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main()
