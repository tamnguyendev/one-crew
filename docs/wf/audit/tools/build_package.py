# The development handover package (directive I, 24/10): one folder with the wheel + sha256, the commit/snapshot identity, the gate decision and
# receipts, the T54 bundles' verdicts, the 92-task table, release notes, and a README that says how to install into a clean venv OUTSIDE the
# checkout, smoke-test, and roll back. Nothing here claims delivery, Codex review or owner acceptance.
#   python docs/wf/audit/tools/build_package.py <snapshot-gate out dir> <package dir (new)> [--bundles bundles.json] [--audit audit-92.json] (--previous-wheel path [--previous-evidence manifest.json|sidecar.json] | --first-release)
# Round 11 D: the package is ONE commit/ONE wheel. The 92-task table, every produced bundle, the gate snapshot and every gate receipt must name the gate's commit
# (short-sha prefix match) and the bundles the gate's wheel sha256, else the build is refused before anything is written. The previous wheel's provenance is read
# from evidence (the previous package's manifest.json, a wheel sidecar, or the wheel's own METADATA), never written by hand. Every bundle result is kept, refused ones included.
import argparse, hashlib, json, os, re, shutil, sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verify_kit  # noqa: E402

R = Path(os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..')))
sys.path.insert(0, str(R))
from wfkit.release_check import inputs_summary, inputs_sentence  # noqa: E402
from wfkit import package_check  # noqa: E402


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def previous_provenance(wheel_path, evidence=None):
    """-> {'file', 'sha256', 'commit', 'version', 'source'} for the previous wheel, from evidence only. Order: --previous-evidence, the wheel's sidecar
    (<wheel>.json), the manifest.json of the package the wheel sits in, the wheel's own METADATA (version only; commit stays None). Evidence that names
    this wheel with another sha256, or another version than the wheel's METADATA, refuses the build; evidence that names another file is not evidence."""
    p = Path(wheel_path)
    digest = sha(p)
    meta = package_check.wheel_metadata_version(p)

    def from_json(path):
        doc = _read(path)
        if 'sha256' in doc and 'wheel' not in doc:                      # a sidecar for exactly one wheel
            if doc['sha256'] != digest:
                sys.exit(f'previous wheel evidence {path} names sha256 {doc["sha256"]}, the wheel is {digest}')
            return {'commit': doc.get('commit'), 'version': doc.get('version'), 'source': 'wheel sidecar'}
        for entry, commit in ((doc.get('wheel'), doc.get('commit')), (doc.get('previous_wheel'), (doc.get('previous_wheel') or {}).get('commit'))):
            if isinstance(entry, dict) and Path(str(entry.get('file', ''))).name == p.name:
                if entry.get('sha256') != digest:
                    sys.exit(f'previous wheel evidence {path} names sha256 {entry.get("sha256")} for {p.name}, the wheel is {digest}')
                version = doc.get('version') if entry is doc.get('wheel') else entry.get('version')
                return {'commit': commit, 'version': version, 'source': 'previous package manifest.json'}
        return None

    found = None
    if evidence:
        found = from_json(evidence)
        if found is None:
            sys.exit(f'previous wheel evidence {evidence} does not name {p.name}')
    else:
        for cand in (Path(str(p) + '.json'), p.parent.parent / 'manifest.json'):
            if cand.is_file():
                found = from_json(cand)
                if found:
                    break
    if found is None:
        if meta is None:
            sys.exit(f'no evidence for the previous wheel {p.name}: not a readable wheel (no METADATA), no sidecar, no adjacent package manifest.json, no --previous-evidence')
        found = {'commit': None, 'version': meta, 'source': 'wheel METADATA'}
    version = found.get('version') or meta
    if meta is not None and version != meta:
        sys.exit(f'previous wheel evidence says version {version}, the wheel METADATA says {meta}')
    if version is None or not p.name.startswith(f'onecrew-{version}-'):
        sys.exit(f'previous wheel file name {p.name} does not carry the evidenced version {version}')
    return {'file': 'wheel/previous/' + p.name, 'sha256': digest, 'commit': found.get('commit'), 'version': version, 'source': found['source']}


def check_one_build(gate_out, build, decision, audit_path, bundle_results, problems):
    """Every input that names a commit or a wheel digest must name the gate's. Appends to `problems`."""
    commit, wheel_sha = build['commit'], build['wheel_sha256']
    same = package_check.commit_matches
    audit = _read(audit_path)
    if not same(audit.get('commit'), commit):
        problems.append(f'{audit_path}: audit-92.json commit is {audit.get("commit")!r}, the gate commit is {commit[:12]} (run audit_merge.py for this commit BEFORE build_package)')
    md = Path(audit_path).with_name('AUDIT-92.md')
    if md.is_file():
        m = re.search(r'Commit kiểm: `([^`]*)`', md.read_text(encoding='utf-8'))
        if not same(m.group(1) if m else None, commit):
            problems.append(f'{md}: AUDIT-92.md "Commit kiểm" is {m.group(1) if m else None!r}, the gate commit is {commit[:12]}')
    for label, doc in (('snapshot.json', _read(gate_out / 'snapshot.json')), ('decision.json snapshot', decision.get('snapshot') or {})):
        if 'commit' in doc and not same(doc['commit'], commit):
            problems.append(f'gate {label} commit is {doc["commit"]!r}, build.json says {commit[:12]}')
    for f in sorted((gate_out / 'gate' / 'receipts').glob('*.json')):
        r = _read(f)
        if 'commit' in r and not same(r['commit'], commit):
            problems.append(f'receipt {f.name} commit is {r["commit"]!r}, the gate commit is {commit[:12]}')
    for rel, v in sorted(bundle_results.items()):
        if v.get('produced') is False:
            continue                                               # a refused/blocked release produced no bundle: nothing to compare, its refusal is the evidence
        if not same(v.get('commit'), commit):
            problems.append(f'bundle {rel}: commit is {v.get("commit")!r}, the gate commit is {commit[:12]}')
        if v.get('wheel_sha256') != wheel_sha:
            problems.append(f'bundle {rel}: wheel sha256 is {v.get("wheel_sha256")!r}, the gate wheel is {wheel_sha}')


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument('gate_out'); ap.add_argument('package'); ap.add_argument('--bundles'); ap.add_argument('--previous-wheel'); ap.add_argument('--matrix', help='W45 provider matrix dir (matrix.json/matrix.md/receipts)')
    ap.add_argument('--audit', help='audit-92.json of THIS commit (default: docs/wf/audit/audit-92.json of the checkout); AUDIT-92.md is read beside it')
    ap.add_argument('--previous-evidence', help='manifest.json of the previous package, or a wheel sidecar json, naming the previous wheel (default: <wheel>.json, then the manifest.json two levels above the wheel)')
    ap.add_argument('--first-release', action='store_true', help='declare a first-release package (kind first-release-handover-package): no previous wheel, rollback not evaluated')
    a = ap.parse_args(argv)
    # P1-3: the manifest KIND declares the verification scope; it is chosen here explicitly, never inferred from a missing flag.
    if bool(a.previous_wheel) == bool(a.first_release):
        sys.exit('give exactly one of --previous-wheel (rollback drill mandatory) or --first-release (no previous wheel exists)')
    kind = 'first-release-handover-package' if a.first_release else 'development-handover-package'
    gate_out, pkg = Path(a.gate_out), Path(a.package)
    if pkg.exists(): sys.exit('package dir must be new: ' + str(pkg))
    build = json.load(open(gate_out / 'gate' / 'build.json', encoding='utf-8'))
    decision = json.load(open(gate_out / 'decision.json', encoding='utf-8'))
    snapshot = json.load(open(gate_out / 'snapshot.json', encoding='utf-8'))
    commit, wheel_sha, version = build['commit'], build['wheel_sha256'], build['version']
    wheel_src = Path(build['wheel'])
    if sha(wheel_src) != wheel_sha: sys.exit('wheel bytes do not match build.json')
    audit_path = Path(a.audit) if a.audit else R / 'docs' / 'wf' / 'audit' / 'audit-92.json'
    index = json.load(open(a.bundles, encoding='utf-8')) if a.bundles else {}
    bundle_results = {rel: _read(path) for rel, path in index.items()}
    problems = []
    check_one_build(gate_out, build, decision, audit_path, bundle_results, problems)
    if problems: sys.exit('refusing to build a package from inputs of different builds:\n  ' + '\n  '.join(problems))
    previous = previous_provenance(a.previous_wheel, a.previous_evidence) if a.previous_wheel else None       # evidence first: a refusal leaves nothing behind
    (pkg / 'wheel').mkdir(parents=True); shutil.copy2(wheel_src, pkg / 'wheel' / wheel_src.name)
    if a.previous_wheel:
        p = Path(a.previous_wheel); (pkg / 'wheel' / 'previous').mkdir(); shutil.copy2(p, pkg / 'wheel' / 'previous' / p.name)
    (pkg / 'gate').mkdir();
    for name in ('decision.json', 'snapshot.json', 'gate-run.log'):
        if (gate_out / name).exists(): shutil.copy2(gate_out / name, pkg / 'gate' / name)
    for name in ('build.json', 'decision.json', 'kitguard.json', 'install.json', 'document-selfcheck.json'):
        if (gate_out / 'gate' / name).exists(): shutil.copy2(gate_out / 'gate' / name, pkg / 'gate' / ('gate-' + name))
    shutil.copytree(gate_out / 'gate' / 'receipts', pkg / 'gate' / 'receipts')
    if (gate_out / 'gate' / 'runs').exists(): shutil.copytree(gate_out / 'gate' / 'runs', pkg / 'gate' / 'runs')
    (pkg / 'docs').mkdir()
    for src in (audit_path.with_name('AUDIT-92.md'), audit_path):
        if src.exists(): shutil.copy2(src, pkg / 'docs' / src.name)
    for rel in ('docs/wf/FEATURE-SCOPE.md', 'docs/wf/TAKEOVER-CLAUDE-2026-10-24.md',
                'docs/wf/DEV-LOG.md', 'docs/wf/R00-DONE.md', 'wfkit/development-testcases.json', 'wfkit/development-manifest.json'):
        if (R / rel).exists(): shutil.copy2(R / rel, pkg / 'docs' / Path(rel).name)
    shutil.copytree(R / 'docs' / 'wf' / 'release-notes', pkg / 'docs' / 'release-notes')
    bundles = {}
    if a.bundles:
        (pkg / 'bundles').mkdir()
        for rel, path in index.items():
            src = Path(path).parent
            dst = pkg / 'bundles' / rel; dst.mkdir()
            for name in ('bundle.json', 'release-check.json', 'receipt.json', 'bundle-result.json'):
                if (src / name).exists(): shutil.copy2(src / name, dst / name)
            if (src / 'receipts').exists(): shutil.copytree(src / 'receipts', dst / 'receipts')
            v = bundle_results[rel]
            produced = v.get('produced') is not False
            bundles[rel] = {'decision': v['decision'], 'produced': produced, 'conditions': v.get('conditions'), 'reasons': v.get('reasons'), 'reason': v.get('reason'),
                            'commit': v.get('commit'), 'wheel_sha256': v.get('wheel_sha256'),
                            'first_release': v.get('first_release') is True, 'first_release_baseline': v.get('first_release_baseline'),
                            'inputs_rule': inputs_summary(v)['code'] if produced else None}
    matrix = None
    if a.matrix:
        src = Path(a.matrix); shutil.copytree(src, pkg / 'provider-matrix', ignore=shutil.ignore_patterns('cells'))
        m = json.load(open(src / 'matrix.json', encoding='utf-8'))
        matrix = {'usable': m['usable'], 'p1': m['p1'], 'rows': {r['id']: r['status'] for r in m['rows']}, 'at': m['at']}
    verifier = verify_kit.build_verify_dir(pkg)   # the verification tool + its dependencies, hash-pinned in manifest.json and SHA256SUMS
    audit = _read(audit_path)
    checks = decision.get('implementation_checks', {})
    manifest = {'schema': 1, 'kind': kind, 'built_at': snapshot.get('prepared_at'), 'commit': commit, 'version': version,
                'wheel': {'file': 'wheel/' + wheel_src.name, 'sha256': wheel_sha}, 'previous_wheel': previous,
                'gate': {'decision': decision.get('decision'), 'release_delivery': decision.get('release_delivery'), 'owner_acceptance': decision.get('owner_acceptance'),
                         'implementation_checks': checks, 'snapshot_intact': decision.get('snapshot', {}).get('intact'),
                         'problem_kinds': sorted({p.get('kind') for p in decision.get('problems', [])})},
                'verifier': verifier, 'bundles': bundles, 'provider_matrix': matrix, 'tasks_92': audit['counts'], 'tasks_92_commit': audit['commit'],
                'claims': {'delivered': False, 'codex_reviewed': False, 'owner_accepted': False}}
    (pkg / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8')
    mixed = package_check.package_scope(pkg)['reasons']          # the shipped identity step, run on what was just built
    if mixed: sys.exit('the built package fails its own identity step (left for inspection at ' + str(pkg) + '):\n  ' + '\n  '.join(mixed))
    counts = audit['counts']
    produced_results = {rel: bundle_results[rel] for rel in bundles if bundles[rel]['produced']}
    bundle_rows = '\n'.join(f"| {rel} | {b['decision']} | {'có' if b['produced'] else 'KHÔNG (bị từ chối/chặn, không có bundle)'} | "
                            + (', '.join(f'{k}={v}' for k, v in (b['conditions'] or {}).items()) or '—') + ' | '
                            + ('; '.join(str(r.get('detail', r)) if isinstance(r, dict) else str(r) for r in (b['reasons'] or [])) or (b['reason'] or '—')).replace('\n', ' ') + ' |'
                            for rel, b in bundles.items())
    kind_text = ('Gói phát hành ĐẦU TIÊN: không có wheel bản trước, chỉ chạy các bước kiểm cơ bản (không diễn tập rollback); '
                 '`legacy_continuation.py` KHÔNG áp dụng và thoát mã 5 (not-applicable — không phải pass).' if kind == 'first-release-handover-package' else
                 'Gói có wheel bản trước được ghim (`manifest.json` → `previous_wheel`, sha256): diễn tập rollback/roll-forward là BẮT BUỘC; '
                 'thiếu wheel bản trước hoặc sha256 lệch là bị từ chối.')
    readme = f"""# Gói bàn giao development — OneCrew workflow chung — commit `{commit[:12]}`

**Đây là gói development: chưa giao, chưa Codex review, chưa nghiệm thu.** Mọi số liệu lấy từ biên nhận trong gói.

| Mục | Giá trị |
|---|---|
| Commit | `{commit}` |
| Wheel | `{manifest['wheel']['file']}` — sha256 `{wheel_sha}` |
| Phiên bản | {version} |
| Gate development (snapshot) | **{decision.get('decision')}** — kiểm hiện thực: {checks.get('receipted', '?')}/{checks.get('expected', '?')} biên nhận, {len(checks.get('failed', []))} hỏng; snapshot nguyên vẹn: {decision.get('snapshot', {}).get('intact')} |
| 92 task | Done {counts.get('Done')} · Partial {counts.get('Partial')} · Blocked {counts.get('Blocked')} (commit `{audit['commit']}`; docs/AUDIT-92.md) |
| Bundle T54 | {len(bundles)} release, {len(produced_results)} có bundle (bundles/<R>/release-check.json) — {inputs_sentence(produced_results)} |
| Ma trận provider (W45) | {('dùng được ' + str(matrix['p1']['count']) + '/6, P1.0 ' + matrix['p1']['label'] + ' — provider-matrix/matrix.md') if matrix else 'chưa chạy'} |

## Bundle T54 từng release (kể cả bị từ chối)

| Release | Quyết định | Có bundle | Điều kiện | Lý do |
|---|---|---|---|---|
{bundle_rows}

Release bị từ chối/chặn vẫn nằm trong gói (`bundles/<R>/bundle-result.json`): thiếu bằng chứng không bị giấu.

## Cài vào venv sạch, NGOÀI checkout

```bash
python -m venv D:/OneCrewRuns/venv-wf-{commit[:7]}
D:/OneCrewRuns/venv-wf-{commit[:7]}/Scripts/python -m pip install --no-index --no-build-isolation "{manifest['wheel']['file']}"
D:/OneCrewRuns/venv-wf-{commit[:7]}/Scripts/onecrew --help
```

Kiểm hash trước khi cài: `sha256sum {manifest['wheel']['file']}` phải bằng dòng tương ứng trong `SHA256SUMS`.

## Smoke test (dữ liệu giả, không chạm sổ thật)

```bash
python verify/verify_package.py <thư mục gói này> <thư mục làm việc MỚI, ngoài gói>
python verify/legacy_continuation.py <thư mục gói này> <thư mục làm việc MỚI khác>
```

Chỉ cần Python 3.11+ của hệ thống và chính gói này: không cần checkout, không cần PYTHONPATH, chạy từ thư mục nào cũng được (kể cả thư mục mới
trống); đường dẫn có dấu cách được hỗ trợ (đặt trong ngoặc kép). Mỗi launcher TỰ KIỂM trước: băm các file trong `verify/` và so với `manifest.json`
(`verifier.files`) và `SHA256SUMS` — thiếu/sửa một file là dừng với mã thoát khác 0 và nêu rõ file nào, chưa tạo venv. Thêm `--self-check-only`
(không cần thư mục làm việc) để chỉ chạy bước tự kiểm. Sau khi chạy, `verification/verifier-origin.json` ghi đường dẫn + sha256 của từng module đã nạp
(phải nằm trong `verify/` của gói; module `wfkit`/`package_check` ngoài gói bị từ chối).

`verify_package.py` tạo venv ngoài checkout, cài wheel từ gói, kiểm hash, chạy một root code (propose → approve → `verdict run`) bằng lệnh `onecrew` của venv trên project
git tạm + sổ tạm, kiểm mọi module `onecrew.*` nạp từ venv (không từ checkout), rồi diễn tập rollback/roll-forward trên BẢN SAO sổ nếu gói có wheel bản trước.
Kết quả ghi `verification/verify-report.json` trong thư mục làm việc.

**Loại gói (`manifest.json` → `kind`): `{kind}`.** {kind_text}
Phạm vi kiểm (bước nào bắt buộc) do `manifest.json` + file trong gói quyết định, không do báo cáo: verifier TỪ CHỐI báo cáo có phạm vi hoặc danh tính
(đường dẫn gói, loại gói, sha256 của manifest / wheel / wheel bản trước, hash file verifier) không khớp `manifest.json`.

Lưu ý Windows (đã gặp thực tế, chưa sửa): chọn thư mục làm việc có đường dẫn NGẮN (vd. `D:/OneCrewRuns/<tên ngắn>`). Đường dẫn ref bằng chứng
`.git/refs/onecrew/evidence/<64 ký tự>/<40 ký tự>` trong project tạm có thể vượt MAX_PATH (260 ký tự) và bước smoke hỏng với `cannot lock ref`.

## Quay lại bản trước

1. Chạy `onecrew --project P --state-root S compat scan --json` trên BẢN SAO sổ; chỉ quay lại khi `blocking.total == 0`.
2. `python -m pip uninstall --yes onecrew` rồi cài wheel bản trước (`{previous['file'] if previous else 'không kèm trong gói — lấy từ bản giao trước'}`).
3. Roll-forward: cài lại wheel này; intent chưa rõ được reconcile trước khi root tiếp tục (`verdict status` → `held`, `verdict release-run`).
Diễn tập đầy đủ trên fixture sinh (CHỈ khi có checkout tại commit `{commit[:12]}`; KHÔNG nằm trong gói): `python -m wfkit.upgrade_drill --out <thư mục mới dưới TEMP>`.

## Trong gói

- `gate/` — decision.json, snapshot.json, kitguard.json, build.json, biên nhận từng check (`receipts/`), log chạy (`runs/`).
- `bundles/<R>/` — bundle T54 từng release: bundle.json, receipts/, release-check.json (kết quả từng điều T54.1–T54.5 và INPUTS hoặc INPUTS(bootstrap)).
- `docs/` — AUDIT-92.md (bảng 92 task), FEATURE-SCOPE.md, release-notes/, TAKEOVER-CLAUDE-2026-10-24.md, registry + manifest đã đóng băng.
- `verify/` — công cụ kiểm kèm phụ thuộc (package_check.py, legacy_core.py, 2 launcher), hash ghim trong `manifest.json` → `verifier` (commit nguồn `{verifier['source_commit']}`).
- `manifest.json`, `SHA256SUMS`.
"""
    (pkg / 'README.md').write_text(readme, encoding='utf-8', newline='\n')
    nlines = verify_kit.write_sums(pkg)
    print(json.dumps({'package': str(pkg), 'files': nlines, 'wheel_sha256': wheel_sha, 'commit': commit, 'gate': decision.get('decision')}))


if __name__ == '__main__':
    main()
