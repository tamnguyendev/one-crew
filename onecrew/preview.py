"""Serve an immutable verified delivery locally; never invoke a model."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from .runtime import state_path,digest,canonical,kill_tree,save

def verified_output(project,run_id):
    root=state_path(project,run_id).parent
    state=json.loads((root/'state.json').read_text(encoding='utf-8'))
    delivery=json.loads((root/'delivery.json').read_text(encoding='utf-8'))
    if state['status']!='ready_for_review' or state['verification']!='passed':raise ValueError('Only verified deliveries can be previewed.')
    output=Path(state['output']).resolve();manifest=delivery['manifest']
    if digest(canonical(manifest))!=state['output_revision']:raise ValueError('Delivery revision mismatch.')
    for name,expected in manifest.items():
        path=(output/name).resolve()
        if not path.is_relative_to(output) or digest(path.read_bytes())!=expected:raise ValueError('Delivered source was changed; reverify before preview.')
    return root,output

def main(argv=None):
    parser=argparse.ArgumentParser(prog='onecrew task preview')
    parser.add_argument('--project',type=Path,default=Path.cwd());parser.add_argument('id')
    parser.add_argument('--port',type=int,default=3201);parser.add_argument('--demo',action='store_true',required=True)
    args=parser.parse_args(argv)
    try:
        if os.name!='nt':raise ValueError('Local preview adapter currently requires Windows.')
        if not 1024<=args.port<=65535:raise ValueError('Port must be 1024–65535.')
        root,output=verified_output(args.project.resolve(),args.id)
        data=output/'.data-preview';data.mkdir(exist_ok=True)
        codex,node=shutil.which('codex'),shutil.which('node')
        if not codex or not node:raise ValueError('Codex and Node required.')
        origin=f'http://127.0.0.1:{args.port}'
        env={k:v for k,v in os.environ.items() if not any(x in k.upper() for x in ('TOKEN','SECRET','PASSWORD','API_KEY','NODE_OPTIONS'))}
        env.update(PORT=str(args.port),HOST='127.0.0.1',APP_ORIGIN=origin,DATA_DIR=str(data),CV_GUARD_MODE='demo')
        command=[codex,'--no-daemon','sandbox','-P',':workspace','-C',str(output),node,'--permission',f'--allow-fs-read={output}',f'--allow-fs-write={data}','server.mjs']
        with (root/'preview.stdout').open('wb') as out,(root/'preview.stderr').open('wb') as err:
            child=subprocess.Popen(command,cwd=output,env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=err,creationflags=subprocess.CREATE_NEW_PROCESS_GROUP|subprocess.CREATE_NO_WINDOW)
            try:
                save(root/'preview.json',{'pid':child.pid,'url':origin,'mode':'demo','run':args.id})
                print(json.dumps({'url':origin,'mode':'demo','run':args.id,'pid':child.pid}),flush=True)
                while child.poll() is None:time.sleep(.5)
                return child.returncode
            finally:kill_tree(child)
    except KeyboardInterrupt:return 0
    except (ValueError,OSError,KeyError) as error:
        print('Cannot preview: '+str(error));return 2

if __name__=='__main__':raise SystemExit(main())
