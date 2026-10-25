"""Delivery-gate HISTORY receipts (CG-<release>) for wfkit.release_check's gate_history rule.

  python -m wfkit.gate_history derive <old gate out dir> --out <new receipt.json>
      Derive a history receipt FROM an existing wfkit.gate decision.json without rewriting it. Allowed only when the build identity is proven
      from the artifacts on disk: build.json names the same commit and wheel sha256 as the decision, the tree was clean, the wheel/ file has
      that sha256, and every packaged file equals the commit's git blob. The receipt records its provenance (source paths + sha256).

  select_previous(paths) picks the latest PASSING CG- receipt: the build an ordinary upgrade must roll back to.
"""
import argparse
import hashlib
import json
import re
import subprocess
import zipfile
from pathlib import Path

from onecrew.ledger import LedgerError
from wfkit.finalgate import identity, timestamp

ROOT = Path(__file__).resolve().parents[1]
DIST_INFO = re.compile(r'onecrew-[^/]+\.dist-info/(METADATA|WHEEL|RECORD|entry_points\.txt)$')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.PIPE)


def wheel_matches_commit(path, commit, repo=ROOT):
    """Every packaged (non dist-info) file of the wheel equals the commit's git blob (modulo the CRLF that git archive / a Windows checkout
    writes under core.autocrlf), and the wheel's METADATA names the version in its file name. Returns the number of files compared."""
    path = Path(path)
    m = re.fullmatch(r'onecrew-(.+)-py3-none-any\.whl', path.name)
    if not m: raise LedgerError('wheel name is not onecrew-<version>-py3-none-any.whl: ' + path.name)
    tree = {}
    for line in git(repo, 'ls-tree', '-r', commit).decode('utf-8').splitlines():
        meta, name = line.split('\t', 1); tree[name] = meta.split()[2]
    compared = 0
    with zipfile.ZipFile(path) as archive:
        names = [i.filename for i in archive.infolist() if not i.is_dir()]
        meta = next((n for n in names if n.endswith('.dist-info/METADATA')), None)
        if meta is None or ('Version: ' + m.group(1)) not in archive.read(meta).decode('utf-8', 'replace').splitlines():
            raise LedgerError('wheel METADATA does not name version ' + m.group(1))
        for name in names:
            if DIST_INFO.fullmatch(name): continue
            data = archive.read(name)
            blobs = {hashlib.sha1(b'blob %d\0' % len(v) + v).hexdigest() for v in (data, data.replace(b'\r\n', b'\n'))}
            if tree.get(name) not in blobs: raise LedgerError('wheel file ' + name + ' is not the blob of ' + commit[:12])
            compared += 1
    if not compared: raise LedgerError('wheel has no packaged file to compare')
    return compared


def is_passing_delivery_gate(receipt):
    return isinstance(receipt, dict) and receipt.get('decision', receipt.get('result')) == 'pass' and str(receipt.get('gate', '')).startswith('CG-')


def derive(gate_dir, out, repo=ROOT):
    """A CG-<release> history receipt derived from an existing wfkit.gate output folder; the source is never modified."""
    gate_dir, out = Path(gate_dir), Path(out)
    if out.exists(): raise LedgerError('history receipt must be a new file: ' + str(out))
    decision_path, build_path = gate_dir / 'decision.json', gate_dir / 'build.json'
    decision = json.loads(decision_path.read_text(encoding='utf-8')); build = json.loads(build_path.read_text(encoding='utf-8'))
    if decision.get('decision') != 'pass': raise LedgerError('the source gate did not pass: ' + str(decision.get('decision')))
    release = decision.get('release')
    if not isinstance(release, str) or not release: raise LedgerError('the source decision names no release')
    if decision.get('gate') not in (None, 'CG-' + release): raise LedgerError('the source decision names another gate')
    ident = identity(decision)
    if identity(build) != ident: raise LedgerError('build.json and decision.json name different builds')
    if build.get('dirty'): raise LedgerError('the source gate built from a dirty tree')
    if build.get('release') not in (None, release): raise LedgerError('build.json was made for another release')
    wheels = sorted((gate_dir / 'wheel').glob('onecrew-*.whl'))
    if len(wheels) != 1: raise LedgerError('expected exactly one stored wheel in ' + str(gate_dir / 'wheel'))
    if sha(wheels[0]) != ident['wheel_sha256']: raise LedgerError('stored wheel bytes differ from the decision wheel sha256')
    if git(repo, 'rev-parse', ident['commit']).decode().strip() != ident['commit']: raise LedgerError('commit not in this repository')
    compared = wheel_matches_commit(wheels[0], ident['commit'], repo)
    receipt = {'gate': 'CG-' + release, 'release': release, 'decision': 'pass', **ident, 'at': decision['at'], 'wheel': str(wheels[0]),
               'derived': True, 'simulated': False,
               'provenance': {'kind': 'real', 'derivation': 'derived from an existing gate decision; the source file is unchanged',
                              'source': 'wfkit.gate_history derive',
                              'decision': {'path': str(decision_path), 'sha256': sha(decision_path)},
                              'build': {'path': str(build_path), 'sha256': sha(build_path)},
                              'wheel': {'path': str(wheels[0]), 'sha256': ident['wheel_sha256'], 'files_equal_to_commit_blobs': compared}},
               'delivered': False, 'owner_acceptance': False}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, ensure_ascii=False, indent=1, sort_keys=True), encoding='utf-8')
    return receipt


def select_previous(paths):
    """The latest PASSING CG- receipt among `paths` (and its path): the build an ordinary upgrade rolls back to. Refuses when none passes."""
    rows = []
    for path in paths:
        receipt = json.loads(Path(path).read_text(encoding='utf-8'))
        if is_passing_delivery_gate(receipt):
            identity(receipt); timestamp(receipt['at']); rows.append((receipt, Path(path)))
    if not rows: raise LedgerError('gate history has no passing CG- delivery gate receipt')
    return max(rows, key=lambda row: timestamp(row[0]['at']))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    d = sub.add_parser('derive'); d.add_argument('gate_dir'); d.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(derive(args.gate_dir, args.out), ensure_ascii=False)); return 0
    except (OSError, ValueError, KeyError, LedgerError, subprocess.SubprocessError) as error:
        print(json.dumps({'decision': 'refused', 'reason': str(error)}, ensure_ascii=False)); return 1


if __name__ == '__main__':
    raise SystemExit(main())
