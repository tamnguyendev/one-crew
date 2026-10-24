"""kit-guard (WK0): the manifest of kit files and test files per release, frozen per release.

* `freeze <release>` pins (sha256 + provenance) the kit files and test modules the release's testcases name in `wfkit/testcases.json`, and
  every testcase entry of the release. Freezing again only ADDS pins; a drifted file is never re-pinned.
* `verify` refuses when a pinned file changed hash or was deleted, when a pinned testcase entry changed or was removed, or when the manifest
  itself was weakened against its committed version -- unless a U1 record (`wfkit/u1/<id>.json`: reason, file, old hash -> new hash) covers that
  exact change. kit-guard NEVER creates a U1: it is the owner's decision, written by hand.
* New files after the freeze are fine (the guard only stops weakening, not growth).

A pin key is the thing U1 names in `file`: a repo-relative path, `wfkit/testcases.json#<release>/<testcase>`, or `doc:wf-doc-check` (the
embedded document self-check of 06 section 7, whose code block lives in a document outside the repository).

Everything here is stdlib. `root` is the repository root (default: the root this file lives in).
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = 'wfkit/manifest.json'
CONFIG = 'wfkit/testcases.json'
U1_DIR = 'wfkit/u1'
DOC_PIN = 'doc:wf-doc-check'
DOC_NAME = '06-TRUY-VET-VA-TU-KIEM.vi.md'
FENCE = chr(96) * 3
HEX64 = re.compile(r'^[0-9a-f]{64}$')


def _now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    """sha256 of a pinned text file with CRLF read as LF, so the same commit has the same hash whatever core.autocrlf checked it out with
    (this repository's working trees are CRLF on Windows and LF elsewhere)."""
    return sha256_bytes(Path(path).read_bytes().replace(b'\r\n', b'\n'))


def canon_sha(obj):
    return sha256_bytes(json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8'))


def _read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False, sort_keys=True) + '\n', encoding='utf-8', newline='\n')


def load_config(root):
    return _read_json(Path(root) / CONFIG)


def load_manifest(root):
    p = Path(root) / MANIFEST
    if not p.is_file():
        return {'version': 1, 'releases': {}}
    return _read_json(p)


def module_path(module):
    """tests.test_wf_x -> tests/test_wf_x.py"""
    return module.replace('.', '/') + '.py'


def extract_doc_block(doc_dir):
    """The embedded self-check of 06 section 7: the ONE python block of the section headed `## 7.`.
    Returns {'sha256', 'count', 'text'}; sha256 is of the block text from the line after the python fence up to the closing fence
    (LF line ends), the rule 06 section 7 states for its own hash. `sha256` is None unless there is exactly one python block."""
    path = Path(doc_dir) / DOC_NAME
    if not path.is_file():
        return {'sha256': None, 'count': 0, 'text': None, 'error': f'{path} is missing'}
    text = path.read_text(encoding='utf-8').replace('\r', '')
    m = re.search(r'^## 7\.[^\n]*\n', text, re.M)
    if not m:
        return {'sha256': None, 'count': 0, 'text': None, 'error': 'no section "## 7." in ' + DOC_NAME}
    rest = text[m.end():]
    nxt = re.search(r'^## ', rest, re.M)
    section = rest[:nxt.start()] if nxt else rest
    blocks = re.findall(FENCE + r'python\n(.*?)' + FENCE, section, re.S)
    count = len(re.findall(FENCE + 'python', section))
    if count != 1 or len(blocks) != 1:
        return {'sha256': None, 'count': count, 'text': None, 'error': f'section 7 must hold exactly one python block, found {count}'}
    return {'sha256': sha256_bytes(blocks[0].encode('utf-8')), 'count': 1, 'text': blocks[0]}


# ---- what a release pins -----------------------------------------------------------------------------------------------------

def release_candidates(root, release, doc_dir=None):
    """{pin key: {'kind', 'path'?, 'sha256' or None, 'missing'?}} for what freezing `release` would pin now."""
    root = Path(root)
    cfg = load_config(root)
    rel = cfg['releases'][release]
    out = {}
    files = list(rel.get('kit_files', []))
    for tc in rel.get('testcases', {}).values():
        for mod in tc.get('modules', []):
            files.append(module_path(mod))
    for f in files:
        p = root / f
        out[f] = {'kind': 'file', 'path': f, 'sha256': sha256_file(p) if p.is_file() else None}
    if (root / CONFIG).is_file():
        for tc, entry in rel.get('testcases', {}).items():
            out[f'{CONFIG}#{release}/{tc}'] = {'kind': 'case', 'release': release, 'testcase': tc, 'sha256': canon_sha(entry)}
    if doc_dir is not None:
        blk = extract_doc_block(doc_dir)
        out[DOC_PIN] = {'kind': 'doc', 'sha256': blk['sha256'], 'error': blk.get('error')}
    return out


def _actual(root, key, pin, doc_dir):
    """(sha or None, available) for a pin right now. available False = cannot be judged here (doc pin without doc_dir)."""
    root = Path(root)
    kind = pin['kind']
    if kind == 'file':
        p = root / pin['path']
        return (sha256_file(p) if p.is_file() else None), True
    if kind == 'case':
        cfg = load_config(root) if (root / CONFIG).is_file() else {'releases': {}}
        entry = cfg.get('releases', {}).get(pin['release'], {}).get('testcases', {}).get(pin['testcase'])
        return (canon_sha(entry) if entry is not None else None), True
    if kind == 'doc':
        if doc_dir is None:
            return None, False
        return extract_doc_block(doc_dir)['sha256'], True
    return None, True


# ---- U1 ----------------------------------------------------------------------------------------------------------------------

def load_u1(root):
    """(valid records by (file, old_sha256), invalid [{path, why}]). A U1 is the owner's record; this module only reads them."""
    d = Path(root) / U1_DIR
    valid, invalid = {}, []
    if not d.is_dir():
        return valid, invalid
    for p in sorted(d.glob('*.json')):
        try:
            rec = _read_json(p)
        except (OSError, ValueError) as e:
            invalid.append({'path': p.name, 'why': f'unreadable: {e}'})
            continue
        why = None
        if not isinstance(rec, dict):
            why = 'not an object'
        elif rec.get('id') != p.stem:
            why = f'id {rec.get("id")!r} does not match the file name {p.stem!r}'
        elif not isinstance(rec.get('reason'), str) or len(rec['reason'].strip()) < 8:
            why = 'reason missing or empty'
        elif not isinstance(rec.get('file'), str) or not rec['file'].strip():
            why = 'file missing'
        elif not isinstance(rec.get('old_sha256'), str) or not HEX64.match(rec['old_sha256']):
            why = 'old_sha256 missing or not a sha256'
        elif rec.get('new_sha256') is not None and not (isinstance(rec['new_sha256'], str) and HEX64.match(rec['new_sha256'])):
            why = 'new_sha256 must be a sha256 or null (deletion)'
        if why:
            invalid.append({'path': p.name, 'why': why})
            continue
        valid.setdefault((rec['file'], rec['old_sha256']), []).append(rec)
    return valid, invalid


def _follow(u1, key, start, target):
    """The U1 records that take `start` to `target` for pin `key`, or None when there is no such chain."""
    chain, cur, seen = [], start, {start}
    while cur != target:
        nxt = None
        for rec in u1.get((key, cur), []):
            new = rec.get('new_sha256')
            if new == target:                                  # prefer the record that lands on the target
                nxt = rec
                break
            if new is not None and new not in seen and nxt is None:
                nxt = rec
        if nxt is None:
            return None
        chain.append(nxt)
        cur = nxt.get('new_sha256')
        if cur is None:                                        # a deletion record ends the chain
            return chain if target is None else None
        seen.add(cur)
    return chain


# ---- freeze / verify ---------------------------------------------------------------------------------------------------------

def freeze(root, release, *, commit=None, doc_dir=None):
    """Pin what `release` names. Only ADDS: existing pins are never rewritten; a file that drifted from its pin makes this refuse (and write
    nothing). Returns {'ok', 'added', 'problems'}."""
    root = Path(root)
    cfg = load_config(root)
    if release not in cfg.get('releases', {}):
        return {'ok': False, 'added': [], 'problems': [{'code': 'unknown-release', 'release': release}]}
    manifest = load_manifest(root)
    owned = {k: (r, p) for r, rr in manifest['releases'].items() for k, p in rr['pins'].items()}
    problems, new = [], {}
    for key, cand in release_candidates(root, release, doc_dir).items():
        if cand['sha256'] is None:
            problems.append({'code': 'missing', 'pin': key, 'release': release, 'detail': cand.get('error') or 'file not found'})
        elif key in owned:
            if owned[key][1]['sha256'] != cand['sha256']:
                problems.append({'code': 'changed', 'pin': key, 'release': owned[key][0], 'pinned_sha256': owned[key][1]['sha256'],
                                 'actual_sha256': cand['sha256'], 'detail': 'drifted from its pin: freeze does not re-pin (needs a U1)'})
        else:
            pin = {k: v for k, v in cand.items() if k != 'error'}
            pin.update({'added_at': _now(), 'commit': commit or head_commit(root)})
            new[key] = pin
    if problems:
        return {'ok': False, 'added': [], 'problems': problems}
    rr = manifest['releases'].setdefault(release, {'frozen_at': _now(), 'commit': commit or head_commit(root), 'pins': {}})
    rr['pins'].update(new)
    manifest['version'] = 1
    _write_json(root / MANIFEST, manifest)
    return {'ok': True, 'added': sorted(new), 'problems': []}


def head_commit(root):
    try:
        r = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None
    except OSError:
        return None


def _committed_manifest(root):
    """The manifest as of HEAD, or None when the root is not a repository / the file is not committed."""
    try:
        r = subprocess.run(['git', '-C', str(root), 'show', 'HEAD:' + MANIFEST], capture_output=True, text=True, encoding='utf-8')
    except OSError:
        return None
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except ValueError:
        return None


def verify(root, releases=None, *, doc_dir=None):
    """Judge every frozen release (or the named ones, which must be frozen). Returns
    {'ok', 'problems': [{code, pin, release, pinned_sha256?, actual_sha256?, detail}], 'u1_used', 'u1_invalid', 'manifest_sha256', 'pinned',
     'unchecked': [pin keys that need doc_dir], 'head_check'}."""
    root = Path(root)
    manifest = load_manifest(root)
    mp = root / MANIFEST
    u1, u1_invalid = load_u1(root)
    problems, used, unchecked = [], [], []
    pinned = 0
    for rel in releases or []:
        if rel not in manifest['releases']:
            problems.append({'code': 'not-frozen', 'release': rel, 'pin': None, 'detail': f'{rel} has no frozen kit in {MANIFEST}'})
    for rel, body in sorted(manifest['releases'].items()):
        for key, pin in sorted(body['pins'].items()):
            pinned += 1
            actual, available = _actual(root, key, pin, doc_dir)
            if not available:
                unchecked.append(key)
                continue
            if actual == pin['sha256']:
                continue
            chain = _follow(u1, key, pin['sha256'], actual)
            if chain:
                used.extend(chain)
                continue
            problems.append({'code': 'deleted' if actual is None else 'changed', 'pin': key, 'release': rel,
                             'pinned_sha256': pin['sha256'], 'actual_sha256': actual,
                             'detail': 'pinned file/entry is gone' if actual is None else 'pinned file/entry changed hash'})
    head = _committed_manifest(root)
    if head is not None:                                           # a pin deleted or rewritten in the working manifest = weakening
        have = {k: p for rr in manifest['releases'].values() for k, p in rr['pins'].items()}
        for rel, body in sorted(head.get('releases', {}).items()):
            for key, pin in sorted(body.get('pins', {}).items()):
                cur = have.get(key)
                if cur is None:
                    if not _follow(u1, key, pin['sha256'], None):
                        problems.append({'code': 'pin-removed', 'pin': key, 'release': rel, 'pinned_sha256': pin['sha256'],
                                         'detail': 'the pin was in the committed manifest and is gone'})
                elif cur['sha256'] != pin['sha256']:
                    chain = _follow(u1, key, pin['sha256'], cur['sha256'])
                    if chain:
                        used.extend(c for c in chain if c not in used)
                    else:
                        problems.append({'code': 'pin-rewritten', 'pin': key, 'release': rel, 'pinned_sha256': pin['sha256'],
                                         'actual_sha256': cur['sha256'], 'detail': 'the pinned hash differs from the committed manifest'})
    uniq, seen = [], set()
    for rec in used:
        if rec['id'] not in seen:
            seen.add(rec['id'])
            uniq.append(rec)
    return {'ok': not problems, 'problems': problems, 'u1_used': uniq, 'u1_invalid': u1_invalid,
            'manifest_sha256': sha256_file(mp) if mp.is_file() else None, 'pinned': pinned, 'unchecked': unchecked,
            'head_check': 'done' if head is not None else 'unavailable'}


def check_doc_block(root, doc_dir):
    """Is the embedded document self-check the one kit-guard has pinned? {'ok', 'sha256', 'problems', 'u1_used', 'manifest_sha256'}."""
    root = Path(root)
    blk = extract_doc_block(doc_dir)
    manifest = load_manifest(root)
    pin = next((rr['pins'][DOC_PIN] for rr in manifest['releases'].values() if DOC_PIN in rr['pins']), None)
    problems, used = [], []
    if blk['sha256'] is None:
        problems.append({'code': 'no-block', 'pin': DOC_PIN, 'detail': blk.get('error')})
    elif pin is None:
        problems.append({'code': 'unregistered', 'pin': DOC_PIN, 'detail': 'the document self-check is not registered with kit-guard'})
    elif blk['sha256'] != pin['sha256']:
        u1, _ = load_u1(root)
        chain = _follow(u1, DOC_PIN, pin['sha256'], blk['sha256'])
        if chain:
            used = chain
        else:
            problems.append({'code': 'changed', 'pin': DOC_PIN, 'pinned_sha256': pin['sha256'], 'actual_sha256': blk['sha256'],
                             'detail': 'the embedded self-check differs from the registered one'})
    mp = root / MANIFEST
    return {'ok': not problems, 'sha256': blk['sha256'], 'problems': problems, 'u1_used': used,
            'manifest_sha256': sha256_file(mp) if mp.is_file() else None}


# ---- CLI ---------------------------------------------------------------------------------------------------------------------

def _print_problems(res):
    for p in res['problems']:
        extra = ''
        if p.get('pinned_sha256'):
            extra += f" pinned={p['pinned_sha256'][:16]}"
        if p.get('actual_sha256'):
            extra += f" now={p['actual_sha256'][:16]}"
        print(f"  REFUSED {p['code']}: {p.get('pin')} ({p.get('release')}){extra} {p.get('detail') or ''}".rstrip())


def main(argv=None):
    ap = argparse.ArgumentParser(prog='kitguard', description='kit-guard: freeze and verify the release kits')
    ap.add_argument('--root', default=str(ROOT))
    sub = ap.add_subparsers(dest='cmd', required=True)
    f = sub.add_parser('freeze', help='pin the kit and test files of a release (only adds)')
    f.add_argument('release')
    f.add_argument('--doc-dir', default=None, help='also register the 06 section 7 self-check of this folder')
    v = sub.add_parser('verify', help='refuse when a pinned file changed or was deleted (unless covered by a U1)')
    v.add_argument('--release', action='append', default=None)
    v.add_argument('--doc-dir', default=None)
    a = ap.parse_args(argv)
    if a.cmd == 'freeze':
        res = freeze(a.root, a.release, doc_dir=a.doc_dir)
        print(f"freeze {a.release}: {'ok' if res['ok'] else 'REFUSED'}; added {len(res['added'])} pin(s)")
        for k in res['added']:
            print('  +', k)
        _print_problems(res)
        return 0 if res['ok'] else 1
    res = verify(a.root, a.release, doc_dir=a.doc_dir)
    print(f"verify: {'ok' if res['ok'] else 'REFUSED'}; {res['pinned']} pin(s), manifest {res['manifest_sha256']}, head check {res['head_check']}")
    for rec in res['u1_used']:
        print(f"  U1 {rec['id']}: {rec['file']} {rec['old_sha256'][:16]} -> {(rec['new_sha256'] or 'deleted')[:16]} ({rec['reason']})")
    for k in res['unchecked']:
        print('  unchecked (needs --doc-dir):', k)
    _print_problems(res)
    return 0 if res['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
