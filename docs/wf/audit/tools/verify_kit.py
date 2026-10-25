# Builder helpers for the verifier that is SHIPPED in a handover package (verify/): copies, hash-pinned in manifest.json (`verifier`) and SHA256SUMS.
import hashlib
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[3]
LAUNCHERS = ('verify_package', 'legacy_continuation')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_commit(checkout=R):
    try:
        out = subprocess.run(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=30).stdout.strip()
        dirty = bool(subprocess.run(['git', '-C', str(checkout), 'status', '--porcelain', '--', 'wfkit/package_check.py', 'docs/wf/audit/tools'],
                                    capture_output=True, text=True, timeout=30).stdout.strip())
        return (out or 'unknown') + ('+uncommitted' if dirty else '')
    except Exception:
        return 'unknown'


def build_verify_dir(pkg, checkout=R):
    """Write <pkg>/verify/ and return the `verifier` block for manifest.json."""
    checkout, v = Path(checkout), Path(pkg) / 'verify'
    v.mkdir(parents=True)
    (v / 'package_check.py').write_bytes((checkout / 'wfkit' / 'package_check.py').read_bytes())
    (v / 'legacy_core.py').write_bytes((checkout / 'docs' / 'wf' / 'audit' / 'tools' / 'legacy_continuation.py').read_bytes())
    tpl = (HERE / 'shipped' / 'launcher_template.py').read_text(encoding='utf-8')
    for name in LAUNCHERS:
        (v / (name + '.py')).write_text(tpl.replace('@TOOL@', name), encoding='utf-8', newline='\n')
    files = {'verify/' + p.name: sha(p) for p in sorted(v.iterdir()) if p.is_file()}
    return {'files': files, 'source_commit': source_commit(checkout)}


def write_sums(pkg):
    pkg = Path(pkg)
    lines = [f'{sha(p)}  {p.relative_to(pkg).as_posix()}'
             for p in sorted(x for x in pkg.rglob('*') if x.is_file() and x.name != 'SHA256SUMS' and '__pycache__' not in x.parts)]
    (pkg / 'SHA256SUMS').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
    return len(lines)
