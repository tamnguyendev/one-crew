"""Shared bounded Jev transport extracted from v1; no workflow or dispatch authority.

v1 configure/probe and model selection, and the optional v2 advice adapter use
this same credential reader, no-redirect transport and choice validator. The
caller owns authorization, budget reservation and durable invocation identity.
"""
import ctypes
from ctypes import wintypes
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
    """Fixed credential-free error; calls counts attempted HTTP requests only."""
    def __init__(self, message, calls=0):
        super().__init__(message)
        self.calls = calls


def credential_path():
    if os.name != 'nt' or not os.environ.get('LOCALAPPDATA'):
        raise JevError('Use TYPESAFE_API_KEY on this platform.')
    return Path(os.environ['LOCALAPPDATA']) / 'OneCrew' / 'credentials' / 'jev.dpapi'


def protect(data, decrypt=False):
    if os.name != 'nt':
        raise JevError('Windows credential protection unavailable.')
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source, target = Blob(len(data), buffer), Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                   wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise JevError('Windows credential protection failed.')
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)


def validate_key(value):
    if not isinstance(value, str) or not 20 <= len(value) <= 512 or not re.fullmatch(r'[A-Za-z0-9_-]+', value):
        raise JevError('Invalid credential format.')
    return value


def configured(key=None):
    """Is a credential present, without reading, decrypting or validating a stored one (no secret is touched, no network)."""
    if key is not None:
        try:
            validate_key(key)
        except JevError:
            return False
        return True
    if os.environ.get('TYPESAFE_API_KEY'):
        return True
    try:
        return credential_path().is_file()
    except (JevError, OSError):
        return False


def load_key():
    env = os.environ.get('TYPESAFE_API_KEY')
    if env:
        return validate_key(env)
    try:
        return validate_key(protect(credential_path().read_bytes(), decrypt=True).decode())
    except (OSError, UnicodeError):
        raise JevError('Credential missing or unreadable.') from None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise JevError('Provider redirect refused.')


def request_json(payload, *, key=None, opener=None):
    """At most one bounded HTTP request; credential/key are never payload fields."""
    try:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (ValueError, TypeError):
        raise JevError('Invalid evaluator request.') from None
    if len(body) > 16000:
        raise JevError('Evaluator context exceeded limit.')
    key = validate_key(key) if key is not None else load_key()
    request = urllib.request.Request(ENDPOINT, data=body,
        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, method='POST')
    started = time.monotonic()
    try:
        client = opener if opener is not None else urllib.request.build_opener(NoRedirect())
        with client.open(request, timeout=15) as response:
            raw = response.read(65537)
        if len(raw) > 65536 or key.encode('utf-8') in raw:
            raise ValueError()
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError()
        return result, round((time.monotonic() - started) * 1000)
    except urllib.error.HTTPError as error:
        raise JevError('Evaluator HTTP ' + str(error.code) + '; details omitted.', calls=1) from None
    except Exception:
        # Includes redirect refusal and response bodies that might echo credentials.
        raise JevError('Evaluator unavailable or invalid response; details omitted. No retry.', calls=1) from None


def parse_choice(result, question, choices):
    """Validate the v1 choice shape, retaining only bounded metadata."""
    def probability(value):
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError()
        return value
    try:
        answer = result['answers'][question]
        if answer['type'] != 'choice' or answer['choice'] not in choices:
            raise ValueError()
        confidence = probability(answer['confidence'])
        probabilities = answer['probabilities']
        if not isinstance(probabilities, dict) or set(probabilities) != set(choices):
            raise ValueError()
        for value in probabilities.values():
            probability(value)
        if abs(sum(probabilities.values()) - 1) > .05:
            raise ValueError()
        if probabilities[answer['choice']] + .001 < max(probabilities.values()):
            raise ValueError()
        model = result['model']
        if not isinstance(model, str) or not re.fullmatch(r'jev-[A-Za-z0-9.-]{1,48}', model):
            raise ValueError()
        usage = result.get('usage', {})
        if not isinstance(usage, dict):
            raise ValueError()
        safe_usage = {k: usage.get(k) if type(usage.get(k)) is int and 0 <= usage[k] <= 1000000 else None
                      for k in ('input_tokens', 'output_tokens')}
        return {'choice': answer['choice'], 'confidence': confidence, 'probabilities': dict(probabilities),
                'model': model, 'usage': safe_usage}
    except Exception:
        raise JevError('Invalid evaluator choice; details omitted. No retry.', calls=1) from None
