"""Read-only landing page for the tracking server. Counts and links use the list's filters."""
import datetime as dt
from collections import Counter
from html import escape
from pathlib import Path
from urllib.parse import urlencode

from . import tracking, tracking_host_web, tracking_list

ATTENTION = (('need', 'Cần bạn quyết định'), ('fix', 'Cần sửa'), ('inconclusive', 'Chưa kết luận'),
             ('recheck', 'Cần kiểm lại'), ('idle', 'Im hơn 3 ngày'))
SERIES = {'pass': 'Đạt', 'fail': 'Không đạt', 'inconclusive': 'Chưa kết luận'}


def check_days(conn, projects, now):
    """One calendar bin per local day. Count recorded results, including superseded revisions."""
    today = now.astimezone().date()
    days = {(today - dt.timedelta(days=i)).isoformat(): dict.fromkeys(SERIES, 0) for i in reversed(range(14))}
    sql = """SELECT date(created_at,'localtime') AS day, json_extract(payload,'$.result') AS result, count(*)
             FROM events WHERE task_id=? AND kind=? AND date(created_at,'localtime') BETWEEN ? AND ?
             GROUP BY day, result"""
    for tasks in projects.values():
        for task in tasks:
            kind = 'node.verification' if task['tracking']['adapter'] == 'engine' else 'verdict.recorded'
            for day, result, count in conn.execute(sql, (task['id'], kind, min(days), max(days))):
                if result in SERIES:
                    days[day][result] += count
    return days


def repo_dir(project):
    """Use Git's worktree metadata. Keep unreadable or removed checkouts separate."""
    path = Path(project)
    git = path / '.git'
    try:
        if git.is_dir():
            return git.resolve()
        with git.open(encoding='utf-8-sig') as stream:
            marker = stream.readline(4096).strip()
        if marker.startswith('gitdir: '):
            private = path / marker[8:]
            common = private / 'commondir'
            if common.is_file():
                with common.open(encoding='utf-8') as stream:
                    return (private / stream.readline(4096).strip()).resolve()
            return private.resolve()
    except (OSError, ValueError, RuntimeError):
        pass
    return None


def link(label, **filters):
    query = '?' + urlencode(filters) if filters else ''
    return f'<a href="/{escape(query)}">{label}</a>'


def projects_html(projects):
    groups = {}
    for project in projects:
        path = Path(project['path'])
        git = repo_dir(path)
        groups.setdefault(git, []).append(project)
    cards = []
    for git, trees in groups.items():
        name = (git.parent.name if git.name == '.git' else git.name) if git else 'Chưa xác định repo'
        rows, tasks_in_repo = [], []
        for tree in trees:
            path, tasks = tree['path'], tree['tasks']
            tasks_in_repo.extend(tasks)
            rows.append('<li>' + link(escape(Path(path).name) + f' · {len(tasks)} việc', project=path)
                        + ' · ' + link(f'{sum(bool(t.get("needs_user")) for t in tasks)} cần bạn', project=path, stage='need') + '</li>')
        repo_filter = 'repo:' + ','.join(sorted({t['project_id'] for t in tasks_in_repo}))
        summary = ' · '.join(link(f'{count} {word}', project=repo_filter, stage=stage) for stage, count, word in (
            ('need', sum(bool(t.get('needs_user')) for t in tasks_in_repo), 'cần bạn'),
            ('fix', sum(tracking_list._stage_ok(t, 'fix') for t in tasks_in_repo), 'cần sửa'),
            ('ended', sum(t.get('root_status') in ('accepted', 'closed') for t in tasks_in_repo), 'đã kết thúc')))
        title = link(escape(tracking._guard(name)), project=repo_filter)
        cards.append(f'<article><h3>{title}</h3><p>{summary}</p><details><summary>{len(trees)} thư mục làm việc</summary><ul>{"".join(rows)}</ul></details></article>')
    return ''.join(cards)


def rhythm_html(days):
    peak = max((sum(counts.values()) for counts in days.values()), default=0)
    columns = []
    totals = Counter()
    for day, counts in days.items():
        totals.update(counts)
        label = day + ' · ' + ', '.join(f'{counts[k]} {word.lower()}' for k, word in SERIES.items())
        segments = ''.join(f'<i class="{k}" style="height:{100 * n / (peak or 1):.3f}%"></i>' for k, n in counts.items() if n)
        columns.append(f'<span class="column" role="img" aria-label="{label}" title="{label}">{segments}</span>')
    legend = ''.join(f'<span><i class="key {k}"></i>{label} {totals[k]}</span>' for k, label in SERIES.items())
    return (f'<article><small>Cao nhất {peak} lần/ngày</small><div class="plot">{"".join(columns)}</div>'
            f'<div class="axis"><time>{min(days)}</time><time>{max(days)}</time></div><p class="legend">{legend}</p></article>')


def background_html(host, leases):
    states = Counter(i['state_label'] for p in host['projects'] for i in (p.get('view') or {}).get('items', []))
    signal = ', '.join(f'{n} {escape(k)}' for k, n in states.items()) or 'Chưa thấy việc nền qua hook'
    missing = host.get('projects_not_read', 0) + sum(bool(p.get('error')) for p in host['projects'])
    if missing:
        signal += f' · {missing} dự án chưa đọc được'
    if leases.get('error'):
        resources = 'Chưa đọc được trạng thái khóa'
    elif leases['declared']:
        resources = ', '.join(escape(r['resource']) + ' · ' + escape(r['state_label']) +
                              (f' ({len(r["waiters"])} chờ)' if r['waiters'] else '') for r in leases['resources'])
    else:
        resources = 'Máy chưa khai báo tài nguyên'
    return (f'<article><h3>Agent và việc nền</h3><p>{signal}</p><small>Host tự báo qua hook</small></article>'
            f'<article><h3>Khóa tài nguyên trên máy</h3><p>{resources}</p></article>')


STYLE = """
:root{color-scheme:light dark;--ink:#202732;--mut:#535f6b;--bg:#f4f6f8;--card:#fff;--line:#cbd2d9;--link:#185eab}
@media(prefers-color-scheme:dark){:root{--ink:#e7ecf2;--mut:#b2bcc8;--bg:#14191f;--card:#202832;--line:#495460;--link:#92c3ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:1rem/1.45 system-ui,sans-serif}
header{background:var(--card);padding:12px max(16px,calc((100% - 1080px)/2));border-bottom:1px solid var(--line)}
header,nav,.legend,.axis{display:flex;gap:1rem;align-items:center;flex-wrap:wrap}main{max-width:1112px;margin:auto;padding:1rem}
a{color:var(--link);text-underline-offset:.18em}a:focus-visible{outline:3px solid currentColor}h1{margin:0}h2{font-size:1.15rem;margin:1.5rem 0 .6rem}
h3,p,ul{margin:.35rem 0}h3{font-size:1rem}small,time{color:var(--mut)}.grid{display:grid;gap:.65rem;grid-template-columns:repeat(auto-fit,minmax(min(100%,14rem),1fr))}
article,.attention a{min-width:0;padding:1rem;border:1px solid var(--line);border-radius:10px;background:var(--card);overflow-wrap:anywhere}
.attention{display:grid;gap:.5rem;grid-template-columns:repeat(auto-fit,minmax(min(100%,9rem),1fr))}.attention a{text-decoration:none}.attention strong{display:block;font-size:1.6rem}.attention a:first-child{border-color:var(--link)}
.plot{height:130px;display:flex;gap:1.4%;border-block:1px solid var(--line);margin-top:.5rem}.column{flex:1;display:flex;flex-direction:column-reverse;justify-content:flex-start}
.pass{background:#348363}.fail{background:#be514b}.inconclusive{background:repeating-linear-gradient(45deg,#b58624 0 3px,transparent 3px 5px)}
.axis{justify-content:space-between;font-size:.8rem}.key{display:inline-block;width:12px;height:12px;margin-right:.3em}.legend{font-size:.9rem}
"""


def page(state_root, project_id=None, *, comparison=True):
    value = tracking._overview(state_root, project_id=project_id, reuse_seconds=tracking.REUSE_SECONDS, rhythm=True, comparison=comparison)
    # Git metadata and the host/lease stores are read only after the ledger transaction has closed.
    if comparison:
        tracking_host_web.attach(value, state_root)
    value = tracking.outward(value)
    now = tracking._at(value['generated_at'])
    # The list can run on a shared server even when this dashboard was opened for one project.
    list_scope = {}
    if project_id:
        projects = value['projects']
        list_scope['project'] = projects[0]['path'] if len(projects) == 1 else 'repo:' + project_id
    overview_url = '/overview?' + urlencode({'project_id': project_id}) if project_id else '/overview'
    content = f'<small>Đọc lúc {now.astimezone():%H:%M %d/%m/%Y} · <a href="">Đọc lại</a></small>'
    if value['source']['status'] != 'ok':
        content += '<p role="status">' + escape(value['source']['detail']) + '</p>'
    else:
        tasks = [t for group in value['projects'] for t in group['tasks']]
        content += '<h2>Cần chú ý trong sổ</h2><nav class="attention" aria-label="Cần chú ý">'
        for stage, label in ATTENTION:
            count = sum(tracking_list._stage_ok(t, stage, now) for t in tasks)
            content += link(f'<strong>{count}</strong>{label}', stage=stage, **list_scope)
        content += '</nav>'
        owners = [t for t in tasks if t.get('needs_user')]
        if owners:
            content += '<ul>' + ''.join('<li>' + link(escape(t.get('row_title') or t['plan']), plan=t['selector'], project_id=t['project_id'])
                                        + '</li>' for t in owners) + '</ul>'
        unseen = sum((t.get('validity') or {}).get('kind') == 'not_compared' for t in tasks)
        if unseen:
            content += f'<p>{unseen} việc chưa so với bản hiện tại. Số cần kiểm lại chỉ gồm việc đã so.</p>'
        content += '<h2>Theo repo và worktree</h2><div class="grid">' + (projects_html(value['projects']) or 'Chưa có việc trong sổ') + '</div>'
        content += '<h2>Nhịp kiểm 14 ngày</h2>' + rhythm_html(value['check_days'])
        if comparison:
            content += '<h2>Việc nền và tài nguyên</h2><div class="grid">' + background_html(value['host_work'], value['shared_resources']) + '</div>'
        session_tasks = value.get('session_tasks', {})
        session_links = []
        for task in tasks:
            count = session_tasks.get(task.get('id'))
            if count:
                query = urlencode({'plan': task['selector'], 'project_id': task['project_id']})
                session_links.append(f'<li><a href="/sessions?{escape(query)}">{escape(task["plan"])} · {count} phiên</a></li>')
        content += '<h2>Phiên Claude</h2><article>' + ('<ul>' + ''.join(session_links) + '</ul>' if session_links
                    else 'Chưa có dữ liệu phiên, token, model và chi phí.') + '</article>'
    return (f'<!doctype html><html lang="vi"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Tổng quan · OneCrew</title><style>{STYLE}</style><header><b>OneCrew</b><nav aria-label="Trang">'
            f'<a href="{escape(overview_url)}" aria-current="page">Tổng quan</a>{link("Công việc", **list_scope)}</nav></header>'
            f'<main><h1>Tổng quan</h1>{content}</main></html>').encode('utf-8')
