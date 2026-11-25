r"""thu-qsat.py: helper of thu-qsat.ps1 (QSAT M2, the owner's trial in a trial folder). Run it with the python of the trial runtime, inside the
environment thu-qsat.ps1 sets (LOCALAPPDATA/APPDATA of the trial folder); it never touches the machine's own profile, ledgers or hooks.

  plan <name> <out.json> <label>        write a small trial plan (owner-manual milestone) for one trial repository
  day  --exe <onecrew.exe> --settings <trial settings.json> --a <repo A> --b <repo B> --session <id>
                                        feed the simulated hook events to the observer handler written into the trial settings file, as Claude
                                        would: from repo A (the hook process directory) a hand-over whose short description holds a fake key, then
                                        a Read of a file in repo B (which has its own plan), then the end of the turn
  xem  --so-a <ledger A> --so-b <ledger B> --session <id> [--plan-a <name>]
                                        read-only: the hand-over's summary line (masked?), the session's binding, the rows in ledger A and ledger B
Exit code of xem: 0 when the summary is there and masked, the session is still bound to A's plan, A has the Read of B and B has no row; else 1.
"""
import argparse
import hashlib
import json
import os
import secrets
import sqlite3
import subprocess
import sys
from pathlib import Path

FAKE = 'ghp_' + 'Thu0Qsat1Khoa2Gia3' * 2         # a fake key in the shape the observer masks (never a real one)
BODY = 'NOI-DUNG-RIENG-cua-loi-giao-viec'         # the hand-over's own text: must never reach a ledger
DESCRIPTION = 'Soat ma thu QSAT ' + FAKE


def plan(name, out, label):
    doc = {
        'schema_version': 2,
        'title': 'Plan thử QSAT ở ' + label + ': xem bộ quan sát ghi dòng tóm tắt và giữ phiên gắn đúng dự án',
        'size': 'S',
        'origin': {'at': '2026-11-25 09:30', 'by': 'owner',
                   'quote': 'đồng ý sửa bộ quan sát (lời chủ 25/11/2026 về QSAT); plan này chỉ dùng để thử ở thư mục thử.'},
        'understanding': {'restated_goal': 'Thử bộ quan sát mới ở thư mục thử riêng, với sổ thử riêng; không đụng sổ thật hay hook toàn máy.',
                          'target': {'repo': '.', 'ref': 'HEAD', 'paths': ['README.md']}, 'assumptions': [], 'confidence': 'high', 'unknowns': []},
        'preconditions': [{'id': 'P1', 'check': 'path_exists', 'args': {'path': 'README.md'}, 'why': 'Repo thử đã có tệp đầu tiên do script tạo.'}],
        'output': ['Bộ quan sát ở thư mục thử ghi dòng tóm tắt đã che của một lần giao việc, và phiên vẫn gắn dự án của nó khi đọc tệp ở dự án thử kia.'],
        'scope': {'owned': ['ghi-chu/']},
        'non_goals': ['Đụng sổ thật, runtime đã cài hay hook toàn máy'],
        'items': [{'id': 'I1', 'title': 'Thử bộ quan sát ở thư mục thử', 'tier': 'must', 'milestone': 'M1', 'source': 'origin'}],
        'milestones': [{'id': 'M1', 'title': 'Chủ thử ở thư mục thử và ghi kết quả', 'verifier': {'type': 'owner-manual', 'config': {}}, 'covers': ['O1']}],
        'budget': {'max_calls': 100, 'time': 1440},
        'attention': {'questions': 1},
        'profile_version': None,
        'presentation': {'request': 'Thử bộ quan sát mới ở thư mục thử trước khi cài thật.',
                         'user_sees': ['Sổ thử có dòng tóm tắt đã che của lần giao việc mô phỏng.', 'Phiên vẫn gắn dự án thử A sau khi đọc tệp ở dự án thử B.'],
                         'acceptance_steps': ['Chạy script thử và đọc kết quả in ra.'],
                         'not_doing': 'Không đổi sổ thật hay hook toàn máy; plan này hết hạn sau một ngày.'},
    }
    Path(out).write_text(json.dumps(doc, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print('plan thu ' + name + ': ' + out)
    return 0


def handler_args(settings):
    """The args of the observation handler `hook user install --observe` wrote into the trial settings file."""
    hooks = json.loads(Path(settings).read_text(encoding='utf-8')).get('hooks') or {}
    found = [h.get('args') for entry in hooks.get('UserPromptSubmit', []) for h in entry.get('hooks', [])
             if isinstance(h.get('args'), list) and h['args'][:2] == ['hook', 'observe']]
    if len(found) != 1: raise SystemExit('KHONG DAT: tep settings thu khong co dung mot muc quan sat: ' + str(settings))
    return found[0]


def day(args):
    observe = handler_args(args.settings)
    a, b = Path(args.a).resolve(), Path(args.b).resolve()
    env = {k: v for k, v in os.environ.items() if k not in ('CLAUDE_PROJECT_DIR', 'CLAUDECODE', 'CLAUDE_CODE_ENTRYPOINT', 'CLAUDE_CODE_CHILD_SESSION')}
    events = [
        {'hook_event_name': 'SessionStart'},
        {'hook_event_name': 'PreToolUse', 'tool_name': 'Agent', 'tool_use_id': 'thu-giao-viec',
         'tool_input': {'description': DESCRIPTION, 'prompt': BODY + ' (cả lời giao, không được vào sổ)', 'subagent_type': 'general-purpose'}},
        {'hook_event_name': 'PreToolUse', 'tool_name': 'Read', 'tool_use_id': 'thu-doc-b', 'tool_input': {'file_path': str(b / 'README.md')}},
        {'hook_event_name': 'Stop'},
    ]
    for event in events:
        event = dict(event, session_id=args.session, cwd=str(a))
        done = subprocess.run([args.exe, *observe], input=json.dumps(event).encode('utf-8'), cwd=str(a), env=env, capture_output=True, timeout=120)
        said = (done.stdout + done.stderr).decode('utf-8', 'replace').strip()
        print('su kien ' + event['hook_event_name'] + (' ' + event.get('tool_name', '') if event.get('tool_name') else '') + ': exit ' + str(done.returncode)
              + ((' (' + said[:200] + ')') if said else ''))
        if done.returncode != 0: return 1
    return 0


def rows_of(ledger, session):
    path = Path(ledger) / 'ledger.sqlite3'
    if not path.is_file(): return []
    con = sqlite3.connect('file:' + path.resolve().as_posix() + '?mode=ro', uri=True)
    try:
        rows = [json.loads(p) for (p,) in con.execute("SELECT payload FROM events WHERE kind='hook.observed' ORDER BY seq")]
    finally:
        con.close()
    return [r for r in rows if r.get('session') == session]


def binding_of(session):
    from onecrew.v2 import where
    path = where.default_state_root() / 'claude-session-bindings' / (hashlib.sha256(session.encode('utf-8')).hexdigest() + '.json')
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def xem(args):
    a_rows, b_rows = rows_of(args.so_a, args.session), rows_of(args.so_b, args.session)
    give = next((r for r in a_rows if r.get('tool_use_id') == 'thu-giao-viec' and r.get('hook') == 'PreToolUse'), None)
    summary = give.get('summary') if give else None
    record = binding_of(args.session) or {}
    target = record.get('target') or {}
    everything = json.dumps(a_rows + b_rows, ensure_ascii=False)
    checks = [
        ('dong tom tat cua lan giao viec co trong so A', isinstance(summary, str) and bool(summary), repr(summary)),
        ('dong tom tat da che khoa gia va dai toi da 160 ky tu', isinstance(summary, str) and FAKE not in summary and len(summary) <= 160,
         (str(len(summary)) + ' ky tu') if isinstance(summary, str) else 'khong co'),
        ('loi giao viec (than tin) khong vao so nao', BODY not in everything, ''),
        ('phien van gan plan cua du an A sau khi doc tep o B', record.get('status') == 'bound' and target.get('plan') == args.plan_a,
         'trang thai ' + str(record.get('status')) + ', plan ' + str(target.get('plan')) + ', ly do ' + str(record.get('reason'))),
        ('lan doc tep o B duoc ghi vao so A', any(r.get('tool_use_id') == 'thu-doc-b' for r in a_rows), str(len(a_rows)) + ' dong cua phien o so A'),
        ('so B khong co dong nao cua phien thu', not b_rows, str(len(b_rows)) + ' dong'),
    ]
    print('Dong tom tat da ghi: ' + (summary if isinstance(summary, str) else '(khong co)'))
    for name, ok, detail in checks:
        print(('DAT  ' if ok else 'TRUOT ') + name + ((': ' + detail) if detail else ''))
    return 0 if all(ok for _, ok, _ in checks) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = parser.add_subparsers(dest='verb', required=True)
    p = sub.add_parser('plan'); p.add_argument('name'); p.add_argument('out'); p.add_argument('label')
    p = sub.add_parser('day'); p.add_argument('--exe', required=True); p.add_argument('--settings', required=True)
    p.add_argument('--a', required=True); p.add_argument('--b', required=True); p.add_argument('--session', required=True)
    p = sub.add_parser('xem'); p.add_argument('--so-a', required=True); p.add_argument('--so-b', required=True); p.add_argument('--session', required=True)
    p.add_argument('--plan-a', default='QSAT-THU-A')
    p = sub.add_parser('phien')
    args = parser.parse_args()
    if args.verb == 'plan': return plan(args.name, args.out, args.label)
    if args.verb == 'day': return day(args)
    if args.verb == 'phien':
        print('thu-qsat-' + secrets.token_hex(4)); return 0
    return xem(args)


if __name__ == '__main__':
    sys.exit(main())
