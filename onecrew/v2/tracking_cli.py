"""`onecrew track list|show|evidence|serve|open|status|stop` — the OBS-1 read-only tracking view (onecrew/v2/tracking.py) as text, JSON or a local web page.

`list` and `show --json` print exactly the JSON the web page reads (one state model, no second source). `serve` runs the page on 127.0.0.1
in this process (Ctrl+C closes the VIEWER, never a worker); `open` starts that server detached and opens the page in the default browser —
or reuses the one already running for this state root when its identity (instance, wheel version, state root, scope) matches; `status` shows
that identity check; `stop` stops only the matching server (never another process). Every command reads the ledger read-only; none approves,
answers, pauses or resumes anything — `stop` ends the page's server, not a task.

`stop --url U --instance I --pid P [--started-at T]` (R5 round 4, 03/11) stops exactly the server that answers at U as instance I with pid P
for this state root, even when the marker names another server (a pinned viewer whose marker moved), and nothing else; without these
arguments `stop` is unchanged (the marker's server). See tracking_web.stop_target.
"""
import argparse
import json
import sys
from pathlib import Path

from ..ledger import LedgerError
from . import tracking
from .where import state_root_for


def _parser():
    p = argparse.ArgumentParser(prog='onecrew track', allow_abbrev=False, description='Theo dõi chỉ đọc: danh sách task, chi tiết/timeline, trang web local.')
    p.add_argument('--project', type=Path, default=Path.cwd())
    p.add_argument('--state-root', type=Path)
    p.add_argument('group', choices=['track'])
    sub = p.add_subparsers(dest='command', required=True)
    a = sub.add_parser('list', help='Một dòng mỗi plan với trạng thái có nguồn; --json in đúng dữ liệu trang web đọc.')
    a.add_argument('--json', action='store_true'); a.add_argument('--all-projects', action='store_true', help='Mọi project của sổ (mặc định: project của --project).')
    a = sub.add_parser('show', help='Chi tiết một plan: node, attempt, chờ, ETA, timeline, bằng chứng.')
    a.add_argument('plan'); a.add_argument('--json', action='store_true'); a.add_argument('--all-projects', action='store_true', help='Tìm plan trong mọi project của sổ.')
    a.add_argument('--timeline', type=int, default=200, help='Số sự kiện gần nhất (1-5000).')
    a = sub.add_parser('evidence', help='In một blob bằng chứng mà sự kiện của plan nêu (lọc bí mật, tối đa 64 KiB).')
    a.add_argument('plan'); a.add_argument('key'); a.add_argument('--all-projects', action='store_true')
    for verb in ('serve', 'open'):
        a = sub.add_parser(verb, help=('Chạy trang web local trong tiến trình này (Ctrl+C đóng trang, không dừng worker).' if verb == 'serve'
                                      else 'Mở trang web local trong trình duyệt mặc định (server chạy tách rời).'))
        a.add_argument('--host', default='127.0.0.1'); a.add_argument('--port', type=int, default=0, help='0 = cổng trống bất kỳ.')
        a.add_argument('--interval', type=float, default=2.0, help='Chu kỳ poll của trang (giây, 0.5-60).')
        a.add_argument('--project-only', action='store_true', help='Chỉ project của --project (mặc định: mọi project của sổ).')
        if verb == 'serve':
            a.add_argument('--announce', help=argparse.SUPPRESS)
            a.add_argument('--idle-exit', type=float, default=None, help='Tự thoát sau N giây không có request (mặc định: không; `track open` đặt 1800).')
        else:
            a.add_argument('--no-browser', action='store_true', help='Khởi động/dùng lại server và in URL, không mở trình duyệt.')
    sub.add_parser('status', help='Server theo dõi của sổ này (marker + /api/health): có dùng lại được không, vì sao không.')
    a = sub.add_parser('stop', help='Dừng server theo dõi mà `track open` đã mở cho sổ này (chỉ tiến trình khớp định danh; không dừng task).')
    a.add_argument('--url', help='Dừng ĐÚNG server này (đi cùng --instance và --pid): http://127.0.0.1:<cổng>/, kể cả khi marker của sổ đã trỏ sang server khác.')
    a.add_argument('--instance', help='Định danh (instance) của server cần dừng; /api/health ở --url phải báo đúng nó.')
    a.add_argument('--pid', type=int, help='PID của server cần dừng; /api/health ở --url phải báo đúng nó.')
    a.add_argument('--started-at', help='started_at mà server đó tự ghi (marker/ghim): phân biệt tiến trình đã thoát với một PID đã bị tiến trình khác dùng lại.')
    return p


def _state_root(opts):
    from ..ledger import Ledger
    project = opts.project.resolve()
    root = state_root_for(project, opts.state_root)
    ledger = Ledger(project, root)                 # resolves the default state root exactly as every other command does; writes nothing
    return ledger.state_root, ledger.project_id


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    opts = _parser().parse_args(args)
    try:
        state_root, project_id = _state_root(opts)
        if opts.command == 'list':
            value = tracking.overview(state_root, project_id=None if opts.all_projects else project_id)
            print(json.dumps(value, ensure_ascii=False, indent=1) if opts.json else tracking.render_overview(value), end='')
            return 0
        if opts.command == 'show':
            if not 1 <= opts.timeline <= 5000: raise LedgerError('--timeline: 1-5000.')
            value = tracking.detail(state_root, opts.plan, project_id=None if opts.all_projects else project_id, timeline_limit=opts.timeline)
            print(json.dumps(value, ensure_ascii=False, indent=1) if opts.json else tracking.render_detail(value), end='')
            return 0
        if opts.command == 'evidence':
            value = tracking.evidence(state_root, opts.plan, opts.key, project_id=None if opts.all_projects else project_id)
            print(f"# blob {value['key']} ({value['bytes']} bytes{', cắt' if value['truncated'] else ''}; lọc: {value['redaction']['rule']})")
            print(value['text'])
            return 0
        from . import tracking_web
        if opts.command == 'status':
            print(json.dumps(tracking_web.status_page(state_root), ensure_ascii=False, indent=1)); return 0
        if opts.command == 'stop':
            named = [value is not None for value in (opts.url, opts.instance, opts.pid)]
            if any(named) or opts.started_at is not None:
                if not all(named):
                    raise LedgerError('track stop: --url, --instance và --pid phải đi cùng nhau (dừng đúng một server đã biết định danh); '
                                      '--started-at chỉ đi kèm ba tham số đó. Không dừng gì.')
                result = tracking_web.stop_target(state_root, opts.url, opts.instance, opts.pid, started_at=opts.started_at)
            else:
                result = tracking_web.stop_page(state_root)
            print(json.dumps(result, ensure_ascii=False, indent=1)); return 0 if result.get('stopped') else 2
        if not 0.5 <= opts.interval <= 60: raise LedgerError('--interval: 0.5-60 giây.')
        scope = project_id if opts.project_only else None
        if opts.command == 'serve':
            import os
            idle = opts.idle_exit if opts.idle_exit is not None else (float(os.environ['ONECREW_TRACK_IDLE_EXIT']) if os.environ.get('ONECREW_TRACK_IDLE_EXIT') else None)
            return tracking_web.serve(state_root, host=opts.host, port=opts.port, project_id=scope, interval=opts.interval, announce=opts.announce, idle_exit=idle)
        result = tracking_web.open_page(state_root, host=opts.host, port=opts.port, project_id=scope, interval=opts.interval,
                                        project=opts.project.resolve(), explicit_state_root=opts.state_root, browser=not opts.no_browser)
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0 if result.get('url') else 2
    except PermissionError as error:
        print(json.dumps(tracking.outward({'error': str(error), 'type': 'refused'}), ensure_ascii=False)); return 3
    except (LedgerError, OSError, ValueError) as error:
        print(json.dumps(tracking.outward({'error': str(error), 'type': type(error).__name__}), ensure_ascii=False)); return 2


if __name__ == '__main__':
    sys.exit(main())
