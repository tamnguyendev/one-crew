"""Local compiler inputs are distinct from the filtered model-readable snapshot.

Only an already authorized trusted-native Flutter recipe can use this workspace.
Omitted Dart library bytes stay local; they never enter prompts or worker blobs.
This is input separation, not an OS sandbox for trusted project tests.
"""
import json
import os
import re
from pathlib import Path
from urllib.parse import urljoin

from .discovery import EXCLUDED, permitted
from .ledger import canonical
from .native_audit import workspace_path
from .sandbox_gate import GateUnavailable
from .snapshots import safe_file, bytes_hash, durable_write


MAX_ASSET_FILES=500
MAX_ASSET_BYTES=20_000_000


def check_inputs(runtime, state):
    native=state['native_change']
    for name,digest in native.get('local_test_sources',{}).items():
        if bytes_hash(safe_file(runtime.ledger.project,name).read_bytes())!=digest:
            raise GateUnavailable('Local compiler-only source changed; preserve candidate and reconcile: '+name)
    for name,digest in native.get('local_test_assets',{}).items():
        if bytes_hash(safe_file(runtime.ledger.project,name).read_bytes())!=digest:
            raise GateUnavailable('Local test asset changed; preserve candidate and reconcile: '+name)


def pubspec_assets(text):
    """Asset and font paths a pubspec declares under its top-level `flutter:` key (minimal reader, no YAML library):
    `assets:` list items and `asset:` entries of font families. Paths are relative to the package directory."""
    found=[];inside=False;mode=None;key_indent=0;item_indent=None
    for raw in text.splitlines():
        line=raw.split(' #')[0].rstrip();body=line.strip()
        if not body or body.startswith('#'):continue
        indent=len(line)-len(line.lstrip(' '))
        if indent==0 and not body.startswith('-'):
            inside=body=='flutter:';mode=None;continue
        if not inside:continue
        if body=='assets:':
            mode='assets';key_indent=indent;item_indent=None;continue
        item=re.match(r'^(?:-\s*)?asset:\s*(.+)$',body)
        if item:
            found.append(item.group(1).strip().strip('\'"'));continue
        if mode=='assets' and body.startswith('-') and indent>=key_indent:
            if item_indent is None:item_indent=indent
            if indent!=item_indent:continue  # nested list (e.g. a transformer's own entries), not an asset
            value=body[1:].strip()
            if value.startswith('path:'):value=value[5:].strip()  # asset with transformers: `- path: x`
            found.append(value.strip('\'"'));continue
        if mode and not body.startswith('-') and indent<=key_indent:mode=None
    return found


def declared_assets(runtime,recipe,taken):
    """Bytes of the package's declared assets/fonts, read from the project (never via capture/discovery, so they stay out
    of prompts and worker blobs). A directory entry means its direct files. Capped at 500 files / 20 MB."""
    project=runtime.ledger.project;package=recipe['package']
    pubspec=safe_file(project,package+'/pubspec.yaml')
    if not pubspec.is_file():return {}
    assets={};total=0
    for declared in pubspec_assets(pubspec.read_text(encoding='utf-8-sig')):
        relative=declared.replace('\\','/')
        if not relative or relative.startswith('/') or ':' in relative or '..' in relative.split('/'):
            raise GateUnavailable('Unsupported asset path in pubspec: '+declared[:120])
        if not permitted(package+'/'+relative.rstrip('/')):continue  # private/control names never cross
        target=safe_file(project,package+'/'+relative.rstrip('/'))
        if target.is_dir():
            names=sorted(leaf.name for leaf in target.iterdir() if leaf.is_file() and not leaf.is_symlink())
            names=[package+'/'+relative.rstrip('/')+'/'+leaf for leaf in names]
        elif target.is_file():names=[package+'/'+relative]
        else:continue
        for name in names:
            if name in assets or name in taken or not permitted(name):continue
            data=safe_file(project,name).read_bytes();total+=len(data)
            if len(assets)>=MAX_ASSET_FILES:raise GateUnavailable('Test assets exceed the limit of 500 files.')
            if total>MAX_ASSET_BYTES:raise GateUnavailable('Test assets exceed the limit of 20 MB.')
            assets[name]=bytes_hash(data)
    return assets


def prepare(runtime,state,recipe):
    if recipe.get('trusted_native') is not True:
        raise GateUnavailable('Full compiler inputs require authorized trusted native execution.')
    native=state['native_change'];worker=Path(native['workspace'])
    manifest=json.loads(runtime.store.read_evidence(native['manifest']))['files']
    expected=dict(manifest,**state['files'])
    omitted={};total=0;visited=0
    for root in recipe['source_roots']:
        library=safe_file(runtime.ledger.project,root+'/lib')
        for directory,dirs,files in os.walk(library,followlinks=False):
            base=Path(directory)
            dirs[:]=sorted(d for d in dirs if d.lower() not in EXCLUDED and not d.lower().startswith('.env')
                          and not (base/d).is_symlink() and not (hasattr(base/d,'is_junction') and (base/d).is_junction()))
            visited+=len(dirs)+len(files)
            if visited>100000: raise GateUnavailable('Local compiler input enumeration exceeds limit.')
            for leaf in sorted(files):
                if not leaf.endswith('.dart'):continue
                name=(base/leaf).relative_to(runtime.ledger.project).as_posix()
                if name in expected:continue
                source=safe_file(runtime.ledger.project,name)
                if source.stat().st_size>2_000_000:raise GateUnavailable('Local Dart compiler input exceeds file limit.')
                data=source.read_bytes();total+=len(data)
                if len(omitted)>=20000 or total>128_000_000:raise GateUnavailable('Local compiler inputs exceed size limit.')
                omitted[name]=bytes_hash(data)
    if 'local_test_sources' in native and native['local_test_sources']!=omitted:
        raise GateUnavailable('Local compiler input set changed; preserve prior verification evidence.')
    native['local_test_sources']=omitted
    assets=declared_assets(runtime,recipe,set(expected)|set(omitted))
    if 'local_test_assets' in native and native['local_test_assets']!=assets:
        raise GateUnavailable('Local test asset set changed; preserve prior verification evidence.')
    native['local_test_assets']=assets
    destination=workspace_path(runtime.ledger.state_root,'native-test')
    destination.mkdir(parents=True,exist_ok=False)
    for name,digest in expected.items():
        data=safe_file(worker,name).read_bytes()
        if bytes_hash(data)!=digest:raise GateUnavailable('Worker input changed while staging compiler inputs: '+name)
        durable_write(safe_file(destination,name),data)
    for name,digest in omitted.items():
        data=safe_file(runtime.ledger.project,name).read_bytes()
        if bytes_hash(data)!=digest:raise GateUnavailable('Local input changed while staging compiler inputs: '+name)
        durable_write(safe_file(destination,name),data)
    for name,digest in assets.items():
        data=safe_file(runtime.ledger.project,name).read_bytes()
        if bytes_hash(data)!=digest:raise GateUnavailable('Test asset changed while staging compiler inputs: '+name)
        durable_write(safe_file(destination,name),data)
    config_path=safe_file(worker,recipe['package']+'/.dart_tool/package_config.json')
    config=json.loads(config_path.read_text(encoding='utf-8'))
    for package in config['packages']:
        absolute=urljoin(config_path.as_uri(),package['rootUri'])
        package['rootUri']=absolute
        for root in recipe['source_roots']:
            if absolute.rstrip('/')==(worker/root).resolve().as_uri().rstrip('/'):
                package['rootUri']=(destination/root).resolve().as_uri()+'/'
    files={recipe['package']+'/.dart_tool/package_config.json':canonical(config).encode(),
           recipe['package']+'/.dart_tool/package_graph.json':
               safe_file(worker,recipe['package']+'/.dart_tool/package_graph.json').read_bytes()}
    expected=dict(expected,**omitted,**assets)
    for name,data in files.items():
        durable_write(safe_file(destination,name),data);expected[name]=bytes_hash(data)
    native['verification_workspace']=str(destination)
    native['verification_inputs']=expected
    check_inputs(runtime,state)
    return destination,{'compiler_input_manifest_sha256':bytes_hash(canonical(expected).encode()),
                        'compiler_input_count':len(expected),'local_only_source_count':len(omitted),
                        'local_only_asset_count':len(assets)}


def check_workspace(state):
    native=state['native_change'];directory=Path(native['verification_workspace'])
    for name,digest in native['verification_inputs'].items():
        if bytes_hash(safe_file(directory,name).read_bytes())!=digest:
            raise GateUnavailable('Compiler input changed during verification: '+name)
