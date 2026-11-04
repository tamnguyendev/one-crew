# Merge the audit fills into one 92-task table (docs/wf/audit/AUDIT-92.md + audit-92.json). Overrides (my own re-judgement) win over agent fills.
import json, os, glob, sys
from collections import Counter
R = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..'))   # the checkout this file lives in
A = os.path.join(R, 'docs', 'wf', 'audit')
base = json.load(open(os.path.join(A, 'tasks-92.json'), encoding='utf-8'))
fills = {}
for f in sorted(glob.glob(os.path.join(A, 'fill-g*.json'))):
    fills.update(json.load(open(f, encoding='utf-8')))
over = json.load(open(os.path.join(A, 'overrides.json'), encoding='utf-8')) if os.path.exists(os.path.join(A, 'overrides.json')) else {}
def category(t):
    tid = t['id']
    if tid.startswith('WK'): return 'bộ kiểm'
    if tid.startswith('W40-'): return 'phát hành'
    if tid in ('W45', 'W40-RP'): return 'provider thật'
    if tid in ('W38b', 'W38c', 'W38d'): return 'pilot/nghiệm thu'
    return 'feature'
rows, missing = [], []
for t in base['tasks']:
    tid = t['id']; fill = dict(fills.get(tid) or {}); fill.update(over.get(tid) or {})
    if not fill.get('status'): missing.append(tid)
    rows.append({'id': tid, 'release': t['release'], 'category': category(t), 'testcases': t['testcases'], 'outcome': t['outcome'][:160],
                 'status': fill.get('status', '?'), 'classes': fill.get('classes', []), 'implementation': fill.get('implementation', []),
                 'tests': fill.get('tests', []), 'missing': fill.get('missing', ''), 'next': fill.get('next', ''), 'evidence': fill.get('evidence', [])})
counts = Counter(r['status'] for r in rows)
by_cat = {c: Counter(r['status'] for r in rows if r['category'] == c) for c in ('feature', 'bộ kiểm', 'phát hành', 'provider thật', 'pilot/nghiệm thu')}
head = sys.argv[1] if len(sys.argv) > 1 else 'HEAD'
gate_dir = sys.argv[2] if len(sys.argv) > 2 else None          # snapshot-gate out dir (decision.json) for the "five levels" block
package = sys.argv[3] if len(sys.argv) > 3 else None           # handover package path, if built
reg = json.load(open(os.path.join(R, 'wfkit', 'development-testcases.json'), encoding='utf-8'))
acc = Counter(c['status'] for rel in reg['releases'].values() for c in rel.get('acceptance', {}).values())
gate_line = 'chưa chạy'
if gate_dir and os.path.exists(os.path.join(gate_dir, 'decision.json')):
    g = json.load(open(os.path.join(gate_dir, 'decision.json'), encoding='utf-8')); ic = g.get('implementation_checks', {})
    gate_line = f"`{g.get('decision')}` — check implementation có biên nhận {ic.get('receipted')}/{ic.get('expected')}, hỏng {len(ic.get('failed', []))}; vấn đề: {dict(Counter(p['kind'] for p in g.get('problems', [])))} (gate `refused` vì acceptance partial/blocked là đúng thiết kế, không phải lỗi mã)"
levels = ['## Năm mức riêng, mức dưới không suy ra mức trên', '',
          f'1. **Task Done (DoD của task)**: {counts.get("Done", 0)}/{len(rows)}.',
          f'2. **Acceptance `complete` trong registry (ma trận [E] đủ)**: {acc.get("complete", 0)}/{sum(acc.values())} testcase (partial {acc.get("partial", 0)}, blocked {acc.get("blocked", 0)}).',
          f'3. **Gate snapshot**: {gate_line}.',
          f'4. **Bản test đã đóng gói**: {("`" + package + "` (kiểm từ artifact, xem verification/)") if package else "chưa dựng cho commit này"}.',
          '5. **Owner acceptance / release đã giao / Codex đã review bản này**: 0 — chưa xảy ra.', '']
out = ['# Bảng đối chiếu 92 task — development chương trình workflow chung', '',
       f'Commit kiểm: `{head}`. Nguồn task: `docs/wf/sources/04-TASKS.vi.md` (sha256 {base["source_04_sha256_12"]}); acceptance: `05-TESTCASES.vi.md`. '
       f'Trạng thái: **Done** = đủ hành vi theo DoD của task, nối vào đường dùng, mọi [E] của phần DoD có test đạt trên commit kiểm; **Partial** = thiếu gì ghi ở cột "Thiếu"; '
       f'**Blocked** = cần provider thật / pilot / điều kiện ngoài. Loại nguyên nhân: A thiếu code, B chưa nối đường dùng, C thiếu test/bằng chứng, D chỉ chưa cập nhật trạng thái, E điều kiện ngoài.', '',
       f'**Tổng: {len(rows)} task — Done {counts.get("Done", 0)}, Partial {counts.get("Partial", 0)}, Blocked {counts.get("Blocked", 0)}'
       + (f', chưa chấm {counts.get("?", 0)}' if counts.get('?') else '') + '.**', '',
       *levels, '| Nhóm | Done | Partial | Blocked |', '|---|---|---|---|']
for c, cnt in by_cat.items():
    out.append(f'| {c} | {cnt.get("Done", 0)} | {cnt.get("Partial", 0)} | {cnt.get("Blocked", 0)} |')
out += ['', '| ID | Release | Testcase (vai trò) | Trạng thái | Loại | Implementation (file:line) | Test / bằng chứng | Thiếu | Việc tiếp |', '|---|---|---|---|---|---|---|---|---|']
def cell(v, n=3):
    if isinstance(v, list): v = '<br>'.join(str(x) for x in v[:n]) + ('<br>…' if len(v) > n else '')
    return str(v).replace('|', '\\|').replace('\n', ' ')
for r in rows:
    tcs = ', '.join(f'{k} ({v})' if v != 'DoD' else k for k, v in r['testcases'].items()) or '—'
    out.append(f"| {r['id']} | {r['release']} | {tcs} | {r['status']} | {','.join(r['classes']) or '—'} | {cell(r['implementation'])} | {cell(r['tests'])} | {cell(r['missing'])} | {cell(r['next'])} |")
open(os.path.join(A, 'AUDIT-92.md'), 'w', encoding='utf-8', newline='\n').write('\n'.join(out) + '\n')
json.dump({'commit': head, 'counts': counts, 'by_category': {k: dict(v) for k, v in by_cat.items()}, 'rows': rows},
          open(os.path.join(A, 'audit-92.json'), 'w', encoding='utf-8', newline='\n'), ensure_ascii=False, indent=1)
print(dict(counts), {k: dict(v) for k, v in by_cat.items()}, 'missing fills:', missing)
