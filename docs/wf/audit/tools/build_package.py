# The development handover package (directive I, 24/10): one folder with the wheel + sha256, the commit/snapshot identity, the gate decision and
# receipts, the T54 bundles' verdicts, the 92-task table, release notes, and a README that says how to install into a clean venv OUTSIDE the
# checkout, smoke-test, and roll back. Nothing here claims delivery, Codex review or owner acceptance.
#   python docs/wf/audit/tools/build_package.py <snapshot-gate out dir> <package dir (new)> [--bundles bundles.json] [--previous-wheel path]
import argparse, hashlib, json, os, shutil, sys
from pathlib import Path

R = Path(os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..')))


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument('gate_out'); ap.add_argument('package'); ap.add_argument('--bundles'); ap.add_argument('--previous-wheel'); ap.add_argument('--matrix', help='W45 provider matrix dir (matrix.json/matrix.md/receipts)')
    a = ap.parse_args(argv)
    gate_out, pkg = Path(a.gate_out), Path(a.package)
    if pkg.exists(): sys.exit('package dir must be new: ' + str(pkg))
    build = json.load(open(gate_out / 'gate' / 'build.json', encoding='utf-8'))
    decision = json.load(open(gate_out / 'decision.json', encoding='utf-8'))
    snapshot = json.load(open(gate_out / 'snapshot.json', encoding='utf-8'))
    commit, wheel_sha, version = build['commit'], build['wheel_sha256'], build['version']
    wheel_src = Path(build['wheel'])
    if sha(wheel_src) != wheel_sha: sys.exit('wheel bytes do not match build.json')
    (pkg / 'wheel').mkdir(parents=True); shutil.copy2(wheel_src, pkg / 'wheel' / wheel_src.name)
    previous = None
    if a.previous_wheel:
        p = Path(a.previous_wheel); (pkg / 'wheel' / 'previous').mkdir(); shutil.copy2(p, pkg / 'wheel' / 'previous' / p.name); previous = {'file': 'wheel/previous/' + p.name, 'sha256': sha(p), 'commit': 'd3120c6 (baseline the compat scanner models; NOT a delivered build)'}
    (pkg / 'gate').mkdir();
    for name in ('decision.json', 'snapshot.json', 'gate-run.log'):
        if (gate_out / name).exists(): shutil.copy2(gate_out / name, pkg / 'gate' / name)
    for name in ('build.json', 'decision.json', 'kitguard.json', 'install.json', 'document-selfcheck.json'):
        if (gate_out / 'gate' / name).exists(): shutil.copy2(gate_out / 'gate' / name, pkg / 'gate' / ('gate-' + name))
    shutil.copytree(gate_out / 'gate' / 'receipts', pkg / 'gate' / 'receipts')
    if (gate_out / 'gate' / 'runs').exists(): shutil.copytree(gate_out / 'gate' / 'runs', pkg / 'gate' / 'runs')
    (pkg / 'docs').mkdir()
    for rel in ('docs/wf/audit/AUDIT-92.md', 'docs/wf/audit/audit-92.json', 'docs/wf/FEATURE-SCOPE.md', 'docs/wf/TAKEOVER-CLAUDE-2026-10-24.md',
                'docs/wf/DEV-LOG.md', 'docs/wf/R00-DONE.md', 'wfkit/development-testcases.json', 'wfkit/development-manifest.json'):
        if (R / rel).exists(): shutil.copy2(R / rel, pkg / 'docs' / Path(rel).name)
    shutil.copytree(R / 'docs' / 'wf' / 'release-notes', pkg / 'docs' / 'release-notes')
    bundles = {}
    if a.bundles:
        index = json.load(open(a.bundles, encoding='utf-8'))
        (pkg / 'bundles').mkdir()
        for rel, path in index.items():
            src = Path(path).parent
            dst = pkg / 'bundles' / rel; dst.mkdir()
            for name in ('bundle.json', 'release-check.json', 'receipt.json'):
                if (src / name).exists(): shutil.copy2(src / name, dst / name)
            if (src / 'receipts').exists(): shutil.copytree(src / 'receipts', dst / 'receipts')
            v = json.load(open(src / 'release-check.json', encoding='utf-8'))
            bundles[rel] = {'decision': v['decision'], 'conditions': v['conditions'], 'reasons': v['reasons']}
    matrix = None
    if a.matrix:
        src = Path(a.matrix); shutil.copytree(src, pkg / 'provider-matrix', ignore=shutil.ignore_patterns('cells'))
        m = json.load(open(src / 'matrix.json', encoding='utf-8'))
        matrix = {'usable': m['usable'], 'p1': m['p1'], 'rows': {r['id']: r['status'] for r in m['rows']}, 'at': m['at']}
    audit = json.load(open(R / 'docs' / 'wf' / 'audit' / 'audit-92.json', encoding='utf-8'))
    checks = decision.get('implementation_checks', {})
    manifest = {'schema': 1, 'kind': 'development-handover-package', 'built_at': snapshot.get('prepared_at'), 'commit': commit, 'version': version,
                'wheel': {'file': 'wheel/' + wheel_src.name, 'sha256': wheel_sha}, 'previous_wheel': previous,
                'gate': {'decision': decision.get('decision'), 'release_delivery': decision.get('release_delivery'), 'owner_acceptance': decision.get('owner_acceptance'),
                         'implementation_checks': checks, 'snapshot_intact': decision.get('snapshot', {}).get('intact'),
                         'problem_kinds': sorted({p.get('kind') for p in decision.get('problems', [])})},
                'bundles': bundles, 'provider_matrix': matrix, 'tasks_92': audit['counts'], 'tasks_92_commit': audit['commit'],
                'claims': {'delivered': False, 'codex_reviewed': False, 'owner_accepted': False}}
    (pkg / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8')
    counts = audit['counts']
    readme = f"""# Gói bàn giao development — OneCrew workflow chung — commit `{commit[:12]}`

**Đây là gói development: chưa giao, chưa Codex review, chưa nghiệm thu.** Mọi số liệu lấy từ biên nhận trong gói.

| Mục | Giá trị |
|---|---|
| Commit | `{commit}` |
| Wheel | `{manifest['wheel']['file']}` — sha256 `{wheel_sha}` |
| Phiên bản | {version} |
| Gate development (snapshot) | **{decision.get('decision')}** — kiểm hiện thực: {checks.get('receipted', '?')}/{checks.get('expected', '?')} biên nhận, {len(checks.get('failed', []))} hỏng; snapshot nguyên vẹn: {decision.get('snapshot', {}).get('intact')} |
| 92 task | Done {counts.get('Done')} · Partial {counts.get('Partial')} · Blocked {counts.get('Blocked')} (docs/AUDIT-92.md) |
| Bundle T54 | {len(bundles)} release (bundles/<R>/release-check.json) — INPUTS luôn không đạt vì chưa có release nào được giao (điều kiện ngoài) |
| Ma trận provider (W45) | {('dùng được ' + str(matrix['p1']['count']) + '/6, P1.0 ' + matrix['p1']['label'] + ' — provider-matrix/matrix.md') if matrix else 'chưa chạy'} |

## Cài vào venv sạch, NGOÀI checkout

```bash
python -m venv D:/OneCrewRuns/venv-wf-{commit[:7]}
D:/OneCrewRuns/venv-wf-{commit[:7]}/Scripts/python -m pip install --no-index --no-build-isolation "{manifest['wheel']['file']}"
D:/OneCrewRuns/venv-wf-{commit[:7]}/Scripts/onecrew --help
```

Kiểm hash trước khi cài: `sha256sum {manifest['wheel']['file']}` phải bằng dòng tương ứng trong `SHA256SUMS`.

## Smoke test (dữ liệu giả, không chạm sổ thật)

```bash
python docs/wf/audit/tools/verify_package.py <thư mục gói này> D:/OneCrewRuns/wf-verify-{commit[:7]}
```

Script tạo venv ngoài checkout, cài wheel từ gói, kiểm hash, chạy một root code (propose → approve → `verdict run`) bằng lệnh `onecrew` của venv trên project
git tạm + sổ tạm, kiểm mọi module `onecrew.*` nạp từ venv (không từ checkout), rồi diễn tập rollback/roll-forward trên BẢN SAO sổ nếu gói có wheel bản trước.
Kết quả ghi `verification/verify-report.json` trong thư mục làm việc.

## Quay lại bản trước

1. Chạy `onecrew --project P --state-root S compat scan --json` trên BẢN SAO sổ; chỉ quay lại khi `blocking.total == 0`.
2. `python -m pip uninstall --yes onecrew` rồi cài wheel bản trước (`{previous['file'] if previous else 'không kèm trong gói — lấy từ bản giao trước'}`).
3. Roll-forward: cài lại wheel này; intent chưa rõ được reconcile trước khi root tiếp tục (`verdict status` → `held`, `verdict release-run`).
Diễn tập đầy đủ trên fixture sinh: `python -m wfkit.upgrade_drill --out <thư mục mới dưới TEMP>` (cần checkout tại commit trên).

## Trong gói

- `gate/` — decision.json, snapshot.json, kitguard.json, build.json, biên nhận từng check (`receipts/`), log chạy (`runs/`).
- `bundles/<R>/` — bundle T54 từng release: bundle.json, receipts/, release-check.json (kết quả từng điều T54.1–T54.5 và INPUTS).
- `docs/` — AUDIT-92.md (bảng 92 task), FEATURE-SCOPE.md, release-notes/, TAKEOVER-CLAUDE-2026-10-24.md, registry + manifest đã đóng băng.
- `manifest.json`, `SHA256SUMS`.
"""
    (pkg / 'README.md').write_text(readme, encoding='utf-8', newline='\n')
    lines = []
    for p in sorted(x for x in pkg.rglob('*') if x.is_file() and x.name != 'SHA256SUMS'):
        lines.append(f'{sha(p)}  {p.relative_to(pkg).as_posix()}')
    (pkg / 'SHA256SUMS').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({'package': str(pkg), 'files': len(lines), 'wheel_sha256': wheel_sha, 'commit': commit, 'gate': decision.get('decision')}))


if __name__ == '__main__':
    main()
