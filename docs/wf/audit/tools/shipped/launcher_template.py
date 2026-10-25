# Verifier launcher SHIPPED INSIDE the handover package (verify/). Stdlib only; needs Python 3.11+, no checkout, no PYTHONPATH.
#   python verify/@TOOL@.py [<package dir>] [<work dir (new, outside the package)>] [--self-check-only]
# Order: 1. verify THIS folder against manifest.json (verifier.files) and SHA256SUMS; 2. import ONLY the sibling copies; 3. refuse when any
# `wfkit`/`package_check` module resolved outside this folder; 4. run; 5. record which module files were used (verification/verifier-origin.json).
import hashlib
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
TOOL = '@TOOL@'
HERE = Path(__file__).resolve().parent
PKG_ROOT = HERE.parent
OWN = ('package_check', 'legacy_core')


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def self_check():
    """-> (reasons, {relative path: sha256}); no reason == this verify/ folder is exactly what the manifest pinned."""
    reasons = []
    try:
        manifest = json.loads((PKG_ROOT / 'manifest.json').read_text(encoding='utf-8'))
        files = manifest['verifier']['files']
        if not isinstance(files, dict) or not files:
            raise ValueError('verifier.files is empty')
    except Exception as e:
        return ['manifest.json has no usable verifier.files: %s: %s' % (type(e).__name__, e)], {}
    sums = {}
    try:
        for line in (PKG_ROOT / 'SHA256SUMS').read_text(encoding='utf-8').splitlines():
            if line.strip():
                h, _, rel = line.partition('  ')
                sums[rel.strip()] = h.strip()
    except Exception as e:
        reasons.append('SHA256SUMS unreadable: %s: %s' % (type(e).__name__, e))
    for rel, want in sorted(files.items()):
        p = PKG_ROOT / rel
        if '..' in Path(rel).parts or Path(rel).parts[:1] != ('verify',):
            reasons.append('verifier file outside verify/: ' + rel)
        elif not p.is_file():
            reasons.append('verifier file missing: ' + rel)
        else:
            if _sha(p) != want:
                reasons.append('verifier file modified (sha256 differs from manifest.json): ' + rel)
            if sums.get(rel) != want:
                reasons.append('verifier file hash in SHA256SUMS differs from manifest.json: ' + rel)
    for p in sorted(HERE.iterdir()):
        if p.name != '__pycache__' and ('verify/' + p.name) not in files:
            reasons.append('unlisted file in verify/ (would be importable): verify/' + p.name)
    return reasons, files


def origin_record(files):
    """Module files actually imported. foreign = a wfkit/package_check module that is not this package's copy."""
    mods, foreign = [], []
    for name, m in sorted(sys.modules.items()):
        f = getattr(m, '__file__', None)
        fp = Path(f).resolve() if f else None
        inside = bool(fp) and fp.is_relative_to(HERE)
        if inside:
            mods.append({'module': name, 'file': str(fp), 'sha256': _sha(fp)})
        if not inside and (name == 'wfkit' or name.startswith('wfkit.') or name in OWN):
            foreign.append({'module': name, 'file': str(fp) if fp else None})
    return {'tool': TOOL, 'package': str(PKG_ROOT), 'verify_dir': str(HERE), 'python': sys.version.split()[0], 'modules': mods,
            'foreign': foreign, 'verifier_files': files}


def _write_origin(work, rec):
    d = Path(work) / 'verification'
    d.mkdir(parents=True, exist_ok=True)
    (d / 'verifier-origin.json').write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding='utf-8')


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    only = '--self-check-only' in argv
    args = [a for a in argv if a != '--self-check-only']
    if len(args) > 2 or (not only and len(args) != 2):
        print('usage: %s.py <package dir> <work dir (new, outside the package)>   |   %s.py --self-check-only [<package dir>] [<work dir>]' % (TOOL, TOOL), file=sys.stderr)
        return 2
    reasons, files = self_check()
    if reasons:
        print(json.dumps({'result': 'refused', 'stage': 'verifier self-check', 'reasons': reasons}, ensure_ascii=False, indent=1), file=sys.stderr)
        return 3
    if sys.version_info < (3, 11):
        print('Python 3.11+ is required', file=sys.stderr)
        return 3
    pkg = Path(args[0]).resolve() if args else PKG_ROOT
    work = Path(args[1]).resolve() if len(args) > 1 else None
    sys.path.insert(0, str(HERE))
    import package_check  # noqa: F401  the sibling copy, pinned above
    if TOOL == 'legacy_continuation':
        import legacy_core
    rec = origin_record(files)
    if rec['foreign']:
        print(json.dumps({'result': 'refused', 'stage': 'module origin', 'foreign': rec['foreign']}, ensure_ascii=False, indent=1), file=sys.stderr)
        return 4
    if only:
        if work is not None:
            _write_origin(work, rec)
        print(json.dumps({'result': 'self-check-ok', **rec}, ensure_ascii=False, indent=1))
        return 0
    if TOOL == 'legacy_continuation':
        code = legacy_core.main([str(pkg), str(work)])
    else:
        code = package_check.main([str(pkg), str(work)])
    rec = origin_record(files)
    _write_origin(work, rec)
    if rec['foreign']:
        print(json.dumps({'result': 'refused', 'stage': 'module origin (after run)', 'foreign': rec['foreign']}, ensure_ascii=False), file=sys.stderr)
        return 4
    return code


if __name__ == '__main__':
    sys.exit(main())
