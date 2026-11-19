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
#list[data-mode=list]{--cols:minmax(0,3.2fr) minmax(0,1.8fr) minmax(0,1.1fr) minmax(0,1.2fr)}
li.task .c-line{display:block;margin-top:4px;font-size:14px;line-height:1.45}li.task .c-line .nx1{font-weight:650}li.task .c-line .who1,li.task .c-line .vnote{color:var(--mut);font-size:13px}
li.task .c-next,li.task .c-state>.stg{display:none}li.task .c-line .arr{color:var(--mut)}
.tiles4{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr));gap:12px;margin:12px 0}
.tile4{border:1px solid var(--line);border-radius:12px;background:var(--card);padding:12px 14px;min-width:0;overflow-wrap:anywhere}.tile4 h3{margin:0 0 6px;font-size:12px;color:var(--mut);text-transform:uppercase;letter-spacing:.05em}
.tile4 .tv{font-size:16px;font-weight:650;margin:0 0 4px}.tile4 p{margin:4px 0}.tile4 pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:40vh;overflow:auto;background:var(--bg);padding:8px;border-radius:6px;font-size:12px}
.tile4 .next-act{font-size:17px;font-weight:700;color:var(--run);margin:2px 0 6px}.tile4 .why-missing{font-size:13px;color:var(--needfg);background:var(--need);border-radius:6px;padding:4px 8px}
.tile4.v-recheck,.tile4.v-inconclusive,.tile4.v-not_compared,.tile4.v-unknown{border-color:var(--wait)}.tile4.v-failed{border-color:var(--blk)}.tile4.v-valid,.tile4.v-accepted{border-color:var(--acc)}
.tile4 .declist{list-style:none;margin:4px 0;padding:0}.tile4 .declist li{margin:6px 0}.tile4 .dsrc,.need .dsrc{display:block;font-size:12px;opacity:.85}
.deep{margin:14px 0}.deep>h3{font-size:15px;margin:0 0 6px}.deep-d{border:1px solid var(--line);border-radius:10px;background:var(--card);padding:6px 12px;margin:6px 0}
.deep-d>summary{font-weight:650;color:var(--fg);min-height:32px;display:flex;align-items:center;gap:6px}.deep-d .cnt{color:var(--mut);font-weight:400}.deep-body{padding:6px 0;overflow-wrap:anywhere}
.loop{list-style:none;margin:6px 0;padding:0}.loop li{padding:4px 0 4px 12px;border-left:3px solid var(--line);margin:2px 0}.loop li.fail{border-left-color:var(--blk)}.loop li.pass{border-left-color:var(--acc)}.loop li.fix{border-left-color:var(--run)}.loop li.recheck{border-left-color:var(--wait)}
.opt .cons{display:block;font-size:13px;margin-top:2px}.opt .oid{font-size:12px;opacity:.8}
#detail pre{white-space:pre-wrap;overflow-wrap:anywhere;max-width:100%;max-height:40vh;overflow:auto;box-sizing:border-box}.deep-body .small{min-width:0;overflow-wrap:anywhere}
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
.org{display:inline-block;font-size:11.5px;font-weight:650;padding:0 7px;border-radius:9px;border:1px solid var(--line);margin-right:4px;white-space:nowrap;line-height:1.6;vertical-align:baseline}
.org.owner{background:#e6f4ea;color:#1e4620;border-color:#b7dfc2}.org.ai{background:#ede7f6;color:#3f2a77;border-color:#cfc2ee}.org.unknown{background:var(--card);color:var(--mut);border-style:dashed}
li.task .links{font-size:12px;color:var(--mut);margin-right:2px}
.listfoot{margin:12px 0 4px;font-size:13.5px;overflow-wrap:anywhere}.listfoot .cov{margin:4px 0}#more{min-height:38px;font-weight:600;margin:4px 0}.needout{background:var(--need);color:var(--needfg);padding:6px 10px;border-radius:8px}
#filters input[type=date]{min-height:36px}
.rel{border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:14px 0;background:var(--card);overflow-wrap:anywhere}.rel h3{margin:0 0 10px;font-size:16px}
.rel-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr));gap:10px 16px}.rel-grid>div{min-width:0;display:grid;gap:3px;align-content:start}
.rel-grid b{font-size:12px;color:var(--mut);text-transform:uppercase;letter-spacing:.04em}.rel-grid small{font-size:12.5px;color:var(--mut)}
.rel-h{font-size:14px;margin:14px 0 4px}.rel-item{border-top:1px solid var(--line);padding:8px 0;min-width:0}.rel-item h4{font-size:14px;margin:0 0 4px}.rel-item p{margin:3px 0}
.rel-kind{font-weight:700}.rel-noname{color:var(--mut);font-style:italic;font-weight:400}.rel-meta{font-size:13px;color:var(--mut)}.rel-state{color:var(--fg);font-weight:600}.rel-foot{display:flex;flex-wrap:wrap;gap:4px 12px;align-items:baseline}.rel-id{font-size:12px}
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
// OBS-2C: where the work came from (ledger records only) and what it spawned, each id counted once (tracking_list)
function orgBadge(o){return o&&o.source?'<span class="org '+esc(o.source)+'" data-origin="'+esc(o.source)+'" title="'+esc(o.why||'')+'">'+esc(o.label||o.source)+'</span>':''}
function linksText(t){var l=(t.list||{}).links||{},p=[];if(l.repairs)p.push(l.repairs+' việc sửa');if(l.children)p.push(l.children+' việc con');return p.length?'<span class="links" title="việc AI/engine phát sinh trong việc này; mỗi việc đếm một lần">'+esc(p.join(' · '))+'</span>':''}
// UI58 MC: one line per row says the state and the next step (and who, when the ledger names it); the validity note says when a result was
// not compared with the project now (the list does not hash projects) or passed on an earlier version; the project shows only when the list
// holds several projects and none is chosen.
function validityNote(t){var v=t&&t.validity;if(!v)return '';if(v.kind==='not_compared')return 'chưa so với bản hiện tại';if(v.kind==='recheck')return 'từng đạt trên bản trước';
  if(v.compared&&v.as_of&&t.compared_by==='task_page'&&!t.milestone_checks)return 'theo lần so lúc '+when(v.as_of);return ''}
function whoShort(t){var s=sit(t);if(!s.next)return '';var w=s.next_by_text||'';return w&&w!=='Chưa có thông tin người xử lý'?w:'chưa rõ ai làm'}
function statusLine(t){var s=sit(t),vn=validityNote(t),needs=(t.needs_user||[]).length;
  return '<span class="sline" data-status-line="1">'+(needs?'<span class="needb">Cần bạn</span> ':'')+workBadge(t)+(vn?' <span class="vnote">('+esc(vn)+')</span>':'')
    +' <span class="arr" aria-hidden="true">→</span> <span class="nx1">'+esc(s.next||(s.stage==='done'||s.stage==='closed'?'Không còn bước tiếp theo':'Chưa biết bước tiếp theo'))+'</span>'
    +(s.next?' <span class="who1">· '+esc(whoShort(t))+'</span>':'')+'</span>'}
function scopeProjects(){var L=(typeof last!=='undefined'&&last)?last:null;if(!L)return 0;var ps=(L.list&&L.list.projects)||L.projects||[];return ps.length}
function showProject(){var p=typeof document!=='undefined'&&document.querySelector?document.querySelector('#proj'):null;return !(p&&p.value)&&scopeProjects()>1}
// UI58 MC (regression of 19/11): the row shows a short name (the model's row_title: the first sentence of the owner's request, clipped); the full
// text is the row's title attribute and accessible name, the task page's "Việc này làm gì", and what the search reads.
function rowName(t){return t.row_title||workTitle(t)}
function rowLabel(t){var s=sit(t),vn=validityNote(t),needs=(t.needs_user||[]).length;
  return workTitle(t)+'. '+(needs?'Cần bạn. ':'')+(s.label||'Chưa xác định')+(vn?' ('+vn+')':'')+' → '+(s.next||(s.stage==='done'||s.stage==='closed'?'Không còn bước tiếp theo':'Chưa biết bước tiếp theo'))+(s.next?' · '+whoShort(t):'')}
function workItem(t){var s=sit(t),needs=(t.needs_user||[]).length,lu=t.last_update,proj=showProject();
  return '<div class="c-title"><span class="ttl" title="'+esc(workTitle(t))+'">'+esc(rowName(t))+'</span><span class="c-line">'+statusLine(t)+'</span><span class="sub">'+orgBadge(t.origin)+linksText(t)+(workNoOwner(t)?(t.origin||linksText(t)?' · ':'')+'<span class="name">'+esc(t.plan)+'</span> · '+workNoOwner(t):'')+(proj?((t.origin||linksText(t)||workNoOwner(t))?' · ':'')+'<span class="r3 mut proj" data-project-shown="1" title="'+esc(t.project)+'">'+esc(short(t.project))+'</span>':'')+'</span>'+(workDesc(t)?'<span class="c-desc">'+esc(workDesc(t))+'</span>':'')+'</div>'
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
function workRows(rows){return '<div class="lhead" aria-hidden="true"><span>Công việc · tình trạng → bước tiếp</span><span>Vì sao</span><span>Kết quả</span><span>Hoạt động cuối</span></div><ul class="lrows" role="listbox" aria-label="Danh sách công việc">'+rows.map(row).join('')+'</ul>'}
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
  var ask=needs.length?'<a href="#needs">'+esc(needs.map(function(x){return needTitle(x)}).join(' · '))+'</a>'
    :s.next_by==='owner'?esc(s.next||'Quyết định của bạn')+'<small>Bước này do OneCrew chỉ ra; trang chưa có mẫu lệnh cho nó.</small>'   // 13/11: never "nothing waits for you" beside "Ai làm tiếp: Bạn"
    :'Không có quyết định nào đang chờ bạn. Điều này không có nghĩa là việc đang tiến triển.';
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
// ---- UI58 MC: the task page — four tiles (output, still valid, next step, your decision), then "Xem sâu" sections opened on demand -------------
var LEVEL_WORDS={produced:'Đã tạo, chưa kiểm',verified:'Đã kiểm đạt',failed:'Đã kiểm, không đạt',accepted:'Đã nghiệm thu',unknown:'Chưa xác định'};
function seqOf(x){var s=x&&x.source;return s&&typeof s.seq==='number'?s.seq:-1}
function outputOf(d){var w=d.work||{},keys=d.evidence_keys||[],outs=(w.outputs||[]).slice().sort(function(a,b){return seqOf(a)-seqOf(b)}),runs=((w.checks||{}).runs||[]).slice().sort(function(a,b){return seqOf(a)-seqOf(b)});
  var cur=outs.filter(function(x){return !x.stale}),pick=(cur.length?cur:outs).slice(-1)[0]||null,r={output:pick,key:null,why:null,receipt:null,log:null,run:null};
  if(!d.work)r.why='Chưa đọc được phần đầu ra của việc này (dữ liệu chi tiết chưa có).';
  else if(!pick)r.why='Sổ chưa ghi đầu ra nào của việc này: chưa có lần tạo đầu ra hay lần kiểm nào nêu một bản bàn giao.';
  else if(pick.artifact&&keys.indexOf(pick.artifact)>=0)r.key=pick.artifact;
  else if(pick.artifact&&/^[0-9a-f]{40}$/.test(pick.artifact))r.why='Đầu ra là bản mã '+pick.artifact.slice(0,12)+'… trong thư mục dự án; sổ không lưu bản này trong kho bằng chứng nên trang không có đích để mở. Kết quả kiểm của bản này mở được bên dưới.';
  else r.why='Đầu ra '+String(pick.artifact||'').slice(0,12)+'… không còn trong kho bằng chứng của sổ: không có đích để mở.';
  var run=pick?runs.filter(function(x){return x.node===pick.node&&x.artifact===pick.artifact}).slice(-1)[0]:null;run=run||runs.slice(-1)[0]||null;r.run=run;
  if(run&&run.receipt&&keys.indexOf(run.receipt)>=0)r.receipt=run.receipt;
  if(run&&run.outputs&&run.outputs.stdout&&keys.indexOf(run.outputs.stdout)>=0)r.log=run.outputs.stdout;
  return r}
function tileOut(d){var o=outputOf(d),x=o.output,h='<section class="tile4" id="t-out" data-k="t-out" aria-label="Đầu ra"><h3>Đầu ra</h3>';
  if(!x)h+='<p class="tv">Chưa có đầu ra</p><p class="why-missing" data-missing="output">'+esc(o.why)+'</p>';
  else{h+='<p class="tv">'+esc(x.title||nodeName(d,x.node))+'</p><p class="small">'+esc(LEVEL_WORDS[x.level]||'Chưa xác định')+(x.stale?' · '+(x.stale_reason==='cần kiểm lại'?'cần kiểm lại trên bản đang xem':'bản cũ'):' · bản mới nhất')+(x.source&&x.source.at?' · '+when(x.source.at):'')+'</p>';
    h+=o.key?'<p class="open-out" data-open-output="'+esc(o.key)+'"><b>Mở đầu ra:</b>'+openBtn(o.key)+'</p>':'<p class="why-missing" data-missing="output-target">'+esc(o.why)+'</p>'}
  if(o.receipt)h+='<p class="open-check" data-open-check="'+esc(o.receipt)+'"><b>Kết quả kiểm mới nhất'+(o.run&&o.run.status?' ('+esc(({pass:'đạt',fail:'không đạt',inconclusive:'chưa kết luận'})[o.run.status]||o.run.status)+')':'')+':</b>'+openBtn(o.receipt)+'</p>';
  else if(x)h+='<p class="why-missing" data-missing="check">Chưa có kết quả kiểm mở được cho đầu ra này: '+(o.run?'biên nhận kiểm không còn trong kho bằng chứng.':'sổ chưa ghi lần kiểm nào của nó.')+'</p>';
  if(o.log)h+='<p class="small">Đầu ra lệnh kiểm (stdout):'+openBtn(o.log)+'</p>';
  return h+'<button type="button" class="linkish" data-deep="evidence">Mọi bằng chứng</button></section>'}
function trustOf(d){if(d.validity)return d.validity;var outs=((d.work||{}).outputs||[]),cur=outs.filter(function(x){return !x.stale}),ok=cur.filter(function(x){return x.level==='verified'||x.level==='accepted'}).length;
  if(!d.work)return {kind:'unknown',label:'Chưa xác định',text:'Chưa đọc được kết quả kiểm của việc này'};
  if(!outs.length)return {kind:'none',label:'Chưa có kết quả kiểm',text:'Sổ chưa ghi lần kiểm nào cho đầu ra của việc này'};
  var all=cur.length&&ok===cur.length;return {kind:all?'valid':cur.length?'parts':'recheck',label:all?'Các phần hiện hành đã kiểm đạt':cur.length?'Theo từng phần':'Cần kiểm lại',
    text:ok+'/'+cur.length+' đầu ra hiện hành đã kiểm đạt'+(outs.length-cur.length?'; '+(outs.length-cur.length)+' bản cũ hoặc cần kiểm lại không được tính':'')}}
function tileTrust(d){var v=trustOf(d),s=sit(d);
  return '<section class="tile4 v-'+esc(v.kind)+'" id="t-trust" data-validity="'+esc(v.kind)+'" aria-label="Còn tin được không"><h3>Còn tin được không</h3><p class="tv">'+esc(v.label)+'</p><p class="small">'+esc(v.text||'')+'</p>'
    +(s.milestones?'<p class="small">'+esc(s.milestones.text)+' <span class="mut">('+esc(s.milestones.note)+')</span></p>':'')
    +(d.compared==='compared'&&d.compared_at?'<p class="small mut">Đã so với bản hiện tại của dự án lúc '+when(d.compared_at)+'.</p>':d.compared==='unknown'?'<p class="why-missing">Chưa xác định bản hiện tại của dự án, nên lần đạt chưa được tính.</p>':'')
    +'<button type="button" class="linkish" data-deep="loop">Xem các lần kiểm</button></section>'}
function tileNext(d){var s=sit(d),done=s.stage==='done'||s.stage==='closed',a=s.activity||{},h='<section class="tile4" id="t-next" aria-label="Bước tiếp theo"><h3>Bước tiếp theo</h3>';
  if(s.next)h+='<p class="next-act" data-next-action="1">'+esc(s.next)+'</p><p class="small">Ai làm: <b>'+esc(s.next_by_text||'Chưa có thông tin người xử lý')+'</b></p>';
  else h+='<p class="tv">'+(done?'Không còn bước nào':'Chưa biết bước tiếp theo')+'</p>'+(done?'':'<p class="why-missing" data-missing="next">Sổ không đủ để nói bước tiếp theo.</p>');
  h+='<p class="small">Vì sao: '+esc(s.reason||'chưa xác định')+'</p>';
  if(s.repairs)h+='<p class="small">Mốc '+esc(s.repairs.milestone)+': '+esc(s.repairs.text)+'</p>';
  if(s.warning)h+='<p class="work-warning small" data-warning="1">'+esc(s.warning)+'</p>';
  return h+'<p class="small mut">'+esc(a.text||'')+'</p><button type="button" class="linkish" data-deep="waits">Thời gian và lượt chờ</button></section>'}
function optHtml(n,o,marks){var c=o.human_command||o.reply_command;
  return '<div class="opt" data-option="'+esc(o.id)+'"><b>'+esc(o.label||o.id)+'</b> <span class="oid">('+esc(o.id)+')</span>'+(o.recommended||n.recommendation===o.id?' <span class="small">· đề xuất</span>':'')
    +'<span class="cons"><b>Hệ quả:</b> '+esc(o.consequence||(n.impact?'câu hỏi không ghi hệ quả riêng cho lựa chọn này; ảnh hưởng chung: '+n.impact:'câu hỏi không ghi hệ quả cho lựa chọn này'))+'</span>'
    +(c?commandBox(c,marks,'Trả lời lựa chọn này'):'')+'</div>'}
function tileDecide(d){var needs=d.needs_user||[],s=sit(d);
  if(!needs.length)return '<section class="tile4" id="t-dec" aria-label="Bạn cần quyết gì"><h3>Bạn cần quyết gì</h3><p class="tv">Không có quyết định nào đang chờ bạn</p>'
    +(s.next_by==='owner'&&s.next?'<p class="small">OneCrew chỉ ra bước của bạn: '+esc(s.next)+'. Trang chưa có mẫu lệnh cho bước này.</p>':'<p class="small mut">Điều này không có nghĩa là việc đang tiến triển.</p>')+'</section>';
  return '<section class="tile4 sit-need" id="t-dec" aria-label="Bạn cần quyết gì"><h3>Bạn cần quyết gì ('+needs.length+')</h3><ul class="declist">'+needs.map(function(n){
    return '<li data-need-row="'+esc(n.id||n.kind)+'"><span class="dsrc">'+esc(n.source_label||({approve:'Kế hoạch chờ bạn duyệt',accept:'Chờ bạn nghiệm thu',stopped:'Đã dừng, chờ bạn quyết'})[n.kind]||'')+'</span><button type="button" class="linkish" data-need-jump="'+esc(needKey(n))+'">'+esc(needTitle(n))+'</button>'
      +((n.options||[]).length?' <span class="small">· '+n.options.length+' lựa chọn</span>':'')+'</li>'}).join('')+'</ul></section>'}
function taskTiles(d){return '<div class="tiles4" data-k="tiles">'+tileOut(d)+tileTrust(d)+tileNext(d)+tileDecide(d)+'</div>'}
function deep(k,title,count,body){return '<details class="deep-d" data-k="deep-'+k+'" id="deep-'+k+'"><summary>'+esc(title)+(count!==''&&count!=null?' <span class="cnt">('+esc(count)+')</span>':'')+'</summary><div class="deep-body">'+body+'</div></details>'}
function deepPlan(d,w){var rows=(w.changes||[]).filter(function(x){return x.kind==='contract'}).slice().reverse();
  if(!rows.length)return workEmpty('Sổ chưa ghi lần đổi hợp đồng nào: việc đang chạy theo bản '+esc(d.contract_revision||1)+'.')+'<button type="button" class="linkish" data-work-tab="changes">Mở tab Thay đổi</button>';
  return rows.map(function(x){var diffs=x.diff||[];return '<article class="work-row" data-change="'+esc(x.id)+'"><h4>Bản '+esc(x.from_revision!=null?x.from_revision:(x.revision-1))+' → bản '+esc(x.revision)+(x.approved?' · đã duyệt':' · chưa duyệt')+'</h4>'
    +'<p><b>Lý do:</b> '+workEsc(x.reason)+'</p>'+diffs.slice(0,6).map(function(v){return '<h4>'+esc(diffLabel(v.path))+'</h4><div class="work-diff"><div><b>Trước</b><br>'+((v.before==null&&v.change==='added')?'Chưa có — nội dung mới được thêm':workEsc(v.before))+'</div><div><b>Sau</b><br>'+workEsc(v.after)+'</div></div>'}).join('')
    +(diffs.length>6||x.diff_total>diffs.length?'<p class="work-meta">Còn '+((x.diff_total||diffs.length)-Math.min(6,diffs.length))+' mục thay đổi khác trong tab Thay đổi.</p>':'')+(x.diff_error?workEmpty(x.diff_error):'')+workSource(x)+'</article>'}).join('')
    +'<button type="button" class="linkish" data-work-tab="changes">Mở tab Thay đổi</button>'}
function loopSteps(r){var out=[],fixes=0,checks=r.checks||[];
  checks.forEach(function(c,i){var prev=checks[i-1];if(prev&&prev.result&&prev.result!=='pass'){fixes++;out.push({k:'fix',t:'Sửa (lượt '+fixes+') rồi kiểm lại'})}
    var k=c.state==='open'?'open':c.state==='lost'||c.state==='abandoned'?'lost':c.result==='pass'?'pass':c.result==='inconclusive'?'recheck':c.result?'fail':'open';
    out.push({k:k,t:'Lần kiểm '+(i+1)+': '+checkWord(c)+((k==='fail'||k==='recheck')&&i===checks.length-1&&r.reason?' — '+r.reason:''),at:c.recorded||c.ended||c.started})});
  if(r.state==='recheck')out.push({k:'recheck',t:'Mã hoặc quy tắc kiểm đã đổi sau lần đạt: cần kiểm lại trên bản đang xem'+(r.note?' ('+r.note+')':'')});
  if(r.repairs&&typeof r.repairs.left==='number'&&checks.length&&checks[checks.length-1].result&&checks[checks.length-1].result!=='pass')out.push({k:'next',t:r.repairs.text});
  return out}
function deepLoop(d,w){var c=d.milestone_checks,h='';
  if(c){var rows=(c.rows||[]).filter(function(r){return (r.checks||[]).length||r.state==='recheck'});
    h+=rows.length?rows.map(function(r){return '<article class="work-row" data-loop="'+esc(r.id)+'"><h4>'+esc(r.id)+(r.title?' — '+esc(r.title):'')+' · '+esc(r.label)+'</h4><ol class="loop">'+loopSteps(r).map(function(s){return '<li class="'+esc(s.k)+'">'+esc(s.t)+(s.at?' <span class="work-meta">· '+when(s.at)+'</span>':'')+'</li>'}).join('')+'</ol></article>'}).join('')
      :workEmpty('Chưa có lần kiểm nào của các mốc trong hợp đồng hiện hành.');
    return h+'<button type="button" class="linkish" data-work-tab="progress">Mở Tiến độ · các mốc</button>'}
  var rp=workRepairFlow(d,w);return (rp||workEmpty('Sổ không ghi vòng sửa nào của việc này (chưa có lần kiểm không đạt dẫn tới việc sửa).'))+'<button type="button" class="linkish" data-work-tab="results">Mở Kết quả &amp; kiểm chứng</button>'}
function deepWaits(d){var ws=(d.waits||[]).slice().sort(function(a,b){return String(a.since).localeCompare(String(b.since))}),h='';
  h+=ws.length?'<ol class="loop waitline">'+ws.map(function(x){var end=x.open?'đang chờ':x.until==='unknown'?'chưa rõ kết thúc':when(x.until),sec=(!x.open&&x.until&&x.until!=='unknown')?(new Date(x.until)-new Date(x.since))/1000:null;
      return '<li class="'+(x.open?'recheck':'')+'" data-wait="'+esc(x.seq)+'">Chờ: '+esc(x.reason||'không rõ lý do')+' · từ '+when(x.since)+' → '+esc(end)+(typeof sec==='number'&&isFinite(sec)?' ('+hms(sec)+')':'')+(x.node?' · phần việc '+esc(x.node):'')+' <span class="work-meta">· nguồn '+esc(x.source)+' #'+esc(x.seq)+'</span></li>'}).join('')+'</ol>'
    :workEmpty('Sổ không ghi khoảng chờ nào của việc này. Khoảng trống giữa hai lần kiểm không phải thời gian chờ.');
  return h+'<button type="button" class="linkish" data-work-tab="progress">Mở dòng thời gian đầy đủ (Tiến độ)</button>'}
function deepEvidence(d){var P=prov(d),keys=P.keys.slice().sort(function(a,b){var x=P.byKey[a],y=P.byKey[b];return (y[y.length-1].seq||0)-(x[x.length-1].seq||0)});
  if(!keys.length)return workEmpty('Sổ chưa nêu bằng chứng nào của việc này.');
  return '<p class="work-meta">Mới nhất trước; mỗi mục mở qua cửa bằng chứng chỉ đọc của việc này (lọc bí mật).</p>'+keys.slice(0,20).map(function(k){var u=P.byKey[k],x=u[u.length-1];
    return '<div class="small" data-k="dev:'+k+'" data-evidence="'+k+'">'+occLine(x)+openOr(x)+'</div>'}).join('')+(keys.length>20?'<p class="work-meta">Còn '+(keys.length-20)+' mục cũ hơn ở “Số đo và nhật ký kỹ thuật”.</p>':'')}
function deepSections(d){var w=d.work||{},ch=(w.changes||[]).filter(function(x){return x.kind==='contract'}).length,c=d.milestone_checks,
    nloop=c?(c.rows||[]).reduce(function(n,r){return n+(r.checks||[]).length},0):(w.repairs||[]).length,P=prov(d);
  return '<section class="deep" aria-label="Xem sâu"><h3>Xem sâu</h3>'+deep('plan','Thay đổi kế hoạch (trước / sau)',ch,deepPlan(d,w))
    +deep('loop',c?'Lần kiểm: lỗi → sửa → kiểm lại':'Vòng sửa: lỗi → sửa → kiểm lại',nloop,deepLoop(d,w))
    +deep('waits','Thời gian chờ và dòng thời gian',(d.waits||[]).length,deepWaits(d))
    +deep('evidence','Bằng chứng',P.keys.length,deepEvidence(d))
    +deep('summary','Tóm tắt: đang ở đâu, vướng gì, ai làm tiếp','',sitPanel(d))+'</section>'}
function msStrip(d){var c=d.milestone_checks;if(!c||!(c.rows||[]).length)return '';
  return '<div class="ms-strip" aria-label="Các mốc">'+c.rows.map(function(m){return '<span class="ms '+esc(m.state)+'" title="'+esc(m.title||'')+'"><b>'+esc(m.id)+'</b> '+esc(m.label)+'</span>'}).join('')+'<button type="button" class="linkish" data-work-tab="progress">Xem các mốc và lần kiểm</button></div>'}
function workOverview(d,w){var o=(w.outputs||[]).filter(function(x){return !x.stale}),f=w.findings||[],open=f.filter(function(x){return (x.status||x.state)==='open'}).length,c=d.milestone_checks,m=d.measure||{};
  var checkTime=c?(c.rows||[]).reduce(function(t,r){return typeof r.check_seconds==='number'?(t||0)+r.check_seconds:t},null):null;
  return workOwnerSection(d)+msStrip(d)
    +'<div class="work-grid">'+workCard('Kết quả đã có',o.length?o.length+' đầu ra hiện hành · '+o.filter(function(x){return x.level==='verified'||x.level==='accepted'}).length+' đã kiểm':((w.outputs||[]).length?'Không có đầu ra hiện hành · '+(w.outputs||[]).length+' bản cũ hoặc cần kiểm lại':'Chưa ghi nhận đầu ra'),'Lịch sử cũ không tính vào số này. Xem từng đầu ra trong Kết quả & kiểm chứng.')
    +workCard('Dự kiến còn lại',d.eta&&d.eta.label,d.eta&&d.eta.reason)+'</div>'
    +(open?'<p class="work-warning">Còn '+open+' finding đang mở. Đây chưa phải số bug độc lập.</p>':'')
    +(c?'<p class="work-meta">Thời gian chạy bộ kiểm đã ghi: '+(checkTime===null?'chưa có lần kiểm nào đủ mốc thời gian':hms(checkTime))+'. Đây là thời gian kiểm, không phải thời gian làm việc; việc không chạy qua engine nên không có số đo thực hiện.</p>'
      :'<p class="work-meta">Thời gian đã trôi qua: '+hms(d.elapsed&&d.elapsed.seconds)+' · Thực hiện đã ghi nhận: '+hms(m.attempts_wall_seconds)+' · Chờ đã ghi nhận: '+hms(m.wait_seconds)+'. Không tự quy thời gian chưa rõ thành thời gian làm việc.</p>')
    +relSection(d)}
// OBS-2C: "Nguồn và quan hệ" — display only, every line names the ledger event it comes from; what no producer records says "chưa theo dõi"
function relSrc(s){return s&&s.kind?' <span class="work-meta">· nguồn '+esc(s.kind)+(s.seq!=null?' #'+esc(s.seq):'')+(s.at?' · '+esc(when(s.at)):'')+'</span>':''}
var REPAIR_WORDS={verified:'Đã kiểm lại đủ phần ảnh hưởng',partial:'Mới kiểm lại một phần',unverified:'Chưa kiểm lại đủ'};
// repair 1 of 14/11: each item says WHAT it is (kind word), its name when the ledger records one (else "chưa có tên trong sổ", never an
// invented one) and its sourced state; the raw id is only a short secondary text; the button opens the tab of this detail that shows it.
// Its key is data-relation, never data-rel: that attribute belongs to the page's relative-time <time> elements (repair 2 of 14/11)
var REL_KIND={repair:'Việc sửa',child:'Phần việc con'},REL_OPENS={results:'Xem ở Kết quả & kiểm chứng',progress:'Xem ở Tiến độ'};
function relName(x,d){if(x.kind==='repair')return 'cho phần việc '+(x.name?esc(x.name):'<span class="rel-noname">chưa có tên trong sổ</span>');return x.name?esc(x.name):'<span class="rel-noname">chưa có tên trong sổ</span>'}
function relItem(x,d){var root=x.root||{},h='<article class="rel-item" data-relation="'+esc(x.kind)+':'+esc(x.id)+'"><h4><span class="rel-kind">'+esc(REL_KIND[x.kind]||x.label||'Việc liên quan')+'</span> · '+relName(x,d)+'</h4>'
    +'<p class="rel-meta"><span class="rel-state">'+esc(x.state_label||'trạng thái chưa xác định')+'</span> · <span class="org ai">AI phát sinh</span> '+esc(x.source_label||'')+'</p>';
  if(x.kind==='repair'){h+='<p><b>Lý do:</b> '+esc(x.reason||'chưa theo dõi')+'</p>'
      +'<p><b>Từ lần kiểm không đạt:</b> '+(x.from_check&&x.from_check.seq!=null?'sự kiện #'+esc(x.from_check.seq):'chưa theo dõi')+((x.failed_checks||[]).length?' · kiểm không đạt: '+esc(x.failed_checks.join(', ')):'')+(x.from_check&&x.from_check.receipt?' '+workEvidence(d,x.from_check.receipt):'')+'</p>'
      +((x.affected_nodes||[]).length?'<p><b>Phần ảnh hưởng:</b> '+esc(x.affected_nodes.map(function(n){return nodeName(d,n)}).join(', '))+'</p>':'')
      +(x.rebindings?'<p class="work-meta">'+x.rebindings+' lần nối lại thứ tự (không tính là vòng sửa mới)</p>':'')}
  else h+='<p><b>Của phần việc:</b> '+esc(nodeName(d,x.node))+(typeof x.generation==='number'?' · thế hệ '+x.generation:'')+'</p>'
      +'<p><b>Lượt chạy:</b> '+((x.attempts||[]).length?x.attempts.length+' lượt · gần nhất: '+esc(x.state_label):'chưa có lượt chạy ghi nhận')+'</p>';
  return h+'<p class="rel-root"><b>Nối với việc gốc:</b> '+esc(root.plan||'chưa theo dõi')+' (việc đang xem)'+relSrc(x.source)+((x.also||[]).length?' · còn được nêu ở '+x.also.map(function(s){return '#'+esc(s)}).join(', ')+' (đếm một lần)':'')+'</p>'
    +'<p class="rel-foot">'+(REL_OPENS[x.opens]?'<button type="button" class="linkish" data-work-tab="'+esc(x.opens)+'">'+REL_OPENS[x.opens]+'</button> ':'')+'<span class="work-meta rel-id" title="'+esc(x.id)+'">mã '+esc(x.short_id||x.id)+'</span></p></article>'}
function relSection(d){var r=d.relations,o=d.origin||(r&&r.origin);if(!r&&!o)return '';r=r||{};var a=(o&&o.approval)||{},end=r.end,sp=r.spawned||[],revs=r.revisions||[];
  var h='<section class="rel" id="relations" aria-label="Nguồn và quan hệ" data-k="relations"><h3>Nguồn và quan hệ</h3><div class="rel-grid">'
    +'<div><b>Nguồn giao việc</b><span>'+orgBadge(o)+'</span><small>'+esc((o&&o.why)||'chưa theo dõi')+'</small></div>'
    +'<div><b>Yêu cầu ban đầu</b><span>'+esc((o&&o.request)||'chưa theo dõi')+'</span><small>'+esc((o&&o.request_note)||'')+'</small></div>'
    +'<div><b>Duyệt</b><span>'+esc(a.label||'chưa duyệt')+'</span>'+(a.session==='unknown'?'<small>Phiên duyệt không khai báo là của người nào: không kết luận là phiên AI.</small>':'')+'</div>'
    +'<div><b>Kết thúc</b><span>'+esc(end?end.label:'chưa kết thúc')+'</span>'+(end&&end.reason?'<small>'+esc(end.reason)+'</small>':'')+'</div></div>';
  h+='<h4 class="rel-h">Việc phát sinh từ việc này ('+sp.length+')</h4>'+(sp.length?sp.map(function(x){return relItem(x,d)}).join(''):workEmpty('Sổ không ghi việc sửa hay việc con nào của việc này.'));
  h+='<details data-k="rel-revisions"><summary>Các bản hợp đồng ('+revs.length+')</summary>'+(revs.length?revs.map(function(v){return '<div class="rel-item"><b>Bản '+esc(v.revision)+'</b> · '+(v.kind==='proposed'?'đề xuất':'sửa')+' bởi '+esc(v.author||'chưa ghi')+(v.author_is_owner?' (chủ sở hữu)':'')
      +(v.reason?'<p><b>Lý do:</b> '+esc(v.reason)+'</p>':'')+(v.impact?'<p><b>Ảnh hưởng:</b> '+esc(v.impact)+'</p>':'')+relSrc(v.source)+'</div>'}).join(''):workEmpty('Chưa có bản hợp đồng đọc được.'))+'</details>';
  return h+'<p class="work-meta">Việc gốc của việc này: '+esc(((r.parent||{}).note)||'chưa theo dõi')+' — chưa theo dõi. '+esc(r.not_tracked||'')+'</p></section>'}
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
