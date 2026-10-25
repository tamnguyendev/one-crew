"""Append-only development check registry; never relabels regressions as acceptance.

python -m wfkit.development_gate list
python -m wfkit.development_gate run R04,R05,KN --out <temporary output>
python -m wfkit.development_gate freeze R04,R05,KN
python -m wfkit.development_gate snapshot R01,...,PL --commit <sha> --out <temporary output>   (the final gate: one clean commit)

Uses the original kit guard, wheel builder, installed-origin check and test
runner. Separate development pins do not replace or waive historical pins.
Partial, missing or externally blocked source criteria refuse release delivery,
even when every selected implementation check passes. No provider calls or
live-ledger actions are performed by this runner. Its registered tests use
disposable fixtures; fake providers prove interfaces only.
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from wfkit import gate, kitguard

ROOT = Path(__file__).resolve().parents[1]
CONFIG = 'wfkit/development-testcases.json'
MANIFEST = 'wfkit/development-manifest.json'
STATES = {'partial', 'blocked', 'missing', 'complete'}

# Scope of every problem kind this gate writes (Codex round 6 P1-2). The ONE classification; wfkit.delivery_gate imports it.
#   GLOBAL  - about the build, the kit, the install, the document self-check, the run selection or the snapshot itself: it blocks the delivery
#             gate of EVERY release judged on this snapshot.
#   RELEASE - one testcase of one release is not complete (acceptance-<status>, with release + testcase): it blocks only that release (03 s4).
# Any other kind, or a release problem without release/testcase, is unclassified: consumers must refuse, never treat it as clean.
SNAPSHOT_PROBLEMS = frozenset({'snapshot-moved', 'snapshot-dirty', 'external-source-changed'})     # written by intact()/finish()
GLOBAL_PROBLEMS = frozenset({'dirty-build', 'missing-build', 'kit-guard', 'document-selfcheck', 'installed-origin', 'implementation-checks',
                             'selected-only'}) | SNAPSHOT_PROBLEMS
RELEASE_PROBLEMS = frozenset('acceptance-' + state for state in STATES - {'complete'})


def problem_scope(problem):
    """'global' | 'release' | None (unknown or malformed: refuse)."""
    if not isinstance(problem, dict): return None
    kind = problem.get('kind')
    if kind in GLOBAL_PROBLEMS: return 'global'
    if kind in RELEASE_PROBLEMS and isinstance(problem.get('release'), str) and isinstance(problem.get('testcase'), str): return 'release'
    return None


def _classified(problems):
    """Every problem this gate writes must be classified; an unclassified one is a defect of the gate, not a pass."""
    unknown = [p for p in problems if problem_scope(p) is None]
    if unknown: raise ValueError('unclassified snapshot-gate problem kinds: ' + ', '.join(sorted({str(p.get('kind') if isinstance(p, dict) else p) for p in unknown})))
    return problems


@contextlib.contextmanager
def layout():
    """Reuse the existing guard unchanged, with a distinct append-only manifest."""
    original = kitguard.CONFIG, kitguard.MANIFEST
    kitguard.CONFIG, kitguard.MANIFEST = CONFIG, MANIFEST
    try: yield
    finally: kitguard.CONFIG, kitguard.MANIFEST = original


def load(root=ROOT):
    root = Path(root)
    config = gate._read(root / CONFIG)
    if config.get('version') != 1 or not isinstance(config.get('releases'), dict):
        raise ValueError('Unsupported development registry.')
    baseline=config.get('baseline',{})
    if baseline.get('manifest') != 'wfkit/manifest.json' or kitguard.sha256_file(root/baseline['manifest']) != baseline.get('sha256'):
        raise ValueError('Historical manifest bytes differ from the referenced baseline.')
    source=config.get('source',{})
    source_path=(root/source.get('path','')).resolve()
    if not source.get('path') or not source_path.is_relative_to(root.resolve()) or gate.hashlib.sha256(source_path.read_bytes()).hexdigest() != source.get('sha256'):
        raise ValueError('Approved testcase source differs from the registered source.')
    for release, body in config['releases'].items():
        checks = body.get('testcases')
        criteria = body.get('acceptance')
        if not isinstance(checks, dict) or not checks or not isinstance(criteria, dict) or not criteria:
            raise ValueError(release + ': nonempty implementation checks and acceptance criteria required')
        registry=checks.get('registry',{})
        if registry.get('acceptance_snapshot') != criteria or registry.get('baseline') != baseline or registry.get('source') != source:
            raise ValueError(release + ': acceptance/source must equal the case-pinned registry snapshot')
        for key, check in checks.items():
            if key.startswith('T') or check.get('kind') != 'unittest' or not check.get('modules'):
                raise ValueError('Implementation checks must have distinct non-T IDs: ' + key)
            for module in check['modules']:
                path = root / kitguard.module_path(module)
                if not module.startswith('tests.test_') or not path.resolve().is_relative_to((root/'tests').resolve()) or not path.is_file():
                    raise ValueError('Unknown or unsafe test module: ' + module)
        for case, criterion in criteria.items():
            if not case.startswith('T') or criterion.get('status') not in STATES:
                raise ValueError('Malformed source criterion: ' + case)
            if set(criterion.get('checks', [])) - set(checks):
                raise ValueError('Unknown supporting check: ' + case)
            if criterion['status'] != 'complete' and not criterion.get('gaps'):
                raise ValueError('Incomplete criterion must explain its gap: ' + case)
            if criterion['status'] == 'complete' and (not criterion.get('checks') or not criterion.get('evidence_matrix')):
                raise ValueError('Complete criterion requires reviewed per-E evidence mapping: ' + case)
    return config


def select(config, releases, only=None):
    """Reject typos and deduplicate actual module groups across release boundaries."""
    names = list(dict.fromkeys(releases))
    if not names or set(names) - set(config['releases']):
        raise ValueError('Unknown or empty release selection: ' + ','.join(names))
    checks = {}
    for release in names:
        for key, entry in config['releases'][release]['testcases'].items():
            identifier = release + '/' + key
            checks[identifier] = entry
    if only is not None:
        requested = set(only)
        if not requested or requested - set(checks):
            raise ValueError('Unknown or empty check selection: ' + ','.join(sorted(requested - set(checks))))
        checks = {key:value for key,value in checks.items() if key in requested}
    return checks


def verify(root, releases, doc_dir=None):
    historical = kitguard.verify(root, ['R00'], doc_dir=doc_dir)
    with layout(): current = kitguard.verify(root, releases, doc_dir=doc_dir)
    return {'ok':historical['ok'] and current['ok'] and not historical['unchecked'] and not current['unchecked'],
            'historical':historical, 'development':current}


def freeze(root, releases):
    config = load(root); select(config, releases)
    with layout():
        return {release:kitguard.freeze(root, release) for release in releases}


def decide(config, releases, build, receipts, install, guards, only=None, document=None):
    """The facts checked by the original gate plus explicit source-coverage gaps."""
    checks = select(config, releases)
    problems = []
    if build.get('dirty'): problems.append({'kind':'dirty-build','detail':'Working tree differs from the recorded commit.'})
    if not build.get('wheel_sha256') or not build.get('commit'):
        problems.append({'kind':'missing-build','detail':'Commit and wheel identity are required.'})
    if not guards.get('ok'):
        problems.append({'kind':'kit-guard','detail':'Historical or development pins refused; no pin is waived.'})
    document=document or {}
    if not (document.get('result')=='pass' and document.get('problems')==0 and document.get('block_sha256')
            and document.get('kit_guard',{}).get('ok') and not document.get('counterexamples',{}).get('missed')
            and not document.get('counterexamples',{}).get('wrong_reason')):
        problems.append({'kind':'document-selfcheck','detail':'Required T38a document self-check has no valid passing receipt.'})
    if not install.get('ok') or not install.get('control_refused') or install.get('wheel_sha256') != build.get('wheel_sha256'):
        problems.append({'kind':'installed-origin','detail':'Installed wheel and rejected checkout control are required.'})
    failed = []
    for key, entry in checks.items():
        receipt = receipts.get(key)
        reason = None
        if not receipt: reason = 'missing receipt'
        elif receipt.get('commit') != build.get('commit') or receipt.get('wheel_sha256') != build.get('wheel_sha256'):
            reason = 'wrong build identity'
        elif receipt.get('simulated') or not gate._counts_pass(receipt, 0): reason = 'not a real passing test execution (skips forbidden)'
        elif any(value != build['wheel_sha256'] for value in receipt.get('wheel_used', [])): reason = 'test consumed a different wheel'
        elif entry.get('installed') and not receipt.get('wheel_used'): reason = 'installed check did not record consuming the final wheel'
        if reason: failed.append({'check':key,'reason':reason})
    if failed: problems.append({'kind':'implementation-checks','failures':failed})
    if only is not None: problems.append({'kind':'selected-only','detail':'A partial run cannot qualify a release.'})
    acceptance = {}
    for release in releases:
        acceptance[release] = config['releases'][release]['acceptance']
        for case, criterion in acceptance[release].items():
            if criterion['status'] != 'complete':
                problems.append({'kind':'acceptance-'+criterion['status'],'release':release,'testcase':case,'gaps':criterion['gaps']})
    _classified(problems)
    return {'decision':'refused' if problems else 'pass', 'release_delivery':not problems,
            'owner_acceptance':False, 'pilot_passed':False, 'releases':releases,
            'implementation_checks':{'expected':len(checks),'receipted':len(receipts),'failed':failed},
            'acceptance':acceptance, 'problems':problems, 'commit':build.get('commit'),
            'wheel_sha256':build.get('wheel_sha256'), 'at':gate._now()}


def run(root, releases, out, only=None, doc_dir=None):
    from tests import wf_wheel as wheel
    root, out = Path(root).resolve(), Path(out).resolve()
    if root != ROOT: raise ValueError('Execution uses this checkout only.')
    if out.exists() or not out.is_relative_to(Path(tempfile.gettempdir()).resolve()):
        raise ValueError('Output must be a NEW directory under OS temp.')
    config = load(root); checks = select(config, releases, only)
    out.mkdir(parents=True)
    guards = verify(root, releases, doc_dir)
    gate._write(out/'kitguard.json',guards)
    wheel_dir=out/'wheel'; wheel_dir.mkdir()
    # Always produce one fresh final wheel; all installed tests receive these bytes.
    previous=os.environ.pop('WF_WHEEL',None)
    try: artifact,version,_ = wheel.build_wheel(wheel_dir)
    finally:
        if previous is not None: os.environ['WF_WHEEL']=previous
    build={'commit':gate._git(root,'rev-parse','HEAD'),'dirty':gate.dirty_files(root,out),
           'wheel':str(artifact),'wheel_sha256':gate.hashlib.sha256(artifact.read_bytes()).hexdigest(),
           'version':version,'at':gate._now()}
    gate._write(out/'build.json',build)
    python=wheel.make_venv(out); wheel.install(python,artifact)
    install=gate.check_install(python,root,out); install['wheel_sha256']=build['wheel_sha256']
    gate._write(out/'install.json',install)
    from . import namespace_lineage
    try:
        lineage=namespace_lineage.execute(root,python,artifact,out/'namespace-lineage')
        succession=namespace_lineage.assess(guards['historical'],lineage['record'],lineage,build['wheel_sha256'])
        guards['namespace_lineage']=succession
        guards['ok']=succession['ok'] and guards['development']['ok'] and not guards['development']['unchecked']
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as error:
        guards['namespace_lineage']={'ok':False,'error':str(error)}
        guards['ok']=False
    gate._write(out/'kitguard.json',guards)
    document=gate.doccheck.run(doc_dir,root) if doc_dir and only is None else {}
    gate._write(out/'document-selfcheck.json',document)
    receipts,cache={},{}
    for key, entry in checks.items():
        modules=tuple(entry['modules'])
        print('check '+key+': '+', '.join(modules),flush=True)
        if modules not in cache:
            tag=key.replace('/','-')
            cache[modules]=gate.run_unittests(root,['-v',*modules],artifact,build['wheel_sha256'],out,tag,sys.executable)
        receipt=dict(cache[modules], check=key, commit=build['commit'],wheel_sha256=build['wheel_sha256'],
                     scope='implementation regression; source acceptance evaluated separately')
        receipts[key]=receipt
        gate._write(out/'receipts'/(key.replace('/','-')+'.json'),receipt)
    decision=decide(config,releases,build,receipts,install,guards,only,document)
    gate._write(out/'decision.json',decision)
    return decision


# ---- snapshot gate (Codex review 9aca8be, P2): one commit, one clean detached worktree, nothing else ----------------------------------
#
# `run` tests whatever is in the checkout it is started from and stamps HEAD on the receipts; started from a working tree that is being
# edited, its receipts describe no single commit. `snapshot` prepares a detached worktree of exactly one commit, fingerprints the sources
# outside the repository that the gate reads (the document folder of the doc self-check, the interpreter), runs `run` INSIDE that
# worktree (so code, tests, helpers, registry, manifest and the wheel all come from the same commit) and refuses the result when the
# snapshot moved during the run. Receipts of earlier working-tree runs keep their labels; they are not re-labelled as this.

def fingerprint(directory):
    """{relative path: sha256} of every file under `directory` (sorted); None when there is no such directory."""
    base = Path(directory) if directory else None
    if base is None or not base.is_dir(): return None
    out = {}
    for path in sorted(p for p in base.rglob('*') if p.is_file()):
        out[path.relative_to(base).as_posix()] = kitguard.sha256_file(path)
    return out


def _status(tree):
    status = gate._git(tree, 'status', '--porcelain', '--untracked-files=normal')
    return None if status is None else [line for line in status.splitlines() if line.strip()]


def prepare(repo, commit, out, doc_dir=None):
    """A detached worktree of `commit` under `out`/snapshot, clean, plus the fingerprints the finish step compares against."""
    out = Path(out).resolve()
    if out.exists() or not out.is_relative_to(Path(tempfile.gettempdir()).resolve()):
        raise ValueError('Output must be a NEW directory under OS temp.')
    resolved = gate._git(repo, 'rev-parse', '--verify', '-q', '--end-of-options', str(commit) + '^{commit}')
    if not resolved: raise ValueError(f'{commit!r} is not a commit of {repo}.')
    out.mkdir(parents=True)
    tree = out / 'snapshot'
    r = subprocess.run(['git', '-C', str(repo), 'worktree', 'add', '--detach', str(tree), resolved], capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode != 0: raise ValueError('git worktree add failed: ' + (r.stderr or r.stdout).strip()[:300])
    head, status = gate._git(tree, 'rev-parse', 'HEAD'), _status(tree)
    if head != resolved or status: raise ValueError(f'snapshot is not clean at {resolved[:12]}: HEAD {head}, status {status}')
    prepared = {'repo': str(Path(repo).resolve()), 'requested': str(commit), 'commit': resolved, 'tree': str(tree), 'out': str(out),
                'doc_dir': str(Path(doc_dir).resolve()) if doc_dir else None, 'doc_fingerprint': fingerprint(doc_dir),
                'python': {'path': sys.executable, 'sha256': kitguard.sha256_file(sys.executable) if os.path.isfile(sys.executable) else None,
                           'version': sys.version.split()[0]},
                'status_at_start': status, 'prepared_at': gate._now()}
    gate._write(out / 'snapshot.json', prepared)
    return prepared


def intact(prepared, tree=None):
    """What changed since prepare (empty list = intact): HEAD, the working tree of the snapshot, the document folder fingerprint."""
    tree = Path(tree or prepared['tree'])
    problems = []
    head = gate._git(tree, 'rev-parse', 'HEAD')
    if head != prepared['commit']: problems.append({'kind': 'snapshot-moved', 'detail': f'HEAD {head} is not the prepared commit {prepared["commit"]}'})
    status = _status(tree)
    if status is None or status: problems.append({'kind': 'snapshot-dirty', 'detail': 'the snapshot worktree changed during the run: ' + ', '.join(status or ['status unavailable'])[:300]})
    if prepared.get('doc_dir') and fingerprint(prepared['doc_dir']) != prepared.get('doc_fingerprint'):
        problems.append({'kind': 'external-source-changed', 'detail': 'the document folder the self-check reads changed during the run'})
    return problems


def finish(prepared, decision, problems):
    """The decision of the snapshot run: the gate's own, refused when the snapshot did not stay intact. Nothing is re-labelled."""
    decision = dict(decision or {'decision': 'refused', 'problems': [], 'error': 'the gate produced no decision'})
    decision['snapshot'] = {k: prepared[k] for k in ('commit', 'requested', 'tree', 'doc_dir', 'python', 'prepared_at')}
    decision['snapshot']['intact'] = not problems
    if problems:
        decision['decision'] = 'refused'; decision['release_delivery'] = False
        decision['problems'] = list(decision.get('problems') or []) + _classified(problems)
    return decision


def snapshot(commit, releases, out, doc_dir=None, keep=False, repo=None):
    """Prepare the snapshot, run `run` inside it as a subprocess, check the snapshot stayed intact, write `out`/decision.json."""
    repo = Path(repo or ROOT)
    prepared = prepare(repo, commit, out, doc_dir)
    out, tree = Path(prepared['out']), Path(prepared['tree'])
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(['.', 'tests']))
    for marker in ('CLAUDE_CODE_CHILD_SESSION', 'CLAUDECODE'): env.pop(marker, None)     # owner verbs on disposable ledgers run from a plain shell
    argv = [sys.executable, '-X', 'utf8', '-m', 'wfkit.development_gate', 'run', ','.join(releases), '--out', str(out / 'gate')]
    if doc_dir: argv += ['--doc-dir', str(doc_dir)]
    log = out / 'gate-run.log'
    with open(log, 'w', encoding='utf-8') as handle:
        code = subprocess.run(argv, cwd=str(tree), env=env, stdout=handle, stderr=subprocess.STDOUT).returncode
    problems = intact(prepared)
    decision = gate._read(out / 'gate' / 'decision.json') if (out / 'gate' / 'decision.json').exists() else None
    result = finish(prepared, decision, problems)
    result['snapshot']['gate_exit_code'] = code; result['snapshot']['log'] = str(log)
    gate._write(out / 'decision.json', result)
    if not keep:
        subprocess.run(['git', '-C', str(repo), 'worktree', 'remove', '--force', str(tree)], capture_output=True)
        subprocess.run(['git', '-C', str(repo), 'worktree', 'prune'], capture_output=True)
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['list','freeze','run','snapshot']); parser.add_argument('releases',nargs='?')
    parser.add_argument('--out'); parser.add_argument('--only')
    parser.add_argument('--doc-dir',default=gate.doccheck.DEFAULT_DOC_DIR)
    parser.add_argument('--commit', help='snapshot: the commit to check (a clean detached worktree of it is created under --out)')
    parser.add_argument('--keep', action='store_true', help='snapshot: keep the worktree after the run')
    args=parser.parse_args(argv)
    try:
        if args.command=='list':
            print(json.dumps(load(),ensure_ascii=True,indent=1)); return 0
        releases=(args.releases or '').split(',')
        if args.command=='freeze':
            result=freeze(ROOT,releases); print(json.dumps(result)); return 0 if all(r['ok'] for r in result.values()) else 1
        if args.command=='snapshot':
            if not args.out or not args.commit: raise ValueError('--out and --commit are required for snapshot')
            result=snapshot(args.commit,releases,args.out,args.doc_dir,keep=args.keep)
            print(json.dumps({'decision':result['decision'],'snapshot':result['snapshot'],'receipt':str(Path(args.out)/'decision.json'),'owner_acceptance':False}))
            return 0 if result.get('release_delivery') else 1
        if not args.out: raise ValueError('--out is required for run')
        result=run(ROOT,releases,args.out,args.only.split(',') if args.only else None,args.doc_dir)
        print(json.dumps({'decision':result['decision'],'receipt':str(Path(args.out)/'decision.json'),'owner_acceptance':False}))
        return 0 if result['release_delivery'] else 1
    except (OSError,ValueError,RuntimeError) as error:
        print(json.dumps({'decision':'refused','error':str(error)})); return 1


if __name__=='__main__': raise SystemExit(main())
