"""Recover missing public pub cache entries only at exact lockfile version/hash."""
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import url2pathname

from .sandbox_gate import command, task_guard, GateUnavailable
from .snapshots import safe_file


def restore(runtime,task_id,state,recipe):
    if recipe.get('restore_cache') is not True:raise GateUnavailable('Cache recovery is not authorized.')
    source=safe_file(runtime.ledger.project,recipe['package']+'/.dart_tool/package_config.json')
    config=json.loads(source.read_text(encoding='utf-8'))
    lock=safe_file(runtime.ledger.project,recipe['package']+'/pubspec.lock').read_text(encoding='utf-8')
    restored=[]
    for package in config['packages']:
        uri=urlparse(urljoin(source.as_uri(),package['rootUri']))
        if uri.scheme!='file' or uri.netloc not in ('','localhost'):raise GateUnavailable('Nonlocal dependency rejected.')
        root=Path(url2pathname(uri.path))
        present=root.is_dir() and (root/'pubspec.yaml').is_file()
        name=package['name']
        if not re.fullmatch(r'[a-zA-Z0-9_]+',name):raise GateUnavailable('Invalid dependency name.')
        block=re.search(r'^  '+re.escape(name)+r':\n(.*?)(?=^  \w+:|\Z)',lock,re.M|re.S)
        value=block.group(1) if block else ''
        version=re.search(r'^    version: "([0-9][0-9A-Za-z.+-]*)"$',value,re.M)
        digest=re.search(r'^      sha256: "?([0-9a-f]{64})"?$',value,re.M)
        recoverable=not (not version or not digest or '    source: hosted' not in value
                or not re.search(r'^      url: "?https://pub\.dev"?$',value,re.M)
                or root.name!=name+'-'+version[1] or root.parent.name!='pub.dev'
                or root.parent.parent.name!='hosted')
        if not recoverable:
            if present:continue  # Existing pinned Git/private/config-only versions stay unchanged.
            raise GateUnavailable('Missing dependency needs an explicit recovery recipe: '+name)
        cache=root.parent.parent.parent
        receipt=cache/'hosted-hashes/pub.dev'/(root.name+'.sha256')
        if present:
            if not receipt.is_file() or receipt.read_text().strip()!=digest[1]:
                raise GateUnavailable('Existing public cache hash does not match lock: '+name)
            continue
        guard=task_guard(runtime.control,task_id);guard()
        dart=Path(recipe['flutter_root'])/'bin/cache/dart-sdk/bin/dart.exe'
        code,_,_=command([str(dart),'pub','cache','add',name,'--version',version[1]],runtime.ledger.state_root/'cache-recovery-logs',90,guard,
                         {'PUB_CACHE':str(cache),'PUB_HOSTED_URL':'https://pub.dev','DART_SUPPRESS_ANALYTICS':'true'})
        if (code!=0 or not (root/'pubspec.yaml').is_file() or not receipt.is_file()
                or receipt.read_text().strip()!=digest[1]):
            raise GateUnavailable('Exact locked cache restoration failed: '+name)
        restored.append({'name':name,'version':version[1],'sha256':digest[1]})
    state['native_change'].setdefault('cache_recoveries',[]).extend(restored)
    return restored
