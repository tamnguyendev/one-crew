"""Local Jev credentials and bounded connectivity probe; no dispatch authority."""
import argparse
import ctypes
from ctypes import wintypes
import getpass
import json
import math
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

ENDPOINT = 'https://api.typesafe.ai/v1/systemone'

class JevError(Exception):
    """Only fixed, credential-free messages cross the CLI boundary."""

def credential_path():
    if os.name != 'nt' or not os.environ.get('LOCALAPPDATA'):
        raise JevError('Use TYPESAFE_API_KEY on this platform.')
    return Path(os.environ['LOCALAPPDATA'])/'OneCrew'/'credentials'/'jev.dpapi'

def protect(data, decrypt=False):
    if os.name != 'nt': raise JevError('Windows credential protection unavailable.')
    class Blob(ctypes.Structure):
        _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]
    buffer=(ctypes.c_ubyte*len(data)).from_buffer_copy(data)
    source=Blob(len(data),buffer); target=Blob()
    crypt=ctypes.WinDLL('crypt32',use_last_error=True)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    fn=crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    fn.restype=wintypes.BOOL
    kernel.LocalFree.argtypes=[ctypes.c_void_p]; kernel.LocalFree.restype=ctypes.c_void_p
    if not fn(ctypes.byref(source),None,None,None,None,1,ctypes.byref(target)):
        raise JevError('Windows credential protection failed.')
    try: return ctypes.string_at(target.data,target.size)
    finally: kernel.LocalFree(target.data)

def validate_key(value):
    if not isinstance(value,str) or not 20<=len(value)<=512 or not re.fullmatch(r'[A-Za-z0-9_-]+',value):
        raise JevError('Invalid credential format.')
    return value

def store_key(value):
    encrypted=protect(validate_key(value).encode())
    path=credential_path(); path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp'); tmp.write_bytes(encrypted); os.replace(tmp,path)

def load_key():
    env=os.environ.get('TYPESAFE_API_KEY')
    if env: return validate_key(env)
    try: return validate_key(protect(credential_path().read_bytes(),decrypt=True).decode())
    except (OSError,UnicodeError): raise JevError('Credential missing or unreadable.') from None

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise JevError('Provider redirect refused.')

def probe(key=None, opener=None):
    key=validate_key(key) if key is not None else load_key()
    payload={'model':'jev-latest','state':'Synthetic connectivity test. A task changes only the color of a button. It does not modify authentication, permissions, payments, storage or deployment.',
             'questions':{'security_change':{'type':'noul','instructions':'Does this task change authentication or permissions?'}}}
    req=urllib.request.Request(ENDPOINT,data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
    started=time.monotonic()
    try:
        client=opener or urllib.request.build_opener(NoRedirect())
        with client.open(req,timeout=15) as response:
            raw=response.read(65537)
        if len(raw)>65536: raise JevError('Provider response exceeded limit.')
        result=json.loads(raw)
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
        return {'status':'connected','provider':'typesafe','model':model,'latency_ms':round((time.monotonic()-started)*1000),
                'synthetic_security_probability':value,'usage':safe_usage,'mode':'connectivity_only','dispatch_enabled':False}
    except urllib.error.HTTPError as error:
        raise JevError(f'Provider HTTP {error.code}; response body omitted.') from None
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
