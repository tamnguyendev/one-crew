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
#legacy-progress[hidden]{display:none}.work-warning{border-left:3px solid var(--wait);padding:8px 12px;background:var(--need);color:var(--needfg)}
@media(max-width:600px){.work-grid,.work-diff{grid-template-columns:1fr}.work-nav{gap:3px}.work-nav button{font-size:12px;padding:8px}.work-card{padding:10px}}
'''

SCRIPT = r'''
var workTab='overview';
var WORK_TABS=[['overview','Tổng quan'],['solution','Solution'],['changes','Thay đổi'],['results','Kết quả & kiểm chứng'],['progress','Tiến độ']];
function workText(v){if(v==null||v===''||(Array.isArray(v)&&!v.length))return 'chưa có dữ liệu';if(typeof v!=='object')return String(v);
  if(Array.isArray(v))return v.map(workText).join('; ');return v.text||v.title||v.label||v.spec||v.question||v.goal||Object.keys(v).map(function(k){return k+': '+workText(v[k])}).join('; ')||'chưa có dữ liệu'}
function workEsc(v){return esc(workText(v))}
function workEmpty(t){return '<div class="work-empty">'+esc(t)+'</div>'}
function workCard(label,value,note){return '<div class="work-card"><div class="eyebrow">'+esc(label)+'</div><div class="answer">'+workEsc(value)+'</div>'+(note?'<p class="work-meta">'+esc(note)+'</p>':'')+'</div>'}
function workSource(x){var s=x&&x.source,q=s&&(s.seq!=null?s.seq:s.verdict_seq);return s?'<div class="work-meta">Nguồn: '+esc(s.kind||'receipt')+(q!=null?' #'+esc(q):'')+((x.at||s.at)?' · '+esc(when(x.at||s.at)):'')+'</div>':''}
function workEvidence(d,k){return k&&(d.evidence_keys||[]).indexOf(k)>=0?openBtn(k):'<span class="work-meta">Chưa có bằng chứng mở được từ task này</span>'}
function nodeName(d,id){var w=d.work||{},n=(w.node_titles||w.nodes||{})[id];return n?workText(n)+' ('+id+')':id||'chưa rõ phần việc'}
function workOverview(d,w){var o=w.outputs||[],f=w.findings||[],open=f.filter(function(x){return (x.status||x.state)==='open'}).length;
  return '<div class="work-grid">'+workCard('Hiện tại',d.current_step||d.status.label,d.status.reason)
    +workCard('Kết quả đã có',o.length?o.length+' mục đầu ra có nguồn':'Chưa ghi nhận đầu ra','Mở “Kết quả & kiểm chứng” để xem mức kiểm của từng mục.')
    +workCard('Việc cần bạn',(d.needs_user||[]).length?(d.needs_user.length+' yêu cầu đang chờ ở phía trên'):'Chưa có yêu cầu cần bạn xử lý','Đọc câu hỏi không đồng nghĩa đã trả lời hoặc đã duyệt.')
    +workCard('Dự kiến còn lại',d.eta&&d.eta.label,d.eta&&d.eta.reason)+'</div>'
    +(open?'<p class="work-warning">Còn '+open+' finding đang mở. Đây chưa phải số bug độc lập.</p>':'')
    +'<p class="work-meta">Thời gian đã trôi qua: '+hms(d.elapsed&&d.elapsed.seconds)+' · Thực hiện đã ghi nhận: '+hms(d.measure&&d.measure.attempts_wall_seconds)+' · Chờ đã ghi nhận: '+hms(d.measure&&d.measure.wait_seconds)+'. Không tự quy thời gian chưa rõ thành thời gian làm việc.</p>'}
function workSolution(d,w){var s=w.solution||{},c=s.contract||{},card=s.card||{},ref=s.source_solution;
  return '<div class="work-grid">'+workCard('Bản đề xuất mới nhất',s.latest_revision)+workCard('Bản được duyệt',s.approved_revision)
    +workCard('Bản có thể thực hiện',s.runnable_revision,'Bản đề xuất mới không tự thay thế bản đang được phép chạy. Không có bản chạy được thì chưa suy quyền thực hiện.')+workCard('Mục tiêu',c.goal||d.goal)+'</div>'
    +((s.latest_revision!=null&&s.latest_revision!==s.approved_revision)?'<p class="work-warning">Có bản chưa được duyệt. Chỉ các phần được cơ chế quyền cho phép mới tiếp tục.</p>':'')
    +(s.frozen?'<p class="work-warning">Phần được tiếp tục: '+workEsc(s.frozen.runnable)+'; phần chờ bản mới: '+workEsc(s.frozen.frozen)+'</p>':'')
    +'<h3>Phương án và phạm vi</h3><div class="work-grid">'+workCard('Trước → sau',card.before||card.after?[card.before,card.after]:null)
    +workCard('Phương án ưu tiên',card.preferred,card.why?workText(card.why):null)+workCard('Giữ nguyên',card.preserve||c.preserve)+workCard('Phạm vi',c.scope)+'</div>'
    +'<h3>Điều kiện hoàn thành</h3>'+workList(c.acceptance||card.acceptance,'Hợp đồng chưa cung cấp điều kiện hiển thị được.')
    +'<h3>Điều còn chưa rõ</h3>'+workList(card.unknowns_open,'Chưa ghi nhận câu hỏi mở trong thẻ solution; điều này không chứng nhận mọi thứ đã được kiểm.')
    +(ref?'<div class="work-row"><h4>Solution nguồn v1</h4><p>'+workEsc(ref.id)+' · revision '+workEsc(ref.revision)+'</p>'
      +(ref.status==='available'?Object.keys(ref.payload||{}).map(function(k){return '<p><b>'+esc(({brief:'Tóm tắt',detail:'Nội dung',before:'Trước',after:'Sau',preferred:'Phương án',why:'Lý do',preserve:'Giữ nguyên',acceptance:'Điều kiện hoàn thành',non_goals:'Ngoài phạm vi',assumptions:'Giả định',questions:'Câu hỏi'})[k]||k)+':</b> '+workEsc(ref.payload[k])+'</p>'}).join(''):workEmpty('Không đọc được SOL đúng phạm vi và revision; không sử dụng nội dung chưa xác minh.'))
      +'<p class="work-meta">Nguồn solution không thay quyền của hợp đồng task.</p></div>':workEmpty('Task không có SOL v1 liên kết; dùng hợp đồng và thẻ bước 0 có sẵn.'))}
function workList(rows,empty){if(!rows||!rows.length)return workEmpty(empty);return '<ul>'+rows.map(function(x){return '<li>'+workEsc(x)+'</li>'}).join('')+'</ul>'}
function workChanges(d,w){var rows=w.changes||[];if(!rows.length)return workEmpty('Chưa ghi nhận thay đổi có nguồn. UI không suy lịch sử từ hội thoại.');
  return '<p class="work-meta">Đổi hợp đồng, điều chỉnh trong quyền và lượt chạy lại là ba việc khác nhau.</p>'+rows.map(function(x){var kind={contract:'Thay đổi hợp đồng',internal:'Điều chỉnh kế hoạch',retry:'Lượt thực hiện lại'}[x.kind]||x.kind;
    return '<article class="work-row"><h4>'+workEsc(kind)+(x.revision!=null?' · bản '+esc(x.revision):'')+'</h4><p>'+workEsc(x.reason)+'</p>'
      +(x.author?'<p class="work-meta">Người ghi: '+workEsc(x.author)+'</p>':'')+workSource(x)
      +((x.diff||x.changes||[]).map(function(v){return '<div class="work-meta">'+workEsc(v.path)+'</div><div class="work-diff"><div><b>Trước</b><br>'+workEsc(v.before)+'</div><div><b>Sau</b><br>'+workEsc(v.after)+'</div></div>'}).join(''))
      +(x.affected_nodes&&x.affected_nodes.length?'<p>Phần bị ảnh hưởng: '+esc(x.affected_nodes.map(function(n){return nodeName(d,n)}).join(', '))+'</p>':'')
      +(x.reused_nodes&&x.reused_nodes.length?'<p>Giữ kết quả: '+esc(x.reused_nodes.map(function(n){return nodeName(d,n)}).join(', '))+'</p>':'')
      +(x.kind==='contract'?'<p class="work-meta">'+(x.approved?'Có sự kiện duyệt bản này; quyền hiện hành xem tab Solution.':'Chưa có sự kiện duyệt bản này.')+'</p>':'')
      +(x.diff_total>(x.diff||[]).length?'<p class="work-warning">Đang hiện '+(x.diff||[]).length+'/'+esc(x.diff_total)+' dòng thay đổi; phần hiển thị đã được rút gọn.</p>':'')
      +(x.decision?'<details data-k="work-decision:'+esc(x.id)+'"><summary>Căn cứ quyền</summary><p>'+workEsc(x.decision)+'</p></details>':'')+'</article>'}).join('')}
function workResults(d,w){var outputs=w.outputs||[],runs=(w.checks||{}).runs||[],findings=w.findings||[],repairs=w.repairs||[],actors=w.actors||[];
  var levels={produced:'Đã tạo',verified:'Đã kiểm',accepted:'Đã nghiệm thu',unknown:'Chưa xác định'};
  var h='<h3>Đầu ra</h3>'+(outputs.length?outputs.map(function(x){return '<article class="work-row"><h4>'+workEsc(x.title||x.label||nodeName(d,x.node))+' · '+esc(levels[x.level]||'Chưa xác định')+'</h4>'
    +'<p class="work-meta">'+(x.stale?'Bản cũ / cần kiểm lại · ':'')+(x.inherited?'Kế thừa · ':'')+'Thế hệ '+workEsc(x.generation)+'</p>'
    +(x.inherited&&x.from_generation!=null?'<p class="work-meta">Kế thừa từ thế hệ '+workEsc(x.from_generation)+' · lượt tạo '+workEsc(x.from_attempt)+'</p>':'')
    +workEvidence(d,x.artifact||x.key)+workSource(x)+'</article>'}).join(''):workEmpty('Chưa có đầu ra được ghi nhận.'));
  h+='<h3>Các lần kiểm</h3><p class="work-meta">Một check có thể gồm nhiều testcase. Số check/finding không phải số bug độc lập; thiếu thống kê testcase thì không tự suy ra.</p>';
  var summary=(w.checks||{}).summary||{},cases=summary.testcases;
  h+='<div class="work-grid">'+workCard('Check duy nhất / lượt chạy',summary.unique_checks!=null?summary.unique_checks+' / '+summary.check_executions:null,'Tổng trong lịch sử có receipt, không phải độ bao phủ của bản hiện tại.')
    +workCard('Testcase duy nhất / lượt chạy',cases?cases.unique+' / '+cases.executions:null,cases?'Các trạng thái là số lượt: pass '+cases.pass+', fail '+cases.fail+', skip '+cases.skip+', error '+cases.error+', chưa rõ '+cases.unknown: 'Receipt chưa cung cấp đủ testcase có định danh.')+'</div>';
  h+=runs.length?runs.map(function(x){var tally={};(x.checks||[]).forEach(function(c){var k=c.status||c.result||'unknown';tally[k]=(tally[k]||0)+1});
    return '<article class="work-row"><h4>'+esc(nodeName(d,x.node))+' · '+workEsc(x.status||x.result)+'</h4><p>'+Object.keys(tally).map(function(k){return esc(k)+': '+tally[k]}).join(' · ')+'</p>'
    +(x.testcases&&x.testcases.length?'<p>Testcase có định danh: '+x.testcases.length+' lượt trong receipt này.</p>'+workList(x.testcases.map(function(c){return c.id+': '+c.status}), ''):'<p class="work-meta">Chưa có thống kê testcase có định danh.</p>')
    +(x.stale?'<p class="work-warning">Kết quả lịch sử, không chứng nhận bản hiện tại.</p>':'')+workEvidence(d,x.receipt)+workSource(x)+'</article>'}).join(''):workEmpty('Chưa có receipt kiểm đọc được; không thể kết luận không có lỗi.');
  h+='<h3>Finding và xử lý</h3>'+(findings.length?findings.map(function(x){var resolution=x.resolution||{};return '<article class="work-row"><h4>'+workEsc(x.id)+' · '+workEsc(x.status||x.state)+'</h4><p>'+workEsc(x.text||x.head||x.claim)+'</p>'+(x.severity?'<p class="work-meta">Mức độ: '+workEsc(x.severity)+'</p>':'')
    +'<p>Nguồn phát hiện: '+workEvidence(d,(x.source||{}).receipt)+'</p>'
    +(x.resolution?'<p>Căn cứ xử lý: '+workEsc(resolution.reason||x.reason)+' '+workEvidence(d,resolution.receipt)+'</p>':'')
    +(x.category?'<p>Phân loại: '+workEsc(x.category)+'</p>':'')+(x.duplicate_of?'<p>Trùng với: '+workEsc(x.duplicate_of)+'</p>':'')+(x.recurrence_of?'<p>Tái xuất hiện từ: '+workEsc(x.recurrence_of)+'</p>':'')
    +workSource(x)+'</article>'}).join(''):workEmpty('Chưa ghi nhận finding; không đồng nghĩa đã kiểm hết.'));
  h+='<h3>Chuỗi sửa và kiểm lại</h3>'+(repairs.length?repairs.map(function(x,i){var linked=runs.filter(function(r){return (x.verification||[]).indexOf(r.id)>=0});return '<article class="work-row"><h4>Vòng sửa '+(i+1)+' · '+esc(nodeName(d,x.node||x.target))+' · '+workEsc(({verified:'Đã kiểm đủ phần ảnh hưởng',partial:'Mới kiểm một phần',unverified:'Chưa kiểm đủ'})[x.status]||x.status)+'</h4>'
    +(x.applicable===false?'<p class="work-warning">Vòng sửa lịch sử; không chứng nhận thế hệ hiện tại.</p>':'')
    +'<p>Kiểm lỗi cũ: '+workEsc(x.failed_checks)+'</p><p>Phần ảnh hưởng: '+esc((x.affected_nodes||[]).map(function(n){return nodeName(d,n)}).join(', '))+'</p>'+workEvidence(d,x.source_receipt)
    +'<p><b>Kiểm lại sau sửa</b></p>'+(linked.length?linked.map(function(r){return '<p>'+esc(nodeName(d,r.node))+' · '+workEsc(r.status)+' '+workEvidence(d,r.receipt)+'</p>'}).join(''):workEmpty('Chưa có receipt kiểm lại liên kết với vòng này.'))
    +((x.rebindings||[]).length?'<p class="work-meta">'+x.rebindings.length+' lần nối lại thứ tự; không tính là vòng sửa mới.</p>'+(x.rebindings||[]).map(function(b,j){var checked=runs.filter(function(r){return (b.verification||[]).indexOf(r.id)>=0});return '<details data-k="work-rebind:'+esc(x.id)+':'+j+'"><summary>Nối lại '+(j+1)+' · '+workEsc(({verified:'Đã kiểm đủ',partial:'Kiểm một phần',unverified:'Chưa kiểm đủ'})[b.status]||b.status)+' · '+(b.applicable?'áp dụng hiện tại':'lịch sử')+'</summary>'+checked.map(function(r){return '<p>'+esc(nodeName(d,r.node))+' · '+workEsc(r.status)+' '+workEvidence(d,r.receipt)+'</p>'}).join('')+workSource(b)+'</details>'}).join(''):'')+workSource(x)+'</article>'}).join(''):workEmpty('Chưa có liên kết repair receipt. Không coi mỗi attempt là một vòng sửa.'));
  h+='<h3>Ai được giao / ai đã thực hiện</h3>'+(actors.length?'<div class="scroll"><table><thead><tr><th>Vai trò</th><th>Phần việc</th><th>Người / model có nguồn</th></tr></thead><tbody>'+actors.map(function(x){return '<tr><td>'+workEsc({assigned:'Được giao',executed:'Đã thực hiện',reviewer:'Đã kiểm'}[x.role]||x.role)+'</td><td>'+esc(nodeName(d,x.node))+'</td><td>'+workEsc(x.actor||x.provider)+(x.model?' · '+workEsc(x.model):'')+workSource(x)+'</td></tr>'}).join('')+'</tbody></table></div>':workEmpty('Chưa có định danh thực thi được ghi nhận. Không suy từ tên phiên chat.'));
  return h}
function workProgress(d){var m=d.measure||{},v=m.verification||[];return '<div class="work-grid">'+workCard('Khoảng thực hiện đã ghi nhận',hms(m.attempts_wall_seconds),'Hợp các khoảng attempt, không cộng đôi phần chồng nhau.')+workCard('Khoảng chờ đã ghi nhận',hms(m.wait_seconds),'Khoảng chờ mở hoặc thiếu mốc kết thúc vẫn chưa xác định.')+'</div>'
  +'<h3>Từ đầu ra đến kết quả kiểm</h3><p class="work-meta">Khoảng này có thể gồm thời gian chờ trước kiểm. Chưa có cặp bắt đầu/kết thúc riêng thì thời gian chạy bộ kiểm và hàng đợi riêng đều chưa xác định; không cộng các khoảng này vào thời gian thực hiện.</p>'
  +(v.length?workList(v.map(function(x){return nodeName(d,x.node)+' · thế hệ '+x.generation+' · '+hms(x.seconds)+' · '+x.result}), ''):workEmpty('Chưa có khoảng kiểm có nguồn.'))}
function workDashboard(d){var w=d.work;if(!w)return '';var content=workTab==='solution'?workSolution(d,w):workTab==='changes'?workChanges(d,w):workTab==='results'?workResults(d,w):workTab==='overview'?workOverview(d,w):workProgress(d);
  return '<nav class="work-nav" role="tablist" aria-label="Chi tiết công việc">'+WORK_TABS.map(function(t){return '<button type="button" role="tab" data-work-tab="'+t[0]+'" id="work-tab-'+t[0]+'" data-k="work-tab:'+t[0]+'" aria-selected="'+(workTab===t[0])+'" aria-controls="work-content">'+t[1]+'</button>'}).join('')+'</nav>'
    +'<section id="work-content" class="work-panel" role="tabpanel" aria-labelledby="work-tab-'+workTab+'">'+content
    +((w.limitations||[]).length?'<details data-k="work-limits"><summary>Giới hạn dữ liệu ('+w.limitations.length+')</summary>'+workList(w.limitations,'')+'</details>':'')+'</section>'}
'''
