"""Device environment check and bounded recovery inside the approved device window.

OneCrew checks the device before and during a scenario and repairs only what cannot change app or
account data: wake the screen, dismiss a non-secure keyguard, answer an Android "not responding"
system dialog with Wait, and - only for the emulator the approved envelope names - boot or restart
that emulator. Every action is recorded; anything else stays an environment failure for the recovery
policy (bounded retry, then one question). A physical device is never rebooted or reconfigured."""
import os
from pathlib import Path
import re
import subprocess
import time
import xml.etree.ElementTree as ET

from .ledger import LedgerError

EMULATOR_SERIAL = re.compile(r'emulator-(\d{4})\Z')
# Recovery actions a device stage may perform. A physical device gets none unless the approved stage lists them;
# an emulator keeps all (its restart additionally needs `device.emulator`).
RECOVERY = {
    'wake_screen': 'adb shell input keyevent KEYCODE_WAKEUP (turns the screen on; no app input)',
    'dismiss_keyguard': 'adb shell wm dismiss-keyguard (non-secure lock only; a PIN/pattern lock stays)',
    'system_dialog_wait': 'tap Wait (android:id/aerr_wait) on a system "not responding" dialog of another app',
    'close_own_crash_dialog': 'tap Close app on the crash dialog of the app under test (its process is already dead)',
    'restart_emulator': 'adb emu kill + boot of the approved AVD (emulator serial and device.emulator only)',
}
AVD_NAME = re.compile(r'[A-Za-z0-9_.-]{1,100}\Z')
# Focus title of the system "not responding" / crash dialogs (AOSP AppNotRespondingDialog / AppErrorDialog).
SYSTEM_DIALOG = re.compile(r'Application Not Responding|Application Error|isn.t responding|not responding', re.I)
WAIT_IDS = ('android:id/aerr_wait',)
WAIT_LABELS = ('wait', 'đợi', 'chờ')
BOOT_SECONDS = 300


class EmulatorIdentityError(LedgerError):
    """The instance on the pinned emulator serial is not provably the approved AVD (or not OneCrew's to change)."""


def parse_avd_name(raw):
    """AVD name from `adb emu avd name` ("<name>\nOK"); None when the console did not answer that way."""
    lines = [line.strip() for line in (raw or '').splitlines() if line.strip()]
    return lines[0] if len(lines) >= 2 and lines[-1] == 'OK' and AVD_NAME.fullmatch(lines[0]) else None


def parse_boot_id(raw):
    value = (raw or '').strip()
    return value if re.fullmatch(r'[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', value) else None


class EnvironmentUnusable(LedgerError):
    """The device stayed unusable after the bounded, granted recovery actions."""


def recovery_grant(c):
    """Granted recovery actions: the stage's explicit list, else all for an emulator and none for a real device."""
    if c.get('recovery') is not None: return set(c['recovery'])
    return set(RECOVERY) if EMULATOR_SERIAL.fullmatch(c.get('serial') or '') else set()


def validate_recovery(value, serial):
    if value is None: return None
    if not isinstance(value, list) or len(set(value)) != len(value) or set(value) - set(RECOVERY):
        raise LedgerError('Device recovery must be a list of: ' + ', '.join(sorted(RECOVERY)) + '.')
    if 'restart_emulator' in value and not EMULATOR_SERIAL.fullmatch(serial or ''):
        raise LedgerError('restart_emulator applies to an emulator serial only.')
    return value


def validate_emulator(value, serial):
    """Envelope/plan form of an emulator OneCrew may boot: {'avd': name, 'avd_home': absolute path or null}."""
    if value is None: return None
    if not isinstance(value, dict) or set(value) != {'avd', 'avd_home'}:
        raise LedgerError('Emulator stage needs exactly avd and avd_home.')
    if not isinstance(value['avd'], str) or not AVD_NAME.fullmatch(value['avd']):
        raise LedgerError('Emulator AVD name invalid.')
    if value['avd_home'] is not None and (not isinstance(value['avd_home'], str) or not Path(value['avd_home']).is_absolute()):
        raise LedgerError('Emulator avd_home must be an absolute local path or null.')
    m = EMULATOR_SERIAL.fullmatch(serial or '')
    if not m or not 5554 <= int(m[1]) <= 5682 or int(m[1]) % 2:
        raise LedgerError('Only an emulator serial (emulator-<even port 5554-5682>) may be booted by OneCrew.')
    return value


def ensure_server(adb):
    """Start the adb server outside any captured command. A server spawned by a captured client inherits its
    raw stream handles (files stay locked) and lives or dies with that client's job."""
    if not Path(adb).is_file(): return False
    try:
        subprocess.run([str(adb), 'start-server'], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, close_fds=True, timeout=30,
                       creationflags=0x08000000 if os.name == 'nt' else 0)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def health(call, package=None):
    """What blocks input right now, from `dumpsys window` and `dumpsys power`. Unknown output is not a blocker.
    The crash dialog of the app under test is not an environment hang: it is reported apart (app_crash_dialog)."""
    from .delivery_android import foreground_focus
    windows = call('shell', 'dumpsys', 'window')
    focus = foreground_focus(windows) or ''
    power = call('shell', 'dumpsys', 'power')
    dialog = bool(SYSTEM_DIALOG.search(focus))
    own = dialog and bool(package) and bool(re.search(r'[:\s]' + re.escape(package) + r'\}?\s*$', focus))
    return {'focus': focus[:160], 'system_dialog': dialog and not own, 'app_crash_dialog': own,
            'keyguard': bool(re.search(r'isKeyguardShowing=true|mDreamingLockscreen=true|mShowingLockscreen=true', windows)),
            'asleep': bool(re.search(r'mWakefulness=(Asleep|Dozing)', power))}


def crash_summary(text, package):
    """Newest crash of `package` in a logcat crash buffer, reduced to structure: kind, signal or exception
    class, thread and native libraries. Never messages or raw lines (they may hold account data)."""
    found, lines = None, (text or '').splitlines()
    for i, line in enumerate(lines):
        m = re.search(r'pid: \d+, tid: \d+, name: (\S+)\s+>>> ' + re.escape(package) + r' <<<', line)
        if m:
            block = lines[i + 1:i + 60]
            signal = next((s[1] for s in (re.search(r'signal \d+ \((SIG[A-Z]+)\)', l) for l in block) if s), None)
            libraries = []
            for l in block:
                if ' pc ' not in l: continue
                lib = re.search(r'([A-Za-z0-9_.+-]+\.so)\b', l.split('!')[-1])
                if lib and lib[1] not in libraries: libraries.append(lib[1])
            found = {'kind': 'native', 'signal': signal, 'thread': m[1][:40], 'libraries': libraries[:5]}
        m = re.search(r'FATAL EXCEPTION: (\S+)', line)
        if m and any(re.search(r'Process: ' + re.escape(package) + r', PID', l) for l in lines[i + 1:i + 3]):
            ex = next((e[1] for e in (re.search(r'\b((?:[a-z_$][\w$]*\.)+[A-Z][\w$]*(?:Exception|Error))\b', l) for l in lines[i + 1:i + 5]) if e), None)
            found = {'kind': 'java', 'thread': m[1][:40], 'exception': ex}
    return found


def describe(crash):
    if crash.get('kind') == 'java': return 'Java ' + str(crash.get('exception'))
    if crash.get('kind') == 'native':
        return 'native ' + str(crash.get('signal')) + ' in ' + ','.join(crash.get('libraries') or ['?']) + ', thread ' + str(crash.get('thread'))
    return 'no crash record'


def _center(bounds):
    m = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds or '')
    if not m: return None
    x1, y1, x2, y2 = map(int, m.groups())
    return ((x1 + x2) // 2, (y1 + y2) // 2) if x2 > x1 and y2 > y1 else None


def answer_system_dialog(call, dump, ids=WAIT_IDS, labels=WAIT_LABELS):
    """Tap Wait on a system "not responding" dialog. Never Close/OK on another process: those kill it.
    (Close is used only for the crash dialog of the app under test, whose process is already gone.)"""
    try: root = ET.fromstring(dump())
    except (ET.ParseError, ValueError, OSError): return False
    candidates = [n for n in root.iter('node') if n.get('package') == 'android' and n.get('clickable') == 'true' and
                  (n.get('resource-id') in ids or (n.get('text') or '').strip().casefold() in labels)]
    if len(candidates) != 1: return False
    point = _center(candidates[0].get('bounds'))
    if not point: return False
    call('shell', 'input', 'tap', str(point[0]), str(point[1]))
    return True


def settle(call, dump, record, seconds=60, pause=5.0, stable=1, package=None, allowed=None):
    """Bring the device to a usable foreground with granted, data-preserving actions. Returns the last health.

    Usable means `stable` consecutive clean reads; once a system dialog was seen, three. A just-booted
    emulator's System UI hangs repeatedly for a minute or two under boot load (trial 3, smoke 12/10): Wait is
    answered each time inside the bound instead of restarting at the first dialog. Bounded by reads, not time.
    A leftover crash dialog of the app under test (its process is already dead) is closed and recorded.
    allowed: granted recovery actions (None = all). A blocker whose action is not granted is recorded as
    needs_permission:<action> and nothing is sent."""
    granted = set(RECOVERY) if allowed is None else set(allowed)
    def denied(action, state):
        record('needs_permission:' + action, state['focus']); return state
    clean, seen = 0, False
    for _ in range(max(1, int(seconds / pause))):
        state = health(call, package)
        if state['app_crash_dialog'] and 'close_own_crash_dialog' not in granted: return denied('close_own_crash_dialog', state)
        if state['asleep'] and not state['app_crash_dialog'] and 'wake_screen' not in granted: return denied('wake_screen', state)
        if state['keyguard'] and not (state['app_crash_dialog'] or state['asleep']) and 'dismiss_keyguard' not in granted:
            return denied('dismiss_keyguard', state)
        if (state['system_dialog'] and not (state['app_crash_dialog'] or state['asleep'] or state['keyguard'])
                and 'system_dialog_wait' not in granted): return denied('system_dialog_wait', state)
        if state['app_crash_dialog']:
            closed = answer_system_dialog(call, dump, ('android:id/aerr_close',), ('close app', 'đóng ứng dụng', 'ok'))
            record('app_crash_dialog_closed' if closed else 'app_crash_dialog_open', state['focus'])
            if not closed: return state
            clean = 0
        elif state['asleep']:
            call('shell', 'input', 'keyevent', 'KEYCODE_WAKEUP'); record('wake', None); clean = 0
        elif state['keyguard']:
            call('shell', 'wm', 'dismiss-keyguard'); record('dismiss_keyguard', None); clean = 0
        elif state['system_dialog']:
            seen, clean = True, 0
            record('system_dialog_wait' if answer_system_dialog(call, dump) else 'system_dialog_unanswered', state['focus'])
        else:
            clean += 1
            if clean >= (max(stable, 3) if seen else stable): return state
        time.sleep(pause)
    return health(call)


def blocked(state):
    return [k for k in ('asleep', 'keyguard', 'system_dialog', 'app_crash_dialog') if state.get(k)]


class AppCrashed(LedgerError):
    """The app under test is not running after a launch or step; evidence is a crash summary, not raw logs."""


def emulator_executable(adb):
    sdk = Path(adb).resolve().parents[1]
    return sdk/'emulator'/('emulator.exe' if os.name == 'nt' else 'emulator')


def boot_emulator(adb, serial, emulator, log, call_state, wait=BOOT_SECONDS, window=None):
    """Launch the envelope's AVD headless on the serial's port and wait for boot. Detached, so a coordinator
    restart does not kill it. Returns evidence; raises EnvironmentUnusable if it does not boot in time."""
    port = EMULATOR_SERIAL.fullmatch(serial)[1]
    exe = emulator_executable(adb)
    if not exe.is_file(): raise EnvironmentUnusable('Android emulator executable unavailable.')
    env = dict(os.environ)
    if emulator['avd_home']: env['ANDROID_AVD_HOME'] = emulator['avd_home']
    argv = [str(exe), '-avd', emulator['avd'], '-port', port, '-no-window', '-no-audio', '-no-boot-anim', '-no-snapshot-save']
    Path(log).parent.mkdir(parents=True, exist_ok=True)
    with open(log, 'ab') as out:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, env=env, close_fds=True,
                                   creationflags=(0x8 | 0x200 | 0x01000000 | 0x08000000) if os.name == 'nt' else 0)
    deadline = time.monotonic() + min(wait, window if window is not None else wait)
    while time.monotonic() < deadline:
        if process.poll() is not None: raise EnvironmentUnusable('Emulator exited during boot (see emulator log).')
        if call_state() == ('device', '1'): return {'booted': True, 'pid': process.pid, 'argv': argv[:5]}
        time.sleep(3)
    raise EnvironmentUnusable('Emulator did not finish booting within the bound.')


def kill_emulator(call):
    """Graceful console kill of the pinned emulator (serial already pinned by the caller)."""
    try: call('emu', 'kill')
    except EmulatorIdentityError: raise  # the pinned instance is gone: never reported as a mere failed stop
    except (ValueError, OSError): return False
    return True
