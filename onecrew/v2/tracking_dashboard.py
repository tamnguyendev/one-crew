"""Read-only landing page (Tổng quan) of the tracking server, and the shell every tracking page shares (UIMOCK, mockup of 19/11).

The shell: one token set (light/dark, switched by the "đổi nền" button and kept in the browser), the four destinations with icons (Tổng quan,
Công việc, Phiên Claude, Hướng đi: a bar on top on a wide screen, at the bottom of a phone screen), the "i" button (what the data does not
show), the "?" button (the legend of every icon) and the theme button. Counts and links of the landing page use the list's filters; numbers
are the ledger's own, and a frame whose source was never observed says so ("chưa quan sát") instead of showing a number.
"""
import datetime as dt
import json
import sqlite3
from collections import Counter
from html import escape
from pathlib import Path
from urllib.parse import urlencode

from ..ledger import LedgerError
from . import tracking, tracking_host_web, tracking_list

# ---- shell shared by the four pages ----------------------------------------------------------------------------------------------------

SPRITE = r'''<svg width="0" height="0" style="position:absolute;width:0;height:0;overflow:hidden" aria-hidden="true" focusable="false"><defs>
<symbol id="i-ok" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M8 12.5l3 3 5-6"/></symbol>
<symbol id="i-stamp" viewBox="0 0 24 24"><path d="M2.5 12.5l4 4L14.5 8.5M10 15l1.5 1.5L21 7"/></symbol>
<symbol id="i-check" viewBox="0 0 24 24"><path d="M4 12l5 5L20 6"/></symbol>
<symbol id="i-cross" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M9 9l6 6M15 9l-6 6"/></symbol>
<symbol id="i-refresh" viewBox="0 0 24 24"><path d="M20 11a8 8 0 0 0-14.3-4.9L4 8"/><path d="M4 3v5h5"/><path d="M4 13a8 8 0 0 0 14.3 4.9L20 16"/><path d="M20 21v-5h-5"/></symbol>
<symbol id="i-hourglass" viewBox="0 0 24 24"><path d="M7 3h10M7 21h10M8 3v3a4 4 0 0 0 1.6 3.2L12 11l2.4-1.8A4 4 0 0 0 16 6V3M8 21v-3a4 4 0 0 1 1.6-3.2L12 13l2.4 1.8A4 4 0 0 1 16 18v3"/></symbol>
<symbol id="i-question" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .9-1 1.6v.6M12 17.2v.1"/></symbol>
<symbol id="i-play" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M10 8.5l5 3.5-5 3.5z"/></symbol>
<symbol id="i-todo" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" stroke-dasharray="3.5 3"/></symbol>
<symbol id="i-stop" viewBox="0 0 24 24"><path d="M8.5 3h7L21 8.5v7L15.5 21h-7L3 15.5v-7z"/><path d="M9 12h6"/></symbol>
<symbol id="i-archive" viewBox="0 0 24 24"><rect x="3.5" y="4" width="17" height="4" rx="1"/><path d="M5 8v11h14V8M10 12h4"/></symbol>
<symbol id="i-need" viewBox="0 0 24 24"><circle cx="10" cy="8" r="3.5"/><path d="M3.5 20a6.5 6.5 0 0 1 13 0M20.5 5v6.5M20.5 15.5v.1"/></symbol>
<symbol id="i-person" viewBox="0 0 24 24"><circle cx="12" cy="8" r="3.5"/><path d="M5 20a7 7 0 0 1 14 0"/></symbol>
<symbol id="i-robot" viewBox="0 0 24 24"><rect x="5" y="8" width="14" height="11" rx="2.5"/><path d="M12 5v3M9.5 13v1M14.5 13v1M2.5 12.5v3M21.5 12.5v3"/><circle cx="12" cy="3.5" r="1.2"/></symbol>
<symbol id="i-shield" viewBox="0 0 24 24"><path d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6z"/><path d="M9 12l2 2 4-4"/></symbol>
<symbol id="i-box" viewBox="0 0 24 24"><path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M4 7.5l8 4.5 8-4.5M12 12v9"/></symbol>
<symbol id="i-next" viewBox="0 0 24 24"><path d="M5 12h14M13 6l6 6-6 6"/></symbol>
<symbol id="i-sign" viewBox="0 0 24 24"><path d="M12 3v18M6 5h11l2.5 2.5L17 10H6zM18 12H7l-2.5 2.5L7 17h11z"/></symbol>
<symbol id="i-copy" viewBox="0 0 24 24"><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/></symbol>
<symbol id="i-pencil" viewBox="0 0 24 24"><path d="M4 20l1-5L16 4l4 4L9 19z"/><path d="M14 6l4 4"/></symbol>
<symbol id="i-lock" viewBox="0 0 24 24"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></symbol>
<symbol id="i-eyeoff" viewBox="0 0 24 24"><path d="M3 3l18 18M10.6 6.1A9.9 9.9 0 0 1 12 6c5 0 9 6 9 6a17 17 0 0 1-2.5 3.1M6.3 7.6C4.1 9.2 3 12 3 12s4 6 9 6a8.8 8.8 0 0 0 4.1-1"/></symbol>
<symbol id="i-eye" viewBox="0 0 24 24"><path d="M3 12s4-6 9-6 9 6 9 6-4 6-9 6-9-6-9-6z"/><circle cx="12" cy="12" r="2.5"/></symbol>
<symbol id="i-warn" viewBox="0 0 24 24"><path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17v.1"/></symbol>
<symbol id="i-file" viewBox="0 0 24 24"><path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/></symbol>
<symbol id="i-list" viewBox="0 0 24 24"><path d="M9 6h11M9 12h11M9 18h11M4.5 6v.1M4.5 12v.1M4.5 18v.1"/></symbol>
<symbol id="i-clock" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></symbol>
<symbol id="i-code" viewBox="0 0 24 24"><path d="M8 7l-5 5 5 5M16 7l5 5-5 5"/></symbol>
<symbol id="i-parts" viewBox="0 0 24 24"><rect x="3.5" y="4" width="7" height="7" rx="1.5"/><rect x="13.5" y="4" width="7" height="7" rx="1.5"/><rect x="3.5" y="14" width="7" height="7" rx="1.5"/><rect x="13.5" y="14" width="7" height="7" rx="1.5"/></symbol>
<symbol id="i-dash" viewBox="0 0 24 24"><path d="M4 15a8 8 0 0 1 16 0"/><path d="M12 15l4-5"/><path d="M3 19h18"/></symbol>
<symbol id="i-turn" viewBox="0 0 24 24"><path d="M4 20V10a4 4 0 0 1 4-4h11"/><path d="M15 2l4 4-4 4"/></symbol>
<symbol id="i-book" viewBox="0 0 24 24"><path d="M4 4h11a4 4 0 0 1 4 4v12H8a4 4 0 0 1-4-4z"/><path d="M8 4v16"/></symbol>
<symbol id="i-flag" viewBox="0 0 24 24"><path d="M5 21V4h11l-2 4 2 4H5"/></symbol>
<symbol id="i-steps" viewBox="0 0 24 24"><path d="M4 18h5v-5h5V8h6"/><circle cx="4" cy="18" r="1.3"/></symbol>
<symbol id="i-out" viewBox="0 0 24 24"><path d="M4 12h11M11 7l5 5-5 5M19 5v14"/></symbol>
<symbol id="i-coin" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M14.8 9.2c-.5-.8-1.5-1.2-2.8-1.2-1.6 0-2.7.8-2.7 2s1.1 1.6 2.7 2 2.9.8 2.9 2.1-1.2 2-2.9 2c-1.3 0-2.4-.5-2.9-1.3M12 6v2M12 16v2"/></symbol>
<symbol id="i-brain" viewBox="0 0 24 24"><path d="M9 4.5a3 3 0 0 0-3 3 3 3 0 0 0-2 5.2A3 3 0 0 0 7 17.5 2.5 2.5 0 0 0 12 18V5.5a2.5 2.5 0 0 0-3-1z"/><path d="M15 4.5a3 3 0 0 1 3 3 3 3 0 0 1 2 5.2 3 3 0 0 1-3 4.8 2.5 2.5 0 0 1-5 .5"/></symbol>
<symbol id="i-cloud" viewBox="0 0 24 24"><path d="M7 18h10a4 4 0 0 0 .6-8A6 6 0 0 0 6 9a4.5 4.5 0 0 0 1 9z"/></symbol>
<symbol id="i-bill" viewBox="0 0 24 24"><path d="M6 3h12v18l-3-2-3 2-3-2-3 2z"/><path d="M9 8h6M9 12h6"/></symbol>
<symbol id="i-left" viewBox="0 0 24 24"><path d="M15 6l-6 6 6 6"/></symbol>
<symbol id="i-right" viewBox="0 0 24 24"><path d="M9 6l6 6-6 6"/></symbol>
<symbol id="i-x" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></symbol>
<symbol id="i-chart" viewBox="0 0 24 24"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></symbol>
<symbol id="i-search" viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/></symbol>
<symbol id="i-sun" viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5L19 19M5 19l1.5-1.5M17.5 6.5L19 5"/></symbol>
<symbol id="i-moon" viewBox="0 0 24 24"><path d="M20 14A8 8 0 1 1 10 4a7 7 0 0 0 10 10z"/></symbol>
<symbol id="i-auto" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 3v18"/><path d="M12 3a9 9 0 0 1 0 18z" fill="currentColor"/></symbol>
</defs></svg>'''

NAV = (('overview', '/overview', 'dash', 'Tổng quan', 'Tổng quan'), ('work', '/', 'list', 'Công việc', 'Việc'),
       ('sessions', '/sessions', 'robot', 'Phiên Claude', 'Phiên'), ('direction', '/direction', 'turn', 'Hướng đi', 'Hướng'))


def icon(name, size='', tone='', label=None):
    """One inline icon of the sprite; `label` makes it an image with a name, otherwise it is decoration."""
    cls = 'ic' + (' ' + size if size else '') + (' x-' + tone if tone else '')
    named = f' role="img" aria-label="{escape(label)}" title="{escape(label)}"' if label else ' aria-hidden="true"'
    return f'<span class="{cls}"{named} data-icon="{escape(name)}"><svg viewBox="0 0 24 24" aria-hidden="true"><use href="#i-{escape(name)}"/></svg></span>'


def chip(text, tone='', name=None, extra=''):
    return f'<span class="chip{" t-" + tone if tone else ""}"{extra}>{icon(name, "sm") if name else ""}{escape(text)}</span>'


def nav_html(current, scope=None, overview_scope=None, work_href=None):
    """The four destinations; `scope` (plan, project_id) keeps the task the reader is on, `overview_scope` the project of the landing page,
    `work_href` the list the landing page counts (its project filter)."""
    task = '?' + urlencode(scope) if scope else ''
    hrefs = {'overview': '/overview' + ('?' + urlencode({'project_id': overview_scope}) if overview_scope else ''),
             'work': work_href or '/' + task, 'sessions': '/sessions' + task, 'direction': '/direction' + task}
    return ''.join(f'<a href="{escape(hrefs[key])}" data-nav="{key}"' + (' aria-current="page"' if key == current else '')
                   + f' title="{label}">{icon(name)}<span class="lg">{label}</span><span class="sh">{short}</span></a>'
                   for key, _path, name, label, short in NAV)


def _li(mark, text):
    return f'<li>{mark}<span>{text}</span></li>'


def _shape(kind):
    shapes = {'read': '<circle r="5" fill="var(--c-doc)"/>', 'edit': '<rect x="-4.5" y="-4.5" width="9" height="9" fill="var(--c-sua)"/>',
              'cmd': '<path d="M0-6L5.5 4.5h-11z" fill="var(--c-lenh)"/>', 'check': '<path d="M0-6L6 0 0 6-6 0z" fill="var(--c-kiem)"/>',
              'agent': '<path d="M0-6l5.2 3v6L0 6l-5.2-3v-6z" fill="var(--c-agent)"/>', 'talk': '<path d="M-6-5h12L0 6z" fill="var(--c-giao)"/>',
              'other': '<path d="M-1.5-6h3v4.5H6v3H1.5V6h-3V1.5H-6v-3h4.5z" fill="var(--c-khac)"/>'}
    return f'<svg class="shape" viewBox="-8 -8 16 16" width="14" height="14" aria-hidden="true">{shapes[kind]}</svg>'


STEP_KINDS = (('read', 'Đọc'), ('edit', 'Sửa'), ('cmd', 'Chạy lệnh'), ('check', 'Kiểm'), ('agent', 'Gọi agent'), ('talk', 'Giao tiếp'), ('other', 'Khác'))
STATE_MARKS = (('need', 'need', 'Cần bạn'), ('play', 'run', 'Đang làm'), ('shield', 'wait', 'Chờ kiểm'), ('refresh', 'wait', 'Cần kiểm lại'),
               ('hourglass', 'wait', 'Chưa kết luận'), ('cross', 'fail', 'Cần sửa (không đạt)'), ('stop', 'stop', 'Đã dừng'), ('ok', 'ok', 'Xong'),
               ('archive', 'closed', 'Đã đóng'), ('todo', 'idle', 'Chưa bắt đầu'), ('question', 'unknown', 'Chưa xác định'))
MILESTONE_MARKS = (('ok', 'Đạt'), ('fail', 'Không đạt'), ('recheck', 'Cần kiểm lại'), ('inconclusive', 'Chưa kết luận'), ('run', 'Đang kiểm'),
                   ('pending', 'Chưa kiểm'), ('unknown', 'Chưa xác định bản hiện tại'))

LEGEND_HTML = (
    '<h4>Trạng thái việc</h4><ul>' + ''.join(_li(icon(n, '', tone), word) for n, tone, word in STATE_MARKS) + '</ul>'
    '<h4>Ai làm bước tiếp</h4><ul>' + _li(icon('person', '', 'need'), 'Bạn') + _li(icon('robot', '', 'run'), 'AI')
    + _li(icon('shield', '', 'run'), 'Bộ kiểm') + _li(icon('question', '', 'unknown'), 'Chưa rõ') + '</ul>'
    '<h4>Thanh mốc (mỗi ô một mốc)</h4><ul>' + ''.join(_li(f'<span class="swatch seg-{k}"></span>', w) for k, w in MILESTONE_MARKS) + '</ul>'
    '<h4>Bước trong phiên (hình và màu)</h4><ul>' + ''.join(_li(_shape(k), w) for k, w in STEP_KINDS) + '</ul>'
    '<h4>Hướng đi</h4><ul>' + _li('<span class="dtag s" style="--d:var(--d-A)">A</span>', 'Chữ cái: một giai đoạn; dấu phẩy (A′): làm lại giai đoạn đó')
    + _li(chip('lời chủ', 'need', 'person'), 'Lời chủ gõ, chép nguyên văn từ phiên đã quan sát')
    + _li(chip('sổ ghi', 'ok', 'book'), 'Dấu vết trong sổ (duyệt, sửa plan, kết quả kiểm)') + '</ul>'
    '<h4>Nguồn số liệu</h4><ul>' + _li(chip('sổ'), 'Đếm từ sổ') + _li(chip('chat'), 'Đếm từ phiên Claude đã quan sát (hook)')
    + _li(icon('lock', 'sm'), 'Dữ liệu thật trên máy này, đã lọc bí mật, chỉ đọc') + '</ul>')

LIMITS_HTML = (
    '<h4>Chung</h4><ul>' + _li(icon('lock', 'sm', 'idle'), 'Chỉ đọc: trang không duyệt, không trả lời, không dừng hay tiếp tục việc. Nút sao chép chỉ chép mẫu lệnh.')
    + _li(icon('shield', 'sm', 'idle'), 'Chữ đã qua bộ lọc bí mật và cắt ngắn; mã nội bộ dài chỉ hiện vài ký tự đầu.')
    + _li(icon('clock', 'sm', 'idle'), '“2 giờ trước” tính đến lúc đọc sổ; trang tự đọc lại sổ sau vài giây.') + '</ul>'
    '<h4>Sổ (Tổng quan, Công việc)</h4><ul>' + _li(icon('book', 'sm', 'idle'), 'Việc theo mốc: sổ chỉ thấy mốc và các lần kiểm, không thấy agent làm gì giữa hai lần kiểm.')
    + _li(icon('parts', 'sm', 'idle'), 'Việc nhiều phần: thấy từng phần, lượt chạy, tiến độ và lúc chờ.')
    + _li(icon('eye', 'sm', 'idle'), '“Còn tin được?” chỉ so với bản hiện tại của dự án khi bạn mở “Xem sâu”; trước đó trang nói “chưa so”.') + '</ul>'
    '<h4>Phiên Claude và Hướng đi</h4><ul>' + _li(icon('eyeoff', 'sm', 'idle'), 'Chỉ có phiên mà hook quan sát của máy này đã ghi vào sổ; phiên khác, phiên trên đám mây hay máy khác: chưa quan sát.')
    + _li(icon('bill', 'sm', 'idle'), 'Token, model và chi phí đọc từ nhật ký của phiên đang chọn; chi phí là ước tính theo giá niêm yết, không phải hóa đơn.')
    + _li(icon('list', 'sm', 'idle'), 'Danh sách việc là Claude tự báo, không phải bằng chứng.')
    + _li(icon('robot', 'sm', 'idle'), 'Giai đoạn của hướng đi tính từ bản kế hoạch và lời đổi hướng; lời chủ là chữ gõ trong phiên, chưa xác thực.') + '</ul>')

SHELL_STYLE = r'''
:root{--paper:#F6F8FB;--sheet:#FFFFFF;--ink:#1D2840;--ink2:#566179;--rule:#DCE3EC;--margin:#EDB1BA;--sel:#EAF0FA;--band:#EEF2F8;
--pen:#C01F3C;--pen-bg:#FBE9EC;--ok:#21784A;--ok-bg:#E5F2EA;--run:#2457A6;--run-bg:#E7EEF9;--wait:#9A6210;--wait-bg:#FAF0DC;--fail:#BF420F;--fail-bg:#FBEBE2;--idle:#7F889C;--idle-bg:#EDF0F4;--focus:#2457A6;
--m-need:#C01F3C;--m-run:#2457A6;--m-wait:#B7791F;--m-ok:#21784A;--m-fail:#BF420F;
--c-doc:#2a78d6;--c-sua:#eb6834;--c-lenh:#1baf7a;--c-kiem:#eda100;--c-agent:#6250d6;--c-giao:#e87ba4;--c-khac:#7F889C;
--d-A:#9EC5F4;--d-B:#eb6834;--d-C:#1baf7a;--d-D:#6250d6;--d-E:#e87ba4;--d-F:#2a78d6;--d-G:#eda100;--d-H:#98A1B3;color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--paper:#141B27;--sheet:#1B2433;--ink:#E4E9F2;--ink2:#A2ACC0;--rule:#2B3547;--margin:#7A3B47;--sel:#22314A;--band:#212C3D;
--pen:#FF7088;--pen-bg:#3A1F28;--ok:#5FC68E;--ok-bg:#1C3328;--run:#86ABF2;--run-bg:#1E2B45;--wait:#E5B65C;--wait-bg:#3A2F1A;--fail:#F58C5E;--fail-bg:#3B2419;--idle:#8E97AB;--idle-bg:#263042;--focus:#86ABF2;
--m-need:#E0506A;--m-run:#5B8FE8;--m-wait:#B8862C;--m-ok:#2A9C86;--m-fail:#E07A45;
--c-doc:#3987e5;--c-sua:#d95926;--c-lenh:#199e70;--c-kiem:#c98500;--c-agent:#9085e9;--c-giao:#d55181;--c-khac:#8E97AB;
--d-A:#2A5C9E;--d-B:#d95926;--d-C:#199e70;--d-D:#9085e9;--d-E:#d55181;--d-F:#3987e5;--d-G:#c98500;--d-H:#6B7488;color-scheme:dark}}
:root[data-theme=dark]{--paper:#141B27;--sheet:#1B2433;--ink:#E4E9F2;--ink2:#A2ACC0;--rule:#2B3547;--margin:#7A3B47;--sel:#22314A;--band:#212C3D;
--pen:#FF7088;--pen-bg:#3A1F28;--ok:#5FC68E;--ok-bg:#1C3328;--run:#86ABF2;--run-bg:#1E2B45;--wait:#E5B65C;--wait-bg:#3A2F1A;--fail:#F58C5E;--fail-bg:#3B2419;--idle:#8E97AB;--idle-bg:#263042;--focus:#86ABF2;
--m-need:#E0506A;--m-run:#5B8FE8;--m-wait:#B8862C;--m-ok:#2A9C86;--m-fail:#E07A45;
--c-doc:#3987e5;--c-sua:#d95926;--c-lenh:#199e70;--c-kiem:#c98500;--c-agent:#9085e9;--c-giao:#d55181;--c-khac:#8E97AB;
--d-A:#2A5C9E;--d-B:#d95926;--d-C:#199e70;--d-D:#9085e9;--d-E:#d55181;--d-F:#3987e5;--d-G:#c98500;--d-H:#6B7488;color-scheme:dark}
*{box-sizing:border-box}html,body{margin:0}
body{background:var(--paper);color:var(--ink);font:15px/1.45 "Segoe UI Variable Text","Segoe UI",system-ui,-apple-system,"Noto Sans",Roboto,sans-serif;font-variant-numeric:tabular-nums;min-width:0}
a{color:inherit}button,select,input{font:inherit;color:inherit}:focus-visible{outline:2px solid var(--focus);outline-offset:2px}
header.shell{position:relative;z-index:10;display:flex;align-items:center;gap:10px;height:48px;padding:0 16px;border-bottom:1px solid var(--rule);background:var(--sheet)}
header.shell .brand{font-weight:700;letter-spacing:-.01em;text-decoration:none;font-size:15px;margin:0}
.views{display:flex;flex:none;gap:2px;padding:2px;border:1px solid var(--rule);border-radius:8px}
.views a{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border-radius:6px;font-size:13.5px;color:var(--ink2);text-decoration:none;white-space:nowrap;background:transparent}
.views a[aria-current]{background:var(--ink);color:var(--paper)}
.views .sh{display:none}.hsp{flex:1 1 auto}
.hbtn{flex:none;display:inline-flex;align-items:center;justify-content:center;min-width:32px;height:30px;font-size:14px;font-weight:700;padding:0 8px;border-radius:6px;border:1px solid var(--rule);background:transparent;color:var(--ink2);cursor:pointer}
#limits-btn{font-style:italic;font-family:Georgia,serif}
.pop{position:absolute;right:16px;top:52px;z-index:20;width:380px;max-width:calc(100vw - 32px);max-height:calc(100vh - 70px);overflow:auto;padding:12px 14px;border:1px solid var(--rule);border-radius:10px;background:var(--sheet);box-shadow:0 8px 24px rgba(20,27,39,.18);font-size:13.5px;color:var(--ink)}
.pop[hidden]{display:none}.pop h4{margin:10px 0 4px;font-size:13px;color:var(--ink2)}.pop h4:first-child{margin-top:0}
.pop ul{list-style:none;margin:0;padding:0;display:grid;gap:5px}.pop li{display:flex;align-items:flex-start;gap:8px}.pop li>.ic,.pop li>svg,.pop li>.swatch,.pop li>.chip{margin-top:2px}
.hstat{font-size:12.5px;color:var(--fail);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}.hstat:empty{display:none}
.ic{display:inline-flex;flex:none;width:18px;height:18px}.ic svg{width:100%;height:100%;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.ic.sm{width:14px;height:14px}.ic.lg{width:30px;height:30px}
.x-ok{color:var(--ok)}.x-run{color:var(--run)}.x-wait{color:var(--wait)}.x-fail{color:var(--fail)}.x-need,.x-stop{color:var(--pen)}.x-idle,.x-closed,.x-unknown{color:var(--ink2)}
.chip{display:inline-flex;align-items:center;gap:4px;padding:0 7px;border-radius:999px;font-size:11.5px;font-weight:600;line-height:18px;white-space:nowrap;background:var(--idle-bg);color:var(--ink2);text-decoration:none}
.chip.t-need{background:var(--pen-bg);color:var(--pen)}.chip.t-ok{background:var(--ok-bg);color:var(--ok)}.chip.t-run{background:var(--run-bg);color:var(--run)}
.chip.t-wait{background:var(--wait-bg);color:var(--wait)}.chip.t-fail{background:var(--fail-bg);color:var(--fail)}a.chip:hover{text-decoration:underline}
.mut{color:var(--ink2)}.small{font-size:13px}.clamp1{overflow:hidden;white-space:nowrap;text-overflow:ellipsis;min-width:0}
.panel{min-width:0;padding:12px 14px;border:1px solid var(--rule);border-radius:10px;background:var(--sheet)}
.panel h3,.ptitle{display:flex;align-items:center;gap:6px;margin:0 0 8px;font-size:14px;font-weight:650}.ptitle .grow{flex:1 1 auto;min-width:0}
.segs{display:inline-flex;flex-wrap:wrap;gap:2px;padding:2px;border:1px solid var(--rule);border-radius:8px}
.segs button,.segs a{border:0;background:transparent;padding:3px 10px;min-height:30px;border-radius:6px;font-size:13px;color:var(--ink2);cursor:pointer;white-space:nowrap;text-decoration:none;display:inline-flex;align-items:center}
.segs [aria-pressed=true],.segs [aria-current]{background:var(--ink);color:var(--paper)}
.legend-row{display:flex;flex-wrap:wrap;gap:4px 12px;margin:8px 0 0;padding:0;list-style:none;font-size:12.5px;color:var(--ink2)}.legend-row li{display:flex;align-items:center;gap:5px}
.swatch{display:inline-block;flex:none;width:28px;height:8px;border-radius:2px}.sq{display:inline-block;flex:none;width:12px;height:12px;border-radius:3px}
.seg-ok{background:var(--m-ok)}.seg-run{background:linear-gradient(90deg,var(--m-run) 55%,var(--run-bg) 55%)}.seg-wait{background:var(--m-wait)}
.seg-recheck{background:repeating-linear-gradient(45deg,var(--m-wait) 0,var(--m-wait) 2px,var(--wait-bg) 2px,var(--wait-bg) 4px)}
.seg-inconclusive{background:repeating-linear-gradient(90deg,var(--m-wait) 0,var(--m-wait) 3px,var(--wait-bg) 3px,var(--wait-bg) 5px)}
.seg-fail{background:repeating-linear-gradient(45deg,var(--m-fail) 0,var(--m-fail) 2px,var(--fail-bg) 2px,var(--fail-bg) 3px),var(--m-fail)}
.seg-stop{background:var(--m-need)}.seg-pending{box-shadow:inset 0 0 0 1.5px var(--idle)}
.seg-unknown{background:repeating-linear-gradient(90deg,var(--idle) 0,var(--idle) 2px,transparent 2px,transparent 4px)}
.sb-todo{background:var(--idle)}.sb-need{background:var(--m-need)}.sb-doing{background:var(--m-run)}.sb-check{background:var(--m-wait)}.sb-done{background:var(--m-ok)}
.sbar{display:flex;gap:2px;height:14px;margin:0 0 8px}.sb{display:block;min-width:8px;border-radius:2px}
.sb:first-child{border-top-left-radius:4px;border-bottom-left-radius:4px}.sb:last-child{border-top-right-radius:4px;border-bottom-right-radius:4px}
.dtag{display:inline-flex;align-items:center;justify-content:center;min-width:34px;height:24px;padding:0 7px 0 10px;border-radius:6px;color:var(--ink);font-size:13px;font-weight:700;background:var(--sheet);box-shadow:inset 0 0 0 1.5px var(--d),inset 5px 0 0 var(--d);font-style:normal}
.dtag.s{min-width:26px;height:18px;font-size:11.5px;padding:0 5px 0 8px;border-radius:4px;box-shadow:inset 0 0 0 1px var(--d),inset 4px 0 0 var(--d)}
.vhead{display:flex;flex-wrap:wrap;align-items:center;gap:6px 10px;margin:0 0 12px}.vhead h2{margin:0;font-size:20px;font-weight:650;letter-spacing:-.01em}
.src{display:inline-flex;align-items:center;gap:5px;min-width:0;max-width:100%;font-size:12.5px;padding:2px 10px;border-radius:999px;background:var(--sheet);color:var(--ink2);border:1px solid var(--rule);overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.ntile{display:flex;align-items:center;gap:8px;padding:6px 10px;border:1px solid var(--rule);border-radius:8px;background:var(--sheet);min-width:0}
.ntile>.ic{color:var(--ink2)}.ntile b{display:block;font-size:19px;line-height:1.1}.ntile small{display:block;font-size:12px;color:var(--ink2)}
.ntile.bad{border-color:var(--fail)}.ntile.bad>.ic,.ntile.bad b{color:var(--fail)}
.empty-st{display:flex;align-items:flex-start;gap:8px;margin:4px 0;color:var(--ink2);font-size:13.5px}
.info{margin-top:4px;font-size:13px}.info>summary{display:inline-flex;align-items:center;justify-content:center;width:20px;height:20px;border-radius:50%;border:1px solid var(--ink2);color:var(--ink2);font-size:12px;font-weight:700;font-style:italic;font-family:Georgia,serif;cursor:pointer;list-style:none}
.info>summary::-webkit-details-marker{display:none}.info>div{margin-top:6px;padding:8px 10px;border-radius:6px;background:var(--idle-bg);color:var(--ink)}.info p{margin:0 0 4px}
.hidden{display:none!important}
ul.plain,ol.plain{list-style:none;margin:0;padding:0}
@media (max-width:640px){
header.shell{gap:6px;padding:0 12px}
.views{position:fixed;left:0;right:0;bottom:0;z-index:12;height:58px;padding:4px 4px calc(4px + env(safe-area-inset-bottom));border:0;border-top:1px solid var(--rule);border-radius:0;background:var(--sheet);display:grid;grid-template-columns:repeat(4,minmax(0,1fr))}
.views a{flex-direction:column;justify-content:center;gap:2px;padding:2px;font-size:11.5px}.views a .ic{width:20px;height:20px}
.views .lg{display:none}.views .sh{display:inline}
body{padding-bottom:64px}.vhead h2{font-size:18px}
}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
'''

SHELL_JS = r'''
var root=document.documentElement,MODES=['auto','light','dark'],ICON={auto:'auto',light:'sun',dark:'moon'},WORD={auto:'Nền tự động',light:'Nền sáng',dark:'Nền tối'},mode='auto';
  try{mode=window.localStorage.getItem('oc-theme')||'auto'}catch(e){}
  function g(id){return document.getElementById(id)}
  function apply(){if(MODES.indexOf(mode)<0)mode='auto';if(mode==='auto')root.removeAttribute('data-theme');else root.setAttribute('data-theme',mode);
    var b=g('theme');if(!b)return;b.innerHTML='<span class="ic sm" aria-hidden="true"><svg viewBox="0 0 24 24"><use href="#i-'+ICON[mode]+'"/></svg></span>';
    b.setAttribute('title','Đổi nền: '+WORD[mode]+' (bấm để đổi sáng / tối / tự động)');b.setAttribute('aria-label','Đổi nền: '+WORD[mode]+', bấm để đổi')}
  function pop(id,btn,open){var p=g(id),b=g(btn);if(!p||!b)return;p.hidden=!open;b.setAttribute('aria-expanded',open?'true':'false')}
  apply();
  document.addEventListener('click',function(e){var t=e.target;if(!t||!t.closest)return;
    if(t.closest('#theme')){mode=MODES[(MODES.indexOf(mode)+1)%3];try{window.localStorage.setItem('oc-theme',mode)}catch(err){}apply();return}
    if(t.closest('#legend-btn')){pop('limits','limits-btn',false);pop('legend','legend-btn',g('legend').hidden);return}
    if(t.closest('#limits-btn')){pop('legend','legend-btn',false);pop('limits','limits-btn',g('limits').hidden);return}
    if(g('legend')&&!g('legend').hidden&&!t.closest('#legend'))pop('legend','legend-btn',false);
    if(g('limits')&&!g('limits').hidden&&!t.closest('#limits'))pop('limits','limits-btn',false)},true);
  document.addEventListener('keydown',function(e){if(e.key!=='Escape')return;var open=(g('legend')&&!g('legend').hidden)||(g('limits')&&!g('limits').hidden);
    if(open){pop('legend','legend-btn',false);pop('limits','limits-btn',false);e.stopPropagation()}},true);
'''
SHELL_SCRIPT = '(function(){' + SHELL_JS + '})();'      # the server pages; the work page runs SHELL_JS inside its own script


def header_html(current, scope=None, overview_scope=None, extra='', work_href=None, limits_extra=''):
    """The shell's header: brand, the four destinations, `extra` (a status line), the i / ? / theme buttons and their two pop-ups."""
    return (f'<header class="shell"><a class="brand" href="/">OneCrew</a><nav class="views" id="nav" aria-label="Phần của trang">'
            f'{nav_html(current, scope, overview_scope, work_href)}</nav><span class="hsp"></span>{extra}'
            '<button type="button" class="hbtn" id="limits-btn" aria-expanded="false" aria-controls="limits" aria-label="Dữ liệu này không cho thấy gì"'
            ' title="Dữ liệu này không cho thấy gì (giới hạn)">i</button>'
            '<button type="button" class="hbtn" id="legend-btn" aria-expanded="false" aria-controls="legend" aria-label="Chú giải biểu tượng" title="Chú giải biểu tượng">?</button>'
            '<button type="button" class="hbtn" id="theme" aria-label="Đổi nền: tự động, sáng, tối" title="Đổi nền"></button>'
            f'<div id="legend" class="pop" role="dialog" aria-label="Chú giải biểu tượng" hidden>{LEGEND_HTML}</div>'
            f'<div id="limits" class="pop" role="dialog" aria-label="Giới hạn của dữ liệu" hidden>{LIMITS_HTML}{limits_extra}</div></header>')


def document(title, current, body, style='', *, scope=None, overview_scope=None, script='', work_href=None):
    """A whole server-rendered page in the shell (UTF-8 bytes)."""
    return (f'<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{escape(title)} · OneCrew</title><style>{SHELL_STYLE}{style}</style></head><body data-page="{current}">{SPRITE}'
            f'{header_html(current, scope, overview_scope, work_href=work_href)}<main>{body}</main><script data-shell="1">{SHELL_SCRIPT}{script}</script></body></html>').encode('utf-8')


def source_chip(read_at, what='Sổ'):
    """The lock chip of a page: real data on this machine, filtered, read at …; the text sits next to the icon (no inner span)."""
    at = tracking._at(read_at) if isinstance(read_at, str) else read_at
    clock = at.astimezone().strftime('%H:%M %d/%m') if at else 'chưa rõ giờ'
    return (f'<span class="src" title="{escape(what)}: dữ liệu thật trên máy này, đã lọc bí mật, chỉ đọc; đọc lúc {clock}">{icon("lock", "sm")}'
            f'{escape(what)}: dữ liệu thật, đã lọc · {clock}</span>')


# ---- landing page --------------------------------------------------------------------------------------------------------------------

ATTENTION = (('need', 'Bạn cần quyết', 'need', 'need'), ('fix', 'Không đạt', 'cross', 'fail'), ('inconclusive', 'Chưa kết luận', 'hourglass', 'wait'),
             ('recheck', 'Cần kiểm lại', 'refresh', 'wait'), ('idle', 'Lâu không động', 'clock', 'idle'))
SERIES = {'pass': 'Đạt', 'fail': 'Không đạt', 'inconclusive': 'Chưa kết luận'}
GROUPS = (('need', 'Cần bạn'), ('doing', 'Đang làm'), ('check', 'Chờ kiểm'), ('todo', 'Chưa bắt đầu'), ('done', 'Xong'))


def group_of(task):
    """The six chips of the work list (UIMOCK D5): who waits, then the situation stage the model computed."""
    if task.get('needs_user'): return 'need'
    stage = (task.get('situation') or {}).get('stage') or 'unknown'
    if stage in ('done', 'closed'): return 'done'
    if stage in ('check', 'accept'): return 'check'
    if stage == 'todo': return 'todo'
    return 'doing'


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


def repair_rounds(conn, projects, now):
    """Checks in the last 14 days that follow a check of the same milestone (or part) that did not pass: one round of repair each."""
    since = (now.astimezone().date() - dt.timedelta(days=13)).isoformat()
    rounds = 0
    for tasks in projects.values():
        for task in tasks:
            engine = task['tracking']['adapter'] == 'engine'
            kind, key = ('node.verification', '$.node') if engine else ('verdict.recorded', '$.milestone')
            last = {}
            for name, result, day in conn.execute(f"SELECT json_extract(payload,'{key}'), json_extract(payload,'$.result'), date(created_at,'localtime') "
                                                  'FROM events WHERE task_id=? AND kind=? ORDER BY seq', (task['id'], kind)):
                if last.get(name) not in (None, 'pass') and day >= since: rounds += 1
                last[name] = result
    return rounds


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


def href(**filters):
    return '/' + ('?' + urlencode(filters) if filters else '')


def link(label, **filters):
    return f'<a href="{escape(href(**filters))}">{label}</a>'


def summary_bar(tasks, **scope):
    counts = Counter(group_of(t) for t in tasks)
    words = ', '.join(f'{w} {counts[k]}' for k, w in GROUPS)
    cells = ''.join(f'<a class="sb sb-{k}" href="{escape(href(stage="g_" + k if k != "need" else "need", **scope))}" style="flex-grow:{counts[k]}"'
                    f' title="{w}: {counts[k]}" aria-label="{w}: {counts[k]}"></a>' for k, w in GROUPS if counts[k])
    return f'<div class="sbar" role="img" aria-label="{escape(words)}">{cells}</div>'


def projects_html(projects):
    """One card per git repository; its worktrees (the ledger's projects) inside, each with its own counts and links to the list."""
    groups = {}
    for project in projects:
        path = Path(project['path'])
        git = repo_dir(path)
        groups.setdefault(git, []).append(project)
    cards = []
    for git, trees in groups.items():
        name = (git.parent.name if git.name == '.git' else git.name) if git else 'Chưa xác định repo'
        tasks_in_repo = [t for tree in trees for t in tree['tasks']]
        repo_filter = 'repo:' + ','.join(sorted({t['project_id'] for t in tasks_in_repo}))
        need = sum(bool(t.get('needs_user')) for t in tasks_in_repo)
        rows = []
        for tree in trees:
            path, tasks = tree['path'], tree['tasks']
            waiting = sum(bool(t.get('needs_user')) for t in tasks)
            rows.append(f'<li data-wt="{escape(Path(path).name)}">{icon("code", "sm")}' + link(escape(Path(path).name) + f' · {len(tasks)} việc', project=path)
                        + (' · ' + link(f'{waiting} cần bạn', project=path, stage='need') if waiting else '') + '</li>')
        stats = ''.join(f'<li><a href="{escape(href(project=repo_filter, stage=stage))}"><b>{icon(name_, "sm", tone if n else "idle")}{n}</b><span>{word}</span></a></li>'
                        for stage, word, name_, tone, n in (
                            ('g_doing', 'Đang làm', 'play', 'run', sum(group_of(t) == 'doing' for t in tasks_in_repo)),
                            ('fix', 'Cần sửa', 'warn', 'fail', sum(tracking_list._stage_ok(t, 'fix') for t in tasks_in_repo)),
                            ('ended', 'Đã kết thúc', 'ok', 'ok', sum(t.get('root_status') in ('accepted', 'closed') for t in tasks_in_repo))))
        title = f'<a href="{escape(href(project=repo_filter))}" title="{escape(name)}">{icon("box", "sm")}<span>{escape(tracking._guard(name))}</span></a>'
        cards.append(f'<article class="panel ptile" data-repo="{escape(name)}"><div class="phead"><h3>{title}</h3>'
                     f'<a class="pneed{" has-need" if need else ""}" href="{escape(href(project=repo_filter, stage="need"))}" aria-label="Cần bạn: {need}">'
                     f'{icon("need" if need else "ok", "", "need" if need else "ok")}<b>{need}</b><span>cần bạn</span></a></div>'
                     + summary_bar(tasks_in_repo, project=repo_filter)
                     + f'<details class="wts"><summary>{icon("code", "sm")}{len(trees)} thư mục làm việc</summary><ul class="plain minis">{"".join(rows)}</ul></details>'
                     + f'<ul class="pstats">{stats}</ul></article>')
    return ''.join(cards)


def rhythm_html(days, rounds=0, milestones=(0, 0)):
    """The 14-day checks chart (columns with a number axis, day labels and a legend with totals) and the four number tiles on its right."""
    peak = max((sum(counts.values()) for counts in days.values()), default=0)
    totals = Counter()
    for counts in days.values():
        totals.update(counts)
    W, H, L0, R, T, B = 360, 132, 22, 4, 12, 18
    n = len(days) or 1
    slot = (W - L0 - R) / n
    bw = min(14, slot * .7)
    top = peak or 1
    y = lambda v: H - B - v / top * (H - T - B)
    g = [f'<svg class="rchart" viewBox="0 0 {W} {H}" role="img" aria-label="Số lần kiểm mỗi ngày, 14 ngày gần nhất; cao nhất {peak} lần một ngày">',
         f'<line class="grid" x1="{L0}" x2="{W - R}" y1="{y(0):.1f}" y2="{y(0):.1f}"/><line class="grid" x1="{L0}" x2="{W - R}" y1="{y(top):.1f}" y2="{y(top):.1f}"/>',
         f'<text x="{L0 - 4}" y="{y(0) + 3:.1f}" text-anchor="end">0</text><text x="{L0 - 4}" y="{y(top) + 3:.1f}" text-anchor="end">{peak}</text>']
    columns = []
    for i, (day, counts) in enumerate(days.items()):
        x = L0 + i * slot + (slot - bw) / 2
        base = y(0)
        label = day + ' · ' + ', '.join(f'{counts[k]} {word.lower()}' for k, word in SERIES.items())
        bars = ''
        for k in SERIES:
            v = counts[k]
            if not v: continue
            h = v / top * (H - T - B)
            bars += f'<rect class="rc-{k}" x="{x:.1f}" y="{base - h:.1f}" width="{bw:.1f}" height="{max(1, h):.1f}" rx="1.5"/>'
            base -= h
        g.append(f'<g data-day="{day}"><title>{escape(label)}</title><rect x="{L0 + i * slot:.1f}" y="{T}" width="{slot:.1f}" height="{H - T - B}" fill="transparent"/>{bars}</g>')
        if i in (0, n // 2, n - 1):
            g.append(f'<text x="{x + bw / 2:.1f}" y="{H - 5}" text-anchor="middle">{day[8:10]}/{day[5:7]}</text>')
        segments = ''.join(f'<i class="{k}" style="height:{100 * v / (peak or 1):.3f}%"></i>' for k, v in counts.items() if v)
        columns.append(f'<span class="column" role="img" aria-label="{label}" title="{label}">{segments}</span>')
    g.append('</svg>')
    legend = ''.join(f'<li><span class="sq sw-{k}"></span>{label} <b>{totals[k]}</b></li>' for k, label in SERIES.items())
    total = sum(totals.values())
    passed = totals['pass']
    stats = (f'<div class="stat" data-stat="checks"><b>{total}</b><span>lần kiểm</span></div>'
             f'<div class="stat" data-stat="pass"><b>{round(passed * 100 / total) if total else 0}%</b><span>lần kiểm đạt ({passed}/{total})</span></div>'
             f'<div class="stat" data-stat="rounds"><b>{rounds}</b><span>vòng sửa</span></div>'
             f'<div class="stat" data-stat="milestones"><b>{milestones[0]}/{milestones[1]}</b><span>mốc đạt</span></div>')
    return (f'<div class="rhythm"><div class="panel"><small class="mut">Cao nhất {peak} lần/ngày</small>{"".join(g)}'
            f'<ul class="legend-row">{legend}</ul></div><div class="stats">{stats}</div></div>')


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
    return (f'<article class="panel" id="dash-host"><h3>{icon("robot", "sm")}Việc nền hook báo</h3><p class="counts">{icon("play" if states else "question", "sm", "run" if states else "unknown")}'
            f'<span>{signal}</span></p><small class="mut">Host tự báo qua hook</small></article>'
            f'<article class="panel" id="dash-res"><h3>{icon("lock", "sm")}Tài nguyên dùng chung</h3><p class="counts">{icon("lock", "sm", "run" if leases.get("declared") else "unknown")}'
            f'<span>{resources}</span></p></article>')


def chat_summary(state_root, tasks, session_tasks):
    """What the observed Claude sessions say that the ledger does not: AI questions with no owner choice, direction changes with no plan amend
    after them, and writes outside the project. Read from the ledger's hook observations only (never a transcript)."""
    from . import tracking_direction
    out = {'asks': 0, 'drift': 0, 'tasks': {}}
    for task in tasks:
        if not session_tasks.get(task.get('id')): continue
        try:
            _task, events = tracking_direction._records(state_root, task['selector'], task['project_id'])
        except (OSError, ValueError, KeyError, sqlite3.Error, LedgerError):
            continue
        stats = tracking_direction.totals(tracking_direction._entries(events), events)
        out['tasks'][task['id']] = stats
        out['asks'] += stats['open_asks']
        out['drift'] += stats['drift']
    return out


def _latest_observed(state_root, tasks, session_tasks):
    """The task whose observed session moved last, with that session's ledger counts (steps, commands, edits, agents, errors)."""
    from . import tracking_sessions
    best = None
    for task in tasks:
        if not session_tasks.get(task.get('id')): continue
        try:
            view = tracking_sessions.observed(state_root, task['selector'], task['project_id'])
        except (OSError, ValueError, KeyError, sqlite3.Error, LedgerError):
            continue
        if view['rows'] and (best is None or view['last_at'] > best[1]['last_at']):
            best = (task, view)
    return best


def session_cards(state_root, tasks, session_tasks, chat, scope_task):
    """The three cards of "Phiên và hướng đi". Without an observed session each card keeps its frame and says "chưa quan sát"."""
    latest = _latest_observed(state_root, tasks, session_tasks) if session_tasks else None
    task = latest[0] if latest else scope_task
    plan = (task or {}).get('plan') or ''
    query = '?' + urlencode({'plan': task['selector'], 'project_id': task['project_id']}) if task and task.get('selector') and task.get('id') else ''
    scope = chip(f'{len(session_tasks)} việc có phiên' if session_tasks else 'chưa quan sát', None, 'eye')
    if latest:
        view = latest[1]
        s = view['stats']
        doing = (f'<p class="doing">{icon("clock", "sm")}<span>Bước cuối: {escape(view["rows"][-1]["what"])} · {escape(view["rows"][-1]["clock"])}</span></p>')
        steps = ''.join(f'<li><a href="/sessions{escape(query)}"><b>{icon(n, "sm", "wait" if k == "errors" and s[k] else "idle")}{s[k]}</b><span>{w}</span></a></li>'
                        for k, n, w in (('steps', 'steps', 'bước'), ('commands', 'code', 'lệnh'), ('edits', 'pencil', 'sửa'), ('agents', 'robot', 'nhánh agent'), ('errors', 'warn', 'lệnh lỗi')))
        first = f'{doing}<ul class="pstats">{steps}</ul><p class="small mut">Việc {escape(plan)} · {escape(view["range"])}</p>'
        cost = ('<p class="empty-st small">' + icon('bill', 'sm', 'idle') + '<span>Token, model và chi phí đọc từ nhật ký phiên khi bạn mở trang Phiên Claude của việc '
                + escape(plan) + '.</span></p>')
    else:
        first = (f'<p class="empty-st">{icon("eyeoff", "sm", "idle")}<span>Chưa quan sát phiên Claude nào gắn với việc trong sổ này: hook quan sát chưa ghi gì.'
                 ' Không có số bước, lệnh, sửa.</span></p>')
        cost = f'<p class="empty-st">{icon("eyeoff", "sm", "idle")}<span>Chưa có dữ liệu phiên: chưa quan sát nhật ký nào để đọc token, model hay chi phí.</span></p>'
    stats = (chat['tasks'].get(task.get('id')) if task else None) or None
    if stats:
        direction = (f'<ul class="pstats"><li><a href="/direction{escape(query)}"><b>{icon("turn", "sm")}{stats["turns"]}</b><span>lần đổi hướng</span></a></li>'
                     f'<li><a href="/direction{escape(query)}"><b>{icon("flag", "sm", "fail" if stats["drift"] else "idle")}{stats["drift"]}</b><span>vượt hợp đồng</span></a></li>'
                     f'<li><a href="/direction{escape(query)}"><b>{icon("book", "sm")}{stats["ledger"]}</b><span>dấu vết sổ</span></a></li></ul>')
    else:
        direction = f'<p class="empty-st">{icon("eyeoff", "sm", "idle")}<span>Chưa quan sát lời chủ hay câu hỏi của AI cho việc này; sổ chỉ có các bước duyệt và kiểm.</span></p>'
    card = lambda key, name, title, path, body: (f'<article class="panel live" data-live="{key}"><div class="phead"><h3><a href="{path}{escape(query)}">{icon(name, "sm")}'
                                                  f'<span>{escape(title)}</span></a></h3>{scope}</div>{body}</article>')
    return (card('session', 'robot', 'Claude đang làm gì', '/sessions', first) + card('cost', 'coin', 'Token, model, chi phí', '/sessions', cost)
            + card('huong', 'turn', 'Hướng đi ' + plan if plan else 'Hướng đi', '/direction', direction))


STYLE = r'''
main{padding:12px 16px 24px}.dash{max-width:1120px;margin:0 auto}
.dash h3.sec{margin:0 0 8px;font-size:13px;font-weight:600;color:var(--ink2)}.dsec{margin:0 0 16px}
.attn{display:flex;flex-wrap:wrap;gap:8px}
.attn a{display:inline-flex;align-items:center;gap:8px;padding:6px 12px;border:1px solid var(--rule);border-radius:10px;background:var(--sheet);text-decoration:none;font-size:13.5px}
.attn a b{font-size:22px;line-height:1}.attn a.hot{border-color:var(--pen);color:var(--pen)}.attn a.zero{opacity:.62}
.dgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,230px),1fr));gap:10px}.dgrid.wide{grid-template-columns:repeat(auto-fill,minmax(min(100%,300px),1fr))}
.ptile h3 a,.live h3 a{display:flex;align-items:center;gap:6px;color:var(--ink);font-size:14px;text-decoration:none;min-width:0}
.ptile h3 a span:last-child,.live h3 a span:last-child{overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.phead{display:flex;align-items:center;gap:8px;margin:0 0 8px}.phead h3{flex:1 1 auto;min-width:0;margin:0}
.pneed{display:flex;flex:none;align-items:center;gap:5px;font-size:13px;font-weight:600;color:var(--ink2);text-decoration:none}
.pneed b{font-size:24px;line-height:1;color:var(--ink)}.pneed.has-need,.pneed.has-need b{color:var(--pen)}
.ptile .sbar{height:10px}.wts{font-size:13px;color:var(--ink2);margin:2px 0}.wts>summary{display:flex;align-items:center;gap:5px;cursor:pointer;list-style:none}
.wts>summary::-webkit-details-marker{display:none}.minis{display:grid;gap:3px;margin:4px 0}.minis li{display:flex;align-items:center;gap:5px;font-size:12.5px;overflow-wrap:anywhere}
.pstats{list-style:none;margin:6px 0 0;padding:0;display:flex;flex-wrap:wrap;gap:2px 10px}
.pstats a,.pstats span.st{display:flex;align-items:center;gap:4px;padding:2px 4px;border-radius:6px;text-decoration:none;font-size:12.5px;color:var(--ink2)}
.pstats a:hover{background:var(--sel)}.pstats b{display:flex;align-items:center;gap:3px;font-size:15px;color:var(--ink)}
.rhythm{display:grid;grid-template-columns:minmax(0,2fr) minmax(0,1fr);gap:10px}
.rchart{display:block;width:100%;height:auto}.rchart text{fill:var(--ink2);font-size:9px;font-family:inherit}.rchart .grid{stroke:var(--rule);stroke-width:.6}
.rc-pass{fill:var(--m-ok)}.rc-fail{fill:var(--m-fail)}.rc-inconclusive{fill:var(--wait-bg);stroke:var(--m-wait);stroke-width:1.2}
.sw-pass{background:var(--m-ok)}.sw-fail{background:var(--m-fail)}.sw-inconclusive{background:var(--wait-bg);box-shadow:inset 0 0 0 1.5px var(--m-wait)}
.stats{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;align-content:start}
.stat{padding:8px 10px;border:1px solid var(--rule);border-radius:8px;background:var(--sheet)}.stat b{display:block;font-size:22px;line-height:1.2}.stat span{font-size:12.5px;color:var(--ink2)}
.counts{display:flex;flex-wrap:wrap;align-items:center;gap:6px 10px;margin:0 0 6px;font-size:13.5px}
.doing{display:inline-flex;align-items:center;gap:8px;max-width:100%;min-width:0;margin:0 0 6px;padding:5px 12px;border-radius:999px;background:var(--idle-bg);color:var(--ink2);font-size:13.5px;font-weight:600}
.doing span{overflow:hidden;white-space:nowrap;text-overflow:ellipsis;min-width:0}
.owners{list-style:none;margin:8px 0 0;padding:0;display:grid;gap:4px}.owners a{display:inline-flex;align-items:center;gap:6px;text-decoration:none;font-size:13.5px}
.owners a:hover{text-decoration:underline}
@media (max-width:899px){.rhythm{grid-template-columns:minmax(0,1fr)}}
'''


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
    head = f'<div class="vhead"><h2>Tổng quan</h2>{source_chip(value["generated_at"])}<a class="small mut" href="">Đọc lại</a></div>'
    if value['source']['status'] != 'ok':
        body = head + '<p role="status">' + escape(value['source']['detail']) + '</p>'
    else:
        tasks = [t for group in value['projects'] for t in group['tasks']]
        session_tasks = value.get('session_tasks', {})
        chat = chat_summary(state_root, tasks, session_tasks) if session_tasks else {'asks': 0, 'drift': 0, 'tasks': {}}
        latest = max(tasks, key=lambda t: (t.get('last_update') or {}).get('at') or t.get('created_at') or '', default=None)
        some = next((t for t in tasks if session_tasks.get(t.get('id'))), latest)
        task_query = '?' + urlencode({'plan': some['selector'], 'project_id': some['project_id']}) if some and some.get('selector') else ''
        chips = ''
        for key, label, name, tone, count in (('ask', 'Câu hỏi chưa trả lời', 'question', 'need', chat['asks']), ('drift', 'Vượt hợp đồng', 'flag', 'fail', chat['drift'])):
            chips += (f'<a href="/direction{escape(task_query)}" data-chat="{key}" data-count="{count}" class="{"hot" if count else "zero"}"'
                      f' title="{label}, nguồn: phiên Claude đã quan sát">{icon(name, "", tone if count else "idle")}<b>{count}</b><span>{label}</span>{chip("chat")}</a>')
        for stage, label, name, tone in ATTENTION:
            count = sum(tracking_list._stage_ok(t, stage, now) for t in tasks)
            chips += (f'<a href="{escape(href(stage=stage, **list_scope))}" data-attn="{stage}" data-count="{count}" class="{"hot" if count and stage == "need" else "" if count else "zero"}"'
                      f' title="{label} (trong sổ): {count}">{icon(name, "", tone if count else "idle")}<b>{count}</b><span>{label}</span>{chip("sổ")}</a>')
        body = head + f'<section class="dsec" id="dash-attn"><h3 class="sec">Cần chú ý</h3><nav class="attn" aria-label="Cần chú ý">{chips}</nav>'
        owners = [t for t in tasks if t.get('needs_user')]
        if owners:
            body += '<ul class="owners">' + ''.join(f'<li><a href="{escape(href(plan=t["selector"], project_id=t["project_id"]))}">{icon("need", "sm", "need")}'
                                                    f'<span>{escape(t.get("row_title") or t["plan"])}</span></a></li>' for t in owners) + '</ul>'
        unseen = sum((t.get('validity') or {}).get('kind') == 'not_compared' for t in tasks)
        if unseen:
            body += f'<p class="empty-st small">{icon("eye", "sm", "idle")}<span>{unseen} việc chưa so với bản hiện tại. Số cần kiểm lại chỉ gồm việc đã so.</span></p>'
        body += '</section>'
        body += ('<section class="dsec" id="dash-live"><h3 class="sec">Phiên và hướng đi</h3><div class="dgrid wide">'
                 + session_cards(state_root, tasks, session_tasks, chat, latest) + '</div></section>')
        body += ('<section class="dsec" id="dash-projects"><h3 class="sec">Theo repo (worktree bên trong)</h3><div class="dgrid">'
                 + (projects_html(value['projects']) or '<p class="mut">Chưa có việc trong sổ.</p>') + '</div></section>')
        passed = sum(((t.get('situation') or {}).get('milestones') or {}).get('passed') or 0 for t in tasks)
        total = sum(((t.get('situation') or {}).get('milestones') or {}).get('total') or len(t.get('milestones') or []) for t in tasks)
        body += ('<section class="dsec" id="dash-rhythm"><h3 class="sec">Nhịp kiểm 14 ngày</h3>'
                 + rhythm_html(value['check_days'], value.get('repair_rounds', 0), (passed, total)) + '</section>')
        if comparison:
            body += ('<section class="dsec" id="dash-bg"><h3 class="sec">Việc nền và tài nguyên (trong sổ)</h3><div class="dgrid">'
                     + background_html(value['host_work'], value['shared_resources']) + '</div></section>')
        body = f'<div class="dash">{body}</div>'
    return document('Tổng quan', 'overview', body, STYLE, overview_scope=project_id, work_href=href(**list_scope))
