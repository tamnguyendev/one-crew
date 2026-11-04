"""Local Jev credentials and bounded connectivity probe; no dispatch authority."""
import argparse
import getpass
import json
import math
import os
import re

from .decision_client_core import ENDPOINT, JevError, NoRedirect, credential_path, protect, validate_key, load_key, request_json

def store_key(value):
    encrypted=protect(validate_key(value).encode())
    path=credential_path(); path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp'); tmp.write_bytes(encrypted); os.replace(tmp,path)

def probe(key=None, opener=None):
    key=validate_key(key) if key is not None else load_key()
    payload={'model':'jev-latest','state':'Synthetic connectivity test. A task changes only the color of a button. It does not modify authentication, permissions, payments, storage or deployment.',
             'questions':{'security_change':{'type':'noul','instructions':'Does this task change authentication or permissions?'}}}
    try:
        result,latency=request_json(payload,key=key,opener=opener)
        answer=result['answers']['security_change']
        value=answer['noul']
        if answer['type']!='noul' or type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=1:
            raise ValueError()
        model=result['model']
        if not isinstance(model,str) or not re.fullmatch(r'jev-[A-Za-z0-9.-]{1,48}',model): raise ValueError()
        usage=result.get('usage',{})
        safe_usage={}
        for field in ('input_tokens','output_tokens'):
            n=usage.get(field)
            safe_usage[field]=n if type(n) is int and 0<=n<=1000000 else None
        return {'status':'connected','provider':'typesafe','model':model,'latency_ms':latency,
                'synthetic_security_probability':value,'usage':safe_usage,'mode':'connectivity_only','dispatch_enabled':False}
    except JevError: raise
    except Exception:
        # Provider error messages/bodies may echo request credentials or payloads.
        raise JevError('Provider unavailable or invalid response; details omitted.') from None

def main(argv=None):
    parser=argparse.ArgumentParser(prog='onecrew decision')
    parser.add_argument('command',choices=['configure','doctor'])
    args=parser.parse_args(argv)
    try:
        if args.command=='configure':
            store_key(getpass.getpass('TypeSafe API key (hidden): '))
            result={'status':'configured','storage':'Windows DPAPI current user','key_visible':False}
        else: result=probe()
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    except (JevError,OSError):
        # OSError can include filesystem details; never serialize a raw exception.
        print(json.dumps({'status':'unavailable','reason':'Credential or provider check failed. No automatic retry; no worker dispatched.'})); return 2

if __name__=='__main__': raise SystemExit(main())
