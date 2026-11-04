# Release notes per release (W40-Rnn, T54 notes criterion: the five sections of wfkit/release_check.SECTIONS), generated from the frozen
# sources (04) and the development registry. Usage: gen_release_notes.py [gate] [commit] [fixture] [bundles-index.json] [out dir]. Status words come from the registry only; nothing here claims a delivery, a provider run or a pilot.
import json, os, re, sys
R = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..'))   # the checkout this file lives in
cfg = json.load(open(os.path.join(R, 'wfkit', 'development-testcases.json'), encoding='utf-8'))
t04 = open(os.path.join(R, 'docs', 'wf', 'sources', '04-TASKS.vi.md'), encoding='utf-8').read()
gate = sys.argv[1] if len(sys.argv) > 1 else 'chưa có'
commit = sys.argv[2] if len(sys.argv) > 2 else 'HEAD'
fixture = sys.argv[3] if len(sys.argv) > 3 else 'pending'   # 'passed' only from a gate receipt where every implementation check passed
bundles = json.load(open(sys.argv[4], encoding='utf-8')) if len(sys.argv) > 4 else {}   # release -> path of release-check.json (wfkit.release_bundle)
out_override = sys.argv[5] if len(sys.argv) > 5 else None   # optional output dir (default docs/wf/release-notes of this checkout)
sys.path.insert(0, R)
from wfkit.release_check import inputs_summary  # noqa: E402


def bundle_lines(rel):
    """The T54 bundle of this release, point by point, from the producer's release-check.json (real local observations); the INPUTS blocker
    (no delivered previous build) is named as the external condition it is."""
    path = bundles.get(rel)
    if not path:
        return [f'- Bundle T54 (`python -m wfkit.release_bundle {rel} --out <thư mục mới>` rồi `python -m wfkit.release_check bundle.json`): chưa chạy cho bản này.']
    v = json.load(open(path, encoding='utf-8'))
    cond = v.get('conditions', {})
    words = {True: 'đạt (biên nhận thật)', False: 'không đạt'}
    names = {'INPUTS': 'INPUTS — lịch sử cổng giao của bản trước', 'INPUTS(bootstrap)': 'INPUTS(bootstrap) — bản giao đầu tiên, baseline compat ghim', 'T54.1': 'T54.1 — kịch bản chạy từ bản cài', 'T54.2': 'T54.2 — nâng cấp giữ ID/ngân sách/evidence/attempt',
             'T54.3': 'T54.3 — lớp sự kiện, S/G/C bản cũ', 'T54.4': 'T54.4 — rollback từ chối/cho phép, roll-forward', 'T54.5': 'T54.5 — ghi chú bốn trạng thái'}
    out = [f'- Bundle T54 thật (`wfkit.release_bundle`, kết quả `release_check`: **{v.get("decision")}**; bundle `{v.get("bundle", "")}`):']
    inputs = inputs_summary(v)
    for key in (inputs['code'], 'T54.1', 'T54.2', 'T54.3', 'T54.4', 'T54.5'):
        reason = next((r['detail'] for r in v.get('reasons', []) if r['code'] == key), '')
        out.append(f'  - {names[key]}: {words.get(cond.get(key), "chưa có")}' + (f' — {reason}' if reason else ''))
    out.append(f"  - Quy tắc INPUTS đã áp dụng: `{inputs['code']}`; first_release: {str(inputs['first_release']).lower()}.")
    if inputs['first_release']:
        out.append(f"  - Bản giao đầu tiên: bản trước là baseline {inputs['baseline_commit'][:7]} ghim (wheel sha256 `{inputs['baseline_wheel_sha256']}`), baseline mà `compat scan` "
                   'mô hình và các diễn tập đã cài — KHÔNG phải bản đã giao, chưa nghiệm thu; INPUTS(bootstrap) không phải lịch sử cổng giao.')
    else:
        out.append('  - Bản trước trong bundle là d3120c6 (baseline mà `compat scan` mô hình), KHÔNG phải bản đã giao: chưa có release nào của chương trình được giao, '
                   'nên điều kiện INPUTS chỉ có thể đạt sau khi chủ sở hữu giao một release (điều kiện ngoài).')
    return out
rows = []
for l in t04.split('## Ánh xạ 62 ID task cũ')[0].split('\n'):
    m = re.match(r'^\| ([A-Z][A-Za-z0-9-]*?)(\s*\(S\))? \| ', l)
    if m and not l.startswith('| ID ') and not l.startswith('| Release '):
        c = [x.strip() for x in l.strip().strip('|').split('|')]
        if len(c) >= 9: rows.append(c)
def short(s, n=140):
    s = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', s).replace('**', '').replace('`', '')
    return s if len(s) <= n else s[:n].rsplit(' ', 1)[0] + ' …'
PREV = {'R01': 'R00', 'R02': 'R01', 'R03': 'R02', 'R04': 'R03', 'R05': 'R04', 'R06': 'R05', 'R07': 'R06', 'R08': 'R07', 'RP': 'R00 (song song M1)', 'RX1': 'R00 (song song M1)', 'RX2': 'R04'}
out_dir = out_override or os.path.join(R, 'docs', 'wf', 'release-notes'); os.makedirs(out_dir, exist_ok=True)
index = ['# Release notes (development) — chương trình workflow chung', '',
         f'Sinh từ `docs/wf/sources/04-TASKS.vi.md` và `wfkit/development-testcases.json` tại commit `{commit}`; biên nhận gate development: {gate}. '
         'Mỗi file có đúng năm mục của T54 (`wfkit/release_check.SECTIONS`). **Không file nào là bằng chứng giao release**: bundle T54 cần bản giao trước đó thật, '
         'kịch bản đầu-cuối theo release, artifact đóng băng và lịch sử biên nhận đã giao (xem "Evidence status" từng file).', '', '| Release | Task | complete | partial | blocked |', '|---|---|---|---|---|']
for rel, body in cfg['releases'].items():
    if rel in ('KN', 'PL'): continue
    acc = body['acceptance']
    counts = {s: sum(1 for c in acc.values() if c['status'] == s) for s in ('complete', 'partial', 'blocked')}
    tasks = [c for c in rows if c[1] == rel and not c[0].startswith('W40') and not c[0].startswith('WK')]
    pack = next((c for c in rows if c[1] == rel and c[0].startswith('W40')), None)
    lines = [f'# {rel} — release notes (development, chưa giao)', '',
             f'Commit: `{commit}`. Bản giao trước gần nhất theo chương trình: {PREV.get(rel, "—")} — **chưa có bản giao thật nào được ghi nhận** (release_check không suy ra từ d3120c6).', '',
             '## Usable outcomes', '',
             'Những gì bản dựng này làm được, theo task của release (rút gọn từ 04; trạng thái lấy từ registry):', '']
    for c in tasks:
        tcs = re.findall(r'T\d\d[a-z]?', c[8])
        st = ', '.join(f'{tc} {acc[tc]["status"]}' if tc in acc else f'{tc} —' for tc in tcs) or '—'
        lines.append(f'- **{c[0]}** — {short(c[3])} _(testcase: {st})_')
    lines += ['', '## Limits', '',
              '- Trạng thái `partial` = có kiểm hồi quy nhưng ma trận acceptance đầy đủ của testcase chưa được chứng nhận riêng; `blocked` = cần provider thật, pilot hay chủ sở hữu.',
              '- Mọi test tự động dùng CLI giả; development không gọi provider trả phí. Ma trận provider thật W45 đã chạy MỘT lần trên wheel `6366137` (claude 2/2 và kiro 2/2 ô đạt, codex 0/2 vì CLI không có → subset 4/6; chỉ chứng minh ô chạy được, không phải chất lượng review). Đó KHÔNG phải wheel của bản dựng này: chưa có ma trận hay so sánh cho wheel hiện hành, lệnh thật của codex CHƯA KIỂM CHỨNG (W45/T40b).',
              '- Không hứa exactly-once cho tác động ngoài; không hoàn tác tác động ngoài đã xảy ra (HD-26).',
              '- Chưa có nghiệm thu của chủ sở hữu; không có pilot thật (PL-A/PL-B).']
    if rel == 'RP': lines.append('- Sáu ô provider × vai trò: 4/6 đã chạy CLI thật trên wheel `6366137` (không phải wheel này), 2 ô codex chưa; so sánh ma trận với wheel hiện hành chưa có nên bundle RP của bản này ghi T54.5 "comparison missing" (cần kiểm lại), provider_bundle thật PV1/PV2 chưa có.')
    lines += ['', '## Install', '',
              '- Wheel một lần từ commit sạch: `python -m build` (gate development dựng và ghi sha256 trong `build.json`); cài vào venv offline; `onecrew --version`/`control` từ checkout bị từ chối (kiểm bản cài của gate).',
              '- Kiểm bản cài: các check `installed: true` của registry tiêu thụ đúng wheel đó (`wheel_used`).',
              '- Hook OneCrew cho Claude Code: `onecrew hook install` theo docs; không bật heartbeat chat.', '',
              '## Rollback', '',
              f'- Trước khi rollback về {PREV.get(rel, "bản trước")}: chạy `onecrew compat scan` (W46) trên bản sao sổ; chỉ rollback khi 0 điều kiện chặn (B1–B4); sự kiện lớp A của release này bị bản cũ bỏ qua im lặng, sự kiện lớp B chỉ nằm trên root `plan-ns:` mà bản cũ không thấy.',
              '- Diễn tập: `python -m wfkit.upgrade_drill` (sinh fixture bản cài, không dùng sổ thật). Rollback không tua lùi sổ (không xoá/sửa sự kiện).',
              '- Roll-forward: reconcile intent chưa rõ (`verdict status` → `held`, `verdict release-run` là quyết định ghi lại) trước khi root tiếp tục.', '',
              '## Evidence status', '',
              f'- Registry {rel}: complete {counts["complete"]}, partial {counts["partial"]}, blocked {counts["blocked"]} (`python -m wfkit.development_gate list`).',
              f'- Gate development trên một wheel: {gate}.',
              *bundle_lines(rel),
              '- Không ghi "đã giao", "Codex đã review" hay "chủ sở hữu đã nghiệm thu".', '',
              'Bốn trạng thái bằng chứng (định dạng của `release_check` T54.5, mỗi dòng một trạng thái):', '',
              'Code: present', f'Fixture checks: {fixture}', 'Real checks: not-run', 'Acceptance: not-requested', '']
    open(os.path.join(out_dir, f'{rel}.md'), 'w', encoding='utf-8', newline='\n').write('\n'.join(lines))
    index.append(f'| {rel} | {pack[0] if pack else "—"} | {counts["complete"]} | {counts["partial"]} | {counts["blocked"]} |')
open(os.path.join(out_dir, 'README.md'), 'w', encoding='utf-8', newline='\n').write('\n'.join(index) + '\n')
print('written', len(os.listdir(out_dir)))
