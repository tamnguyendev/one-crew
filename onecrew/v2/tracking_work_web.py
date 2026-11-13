"""Small read-only work views. Uses the tracking page's escaping/evidence door."""

STYLE = r'''
body{font-size:15px;line-height:1.5}header{padding:12px 20px}h1{font-size:19px}
.tools{gap:10px;margin-top:10px;align-items:center}.tools label{font-size:13px}
.tools .search{flex:1 1 280px;max-width:520px}.tools .search input{width:100%;min-height:38px;font-size:15px}
#viewsw{display:inline-flex;border:1px solid var(--line);border-radius:8px;overflow:hidden;flex:none}#viewsw button{border:0;border-radius:0;padding:6px 14px;min-height:38px;font-weight:600;color:var(--mut)}
#viewsw button[aria-pressed=true]{background:var(--sel);color:var(--run)}#viewsw button+button{border-left:1px solid var(--line)}
#filters{margin:0}#filters>summary{display:inline-flex;align-items:center;gap:6px;min-height:38px;padding:6px 12px;border:1px solid var(--line);border-radius:8px;color:var(--fg);font-weight:600;list-style:none}
#filters>summary::-webkit-details-marker{display:none}#filters>summary::after{content:'▾';font-size:11px;color:var(--mut)}#filters[open]>summary::after{content:'▴'}
#filters .fbody{display:flex;gap:10px 14px;flex-wrap:wrap;margin-top:8px;align-items:center}#filters select{min-height:36px;width:auto;max-width:280px}.tools{flex-wrap:wrap}body[data-view=detail] header .tools,body[data-view=detail] #factive{display:none}#filters[open]{flex-basis:100%}li.task .c-last .mut{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
#factive{display:flex;gap:6px 10px;flex-wrap:wrap;align-items:center;font-size:13px;margin-top:8px}#factive[hidden]{display:none}#factive b{font-weight:600}
#factive button{font-size:12.5px;padding:3px 10px;border-radius:12px}
#chips{margin-top:0}#chips button{min-height:32px;padding:3px 10px}
main,main[data-view=list],main[data-view=detail]{display:block;padding:14px 20px}main[data-view=list] #detailpane{display:none}main[data-view=detail] #listpane{display:none}
#listpane{background:transparent;border:0;padding:0}#listpane>h2{font-size:15px;text-transform:none;letter-spacing:0;margin:0 0 4px;color:var(--fg)}
.stage-note{font-size:13px;color:var(--mut);margin:0 0 10px}
#detailpane{position:static;max-height:none;overflow:visible;padding:18px 22px;max-width:1240px;margin:0 auto}
.stg .g{margin-right:4px;font-size:11px}.stg{display:inline-block;padding:2px 10px;border-radius:11px;font-size:12.5px;font-weight:650;white-space:nowrap;color:#fff;border:1px solid transparent;line-height:1.5;vertical-align:baseline}
.stg.todo{background:var(--card);color:var(--fg);border-color:var(--mut)}.stg.doing{background:var(--run)}.stg.check{background:var(--ver)}.stg.fix{background:var(--blk)}
.stg.accept{background:var(--wait)}.stg.done{background:var(--acc)}.stg.stopped{background:#7a1f1f}.stg.closed{background:var(--card);color:var(--mut);border-color:var(--line)}.stg.unknown{background:#5b4a86}
.needb{display:inline-block;background:var(--need);color:var(--needfg);padding:1px 8px;border-radius:10px;font-size:12px;font-weight:650;margin-right:4px}
li.task{cursor:pointer;overflow-wrap:anywhere}li.task .ttl{display:block;font-weight:650;font-size:15px;line-height:1.4;white-space:normal;overflow:visible}
li.task .sub{display:block;font-size:12.5px;color:var(--mut);margin-top:2px}li.task .why,li.task .who{display:block;font-size:13px;color:var(--mut);margin-top:3px}
li.task .nx{font-size:14px}li.task .c-res,li.task .c-last{font-size:13px}li.task .lbl{color:var(--mut)}
li.task[aria-selected=true]{background:var(--sel);border-left-color:var(--run)}li.task.last{border-left-color:var(--mut)}
#list[data-mode=list]{--cols:minmax(0,2.3fr) minmax(0,1.6fr) minmax(0,1.9fr) minmax(0,1.1fr) minmax(0,1.2fr)}
#list[data-mode=list] .lhead{display:grid;grid-template-columns:var(--cols);gap:14px;padding:6px 14px 6px 18px;font-size:12px;color:var(--mut);text-transform:uppercase;letter-spacing:.04em}
.lrows{list-style:none;margin:0;padding:0;border:1px solid var(--line);border-radius:10px;background:var(--card);overflow:hidden}
.lrows li.task{display:grid;grid-template-columns:var(--cols);gap:14px;padding:12px 14px;border-top:1px solid var(--line);border-left:4px solid transparent;margin:0}
.lrows li.task:first-child{border-top:0}.lrows li.task .lbl,.lrows li.task .c-desc{display:none}li.task .c-desc{display:block;font-size:13px;margin-top:4px}.lrows li.task:hover{background:rgba(120,140,180,.07)}
.board{display:flex;gap:12px;overflow-x:auto;align-items:flex-start;padding:2px 0 12px}
.board-lane{flex:1 0 230px;min-width:0;background:var(--bg);border:1px solid var(--line);border-radius:12px;padding:10px}.board-lane.attn{border-color:#5b4a86;border-width:2px}
.lane-title{display:flex;justify-content:space-between;align-items:center;font-size:14px;margin:0 0 10px}.lane-title span{font-size:12px;color:var(--mut)}
.board-lane ul,.closed-fold ul{list-style:none;padding:0;margin:0}.lane-empty{font-size:13px;color:var(--mut);padding:8px 0}
.board li.task,.closed-fold li.task{display:block;border:1px solid var(--line);border-left:4px solid transparent;border-radius:10px;background:var(--card);padding:12px;margin:0 0 10px}
.board li.task>div+div,.closed-fold li.task>div+div{margin-top:7px}.board li.task .c-state .why{margin-top:4px}
.closed-fold{margin-top:6px;border:1px dashed var(--line);border-radius:10px;padding:6px 12px}.closed-fold>summary{font-weight:600;color:var(--mut)}
.closed-fold ul{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:10px;margin-top:8px}.closed-fold li.task{margin:0}
.crumbs{display:flex;flex-wrap:wrap;gap:4px 8px;align-items:center;font-size:13px;color:var(--mut);margin-bottom:8px}.crumbs .sep{color:var(--line)}.crumbs .here{color:var(--fg);font-weight:600;overflow-wrap:anywhere}
#back{display:inline-flex;align-items:center;gap:4px;min-height:36px;font-weight:600;color:var(--run);border-color:var(--line)}
.dhead{display:flex;gap:10px;align-items:flex-start;flex-wrap:nowrap}.dhead h2{flex:1;min-width:0;font-size:21px;line-height:1.35;margin:0;color:var(--fg);text-transform:none;letter-spacing:0;overflow-wrap:anywhere}
.dhead h2 .stg{font-size:13px;margin-left:6px;vertical-align:middle}#close{min-height:36px;flex:none}.work-id{font-size:14px;font-weight:500;color:var(--mut)}
.sit{border:1px solid var(--line);border-radius:12px;background:var(--card);margin:12px 0;padding:14px 16px}
.sit-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,190px),1fr));gap:12px 18px}
.sit-grid>div{min-width:0;display:grid;gap:4px;align-content:start;overflow-wrap:anywhere}.sit-grid b{font-size:12px;color:var(--mut);text-transform:uppercase;letter-spacing:.05em}
.sit-grid span{font-size:15px}.sit-grid small{display:block;font-size:13px;color:var(--mut)}.sit-count{font-weight:600;margin-left:4px}
.sit-need{background:var(--need);color:var(--needfg);border-radius:8px;padding:6px 8px}.sit-need b{color:var(--needfg)}.sit-need a{color:var(--needfg);font-weight:650}
.sit-foot{display:flex;flex-wrap:wrap;gap:4px 18px;margin:12px 0 0;padding-top:10px;border-top:1px solid var(--line);font-size:13px}.sit-foot .live{color:var(--run);font-weight:600}.sit-foot .idle{color:var(--fg)}
button.linkish{border:0;background:none;padding:0 2px;color:var(--run);text-decoration:underline;font-size:13.5px;min-height:0}
.ms-strip{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:12px 0}
.ms{display:inline-block;font-size:12.5px;padding:2px 8px;border-radius:8px;border:1px solid var(--line);background:var(--card);white-space:nowrap}
.ms.passed{border-color:var(--acc);color:var(--acc)}.ms.failed{border-color:var(--blk);color:var(--blk);font-weight:650}.ms.recheck{border-color:var(--wait);color:var(--wait)}.ms.checking{border-color:var(--run);color:var(--run)}.ms.pending{color:var(--mut);border-style:dashed}.ms.stopped{border-color:#7a1f1f;color:#7a1f1f}
.mslist{list-style:none;margin:8px 0 16px;padding:0;border:1px solid var(--line);border-radius:10px;overflow:hidden}
.msitem{display:grid;grid-template-columns:minmax(0,2.4fr) minmax(0,1fr) minmax(0,1.1fr) minmax(0,1.8fr) minmax(0,1.3fr);gap:6px 14px;padding:10px 14px;border-top:1px solid var(--line);align-items:baseline;overflow-wrap:anywhere}
.msitem:first-child{border-top:0}.msitem.failed{border-left:4px solid var(--blk)}.msitem .ms-note,.msitem .ms-detail{grid-column:1/-1;font-size:13px;color:var(--mut);margin:0}.msitem .ms-detail ol{margin:4px 0;padding-left:20px}
.ms-head h3{font-size:16px;margin:12px 0 2px;overflow-wrap:anywhere}
.gbody.msbody{grid-template-columns:260px minmax(0,1fr)}.grow.msrow{height:58px}.gtree .grow.msrow{display:grid;align-content:center;gap:2px;font-size:13px;padding:4px 8px;line-height:1.3}.gtree .msrow strong{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;font-weight:600}
.gtree .msrow span{font-size:12px;color:var(--mut)}.seg.chk{top:18px;height:16px}.seg.chk.pass{background:var(--acc)}.seg.chk.fail{background:var(--blk)}.seg.chk.lost{background:repeating-linear-gradient(45deg,#9aa4b2 0 3px,transparent 3px 6px);border:1px solid var(--mut)}.seg.chk.open{background:var(--run)}
.msrow .mk{top:16px}.msrow .mk.pass{color:var(--acc)}.msrow .mk.fail{color:var(--blk)}.msnone{position:absolute;left:8px;top:16px;font-size:12px;color:var(--mut)}
.work-nav{display:flex;gap:4px;flex-wrap:wrap;margin:16px 0 10px;border-bottom:1px solid var(--line);padding-bottom:0}
.work-nav button{padding:8px 14px;min-height:40px;border:0;border-bottom:3px solid transparent;border-radius:0;font-weight:600;font-size:14px;color:var(--mut);background:none}
.work-nav button[aria-selected=true]{color:var(--run);border-bottom-color:var(--run)}
.work-panel{min-width:0;margin:8px 0 16px}.work-panel h3{font-size:16px;margin:16px 0 8px}
.work-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,260px),1fr));gap:12px}
.work-card{padding:14px;border:1px solid var(--line);border-radius:10px;min-width:0;overflow-wrap:anywhere;background:var(--card)}
.work-card .eyebrow{font-size:12px;color:var(--mut);margin-bottom:6px}.work-card .answer{font-size:15px;font-weight:600}
.work-card p{margin:6px 0}.work-row{padding:12px 0;border-top:1px solid var(--line);overflow-wrap:anywhere}
.work-row:first-child{border-top:0}.work-row h4{font-size:16px;margin-bottom:4px}.work-row ul{padding-left:20px}.work-row details{margin:10px 0}
.work-empty{padding:14px;background:var(--bg);border-radius:8px;color:var(--mut);border:1px solid var(--line)}
.work-meta{font-size:13px;color:var(--mut);margin:6px 0}.work-diff{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:8px}
.work-diff>div{padding:8px;background:var(--bg);border-radius:6px;white-space:pre-wrap;overflow-wrap:anywhere}
.work-panel table td{white-space:normal;overflow-wrap:anywhere}.work-panel table{table-layout:fixed;width:100%}
.work-panel pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:40vh;overflow:auto;padding:12px;background:var(--bg);border-radius:6px}
.connection-details{font-size:12px;color:var(--mut);margin-top:8px}.connection-details summary{cursor:pointer}.connection-details .note{margin:8px 0}.sample-banner{padding:8px 12px;background:var(--sel);border-radius:6px;margin-top:10px;font-size:13px}
.need{padding:14px 16px;border:1px solid var(--line);border-radius:10px}details.need:not([open]){padding:5px 12px;margin:4px 0}details.need:not([open])>summary{line-height:1.5}.need .q{font-size:16px}.command-box{margin:14px 0;background:var(--bg);border:1px solid var(--line);border-radius:8px;overflow:hidden}
.command-head{padding:8px 12px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--line);gap:8px;font-size:13px;flex-wrap:wrap}.command-box pre{margin:0;padding:14px;overflow-x:auto;white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.65 Consolas,monospace}.command-box .copy{white-space:nowrap;min-height:36px}.command-box code{background:transparent;padding:0;font:inherit;color:var(--fg)}
.repair-flow{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.repair-flow>div{border:1px solid var(--line);border-radius:8px;padding:12px;overflow-wrap:anywhere}.repair-flow b{display:block;margin-bottom:8px}
#legacy-progress[hidden]{display:none}.work-warning{border-left:3px solid var(--wait);padding:8px 12px;background:var(--need);color:var(--needfg)}
.gnselect strong{-webkit-line-clamp:3}
@media(max-width:760px){.stage-note{display:none}header{padding:10px 12px}h1{font-size:17px}main,main[data-view=list],main[data-view=detail]{padding:10px 12px}#detailpane{padding:12px}
  .tools{gap:8px}.tools .search{flex:1 1 100%;max-width:none}#filters .fbody{flex-direction:column;align-items:stretch}#filters .fbody label{justify-content:space-between}
  #list[data-mode=list] .lhead{display:none}.lrows li.task{display:block;padding:12px}.lrows li.task>div+div{margin-top:6px}.lrows li.task .lbl{display:inline}
  .board{display:block}.board-lane{margin:0 0 12px}.board-lane.empty{display:none}.closed-fold ul{grid-template-columns:1fr}
  .dhead h2{font-size:18px}.sit{padding:12px}.sit-grid{grid-template-columns:1fr;gap:10px}
  .msitem{grid-template-columns:minmax(0,1fr) auto}.msitem .ms-name{grid-column:1/2}.msitem .ms-checks,.msitem .ms-last,.msitem .ms-time{grid-column:1/-1;font-size:13px;color:var(--mut)}
  .gbody.msbody{grid-template-columns:150px minmax(320px,1fr);min-width:480px}.repair-flow,.work-diff{grid-template-columns:1fr}
  .work-nav button{padding:8px 10px;font-size:13.5px}input,select,button{min-height:38px}button.linkish{min-height:32px}}
'''

SCRIPT = r'''
var workTab='overview';
var WORK_TABS=[['overview','Tổng quan'],['solution','Solution'],['changes','Thay đổi'],['results','Kết quả & kiểm chứng'],['progress','Tiến độ']];
// UX 13/11: the stage comes from the model (tracking_situation.situation); the page renders it and derives none of its own.
var STAGE_ORDER=['todo','doing','fix','check','accept','done'];
var BOARD_LANES=[['attn','Cần chú ý',['stopped','unknown']],['todo','Chưa bắt đầu'],['doing','Đang thực hiện'],['fix','Cần sửa'],['check','Chờ kiểm'],['accept','Chờ nghiệm thu'],['done','Hoàn tất']];
var STAGE_FILTERS=[['todo','Chưa bắt đầu'],['doing','Đang thực hiện'],['fix','Cần sửa'],['check','Chờ kiểm'],['accept','Chờ nghiệm thu'],['done','Hoàn tất'],['stopped','Đã dừng'],['unknown','Chưa xác định'],['closed','Đã đóng']];
function sit(t){return (t&&t.situation)||{stage:'unknown',label:'Chưa xác định',reason:(t&&t.status&&t.status.reason)||'Không đọc được trạng thái',activity:{running:false,text:'Không đọc được hoạt động'}}}
function workStage(t){return sit(t).stage||'unknown'}
function workStatus(t){return sit(t).label||'Chưa xác định'}
function ownerView(t){var o=t&&t.owner_view;return o&&o.present&&o.request?o:null}
function workTitle(t){var o=ownerView(t);return o?o.request:(t.headline||t.goal||t.title||t.plan||'Công việc chưa có tên')}   // dev11 owner part first; mep6: then the contract title
function ownerJoin(a){return (a||[]).map(function(x,i){return x+(i<a.length-1&&!/[.!?…:;]$/.test(x)?';':'')}).join(' ')}
function workDesc(t){var o=ownerView(t),s=o?ownerJoin(o.user_sees):'';return s?'Xong bạn thấy: '+s:''}
function workSearch(t){var o=ownerView(t)||{};   // dev12 (review F7): the words the card shows are searchable, with the technical ones as before
  return [t.plan,t.headline,t.goal,t.title,t.current_step,o.request,(o.user_sees||[]).join(' '),(o.acceptance_steps||[]).join(' '),o.not_doing].filter(Boolean).join(' ').toLowerCase()}
function workWaiting(t){var n=(t.needs_user||[]).filter(function(x){return x.owner_ask})[0];return n?'Đang chờ bạn: '+n.owner_ask:''}
function workNoOwner(t){return ownerView(t)?'':'chưa có mô tả cho chủ'}
function workTech(d){return '<details data-k="owner-tech" class="work-meta"><summary>chi tiết kỹ thuật</summary><p>Plan '+esc(d.plan)+(d.id?' · mã task '+esc(d.id):'')+'</p>'+(d.goal?'<p>Mục tiêu kỹ thuật: '+esc(d.goal)+'</p>':'')+'</details>'}
function workOwnerSection(d){var o=ownerView(d);if(!o)return '<p class="small mut owner-missing">Chưa có mô tả cho chủ: thẻ hiện tiêu đề của hợp đồng, nếu không có thì mục tiêu kỹ thuật do AI viết.</p>'+(d.goal&&!d.work?'<p style="margin:6px 0">'+esc(d.goal)+'</p>':'');
  var card=function(label,v){var items=Array.isArray(v)?v:[v];return '<div class="work-card"><div class="eyebrow">'+esc(label)+'</div><div class="answer">'+(items.filter(Boolean).length?items.filter(Boolean).map(function(x){return '<div>'+esc(x)+'</div>'}).join(''):'chưa có dữ liệu')+'</div></div>'};
  return '<div class="work-grid owner-view">'+card('Việc này làm gì',o.request)+card('Xong bạn thấy gì',o.user_sees)+card('Làm sao biết đạt',o.acceptance_steps)+card('Không làm gì',o.not_doing)+'</div>'+workTech(d)}
function nextMilestone(t){var m=(t.milestones||[]).find(function(m){return m.state!=='passed'});return m?m.id+(m.title?' — '+m.title:''):''}   // mep6: shown in the detail
var STAGE_GLYPH={todo:'○',doing:'▶',check:'◔',fix:'✕',accept:'✓',done:'✔',stopped:'■',closed:'□',unknown:'?'};
function workBadge(t){var s=sit(t),k=s.stage||'unknown';return '<span class="stg '+esc(k)+'"><span class="g" aria-hidden="true">'+(STAGE_GLYPH[k]||'?')+'</span>'+esc(s.label||'Chưa xác định')+'</span>'}
function workReason(t){return sit(t).reason||''}
function workWho(t){var s=sit(t);return s.next?(s.next_by_text||'Chưa có thông tin người xử lý'):''}
function workResult(t){var s=sit(t),m=s.milestones;return m?m.text:((t.level||{}).label||'chưa có đầu ra')}   // a milestone root: the count of passed milestones (its 'level' would read "chưa có đầu ra" beside a pass)
function workItem(t){var s=sit(t),needs=(t.needs_user||[]).length,lu=t.last_update;
  return '<div class="c-title"><span class="ttl">'+esc(workTitle(t))+'</span><span class="sub">'+(workNoOwner(t)?'<span class="name">'+esc(t.plan)+'</span> · '+workNoOwner(t)+' · ':'')+'<span class="r3 mut" title="'+esc(t.project)+'">'+esc(short(t.project))+'</span></span>'+(workDesc(t)?'<span class="c-desc">'+esc(workDesc(t))+'</span>':'')+'</div>'
    +'<div class="c-state">'+workBadge(t)+'<span class="why">'+esc(workReason(t))+'</span></div>'
    +'<div class="c-next">'+(needs?'<span class="needb">Cần bạn</span> ':'')+'<span class="nx">'+esc(s.next||'Không còn bước tiếp theo')+'</span>'+(s.next?'<span class="who">Người xử lý: '+esc(workWho(t))+'</span>':'')+'</div>'
    +'<div class="c-res"><span class="lbl">Kết quả: </span>'+esc(workResult(t))+'</div>'
    +'<div class="c-last r2"><span class="lbl">Hoạt động cuối: </span>'+(lu?rel(lu.at)+' <span class="mut">· '+esc(lu.summary||'')+'</span>':'<span class="mut">chưa có</span>')+'</div>'}
function workOrder(rows,mode){function time(x){var n=Date.parse(x||'');return Number.isFinite(n)?n:null}function attention(t){var k=workStage(t);return (t.needs_user||[]).length?0:(k==='fix'||k==='stopped'||k==='unknown')?1:(sit(t).activity||{}).running?2:(k==='done'||k==='closed')?4:3}   // 13/11: the model's stage; finished work last
  return rows.slice().sort(function(a,b){var x,y;if(mode==='attention'){x=attention(a)-attention(b);if(x)return x;mode='attention'}
    if(mode==='created'){x=time(a.created_at);y=time(b.created_at)}else if(mode==='deadline'){x=time(a.deadline);y=time(b.deadline)}else{x=time(a.last_update&&a.last_update.at);y=time(b.last_update&&b.last_update.at)}
    if(x!==y){if(x===null)return 1;if(y===null)return -1;return mode==='created'||mode==='deadline'?x-y:y-x}
    return String(a.project_id||'').localeCompare(String(b.project_id||''))||String(a.selector||a.id||'').localeCompare(String(b.selector||b.id||''))})}
function laneOf(t){var k=workStage(t);return (k==='stopped'||k==='unknown')?'attn':k}
function workBoard(rows){var lanes=BOARD_LANES.map(function(s){var items=rows.filter(function(t){return laneOf(t)===s[0]});if(s[0]==='attn'&&!items.length)return '';
    return '<section class="board-lane'+(!items.length?' empty':'')+(s[0]==='attn'?' attn':'')+'" data-stage="'+s[0]+'" aria-label="'+s[1]+'"><h3 class="lane-title">'+s[1]+' <span>'+items.length+'</span></h3><ul role="listbox" aria-label="'+s[1]+'">'+items.map(row).join('')+'</ul>'+(!items.length?'<div class="lane-empty">Không có công việc</div>':'')+'</section>'}).join('');
  var closed=rows.filter(function(t){return workStage(t)==='closed'});
  return '<div class="board">'+lanes+'</div>'+(closed.length?'<details class="closed-fold" data-k="closed-fold"><summary>Đã đóng ('+closed.length+') · đóng không phải nghiệm thu</summary><ul role="listbox" aria-label="Đã đóng">'+closed.map(row).join('')+'</ul></details>':'')}
function workRows(rows){return '<div class="lhead" aria-hidden="true"><span>Công việc</span><span>Trạng thái · lý do</span><span>Bước tiếp theo · người xử lý</span><span>Kết quả</span><span>Hoạt động cuối</span></div><ul class="lrows" role="listbox" aria-label="Danh sách công việc">'+rows.map(row).join('')+'</ul>'}
function workText(v){if(v==null||v===''||(Array.isArray(v)&&!v.length))return 'chưa có dữ liệu';if(typeof v!=='object')return String(v);
  if(Array.isArray(v))return v.map(workText).join('; ');return v.text||v.title||v.label||v.spec||v.question||v.goal||Object.keys(v).map(function(k){return k+': '+workText(v[k])}).join('; ')||'chưa có dữ liệu'}
function workEsc(v){return esc(workText(v))}
function workOutputs(d,o){if(!o)return '';var n=function(b){return b==null?'':' ('+esc(b)+' byte)'};return '<p>Đầu ra lệnh kiểm, mã thoát '+esc(o.exit_code==null?'chưa rõ':o.exit_code)+(o.timed_out?', hết thời gian':'')+': stdout'+n(o.stdout_bytes)+' '+workEvidence(d,o.stdout)+' · stderr'+n(o.stderr_bytes)+' '+workEvidence(d,o.stderr)+(o.truncated?' · chỉ giữ phần cuối':'')+'</p>'}
function workEmpty(t){return '<div class="work-empty">'+esc(t)+'</div>'}
function workCard(label,value,note){return '<div class="work-card"><div class="eyebrow">'+esc(label)+'</div><div class="answer">'+workEsc(value)+'</div>'+(note?'<p class="work-meta">'+esc(note)+'</p>':'')+'</div>'}
function workSource(x){var s=x&&x.source,q=s&&(s.seq!=null?s.seq:s.verdict_seq);return s?'<details class="work-meta"><summary>Nguồn đối chiếu</summary><div>Nguồn: '+esc(s.kind||'receipt')+(q!=null?' #'+esc(q):'')+((x.at||s.at)?' · '+esc(when(x.at||s.at)):'')+'</div></details>':''}
function workEvidence(d,k){return k&&(d.evidence_keys||[]).indexOf(k)>=0?openBtn(k):'<span class="work-meta">Chưa có bằng chứng mở được từ task này</span>'}
function nodeName(d,id){var w=d.work||{},n=(w.node_titles||w.nodes||{})[id];return n?workText(n)+' ('+id+')':id||'chưa rõ phần việc'}
function sitPanel(d){var s=sit(d),a=s.activity||{},needs=d.needs_user||[],lu=d.last_update,n=d.nodes_summary||{},where=s.milestones?s.milestones.text:(n.total?((n.verified||0)+(n.accepted||0))+'/'+n.total+' phần việc đã kiểm':'');
  var ask=needs.length?'<a href="#needs">'+esc(needs.map(function(x){return needTitle(x)}).join(' · '))+'</a>':'Không có quyết định nào đang chờ bạn. Điều này không có nghĩa là việc đang tiến triển.';
  var all=((d.work||{}).outputs||[]),cur=all.filter(function(x){return !x.stale}),outs=cur.length,old=all.length-outs,chk=cur.filter(function(x){return x.level==='verified'||x.level==='accepted'}).length;
  return '<section class="sit" aria-label="Tóm tắt việc" data-k="sit"><div class="sit-grid">'
    +'<div><b>Đang ở đâu</b><span>'+workBadge(d)+(where?' <span class="sit-count">'+esc(where)+'</span>':'')+'</span>'+(s.milestones?'<small>'+esc(s.milestones.note)+'</small>':'')+'</div>'
    +'<div><b>Vướng gì</b><span>'+esc(s.reason||'chưa xác định')+'</span></div>'
    +'<div><b>Ai làm tiếp</b><span>'+(s.next?esc(s.next_by_text||'Chưa có thông tin người xử lý')+'<small>Bước tiếp theo: '+esc(s.next)+'</small>':'Không còn bước tiếp theo')+'</span></div>'
    +'<div class="'+(needs.length?'sit-need':'')+'"><b>Bạn cần làm gì</b><span>'+ask+'</span></div>'
    +'<div><b>Kết quả ở đâu</b><span>'+esc(d.work?((outs?outs+' đầu ra hiện hành · '+chk+' đã kiểm':(old?'Không có đầu ra hiện hành':'Chưa ghi nhận đầu ra'))+(old?' · '+old+' bản cũ hoặc cần kiểm lại':'')):((d.level||{}).label||'chưa có đầu ra'))+' <button type="button" class="linkish" data-work-tab="results">Mở Kết quả &amp; kiểm chứng</button></span></div>'
    +'</div><p class="sit-foot"><span class="'+(a.running?'live':'idle')+'">'+esc(a.text||'')+(a.since?' · từ '+when(a.since):'')+(a.last_signal?' · tín hiệu cuối '+when(a.last_signal)+' ('+relText(a.last_signal)+')':'')+'</span>'
    +'<span>Hoạt động cuối của việc: '+(lu?'<time title="'+when(lu.at)+'">'+when(lu.at)+'</time> · '+esc(lu.summary||''):'chưa có')+'</span>'
    +'<span class="mut">Sổ đọc lúc '+(d.generated_at?when(d.generated_at):'chưa rõ')+'</span></p></section>'}
function msStrip(d){var c=d.milestone_checks;if(!c||!(c.rows||[]).length)return '';
  return '<div class="ms-strip" aria-label="Các mốc">'+c.rows.map(function(m){return '<span class="ms '+esc(m.state)+'" title="'+esc(m.title||'')+'"><b>'+esc(m.id)+'</b> '+esc(m.label)+'</span>'}).join('')+'<button type="button" class="linkish" data-work-tab="progress">Xem các mốc và lần kiểm</button></div>'}
function workOverview(d,w){var o=(w.outputs||[]).filter(function(x){return !x.stale}),f=w.findings||[],open=f.filter(function(x){return (x.status||x.state)==='open'}).length,c=d.milestone_checks,m=d.measure||{};
  var checkTime=c?(c.rows||[]).reduce(function(t,r){return typeof r.check_seconds==='number'?(t||0)+r.check_seconds:t},null):null;
  return workOwnerSection(d)+msStrip(d)
    +'<div class="work-grid">'+workCard('Kết quả đã có',o.length?o.length+' đầu ra hiện hành · '+o.filter(function(x){return x.level==='verified'||x.level==='accepted'}).length+' đã kiểm':((w.outputs||[]).length?'Không có đầu ra hiện hành · '+(w.outputs||[]).length+' bản cũ hoặc cần kiểm lại':'Chưa ghi nhận đầu ra'),'Lịch sử cũ không tính vào số này. Xem từng đầu ra trong Kết quả & kiểm chứng.')
    +workCard('Dự kiến còn lại',d.eta&&d.eta.label,d.eta&&d.eta.reason)+'</div>'
    +(open?'<p class="work-warning">Còn '+open+' finding đang mở. Đây chưa phải số bug độc lập.</p>':'')
    +(c?'<p class="work-meta">Thời gian chạy bộ kiểm đã ghi: '+(checkTime===null?'chưa có lần kiểm nào đủ mốc thời gian':hms(checkTime))+'. Đây là thời gian kiểm, không phải thời gian làm việc; việc không chạy qua engine nên không có số đo thực hiện.</p>'
      :'<p class="work-meta">Thời gian đã trôi qua: '+hms(d.elapsed&&d.elapsed.seconds)+' · Thực hiện đã ghi nhận: '+hms(m.attempts_wall_seconds)+' · Chờ đã ghi nhận: '+hms(m.wait_seconds)+'. Không tự quy thời gian chưa rõ thành thời gian làm việc.</p>')}
function workSolution(d,w){var s=w.solution||{},c=s.contract||{},card=s.card||{},ref=s.source_solution;
  return '<div class="work-grid">'+workCard('Bản đề xuất mới nhất',s.latest_revision)+workCard('Bản được duyệt',s.approved_revision)
    +workCard('Bản có thể thực hiện',s.runnable_revision,'Bản đề xuất mới không tự thay thế bản đang được phép chạy. Không có bản chạy được thì chưa suy quyền thực hiện.')+workCard('Mục tiêu',c.goal||d.goal)+'</div>'
    +((s.latest_revision!=null&&s.latest_revision!==s.approved_revision)?'<p class="work-warning">Có bản chưa được duyệt. Chỉ các phần được cơ chế quyền cho phép mới tiếp tục.</p>':'')
    +(s.frozen?'<p class="work-warning">Phần được tiếp tục: '+(Array.isArray(s.frozen.runnable)&&!s.frozen.runnable.length?'không có':workEsc(s.frozen.runnable))+'; phần chờ bản mới: '+(Array.isArray(s.frozen.frozen)&&!s.frozen.frozen.length?'không có':workEsc(s.frozen.frozen))+'</p>':'')
    +'<h3>Phương án và phạm vi</h3><div class="work-grid">'+workCard('Trước → sau',card.before||card.after?[card.before,card.after]:null)
    +workCard('Phương án ưu tiên',card.preferred,card.why?workText(card.why):null)+workCard('Giữ nguyên',card.preserve||c.preserve)+workCard('Phạm vi',c.scope)+'</div>'
    +'<h3>Điều kiện hoàn thành</h3>'+workList(c.acceptance||card.acceptance,'Hợp đồng chưa cung cấp điều kiện hiển thị được.')
    +'<h3>Điều còn chưa rõ</h3>'+workList(card.unknowns_open,'Chưa ghi nhận câu hỏi mở trong thẻ solution; điều này không chứng nhận mọi thứ đã được kiểm.')
    +(ref?'<div class="work-row"><h4>Solution nguồn v1</h4><p>'+workEsc(ref.id)+' · revision '+workEsc(ref.revision)+'</p>'
      +(ref.status==='available'?Object.keys(ref.payload||{}).map(function(k){return '<p><b>'+esc(({brief:'Tóm tắt',detail:'Nội dung',before:'Trước',after:'Sau',preferred:'Phương án',why:'Lý do',preserve:'Giữ nguyên',acceptance:'Điều kiện hoàn thành',non_goals:'Ngoài phạm vi',assumptions:'Giả định',questions:'Câu hỏi'})[k]||k)+':</b> '+workEsc(ref.payload[k])+'</p>'}).join(''):workEmpty('Không đọc được SOL đúng phạm vi và revision; không sử dụng nội dung chưa xác minh.'))
      +'<p class="work-meta">Nguồn solution không thay quyền của hợp đồng task.</p></div>':workEmpty('Task không có SOL v1 liên kết; dùng hợp đồng và thẻ bước 0 có sẵn.'))}
function workList(rows,empty){if(!rows||!rows.length)return workEmpty(empty);return '<ul>'+rows.map(function(x){return '<li>'+workEsc(x)+'</li>'}).join('')+'</ul>'}
function diffLabel(path){var k=String(path||''),base={title:'Tên công việc',goal:'Mục tiêu',acceptance:'Điều kiện hoàn thành',nodes:'Các phần việc',version:'Phiên bản cấu trúc',scope:'Phạm vi',budget:'Ngân sách',outputs:'Đầu ra'};
  if(base[k])return base[k];if(/^nodes\[/.test(k))return k.includes('.input')?'Đầu vào của phần việc':'Nội dung một phần việc';return 'Chi tiết thay đổi'}
function workChanges(d,w){var rows=w.changes||[];if(!rows.length)return workEmpty('Chưa ghi nhận thay đổi có nguồn. UI không suy lịch sử từ hội thoại.');
  return '<p class="work-meta">Mới nhất trước. Điều chỉnh trong quyền đã cấp không tự tạo yêu cầu duyệt mới.</p>'+rows.slice().reverse().map(function(x){var kind={initial:'Kế hoạch thực hiện ban đầu',contract:'Cập nhật phương án',internal:'Điều chỉnh cách thực hiện',retry:'Thực hiện lại phần việc'}[x.kind]||x.kind;
    var version=x.kind==='internal'?(x.internal_revision!=null?' · lần '+x.internal_revision:'')+(x.revision!=null?' (phương án '+x.revision+')':''):(x.revision!=null?' · bản '+x.revision:'');
    var diffs=x.diff||x.changes||[],fields=Array.from(new Set(diffs.map(function(v){return diffLabel(v.path)})));
    var h='<article class="work-row"><h4>'+workEsc(kind)+esc(version)+'</h4><p>'+workEsc(x.reason)+'</p>'
      +(fields.length?'<p><b>'+(x.kind==='initial'?'Nội dung kế hoạch:':'Nội dung thay đổi:')+'</b> '+esc(fields.join(', '))+'</p>':'')
      +(x.affected_nodes&&x.affected_nodes.length?'<p><b>Phần bị ảnh hưởng:</b> '+esc(x.affected_nodes.map(function(n){return nodeName(d,n)}).join(', '))+'</p>':'')
      +(x.reused_nodes&&x.reused_nodes.length?'<p><b>Giữ kết quả:</b> '+esc(x.reused_nodes.map(function(n){return nodeName(d,n)}).join(', '))+'</p>':'')
      +(x.kind==='contract'?'<p class="work-warning">'+(x.approved?'Bản này đã có quyết định duyệt. Quyền hiện tại xem Solution.':'Bản đề xuất chưa duyệt. Xem thẻ quyết định ở đầu trang.')+'</p>':(x.decision&&x.decision.validity&&x.decision.validity.outcome==='in_authority'?'<p>'+(x.kind==='initial'?'Kế hoạch ban đầu nằm trong quyền được cấp.':'Điều chỉnh đã được xử lý trong quyền được cấp.')+'</p>':''));
    h+='<details data-k="work-diff:'+esc(x.id)+'"><summary>'+(x.kind==='initial'?'Xem nội dung ban đầu':'Xem trước / sau')+' ('+diffs.length+' mục)</summary>'+diffs.map(function(v){return '<h4>'+esc(diffLabel(v.path))+'</h4>'+(x.kind==='initial'?'<div>'+workEsc(v.after)+'</div>':'<div class="work-diff"><div><b>Trước</b><br>'+((v.before==null&&v.change==='added')?'Chưa có — nội dung mới được thêm':workEsc(v.before))+'</div><div><b>Sau</b><br>'+workEsc(v.after)+'</div></div>')+'<details><summary>Trường kỹ thuật</summary>'+workEsc(v.path)+'</details>'}).join('')+'</details>';
    if(x.diff_error)h+=workEmpty(x.diff_error);
    if(x.diff_total>diffs.length)h+='<p class="work-warning">Đang hiện '+diffs.length+'/'+esc(x.diff_total)+' dòng thay đổi; phần hiển thị đã được rút gọn.</p>';
    return h+workSource(x)+(x.decision?'<details data-k="work-decision:'+esc(x.id)+'"><summary>Căn cứ quyền</summary><p>'+workEsc(x.decision)+'</p></details>':'')+'</article>'}).join('')}
function workRepairFlow(d,w){var repairs=w.repairs||[],runs=(w.checks||{}).runs||[],actors=w.actors||[],findings=w.findings||[];
  return repairs.length?'<h3>Diễn tiến kiểm và sửa</h3>'+repairs.map(function(r,i){var linked=runs.filter(function(x){return (r.verification||[]).indexOf(x.id)>=0}),issues=findings.filter(function(f){return (f.source||{}).receipt===r.source_receipt}),who=actors.filter(function(a){return a.node===r.node&&a.role==='executed'&&(!a.attempt||((w.outputs||[]).some(function(o){return o.attempt===a.attempt&&o.generation===(r.generations||{})[r.node]})))});
    return '<article class="work-row"><h4>Vòng '+(i+1)+' · '+esc(nodeName(d,r.node))+'</h4>'+(r.applicable===false?'<p class="work-warning">Lịch sử — không chứng nhận bản hiện hành</p>':'')+'<div class="repair-flow"><div><b>1. Kiểm phát hiện vấn đề</b>'+esc((r.failed_checks||[]).length)+' kiểm tra không đạt'+(issues.length?'<p>'+issues.map(function(f){return workEsc(f.text||f.head||f.claim||f.id)}).join('; ')+'</p>':'')+workEvidence(d,r.source_receipt)+'</div><div><b>2. Sửa phần bị ảnh hưởng</b>'+workEsc(r.reason)+'<p>Người thực hiện: '+(who.length?who.map(function(a){return workEsc(a.actor||a.provider)}).join(', '):'chưa có định danh xác nhận cho lượt này')+'</p></div><div><b>3. Kiểm lại sau sửa</b>'+(linked.length?linked.map(function(x){return '<p>'+esc(nodeName(d,x.node))+' · '+esc(x.status==='pass'?'Đạt':x.status==='fail'?'Không đạt':x.status||'Chưa rõ')+'</p>'+workEvidence(d,x.receipt)}).join(''):'Chưa có kết quả kiểm lại liên kết')+'</div></div></article>'}).join(''):''}
function workResults(d,w){var outputs=w.outputs||[],runs=(w.checks||{}).runs||[],findings=w.findings||[],repairs=w.repairs||[],actors=w.actors||[];
  var levels={produced:'Đã tạo',verified:'Đã kiểm',failed:'Đã kiểm · không đạt',accepted:'Đã nghiệm thu',unknown:'Chưa xác định'};
  var current=outputs.filter(function(x){return !x.stale}),history=outputs.filter(function(x){return x.stale});
  function outputRows(items){return items.map(function(x){return '<article class="work-row"><h4>'+workEsc(x.title||x.label||nodeName(d,x.node))+' · '+esc(levels[x.level]||'Chưa xác định')+'</h4>'
    +'<p class="work-meta">'+esc(nodeName(d,x.node))+' · '+(x.stale?(x.stale_reason==='cần kiểm lại'?'Cần kiểm lại: lần đạt này không còn được tính · ':'Bản cũ / cần kiểm lại · '):'')+(x.inherited?'Kế thừa · ':'')+'Thế hệ '+workEsc(x.generation)+'</p>'
    +(x.inherited&&x.from_generation!=null?'<p class="work-meta">Kế thừa từ thế hệ '+workEsc(x.from_generation)+' · lượt tạo '+workEsc(x.from_attempt)+'</p>':'')
    +workEvidence(d,x.artifact||x.key)+workSource(x)+'</article>'}).join('')}
  var h='<h3>Kết quả hiện hành</h3>'+(current.length?outputRows(current):workEmpty(history.length?'Chưa có đầu ra hiện hành: '+history.length+' đầu ra trước đây là bản cũ hoặc cần kiểm lại (xem bên dưới), không chứng nhận bản hiện tại.':'Chưa có đầu ra hiện hành được ghi nhận.'))
    +(history.length?'<details data-k="work-history"'+(current.length?'':' open')+'><summary>Đầu ra lịch sử ('+history.length+')</summary>'+outputRows(history)+'</details>':'')
    +workRepairFlow(d,w)+'<details data-k="work-check-details"><summary>Chi tiết các lần kiểm, vấn đề và người thực hiện</summary>';
  h+='<h3>Các lần kiểm</h3><p class="work-meta">Một check có thể gồm nhiều testcase. Số check/finding không phải số bug độc lập; thiếu thống kê testcase thì không tự suy ra.</p>';
  var summary=(w.checks||{}).summary||{},cases=summary.testcases;
  h+='<div class="work-grid">'+workCard('Check duy nhất / lượt chạy',summary.unique_checks!=null?summary.unique_checks+' / '+summary.check_executions:null,'Tổng trong lịch sử có receipt, không phải độ bao phủ của bản hiện tại.')
    +workCard('Testcase duy nhất / lượt chạy',cases?cases.unique+' / '+cases.executions:null,cases?'Các trạng thái là số lượt: pass '+cases.pass+', fail '+cases.fail+', skip '+cases.skip+', error '+cases.error+', chưa rõ '+cases.unknown: 'Receipt chưa cung cấp đủ testcase có định danh.')+'</div>';
  h+=runs.length?runs.map(function(x){var tally={};(x.checks||[]).forEach(function(c){var k=c.status||c.result||'unknown';tally[k]=(tally[k]||0)+1});
    return '<article class="work-row"><h4>'+esc(nodeName(d,x.node))+' · '+workEsc(x.status||x.result)+'</h4><p>'+Object.keys(tally).map(function(k){return esc(k)+': '+tally[k]}).join(' · ')+'</p>'
    +(x.testcases&&x.testcases.length?'<p>Testcase có định danh: '+x.testcases.length+' lượt trong receipt này.</p>'+workList(x.testcases.map(function(c){return c.id+': '+c.status}), ''):'<p class="work-meta">Chưa có thống kê testcase có định danh.</p>')
    +(x.stale?'<p class="work-warning">Kết quả lịch sử, không chứng nhận bản hiện tại.</p>':'')+workEvidence(d,x.receipt)+workOutputs(d,x.outputs)+workSource(x)+'</article>'}).join(''):workEmpty('Chưa có receipt kiểm đọc được; không thể kết luận không có lỗi.');
  h+='<h3>Finding và xử lý</h3>'+(findings.length?findings.map(function(x){var resolution=x.resolution||{};return '<article class="work-row"><h4>'+workEsc(x.id)+' · '+workEsc(x.status||x.state)+'</h4><p>'+workEsc(x.text||x.head||x.claim)+'</p>'+(x.severity?'<p class="work-meta">Mức độ: '+workEsc(x.severity)+'</p>':'')
    +'<p>Nguồn phát hiện: '+workEvidence(d,(x.source||{}).receipt)+'</p>'
    +(x.resolution?'<p>Căn cứ xử lý: '+workEsc(resolution.reason||x.reason)+' '+workEvidence(d,resolution.receipt)+'</p>':'')
    +(x.category?'<p>Phân loại: '+workEsc(x.category)+'</p>':'')+(x.duplicate_of?'<p>Trùng với: '+workEsc(x.duplicate_of)+'</p>':'')+(x.recurrence_of?'<p>Tái xuất hiện từ: '+workEsc(x.recurrence_of)+'</p>':'')
    +workSource(x)+'</article>'}).join(''):workEmpty(w.finding_register===false?'Plan này không có sổ finding (đề xuất không kèm --workflow): lần kiểm fail chỉ nằm ở "Các lần kiểm" phía trên, kèm stdout/stderr; nó không tự thành finding hay vòng sửa.':'Chưa ghi nhận finding; không đồng nghĩa đã kiểm hết.'));
  h+='<h3>Chuỗi sửa và kiểm lại</h3>'+(repairs.length?repairs.map(function(x,i){var linked=runs.filter(function(r){return (x.verification||[]).indexOf(r.id)>=0});return '<article class="work-row"><h4>Vòng sửa '+(i+1)+' · '+esc(nodeName(d,x.node||x.target))+' · '+workEsc(({verified:'Đã kiểm đủ phần ảnh hưởng',partial:'Mới kiểm một phần',unverified:'Chưa kiểm đủ'})[x.status]||x.status)+'</h4>'
    +(x.applicable===false?'<p class="work-warning">Vòng sửa lịch sử; không chứng nhận thế hệ hiện tại.</p>':'')
    +'<p>Kiểm lỗi cũ: '+workEsc(x.failed_checks)+'</p><p>Phần ảnh hưởng: '+esc((x.affected_nodes||[]).map(function(n){return nodeName(d,n)}).join(', '))+'</p>'+workEvidence(d,x.source_receipt)
    +'<p><b>Kiểm lại sau sửa</b></p>'+(linked.length?linked.map(function(r){return '<p>'+esc(nodeName(d,r.node))+' · '+workEsc(r.status)+' '+workEvidence(d,r.receipt)+'</p>'}).join(''):workEmpty('Chưa có receipt kiểm lại liên kết với vòng này.'))
    +((x.rebindings||[]).length?'<p class="work-meta">'+x.rebindings.length+' lần nối lại thứ tự; không tính là vòng sửa mới.</p>'+(x.rebindings||[]).map(function(b,j){var checked=runs.filter(function(r){return (b.verification||[]).indexOf(r.id)>=0});return '<details data-k="work-rebind:'+esc(x.id)+':'+j+'"><summary>Nối lại '+(j+1)+' · '+workEsc(({verified:'Đã kiểm đủ',partial:'Kiểm một phần',unverified:'Chưa kiểm đủ'})[b.status]||b.status)+' · '+(b.applicable?'áp dụng hiện tại':'lịch sử')+'</summary>'+checked.map(function(r){return '<p>'+esc(nodeName(d,r.node))+' · '+workEsc(r.status)+' '+workEvidence(d,r.receipt)+'</p>'}).join('')+workSource(b)+'</details>'}).join(''):'')+workSource(x)+'</article>'}).join(''):workEmpty('Chưa có liên kết repair receipt. Không coi mỗi attempt là một vòng sửa.'));
  h+='<h3>Ai được giao / ai đã thực hiện</h3>'+(actors.length?'<div class="scroll"><table><thead><tr><th>Vai trò</th><th>Phần việc</th><th>Người / model có nguồn</th></tr></thead><tbody>'+actors.map(function(x){return '<tr><td>'+workEsc({assigned:'Được giao',executed:'Đã thực hiện',reviewer:'Đã kiểm'}[x.role]||x.role)+'</td><td>'+esc(nodeName(d,x.node))+'</td><td>'+workEsc(x.actor||x.provider)+(x.model?' · '+workEsc(x.model):'')+workSource(x)+'</td></tr>'}).join('')+'</tbody></table></div>':workEmpty('Chưa có định danh thực thi được ghi nhận. Không suy từ tên phiên chat.'));
  return h+'</details>'}
function workProgress(d){var m=d.measure||{},v=m.verification||[],a=m.attempts||[];return '<div class="work-grid">'+workCard('Khoảng thực hiện đã ghi nhận',hms(m.attempts_wall_seconds),'Hợp các khoảng attempt, không cộng đôi phần chồng nhau.')+workCard('Khoảng chờ đã ghi nhận',hms(m.wait_seconds),'Khoảng chờ mở hoặc thiếu mốc kết thúc vẫn chưa xác định.')+'</div>'
  +'<details data-k="work-progress-measures"><summary>Số đo chi tiết từng lượt</summary><h3>Từng lượt thực hiện</h3><p class="work-meta">Tiếp nhận: quyết định Q2 đến bắt đầu phần việc. Chuẩn bị: giữ chỗ đến khởi chạy. Thực thi: khởi chạy đến kết thúc lượt. Đây là các khoảng quan sát, chưa phải thời gian hàng đợi scheduler riêng; không cộng các lượt chạy song song.</p>'
  +(a.length?'<table><thead><tr><th>Phần việc / lượt</th><th>Tiếp nhận</th><th>Chuẩn bị</th><th>Thực thi</th></tr></thead><tbody>'+a.map(function(x){return '<tr><td>'+esc(nodeName(d,x.node))+'<div class="work-meta">'+esc(String(x.attempt||'').slice(0,12))+' · thế hệ '+workEsc(x.generation)+'</div></td><td>'+hms(x.admission_seconds)+'</td><td>'+hms(x.preparation_seconds)+'</td><td>'+hms(x.execution_seconds)+'</td></tr>'}).join('')+'</tbody></table>':workEmpty('Chưa có lượt thực hiện có số đo.'))
  +'<h3>Từ đầu ra đến kết quả kiểm</h3><p class="work-meta">Khoảng này có thể gồm thời gian chờ trước kiểm. Chưa có cặp bắt đầu/kết thúc riêng thì thời gian chạy bộ kiểm và hàng đợi riêng đều chưa xác định; không cộng các khoảng này vào thời gian thực hiện.</p>'
  +(v.length?workList(v.map(function(x){return nodeName(d,x.node)+' · thế hệ '+x.generation+' · '+hms(x.seconds)+' · '+x.result}), ''):workEmpty('Chưa có khoảng kiểm có nguồn.'))+'</details>'}
var CHECK_WORDS={pass:'Đạt',fail:'Không đạt',error:'Lỗi bộ kiểm',inconclusive:'Chưa kết luận'};
function checkWord(c){if(c.state==='open')return 'Đang kiểm';if(c.state==='lost')return 'Mất tín hiệu';if(c.state==='abandoned')return 'Bỏ dở';return CHECK_WORDS[c.result]||c.result||'Chưa có kết quả'}
function checkCls(c){return c.state==='open'?'open':c.state==='lost'||c.state==='abandoned'?'lost':c.result==='pass'?'pass':c.result?'fail':'open'}
function msChart(c){var ts=[];(c.rows||[]).forEach(function(r){r.checks.forEach(function(x){[x.started,x.ended,x.recorded].forEach(function(v){var n=tms(v);if(n!==null)ts.push(n)})})});
  if(!ts.length)return '';var W={w0:Math.min.apply(null,ts),w1:Math.max.apply(null,ts)};if(W.w1-W.w0<1000){var mid=(W.w0+W.w1)/2;W.w0=mid-500;W.w1=mid+500}
  var ticks=gTicks(W),axis=ticks.map(function(t,i){return '<i style="left:'+t.pct+'%"></i><span class="'+(i===0?'first':t.pct>95?'last':'')+'" style="left:'+t.pct+'%">'+esc(t.label)+'</span>'}).join('');
  var tree=['<div class="grow gh0">Mốc</div>'],chart=['<div class="gaxis">'+axis+'</div>'];
  (c.rows||[]).forEach(function(r){tree.push('<div class="grow msrow"><strong title="'+esc(r.title||'')+'">'+esc(r.id)+(r.title?' — '+esc(r.title):'')+'</strong><span>'+esc(r.label)+'</span></div>');
    chart.push('<div class="grow msrow">'+ticks.map(function(t){return '<i class="ggrid" style="left:'+t.pct.toFixed(3)+'%"></i>'}).join('')+r.checks.map(function(x,i){var l=pct(W,x.started),e=pct(W,x.ended);
      if(l!==null&&e!==null)return '<div class="seg chk '+checkCls(x)+'" style="left:'+l.toFixed(3)+'%;width:'+Math.max(0.4,e-l).toFixed(3)+'%" title="Lần kiểm '+(i+1)+' · '+esc(checkWord(x))+' · chạy bộ kiểm '+when(x.started)+' → '+when(x.ended)+'"></div>';
      var at=pct(W,x.recorded||x.ended||x.started);return at===null?'':'<span class="mk '+checkCls(x)+'" style="left:'+at.toFixed(3)+'%" title="Lần kiểm '+(i+1)+' · '+esc(checkWord(x))+' · '+when(x.recorded||x.ended||x.started)+' (không có thời điểm bắt đầu)">◆</span>'}).join('')+(r.checks.length?'':'<span class="msnone">chưa kiểm</span>')+'</div>')});
  return '<div class="gscroll" data-k="msscroll"><div class="gbody msbody"><div class="gtree">'+tree.join('')+'</div><div class="gchart">'+chart.join('')+'</div></div></div>'
    +'<p class="gexplain">Thanh = thời gian chạy bộ kiểm của một lần kiểm (từ lúc bắt đầu đến lúc có receipt); ◆ = kết quả không có thời điểm bắt đầu. Khoảng trống giữa hai lần kiểm không phải thời gian chờ hay thời gian làm việc. Mốc 0: '+when(new Date(W.w0).toISOString())+'.</p>'}
function msProgress(d){var c=d.milestone_checks,s=sit(d);if(!c)return workEmpty('Chưa đọc được danh sách mốc của hợp đồng hiện hành.');
  var h='<div class="ms-head"><h3>Các mốc của việc: '+esc(workTitle(d))+'</h3><p class="work-meta">Hợp đồng bản '+esc(c.revision)+' · '+esc(s.milestones?s.milestones.text:'')+'. '+esc(s.milestones?s.milestones.note:'')+'. Trạng thái việc xem ở phần tóm tắt phía trên; không cần đọc biểu đồ.</p><p class="work-meta">“Đạt” là lần kiểm gần nhất của mốc trên hợp đồng này đạt. Trang không băm lại thư mục dự án; nếu mã đã đổi sau lần kiểm, việc đối chiếu xảy ra ở bước kiểm điều kiện nghiệm thu và khi đó mốc chuyển sang “Cần kiểm lại”.</p></div>';
  h+='<ol class="mslist">'+(c.rows||[]).map(function(r){var last=r.checks.length?r.checks[r.checks.length-1]:null;
    return '<li class="msitem '+esc(r.state)+'" data-k="ms:'+esc(r.id)+'"><div class="ms-name"><b>'+esc(r.id)+'</b> '+esc(r.title||'')+'</div><div class="ms-state"><span class="ms '+esc(r.state)+'">'+esc(r.label)+'</span></div>'
      +'<div class="ms-checks">'+(r.checks.length?r.checks.length+' lần kiểm'+(r.failures?' · '+r.failures+' không đạt':''):'Chưa có lần kiểm')+'</div>'
      +'<div class="ms-last">'+(last?'Gần nhất: '+esc(checkWord(last))+' · '+when(last.recorded||last.ended||last.started):'—')+'</div>'
      +'<div class="ms-time">'+(typeof r.check_seconds==='number'?'Chạy bộ kiểm: '+gDuration(r.check_seconds):r.checks.length?'Chạy bộ kiểm: chưa đủ mốc đo':'')+'</div>'
      +(r.note?'<div class="ms-note">'+esc(r.note)+'</div>':'')
      +(r.checks.length?'<details class="ms-detail" data-k="ms-checks:'+esc(r.id)+'"><summary>Các lần kiểm ('+r.checks.length+')</summary><ol>'+r.checks.map(function(x,i){return '<li>Lần '+(i+1)+': <b>'+esc(checkWord(x))+'</b> · '+(x.started?'chạy '+when(x.started)+' → '+(x.ended?when(x.ended):'chưa kết thúc'):'không có thời điểm bắt đầu')+(typeof x.seconds==='number'?' ('+gDuration(x.seconds)+')':'')+(x.by?' · ghi bởi '+esc(x.by):'')+(x.lost?' · '+(x.lost==='process_gone'?'tiến trình kiểm không còn':'quá hạn chạy'):'')+'</li>'}).join('')+'</ol></details>':'')+'</li>'}).join('')+'</ol>';
  h+='<h3>Các lần kiểm theo thời gian</h3>'+(c.timed?msChart(c):'<p class="work-empty" id="msnotime">Chưa có lần kiểm nào có đủ thời điểm bắt đầu và kết thúc trong sổ, nên trang không dựng trục hay thanh thời gian. Danh sách mốc phía trên là nguồn đầy đủ.</p>');
  return h}
function crumbTab(d){var t=WORK_TABS.find(function(x){return x[0]===workTab});return t?(workTab==='progress'&&d.milestone_checks?'Tiến độ · các mốc':t[1]):''}
function workDashboard(d){var w=d.work;if(!w)return '';var content=workTab==='solution'?workSolution(d,w):workTab==='changes'?workChanges(d,w):workTab==='results'?workResults(d,w):workTab==='overview'?workOverview(d,w):(d.milestone_checks?msProgress(d):gantt(d)+workProgress(d));
  return '<nav class="work-nav" role="tablist" aria-label="Chi tiết công việc">'+WORK_TABS.map(function(t){return '<button type="button" role="tab" data-work-tab="'+t[0]+'" id="work-tab-'+t[0]+'" data-k="work-tab:'+t[0]+'" aria-selected="'+(workTab===t[0])+'" aria-controls="work-content">'+t[1]+'</button>'}).join('')+'</nav>'
    +'<section id="work-content" class="work-panel" role="tabpanel" aria-labelledby="work-tab-'+workTab+'">'+content
    +((w.limitations||[]).length?'<details data-k="work-limits"><summary>Giới hạn dữ liệu ('+w.limitations.length+')</summary>'+workList(w.limitations,'')+'</details>':'')+'</section>'}
'''
