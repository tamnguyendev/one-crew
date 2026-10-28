"""first_task_drill.py <package dir> <work dir> [--owner-step auto|fixture|real] [--lint-only] - drill the first task FROM A BUILT PACKAGE.

Stdlib only; run it with `python -I` from anywhere (it never imports a checkout). It follows examples/first-task/README.vi.md LITERALLY: the
PowerShell blocks of that file are the commands, each one run in its own Windows PowerShell 5.1 process (-EncodedCommand) with the blocks
tagged `<!-- drill: prelude -->` (variables, PATH/fake settings) replayed before it, so the file and the drill cannot drift apart. Only the
three variables the reader is told to edit (`$py`, `$pkg`, `$work`) are overridden. Each block is a step; the log records its command, exit
code and key output. Part A only (the fake `claude`, a test double: no model, no login): the drill proves the written commands run, not that a
model understands the wiki, and it says nothing about part B (the real provider).

Isolation (per process, nothing else is touched): TEMP/TMP/LOCALAPPDATA/APPDATA point into <work>/env; PYTHON*, ONECREW_*, GIT_* variables are
dropped; a fresh venv under <work>; the fake `claude` is installed into that venv and put first on PATH only in the blocks that say so.

Owner step: `onecrew owner approve` is the owner's verb and is refused in an AI tool session (CLAUDE_CODE_CHILD_SESSION). Outside such a
session (--owner-step auto) the README block runs as written. Inside one, the drill (1) runs the README block as written and expects the
refusal, (2) parses the README arguments with the installed CLI parser (no execution), and (3) SUBSTITUTES the approval with the fixture
approval verify_milestone/scenario_a1 use - plan.approve(ledger, 'P1', 'owner', ...) on the temporary ledger, in a process whose AI-session
markers are removed exactly as verify_milestone.env_for does - and labels it `substituted` in the log. That is the only substituted step.

--lint-only: resolve every relative path the README names (links, `../x` code spans, "$pkg\\x" / "$ex\\x" strings) inside the package and list the
ones that do not exist; runs no command.
Writes <work>/first-task-drill-log.json (or readme-lint-log.json). Exit 0 when everything required passed, 1 otherwise."""
import argparse
import base64
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

AI_MARKERS = ('CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION', 'ONECREW_ACTOR', 'PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP', 'PYTHONUTF8', 'PYTHONIOENCODING')   # = verify_milestone.AI_MARKERS
POWERSHELL = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'
TAG = re.compile(r'^<!--\s*drill:\s*(prelude|run|owner|real|show)(?:\s+id=([\w-]+))?\s*-->\s*$')
FENCE = re.compile(r'^```(\w*)\s*$')
OVERRIDDEN = ('py', 'pkg', 'work')
HEX40 = re.compile(r'[0-9a-f]{40}')


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree_digest(root):
    h = hashlib.sha256()
    for p in sorted(Path(root).rglob('*')):
        if p.is_file(): h.update(p.relative_to(root).as_posix().encode() + b'\0' + sha256(p).encode() + b'\n')
    return h.hexdigest()


def parse_readme(path):
    """The README's PowerShell blocks in order: [{kind, id, text, line}]. A powershell fence without a drill tag right before it is an error."""
    lines = Path(path).read_text(encoding='utf-8').splitlines()
    blocks, errors, index = [], [], 0
    while index < len(lines):
        match = FENCE.match(lines[index])
        if match and match.group(1) == 'powershell':
            before = next((lines[i] for i in range(index - 1, -1, -1) if lines[i].strip()), '')
            tag = TAG.match(before.strip())
            end = next((i for i in range(index + 1, len(lines)) if lines[i].startswith('```')), None)
            if end is None: errors.append(f'line {index + 1}: block never closes'); break
            if not tag: errors.append(f'line {index + 1}: powershell block without a <!-- drill: ... --> tag')
            else: blocks.append({'kind': tag.group(1), 'id': tag.group(2) or f'line{index + 1}', 'text': '\n'.join(lines[index + 1:end]), 'line': index + 1})
            index = end
        index += 1
    return blocks, errors


def lint(readme, pkg, blocks):
    """Relative paths the README names that do not resolve inside the package."""
    readme, pkg = Path(readme), Path(pkg)
    text = readme.read_text(encoding='utf-8')
    found = {}
    for target in re.findall(r'\]\(([^)#\s]+)\)', text):
        if not re.match(r'[a-z]+:', target): found[target] = (readme.parent / target)
    for target in re.findall(r'`((?:\.\./|\./)[^`\s]+)`', text): found[target] = (readme.parent / target)
    roots = {'pkg': pkg, 'ex': readme.parent}
    for block in blocks:
        for var, rest in re.findall(r'\$(pkg|ex)\\([^"\'\s`)]+)', block['text']):
            found[f'${var}\\{rest}'] = roots[var] / rest.replace('\\', '/')
    missing = []
    for shown, path in sorted(found.items()):
        ok = bool(glob.glob(str(path))) if '*' in str(path) else path.exists()
        if not ok: missing.append({'named': shown, 'resolved_to': str(path)})
    return {'checked': sorted(found), 'unresolved': missing}


def inside_checkout(path):
    """The nearest ancestor (or the folder itself) that holds a .git, else None."""
    for folder in [Path(path), *Path(path).parents]:
        if (folder / '.git').exists(): return str(folder)
    return None


def ps_run(script, env, cwd, timeout=600):
    """Run a PowerShell script in its own Windows PowerShell process; a non-zero native exit code stops it at that line."""
    guarded = []
    for line in script.splitlines():
        guarded.append(line)
        if line.strip() and not line.strip().startswith('#'): guarded.append('if ($LASTEXITCODE) { exit $LASTEXITCODE }')
    body = ("$ErrorActionPreference = 'Stop'\n[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false\n" + '\n'.join(guarded) + '\n')
    started = time.perf_counter()
    done = subprocess.run([str(POWERSHELL), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-EncodedCommand',
                           base64.b64encode(body.encode('utf-16-le')).decode()], capture_output=True, env=env, cwd=str(cwd), timeout=timeout)
    return done.returncode, done.stdout.decode('utf-8', 'replace'), done.stderr.decode('utf-8', 'replace'), round(time.perf_counter() - started, 2)


def first_json(text):
    start = text.find('{')
    if start < 0: return None
    try: return json.JSONDecoder().raw_decode(text[start:])[0]
    except ValueError: return None


def clip(text, head=700, tail=1300):
    text = text.strip()
    return text if len(text) <= head + tail + 40 else text[:head] + f'\n... [{len(text) - head - tail} chars omitted] ...\n' + text[-tail:]


def main():
    parser = argparse.ArgumentParser(description='Drill the first task from a built package.')
    parser.add_argument('package'); parser.add_argument('work')
    parser.add_argument('--owner-step', choices=['auto', 'fixture', 'real'], default='auto')
    parser.add_argument('--lint-only', action='store_true')
    parser.add_argument('--readme', help='default: <package>/examples/first-task/README.vi.md')
    args = parser.parse_args()
    pkg, work = Path(args.package).resolve(), Path(args.work).resolve()
    readme = Path(args.readme).resolve() if args.readme else pkg / 'examples' / 'first-task' / 'README.vi.md'
    if work.exists() and any(work.iterdir()): raise SystemExit(f'{work} is not empty; a drill folder is never reused.')
    work.mkdir(parents=True, exist_ok=True)
    os.chdir(work)
    blocks, parse_errors = parse_readme(readme)
    linted = lint(readme, pkg, blocks)
    if args.lint_only:
        report = {'kind': 'first-task-readme-lint', 'package': str(pkg), 'readme': str(readme), 'blocks': len(blocks), 'parse_errors': parse_errors, **linted,
                  'result': 'pass' if not parse_errors and not linted['unresolved'] and blocks else 'fail'}
        (work / 'readme-lint-log.json').write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding='utf-8')
        print(json.dumps({k: v for k, v in report.items() if k != 'checked'}, indent=1, ensure_ascii=False))
        return 0 if report['result'] == 'pass' else 1
    manifest = json.loads((pkg / 'manifest.json').read_text(encoding='utf-8')) if (pkg / 'manifest.json').is_file() else {}
    in_ai = 'CLAUDE_CODE_CHILD_SESSION' in os.environ
    owner_mode = args.owner_step if args.owner_step != 'auto' else ('fixture' if in_ai else 'real')
    iso = work / 'env'
    for sub in ('tmp', 'localappdata', 'appdata'): (iso / sub).mkdir(parents=True)
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(('PYTHON', 'ONECREW_', 'GIT_')) and k.upper() != 'VIRTUAL_ENV'}
    env.update(TEMP=str(iso / 'tmp'), TMP=str(iso / 'tmp'), LOCALAPPDATA=str(iso / 'localappdata'), APPDATA=str(iso / 'appdata'))
    steps, substituted = [], []
    report = {'kind': 'first-task-drill-log', 'package': str(pkg), 'readme': str(readme), 'work': str(work), 'started': time.strftime('%Y-%m-%dT%H:%M:%S'),
              'part': 'A (fake claude; no model, no login)', 'owner_step_mode': owner_mode, 'in_ai_session': in_ai,
              'proves': 'the PowerShell blocks of the README (part A) run in order from this package, in a fresh venv, with the fake claude, and each step produced what its check expects',
              'does_not_prove': ['part B: the real provider (Claude Code CLI 2.1.286, subscription login, claude-haiku-5-5)', 'that a model understands or uses the wiki',
                                 'that the owner approve step ran as written when in_ai_session is true (it is then substituted and labelled)'],
              'manifest': {k: manifest.get(k) for k in ('milestone', 'version', 'code_commit', 'claims')},
              'isolation': {'TEMP/TMP': str(iso / 'tmp'), 'LOCALAPPDATA': str(iso / 'localappdata'), 'APPDATA': str(iso / 'appdata'),
                            'dropped': 'PYTHON*, ONECREW_*, GIT_*, VIRTUAL_ENV', 'real_ledger_used': False}, 'steps': steps, 'substituted': substituted}

    def record(sid, kind, ok, command='', **facts):
        steps.append(dict(id=sid, kind=kind, result='pass' if ok else 'fail', command=command, **facts)); print(sid, 'pass' if ok else 'FAIL', flush=True)
        return ok

    def finish():
        report['finished'] = time.strftime('%Y-%m-%dT%H:%M:%S')
        report['package_unchanged'] = tree_digest(pkg) == before
        required = [s for s in steps if s['kind'] != 'info']
        report['result'] = 'pass' if required and all(s['result'] == 'pass' for s in required) and report['package_unchanged'] and not parse_errors else 'fail'
        (work / 'first-task-drill-log.json').write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding='utf-8')
        print('RESULT', report['result'], f'{sum(s["result"] == "pass" for s in required)}/{len(required)}', 'package_unchanged=' + str(report['package_unchanged']))
        return 0 if report['result'] == 'pass' else 1

    before = tree_digest(pkg)
    ok = record('links', 'run', not linted['unresolved'] and not parse_errors and bool(blocks), 'resolve every relative path the README names inside the package',
                unresolved=linted['unresolved'], parse_errors=parse_errors, checked=len(linted['checked']), blocks=len(blocks))
    if not ok: return finish()
    inside = {'package': inside_checkout(pkg), 'work': inside_checkout(work)}
    ok = record('location', 'run', not any(inside.values()), 'the package and the drill folder are not inside a git checkout (nothing of a checkout can answer a command)', inside_checkout=inside)
    if not ok: return finish()
    # the three variables the reader edits are overridden; everything else in the vars block runs as written
    override = {'py': sys.executable, 'pkg': str(pkg), 'work': str(work / 'task dau tien thu')}
    preludes = []

    def prelude_text(skip_fake=False):
        return '\n'.join(p['text'] for p in preludes if not (skip_fake and p['id'].startswith('fake')))

    def vars_text(text):
        out = []
        for line in text.splitlines():
            m = re.match(r'^\$(py|pkg|work)\s*=', line)
            out.append(f'${m.group(1)} = "' + override[m.group(1)] + '"' if m else line)
        return '\n'.join(out)

    ctx = {}
    for block in blocks:
        kind, sid, text = block['kind'], block['id'], block['text']
        if kind == 'show':
            record(sid, 'info', True, text, note='shown in the README, not executed'); continue
        if kind == 'real':
            record(sid, 'info', True, text, note='part B (real provider): not run by the drill'); continue
        if kind == 'prelude':
            effective = vars_text(text) if sid == 'vars' else text
            preludes.append({'id': sid, 'text': effective})
            code, out, err, secs = ps_run(prelude_text() + '\n' + ('$ctx = @($py, $pkg, $work, $venv, $proj, $ledger, $onecrew, $ex, $PSVersionTable.PSVersion.ToString()) -join "|"; $ctx' if sid == 'vars' else '"ok"'),
                                          env, work)
            if sid == 'vars' and code == 0:
                names = ['py', 'pkg', 'work', 'venv', 'proj', 'ledger', 'onecrew', 'ex', 'powershell']
                ctx.update(dict(zip(names, out.strip().splitlines()[-1].split('|'))))
                report['variables'] = dict(ctx); report['overridden_by_drill'] = {k: override[k] for k in OVERRIDDEN}
            if not record(sid, 'run', code == 0 and (sid != 'vars' or len(ctx) == 9), text, exit=code, seconds=secs, stdout=clip(out), stderr=clip(err, 200, 600)): return finish()
            continue
        facts, passed = {}, True
        script = prelude_text() + '\n' + text
        command_text = text
        if kind == 'owner' and owner_mode == 'fixture':
            if not owner_step(block, in_ai, ctx, prelude_text(), env, work, record, substituted): return finish()
            continue
        code, out, err, secs = ps_run(script, env, work)
        facts = dict(exit=code, seconds=secs, stdout=clip(out), stderr=clip(err, 200, 800))
        passed, extra = check_step(sid, code, out, err, ctx, work)
        facts.update(extra)
        if kind == 'owner': facts['substituted'] = False           # the owner's own terminal: the README command ran as written
        if not record(sid, 'run', passed and code == 0, command_text, **facts): return finish()
        if sid == 'venv': report['onecrew_version'] = out.strip().splitlines()[-1] if out.strip() else None
    # informational only: the claude the adapter would find WITHOUT the fake (PATH first, then ~/.local/bin/claude.exe): `--version`, no login probe, no model call
    real = next((c for c in (shutil.which('claude', path=env.get('PATH')), str(Path.home() / '.local' / 'bin' / 'claude.exe')) if c and Path(c).is_file()), None)
    done = subprocess.run([real, '--version'], capture_output=True, env=env, timeout=20) if real else None
    report['real_provider_probe'] = {'note': 'informational: the claude on this machine the adapter would use if the fake were not first on PATH (version only; no login probe, no model call)',
                                     'path': real, 'version': done.stdout.decode('utf-8', 'replace').strip() if done else None, 'required': '2.1.286 (Claude Code)'}
    return finish()


def owner_step(block, in_ai, ctx, prelude, env, work, record, substituted):
    """The README's `owner approve` block inside an AI session (outside one it runs as written, like every other block): refusal evidence for the
    command as written, a parse check of its arguments, then the labelled fixture approval. Returns True when all three held."""
    text, sid = block['text'], block['id']
    venv_py = str(Path(ctx['venv']) / 'Scripts' / 'python.exe')
    ok = True
    if in_ai:
        code, out, err, secs = ps_run(prelude + '\n' + text, env, work)
        refused = code == 2 and 'refused' in out and 'AI tool session' in out
        ok &= record(sid + '-literal-refused', 'run', refused, text, exit=code, seconds=secs, stdout=clip(out, 500, 600),
                     note='the README command run as written inside an AI session: refused by design (exit 2). The guard is not bypassed.')
    argv_text = re.search(r'owner approve .*', text).group(0)
    words = re.findall(r'"[^"]*"|\S+', argv_text.replace('owner ', '', 1))
    words = [w[1:-1] if w.startswith('"') else w for w in words]
    code = subprocess.run([venv_py, '-I', '-c', 'import json, sys; from onecrew.v2 import owner_cli; ns = owner_cli._parser().parse_args(sys.argv[1:]); '
                           'print(json.dumps({"verb": ns.verb, "plan": ns.plan, "reference": ns.reference, "equals": " ".join(owner_cli.translate(ns)[1][:3])}))', *words],
                          capture_output=True, env=env, cwd=str(work), timeout=60)
    parsed = first_json(code.stdout.decode('utf-8', 'replace'))
    ok &= record(sid + '-parse', 'run', code.returncode == 0 and bool(parsed) and parsed['verb'] == 'approve' and parsed['plan'] == 'P1', argv_text,
                 exit=code.returncode, stdout=clip(code.stdout.decode('utf-8', 'replace')), note='README arguments parsed by the installed owner CLI parser; nothing executed')
    project, ledger = ctx['proj'], ctx['ledger']
    if 'state-v2-real' in ledger.replace('\\', '/') or not Path(ledger).resolve().is_relative_to(work):
        return record(sid + '-fixture', 'run', False, '', note='refused: the ledger is not under the drill folder')
    fixture = ('import sys; from pathlib import Path; from onecrew.ledger import Ledger; from onecrew.v2 import plan; '
               'ledger = Ledger(Path(sys.argv[1]), Path(sys.argv[2])); '
               'shown = plan.approve(ledger, "P1", "owner", "temporary drill fixture (not a real ledger; substitutes the owner approve step)"); '
               'print(shown["status"], shown.get("approved_revision"))')
    clean = {k: v for k, v in env.items() if k.upper() not in AI_MARKERS}     # exactly verify_milestone.env_for: the fixture owner is not an AI session
    done = subprocess.run([venv_py, '-I', '-c', fixture, project, ledger], capture_output=True, env=clean, cwd=str(work), timeout=300)
    out = done.stdout.decode('utf-8', 'replace') + done.stderr.decode('utf-8', 'replace')
    shown = subprocess.run([ctx['onecrew'], '--project', project, '--state-root', ledger, 'plan', 'show', 'P1'], capture_output=True, env=env, cwd=str(work), timeout=120)
    state = (first_json(shown.stdout.decode('utf-8', 'replace')) or {}).get('status')
    label = ('SUBSTITUTED: the owner approves in a terminal of their own; inside this AI session `onecrew owner approve` is refused by design, so the plan '
             'was approved with the fixture approval verify_milestone/scenario_a1 use (plan.approve(ledger, "P1", "owner", ...)) on the temporary ledger, '
             'in a process without the AI-session markers. Nothing else in the drill is substituted.')
    substituted.append({'step': sid, 'what': 'owner approve P1', 'by': 'fixture plan.approve on the temporary ledger', 'ledger': ledger, 'reason': label})
    ok &= record(sid + '-fixture', 'run', done.returncode == 0 and state == 'approved' and out.strip().startswith('approved'), 'plan.approve(ledger, "P1", "owner", ...)',
                 exit=done.returncode, stdout=clip(out), plan_status_after=state, substituted=True, note=label)
    return ok


def check_step(sid, code, out, err, ctx, work):
    """(passed, facts) - what each README step must have produced, checked on files and output, not on exit codes alone."""
    facts = {}
    proj, ledger, venv = Path(ctx.get('proj', work)), Path(ctx.get('ledger', work)), Path(ctx.get('venv', work))
    fake_log = Path(ctx.get('work', str(work))) / 'fake.jsonl'
    if sid == 'venv':
        version = out.strip().splitlines()[-1] if out.strip() else ''
        return (Path(ctx['onecrew']).is_file() and 'wiki' in out and re.fullmatch(r'\d[\w.]*', version) is not None), {'installed_version': version}
    if sid == 'repo':
        count = subprocess.run(['git', '-C', str(proj), 'rev-list', '--count', 'HEAD'], capture_output=True, text=True).stdout.strip()
        return count == '1' and (proj / 'a.txt').read_text() == 'base\n', {'commits': count}
    if sid == 'wiki-page':
        page = (proj / 'docs' / 'wiki' / 'rules.md').read_text(encoding='utf-8')
        first = subprocess.run(['git', '-C', str(proj), 'rev-list', '--max-parents=0', 'HEAD'], capture_output=True, text=True).stdout.strip()
        revisions = re.findall(r'"revision":\s*"([^"]+)"', page)
        facts = {'revisions': revisions, 'first_commit': first}
        return revisions == [first, first] and HEX40.fullmatch(first) is not None and 'HEAD' not in revisions, facts
    if sid == 'wiki-pages':
        value = first_json(out) or {}
        entries = [(e['id'], e['label']) for p in value.get('pages', []) for e in p.get('entries', [])]
        facts = {'entries': entries, 'problems': value.get('problems')}
        return value.get('problems') == [] and entries == [('a-value', 'verified'), ('no-two-lines', 'refuted'), ('rules-ghi-chu-chua-co-nguon', 'unverified')], facts
    if sid == 'contract':
        text = (Path(ctx['work']) / 'contract.json').read_text(encoding='utf-8')
        return 'PYTHON_EXE' not in text and str(venv / 'Scripts' / 'python.exe').replace('\\', '/') in text and 'lint: clean' in out, {'rendered_python': 'PYTHON_EXE' not in text}
    if sid == 'propose':
        value = first_json(out) or {}
        return value.get('status') == 'proposed' and value.get('plan') == 'P1', {'status': value.get('status')}
    if sid == 'present':
        return 'P1' in out and 'Cách nghiệm thu' in out, {}
    if sid == 'approve':                                   # the README owner block run as written (owner's terminal)
        value = first_json(out) or {}
        return value.get('status') == 'approved' and value.get('approved_revision') == 1, {'status': value.get('status')}
    if sid == 'revise':
        value = first_json(out) or {}
        return value.get('internal_revision') == 1 and [n['id'] for n in value.get('definition', {}).get('nodes', [])] == ['C', 'I'], {'internal_revision': value.get('internal_revision')}
    if sid == 'show-package':
        return 'a-value' in out and 'sự thật' in out and 'hướng đã loại' in out and 'đầu mối' in out, {}
    if sid == 'fake-install':
        return (venv / 'Scripts' / 'claude.exe').is_file() and 'Successfully installed onecrew-fake-claude' in out, {'claude_exe': str(venv / 'Scripts' / 'claude.exe')}
    if sid == 'fake-check':
        lines = [line.strip() for line in out.strip().splitlines()]
        return len(lines) == 2 and Path(lines[0]).resolve() == (venv / 'Scripts' / 'claude.exe').resolve() and lines[1] == '2.1.286 (Claude Code)', {'claude': lines}
    if sid == 'step-c':
        value = first_json(out) or {}
        log = [json.loads(line) for line in fake_log.read_text(encoding='utf-8').splitlines()] if fake_log.exists() else []
        rows = [line.split() for line in out.splitlines() if re.match(r'^(a-value|no-two-lines|rules-ghi-chu-chua-co-nguon)\s', line)]
        facts = {'step': {k: value.get(k) for k in ('node', 'state')}, 'package_rows': rows, 'fake_runs': len(log), 'fake_first': log[0] if log else None}
        used = re.search(r'^used\s*:\s*\{?(.*)', out, re.M)
        return (value.get('state') == 'produced' and value.get('node') == 'C' and len(log) == 1 and log[0]['how'] == 'fact' and log[0]['value'] == 'right'
                and rows[:1] == [['a-value', 'fact', 'applies']] and [r[0] for r in rows] == ['a-value', 'no-two-lines', 'rules-ghi-chu-chua-co-nguon']
                and 'a-value' in (used.group(1) if used else '') and re.search(r'violations\s*:\s*\{\s*\}', out) is not None), facts
    if sid in ('verify-c', 'verify-i'):
        value = first_json(out) or {}
        node = 'C' if sid == 'verify-c' else 'I'
        return value.get('result') == 'pass' and value.get('node') == node and [c['result'] for c in value.get('observed', {}).get('checks', [])] == ['pass'], {'verify_result': value.get('result')}
    if sid == 'step-i':
        value = first_json(out) or {}
        log = [json.loads(line) for line in fake_log.read_text(encoding='utf-8').splitlines()] if fake_log.exists() else []
        return value.get('state') == 'produced' and value.get('node') == 'I' and [r['node'] for r in log] == ['C', 'I'], {'fake_nodes': [r['node'] for r in log]}
    if sid == 'state':
        return out.count('"verified"') >= 2 and out.count('"pass"') >= 2 and out.strip().splitlines()[-1].strip() == 'base', {}
    return True, facts


if __name__ == '__main__':
    sys.exit(main())
