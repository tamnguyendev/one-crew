"""Pinned before/after runtime evals, separated from observed product outcomes."""
import argparse
import collections
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import signal
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid

from .eval_corpus import catalog
from .ledger import canonical, content_hash, utcnow

STATUSES = {'passed', 'assertion_failed', 'runtime_error', 'capability_unavailable',
            'skipped', 'timed_out', 'harness_error'}


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.PIPE)


def revision(repo, ref):
    return git(repo, 'rev-parse', '--verify', '--end-of-options', ref+'^{commit}').decode().strip()


def archive(repo, sha, destination, *, exclude=()):
    """No checkout/index mutation. Reject links and paths outside the fresh directory."""
    destination.mkdir(parents=True, exist_ok=False)
    with tarfile.open(fileobj=io.BytesIO(git(repo, 'archive', '--format=tar', sha))) as stream:
        for member in stream:
            name = Path(member.name)
            if name.parts[0] in exclude:
                continue
            target = destination / name
            if name.is_absolute() or not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError('Unsafe Git archive path.')
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(stream.extractfile(member).read())
            else:
                raise ValueError('Eval archive does not support links or special files.')


def tree_hash(root, paths):
    entries = {}
    for part in paths:
        p = root/part
        for f in sorted(p.rglob('*') if p.is_dir() else [p]):
            if f.is_file() and '__pycache__' not in f.parts:
                entries[f.relative_to(root).as_posix()] = hashlib.sha256(f.read_bytes()).hexdigest()
    if not entries:
        raise ValueError('Empty harness.')
    return content_hash(entries)


def environment():
    # Microsoft Store's executable is an app-execution alias, not a readable PE.
    # Fingerprint the installed interpreter, retaining the invoked alias separately.
    executable = Path(sys.executable)
    try:
        binary = executable.read_bytes()
    except OSError:
        executable = Path(sys.base_prefix)/('python.exe' if os.name=='nt' else 'bin/python3')
        binary = executable.read_bytes()
    return {'python': sys.version, 'executable_sha256': hashlib.sha256(binary).hexdigest(),
            'invoked_executable':sys.executable, 'fingerprinted_executable':str(executable),
            'platform': platform.platform(), 'machine': platform.machine(),
            'git': subprocess.check_output(['git', '--version']).decode().strip(),
            'transport': 'fixture-only', 'model': None, 'device': None}


def clean_environment(home):
    # Child inherits only OS/tool discovery, never provider tokens or OneCrew state configuration.
    keep = {'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATH', 'PATHEXT', 'SYSTEMDRIVE',
            'PROGRAMFILES', 'PROGRAMFILES(X86)', 'PROCESSOR_ARCHITECTURE'}
    env = {k:v for k,v in os.environ.items() if k.upper() in keep}
    for name in ('TEMP', 'TMP', 'LOCALAPPDATA', 'APPDATA', 'USERPROFILE', 'ONECREW_DESKTOP_HOME'):
        p = home/name.lower(); p.mkdir(parents=True, exist_ok=True); env[name] = str(p)
    # Local attribution (getpass) needs a user name; a fixed one keeps probes identical across machines.
    env.update(USERNAME='onecrew-eval', PYTHONUTF8='1', GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT='0', FLUTTER_SUPPRESS_ANALYTICS='true', DART_SUPPRESS_ANALYTICS='true')
    return env


def execute_probe(runtime, harness, selector, destination, timeout):
    start = time.monotonic()
    argv = [sys.executable, '-I', '-X', 'utf8', str(harness/'onecrew/eval_probe.py'),
            str(runtime), str(harness), selector, str(destination)]
    process = subprocess.Popen(argv, cwd=runtime, env=clean_environment(harness.parent/'env'),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=os.name != 'nt')
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, timeout=15)
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.kill()
        process.communicate(timeout=15)
        return {'selector':selector, 'status':'timed_out', 'tests':0, 'errors':[{'type':'TimeoutExpired','capability':False}],
                'elapsed_seconds':round(time.monotonic()-start, 6), 'diagnostic':'Probe deadline exceeded.'}
    if process.returncode != 0 or not destination.is_file():
        return {'selector':selector, 'status':'harness_error', 'tests':0, 'errors':[], 'exit_code':process.returncode,
                'diagnostic':(stdout+stderr).decode('utf-8', errors='replace')[-16000:]}
    value = json.loads(destination.read_text(encoding='utf-8'))
    if value.get('selector') != selector or value.get('status') not in STATUSES or not valid_errors(value.get('errors', [])):
        raise ValueError('Invalid probe receipt.')
    return value


def valid_errors(errors):
    # Exception class names only; receipts from older harnesses carry no 'errors'.
    return isinstance(errors, list) and all(isinstance(e, dict) and set(e) == {'type', 'capability'} and
        isinstance(e['type'], str) and e['type'].isidentifier() and type(e['capability']) is bool for e in errors)


def seal(value):
    return dict(value, digest=content_hash(value))


def read_result(path):
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    digest = value.pop('digest', None)
    if digest != content_hash(value):
        raise ValueError('Eval result digest mismatch.')
    return value


def case_status(probes):
    if not probes:
        return 'harness_error'
    # Any failure/skip prevents pass. Counts are always case-level, not assertion totals.
    for status in ('harness_error','timed_out','capability_unavailable','runtime_error','assertion_failed','skipped'):
        if any(p['status'] == status for p in probes):
            return status
    return 'passed'


def replay(repo, output, ref='HEAD', harness_ref='HEAD', ids=None, repeat=1, timeout=120):
    if type(repeat) is not int or not 1 <= repeat <= 5 or not 1 <= timeout <= 600:
        raise ValueError('repeat must be 1..5; timeout 1..600 seconds.')
    corpus = catalog(ids)
    harness_sha = revision(repo, harness_ref)
    targets = {c['id']:revision(repo, c['before'] if ref == 'historical' else ref) for c in corpus['cases']}
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex
    run_dir = output/run_id; run_dir.mkdir()
    result = {'version':1, 'type':'runtime_replay', 'run_id':run_id, 'created_at':utcnow(),
              'corpus':corpus, 'corpus_hash':content_hash(corpus), 'harness_revision':harness_sha,
              'environment':environment(), 'repeat':repeat, 'timeout_seconds':timeout,
              'target_mode':'per-case-pre-fix' if ref == 'historical' else 'single-revision',
              'targets':targets, 'results':[], 'product_autonomy_rate':None, 'live_model_calls':0,
              'promotion':'not_evaluated; never automatic'}
    # Scratch lives on the chosen output disk, not necessarily the scarce system disk.
    # Avoid consuming Windows' path budget with the 32-character report ID.
    with tempfile.TemporaryDirectory(prefix='e-', dir=output) as temp:
        base = Path(temp); harness = base/'harness'
        archive(repo, harness_sha, harness)
        if not (harness/'onecrew/eval_probe.py').is_file():
            raise ValueError('Harness revision must contain the committed eval implementation.')
        result['harness_hash'] = tree_hash(harness, ['tests', 'specs', 'onecrew/eval_probe.py'])
        result['grader_hash'] = tree_hash(Path(__file__).parent, ['evaluation.py','eval_corpus.py'])
        for case in corpus['cases']:
            for trial in range(repeat):
                # Fresh runtime AND fixture storage per trial; do not carry state between cases.
                work = base/(case['id']+'-'+str(trial)); runtime = work/'runtime'
                archive(repo, targets[case['id']], runtime, exclude=('tests',))
                probes = []
                for number, selector in enumerate(case['tests']):
                    value = execute_probe(runtime, harness, selector, work/(str(number)+'.json'), timeout)
                    probes.append(value)
                result['results'].append({'case':case['id'], 'trial':trial, 'revision':targets[case['id']],
                                          'status':case_status(probes), 'probes':probes})
                # Incremental durable evidence if the parent process is interrupted.
                (run_dir/'partial.json').write_text(json.dumps(seal(result), ensure_ascii=False, indent=2), encoding='utf-8')
                print(case['id']+' ['+str(trial+1)+']: '+case_status(probes), file=sys.stderr, flush=True)
    result['counts'] = dict(collections.Counter(r['status'] for r in result['results']))
    result['completed'] = True
    path = run_dir/'result.json'
    path.write_text(json.dumps(seal(result), ensure_ascii=False, indent=2), encoding='utf-8')
    return path, result


def compare(before, after):
    for value in (before, after):
        if value.get('type') != 'runtime_replay' or value.get('completed') is not True:
            raise ValueError('Comparison requires two complete runtime replays.')
        if content_hash(value['corpus']) != value.get('corpus_hash'):
            raise ValueError('Corpus content changed without a matching hash.')
    for key in ('version','corpus_hash','harness_hash','grader_hash','environment','repeat','timeout_seconds'):
        if before.get(key) != after.get(key):
            raise ValueError('Incomparable evals: '+key)
    expected = {(c['id'],n) for c in before['corpus']['cases'] for n in range(before['repeat'])}
    def index(value):
        rows = {(r['case'],r['trial']):r for r in value['results']}
        if set(rows) != expected or len(rows) != len(value['results']):
            raise ValueError('Missing/duplicate case trials; denominator cannot change.')
        for r in rows.values():
            c = next(c for c in value['corpus']['cases'] if c['id'] == r['case'])
            if ([p['selector'] for p in r['probes']] != c['tests'] or
                    any(p['status'] not in STATUSES or not valid_errors(p.get('errors', [])) for p in r['probes']) or
                    case_status(r['probes']) != r['status'] or r['revision'] != value['targets'][r['case']]):
                raise ValueError('Inconsistent case/probe evidence.')
            if any(p['status'] == 'passed' and (p.get('tests') != 1 or p.get('skipped',0)) for p in r['probes']):
                raise ValueError('Pass needs exactly one executed, non-skipped test.')
        return rows
    left, right = index(before), index(after)
    rows = []
    for key in sorted(expected):
        a,b = left[key],right[key]
        change = ('regressed' if a['status']=='passed' and b['status']!='passed' else
                  'capability_added' if a['status']=='capability_unavailable' and b['status']=='passed' else
                  'recovered' if a['status'] in ('runtime_error','assertion_failed') and b['status']=='passed' else
                  'inconclusive' if a['status'] in ('harness_error','timed_out','skipped') or b['status'] in ('harness_error','timed_out','skipped') else
                  'unchanged')
        rows.append({'case':key[0], 'trial':key[1], 'before':a['status'], 'after':b['status'], 'change':change,
                     'before_revision':a['revision'], 'after_revision':b['revision']})
    return {'version':1, 'type':'runtime_comparison', 'before_run':before['run_id'], 'after_run':after['run_id'],
            'corpus_hash':before['corpus_hash'], 'rows':rows, 'trials':len(expected),
            'before_passed':sum(r['before']=='passed' for r in rows),
            'after_passed':sum(r['after']=='passed' for r in rows),
            'changes':dict(collections.Counter(r['change'] for r in rows)),
            'historical':before['target_mode']=='per-case-pre-fix',
            'product_autonomy_rate':None, 'promotion':'manual_review_required', 'limits':before['corpus']['limits']}


def markdown(value):
    if value['type'] == 'runtime_comparison':
        lines = ['# OneCrew eval: runtime trước–sau', '',
                 f"Đạt: {value['before_passed']}/{value['trials']} → {value['after_passed']}/{value['trials']} case-trials.",
                 'Baseline riêng trước từng fix.' if value['historical'] else 'So sánh hai revision.',
                 'Không phải tỷ lệ tự hoàn thành sản phẩm; không tự approve skill/routing.', '',
                 '| Case | Lượt | Trước | Sau | Phân loại |', '|---|---:|---|---|---|']
        lines += [f"| {r['case']} | {r['trial']+1} | {r['before']} | {r['after']} | {r['change']} |" for r in value['rows']]
        lines += ['', *['- '+s for s in value['limits']]]
        return '\n'.join(lines)+'\n'
    from .eval_observe import markdown as observed_markdown
    return observed_markdown(value)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project', type=Path, default=Path.cwd()); p.add_argument('--state-root', type=Path)
    sub = p.add_subparsers(dest='group', required=True).add_parser('eval').add_subparsers(dest='command', required=True)
    sub.add_parser('cases')
    run = sub.add_parser('replay'); run.add_argument('--ref', default='HEAD'); run.add_argument('--harness-ref',default='HEAD')
    run.add_argument('--case', action='append'); run.add_argument('--repeat', type=int,default=1)
    run.add_argument('--timeout', type=int,default=120); run.add_argument('--output',type=Path,required=True)
    diff = sub.add_parser('compare'); diff.add_argument('--before',type=Path,required=True); diff.add_argument('--after',type=Path,required=True)
    diff.add_argument('--output',type=Path,required=True)
    obs = sub.add_parser('observe'); obs.add_argument('--task',action='append',required=True); obs.add_argument('--output',type=Path,required=True)
    card = sub.add_parser('scorecard'); card.add_argument('--task',action='append',required=True); card.add_argument('--replay-compare',type=Path)
    card.add_argument('--output',type=Path,required=True,help='Directory for scorecard.json and scorecard.md')
    note = sub.add_parser('assistance');note.add_argument('--task',required=True);note.add_argument('--key',required=True)
    note.add_argument('--actor',choices=['codex','claude','human','other-entry'],required=True)
    note.add_argument('--category',choices=['runtime','environment','product-code','tests','build','device','decision'],required=True)
    note.add_argument('--reason',required=True)
    a = p.parse_args(argv)
    try:
        if a.command == 'cases':
            print(json.dumps(catalog(), ensure_ascii=False,indent=2)); return 0
        if a.command == 'assistance':
            from .eval_observe import assistance_note
            from .ledger import Ledger
            if not a.state_root:raise ValueError('assistance requires explicit --state-root and task project.')
            value=assistance_note(Ledger(a.project,a.state_root),a.task,a.key,a.actor,a.category,a.reason)
            print(json.dumps(value,ensure_ascii=False));return 0
        if a.command == 'replay':
            path,value = replay(a.project,a.output,a.ref,a.harness_ref,a.case,a.repeat,a.timeout)
            print(json.dumps({'result':str(path),'counts':value['counts'],'product_autonomy_rate':None})); return 0
        if a.command == 'scorecard':
            from .eval_scorecard import scorecard, markdown as card
            if not a.state_root: raise ValueError('scorecard requires explicit --state-root.')
            value = scorecard(a.state_root,a.task,read_result(a.replay_compare) if a.replay_compare else None)
            a.output.mkdir(parents=True,exist_ok=True); result,report = a.output/'scorecard.json',a.output/'scorecard.md'
            with result.open('x',encoding='utf-8') as f: f.write(json.dumps(seal(value),ensure_ascii=False,indent=2))
            with report.open('x',encoding='utf-8') as f: f.write(card(value))
            print(json.dumps({'result':str(result),'report':str(report)})); return 0
        if a.command == 'compare':
            value = compare(read_result(a.before),read_result(a.after))
        else:
            from .eval_observe import observe
            if not a.state_root: raise ValueError('observe requires explicit --state-root.')
            value = observe(a.state_root,a.task)
        # Exclusive creation prevents overwriting an earlier evidence report.
        a.output.parent.mkdir(parents=True,exist_ok=True)
        with a.output.open('x',encoding='utf-8') as f: f.write(json.dumps(seal(value),ensure_ascii=False,indent=2))
        with a.output.with_suffix('.md').open('x',encoding='utf-8') as f: f.write(markdown(value))
        print(json.dumps({'result':str(a.output),'report':str(a.output.with_suffix('.md'))})); return 0
    except (ValueError,OSError,sqlite3.Error,subprocess.SubprocessError) as e:
        print('Eval: '+str(e),file=sys.stderr); return 2
