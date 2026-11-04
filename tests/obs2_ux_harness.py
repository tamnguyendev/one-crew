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
  await select(first);
  const cmd=$('#detail details.need pre code'),copy=$('#detail details.need button.copy');
  check('approval has a separate complete PowerShell command',cmd&&copy&&cmd.textContent===copy.dataset.copy&&cmd.textContent.includes('--project')&&cmd.textContent.includes('--state-root')&&cmd.textContent.includes('--revision 2')&&cmd.textContent.includes('--human'));
  check('approval explains copying does not approve', $('#detail details.need').textContent.includes('Sao chép chưa phải duyệt'));
  if(copy){copy.click();await waitFor(()=>$('#detail .copied'),5000,'copy feedback');const copied=$('#detail .copied');check('clipboard reports exact command or explicit failure', copied.dataset.copied===cmd.textContent||copied.hasAttribute('data-copy-failed'));await morePolls(2);check('copy leaves approval pending',!!$('#detail details.need[data-need-rev="2"]'));}

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
  check('results name cases and repair separately', ['Testcase duy nhất / lượt chạy','Finding và xử lý','Chuỗi sửa và kiểm lại'].every(t=>$('#work-content').textContent.includes(t)));
  const ev=$('#work-content button.ev-open');
  check('output offers evidence', !!ev);
  if(ev){ev.click(); await waitFor(()=>$('#work-content pre')&&$('#work-content pre').textContent.length>10,8000,'output evidence');check('output evidence opens through existing door', !!$('#work-content pre')&&!$('#work-content pre').textContent.includes('không mở được'));}
  check('results show current outputs before history', $('#work-content').textContent.indexOf('Kết quả hiện hành')<$('#work-content').textContent.indexOf('Đầu ra lịch sử'));
  check('repair has linked three-step reading flow', $$('.repair-flow>div').length===3);
  check('repair is linked to followup checks', $('#work-content').textContent.includes('Vòng sửa 1') && $('#work-content').textContent.includes('Kiểm lại sau sửa'));
  await select(second);
  check('another task resets to overview', $('#work-tab-overview').getAttribute('aria-selected')==='true');
  $('#work-tab-solution').click();
  check('noncoding uses same solution view', $('#work-content').textContent.includes('Phương án và phạm vi'));
  $('#work-tab-results').click();check('document new output not certified by old pass', $('#work-content').textContent.includes('Đã tạo')&&$('#work-content details[data-k="work-history"]'));
  check('noncoding no page overflow', d.documentElement.scrollWidth<=w.innerWidth+1);
  // Leave the visible screenshot in the work view, not in raw event JSON.
  $('#work-tab-overview').click();
  if(shot&&qs.get('view')){await select(first);if(qs.get('view')==='board')$('#close').click();else $('#work-tab-'+qs.get('view')).click();}
}
'''

HARNESS = base.HARNESS.replace("if(S==='ux01'){", SCENARIO + "\nif(S==='ux01'){")
