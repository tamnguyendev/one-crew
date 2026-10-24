"""T38a (WK0): the embedded document self-check of 06 section 7, run as a kit command, through kit-guard.

This only RE-RUNS the existing self-check. It does not edit or extend it. Steps:
  1. take the one python block of section 7 out of 06-TRUY-VET-VA-TU-KIEM.vi.md (kitguard.extract_doc_block) and ask kit-guard whether it is
     the registered one (hash pinned in wfkit/manifest.json); an unregistered or changed block is REFUSED, never run;
  2. run it in a child interpreter, in memory (the code goes in on stdin), with the document folder as working directory, which it only reads;
  3. require exit 0, `PROBLEMS: 0` and every counterexample caught (BẮT), no false alarm on a control, and that the document folder (and its
     parent, where the checker reads the roadmap files) were not touched.
The result is a receipt (testcase T38a) carrying the block hash, the kit-guard verdict, the counts and the document file hashes the checker prints.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from wfkit import kitguard
except ImportError:                                               # run as a script: wfkit/ is sys.path[0]
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from wfkit import kitguard

DEFAULT_DOC_DIR = r'D:\TamNT\Workspace\11.OneCrew\outputs\onecrew-as-qc\workflow-chung'
ROOT = kitguard.ROOT


def _now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _snapshot(doc_dir):
    """(size, mtime_ns) of every file under the document folder and of the files directly in its parent."""
    snap = {}
    doc_dir = Path(doc_dir)
    for base, recursive in ((doc_dir, True), (doc_dir.parent, False)):
        it = base.rglob('*') if recursive else base.glob('*')
        for p in it:
            if p.is_file():
                try:
                    st = p.stat()
                except OSError:
                    continue
                snap[str(p)] = (st.st_size, st.st_mtime_ns)
    return snap


def parse_output(text):
    """Read the self-check's report: PROBLEMS count, document hashes, counterexample verdicts, controls, summary line."""
    res = {'problems': None, 'doc_files': {}, 'caught': 0, 'missed': [], 'wrong_reason': [], 'not_applicable': [],
           'controls_ok': 0, 'false_alarms': [], 'summary': None, 'cx_lines': 0}
    in_cx = False
    for raw in text.splitlines():
        line = raw.strip()
        m = re.match(r'^PROBLEMS:\s*(\d+)\s*$', line)
        if m:
            res['problems'] = int(m.group(1))
            continue
        m = re.match(r'^sha256\s+([0-9a-f]{16})\s+(.+)$', line)
        if m:
            res['doc_files'][m.group(2)] = m.group(1)
            continue
        if line.startswith('phản chứng và đối chứng'):
            in_cx = True
            continue
        m = re.match(r'^phản chứng bị bắt đúng lý do:\s*(\d+)/(\d+);\s*đối chứng không bị báo:\s*(\d+)/(\d+)', line)
        if m:
            in_cx = False
            res['summary'] = {'caught': int(m.group(1)), 'total': int(m.group(2)), 'controls_ok': int(m.group(3)), 'controls_total': int(m.group(4))}
            continue
        if not in_cx or not line:
            continue
        res['cx_lines'] += 1
        if line.startswith('BẮT SAI LÝ DO'):
            res['wrong_reason'].append(line)
        elif line.startswith('BẮT'):
            res['caught'] += 1
        elif line.startswith('LỌT'):
            res['missed'].append(line)
        elif line.startswith('KHÔNG ÁP ĐƯỢC'):
            res['not_applicable'].append(line)
        elif line.startswith('ĐÚNG'):
            res['controls_ok'] += 1
        elif line.startswith('BÁO NHẦM'):
            res['false_alarms'].append(line)
        else:
            res['missed'].append('UNRECOGNISED ' + line)          # an unknown verdict is never read as caught
    return res


def run(doc_dir, root=ROOT, *, python=None, timeout=3600):
    """Run the T38a command. Returns a receipt dict; result is 'pass', 'fail' (ran, found a problem) or 'refused' (did not run)."""
    doc_dir = Path(doc_dir)
    rec = {'testcase': 'T38a', 'kind': 'doccheck', 'at': _now(), 'doc_dir': str(doc_dir), 'result': 'refused', 'reason': None}
    if not doc_dir.is_dir():
        rec['reason'] = f'document folder {doc_dir} not found'
        return rec
    blk = kitguard.extract_doc_block(doc_dir)
    rec['block_sha256'] = blk['sha256']
    if blk['sha256'] is None:
        rec['reason'] = blk.get('error') or 'no self-check block'
        rec['kit_guard'] = {'ok': False, 'problems': [{'code': 'no-block', 'pin': kitguard.DOC_PIN, 'detail': rec['reason']}]}
        return rec
    kg = kitguard.check_doc_block(root, doc_dir)
    rec['kit_guard'] = kg
    rec['manifest_sha256'] = kg.get('manifest_sha256')
    if not kg['ok']:
        rec['reason'] = 'kit-guard refused the self-check: ' + '; '.join(f"{p['code']} {p['pin']}" for p in kg['problems'])
        return rec
    python = python or sys.executable
    cmd = [str(python), '-I', '-X', 'utf8', '-']
    rec['command'] = f'{python} -I -X utf8 - < section-7 block {blk["sha256"][:16]} (cwd={doc_dir})'
    env = {k: v for k, v in os.environ.items() if not k.startswith('WFCHECK_')}      # the full run: counterexamples included
    env['PYTHONIOENCODING'] = 'utf-8'
    before = _snapshot(doc_dir)
    try:
        r = subprocess.run(cmd, input=blk['text'].encode('utf-8'), capture_output=True, cwd=str(doc_dir), env=env, timeout=timeout)
        out = r.stdout.decode('utf-8', errors='replace') + r.stderr.decode('utf-8', errors='replace')
        code = r.returncode
    except subprocess.TimeoutExpired as e:
        out = ((e.stdout or b'').decode('utf-8', errors='replace')) if isinstance(e.stdout, bytes) else (e.stdout or '')
        code = None
    after = _snapshot(doc_dir)
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    rec['changed_in_doc_dir'] = changed
    rec['exit_code'] = code
    rec['output_tail'] = out[-1500:]
    parsed = parse_output(out)
    rec['problems'] = parsed['problems']
    rec['doc_files'] = parsed['doc_files']
    rec['counterexamples'] = {k: parsed[k] for k in ('caught', 'missed', 'wrong_reason', 'not_applicable', 'controls_ok', 'false_alarms', 'summary')}
    why = []
    if code is None:
        why.append('timed out')
    elif code != 0:
        why.append(f'exit code {code}')
    if parsed['problems'] is None:
        why.append('no "PROBLEMS: n" line')
    elif parsed['problems'] != 0:
        why.append(f"PROBLEMS: {parsed['problems']}")
    if parsed['summary'] is None:
        why.append('no counterexample summary line')
    else:
        s = parsed['summary']
        if s['caught'] != parsed['caught']:
            why.append(f"summary says {s['caught']} caught, the lines show {parsed['caught']}")
        if s['controls_ok'] != s['controls_total'] or s['controls_ok'] != parsed['controls_ok']:
            why.append('a control was not clean')
    if parsed['caught'] < 1:
        why.append('no counterexample was caught (an empty counterexample run proves nothing)')
    if parsed['missed']:
        why.append(f"{len(parsed['missed'])} counterexample(s) slipped through")
    if parsed['wrong_reason']:
        why.append(f"{len(parsed['wrong_reason'])} counterexample(s) caught for the wrong reason")
    if parsed['false_alarms']:
        why.append(f"{len(parsed['false_alarms'])} false alarm(s) on controls")
    if changed:
        why.append('the checker changed files it must only read')
    rec['result'] = 'pass' if not why else 'fail'
    rec['reason'] = '; '.join(why) if why else None
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser(prog='doccheck', description='T38a: run the 06 section 7 document self-check through kit-guard')
    ap.add_argument('--doc-dir', default=os.environ.get('WF_DOC_DIR', DEFAULT_DOC_DIR))
    ap.add_argument('--root', default=str(ROOT))
    ap.add_argument('--out', default=None, help='write the receipt JSON here')
    a = ap.parse_args(argv)
    rec = run(a.doc_dir, a.root)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(rec, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    cx = rec.get('counterexamples') or {}
    print(f"T38a: {rec['result'].upper()}  block {str(rec.get('block_sha256'))[:16]}  PROBLEMS: {rec.get('problems')}  "
          f"caught {cx.get('caught')}  missed {len(cx.get('missed', []))}  wrong-reason {len(cx.get('wrong_reason', []))}  "
          f"not-applicable {len(cx.get('not_applicable', []))}")
    if rec.get('reason'):
        print('  ' + rec['reason'])
    return 0 if rec['result'] == 'pass' else 1


if __name__ == '__main__':
    sys.exit(main())
