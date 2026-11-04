"""Read-only host lease/registry adapter extracted from the existing v1 host.

Registration and process launch remain user/host operations outside this module.
"""
import datetime as dt
import json
import os
from pathlib import Path
import time

HEARTBEAT = 30


def home():
    # Unlike the legacy host's write entry point, a status read creates nothing.
    configured = os.environ.get('ONECREW_HOST_HOME')
    return Path(configured) if configured else Path.home() / '.onecrew' / 'host'


class _Unreadable(OSError):
    """A host file that exists but cannot be read right now (another process holds it open, an I/O error). It is neither
    missing nor malformed, and nothing it describes may be dropped or decided on because of it."""



def _load(path):
    """('ok', value) | ('missing', None) | ('corrupt', error) | ('unreadable', error).
    P4-A (Codex deep review P3, reproduced with a real Windows lock): the former reader turned every OSError into None, and
    the scan then moved a valid dispatch request that was only locked for a moment out of the queue for good."""
    try: data = Path(path).read_bytes()
    except FileNotFoundError: return 'missing', None
    except OSError as error: return 'unreadable', error
    try: return 'ok', json.loads(data.decode('utf-8'))
    except ValueError as error: return 'corrupt', error  # includes UnicodeDecodeError



def _read(path, default=None):
    """Missing or malformed -> default. A file that exists but cannot be read now raises _Unreadable: callers decide later,
    they never treat it as absent."""
    status, value = _load(path)
    if status == 'unreadable': raise _Unreadable(f'{Path(path).name} cannot be read right now: {value}')
    return value if status == 'ok' else default



def _read_patiently(path, default=None, attempts=4, pause=.05):
    """For readers that must answer now (the lease seen by an entry): a few short retries, then _Unreadable."""
    for attempt in range(attempts):
        try: return _read(path, default)
        except _Unreadable:
            if attempt == attempts - 1: raise
            time.sleep(pause * (attempt + 1))



def _when(text):
    value = dt.datetime.fromisoformat(text)
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)



def lease(base=None, *, probe_fn=None):
    """The live host's lease, or None (missing, stale heartbeat or dead process)."""
    from .process_core import probe
    try: record = _read_patiently((base or home()) / 'lease.json')
    except _Unreadable: return None  # cannot prove a live host right now; the entry says so instead of queueing blindly
    if not record or record.get('stopped_at'): return None
    try:
        if (dt.datetime.now(dt.timezone.utc) - _when(record['heartbeat'])).total_seconds() > HEARTBEAT: return None
    except (KeyError, ValueError): return None
    return record if (probe_fn or probe)(record.get('identity')) == 'alive' else None



def served(state_root, base=None, record=None, *, lease_fn=None):
    """True only when the live host itself reports scanning this state root: the entry's own copy of the registry
    proves nothing if the entry's writes are invisible to the host."""
    record = record or (lease_fn or lease)(base)
    return bool(record) and str(Path(state_root).resolve()) in (record.get('roots_seen') or {})


def status(state_root, base=None):
    """Actual registration plus host-observed service, never a reboot promise."""
    base = Path(base) if base is not None else home()
    root = str(Path(state_root).resolve())
    try:
        registry = _read(base / 'roots.json', {'roots': []})
        rows = registry.get('roots') if isinstance(registry, dict) else None
        registered = (any(isinstance(r, dict) and r.get('state_root') == root for r in rows)
                      if isinstance(rows, list) else 'unknown')
        record = lease(base)
        active = served(state_root, base, record, lease_fn=lambda _: None)
        problem = None
    except (_Unreadable, OSError, ValueError, TypeError) as error:
        registered, record, active, problem = 'unknown', None, False, type(error).__name__
    return {'registered': registered, 'alive': bool(record), 'served': active,
            'automatic_restart_after_reboot': False, 'text': 'không tự chạy lại sau reboot; explicit resume reconciles the checkpoint first',
            'reason': problem or ('The live host observed this state root; reboot still requires explicit resume.' if active else
                                  'This state root is not observed by a live registered host.'),
            'registry_source': str(base / 'roots.json'), 'lease_source': str(base / 'lease.json')}



