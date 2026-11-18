"""DEV31 on the tracking PAGE: host background work (slice A, #55) and machine leases of shared resources (slice C, #32).

Both exist as CLI (`onecrew track background`, `python -m onecrew.resource_lease status`); this module puts them in the page's JSON
(`/api/overview` -> `host_work`, `shared_resources`) and gives the page the code that draws them. Read-only end to end: it calls
background.view() and Leases.status() only; it opens no output reference, shows no link that runs anything, creates no file or folder
(a missing lease home or managed.json is reported as "chưa khai báo tài nguyên", and Leases() — whose constructor makes its folder — is
not built unless managed.json is there), and copies only named fields of a lease (never a token or its hash). The page escapes every
value with esc(); the server passes the JSON through tracking.outward (the same guard as every other section).
"""
import os
import time
from pathlib import Path

from . import background
from .tracking import clean

MAX_PROJECTS = 25
CACHE_SECONDS = 3.0
_cache = {}

HOST_NOTE = ('Quan sát qua hook của host (Claude Code): host báo, OneCrew chưa kiểm độc lập. Chỉ đọc: OneCrew không bắt đầu, dừng, tạm dừng hay '
             'chạy lại việc nền. Không có dòng nào không có nghĩa là không có việc nền.')
LEASE_NOTE = ('Khóa dùng chung của máy (mọi phiên, plan và sổ). Chỉ đọc: trang không nhận, nhả hay gia hạn khóa. "Đến lúc" chỉ là gợi ý cho người, '
              'không tự nhả; khóa chỉ được nhả khi bên giữ nhả, hoặc khi tiến trình của bên giữ đã chết được xác nhận.')
STATE_LABELS = {'held': 'đang giữ', 'expired_holder_alive': 'quá hạn nhưng tiến trình còn sống: vẫn giữ',
                'held_holder_unknown': 'đang giữ, chưa kiểm được tiến trình', 'expired_holder_unknown': 'quá hạn, chưa kiểm được tiến trình: vẫn giữ',
                'dead_unreleased': 'tiến trình đã chết, chưa nhả (sẽ nhả khi đối chiếu)'}
MODE_LABELS = {'write': 'độc quyền (nặng)', 'read': 'dùng chung (nhẹ)'}
WHO_FIELDS = ('claim', 'mode', 'session', 'plan', 'state_root', 'pid', 'since', 'until', 'process')


# ---- host background work ------------------------------------------------------------------------------------------------------

def _project_paths(overview):
    paths, seen = [], set()
    listed = (overview.get('list') or {}).get('projects') or []
    for entry in list(listed) + list(overview.get('projects') or []):
        path = entry.get('path') if isinstance(entry, dict) else None
        if isinstance(path, str) and path and path.casefold() not in seen:
            seen.add(path.casefold()); paths.append(path)
    return paths


def _view(path):
    """background.view(path) of one project, kept for a few seconds so a page that polls every 2 s does not re-read the file each time."""
    now = time.monotonic()
    hit = _cache.get(path)
    if hit and now - hit[0] < CACHE_SECONDS: return hit[1]
    try:
        value = background.view(Path(path)); value.pop('generated_at', None)
        out = {'path': path, 'view': value, 'error': None}
    except Exception as error:                      # one unreadable project must not take the page's other sections down
        out = {'path': path, 'view': None, 'error': clean(f'{type(error).__name__}: {error}', 200)}
    if len(_cache) > 200: _cache.clear()
    _cache[path] = (now, out)
    return out


def host_work(overview):
    paths = _project_paths(overview)
    return {'kind': 'onecrew-page-host-work', 'read_only': True, 'note': HOST_NOTE, 'source': background.SOURCE, 'trust': background.TRUST,
            'projects': [_view(p) for p in paths[:MAX_PROJECTS]], 'projects_not_read': max(0, len(paths) - MAX_PROJECTS)}


# ---- machine leases --------------------------------------------------------------------------------------------------------------

def _lease_home():
    configured = os.environ.get('ONECREW_LEASE_HOME')
    return Path(configured) if configured else Path.home() / '.onecrew' / 'leases'


def _who(row, **more):
    out = {k: row.get(k) for k in WHO_FIELDS}
    out.update(more)
    return out


def shared_resources():
    """Every declared resource: free or held, holders (plan, session, state root, since, until, state) and waiters with position.
    Nothing is created: without a lease home with managed.json this answers "chưa khai báo" and stops."""
    base = _lease_home()
    out = {'kind': 'onecrew-page-resources', 'read_only': True, 'note': LEASE_NOTE, 'home': str(base), 'declared': False, 'resources': [], 'error': None}
    try:
        if not (base / 'managed.json').is_file():
            out['empty_note'] = 'chưa khai báo tài nguyên dùng chung nào trên máy này (không có managed.json); trang không tạo gì'
            return out
        from ..resource_lease import Leases
        leases = Leases(base)                       # the folder exists (managed.json is in it): the constructor creates nothing
        status = leases.status()
        declared = list(status.get('managed') or [])
        known = {r['resource']: r for r in status.get('resources', [])}
        out['declared'] = bool(declared)
        for name in sorted(set(declared) | set(known)):
            row = known.get(name) or {'resource': name, 'free': True, 'holders': [], 'waiters': []}
            out['resources'].append({
                'resource': clean(name, 120), 'declared': name in declared, 'free': bool(row['free']),
                'state_label': 'trống' if row['free'] else 'đang được giữ',
                'holders': [_who(h, state=h.get('state'), state_label=STATE_LABELS.get(h.get('state'), h.get('state')),
                                 mode_label=MODE_LABELS.get(h.get('mode'), h.get('mode'))) for h in row['holders']],
                'waiters': [_who(w, position=w.get('position'), mode_label=MODE_LABELS.get(w.get('mode'), w.get('mode'))) for w in row['waiters']]})
        if not declared: out['empty_note'] = 'chưa khai báo tài nguyên dùng chung nào (managed.json rỗng)'
    except Exception as error:                      # an unreadable store is shown as such, never as "free"
        out['error'] = clean(f'{type(error).__name__}: {error}', 300)
    return out


def attach(overview):
    """Add `host_work` and `shared_resources` to an overview/list-page model of the server (in place) and return it."""
    overview['host_work'] = host_work(overview)
    overview['shared_resources'] = shared_resources()
    return overview


# ---- the page ----------------------------------------------------------------------------------------------------------------------

STYLE = r'''
.hostbox{margin:14px 0;border:1px solid var(--line);border-radius:10px;background:var(--card);padding:10px 14px}.hostbox>summary{font-weight:650;cursor:pointer}
.hostbox .host-note{font-size:13px;color:var(--mut);margin:6px 0;overflow-wrap:anywhere}.host-proj{margin:10px 0;overflow-wrap:anywhere}.host-proj>h4,.host-plan>h5{margin:10px 0 4px;font-size:14px}
.host-item,.res-item{border-top:1px solid var(--line);padding:8px 0;min-width:0;overflow-wrap:anywhere}.host-item h4,.res-item h4{font-size:14px;margin:0 0 4px}.host-item p,.res-item p{margin:3px 0;font-size:13.5px}
.host-state{display:inline-block;padding:1px 9px;border-radius:10px;font-size:12px;font-weight:650;border:1px solid var(--line)}.host-state.running{border-color:var(--run);color:var(--run)}
.host-state.waiting{border-color:var(--wait);color:var(--wait)}.host-state.finished{border-color:var(--acc);color:var(--acc)}.host-state.unknown{border-color:#5b4a86;color:#5b4a86;border-style:dashed}
.host-out{color:var(--wait);font-weight:600}.res-free{color:var(--acc);font-weight:650}.res-held{color:var(--wait);font-weight:650}.res-row{margin:3px 0 3px 12px;font-size:13.5px}
.hostplan{margin:12px 0;border:1px solid var(--line);border-radius:10px;background:var(--card);padding:10px 14px}.hostplan h3{margin:0 0 6px;font-size:15px}
'''

SCRIPT = r'''
// DEV31 (tracking_host_web): host background work and machine leases. Display only: reads last.host_work / last.shared_resources, escapes every value.
function hostPlanKey(p){return String(p==null?'':p).replace(/^plan(-ns)?:/,'')}
function hostProjects(path){var hw=(last&&last.host_work)||{},ps=hw.projects||[];return path?ps.filter(function(x){return x.path===path}):ps}
function hostItemHtml(i){var o=i.onecrew||{},h=i.host||{},bound=o.bound;
  return '<article class="host-item" data-host-state="'+esc(i.state)+'" data-host-kind="'+esc(i.kind)+'">'
    +'<h4><span class="host-state '+esc(i.state)+'">'+esc(i.state_label)+'</span> '+(i.kind==='subagent'?'Subagent':'Lệnh shell nền')+(h.agent_type?' ('+esc(h.agent_type)+')':'')+' <code>'+esc(h.agent_id||h.tool_use_id||'?')+'</code>'+(i.summary?' — '+esc(i.summary):'')+'</h4>'
    +'<p><b>Thuộc:</b> '+(bound?'kế hoạch '+esc(o.plan)+' bản '+esc(o.revision):'<span class="host-out">ngoài hợp đồng</span>')+' · phiên host '+esc(h.session_id||'chưa rõ')+' · attempt: chưa rõ</p>'
    +'<p><b>Vì sao:</b> '+esc(i.state_reason)+'</p>'
    +'<p><b>Kết quả:</b> '+esc(i.outcome_label)+'</p>'
    +'<p><b>Nguồn:</b> '+esc(i.source)+' · host báo, chưa kiểm độc lập ('+esc(i.trust)+')</p>'
    +'<p><b>Bắt đầu:</b> '+(i.started_at?when(i.started_at):'chưa quan sát')+' · <b>quan sát gần nhất:</b> '+when(i.last_observed)+(i.finished_at?' · <b>kết thúc:</b> '+when(i.finished_at):'')+'</p>'
    +'<p><b>Output:</b> '+(i.output_ref?'<code>'+esc(i.output_ref)+'</code> <span class="mut">(chỉ là chữ host báo, trang không mở)</span>':'không có tham chiếu')+'</p>'
    +'<p><b>Bước tiếp:</b> '+esc(i.next_step)+'</p>'
    +(i.notes||[]).map(function(n){return '<p class="work-meta">Lưu ý: '+esc(n)+'</p>'}).join('')+'</article>'}
function hostViewHtml(v,onlyPlan){var items=v.items||[];if(onlyPlan!=null)items=items.filter(function(i){return hostPlanKey((i.onecrew||{}).plan)===hostPlanKey(onlyPlan)&&(i.onecrew||{}).bound});
  var c=v.counts||{},head='<p class="work-meta">'+['running','waiting','finished','unknown'].map(function(s){return ({running:'đang chạy',waiting:'đang chờ',finished:'đã kết thúc',unknown:'chưa rõ'})[s]+' '+(onlyPlan!=null?items.filter(function(i){return i.state===s}).length:(c[s]||0))}).join(' · ')+'</p>';
  var groups={},order=[];items.forEach(function(i){var k=(i.onecrew||{}).bound?'plan:'+i.onecrew.plan:'out';if(!groups[k]){groups[k]=[];order.push(k)}groups[k].push(i)});
  var body=order.map(function(k){return '<div class="host-plan"><h5>'+(k==='out'?'Ngoài hợp đồng (không gắn kế hoạch nào)':'Kế hoạch '+esc(k.slice(5)))+' ('+groups[k].length+')</h5>'+groups[k].map(hostItemHtml).join('')+'</div>'}).join('');
  if(!items.length)body='<p class="work-empty">'+(onlyPlan!=null?'Chưa quan sát việc nền nào gắn với kế hoạch này (không có nghĩa là không có).':'Chưa quan sát việc nền nào (không có nghĩa là không có).')+'</p>';
  var done=items.length&&onlyPlan==null?'<p class="work-meta">Mọi việc đã quan sát đều kết thúc: '+(v.all_observed_finished?'có':'chưa')+'. Lượt của phiên mẹ kết thúc không làm việc con kết thúc.</p>':'';
  var un=(v.unobserved||[]).length?'<details class="work-meta"><summary>OneCrew chưa quan sát ('+v.unobserved.length+')</summary><ul>'+v.unobserved.map(function(x){return '<li>'+esc(x)+'</li>'}).join('')+'</ul></details>':'';
  return head+done+body+un}
function hostSectionHtml(path){var hw=(last&&last.host_work)||null;if(!hw)return '<p class="work-empty">Chưa đọc được việc nền.</p>';
  var ps=hostProjects(path),h='<p class="host-note">'+esc(hw.note||'')+'</p>';
  if(!ps.length)h+='<p class="work-empty">Chưa có project nào để đọc việc nền (không có nghĩa là không có).</p>';
  ps.forEach(function(p){h+='<div class="host-proj" data-host-project="'+esc(p.path)+'"><h4 title="'+esc(p.path)+'">'+esc(short(p.path))+'</h4>'+(p.error?'<p class="err">Không đọc được việc nền của project này: '+esc(p.error)+'. Không coi là không có.</p>':hostViewHtml(p.view||{}))+'</div>'});
  if(hw.projects_not_read)h+='<p class="work-meta">'+esc(hw.projects_not_read)+' project nữa chưa đọc (giới hạn). Lọc theo Dự án để xem.</p>';
  return h}
function hostPlanPanel(d){var hw=(last&&last.host_work)||null,rs=(last&&last.shared_resources)||null,h='';
  if(hw){var p=hostProjects(d.project)[0];h+='<section class="hostplan" id="hostplan" data-k="hostplan" aria-label="Việc nền của host"><h3>Việc nền của host gắn với việc này</h3>'
    +(!p?'<p class="work-empty">Chưa đọc được việc nền của project này.</p>':p.error?'<p class="err">Không đọc được: '+esc(p.error)+'</p>':hostViewHtml(p.view||{},d.plan))+'</section>'}
  if(rs&&(rs.resources||[]).length){var mine=rs.resources.filter(function(r){return (r.holders||[]).concat(r.waiters||[]).some(function(x){return x.plan&&hostPlanKey(x.plan)===hostPlanKey(d.plan)})});
    if(mine.length)h+='<section class="hostplan" id="resplan" aria-label="Tài nguyên dùng chung"><h3>Tài nguyên dùng chung mà việc này giữ hoặc chờ</h3>'+mine.map(resItemHtml).join('')+'</section>'}
  return h}
function resRow(x,waiter){return '<div class="res-row" data-res-role="'+(waiter?'waiter':'holder')+'">'+(waiter?'Chờ, vị trí <b>'+esc(x.position)+'</b>: ':'Giữ: ')+'kế hoạch '+esc(x.plan||'chưa rõ')+' · phiên '+esc(x.session||'chưa rõ')+' · sổ '+esc(x.state_root||'chưa rõ')+' · pid '+esc(x.pid==null?'chưa rõ':x.pid)+' · '+esc(x.mode_label||x.mode)
    +' · '+(waiter?'xin từ ':'từ ')+when(x.since)+(x.until?' · đến '+when(x.until):'')+(waiter?' · tiến trình: '+esc(x.process||'chưa rõ'):' · <b>'+esc(x.state_label||x.state||'chưa rõ')+'</b>')+'</div>'}
function resItemHtml(r){return '<article class="res-item" data-resource="'+esc(r.resource)+'" data-free="'+(r.free?'true':'false')+'"><h4><code>'+esc(r.resource)+'</code> · <span class="'+(r.free?'res-free':'res-held')+'">'+esc(r.state_label)+'</span>'+(r.declared===false?' <span class="mut">(không còn trong danh sách khai báo)</span>':'')+'</h4>'
  +(r.holders||[]).map(function(x){return resRow(x,false)}).join('')+(r.waiters||[]).map(function(x){return resRow(x,true)}).join('')
  +(r.free&&!(r.waiters||[]).length?'<p class="work-meta">Không ai giữ, không ai chờ.</p>':'')+'</article>'}
function resSectionHtml(){var rs=(last&&last.shared_resources)||null;if(!rs)return '<p class="work-empty">Chưa đọc được tài nguyên dùng chung.</p>';
  var h='<p class="host-note">'+esc(rs.note||'')+'</p>';
  if(rs.error)return h+'<p class="err">Không đọc được kho khóa: '+esc(rs.error)+'. Không coi là trống.</p>';
  if(!(rs.resources||[]).length)return h+'<p class="work-empty">'+esc(rs.empty_note||'chưa khai báo tài nguyên')+'</p>';
  return h+rs.resources.map(resItemHtml).join('')}
var hostSig=null;
function paintHost(){if(!last)return;var path=$('#proj').value||'',hw=last.host_work||{},rs=last.shared_resources||{},sig=JSON.stringify([path,hw.projects,hw.projects_not_read,rs.resources,rs.error,rs.empty_note]);if(sig===hostSig)return;hostSig=sig;
  var a=$('#hostwork'),b=$('#resources');if(a)a.innerHTML=hostSectionHtml(path);if(b)b.innerHTML=resSectionHtml();
  var c=hw.projects?hw.projects.reduce(function(n,p){return n+((p.view&&p.view.items)||[]).length},0):0,sa=$('#hostbox'),sb=$('#resbox');
  if(sa)sa.querySelector('summary').textContent='Việc nền của host ('+c+')';if(sb)sb.querySelector('summary').textContent='Tài nguyên dùng chung ('+((rs.resources||[]).length)+')'}
'''

HTML = ('<details class="hostbox" id="hostbox" data-k="hostwork" open><summary>Việc nền của host</summary><div id="hostwork" class="small">Đang đọc…</div></details>\n'
        '<details class="hostbox" id="resbox" data-k="resources" open><summary>Tài nguyên dùng chung</summary><div id="resources" class="small">Đang đọc…</div></details>')
