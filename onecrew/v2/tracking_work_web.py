"""Small read-only work views. Uses the tracking page's escaping/evidence door."""

STYLE = r'''
.work-nav{display:flex;gap:6px;flex-wrap:wrap;margin:18px 0 12px;border-bottom:1px solid var(--line);padding-bottom:10px}
.work-nav button{padding:8px 12px;border-color:transparent;font-weight:600}
.work-nav button[aria-selected=true]{color:var(--run);background:var(--sel);border-color:var(--run)}
.work-panel{min-width:0;margin:8px 0 16px}.work-panel h3{font-size:16px;margin:16px 0 8px}
.work-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.work-card{padding:14px;border:1px solid var(--line);border-radius:10px;min-width:0;overflow-wrap:anywhere}
.work-card .eyebrow{font-size:12px;color:var(--mut);margin-bottom:6px}.work-card .answer{font-size:15px;font-weight:600}
.work-card p{margin:6px 0}.work-row{padding:12px 0;border-top:1px solid var(--line);overflow-wrap:anywhere}
.work-row:first-child{border-top:0}.work-row h4{font-size:14px;margin-bottom:4px}.work-row ul{padding-left:20px}
.work-empty{padding:14px;background:var(--bg);border-radius:8px;color:var(--mut)}
.work-meta{font-size:12px;color:var(--mut);margin:6px 0}.work-diff{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:8px}
.work-diff>div{padding:8px;background:var(--bg);border-radius:6px;white-space:pre-wrap;overflow-wrap:anywhere}
.work-panel table td{white-space:normal;overflow-wrap:anywhere}.work-panel table{table-layout:fixed;width:100%}
.work-panel pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:40vh;overflow:auto;padding:12px;background:var(--bg);border-radius:6px}
body{font-size:15px;line-height:1.55}header{padding:16px 24px}h1{font-size:21px}.tools{gap:14px;margin-top:14px}.tools label{font-size:13px}
main[data-view=list]{display:block}main[data-view=list] #detailpane{display:none}main[data-view=detail]{grid-template-columns:310px minmax(0,1fr)}
#listpane{background:transparent;border:0;padding:0}#listpane>h2{font-size:15px;text-transform:none;letter-spacing:0;margin:0 0 12px}
#list{display:flex;gap:14px;overflow-x:auto;align-items:flex-start;padding:2px 0 16px;margin:0;list-style:none}
.board-lane{flex:1 0 235px;min-width:0;background:var(--bg);border:1px solid var(--line);border-radius:12px;padding:12px}
.lane-title{display:flex;justify-content:space-between;align-items:center;font-size:14px;margin:0 0 12px}.lane-title span{font-size:12px;color:var(--mut)}
.board-lane ul{list-style:none;padding:0;margin:0}.lane-empty{font-size:13px;color:var(--mut);padding:12px 0}
li.task{border:1px solid var(--line);border-radius:10px;background:var(--card);box-shadow:0 2px 5px #00000006;padding:14px;margin:0 0 10px;cursor:pointer}
li.task[aria-selected=true]{border-color:var(--run);box-shadow:0 0 0 1px var(--run);background:var(--sel)}
.task .r1{display:block}.task .ttl{display:block;font-size:15px;font-weight:650;white-space:normal;overflow:visible;line-height:1.45;margin:6px 0}
.task .r2{display:block;font-size:13px}.task .r2>span{display:block;margin-top:6px}.task .name{font-size:11px;color:var(--mut);font-weight:500}.task .st{font-size:12px;white-space:normal}
.task .r3{display:block;font-size:12px;margin-top:8px;color:var(--mut)}.needb{display:inline-block;margin:8px 0 0;padding:3px 8px;border-radius:5px}
main[data-view=detail] #list{display:block;overflow:visible}main[data-view=detail] .board-lane{margin-bottom:12px;padding:10px}main[data-view=detail] .board-lane.empty{display:none}
#detailpane{padding:22px;max-height:calc(100vh - 165px)}.dhead h2{font-size:20px;line-height:1.4;color:var(--fg);text-transform:none;letter-spacing:0}.dhead .st{display:block;width:fit-content;margin-top:8px}
.connection-details{font-size:12px;color:var(--mut);margin-top:10px}.connection-details summary{cursor:pointer}.connection-details .note{margin:8px 0}.sample-banner{padding:8px 12px;background:var(--sel);border-radius:6px;margin-top:10px;font-size:13px}
.need{padding:16px;border:1px solid var(--line);border-radius:10px}.need .q{font-size:16px}.command-box{margin:14px 0;background:var(--bg);border:1px solid var(--line);border-radius:8px;overflow:hidden}
.command-head{padding:8px 12px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--line);gap:8px;font-size:13px}.command-box pre{margin:0;padding:14px;overflow-x:auto;white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.65 Consolas,monospace}.command-box .copy{white-space:nowrap}.command-box code{background:transparent;padding:0;font:inherit;color:var(--fg)}
.work-row h4{font-size:16px}.work-meta{font-size:13px}.work-row details{margin:10px 0}.work-nav button{font-size:14px}.work-id{font-size:13px;font-weight:500;color:var(--mut)}.stage-note{font-size:13px;color:var(--mut);margin:0 0 12px}
.repair-flow{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.repair-flow>div{border:1px solid var(--line);border-radius:8px;padding:12px;overflow-wrap:anywhere}.repair-flow b{display:block;margin-bottom:8px}
@media(max-width:899px){main[data-view=detail]{display:block}#detailpane{max-height:none;padding:16px}#list{display:block}.board-lane{margin:0 0 12px}.board-lane.empty{display:none}header{padding:12px}.repair-flow{grid-template-columns:1fr}.dhead h2{font-size:18px}}
#legacy-progress[hidden]{display:none}.work-warning{border-left:3px solid var(--wait);padding:8px 12px;background:var(--need);color:var(--needfg)}
@media(max-width:600px){.work-grid,.work-diff{grid-template-columns:1fr}.work-nav{gap:3px}.work-nav button{font-size:12px;padding:8px}.work-card{padding:10px}}
'''

SCRIPT = r'''
var workTab='overview';
var WORK_TABS=[['overview','Tổng quan'],['solution','Solution'],['changes','Thay đổi'],['results','Kết quả & kiểm chứng'],['progress','Tiến độ']];
var WORK_STAGES=[['todo','Chưa bắt đầu'],['doing','Đang xử lý'],['check','Chờ kiểm'],['accept','Chờ nghiệm thu'],['done','Hoàn tất'],['closed','Đã đóng'],['unknown','Chưa xác định']];
function workStage(t){var s=t.status||{},n=t.nodes_summary||{},l=(t.level||{}).kind;
  if(t.root_status==='closed'||s.outcome==='closed')return 'closed';
  if(t.root_status==='accepted'||s.outcome==='accepted')return 'done';
  if(s.kind==='unknown')return 'unknown';
  if((t.active||[]).length||s.kind==='running')return 'doing';
  if(t.root_status==='proposed'||(t.needs_user||[]).some(function(n){return n.kind==='approve'}))return t.has_started||l==='verified'||l==='produced'?'doing':'todo';
  if((t.acceptance||{}).ready)return 'accept';
  if(n.produced>0||(t.milestones||[]).some(function(m){return m.state==='ready'}))return 'check';
  if(s.kind==='blocked'||n.verified>0||n.accepted>0)return 'doing';
  if(t.has_started||(t.milestones||[]).some(function(m){return (!!m.state&&m.state!=='pending')||!!m.last_verdict}))return 'doing';     // R7-2: the API's own milestone states (passed/failed/stopped) and has_started (verdicts, runs, attempts)
  if(t.root_status==='approved'||t.root_status==='proposed')return 'todo';return 'unknown'}
function workStatus(t){var needs=t.needs_user||[],s=t.status||{},n=t.nodes_summary||{},stage=workStage(t),request=needs.find(function(n){return n.kind==='request'});
  if(s.label==='đã dừng')return 'Đã dừng · chờ bạn quyết định';
  if(s.kind==='blocked')return 'Có trở ngại'+((t.active||[]).length?' · phần khác vẫn thực hiện':'');
  if(t.root_status==='proposed'||needs.some(function(n){return n.kind==='approve'}))return (t.active||[]).length?'Đang thực hiện · chờ duyệt thay đổi':'Chờ bạn duyệt kế hoạch';
  if(s.kind==='running')return 'Đang thực hiện';
  if(request)return 'Chờ bạn trả lời';
  if(stage==='check')return 'Đã có đầu ra · chờ kiểm';
  if(stage==='accept')return 'Đã kiểm đạt · chờ nghiệm thu';
  if(stage==='done')return 'Đã nghiệm thu';if(stage==='closed')return 'Đã đóng · không phải nghiệm thu';
  if(stage==='todo')return 'Chưa khởi chạy';if(stage==='doing'&&t.has_started&&!(t.milestones||[]).length)return 'Chờ bước tiếp theo';   // a milestone root says which milestone (its sourced step below)
  return t.current_step||s.reason||'Chưa xác định tiến độ'}
function workTitle(t){return t.goal||t.title||t.plan||'Công việc chưa có tên'}
function workBadge(t){var s=t.status||{};return '<span class="st '+esc(s.kind||'unknown')+'">'+esc(workStatus(t))+'</span>'}
function workOrder(rows,mode){function time(x){var n=Date.parse(x||'');return Number.isFinite(n)?n:null}function attention(t){return (t.needs_user||[]).length?0:(t.status||{}).kind==='blocked'?1:(t.status||{}).kind==='running'?2:3}
  return rows.slice().sort(function(a,b){var x,y;if(mode==='attention'){x=attention(a)-attention(b);if(x)return x;mode='attention'}
    if(mode==='created'){x=time(a.created_at);y=time(b.created_at)}else if(mode==='deadline'){x=time(a.deadline);y=time(b.deadline)}else{x=time(a.last_update&&a.last_update.at);y=time(b.last_update&&b.last_update.at)}
    if(x!==y){if(x===null)return 1;if(y===null)return -1;return mode==='created'||mode==='deadline'?x-y:y-x}
    return String(a.project_id||'').localeCompare(String(b.project_id||''))||String(a.selector||a.id||'').localeCompare(String(b.selector||b.id||''))})}
function workBoard(rows){return WORK_STAGES.map(function(s){var items=rows.filter(function(t){return workStage(t)===s[0]});return '<section class="board-lane'+(!items.length?' empty':'')+'" data-stage="'+s[0]+'" aria-label="'+s[1]+'"><h3 class="lane-title">'+s[1]+' <span>'+items.length+'</span></h3><ul role="listbox" aria-label="'+s[1]+'">'+items.map(row).join('')+'</ul>'+(!items.length?'<div class="lane-empty">Không có công việc</div>':'')+'</section>'}).join('')}
function workText(v){if(v==null||v===''||(Array.isArray(v)&&!v.length))return 'chưa có dữ liệu';if(typeof v!=='object')return String(v);
  if(Array.isArray(v))return v.map(workText).join('; ');return v.text||v.title||v.label||v.spec||v.question||v.goal||Object.keys(v).map(function(k){return k+': '+workText(v[k])}).join('; ')||'chưa có dữ liệu'}
function workEsc(v){return esc(workText(v))}
function workOutputs(d,o){if(!o)return '';var n=function(b){return b==null?'':' ('+esc(b)+' byte)'};return '<p>Đầu ra lệnh kiểm, mã thoát '+esc(o.exit_code==null?'chưa rõ':o.exit_code)+(o.timed_out?', hết thời gian':'')+': stdout'+n(o.stdout_bytes)+' '+workEvidence(d,o.stdout)+' · stderr'+n(o.stderr_bytes)+' '+workEvidence(d,o.stderr)+(o.truncated?' · chỉ giữ phần cuối':'')+'</p>'}
function workEmpty(t){return '<div class="work-empty">'+esc(t)+'</div>'}
function workCard(label,value,note){return '<div class="work-card"><div class="eyebrow">'+esc(label)+'</div><div class="answer">'+workEsc(value)+'</div>'+(note?'<p class="work-meta">'+esc(note)+'</p>':'')+'</div>'}
function workSource(x){var s=x&&x.source,q=s&&(s.seq!=null?s.seq:s.verdict_seq);return s?'<details class="work-meta"><summary>Nguồn đối chiếu</summary><div>Nguồn: '+esc(s.kind||'receipt')+(q!=null?' #'+esc(q):'')+((x.at||s.at)?' · '+esc(when(x.at||s.at)):'')+'</div></details>':''}
function workEvidence(d,k){return k&&(d.evidence_keys||[]).indexOf(k)>=0?openBtn(k):'<span class="work-meta">Chưa có bằng chứng mở được từ task này</span>'}
function nodeName(d,id){var w=d.work||{},n=(w.node_titles||w.nodes||{})[id];return n?workText(n)+' ('+id+')':id||'chưa rõ phần việc'}
function workOverview(d,w){var o=(w.outputs||[]).filter(function(x){return !x.stale}),f=w.findings||[],open=f.filter(function(x){return (x.status||x.state)==='open'}).length;
  return '<div class="work-grid">'+workCard('Hiện tại',workStatus(d),d.current_step||d.status.reason)
    +workCard('Kết quả đã có',o.length?o.length+' đầu ra hiện hành · '+o.filter(function(x){return x.level==='verified'||x.level==='accepted'}).length+' đã kiểm':'Chưa ghi nhận đầu ra','Lịch sử cũ không tính vào số này. Xem từng đầu ra trong Kết quả & kiểm chứng.')
    +workCard('Việc cần bạn',(d.needs_user||[]).length?(d.needs_user.map(function(n){return n.title||(n.kind==='approve'?'Duyệt kế hoạch':n.kind==='accept'?'Nghiệm thu':n.question||'Trả lời câu hỏi')}).join(' · ')):'Chưa có yêu cầu cần bạn xử lý','Đọc câu hỏi không đồng nghĩa đã trả lời hoặc đã duyệt.')
    +workCard('Dự kiến còn lại',d.eta&&d.eta.label,d.eta&&d.eta.reason)+'</div>'
    +(open?'<p class="work-warning">Còn '+open+' finding đang mở. Đây chưa phải số bug độc lập.</p>':'')
    +'<p class="work-meta">Thời gian đã trôi qua: '+hms(d.elapsed&&d.elapsed.seconds)+' · Thực hiện đã ghi nhận: '+hms(d.measure&&d.measure.attempts_wall_seconds)+' · Chờ đã ghi nhận: '+hms(d.measure&&d.measure.wait_seconds)+'. Không tự quy thời gian chưa rõ thành thời gian làm việc.</p>'}
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
  var levels={produced:'Đã tạo',verified:'Đã kiểm',accepted:'Đã nghiệm thu',unknown:'Chưa xác định'};
  var current=outputs.filter(function(x){return !x.stale}),history=outputs.filter(function(x){return x.stale});
  function outputRows(items){return items.map(function(x){return '<article class="work-row"><h4>'+workEsc(x.title||x.label||nodeName(d,x.node))+' · '+esc(levels[x.level]||'Chưa xác định')+'</h4>'
    +'<p class="work-meta">'+esc(nodeName(d,x.node))+' · '+(x.stale?'Bản cũ / cần kiểm lại · ':'')+(x.inherited?'Kế thừa · ':'')+'Thế hệ '+workEsc(x.generation)+'</p>'
    +(x.inherited&&x.from_generation!=null?'<p class="work-meta">Kế thừa từ thế hệ '+workEsc(x.from_generation)+' · lượt tạo '+workEsc(x.from_attempt)+'</p>':'')
    +workEvidence(d,x.artifact||x.key)+workSource(x)+'</article>'}).join('')}
  var h='<h3>Kết quả hiện hành</h3>'+(current.length?outputRows(current):workEmpty('Chưa có đầu ra hiện hành được ghi nhận.'))
    +(history.length?'<details data-k="work-history"><summary>Đầu ra lịch sử ('+history.length+')</summary>'+outputRows(history)+'</details>':'')
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
function workDashboard(d){var w=d.work;if(!w)return '';var content=workTab==='solution'?workSolution(d,w):workTab==='changes'?workChanges(d,w):workTab==='results'?workResults(d,w):workTab==='overview'?workOverview(d,w):gantt(d)+workProgress(d);
  return '<nav class="work-nav" role="tablist" aria-label="Chi tiết công việc">'+WORK_TABS.map(function(t){return '<button type="button" role="tab" data-work-tab="'+t[0]+'" id="work-tab-'+t[0]+'" data-k="work-tab:'+t[0]+'" aria-selected="'+(workTab===t[0])+'" aria-controls="work-content">'+t[1]+'</button>'}).join('')+'</nav>'
    +'<section id="work-content" class="work-panel" role="tabpanel" aria-labelledby="work-tab-'+workTab+'">'+content
    +((w.limitations||[]).length?'<details data-k="work-limits"><summary>Giới hạn dữ liệu ('+w.limitations.length+')</summary>'+workList(w.limitations,'')+'</details>':'')+'</section>'}
'''
