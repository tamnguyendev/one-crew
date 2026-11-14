"""OBS-2C scenario on the existing real-browser harness (tests/obs1_ux_harness.py): the real page served by the tracking server over the
tests/obs2c_fixture ledger, driven as a reader would (click, type, choose), never mock HTML. Runs in real time (the list of 160 roots is
read anew on every poll, which takes longer than a virtual clock should hide)."""
from tests import obs1_ux_harness as base

SCENARIO = r'''
if(S==='obs2c'){
  const A=()=>(w.__track.state().list||{}).answer||{};
  const F=()=>A().filters||{};
  const rowsNow=()=>$$('#list li.task');
  const planOf=li=>li.dataset.plan.replace(/^plan(-ns)?:/,'');
  const ids=()=>rowsNow().map(li=>li.dataset.project+'|'+li.dataset.plan);
  const fits=()=>d.documentElement.scrollWidth<=w.innerWidth+1;
  async function settle(label,fn){return await waitFor(fn,120000,label)}
  function choose(sel,v){const e=$(sel);e.value=v;e.dispatchEvent(new w.Event('change',{bubbles:true}))}
  await settle('first page',()=>A().total>=150&&rowsNow().length>0);
  check('the first page is one page of the whole list',rowsNow().length===50&&A().total>=150&&A().complete===false,{rows:rowsNow().length,total:A().total});
  const cov=$('#coverage');
  check('the footer says shown, total and what is left',!!cov&&cov.textContent.includes('50 việc đã tải')&&cov.textContent.includes('tổng '+A().total)&&cov.textContent.includes('chưa tải')&&!!$('#more'),cov&&cov.textContent);
  check('the header counts shown over total',$('#count').textContent.includes('/ '+A().total+' công việc'),$('#count').textContent);
  check('an old root is not on the first page',!rowsNow().some(li=>planOf(li)==='W007'));
  check('every row names where the work came from',rowsNow().every(li=>li.querySelector('.org')));
  check('the list has no horizontal overflow',fits(),{w:w.innerWidth,s:d.documentElement.scrollWidth});
  $('#filters').open=true;
  check('the filters (source, time) fit the screen',fits()&&!!$('#origin')&&!!$('#since')&&!!$('#until'),{w:w.innerWidth,s:d.documentElement.scrollWidth});
  $('#more').click();
  await settle('more rows',()=>rowsNow().length===100);
  check('load more adds the next page without a duplicate',rowsNow().length===100&&new Set(ids()).size===100,{n:rowsNow().length});
  await morePolls(2);
  check('polls keep the loaded rows',rowsNow().length===100&&new Set(ids()).size===100,{n:rowsNow().length});
  const q=$('#q');q.value='kỳ lân';q.dispatchEvent(new w.Event('input',{bubbles:true}));
  await settle('search answer',()=>F().q==='kỳ lân'&&rowsNow().length===1);
  check('search finds the old root through the ledger',rowsNow().length===1&&planOf(rowsNow()[0])==='W007');
  q.value='RCPT';q.dispatchEvent(new w.Event('input',{bubbles:true}));
  await settle('receipt pair',()=>F().q==='RCPT'&&rowsNow().length===2);
  const gone=rowsNow().find(li=>planOf(li)==='RCPT-GONE');
  check('a pass whose receipt is gone is not green',!!gone&&!gone.querySelector('.stg.done')&&!gone.querySelector('.stg.accept')&&!gone.textContent.includes('Đạt 1/1'),gone&&gone.textContent.slice(0,300));
  q.value='';q.dispatchEvent(new w.Event('input',{bubbles:true}));
  await settle('search cleared',()=>F().q===''&&rowsNow().length===50);
  choose('#origin','spawned');
  await settle('spawned filter',()=>F().source==='spawned'&&rowsNow().length===1);
  check('the spawned filter lists the work that holds a repair',rowsNow().length===1&&planOf(rowsNow()[0])==='REPAIR'&&rowsNow()[0].textContent.includes('1 việc sửa'));
  rowsNow()[0].click();
  await settle('repair detail',()=>$('#relations [data-relation^="repair:"]')&&$('#relations [data-relation^="child:"]')&&$('#relations').textContent.includes('Nối với việc gốc: REPAIR'));
  const rel=$('#relations'),words=['Việc sửa','Lý do','Từ lần kiểm không đạt','Nối với việc gốc: REPAIR'];
  out.relations={sections:$$('#relations').length,repairs:$$('#relations [data-relation^="repair:"]').length,children:$$('#relations [data-relation^="child:"]').length,tab:(w.__track.state().selected||{}).plan,tail:rel?rel.textContent.slice(-900):null};
  check('the relation section shows the repair, its reason, its check and its root',!!rel&&words.every(x=>rel.textContent.includes(x)),{missing:words.filter(x=>!rel||!rel.textContent.includes(x)),repairs:out.relations.repairs});
  // repair 2 of 14/11: every relation item, as the reader sees it, keeps its words (kind + name, state, short id only) — read now AND after
  // the page's relative-time ticker (setInterval 1 s) has run several times: the dev27 ticker once rewrote every [data-rel] element
  function itemsRead(){return $$('#relations .rel-item').map(a=>({head:(a.querySelector('h4')||{}).textContent||'',state:(a.querySelector('.rel-state')||{}).textContent||'',id:(a.querySelector('.rel-id')||{}).textContent||'',text:a.textContent}))}
  function itemsOk(list){return list.length===3&&list.every(x=>/^(Việc sửa|Phần việc con) · \S/.test(x.head)&&!/TASK-|[0-9a-f]{12}/.test(x.head)&&x.state.length>3&&/^mã \S+…$/.test(x.id)&&!/^(repair|child):/.test(x.text.trim()))}
  const before=itemsRead();
  check('every spawned item is named by its kind and its name, never by its raw id',itemsOk(before),before);
  await sleep(3500);
  const after=itemsRead();
  check('after the time ticker ran, every spawned item still shows its kind, name, state and only a short id',itemsOk(after)&&JSON.stringify(after.map(x=>x.head))===JSON.stringify(before.map(x=>x.head)),after.map(x=>x.text.slice(0,120)));
  check('the ticker still updates the relative times it owns',$$('time[data-rel]').length>0&&$$('[data-rel]').every(e=>e.tagName==='TIME'));
  check('the first heading is the source of the assignment, never read as "AI"',!!rel&&rel.querySelector('.rel-grid b').textContent==='Nguồn giao việc');
  check('child tasks name the event they come from',$$('#relations [data-relation^="child:"]').length>=1&&$('#relations [data-relation^="child:"]').textContent.includes('node.started'));
  check('who asked comes from the ledger',!!rel&&rel.textContent.includes('Chủ giao')&&rel.textContent.includes('Sửa phép cộng cho đúng rồi bàn giao'));
  check('the page offers no write control',!$$('#detail button,#detail a').some(b=>/^(Duyệt|Nghiệm thu|Tách|Gộp|Đổi tên|Huỷ|Hủy)/.test(b.textContent.trim())));
  check('the detail has no horizontal overflow',fits(),{w:w.innerWidth,s:d.documentElement.scrollWidth});
  $('#close').click();
  choose('#origin','unknown');
  await settle('unknown filter',()=>F().source==='unknown'&&rowsNow().length>0&&rowsNow().every(li=>li.querySelector('.org.unknown')));
  check('the unknown source lists only work nobody recorded as assigned',rowsNow().length>0&&rowsNow().every(li=>li.querySelector('.org.unknown')));
  choose('#origin','');
  await settle('source cleared',()=>!F().source&&rowsNow().length===50);
  const chip=$('#chips [data-kind="ended"]');
  check('the finished view is one click',!!chip);
  if(chip)chip.click();
  await settle('finished',()=>F().stage==='ended'&&rowsNow().length===2);
  const closed=rowsNow().find(li=>planOf(li)==='CLOSED'),acc=rowsNow().find(li=>planOf(li)==='ACCEPTED');
  check('finished lists the accepted and the closed work',!!closed&&!!acc);
  check('closed is not shown as a success',!!closed&&!!closed.querySelector('.stg.closed')&&!closed.querySelector('.stg.done')&&!/nghiệm thu/i.test(closed.querySelector('.stg').textContent));
  check('accepted is shown as accepted',!!acc&&!!acc.querySelector('.stg.done'));
  check('the finished view has no horizontal overflow',fits(),{w:w.innerWidth,s:d.documentElement.scrollWidth});
}
'''

HARNESS = base.HARNESS.replace("if(S==='ux01'){", SCENARIO + "\nif(S==='ux01'){")
