"""Installed-wheel R7-1 checker: the project hook binding changes WHILE the page is open and the ledger does not move.

Run: installed-python -I -B check_binding_live.py NEW_WORK
Only a fresh fixture: two PROPOSED plans with one question each (no owner verb), a disposable project whose
.claude/settings.local.json this script writes, removes or points elsewhere. No provider, real registry, real project or ledger.

Every run first proves its precondition (bound: the cards really carry write commands and a copy click left feedback);
a run whose precondition fails is a failed run, never a pass. Cases:
  live-<to>-<size>  virtual time: bound -> <to> (missing | other-runtime | other-state) -> bound again, same task and tab
  slow-<size>       real time: detail reads of P1 answer 2.5 s late while the binding is lost and the reader switches P1 -> P2 -> P1
Writes NEW_WORK/browser-binding-live.json (+ a screenshot of the lost-binding state per size)."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

from onecrew.ledger import Ledger
from onecrew.v2 import tracking, tracking_web, plan, hook_cli

SCENARIO = r'''
function liveSnap(){const needs=$$('details.need');const card=n=>n?({copies:Array.from(n.querySelectorAll('button.copy')).map(b=>b.dataset.copy||''),boxes:n.querySelectorAll('.command-box').length,
    copied:n.querySelectorAll('.copied').length,opts:Array.from(n.querySelectorAll('.opt b')).map(b=>b.textContent),text:n.textContent}):null;
  const q=needs.find(n=>n.dataset.k&&n.dataset.k.indexOf('need:request:')===0), a=needs.find(n=>n.dataset.k&&n.dataset.k.indexOf('need:approve:')===0);
  const det=$('#detail');return {title:($('#dtitle')||{}).textContent||'',q:card(q),a:card(a),boxes:det?det.querySelectorAll('.command-box').length:0,copyButtons:det?det.querySelectorAll('button.copy').length:0,
    copied:det?det.querySelectorAll('.copied').length:0,writeText:det?/owner (answer|approve)/.test(det.textContent):false,open:$$('details.need[open]').length,text:det?det.textContent:''}}
function openNeeds(){$$('details.need').forEach(n=>n.open=true)}
async function apiOf(plan){const j=await (await fetch('/api/task?plan='+encodeURIComponent(plan)+'&timeline=5',{cache:'no-store'})).json();
  const needs=j.needs_user||[];return {seq:j.source&&j.source.last_seq,cmds:needs.reduce((s,n)=>s+(n.human_command||n.reply_command?1:0)+(n.options||[]).filter(o=>o.human_command||o.reply_command).length,0),
    bound:needs.length?needs.every(n=>(n.runtime_binding||{}).verified===true):null,unbound:needs.length?needs.every(n=>(n.runtime_binding||{}).verified===false):null}}
async function settle(pred,ms){const t0=Date.now();while(Date.now()-t0<ms){if(pred())return true;await sleep(100)}return !!pred()}
if(S==='live'){const to=qs.get('to'), P1=rowOf('P1').dataset.plan;
  await select('P1'); openNeeds(); await sleep(300);
  $('#work-tab-changes').click(); await sleep(200); openNeeds();
  const pre=liveSnap(), api0=await apiOf(P1);
  out.pre={q:pre.q&&pre.q.copies.length,a:pre.a&&pre.a.copies.length,api:api0};
  check('precondition: API bound with write commands', api0.bound===true&&api0.cmds>=3, api0);
  check('precondition: question options carry owner answer commands', !!pre.q&&pre.q.copies.length===2&&pre.q.copies.every(c=>/owner answer/.test(c)), pre.q&&pre.q.copies);
  check('precondition: approve carries owner approve command', !!pre.a&&pre.a.copies.length===1&&/owner approve/.test(pre.a.copies[0]), pre.a&&pre.a.copies);
  pre.q&&$$('details.need').find(n=>n.dataset.k.indexOf('need:request:')===0).querySelector('button.copy').click(); await sleep(700); openNeeds();
  const fb=liveSnap(); out.copied_state=st().copied&&{k:st().copied.k,ok:st().copied.ok};
  check('precondition: the copy click left feedback holding the command', fb.q&&fb.q.copied===1&&st().copied&&/owner answer/.test(st().copied.text||''), fb.q&&fb.q.copied);
  const sentinel=$$('details.need')[0]; if(sentinel)sentinel.dataset.rvSentinel='1';
  const open0=liveSnap().open; await morePolls(3); await sleep(400);
  check('no change: three polls without a change keep the rendered cards (no repaint)', !!$$('details.need')[0]&&$$('details.need')[0].dataset.rvSentinel==='1');
  await signal('mode',{to:to});
  const gone=await settle(()=>liveSnap().copyButtons===0, 15000); openNeeds(); await sleep(200);
  const lost=liveSnap(), api1=await apiOf(P1);
  out.lost={boxes:lost.boxes,copyButtons:lost.copyButtons,copied:lost.copied,writeText:lost.writeText,api:api1};
  check('the ledger did not move (same last_seq)', api1.seq===api0.seq, [api0.seq,api1.seq]);
  check('API: binding not verified and no write command', api1.unbound===true&&api1.cmds===0, api1);
  check('page: write commands gone on the next polls without reselecting', gone&&lost.boxes===0&&lost.copyButtons===0);
  check('page: no old copy feedback or command text', lost.copied===0&&!lost.writeText&&!(st().copied), out.lost);
  check('page: question, options and reason stay readable', !!lost.q&&lost.q.opts.join('|')==='7 ngày|30 ngày'&&/Chưa xác minh hook/.test(lost.q.text), lost.q&&lost.q.opts);
  check('page: same task, same work tab, needs still open', st().selected&&st().selected.plan===P1&&$('#work-tab-changes').getAttribute('aria-selected')==='true'&&lost.open===open0, [lost.open,open0]);
  if(qs.get('shot')==='1'){const n=$$('details.need')[0];if(n)n.scrollIntoView({block:'start'})}   // screenshot run: the page stays in the lost-binding state
  else{
  await signal('mode',{to:'bound'});
  const back=await settle(()=>liveSnap().copyButtons===3, 15000); openNeeds(); await sleep(200);
  const again=liveSnap(), api2=await apiOf(P1);
  out.restored={boxes:again.boxes,copyButtons:again.copyButtons,copied:again.copied,api:api2};
  check('restore: API bound again, ledger still unmoved', api2.bound===true&&api2.cmds>=3&&api2.seq===api0.seq, api2);
  check('restore: current commands come back without reselecting', back&&again.q&&again.q.copies.length===2&&again.a&&again.a.copies.length===1);
  check('restore: the old copy feedback does not come back', again.copied===0&&!(st().copied));
  check('no horizontal page overflow', d.documentElement.scrollWidth<=w.innerWidth+1, [d.documentElement.scrollWidth,w.innerWidth]);
  }
}
function fakeClipboard(){const cb={calls:[],pending:[]};          // a controlled clipboard: each writeText waits until the scenario settles it
  try{Object.defineProperty(w.navigator,'clipboard',{configurable:true,value:{writeText:t=>new Promise((res,rej)=>{cb.calls.push(t);cb.pending.push({res:res,rej:rej,t:t})})}})}catch(e){cb.error=String(e)}
  return cb}
function qCards(){return $$('details.need').filter(n=>n.dataset.k&&n.dataset.k.indexOf('need:request:')===0)}
function cardOf(key){return $$('details.need').find(n=>n.dataset.k===key)||null}
function focusAt(){const a=d.activeElement,card=a&&a.closest?a.closest('details.need'):null;
  return {tag:a?a.tagName:null,isCopy:!!(a&&a.classList&&a.classList.contains('copy')),copy:a&&a.dataset?(a.dataset.copy||null):null,card:card?card.dataset.k:null,inDetail:!!(a&&a.closest&&a.closest('#detail')),id:a?a.id||null:null}}
function readPos(){return narrow()?w.scrollY:$('#detailpane').scrollTop}
function narrow(){return w.innerWidth<900}
if(S==='focus'){const P2=rowOf('P2').dataset.plan;
  await select('P3'); openNeeds(); await sleep(300);
  const clip=fakeClipboard(); d.execCommand=()=>false;           // the fallback copy fails on purpose: a failure is a controlled outcome, not a headless accident
  const cards=qCards();
  check('precondition: two question cards, two bound options each', cards.length===2&&cards.every(n=>{const b=n.querySelectorAll('button.copy');return b.length===2&&Array.from(b).every(x=>/owner answer/.test(x.dataset.copy||''))}), cards.length);
  check('precondition: the page writes through the controlled clipboard', !clip.error&&w.navigator.clipboard&&typeof w.navigator.clipboard.writeText==='function', clip.error);
  const open0=$$('details.need[open]').length;
  async function copyAt(cardIndex,optIndex){const card=qCards()[cardIndex],btn=card.querySelectorAll('button.copy')[optIndex];btn.focus();const want={copy:btn.dataset.copy,card:card.dataset.k};btn.click();await sleep(60);return want}
  // A: second card, second option, the clipboard succeeds
  let want=await copyAt(1,1);
  check('A: the clipboard got exactly that option command', clip.calls.length===1&&clip.calls[0]===want.copy);
  clip.pending.shift().res(); await sleep(400);
  let at=focusAt(), c=cardOf(want.card);
  check('A success: focus stays on the same option button of the same card', at.isCopy&&at.copy===want.copy&&at.card===want.card, at);
  check('A success: copied feedback only in that card, holding that command', $$('#detail .copied').length===1&&!!c&&!!c.querySelector('.copied[data-copied]')&&c.querySelector('.copied').getAttribute('data-copied')===want.copy);
  check('A: open sections kept', $$('details.need[open]').length===open0, [$$('details.need[open]').length,open0]);
  // B: first card, first option, the clipboard refuses and the fallback fails
  want=await copyAt(0,0); clip.pending.shift().rej(new Error('denied')); await sleep(400);
  at=focusAt(); c=cardOf(want.card);
  check('B failure: focus stays on the first option button of the first card', at.isCopy&&at.copy===want.copy&&at.card===want.card, at);
  check('B failure: one failure note with the command to copy by hand, in that card only', $$('#detail .copied').length===1&&!!c&&!!c.querySelector('.copied[data-copy-failed]')&&c.querySelector('textarea').value===want.copy);
  // C: the answer lands late; meanwhile the reader moved focus and scrolled
  want=await copyAt(0,1); const tab=$('#work-tab-changes'); tab.focus(); const posClick=readPos();
  if(narrow())w.scrollTo(0,w.scrollY+120);else $('#detailpane').scrollTop=$('#detailpane').scrollTop+120;
  const posMoved=readPos(); check('C precondition: the reader really scrolled while the copy was pending', Math.abs(posMoved-posClick)>=60, [posClick,posMoved]);
  clip.pending.shift().res(); await sleep(400);
  at=focusAt();
  check('C late answer: focus stays where the reader moved it (work tab), not pulled back', at.id==='work-tab-changes', at);
  check('C late answer: reading position not pulled back', Math.abs(readPos()-posMoved)<=4, [readPos(),posMoved]);
  check('C late answer: feedback for that command still appears in its card', !!cardOf(want.card)&&!!cardOf(want.card).querySelector('.copied[data-copied]')&&cardOf(want.card).querySelector('.copied').getAttribute('data-copied')===want.copy);
  // D: the answer lands late after the reader switched task
  want=await copyAt(1,0); rowOf('P2').click(); await settle(()=>($('#dtitle')||{}).textContent&&$('#dtitle').textContent.indexOf('P2')>=0&&!!$('#detail .dsum'),8000);
  clip.pending.shift().res(); await sleep(400);
  check('D task switched: P2 shows no P3 question, no copy feedback', ($('#dtitle')||{}).textContent.indexOf('P2')>=0&&!/Giữ (CV|log) P3/.test($('#detail').textContent)&&$$('#detail .copied').length===0);
  check('D task switched: focus not pulled into a P3 card', !focusAt().card||focusAt().card.indexOf(want.card)<0, focusAt());
  await select('P3'); openNeeds(); await sleep(300);
  check('D back on P3: no copy feedback from before the switch', $$('#detail .copied').length===0);
  // E: the answer lands late after the binding was lost
  want=await copyAt(1,1); await signal('mode',{to:'missing'});
  const gone=await settle(()=>$$('#detail button.copy').length===0,15000); await sleep(200);
  check('E precondition: the binding loss repainted the cards while the copy was pending', gone&&clip.pending.length===1);
  clip.pending.shift().res(); await sleep(400);
  at=focusAt();
  check('E late answer after binding loss: no copy feedback and no command text', $$('#detail .copied').length===0&&$$('#detail button.copy').length===0&&!/owner (answer|approve)/.test($('#detail').textContent));
  check('E late answer after binding loss: focus on a meaningful place of the current card (its heading), not lost', at.tag==='SUMMARY'&&at.card===want.card, at);
  await signal('mode',{to:'bound'});
  const back=await settle(()=>$$('#detail button.copy').length>=4,15000); openNeeds(); await sleep(200);
  check('E restore: current commands back, the old feedback does not come back', back&&$$('#detail .copied').length===0);
  check('no horizontal page overflow', d.documentElement.scrollWidth<=w.innerWidth+1, [d.documentElement.scrollWidth,w.innerWidth]);
}
if(S==='slow'){const P1=rowOf('P1').dataset.plan, P2=rowOf('P2').dataset.plan;
  const trace=[];const mo=new w.MutationObserver(()=>{const s=liveSnap();trace.push({t:Date.now(),title:s.title.slice(0,4),p1q:/Giữ CV P1/.test(s.text),p2q:/Giữ CV P2/.test(s.text),cmds:s.copyButtons,copied:s.copied})});
  await select('P1'); openNeeds(); await sleep(300);
  const pre=liveSnap();
  check('precondition: P1 bound with write commands', pre.copyButtons===3&&/Giữ CV P1/.test(pre.text), pre.copyButtons);
  mo.observe($('#detail'),{childList:true,subtree:true,characterData:true});
  await (await fetch('/__fault?detail=ok&plan='+encodeURIComponent(P1)+'&delay=2500&count=3',{cache:'no-store'})).json();
  await signal('mode',{to:'missing'});
  await sleep(1200);                                   // a P1 read is in flight (2.5 s late) when the reader switches
  rowOf('P2').click();
  const p2=await settle(()=>{const s=liveSnap();return s.title.indexOf('P2')===0&&/Giữ CV P2/.test(s.text)}, 15000); openNeeds(); await sleep(400);
  const atP2=liveSnap();
  check('switch: P2 shows its own question, unbound, no command', p2&&atP2.copyButtons===0&&!atP2.writeText&&/Chưa xác minh hook/.test(atP2.text), [atP2.copyButtons]);
  await sleep(3000);                                   // the late P1 answer lands now: it must not paint under P2
  const stillP2=liveSnap();
  check('late P1 answer never painted under P2', stillP2.title.indexOf('P2')===0&&!/Giữ CV P1/.test(stillP2.text));
  rowOf('P1').click();
  const p1=await settle(()=>{const s=liveSnap();return s.title.indexOf('P1')===0&&/Giữ CV P1/.test(s.text)}, 20000); openNeeds(); await sleep(400);
  const atP1=liveSnap();
  check('back on P1 (slow reads): unbound state, no old command or feedback', p1&&atP1.copyButtons===0&&atP1.copied===0&&!atP1.writeText, [atP1.copyButtons,atP1.copied]);
  await signal('mode',{to:'bound'});
  const back=await settle(()=>liveSnap().copyButtons===3, 25000);
  check('restore under slow reads: P1 commands come back without reselecting', back&&liveSnap().title.indexOf('P1')===0);
  mo.disconnect();
  const mixed=trace.filter(x=>(x.title.indexOf('P2')===0&&x.p1q)||(x.title.indexOf('P1')===0&&x.p2q));
  check('no moment showed one task\'s question under the other\'s title', mixed.length===0, mixed.slice(0,3));
  out.trace=trace.length;
}
'''


def main(work):
    work = Path(work).resolve(); work.mkdir(exist_ok=False)
    here = Path(__file__).resolve().parent
    registry = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'OneCrew/hook-projects.json'
    original_registry = registry.read_bytes() if registry.exists() else None
    for key, name in [('TEMP', 'tmp'), ('TMP', 'tmp'), ('LOCALAPPDATA', 'lad'), ('APPDATA', 'ad')]:
        p = work / name; p.mkdir(exist_ok=True); os.environ[key] = str(p)
    spec = importlib.util.spec_from_file_location('fixture', here / 'scenario_obs2.py')
    fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
    project = work / 'project'; project.mkdir(); (project / 'code.py').write_text('fixture\n')
    for args in [('init', '-q'), ('config', 'user.name', 'Fixture'), ('config', 'user.email', 'fixture@localhost'), ('add', 'code.py'), ('commit', '-qm', 'fixture')]:
        subprocess.run(['git', '-C', str(project), *args], check=True, capture_output=True)
    ledger = Ledger(project, work / 'state')
    for name, questions in (('P1', ('CV',)), ('P2', ('CV',)), ('P3', ('CV', 'log'))):      # P3: two question cards (focus scenario)
        root = plan.propose(ledger, name, fixture.contract('code.py', 'Binding fixture ' + name), 'fixture')
        for what in questions:
            ledger.create_request(root['anchor_task'], 'choice-' + what, {'schema_version': 1, 'question': 'Giữ ' + what + ' ' + name + ' bao lâu?', 'reason': 'Fixture only',
                'impact': 'Fixture', 'options': [{'id': 'a', 'label': '7 ngày'}, {'id': 'b', 'label': '30 ngày'}], 'recommendation': 'a',
                'action': {'type': 'clarify', 'parameters': {}}})
    sys.path.insert(0, str(here))
    from tests import obs1_ux_harness as ux
    ux.HARNESS = ux.HARNESS.replace("if(S==='shot-list'){}", "if(S==='shot-list'){}\n" + SCENARIO, 1)
    browser = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
    if not Path(browser).is_file(): raise RuntimeError('Chrome missing, not verified')
    exe = Path(sys.executable).with_name('onecrew.exe')
    other = work / 'other-runtime' / 'onecrew.exe'; other.parent.mkdir(); other.write_bytes(b'another runtime identity; never executed')
    settings = project / '.claude/settings.local.json'; settings.parent.mkdir()

    def set_mode(mode):
        if mode == 'missing':
            if settings.exists(): settings.unlink()
            return
        settings.write_text(json.dumps(hook_cli.portable_settings(other if mode == 'other-runtime' else exe,
                                                                  work / 'other-state' if mode == 'other-state' else ledger.state_root)), encoding='utf8')

    signals = []

    def on_signal(name, params=None):
        to = (params or {}).get('to')
        set_mode(to); signals.append({'signal': name, 'to': to, 'settings': settings.exists()})
        return signals[-1]

    db = ledger.state_root / 'ledger.sqlite3'; before = hashlib.sha256(db.read_bytes()).hexdigest()
    server = tracking_web.make_server(ledger.state_root, interval=1)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    proxy = ux.Proxy(tracking_web.url_of(server), on_signal=on_signal)
    report = {'origin': tracking.__file__, 'version': tracking_web.version(), 'results': {}, 'signals': signals, 'ok': False}
    try:
        runs = [('live-' + to + '-' + size, 'live', size, '&to=' + to, False) for to in ('missing', 'other-runtime', 'other-state') for size in ('desktop', 'mobile')]
        runs += [('slow-' + size, 'slow', size, '', True) for size in ('desktop', 'mobile')]
        runs += [('focus-' + size, 'focus', size, '', False) for size in ('desktop', 'mobile')]
        for key, scenario, size, extra, realtime in runs:
            set_mode('bound')
            if not tracking._runtime_binding(project, ledger.state_root)['verified']:
                raise RuntimeError('fixture binding is not verified before ' + key)
            width, height = ux.SIZES[size]
            result = ux.run(browser, proxy.url, scenario, width, height, work / 'profile', budget=120000 if realtime else 60000, extra=extra, realtime=realtime)
            report['results'][key] = result
            (work / 'browser-binding-live.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
            if key in ('live-other-state-desktop', 'live-other-state-mobile'):
                set_mode('bound')
                ux.screenshot(browser, proxy.url, 'live', width, height, work / 'profile', work / (key + '-lost.png'), budget=60000, extra=extra + '&shot=1')
        set_mode('bound')
        report['passed'] = sum(sum(1 for v in (r.get('checks') or {}).values() if v) for r in report['results'].values())
        report['total'] = sum(len(r.get('checks') or {}) for r in report['results'].values())
        report['ledger_unchanged'] = hashlib.sha256(db.read_bytes()).hexdigest() == before
        report['registry_unchanged'] = (registry.read_bytes() if registry.exists() else None) == original_registry
        report['ok'] = (all(r.get('ok') for r in report['results'].values()) and report['ledger_unchanged'] and report['registry_unchanged']
                        and Path(tracking.__file__).is_relative_to(Path(sys.prefix)))
    finally:
        proxy.stop(); server.shutdown(); server.server_close(); thread.join(10)
        (work / 'browser-binding-live.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'ok': report['ok'], 'cases': len(report['results']), 'passed': report.get('passed'), 'total': report.get('total'),
                      'failed': {k: [c for c, v in (r.get('checks') or {}).items() if not v] + ([r['error']] if r.get('error') else []) for k, r in report['results'].items() if not r.get('ok')},
                      'report': str(work / 'browser-binding-live.json')}, ensure_ascii=False))
    return 0 if report['ok'] else 1


if __name__ == '__main__': raise SystemExit(main(sys.argv[1]))
