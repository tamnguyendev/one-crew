# FEATURE-SCOPE.md regenerated from the frozen sources (04/05 copies) and the development registry. One source of truth for
# status: the registry's acceptance_snapshot; this file only joins task -> testcase -> checks -> status -> gap.
import json, re, hashlib, os, sys
R = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..'))   # the checkout this file lives in
cfg = json.load(open(os.path.join(R, 'wfkit', 'development-testcases.json'), encoding='utf-8'))
t04 = open(os.path.join(R, 'docs', 'wf', 'sources', '04-TASKS.vi.md'), encoding='utf-8').read()
h04 = hashlib.sha256(t04.encode('utf-8')).hexdigest()[:12]
extra = sys.argv[1] if len(sys.argv) > 1 else ''
acc, checks = {}, {}
for rel, body in cfg['releases'].items():
    for case, crit in body['acceptance'].items():
        acc[(rel, case)] = crit
    for cid, entry in body['testcases'].items():
        if cid != 'registry': checks[(rel, cid)] = entry
prog = ['R00', 'R01', 'R02', 'R03', 'R04', 'R05', 'R06', 'R07', 'R08', 'RP', 'RX1', 'RX2', 'KN', 'PL', 'PL-A', 'PL-B', 'KET']
rows = []
sec = t04.split('## Ánh xạ 62 ID task cũ')[0]
for l in sec.split('\n'):
    m = re.match(r'^\| ([A-Z][A-Za-z0-9-]*?)(\s*\(S\))? \| ', l)
    if m and not l.startswith('| ID ') and not l.startswith('| Release '):
        c = [x.strip() for x in l.strip().strip('|').split('|')]
        if len(c) >= 9 and c[1] in prog: rows.append(c)
def short(s, n=110):
    s = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', s).replace('**', '')
    return s if len(s) <= n else s[:n].rsplit(' ', 1)[0] + ' …'
r00 = json.load(open(os.path.join(R, 'wfkit', 'testcases.json'), encoding='utf-8'))
r00_map = {}
for cid, entry in (r00.get('releases', {}).get('R00', {}).get('testcases', {}) or r00.get('R00', {}).get('testcases', {}) or {}).items():
    for tc in entry.get('testcases', [cid]) if isinstance(entry, dict) else []:
        r00_map[tc] = ', '.join(entry.get('modules', [])) if isinstance(entry, dict) else ''
def status_of(rel, tcs):
    found = []
    for tc in re.findall(r'T\d\d[a-z]?', tcs):
        if rel == 'R00' and tc in r00_map:
            found.append((tc, 'cổng R00 (wfkit/gate.py R00)', r00_map[tc].replace('tests.', ''), ''))
            continue
        key = next((k for k in acc if k[1] == tc and (k[0] == rel or rel in ('PL-A', 'PL-B', 'KET', 'PL') and k[0] == 'PL' or rel == 'KN' and k[0] == 'KN')), None)
        if key is None:
            key = next((k for k in acc if k[1] == tc), None)
        if key is None:
            found.append((tc, 'không có trong registry', '', ''))
            continue
        crit = acc[key]
        gap = '; '.join(sorted({g['kind'] for g in crit.get('gaps', [])}))
        found.append((tc, crit['status'], ', '.join(c.replace('check.', '') for c in crit.get('checks', [])), gap))
    return found
out = ['# FEATURE-SCOPE — chương trình workflow chung (development)', '',
       f'Sinh từ `docs/wf/sources/04-TASKS.vi.md` (sha256 {h04}) và `wfkit/development-testcases.json` (trạng thái acceptance theo từng testcase; '
       f'`python -m wfkit.development_gate list`). Trạng thái: `complete` = có bảng bằng chứng theo từng [E]; `partial` = có kiểm hồi quy, ma trận '
       f'acceptance và phản chứng đầy đủ của T-case chưa được chứng nhận riêng; `blocked` = cần provider thật, pilot hay chủ sở hữu (ngoài development). '
       f'R00 được kiểm bằng cổng riêng `wfkit/gate.py R00` (biên nhận PASS 24/10, D:\\OneCrewRuns\\wf-dev-logs\\cg-r00). {extra}', '']
for rel in prog:
    rs = [r for r in rows if r[1] == rel]
    if not rs: continue
    out += [f'## {rel}', '', '| Task | Kết quả (rút gọn từ 04) | Testcase | Trạng thái registry | Kiểm hiện có | Khoảng trống |', '|---|---|---|---|---|---|']
    for r in rs:
        tcs = status_of(rel, r[8])
        if not tcs:
            out.append(f'| {r[0]} | {short(r[3])} | {r[8]} | — | — | bộ kiểm (WK*) / khảo sát: không có T-case riêng |')
            continue
        for tc, st, ch, gap in tcs:
            out.append(f'| {r[0]} | {short(r[3])} | {tc} | {st} | {ch} | {gap} |')
    out.append('')
out += ['## Ngoài chương trình (hoãn theo nguồn)', '', 'RD, RR, RL (04 mục "Hoãn: nhánh có điều kiện") và Digital Twin không thuộc development này.', '']
open(os.path.join(R, 'docs', 'wf', 'FEATURE-SCOPE.md'), 'w', encoding='utf-8', newline='\n').write('\n'.join(out))
from collections import Counter
print(Counter(v['status'] for v in acc.values()), len(rows), 'task rows')
