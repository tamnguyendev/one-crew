"""Local compiler inputs are distinct from the filtered model-readable snapshot.

Only an already authorized trusted-native Flutter recipe can use this workspace.
Omitted Dart library bytes stay local; they never enter prompts or worker blobs.
This is input separation, not an OS sandbox for trusted project tests.
"""
import json
import os
from pathlib import Path
from urllib.parse import urljoin

from .discovery import EXCLUDED
from .ledger import canonical
from .native_audit import workspace_path
from .sandbox_gate import GateUnavailable
from .snapshots import safe_file, bytes_hash, durable_write


def check_inputs(runtime, state):
    native=state['native_change']
    for name,digest in native.get('local_test_sources',{}).items():
        if bytes_hash(safe_file(runtime.ledger.project,name).read_bytes())!=digest:
            raise GateUnavailable('Local compiler-only source changed; preserve candidate and reconcile: '+name)


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
    expected=dict(expected,**omitted)
    for name,data in files.items():
        durable_write(safe_file(destination,name),data);expected[name]=bytes_hash(data)
    native['verification_workspace']=str(destination)
    native['verification_inputs']=expected
    check_inputs(runtime,state)
    return destination,{'compiler_input_manifest_sha256':bytes_hash(canonical(expected).encode()),
                        'compiler_input_count':len(expected),'local_only_source_count':len(omitted)}


def check_workspace(state):
    native=state['native_change'];directory=Path(native['verification_workspace'])
    for name,digest in native['verification_inputs'].items():
        if bytes_hash(safe_file(directory,name).read_bytes())!=digest:
            raise GateUnavailable('Compiler input changed during verification: '+name)
