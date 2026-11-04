"""Pinned APK audits and typed ADB scenarios. No worker-controlled host shell."""
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import struct
import time
import xml.etree.ElementTree as ET
import zipfile

from .ledger import LedgerError,canonical,content_hash,exact_fields
from .delivery_device_env import EMULATOR_SERIAL
from .workflow import task_lock
from .delivery_steps import bounded,file_hash,home
from .snapshots import durable_write


def elf_alignment(data):
    if data[:4]!=b'\x7fELF' or len(data)<64: raise LedgerError('Invalid native ELF.')
    wide=data[4]==2
    if data[4] not in (1,2) or data[5] not in (1,2):raise LedgerError('Unsupported ELF header.')
    endian='<' if data[5]==1 else '>'
    read=lambda fmt,off:struct.unpack_from(endian+fmt,data,off)[0]
    start=read('Q' if wide else 'I',32 if wide else 28)
    size=read('H',54 if wide else 42);count=read('H',56 if wide else 44)
    if count>2048 or size<(56 if wide else 32):raise LedgerError('Invalid ELF program headers.')
    loads=[]
    for i in range(count):
        off=start+i*size
        if off+size>len(data):raise LedgerError('Truncated ELF headers.')
        if read('I',off)!=1:continue
        pos=read('Q' if wide else 'I',off+(8 if wide else 4))
        addr=read('Q' if wide else 'I',off+(16 if wide else 8))
        align=read('Q' if wide else 'I',off+(48 if wide else 28))
        loads.append(align>=16384 and (pos-addr)%16384==0)
    if not loads:raise LedgerError('ELF has no loadable segments.')
    return {'bits':64 if wide else 32,'load_segments':len(loads),'aligned_16kb':all(loads)}


def apk_input(s,node):
    r=s['delivery']['nodes'][node['config']['build_node']]['receipt']
    if not r or not r.get('passed') or file_hash(r['apk'])!=r['sha256']:raise LedgerError('APK changed or build receipt unavailable.')
    if r['source']!=s['delivery']['source']['hash']:raise LedgerError('APK belongs to stale source.')
    return r


def audit(runtime,task,s,node):
    c=node['config'];build=apk_input(s,node);apk=Path(build['apk']);tools=Path(c['build_tools'])
    suffix='.exe' if os.name=='nt' else ''
    java=shutil.which('java')
    if not java:raise LedgerError('Java unavailable for APK signer audit.')
    rc,signature,_=bounded(runtime,task,[java,'-jar',str(tools/'lib/apksigner.jar'),'verify','--verbose','--print-certs',str(apk)],home(runtime,task),60)
    signers=re.findall(r'Signer #\d+ certificate SHA-256 digest:\s*([0-9a-fA-F]{64})',signature)
    signature_ok=rc==0 and bool(signers) and {x.lower() for x in signers}=={c['signer_sha256'].lower()}
    zargs=[str(tools/('zipalign'+suffix)),'-c']+(['-P','16'] if c['require_16kb'] else [])+['4',str(apk)]
    zrc,_,_=bounded(runtime,task,zargs,home(runtime,task),60)
    arc,badging,_=bounded(runtime,task,[str(tools/('aapt2'+suffix)),'dump','badging',str(apk)],home(runtime,task),60)
    package=re.search(r"package: name='([^']+)'",badging)
    version=re.search(r"versionCode='([^']+)'",badging)
    version_ok='version_code' not in c or version is not None and version[1]==c['version_code']
    variant_ok=build.get('variant')!='release' or 'application-debuggable' not in badging
    libraries=[]
    with zipfile.ZipFile(apk) as z:
        names=z.namelist();unique=len(names)==len(set(names));crc=z.testzip()
        compressed=sum(i.compress_size for i in z.infolist())
        for n in names:
            if n.startswith('lib/') and n.endswith('.so'):
                info=z.getinfo(n)
                if info.file_size>256_000_000:raise LedgerError('Native library exceeds audit limit.')
                libraries.append(dict(path=n,**elf_alignment(z.read(n))))
    # Large unreferenced ZIP payload is a packaging defect even if the signature verifies.
    overhead=apk.stat().st_size-compressed
    packaging_ok=unique and crc is None and overhead<=max(2_000_000,len(names)*2048)
    alignment_ok=not c['require_16kb'] or all(v['aligned_16kb'] for v in libraries if v['bits']==64)
    passed=signature_ok and zrc==0 and arc==0 and package is not None and package[1]==c['package_id'] and version_ok and variant_ok and packaging_ok and alignment_ok and apk.stat().st_size<=c['max_bytes']
    return {'passed':passed,'failure_kind':'artifact','detail':'APK policy passed.' if passed else 'APK signer/package/alignment/size/ZIP policy failed.',
        'packaging_anomaly':not packaging_ok,
        'sha256':build['sha256'],'source':build['source'],'signers':signers,'package':package[1] if package else None,
        'version_code':version[1] if version else None,'version_policy_checked':'version_code' in c,'variant_policy_passed':variant_ok,
        'zipalign_exit':zrc,'zip_unique':unique,'zip_crc':crc,'zip_overhead_bytes':overhead,'bytes':apk.stat().st_size,'native_libraries':libraries}


def scenario(path,digest):
    p=Path(path)
    if file_hash(p)!=digest:raise LedgerError('Device scenario changed since approval.')
    v=json.loads(p.read_text(encoding='utf-8-sig'))
    exact_fields(v,('version','activity','steps','cleanup'),'Android scenario')
    if v['version']!=1 or not isinstance(v['activity'],str) or not re.fullmatch(r'[A-Za-z0-9_.$]+',v['activity']):raise LedgerError('Pin launcher activity.')
    for key in ('steps','cleanup'):
        if not isinstance(v[key],list) or len(v[key])>100:raise LedgerError('Bounded scenario steps required.')
        for step in v[key]:
            exact_fields(step,('id','operation','arguments'),'Device step')
            if not isinstance(step['id'],str) or not re.fullmatch('[a-zA-Z0-9_-]{1,60}',step['id']):raise LedgerError('Step ID invalid.')
            args=step['arguments'];op=step['operation']
            fields={'assert_ui':{'selector'},'assert_absent':{'selector'},'tap':{'selector'},'type':{'selector','private_key'},
                    'scroll_to':{'selector','direction','max_swipes'},'wait_for':{'selector','timeout_seconds'},'key':{'key'},'restart':set(),
                    'assert_no_flutter_error':set()}
            if op not in fields or not isinstance(args,dict) or set(args)!=fields[op]:raise LedgerError('Unsupported device operation or arguments.')
            if 'selector' in args:
                selector=args['selector']
                if not isinstance(selector,dict) or not selector or set(selector)-SELECTOR_KEYS or any(not isinstance(x,str) or len(x)>200 for x in selector.values()):
                    raise LedgerError('Typed exact UI selector required.')
            if op=='wait_for' and (type(args['timeout_seconds']) is not int or not 1<=args['timeout_seconds']<=60):raise LedgerError('UI wait must be bounded to 60 seconds.')
            if op=='key' and args['key'] not in ('BACK','ENTER','TAB'):raise LedgerError('Key not allowed.')
            if op=='type' and (not isinstance(args['private_key'],str) or not re.fullmatch('[A-Za-z0-9_]{1,80}',args['private_key'])):raise LedgerError('Private input key invalid.')
            if op=='scroll_to' and (args['direction'] not in ('up','down') or type(args['max_swipes']) is not int or not 1<=args['max_swipes']<=6):raise LedgerError('Scroll must be bounded.')
    ids=[s['id'] for s in v['steps']+v['cleanup']]
    if not v['steps'] or len(ids)!=len(set(ids)):raise LedgerError('Nonempty steps with unique IDs required.')
    return v


SELECTOR_KEYS={'text','resource-id','content-desc','hint','class','checked','focused'}
# Visible label attributes. Flutter puts a Text into content-desc (empty text), a TextField's value into text and
# its label (joined with ', ' to an error text) into hint, and merges child labels into a parent with newlines.
LABELS=('text','content-desc','hint')
TIERS=('exact','label','label_part','label_casefold')


class SelectorUnresolved(LedgerError):
    """A selector did not name exactly one node in the live UI (not found, ambiguous or never appeared)."""
    def __init__(self,message,reason,matches=0):
        super().__init__(message);self.reason=reason;self.matches=matches


def _parts(value):
    return [p.strip() for p in re.split(r'\n|, ',value or '') if p.strip()]


def _label(n,key,value,tier):
    if tier==0:
        # Exact attribute; a text selector also names a Flutter label exposed as content-desc with empty text.
        return n.attrib.get(key)==value or (key=='text' and not n.attrib.get('text') and n.attrib.get('content-desc')==value)
    labels=[n.attrib.get(k) or '' for k in LABELS]
    if tier==1:return value in labels
    parts=[p for x in labels for p in _parts(x)]
    if tier==2:return value in parts
    folded=value.casefold()
    if tier==3:return any(folded==x.casefold() for x in labels+parts)
    return any(folded in x.casefold() for x in labels)  # presence only (assert_absent): any visible mention


def _matches(n,selector,tier):
    return all(_label(n,k,v,tier) if k in LABELS else n.attrib.get(k)==v for k,v in selector.items())


def selector_mode(c):
    """'exact' for a physical device unless the approved stage says otherwise; 'tiered' for an emulator.
    Exact: attribute equality only, no relaxed tier, no calibration, no UI data to any model."""
    from .delivery_device_env import EMULATOR_SERIAL
    return c.get('selectors') or ('tiered' if EMULATOR_SERIAL.fullmatch(c.get('serial') or '') else 'exact')


def resolve(xml,selector,exact=False):
    """(node, tier) from the live UI. Label tiers relax only how a visible label is written (exact attribute,
    any label attribute, one merged part, case); the first tier with any match must have exactly one.
    exact=True: every key must equal the attribute as written (no label fallback, no relaxed tier)."""
    nodes=list(ET.fromstring(xml).iter('node'))
    if exact:
        found=[n for n in nodes if all(n.attrib.get(k)==v for k,v in selector.items())]
        if len(found)==1:return found[0],0
        raise SelectorUnresolved('UI precondition failed: selector must match exactly one visible node.',
                                 'ambiguous' if found else 'not_found',len(found))
    for tier in range(len(TIERS) if any(k in LABELS for k in selector) else 1):
        found=[n for n in nodes if _matches(n,selector,tier)]
        if len(found)==1:return found[0],tier
        if found:raise SelectorUnresolved('UI precondition failed: selector must match exactly one visible node.','ambiguous',len(found))
    raise SelectorUnresolved('UI precondition failed: selector must match exactly one visible node.','not_found')


def present(xml,selector,package):
    """Any node of the app that mentions the selector's labels in any form; absence needs none."""
    # The presence tier (case-folded substring of any label) includes every resolving tier.
    return any(n.get('package')==package and _matches(n,selector,len(TIERS)) for n in ET.fromstring(xml).iter('node'))


def snapshot(xml,package,private=()):
    """Bounded, sanitized view of the app's nodes for evidence and calibration. Private input values are masked."""
    nodes=[]
    for n in ET.fromstring(xml).iter('node'):
        if n.get('package')!=package:continue
        a={k:n.get(k) for k in ('class','text','content-desc','hint','resource-id','clickable','focused','checked','scrollable','bounds')
           if n.get(k) not in (None,'','false')}
        if not set(a)-{'class','bounds'}:continue  # layout containers carry nothing a selector could name
        for k in LABELS:
            if k in a:
                value=a[k]
                for secret in private:
                    if isinstance(secret,str) and len(secret)>=2:value=value.replace(secret,'<private>')
                a[k]=value[:160]
        nodes.append(a)
        if len(nodes)>=150:break
    return nodes


def masked_view(xml,package,selector):
    """Evidence for an exact-mode mismatch that reveals no screen text: per app node its structure and, for each
    label key of the selector, how its label relates to the expected value (equal / casefold / contains / none)."""
    nodes=[]
    for n in ET.fromstring(xml).iter('node'):
        if n.get('package')!=package:continue
        a={k:n.get(k) for k in ('class','resource-id','clickable','focused','checked','enabled','scrollable','bounds') if n.get(k) not in (None,'','false')}
        for k in LABELS:
            value=n.get(k) or ''
            if value:a[k]={'length':len(value)}
            if k in selector and value:
                want=selector[k]
                a[k]['vs_expected']=('equal' if value==want else 'casefold' if value.casefold()==want.casefold() else
                                    'contains' if want and want.casefold() in value.casefold() else 'none')
        if set(a)-{'class','bounds','enabled'}:nodes.append(a)
        if len(nodes)>=150:break
    return nodes


def find_ui(xml,selector,package=None,viewport=None,evidence=None,exact=False):
    node,tier=resolve(xml,selector,exact)
    if evidence is not None:evidence['selector_tier']=TIERS[tier]
    bounds=re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',node.get('bounds',''))
    if package is not None and node.get('package')!=package:raise LedgerError('UI target belongs to another package.')
    if not bounds or node.get('enabled')=='false':raise LedgerError('UI target disabled or bounds unavailable.')
    x1,y1,x2,y2=map(int,bounds.groups())
    if x2<=x1 or y2<=y1:raise LedgerError('UI target not hit-testable.')
    if viewport and (x2>viewport[0] or y2>viewport[1]):raise LedgerError('UI target is outside the visible input area (off-screen or under the keyboard/overlay).')
    return node,((x1+x2)//2,(y1+y2)//2)


class SwipeRefused(LedgerError):
    """No safe gesture surface this round; the caller may re-read the UI without injecting input."""


def foreground_focus(dump):
    """Focused window of the top focused display from `dumpsys window`.

    Android 16 prints mCurrentFocus per display under `displays` (a secondary display may say null),
    not under `windows`. Ambiguity fails closed (None)."""
    top=re.search(r'mTopFocusedDisplayId=(-?\d+)',dump)
    sections=re.split(r'(?=Display: mDisplayId=)',dump)
    if top and len(sections)>1:
        for section in sections[1:]:
            if re.match(r'Display: mDisplayId='+re.escape(top[1])+r'\b',section):
                m=re.search(r'mCurrentFocus=([^\r\n]+)',section)
                value=m[1].strip() if m else ''
                return None if value in ('','null') else value
        return None
    values=[v.strip() for v in re.findall(r'mCurrentFocus=([^\r\n]+)',dump) if v.strip() not in ('','null')]
    return values[0] if len(set(values))==1 else None


def app_has_focus(dump, package):
    focus=foreground_focus(dump)
    return bool(focus and re.search(r'\b'+re.escape(package)+'/',focus))


def keyboard_top(dump, input_method, height):
    """Top edge of a visible keyboard, None when hidden.

    Insets state is authoritative; mIsInputViewShown can stay true while the keyboard is hidden and
    the IME window frame can cover the whole screen, so neither alone marks the keyboard edge."""
    tops=[];visible=False
    for line in re.findall(r'[^\r\n]*InsetsSource\b[^\r\n]*\btype=ime\b[^\r\n]*',dump):
        if not re.search(r'\bvisible=true\b',line):continue
        visible=True
        for key in ('frame','visibleFrame'):
            m=re.search(r'\b'+key+r'=\[(\d+),(\d+)\]\[(\d+),(\d+)\]',line)
            if m and int(m[4])>int(m[2]) and int(m[2])>=height//4:tops.append(int(m[2]))
    shown=visible or bool(re.search(r'\bmInputShown=true\b',input_method))
    if not shown:return None
    if not tops:
        for block in re.split(r'(?=Window #\d+)',dump):
            if not re.search(r'(?:InputMethod|type=2011|ty=INPUT_METHOD)',block):continue
            for m in re.finditer(r'(?:mFrame|frame)=\[(\d+),(\d+)\]\[(\d+),(\d+)\]',block):
                # A full-height IME window is not the keyboard edge.
                if int(m[4])>int(m[2])>=height//4:tops.append(int(m[2]))
    if not tops:raise SwipeRefused('Visible keyboard bounds unavailable; swipe refused.')
    return min(tops)


def _bounds(value):
    m=re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',value)
    return tuple(map(int,m.groups())) if m else None


def input_area(xml, package, viewport, windows, input_method):
    """(width, bottom) of the screen region input may reach: above a visible keyboard and foreign
    lower-half surfaces. Unknown keyboard bounds raise SwipeRefused; callers never guess coordinates."""
    root=ET.fromstring(xml);width,height=viewport;edges=[]
    for n in root.iter('node'):
        b=_bounds(n.get('bounds',''))
        # Foreign surfaces in the lower half (keyboard, navigation) bound the gesture; status bars do not.
        if b and n.get('package') not in (None,'',package) and b[2]>b[0] and b[3]>b[1] and b[1]>=height//2:
            edges.append(b[1])
    ime=keyboard_top(windows,input_method,height)
    if ime is not None:edges.append(ime)
    return width,min([height]+edges)


def scroll_gesture(xml, package, viewport, windows, input_method, direction):
    """Use a unique app scroll surface, clipped above a visible keyboard."""
    root=ET.fromstring(xml);width,bottom=input_area(xml,package,viewport,windows,input_method)
    bounds=_bounds
    surfaces=set()
    for n in root.iter('node'):
        b=bounds(n.get('bounds',''))
        if n.get('package')==package and n.get('scrollable')=='true' and n.get('enabled')!='false' and b:
            x1,y1,x2,y2=b;b=(max(0,x1),max(0,y1),min(width,x2),min(bottom,y2))
            if b[2]-b[0]>=40 and b[3]-b[1]>=80:surfaces.add(b)
    if len(surfaces)!=1:raise SwipeRefused('A unique visible app scroll surface is required; swipe refused.')
    x1,y1,x2,y2=surfaces.pop();x=(x1+x2)//2;lo=y1+(y2-y1)//4;hi=y2-(y2-y1)//4
    return [x,hi,x,lo] if direction=='up' else [x,lo,x,hi]


class PermissionExpired(LedgerError):
    """The approved device window ended; no further device command may be sent."""


def permission_left(c):
    """Seconds left in the approved device window (inf without one). Checked before every device command."""
    if not c.get('valid_until'):return float('inf')
    end=dt.datetime.fromisoformat(c['valid_until'])
    if end.tzinfo is None:end=end.astimezone()
    left=(end-dt.datetime.now(dt.timezone.utc)).total_seconds()
    if left<=0:raise PermissionExpired('Device permission expired (valid_until); no further device command sent.')
    return left


def device_directory(runtime,task,node,row):
    return home(runtime,task)/('device-'+node['id']+'-'+str(row['generation']))


def effects_started(runtime,task,node,row):
    """Last durable intent of this node generation, or None when no device effect began."""
    path=device_directory(runtime,task,node,row)/'intent.json'
    try:return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
    except (OSError,ValueError):return {'unreadable':True}


def reconcile(runtime,task,s,node,row):
    """Read-only evidence after an interrupted device node. Never installs, taps or clears data."""
    c=node['config'];effects=effects_started(runtime,task,node,row);out={'intent':effects,'replay':False}
    try:permission_left(c)
    except PermissionExpired:
        # Even a read-only probe is a device command: after the window it is not sent, and nothing is replayed.
        out.update(permission_expired=True,detail='Device permission expired; device state not probed and nothing replayed.')
        return out
    try:
        build=apk_input(s,node);directory=home(runtime,task)
        rc,state,_=bounded(runtime,task,[c['adb'],'-s',c['serial'],'get-state'],directory,min(15,permission_left(c)))
        out['device']=state.strip() if rc==0 else 'unavailable'
        if out['device']=='device':
            rc,paths,_=bounded(runtime,task,[c['adb'],'-s',c['serial'],'shell','pm','path',c['package_id']],directory,min(15,permission_left(c)))
            lines=paths.strip().splitlines() if rc==0 else []
            if len(lines)==1 and re.fullmatch(r'package:/[A-Za-z0-9_./=+~-]+\.apk',lines[0]):
                rc,digest,_=bounded(runtime,task,[c['adb'],'-s',c['serial'],'shell','sha256sum',lines[0][8:]],directory,min(30,permission_left(c)))
                out['installed_matches_audited']=rc==0 and digest.split()[:1]==[build['sha256']]
            if EMULATOR_SERIAL.fullmatch(c['serial']) and (effects or {}).get('boot_id'):
                from .delivery_device_env import parse_boot_id
                rc,now,_=bounded(runtime,task,[c['adb'],'-s',c['serial'],'shell','cat','/proc/sys/kernel/random/boot_id'],directory,min(15,permission_left(c)))
                now=parse_boot_id(now) if rc==0 else None
                out['instance']='unreadable' if now is None else 'same' if now==effects['boot_id'] else 'replaced'
    except (ValueError,OSError) as error:out['probe_error']=str(error)[:300]
    if effects and effects.get('boot_id') and out.get('instance')!='same':
        # The interrupted attempt's effects are bound to its pinned instance: a replay (a recovery) is never sent to a
        # replacement or to an instance that cannot be shown to be the same one.
        out['detail']=('The interrupted attempt ran on emulator instance '+effects['boot_id'][:8]+'; the instance now on '+
                       c['serial']+' is '+str(out.get('instance','not readable'))+'. Nothing is replayed on it.')
    elif not effects:out.update(replay=True,detail='No device effect had started.')
    elif effects.get('operation')=='install':out.update(replay=True,detail='Only install -r of the audited APK may have run; reinstall is idempotent.')
    elif c.get('replay_safe'):out.update(replay=True,detail='Scenario declared replay-safe; rerun from install with its cleanup.')
    else:out['detail']='Scenario steps may have changed app or server state and the scenario is not declared replay-safe.'
    return out


# Commands that only read (a prefix of the argv); everything else counts as a change and passes the instance gate.
READ_ONLY=(('get-state',),('exec-out','uiautomator','dump','/dev/tty'),('shell','dumpsys','window'),('shell','dumpsys','power'),
           ('shell','dumpsys','input_method'),('shell','getprop'),('shell','pidof'),('logcat','-d'),('shell','sha256sum'),
           ('shell','pm','path'),('shell','date','+%s'),('shell','cat','/proc/sys/kernel/random/boot_id'),('emu','avd','name'),
           ('shell','wm','size'))


def mutating(args):
    """Every adb command not on the read-only allowlist is treated as a change to the device."""
    return not any(tuple(args[:len(p)])==p for p in READ_ONLY)


class StepDeadline(LedgerError):
    """The current step's own bound (a UI wait) ran out; the scenario and permission bounds still hold."""


def active_scenario(node,row):
    """(path, sha256, revision) the node runs: the sealed scenario, or OneCrew's latest calibrated revision of a
    scenario it planned itself. A user-pinned scenario is never replaced."""
    current=(row or {}).get('scenario')
    if current and node['config'].get('calibration')=='onecrew':return current['path'],current['sha256'],current.get('revision',0)
    return node['config']['scenario'],node['config']['scenario_sha256'],0


def device(runtime,task,s,node,row):
    c=node['config'];build=apk_input(s,node)
    path,digest,revision=active_scenario(node,row);v=scenario(path,digest)
    permission_left(c)  # before any device action; every later command checks again
    reference=Path(c['private_reference']) if c['private_reference'] else None
    private=json.loads(reference.read_text(encoding='utf-8-sig')) if reference else {}
    if not isinstance(private,dict):raise LedgerError('Private scenario inputs must be a mapping.')
    private_digest=file_hash(reference) if reference else None
    directory=device_directory(runtime,task,node,row);directory.mkdir(exist_ok=True)
    # Reaching here means any earlier intent was reconciled; a stale marker must not describe this run.
    (directory/'intent.json').unlink(missing_ok=True)
    environment={'actions':[],'emulator_started':False}
    exact=selector_mode(c)=='exact'
    from .delivery_device_env import recovery_grant
    allowed=recovery_grant(c)
    receipt={'passed':False,'source':build['source'],'apk_sha256':build['sha256'],'serial':c['serial'],'package':c['package_id'],
        'scenario_sha256':digest,'scenario_revision':revision,'private_version':c['private_version'],'steps':[],'cleanup':[],
        'live_device':True,'failure_kind':'device','environment':environment,'selector_mode':'exact' if exact else 'tiered'}
    start=time.monotonic()
    viewport=None
    effect_pending=False
    operation_deadline=None
    step_evidence={}
    current={'step':None,'operation':None,'tree':None}
    refocus_left=[3]
    launched={'epoch':0}
    pinned={}  # the emulator instance verified for this attempt: {'avd':…, 'boot_id':…}
    emulator_serial=bool(EMULATOR_SERIAL.fullmatch(c['serial']))
    def adb(*args,effect=True):
        nonlocal effect_pending
        left=c['timeout_seconds']-(time.monotonic()-start)
        # The approved window bounds every command, so none starts or runs past valid_until.
        left=min(left,permission_left(c))
        if left<=0:raise LedgerError('Device scenario/operation timeout.')
        if emulator_serial and mutating(args):
            # Codex follow-up P1-2: the one place every install, input, am, wm, recovery, cleanup and kill passes.
            same_instance('before '+' '.join(args[:3]))
        if operation_deadline is not None:
            step=operation_deadline-time.monotonic()
            if step<=0:raise StepDeadline('Device step deadline reached.')
            left=min(left,step)
        effect_pending=effect and (args[0]=='install' or args[:2] in (('shell','input'),('shell','am')))
        rc,out,err=bounded(runtime,task,[c['adb'],'-s',c['serial'],*args],directory,min(45,left))
        if rc:raise LedgerError('ADB operation failed; raw output withheld to protect private inputs.')
        effect_pending=False
        return out
    def system(*args):
        # Recovery input to system UI (wake, keyguard, a "not responding" dialog's Wait) never changes app state.
        return adb(*args,effect=False)
    def xml():
        # exec-out is bounded; never save the entire UI tree, which may contain account data.
        out=adb('exec-out','uiautomator','dump','/dev/tty')
        begin=out.find('<?xml');end=out.rfind('</hierarchy>')
        if begin<0 or end<0:raise LedgerError('Android UI hierarchy unavailable.')
        current['tree']=out[begin:end+len('</hierarchy>')]
        return current['tree']
    def record(action,detail):
        environment['actions'].append({'action':action,'detail':str(detail or '')[:160],'step':current['step'],'at':time.monotonic()-start})
    def probe(*args,seconds=15):
        # Raw read: an absent or booting device is an answer here, not an ADB failure.
        rc,out,_=bounded(runtime,task,[c['adb'],'-s',c['serial'],*args],directory,min(seconds,permission_left(c)))
        return out.strip() if rc==0 else None
    def booted():
        return (probe('get-state') or 'absent'),(probe('shell','getprop','sys.boot_completed') or '')
    def same_instance(purpose):
        """Refuse unless the instance on the serial is still the one verified for this attempt (same boot_id; a
        replacement, even of the same AVD, boots with another id). Nothing is sent to an unverified instance."""
        from .delivery_device_env import EmulatorIdentityError,parse_boot_id
        if not pinned:
            raise EmulatorIdentityError('No verified emulator instance on '+c['serial']+' ('+purpose+'); no command sent.')
        for attempt in range(3):
            # An unreadable answer is read again (a transport hiccup is not a replacement); a different id never is.
            now=parse_boot_id(probe('shell','cat','/proc/sys/kernel/random/boot_id'))
            if now is not None:break
            time.sleep(1)
        if now!=pinned['boot_id']:
            environment['identity_lost']={'purpose':purpose[:80],'pinned':pinned['boot_id'][:8],'now':now[:8] if now else None}
            raise EmulatorIdentityError('Emulator instance on '+c['serial']+' changed or is unreadable since it was verified ('+
                                        purpose+'); no command sent to it.')
    def pin(avd,boot_id):
        pinned.clear();pinned.update(avd=avd,boot_id=boot_id)
    # Ownership of an emulator OneCrew booted survives attempts and coordinator restarts (Codex P2, 12/10).
    owner_file=home(runtime,task)/('emulator-'+re.sub(r'[^A-Za-z0-9_.-]','_',c['serial'])+'.json')
    def identity():
        """(avd, boot_id) of the instance on the pinned serial; None where it cannot be read."""
        from .delivery_device_env import parse_avd_name,parse_boot_id
        return parse_avd_name(probe('emu','avd','name')),parse_boot_id(probe('shell','cat','/proc/sys/kernel/random/boot_id'))
    def owner():
        try:return json.loads(owner_file.read_text(encoding='utf-8')) if owner_file.is_file() else None
        except (OSError,ValueError):return None
    def verify(purpose):
        """The pinned serial must carry the approved AVD before anything changes it (Codex P1-2). 'owned' only when this
        exact boot is the one OneCrew started and recorded; an instance the user opened, or a replacement, is 'borrowed'."""
        from .delivery_device_env import EmulatorIdentityError
        avd,boot_id=identity()
        environment['identity']={'avd':avd,'boot_id':boot_id[:8] if boot_id else None,'checked_for':purpose}
        if avd is not None and avd!=c['emulator']['avd']:
            raise EmulatorIdentityError('Emulator on '+c['serial']+' is AVD '+avd+', not the approved AVD '+c['emulator']['avd']+
                                        ' ('+purpose+'); no install, input or kill sent.')
        if avd is None or boot_id is None:
            raise EmulatorIdentityError('Emulator identity unverifiable on '+c['serial']+' ('+purpose+'); no install, input or kill sent.')
        if pinned and boot_id!=pinned['boot_id']:
            environment['identity_lost']={'purpose':purpose,'pinned':pinned['boot_id'][:8],'now':boot_id[:8]}
            raise EmulatorIdentityError('Emulator instance on '+c['serial']+' changed since it was verified ('+purpose+'); no command sent to it.')
        pin(avd,boot_id)
        mine=owner()
        environment['ownership']='owned' if mine and mine.get('boot_id')==boot_id and mine.get('avd')==avd else 'borrowed'
        return environment['ownership']
    def boot(reason):
        from .delivery_device_env import boot_emulator,EmulatorIdentityError
        record('emulator_boot',reason);environment['emulator_started']=True
        environment['boot']=boot_emulator(c['adb'],c['serial'],c['emulator'],directory/'emulator.log',booted,window=permission_left(c))
        avd,boot_id=identity()
        if avd!=c['emulator']['avd'] or boot_id is None:
            raise EmulatorIdentityError('The emulator that came up on '+c['serial']+' is not provably the approved AVD; no install or input sent.')
        durable_write(owner_file,canonical({'serial':c['serial'],'avd':avd,'boot_id':boot_id,'task':task,
                                            'pid':(environment['boot'] or {}).get('pid'),'at':time.time()}).encode())
        pin(avd,boot_id)
        environment['ownership']='owned';environment['identity']={'avd':avd,'boot_id':boot_id[:8],'checked_for':'boot'}
    def restart(reason):
        """Only the verified instance OneCrew itself booted is killed and rebooted; anything else is left alone."""
        from .delivery_device_env import kill_emulator
        if verify('restart')!='owned':
            record('emulator_restart_refused','not booted by OneCrew: '+reason);return False
        record('emulator_stop',reason)
        if not kill_emulator(system):raise LedgerError('Pinned emulator could not be stopped for a restart; nothing else sent.')
        owner_file.unlink(missing_ok=True);pinned.clear()
        for _ in range(20):
            if (probe('get-state') or 'absent')=='absent':break
            time.sleep(3)
        boot(reason);return True
    def prepare():
        """Usable device before install: granted, data-preserving recovery only; one emulator restart at most."""
        from .delivery_device_env import ensure_server,settle,blocked,EnvironmentUnusable
        environment['adb_server']=ensure_server(c['adb'])
        state=probe('get-state') or 'absent'
        try:last=json.loads((directory/'receipt.json').read_text(encoding='utf-8')) if (directory/'receipt.json').is_file() else {}
        except (OSError,ValueError):last={}
        if c.get('emulator'):
            if state=='absent':boot('device absent')
            else:
                verify('prepare')  # before any install, input or kill on this serial
                if state!='device':restart('device '+state)
                elif (last.get('app_crash') or {}).get('kind')=='native':
                    # Trial 5 (12/10): after a native Flutter raster crash every launch crashed until the emulator restarted.
                    restart('previous run: app crashed natively on the emulator')
        elif state!='device':raise LedgerError('Authorized device not ready.')
        elif emulator_serial:
            # No approved AVD: the approval names only the serial, so the instance found now is pinned for this attempt.
            from .delivery_device_env import EmulatorIdentityError,parse_boot_id
            boot_id=parse_boot_id(probe('shell','cat','/proc/sys/kernel/random/boot_id'))
            if boot_id is None:raise EmulatorIdentityError('Emulator identity unverifiable on '+c['serial']+'; no command sent.')
            pin(None,boot_id)
            environment['identity']={'avd':None,'boot_id':boot_id[:8],'checked_for':'prepare'}
        # A fresh boot settles under load for minutes; an already running device gets a short bound.
        booted_now=lambda:environment['emulator_started']
        health=settle(system,xml,record,seconds=240 if booted_now() else 60,stable=3 if booted_now() else 1,package=c['package_id'],allowed=allowed)
        if blocked(health) and c.get('emulator') and 'restart_emulator' in allowed and restart(','.join(blocked(health))):
            health=settle(system,xml,record,seconds=240,stable=3,package=c['package_id'],allowed=allowed)
        environment['health']=health
        needs=sorted({a['action'][len('needs_permission:'):] for a in environment['actions'] if a['action'].startswith('needs_permission:')})
        if blocked(health) and needs:
            raise EnvironmentUnusable('Device recovery requires permission not granted for this device: '+','.join(needs)+
                                      '; blocked by '+','.join(blocked(health))+'. No recovery action was sent.')
        if blocked(health):
            done=sorted({a['action'] for a in environment['actions']})
            raise EnvironmentUnusable('Android device not usable after granted recovery: '+','.join(blocked(health))+'; focus '+
                                      health['focus'][:120]+'; actions '+','.join(done)+' ('+str(len(environment['actions']))+')')
    def refocus():
        """The app lost focus: one bounded system recovery (dialog Wait, wake, keyguard), never a blind input."""
        if refocus_left[0]<=0:return adb('shell','dumpsys','window')
        refocus_left[0]-=1
        gone()  # a crashed app is evidence, never a dialog to dismiss and continue past
        from .delivery_device_env import settle
        settle(system,xml,record,seconds=90,allowed=allowed)
        return adb('shell','dumpsys','window')
    def alive():
        return bool((probe('shell','pidof',c['package_id']) or '').strip())
    def gone():
        """Raise AppCrashed with a sanitized summary when the app under test is not running."""
        from .delivery_device_env import AppCrashed,crash_summary,describe
        if alive():return
        since=launched['epoch']
        text=probe('logcat','-d','-b','crash','-T',str(since)+'.000',seconds=30) if since else probe('logcat','-d','-b','crash','-t','400',seconds=30)
        crash=crash_summary(text,c['package_id']) or {'kind':'none'}
        receipt['app_crash']=crash
        if crash['kind']=='java':
            receipt['failure_kind']='product'
            raise AppCrashed('App crashed on the device ('+describe(crash)+'); the app must not crash in this flow.')
        emulator=' on the emulator; emulator graphics/runtime suspected' if c.get('emulator') and crash['kind']=='native' else ''
        raise AppCrashed('App process died during the device scenario ('+describe(crash)+')'+emulator+'.')
    def launch(restart_app=False):
        """Start the pinned activity and confirm the app process runs and holds focus; 'Status: ok' alone is not proof."""
        if restart_app:adb('shell','am','force-stop',c['package_id'])
        try:launched['epoch']=int((probe('shell','date','+%s') or '0').strip() or 0)
        except ValueError:launched['epoch']=0
        adb('shell','am','start','-W','-n',c['package_id']+'/'+v['activity'])
        for _ in range(10):
            windows=adb('shell','dumpsys','window')
            if app_has_focus(windows,c['package_id']):return
            if not alive():break
            if foreground_focus(windows) is None:break  # focus unreadable: the input steps decide, as before
            time.sleep(.5)
        gone()  # alive but not focused yet: each input step checks focus and recovers within its own bound
    def perform(step):
        nonlocal operation_deadline,step_evidence
        step_evidence={}
        op=step['operation'];a=step['arguments'];windows=None
        current.update(step=step['id'],operation=op)
        if op in ('tap','type','key','scroll_to'):
            # Full dump: Android 16 reports focus per display, not under `dumpsys window windows`.
            windows=adb('shell','dumpsys','window')
            if not app_has_focus(windows,c['package_id']):windows=refocus()
            if not app_has_focus(windows,c['package_id']):
                raise LedgerError('Another window has foreground focus; input refused.')
        if op=='assert_ui':find_ui(xml(),a['selector'],c['package_id'],viewport,step_evidence,exact)
        if op=='assert_absent':
            if present(xml(),a['selector'],c['package_id']):
                receipt['failure_kind']='product'
                raise LedgerError('Device shows a UI element the scenario requires to be absent (step '+step['id']+').')
        if op in ('tap','type'):
            tree=xml()
            try:area=input_area(tree,c['package_id'],viewport,windows,adb('shell','dumpsys','input_method'))
            except SwipeRefused as unknown:raise LedgerError('Keyboard bounds unknown; input refused.') from unknown
            # The whole target must lie in the reachable area, so a tap never lands on the keyboard.
            element,(x,y)=find_ui(tree,a['selector'],c['package_id'],area,step_evidence,exact)
            step_evidence.update(input_area=list(area),point=[x,y])
            if op=='tap':adb('shell','input','tap',str(x),str(y))
            elif op=='type':
                value=private.get(a['private_key'])
                # Android input text goes through a remote shell; whitelist rather than quote arbitrary shell syntax.
                if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9@._:+/-]{1,150}',value):raise LedgerError('Private input unsupported by typed ADB text adapter.')
                if element.get('class')!='android.widget.EditText':raise LedgerError('Typing requires an editable target.')
                adb('shell','input','tap',str(x),str(y))
                focused,_=find_ui(xml(),dict(a['selector'],focused='true'),c['package_id'],viewport,None,exact)
                adb('shell','input','keyevent','KEYCODE_MOVE_END')
                for _ in range(min(len(focused.get('text','')),150)):adb('shell','input','keyevent','KEYCODE_DEL')
                adb('shell','input','text',value)
        elif op=='key':adb('shell','input','keyevent','KEYCODE_'+a['key'])
        elif op=='restart':launch(restart_app=True)
        elif op=='wait_for':
            operation_deadline=time.monotonic()+a['timeout_seconds'];attempts=0;unavailable=0;checked=time.monotonic()
            try:
                while True:
                    attempts+=1
                    try:
                        # uiautomator can miss a frame during transitions; ADB failures stay fatal.
                        tree=xml();find_ui(tree,a['selector'],c['package_id'],viewport,step_evidence,exact);break
                    except StepDeadline:
                        break_reason='deadline'
                    except LedgerError as e:
                        if str(e).startswith('ADB operation failed') or 'scenario/operation timeout' in str(e):raise
                        unavailable+=str(e)=='Android UI hierarchy unavailable.'
                        break_reason=None
                    left=operation_deadline-time.monotonic()
                    if break_reason or left<=0:
                        operation_deadline=None
                        focus=foreground_focus(adb('shell','dumpsys','window'))
                        if focus and not re.search(re.escape(c['package_id'])+'/',focus):
                            gone()  # trial 5: the "other window" was the launcher after the app crashed
                            # A system dialog (e.g. System UI not responding) is an environment problem, not an app failure.
                            raise LedgerError('Another window has foreground focus during a UI wait: '+focus[:120])
                        raise SelectorUnresolved('UI wait timeout: selector never matched exactly one visible node.','timeout')
                    if time.monotonic()-checked>=3:
                        # A system dialog that took focus is answered within the step, once per bound, then the wait goes on.
                        checked=time.monotonic()
                        focus=foreground_focus(adb('shell','dumpsys','window'))
                        if focus and not re.search(re.escape(c['package_id'])+'/',focus) and refocus_left[0]>0:refocus()
                    time.sleep(min(.25,max(left,0)))
                step_evidence.update(polls=attempts,hierarchy_unavailable=unavailable)
            finally:operation_deadline=None
        elif op=='scroll_to':
            gestures=[];step_evidence['gestures']=gestures
            for i in range(a['max_swipes']+1):
                tree=xml()
                if i:
                    windows=adb('shell','dumpsys','window')
                    if not app_has_focus(windows,c['package_id']):windows=refocus()
                    if not app_has_focus(windows,c['package_id']):
                        raise LedgerError('Another window has foreground focus; swipe refused.')
                ime=adb('shell','dumpsys','input_method')
                try:
                    # Reached means the next tap is safe: the target lies above the keyboard, not merely on screen.
                    area=input_area(tree,c['package_id'],viewport,windows,ime)
                    try:
                        find_ui(tree,a['selector'],c['package_id'],area,step_evidence,exact)
                        step_evidence['input_area']=list(area);break
                    except SwipeRefused:raise
                    except LedgerError:
                        if i==a['max_swipes']:raise
                    coords=scroll_gesture(tree,c['package_id'],viewport,windows,ime,a['direction'])
                except SwipeRefused as refused:
                    # Unknown keyboard edge or no safe surface: re-read only, never a blind gesture.
                    if i==a['max_swipes']:raise LedgerError('UI target not confirmed reachable: '+str(refused)) from refused
                    gestures.append({'refused':str(refused)});time.sleep(.5);continue
                gestures.append({'coordinates':coords,'duration_ms':350})
                adb('shell','input','swipe',*map(str,coords),'350')
        elif op=='assert_no_flutter_error':
            # Restrict logs to this app process. Store only the result, not server/account data.
            gone()
            pid=adb('shell','pidof',c['package_id']).strip()
            if not re.fullmatch(r'\d+',pid):raise LedgerError('App process unavailable.')
            logs=adb('logcat','-d','--pid='+pid,'-t','500','flutter:E','*:S')
            if re.search('RenderFlex overflowed|Unhandled Exception|EXCEPTION CAUGHT',logs,re.I):
                receipt['failure_kind']='product';raise LedgerError('Flutter runtime error observed.')
    # A single lock per serial (including other root tasks) lasts through install, tests and cleanup.
    with task_lock(runtime.ledger,'device-'+content_hash(c['serial'])[:24]):
        prepare()
        if adb('get-state').strip()!='device':raise LedgerError('Authorized device not ready.')
        sizes=re.findall(r'(\d+)x(\d+)',adb('shell','wm','size'))
        if not sizes:raise LedgerError('Device viewport unavailable.')
        viewport=tuple(map(int,sizes[-1]));receipt['viewport']=list(viewport)
        # The caller already audited the signer; install -r must not silently uninstall to solve a mismatch.
        intent=directory/'intent.json'
        durable_write(intent,canonical({'task':task,'operation':'install','apk':build['sha256'],'boot_id':pinned.get('boot_id')}).encode())
        try:
            result=adb('install','-r',build['apk'])
            if 'Success' not in result:raise LedgerError('APK installation not confirmed.')
            paths=adb('shell','pm','path',c['package_id']).strip().splitlines()
            if len(paths)!=1 or not paths[0].startswith('package:'):raise LedgerError('Installed APK identity is ambiguous.')
            remote=paths[0][8:]
            if not re.fullmatch(r'/[A-Za-z0-9_./=+~-]+\.apk',remote):raise LedgerError('Invalid installed package path.')
            digest_installed=adb('shell','sha256sum',remote).split()[0]
            if digest_installed!=build['sha256']:raise LedgerError('Installed APK differs from audited artifact.')
            receipt['installed_sha256']=digest_installed
            from .delivery_device_env import AppCrashed
            try:launch()
            except AppCrashed:
                # A native crash at launch on the approved emulator: one restart of that emulator, then one more launch
                # of the same verified install. A Java crash is a product finding and is never retried here.
                if (receipt.get('app_crash') or {}).get('kind')!='native' or not c.get('emulator') or environment.get('crash_restart'):raise
                environment['crash_restart']=True
                if not restart('app crashed natively at launch'):raise
                receipt.pop('app_crash',None)
                from .delivery_device_env import settle,blocked,EnvironmentUnusable
                health=settle(system,xml,record,seconds=240,stable=3,package=c['package_id'])
                if blocked(health):raise EnvironmentUnusable('Android device not usable after the crash restart: '+','.join(blocked(health)))
                again=adb('shell','pm','path',c['package_id']).strip().splitlines()
                if again!=paths or adb('shell','sha256sum',remote).split()[0]!=build['sha256']:raise LedgerError('Installed APK differs after the emulator restart.')
                launch()
            for step in v['steps']:
                receipt['scenario_started']=True
                durable_write(intent,canonical({'task':task,'step':step['id'],'state':'intent','boot_id':pinned.get('boot_id')}).encode())
                perform(step)
                if emulator_serial:same_instance('after step '+step['id'])  # its reads came from the pinned instance
                receipt['steps'].append({'id':step['id'],'passed':True,**step_evidence})
                durable_write(directory/'receipt.json',canonical(receipt).encode())
            receipt['passed']=True
        except (ValueError,OSError) as e:
            receipt['detail']=str(e)[:500];receipt['passed']=False;receipt['uncertain']=effect_pending
            receipt['failed_step_evidence']=step_evidence
            if isinstance(e,PermissionExpired):receipt['permission_expired']=True
            from .delivery_device_env import EmulatorIdentityError
            if isinstance(e,EmulatorIdentityError):receipt['identity_lost']=True
            if isinstance(e,SelectorUnresolved):
                # Evidence from the live UI at the failing step: what a calibration or a reviewer can see.
                receipt['failure_kind']='selector'
                receipt['selector_failure']={'step':current['step'],'operation':current['operation'],'reason':e.reason,'matches':e.matches}
                if current['tree']:
                    selector=next((s['arguments'].get('selector') for s in v['steps']+v['cleanup'] if s['id']==current['step']),None) or {}
                    # Exact mode (real device, e.g. HIS): structure and relation to the expected value only, never screen text.
                    nodes=masked_view(current['tree'],c['package_id'],selector) if exact else snapshot(current['tree'],c['package_id'],private.values())
                    view=directory/('ui-'+str(current['step'])+'.json')
                    durable_write(view,canonical({'step':current['step'],'package':c['package_id'],'masked':exact,
                                                  'selector':selector if exact else None,'nodes':nodes}).encode())
                    receipt['ui_snapshot']={'file':str(view),'sha256':file_hash(view),'nodes':len(nodes),'masked':exact}
        finally:
            from .delivery_device_env import EmulatorIdentityError
            for step in v['cleanup']:
                if receipt.get('identity_lost'):
                    # Cleanup is never sent to a replacement: nothing is read from or sent to it, and the verified
                    # instance's state stays unknown.
                    receipt['cleanup'].append({'id':step['id'],'passed':False,'skipped':'emulator instance lost'});receipt['passed']=False
                    receipt['uncertain']=receipt.get('uncertain',False) or bool(receipt.get('scenario_started'))
                    continue
                try:
                    perform(step)
                    if emulator_serial:same_instance('after cleanup '+step['id'])
                    receipt['cleanup'].append({'id':step['id'],'passed':True})
                except (ValueError,OSError) as e:
                    receipt['cleanup'].append({'id':step['id'],'passed':False});receipt['passed']=False
                    if isinstance(e,EmulatorIdentityError):
                        receipt['identity_lost']=True
                        receipt['uncertain']=receipt.get('uncertain',False) or bool(receipt.get('scenario_started'))
                        receipt.setdefault('detail','Emulator instance changed before cleanup; no cleanup sent to it.')
                    receipt['uncertain']=receipt.get('uncertain',False) or effect_pending
                    if isinstance(e,PermissionExpired):
                        # Cleanup cannot run after the window: steps that already ran leave an unknown device state.
                        receipt['permission_expired']=True
                        receipt['uncertain']=receipt.get('uncertain',False) or bool(receipt.get('scenario_started'))
                        receipt.setdefault('detail','Device permission expired before cleanup; no further device command sent.')
            if reference and file_hash(reference)!=private_digest:
                receipt.update(passed=False,detail='Private scenario inputs changed.')
            if receipt['passed'] and c.get('emulator'):
                # Only the instance OneCrew booted (any attempt; verified again now) is stopped; its result is its own field.
                from .delivery_device_env import kill_emulator
                try:
                    if environment.get('ownership')!='owned':cleanup='borrowed_left_running'
                    elif not pinned or verify('stop')!='owned':cleanup='replaced_not_stopped'
                    elif kill_emulator(system):owner_file.unlink(missing_ok=True);pinned.clear();cleanup='stopped'
                    else:cleanup='stop_failed'
                except EmulatorIdentityError:cleanup='identity_lost_not_stopped'
                except (ValueError,OSError):cleanup='stop_failed'
                environment['emulator_cleanup']=cleanup;environment['emulator_stopped']=cleanup=='stopped'
            durable_write(directory/'receipt.json',canonical(receipt).encode())
    receipt['detail']=receipt.get('detail','Device scenarios and cleanup passed.' if receipt['passed'] else 'Device acceptance or cleanup failed.')
    receipt['receipt_file']=str(directory/'receipt.json')
    return receipt
