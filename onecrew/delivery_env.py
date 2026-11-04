"""Deterministic read-only discovery of the Flutter/Android toolchain and project packages (delivery autopilot §2).

Only file reads: no network, device or build. The one subprocess is the optional bounded keytool call for the
public debug certificate. Missing tools are reported in ``problems``; nothing here raises for an absent toolchain.
"""
import hashlib
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import subprocess
import xml.etree.ElementTree as ET

from .ledger import LedgerError, content_hash


EXE='.exe' if os.name=='nt' else ''
SKIP={'build','.dart_tool'}
ANDROID='{http://schemas.android.com/apk/res/android}'
ESCAPES={'t':'\t','n':'\n','r':'\r','f':'\f'}
DIRECTIVE=re.compile(r'(?m)^[ \t]*(?:import|export|part(?![ \t]+of\b))\s+([^;]*);')
FLUTTER_DEP=re.compile(r'(?m)^[ \t]+flutter:[ \t]*(?:\{[ \t]*|\n[ \t]+)sdk:[ \t]*["\']?flutter\b')
BUILD_TOOLS=('lib/apksigner.jar','aapt2'+EXE,'zipalign'+EXE)
FLUTTER_PACKAGES='packages/flutter_tools/.dart_tool/package_config.json'
VARIANTS=('debug','release')


def _environ(env):
    env=os.environ if env is None else env
    return {k.upper():v for k,v in env.items()} if os.name=='nt' else dict(env)


def _home(env): return Path(env.get('USERPROFILE' if os.name=='nt' else 'HOME') or Path.home())


def _text(path):
    try: return Path(path).read_text(encoding='utf-8-sig',errors='replace')
    except OSError: return None


def _file_hash(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): digest.update(block)
    return digest.hexdigest()


def _problem(code,detail): return {'code':code,'detail':detail}


def which(name,env):
    """PATH lookup from ``env`` only; unlike shutil.which it never searches the current or a relative directory."""
    exts=[e for e in env.get('PATHEXT','.COM;.EXE;.BAT;.CMD').lower().split(';') if e] if os.name=='nt' else ['']
    for entry in env.get('PATH','').split(os.pathsep):
        entry=entry.strip().strip('"')
        if not entry or not os.path.isabs(entry): continue
        for ext in exts:
            path=Path(entry)/(name+ext)
            if path.is_file() and (os.name=='nt' or os.access(path,os.X_OK)): return path
    return None


def unescape(value):
    """Java .properties escapes: \\uXXXX, \\t \\n \\r \\f, otherwise the escaped character itself (\\\\, \\:, \\=)."""
    return re.sub(r'\\(u[0-9a-fA-F]{4}|.)',lambda m:chr(int(m[1][1:],16)) if len(m[1])==5 else ESCAPES.get(m[1],m[1]),value,flags=re.S)


def _pair(line):
    m=re.match(r'((?:\\.|[^\\=:\s])*)\s*(?:[=:]\s*)?(.*)',line,re.S)
    return unescape(m[1]),unescape(m[2])


def properties(path):
    """Read a .properties file as Gradle does for local.properties (continuations, separators, escapes); {} when unreadable."""
    values={};logical=None
    for raw in (_text(path) or '').splitlines():
        line=raw.lstrip()
        if logical is None:
            if not line or line[0] in '#!': continue
            logical=''
        logical+=line
        if (len(line)-len(line.rstrip('\\')))%2: logical=logical[:-1];continue
        key,value=_pair(logical);values[key]=value;logical=None
    if logical is not None: key,value=_pair(logical);values[key]=value
    return values


def flutter_tools(root):
    """dart and flutter_tools.snapshot exactly as delivery_steps.dart_argv runs them."""
    root=Path(root);return root/'bin/cache/dart-sdk/bin'/('dart'+EXE),root/'bin/cache/flutter_tools.snapshot'


def _flutter_gap(root):
    # dart_argv also passes the flutter_tools package config (--packages), so it is part of a usable root.
    missing=[p.relative_to(root).as_posix() for p in (*flutter_tools(root),root/FLUTTER_PACKAGES) if not p.is_file()]
    return 'missing '+', '.join(missing) if missing else None


def _sdk_gap(root):
    if not root.is_dir(): return 'not a directory'
    return None if (root/'platform-tools').is_dir() or (root/'build-tools').is_dir() else 'no platform-tools or build-tools'


def _first(candidates,gap):
    """(absolute path, source, rejections) of the first candidate without a gap."""
    rejected=[]
    for source,path in candidates:
        if not path: continue
        reason=gap(Path(path))
        if reason is None: return os.path.abspath(path),source,rejected
        rejected.append(f'{source}={path} ({reason})')
    return None,None,rejected


def _tried(rejected,sources): return '; tried '+'; '.join(rejected) if rejected else '; none of '+sources+' is set'


def build_tools(sdk):
    """Highest complete build-tools dir (lib/apksigner.jar, aapt2, zipalign): (path, version, incomplete notes)."""
    complete=[];incomplete=[]
    try: dirs=[d for d in (Path(sdk)/'build-tools').iterdir() if d.is_dir()]
    except OSError: dirs=[]
    for d in dirs:
        m=re.match(r'(\d+)(?:\.(\d+))?(?:\.(\d+))?',d.name)
        if not m: continue
        missing=[n for n in BUILD_TOOLS if not (d/n).is_file()]
        if missing: incomplete.append(d.name+' (missing '+', '.join(missing)+')');continue
        # A stable release outranks its preview (36.0.0 > 36.0.0-rc1); the name breaks any remaining tie.
        complete.append(((tuple(int(g or 0) for g in m.groups()),m.end()==len(d.name),d.name),d))
    if not complete: return None,None,sorted(incomplete)
    (_,_,name),d=max(complete);return os.path.abspath(d),name,sorted(incomplete)


def zipalign_16kb(version):
    """Whether build-tools ``version`` has ``zipalign -P 16``: 35.0.0-rc3 and later."""
    m=re.match(r'(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:-rc(\d+))?',version or '')
    if not m: return False
    v=tuple(int(g or 0) for g in m.groups()[:3])
    return v>(35,0,0) or v==(35,0,0) and (m[4] is None or int(m[4])>=3)


def _java_home(java):
    for path in (java,java.resolve()):
        home=path.parent.parent
        if path.parent.name.lower()=='bin' and ((home/'release').is_file() or (home/'lib').is_dir()): return os.path.abspath(home)
    return None


def _studio_jbr(env,home):
    if os.name=='nt': return [Path(env.get('PROGRAMFILES') or r'C:\Program Files')/'Android/Android Studio/jbr']
    return [Path('/opt/android-studio/jbr'),home/'android-studio/jbr',Path('/Applications/Android Studio.app/Contents/jbr/Contents/Home')]


def _scalar(text,key):
    m=re.search(r'(?m)^'+key+r':[ \t]*([^#\n]*)',text)
    value=m[1].strip() if m else ''
    return (value[1:-1] if len(value)>1 and value[0]==value[-1] and value[0] in '"\'' else value) or None


def _block(text,key):
    """Indented body of a top-level YAML key."""
    lines=text.splitlines()
    for i,line in enumerate(lines):
        if re.match(key+r':[ \t]*(#.*)?$',line):
            body=[]
            for item in lines[i+1:]:
                if item.strip() and not item[0].isspace() and not item.startswith('#'): break
                body.append(item)
            return '\n'.join(body)
    return ''


def _closure(text,head):
    """Brace-balanced body of the first ``head { ... }`` in Gradle text, or None."""
    m=re.search(r'(?<![\w.])(?:'+head+r')\s*\{',text or '')
    if not m: return None
    depth=0
    for i in range(m.end()-1,len(text)):
        depth+={'{':1,'}':-1}.get(text[i],0)
        if not depth: return text[m.end():i]
    return text[m.end():]


def _assigned(body,key):
    """String literal assigned to ``key`` in a Gradle block: '' when unassigned, None when set to an expression."""
    m=re.search(r'(?<!\w)'+key+r'\b\s*[=(]?\s*(?:(["\'])([A-Za-z0-9_.]*)\1)?',body or '')
    return '' if not m else m[2] if m[1] else None


def _gradle(app,manifest_package):
    """(applicationId, namespace, {variant: effective package}) from android/app/build.gradle(.kts).

    applicationId is the defaultConfig literal, else the namespace (Gradle ``namespace``, else the manifest package).
    The effective package of ``flutter build apk --<variant>`` adds the defaultConfig and buildType applicationIdSuffix
    as AGP does; it is None when any part is not a literal.
    """
    text=next((t for t in (_text(app/n) for n in ('build.gradle','build.gradle.kts')) if t is not None),None)
    if text is None: return None,manifest_package,dict.fromkeys(VARIANTS)
    text=re.sub(r'(?m)^[ \t]*//.*$','',re.sub(r'(?s)/\*.*?\*/','',text))
    config=_closure(text,'defaultConfig');types=_closure(text,'buildTypes')
    namespace=_assigned(text,'namespace');namespace=namespace or (manifest_package if namespace=='' else None)
    # Flavors may declare their own applicationId, so only defaultConfig's counts when that block exists.
    declared=_assigned(text if config is None else config,'applicationId')
    base=declared or (namespace if declared=='' else None);ids={}
    for variant in VARIANTS:
        block=_closure(types,variant+r'|(?:getByName|named|maybeCreate|create)\(\s*["\']'+variant+r'["\']\s*\)')
        parts=[base,_assigned(config,'applicationIdSuffix'),_assigned(block,'applicationIdSuffix')]
        ids[variant]=None if None in parts else parts[0]+''.join(s if s[0]=='.' else '.'+s for s in parts[1:] if s)
    return declared or namespace,namespace,ids


def _manifest(manifest):
    """(package attribute, first enabled MAIN/LAUNCHER activity or alias name as written)."""
    root=ET.parse(manifest).getroot()
    for e in root.iter():
        if e.tag not in ('activity','activity-alias') or e.get(ANDROID+'enabled')=='false': continue
        for f in e.findall('intent-filter'):
            if ('android.intent.action.MAIN' in {a.get(ANDROID+'name') for a in f.findall('action')}
                    and 'android.intent.category.LAUNCHER' in {c.get(ANDROID+'name') for c in f.findall('category')}):
                return root.get('package') or None,e.get(ANDROID+'name')
    return root.get('package') or None,None


def qualify(name,namespace):
    """Manifest class name resolved against the namespace, as `am start -n <package>/<class>` needs when package != namespace."""
    if not name or name[0]!='.' and '.' in name: return name or None
    return (namespace+('' if name[0]=='.' else '.')+name) if namespace else None


def _tests(package):
    root=Path(package)/'test'
    if not root.is_dir(): return []
    return sorted(r for r in (p.relative_to(package).as_posix() for p in root.rglob('*_test.dart') if p.is_file())
                  if not SKIP.intersection(r.split('/')))


def _pubspec_dirs(base,depth):
    if (base/'pubspec.yaml').is_file(): yield base
    if not depth: return
    try: children=sorted(c for c in base.iterdir() if c.is_dir() and c.name not in SKIP and not c.name.startswith('.'))
    except OSError: return
    for child in children: yield from _pubspec_dirs(child,depth-1)


def package(root,path,problems):
    """Planner facts for the pubspec package at ``path`` (``root`` is its posix path relative to the project)."""
    text=_text(path/'pubspec.yaml') or '';version_name,_,code=(_scalar(text,'version') or '').partition('+')
    app=path/'android/app';manifest=app/'src/main/AndroidManifest.xml';manifest_package=activity=None
    if manifest.is_file():
        try: manifest_package,activity=_manifest(manifest)
        except (OSError,ET.ParseError) as error: problems.append(_problem('manifest_unreadable:'+root,f'{root}/android/app/src/main/AndroidManifest.xml: {error}'))
    application_id,namespace,application_ids=_gradle(app,manifest_package)
    return {'root':root,'name':_scalar(text,'name'),'flutter':bool(re.search(r'(?m)^flutter:',text) or FLUTTER_DEP.search(_block(text,'dependencies'))),
            'dependency_ready':(path/'.dart_tool/package_config.json').is_file(),'application_id':application_id,'namespace':namespace,
            'application_ids':application_ids,'version_name':version_name or None,'version_code':code if code.isascii() and code.isdigit() else None,
            'launch_activity':activity,'launch_activity_class':qualify(activity,namespace),'tests':_tests(path)}


def discover(project,roots,env=None):
    """Toolchain and package facts for source ``roots`` under ``project``. Absent tools become ``problems``, never errors."""
    project=Path(project)
    if not project.is_dir(): raise LedgerError('Project directory unavailable: '+str(project))
    if not isinstance(roots,(list,tuple)): raise LedgerError('Source roots must be a list of project-relative paths.')
    env=_environ(env);home=_home(env)
    problems=[];found={}
    for root in roots:
        rel=PurePosixPath(str(root).replace('\\','/'))
        if not isinstance(root,str) or not root.strip() or rel.is_absolute() or '..' in rel.parts or re.match(r'[A-Za-z]:',root):
            raise LedgerError('Source root must be a project-relative path: '+str(root))
        if not (project/rel).is_dir(): problems.append(_problem('root_missing:'+rel.as_posix(),'Source root is not a directory: '+rel.as_posix()));continue
        for path in _pubspec_dirs(project/rel,2): found.setdefault(path.relative_to(project).as_posix(),path)
    packages=[package(rel,path,problems) for rel,path in sorted(found.items())]
    local=[(p['root'],found[p['root']]/'android') for p in packages]
    local=[(r,a,properties(a/'local.properties')) for r,a in local if (a/'local.properties').is_file()]
    info={'version':1}

    flutter=[('FLUTTER_ROOT',env.get('FLUTTER_ROOT'))]+[('local.properties:'+r,a/v['flutter.sdk'] if v.get('flutter.sdk') else None) for r,a,v in local]
    launcher=which('flutter',env)
    flutter+=[('PATH',p.parent.parent) for p in dict.fromkeys((launcher,launcher.resolve()) if launcher else ()) if p.parent.name.lower()=='bin']
    info['flutter_root'],info['flutter_source'],rejected=_first(flutter,_flutter_gap)
    if not info['flutter_root']:
        problems.append(_problem('flutter_root_missing',f'No Flutter SDK with bin/cache/dart-sdk/bin/dart{EXE}, bin/cache/flutter_tools.snapshot and '
                                 +FLUTTER_PACKAGES+_tried(rejected,'FLUTTER_ROOT, local.properties flutter.sdk, flutter on PATH')))

    default=Path(env['LOCALAPPDATA'])/'Android/Sdk' if os.name=='nt' and env.get('LOCALAPPDATA') else home/'Android/Sdk'
    sdks=([('ANDROID_HOME',env.get('ANDROID_HOME')),('ANDROID_SDK_ROOT',env.get('ANDROID_SDK_ROOT'))]
          +[('local.properties:'+r,a/v['sdk.dir'] if v.get('sdk.dir') else None) for r,a,v in local]+[('default',default)])
    sdk,source,rejected=_first(sdks,_sdk_gap);info.update(android_sdk=sdk,android_sdk_source=source)
    if not sdk: problems.append(_problem('android_sdk_missing','No Android SDK with platform-tools or build-tools'+_tried(rejected,'Android SDK locations')))
    tools,version,incomplete=build_tools(sdk) if sdk else (None,None,[])
    info.update(build_tools=tools,build_tools_version=version,zipalign_16kb=zipalign_16kb(version))
    if not tools:
        problems.append(_problem('build_tools_missing',('No build-tools under '+sdk+' with '+', '.join(BUILD_TOOLS)
                                 +('; incomplete: '+'; '.join(incomplete) if incomplete else '')) if sdk else 'Android SDK unavailable'))
    adb=Path(sdk)/'platform-tools'/('adb'+EXE) if sdk else None
    info['adb']=os.path.abspath(adb) if adb and adb.is_file() else None
    if not info['adb']: problems.append(_problem('adb_missing',str(adb)+' is missing' if sdk else 'Android SDK unavailable'))

    java_home=env.get('JAVA_HOME');path_java=which('java',env)
    javas=([('JAVA_HOME',Path(java_home)/'bin'/('java'+EXE) if java_home else None),('PATH',path_java)]
           +[('android_studio',j/'bin'/('java'+EXE)) for j in _studio_jbr(env,home)])
    java,source,rejected=_first(javas,lambda p:None if p.is_file() else 'missing')
    info.update(java=java,java_source=source,java_home=(os.path.abspath(java_home) if source=='JAVA_HOME' else _java_home(Path(java))) if java else None)
    # apk_audit and preflight run shutil.which('java'), which may be another JDK than the one chosen above (or none).
    info['java_on_path']=os.path.abspath(path_java) if path_java else None
    if not java: problems.append(_problem('java_missing','No java'+EXE+_tried(rejected,'JAVA_HOME, java on PATH, Android Studio jbr')))

    info['packages']=packages
    if not packages: problems.append(_problem('package_missing','No pubspec.yaml within depth 2 of source roots: '+', '.join(map(str,roots))))
    problems+=[_problem('dependency_graph_missing:'+p['root'],'Prepared dependency graph missing: '+p['root']+'/.dart_tool/package_config.json')
               for p in packages if not p['dependency_ready']]
    info['problems']=problems
    return info


def tests_for(package_dir,lib_paths):
    """Existing test/**/*_test.dart of a package, ranked: importing a given lib file directly, then transitively, then the rest.

    ``lib_paths`` are package-relative ('lib/src/a.dart') or absolute paths inside the package; others are ignored.
    """
    package=Path(package_dir);name=_scalar(_text(package/'pubspec.yaml') or '','name');targets=set();memo={}
    for item in lib_paths:
        path=Path(item)
        if path.is_absolute():
            try: path=path.relative_to(package)
            except ValueError: continue
        rel=posixpath.normpath(path.as_posix())
        if rel.startswith('lib/'): targets.add(rel)

    def imports(rel):
        if rel not in memo:
            found=set()
            for clause in DIRECTIVE.findall(_text(package/rel) or ''):
                for uri in re.findall(r'''['"]([^'"]+)['"]''',clause):
                    if name and uri.startswith('package:'+name+'/'): found.add(posixpath.normpath('lib/'+uri[len(name)+9:]))
                    elif ':' not in uri: found.add(posixpath.normpath(posixpath.join(posixpath.dirname(rel),uri)))
            memo[rel]={r for r in found if not r.startswith(('../','/')) and r!='..'}
        return memo[rel]

    def reaches(rel):
        seen=set();todo=list(imports(rel))
        while todo:
            item=todo.pop()
            if item in seen: continue
            if item in targets: return True
            seen.add(item);todo.extend(imports(item))
        return False

    return sorted(_tests(package),key=lambda t:(0 if imports(t)&targets else 1 if reaches(t) else 2,t))


def signer_sha256(text):
    """Certificate SHA-256 from ``keytool -list -v`` output, lowercase hex without colons."""
    m=re.search(r'SHA-?256:\s*((?:[0-9A-Fa-f]{2}:){31}[0-9A-Fa-f]{2})\b',text or '')
    return m[1].replace(':','').lower() if m else None


def debug_keystore(env=None):
    """The debug keystore AGP signs with: $ANDROID_USER_HOME, else $ANDROID_PREFS_ROOT or $ANDROID_SDK_HOME + /.android, else ~/.android."""
    env=_environ(env)
    if env.get('ANDROID_USER_HOME'): return Path(env['ANDROID_USER_HOME'])/'debug.keystore'
    root=env.get('ANDROID_PREFS_ROOT') or env.get('ANDROID_SDK_HOME')
    return (Path(root) if root else _home(env))/'.android/debug.keystore'


def debug_signer_sha256(java_home=None,keystore=None):
    """SHA-256 of the Android *debug* keystore certificate, or None when keytool/keystore is unavailable. Never for release keys."""
    keystore=Path(keystore) if keystore else debug_keystore()
    keytool=Path(java_home)/'bin'/('keytool'+EXE) if java_home else which('keytool',_environ(None))
    if not keystore.is_file() or not keytool or not Path(keytool).is_file(): return None
    # 'android' is the publicly documented debug store password, not a secret; -J pins English labels.
    argv=[str(keytool),'-J-Duser.language=en','-list','-v','-keystore',str(keystore),'-alias','androiddebugkey','-storepass','android']
    try:
        done=subprocess.run(argv,stdin=subprocess.DEVNULL,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=20,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    except (OSError,subprocess.SubprocessError): return None
    return signer_sha256(done.stdout) if done.returncode==0 else None


def tool_paths(info):
    """Tool files the delivery steps execute, by role; only those present."""
    paths={}
    if info.get('flutter_root'): paths['dart'],paths['flutter_tools.snapshot']=flutter_tools(info['flutter_root'])
    if info.get('build_tools'): paths.update(zip(('apksigner.jar','aapt2','zipalign'),(Path(info['build_tools'])/n for n in BUILD_TOOLS)))
    for key in ('adb','java','java_on_path'):
        if info.get(key): paths[key]=Path(info[key])
    return {k:p for k,p in paths.items() if p.is_file()}


def fingerprint(info):
    """Content hash of the discovered tool paths and file hashes; changes when any executed tool changes."""
    tools={}
    for role,path in sorted(tool_paths(info).items()):
        try: tools[role]={'path':str(path.resolve()),'sha256':_file_hash(path)}
        except OSError: continue
    return content_hash(tools)
