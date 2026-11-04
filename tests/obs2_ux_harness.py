"""OBS-2 scenarios on the existing real-browser harness, never mock page HTML."""
from tests import obs1_ux_harness as base

SCENARIO = r'''
if(S==='work'){
  const first=qs.get('first')||'CODE', second=qs.get('second')||'DOC';
  await select(first);
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
  check('repair is linked to followup checks', $('#work-content').textContent.includes('Vòng sửa 1') && $('#work-content').textContent.includes('Kiểm lại sau sửa'));
  await select(second);
  check('another task resets to overview', $('#work-tab-overview').getAttribute('aria-selected')==='true');
  $('#work-tab-solution').click();
  check('noncoding uses same solution view', $('#work-content').textContent.includes('Phương án và phạm vi'));
  check('noncoding no page overflow', d.documentElement.scrollWidth<=w.innerWidth+1);
  // Leave the visible screenshot in the work view, not in raw event JSON.
  $('#work-tab-overview').click();
  if(shot&&qs.get('view')){await select(first);$('#work-tab-'+qs.get('view')).click();}
}
'''

HARNESS = base.HARNESS.replace("if(S==='ux01'){", SCENARIO + "\nif(S==='ux01'){")
