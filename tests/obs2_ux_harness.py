"""OBS-2 scenarios on the existing real-browser harness, never mock page HTML."""
from tests import obs1_ux_harness as base

SCENARIO = r'''
if(S==='work'){
  const first=qs.get('first')||'CODE', second=qs.get('second')||'DOC';
  check('board groups cards into sourced stages', $$('.board-lane').length===7 && $$('.board-lane li.task').length===2);
  check('board states are not draggable controls', !$$('li.task').some(x=>x.draggable));
  check('sample data is visibly distinguished', $('#sample')&&!$('#sample').hidden);
  const originalCards=$$('li.task').map(x=>x.dataset.plan).sort().join(',');
  for(const order of ['created','updated','deadline','attention']){$('#sort').value=order;$('#sort').dispatchEvent(new w.Event('change',{bubbles:true}));check('sorting '+order+' preserves the same tasks',$$('li.task').map(x=>x.dataset.plan).sort().join(',')===originalCards);}
  const docCard=rowOf(second);check('document waits for check not owner', docCard.textContent.includes('chờ kiểm')&&!docCard.querySelector('.needb'));
  check('pending amendment is not ready for acceptance',rowOf(first).closest('.board-lane').dataset.stage==='doing');
  await select(first);
  const decision=$('#detail details.need');
  check('decision starts compact so work tabs remain accessible',!decision.open);
  decision.querySelector('summary').click();
  const cmd=$('#detail details.need pre code'),copy=$('#detail details.need button.copy');
  check('approval has a separate complete PowerShell command',cmd&&copy&&cmd.textContent===copy.dataset.copy&&cmd.textContent.includes('--project')&&cmd.textContent.includes('--state-root')&&cmd.textContent.includes('--revision 2')&&cmd.textContent.includes('--human'));
  check('approval explains copying does not approve', $('#detail details.need').textContent.includes('Sao chép chưa phải duyệt'));
  if(copy){copy.click();await waitFor(()=>$('#detail .copied'),5000,'copy feedback');const copied=$('#detail .copied');check('clipboard reports exact command or explicit failure', copied.dataset.copied===cmd.textContent||copied.hasAttribute('data-copy-failed'));await morePolls(2);check('copy leaves approval pending',!!$('#detail details.need[data-need-rev="2"]'));}

  $('#detail details.need').open=false;
  const timeline=$('.gantt');
  check('timeline uses task rows by default', $$('.gnselect').length>=2 && !$$('.gtree .att').length);
  check('timeline hides empty inspector', $('#gside').hidden);
  const ticks=$$('.gaxis span').map(x=>x.textContent);check('timeline scale labels do not repeat',ticks.length>=3&&new Set(ticks).size===ticks.length);
  const selectNode=$('.gnselect');selectNode.click();check('whole node is selectable',!$('#gside').hidden&&$('#gside').textContent.includes('Đầu ra hiện hành'));
  check('node details distinguish actor evidence', $('#gside').textContent.includes('Đã thực hiện:'));
  const selectedNode=st().selStep.id;await morePolls(2);check('selected node persists across polls',st().selStep.id===selectedNode);
  $('#grange').value='all';$('#grange').dispatchEvent(new w.Event('change',{bubbles:true}));
  const historic=[$('.gchart').dataset.w0,$('.gchart').dataset.w1].join('|');await morePolls(2);check('history window is held across polls',historic===[$('.gchart').dataset.w0,$('.gchart').dataset.w1].join('|')&&$('.ganchor').textContent.includes('giữ khung'));
  $('#gfit').click();check('fit returns to current work',st().gRange==='current'&&!$('.ganchor').textContent.includes('giữ khung'));
  $('.gnselect').click();
  const expand=$('.gtree [data-fold^="n:"]');expand.click();check('attempt ids appear only on expansion',$$('.gtree .att').length>=1);expand.click();

  check('five named work tabs', $$('.work-nav [role=tab]').length===5);
  check('overview answers current/output/owner/estimate', ['Hiện tại','Kết quả đã có','Việc cần bạn','Dự kiến còn lại'].every(t=>$('#work-content').textContent.includes(t)));
  check('technical detail folded by default', !$('#detail details[data-k="work-technical"]').open);
  for(const tab of ['solution','changes','results','progress','overview']){
    $('[data-work-tab="'+tab+'"]').click();
    check(tab+' is selected and labelled', $('#work-content').getAttribute('aria-labelledby')==='work-tab-'+tab && $('#work-tab-'+tab).getAttribute('aria-selected')==='true');
    check(tab+' has no page overflow', d.documentElement.scrollWidth<=w.innerWidth+1, {width:w.innerWidth,scroll:d.documentElement.scrollWidth});
    check(tab+' has no blank panel', $('#work-content').textContent.trim().length>20);
  }
  $('#work-tab-solution').click(); await morePolls(3);
  check('solution tab survives polls', $('#work-tab-solution').getAttribute('aria-selected')==='true');
  check('solution distinguishes latest and runnable', ['Bản đề xuất mới nhất','Bản được duyệt','Bản có thể thực hiện'].every(t=>$('#work-content').textContent.includes(t)));
  check('Gantt hidden in solution', $('#legacy-progress').hidden);
  $('#work-tab-results').click();
  check('finding is readable instead of raw receipt JSON', $('#work-content').textContent.includes('Không đạt: Nội dung')&&!$('#work-content').textContent.includes('{"criterion"'));
  check('plain text evidence has no false unreadable warning', !$('#detail').textContent.includes('Không đọc được receipt/definition/register'));
  check('results name cases and repair separately', ['Testcase duy nhất / lượt chạy','Finding và xử lý','Chuỗi sửa và kiểm lại'].every(t=>$('#work-content').textContent.includes(t)));
  const ev=$('#work-content button.ev-open');
  check('output offers evidence', !!ev);
  if(ev){ev.click(); await waitFor(()=>$('#work-content pre')&&$('#work-content pre').textContent.length>10,8000,'output evidence');check('output evidence opens through existing door', !!$('#work-content pre')&&!$('#work-content pre').textContent.includes('không mở được'));}
  check('results show current outputs before history', $('#work-content').textContent.indexOf('Kết quả hiện hành')<$('#work-content').textContent.indexOf('Đầu ra lịch sử'));
  check('repair has linked three-step reading flow', $$('.repair-flow>div').length===3);
  check('repair is linked to followup checks', $('#work-content').textContent.includes('Vòng sửa 1') && $('#work-content').textContent.includes('Kiểm lại sau sửa'));
  $('#work-tab-changes').click();
  check('initial execution plan is distinct from changes', $('#work-content').textContent.includes('Kế hoạch thực hiện ban đầu'));
  await select(second);
  check('another task resets to overview', $('#work-tab-overview').getAttribute('aria-selected')==='true');
  $('#work-tab-solution').click();
  check('noncoding uses same solution view', $('#work-content').textContent.includes('Phương án và phạm vi'));
  $('#work-tab-results').click();check('document new output not certified by old pass', $('#work-content').textContent.includes('Đã tạo')&&$('#work-content details[data-k="work-history"]'));
  check('noncoding no page overflow', d.documentElement.scrollWidth<=w.innerWidth+1);
  // dev5 regressions: use the real installed renderer and real polls. Only the
  // live-axis flag is injected in a fetched response; no ledger or DOM is edited.
  $('#work-tab-progress').click();
  const ga=$('.gantt').getBoundingClientRect(), row=$('.gchart .nodehead').getBoundingClientRect();
  check('progress starts with timeline without test scrolling',ga.top>=0&&ga.top<w.innerHeight-100&&row.top<w.innerHeight-60,{top:ga.top,row:row.top,height:w.innerHeight});
  check('attempt measurements are collapsed',!!$('details[data-k="work-progress-measures"]')&&!$('details[data-k="work-progress-measures"]').open);
  check('legacy technical measurements remain collapsed',!$('details[data-k="work-technical"]').open);
  const tickPositions=$$('.gaxis i').map(x=>parseFloat(x.style.left));
  const gridPositions=$$('.gchart .nodehead:first-of-type .ggrid').map(x=>parseFloat(x.style.left));
  const anyRow=$('.gchart [data-node-row]');const rowPositions=anyRow?Array.from(anyRow.querySelectorAll('.ggrid')).map(x=>parseFloat(x.style.left)):[];
  check('body grid aligns with every axis tick',tickPositions.length===rowPositions.length&&tickPositions.every((x,i)=>Math.abs(x-rowPositions[i])<.002),{tickPositions,rowPositions});
  $('#grange').value='all';$('#grange').dispatchEvent(new w.Event('change',{bubbles:true}));
  check('all history reveals old attempts immediately',$$('.gtree .att.old').length>0);
  check('return control names its actual action',$('#gfit').textContent==='Về hiện hành');
  $('#gfit').click();check('return current collapses historical rows',st().gRange==='current'&&!$$('.gtree .att.old').length&&!$$('.gtree .att').length);
  const realFetch=w.fetch;
  try{
    w.fetch=function(u,o){return realFetch.call(w,u,o).then(async response=>{if(typeof u==='string'&&u.startsWith('/api/task?')&&response.ok){const body=await response.clone().json();body.gantt.axis.extends_to_now=true;return new w.Response(JSON.stringify(body),{status:200,headers:{'Content-Type':'application/json'}})}return response})};
    await morePolls(2);
    $('.gnselect').click();
    const sources=$('#gside details');sources.querySelector('summary').click();const sourceKey=sources.dataset.k;
    await morePolls(2);
    check('node disclosure stays open across live polls',!!sourceKey&&$('#gside details[data-k="'+sourceKey+'"]').open);
    $('.seg.execution').click();
    check('attempt inspector leads with readable step name',!$('#gside h4').textContent.includes('ATT-')&&$('#gside h4').textContent.includes('Chuẩn bị'));
    check('attempt inspector keeps millisecond duration',/Thực thi:.*ms/.test($('#gside').textContent));
    const outputs=$$('#gside .goutput');check('same artifact appears once as user output',outputs.length===1,{outputs:outputs.length});
    check('output retains multiple provenance occurrences',outputs.length&&outputs[0].textContent.includes('2 lần ghi nhận'));
    const source=$('#gside details[data-k^="g-attempt-source:"]');check('attempt technical details start collapsed',!!source&&!source.open);
    const stamp=$('#gside details[data-k^="g-attempt-time:"]');
    if(source&&stamp){source.querySelector('summary').click();stamp.querySelector('summary').click();const stampKey=stamp.dataset.k;await morePolls(2);
      check('exact timestamps stay open across live polls',$('#gside details[data-k="'+stampKey+'"]').open&&$('#gside details[data-k^="g-attempt-source:"]').open);
    }else check('exact timestamps stay open across live polls',false,'disclosure missing');
    const outputSource=$('#gside .goutput details');if(outputSource){outputSource.querySelector('summary').click();await morePolls(2);}
    check('output provenance stays open across live polls',!!$('#gside .goutput details')&&$('#gside .goutput details').open);
    const openOutput=$('#gside .goutput button.ev-open');if(openOutput){openOutput.click();await waitFor(()=>$('#gside .goutput pre'),8000,'compact output evidence');}
    check('compact output reuses evidence door',!!$('#gside .goutput pre')&&!$('#gside .goutput pre').textContent.includes('không mở được'));
  }finally{w.fetch=realFetch;}
  // Leave the visible screenshot in the work view, not in raw event JSON.
  $('#work-tab-overview').click();
  if(shot&&qs.get('view')){await select(first);if(qs.get('view')==='board')$('#close').click();else if(qs.get('view')==='timeline'){$('#work-tab-progress').click();}else if(qs.get('view')==='decision')$('#detail details.need').open=true;else $('#work-tab-'+qs.get('view')).click();}
}
'''

HARNESS = base.HARNESS.replace("if(S==='ux01'){", SCENARIO + "\nif(S==='ux01'){")
