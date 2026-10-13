"""OS write boundary for worker commands on Windows, per task (GX-P1-01 13/10/2026; per-task since Codex review 2, same day).

A contained command runs with a restricted copy of the runner's token: BUILTIN\\Administrators is deny-only, every
privilege except change-notify is removed, the integrity level is Low, and the token carries RESTRICTING SIDs: the
token's own enabled groups and user, plus two resource SIDs - S_task (this task, derived from state root + task) and
CONTAINED (every contained process). For a restricted token Windows grants a write only if both the ordinary SIDs and
the restricting SIDs are granted it.

The core gives each task directory (workspace, temp, cache, verification checkout) a protected DACL, in this order:
ALLOW S_task full, DENY CONTAINED every write right, ALLOW user/SYSTEM/Administrators full - and a Low label. A
contained command of task X writes its own directories (the first ACE matches its restricting S_X); in a directory of
task Y it meets DENY CONTAINED; the core, which is not restricted and carries no CONTAINED, writes both. Everything not
labelled Low (the project, the OneCrew state/ledger, the user profile, other repositories) stays refused by mandatory
integrity control. Permissions come from this explicit DACL, never from the owner or inherited ACL of a parent
directory: the token default owner is the user in a Claude entry but BUILTIN\\Administrators in the Codex app and the
Task Scheduler host on this machine, and owner-based ACLs (e.g. mkdtemp(0o700)) then refused the contained command its
own workspace - Codex review 2, finding 4.

Stated plainly, this is a WRITE boundary: a contained command can still read what the user can read and use the
network, and Windows' shared Low locations (e.g. %USERPROFILE%\\AppData\\LocalLow) remain writable by every task. The
process tree also runs in a Job object (see work_tools._spawn)."""
import ctypes
from ctypes import wintypes as w
import hashlib
import msvcrt
import os
from pathlib import Path
import subprocess

from .ledger import LedgerError

CONTAINED = 'S-1-9-1-0'           # resource-manager authority: names no account; carried by every contained process
TASK_PREFIX = 'S-1-9-1-1-'
WRITE_RIGHTS = '0xd0156'          # WRITE_DATA|APPEND|WRITE_EA|DELETE_CHILD|WRITE_ATTRIBUTES|DELETE|WRITE_DAC|WRITE_OWNER
ADMINISTRATORS = 'S-1-5-32-544'


def task_sid(key):
    """Deterministic resource SID of one task (key: its home directory name, a hash of state root + task)."""
    digest = hashlib.sha256(str(key).encode()).digest()
    return TASK_PREFIX + '-'.join(str(int.from_bytes(digest[i:i + 4], 'little')) for i in range(0, 16, 4))


def _apis():
    if os.name != 'nt': raise LedgerError('The command write boundary is implemented for Windows only.')
    k = ctypes.WinDLL('kernel32', use_last_error=True); a = ctypes.WinDLL('advapi32', use_last_error=True)
    k.GetCurrentProcess.restype = w.HANDLE
    k.InitializeProcThreadAttributeList.argtypes = [ctypes.c_void_p, w.DWORD, w.DWORD, ctypes.POINTER(ctypes.c_size_t)]
    k.UpdateProcThreadAttribute.argtypes = [ctypes.c_void_p, w.DWORD, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p]
    k.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
    k.SetHandleInformation.argtypes = [w.HANDLE, w.DWORD, w.DWORD]
    k.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    k.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
    k.TerminateProcess.argtypes = [w.HANDLE, w.UINT]
    k.ResumeThread.argtypes = [w.HANDLE]
    k.CloseHandle.argtypes = [w.HANDLE]
    k.LocalFree.argtypes = [ctypes.c_void_p]
    a.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
    a.CreateRestrictedToken.argtypes = [w.HANDLE, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, ctypes.c_void_p, w.DWORD,
                                        ctypes.c_void_p, ctypes.POINTER(w.HANDLE)]
    a.ConvertStringSidToSidW.argtypes = [w.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    a.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(w.LPWSTR)]
    a.SetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
    a.GetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)]
    a.GetLengthSid.argtypes = [ctypes.c_void_p]
    a.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [w.LPCWSTR, w.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    a.GetSecurityDescriptorDacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(w.BOOL), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(w.BOOL)]
    a.GetSecurityDescriptorSacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(w.BOOL), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(w.BOOL)]
    a.GetSecurityDescriptorOwner.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(w.BOOL)]
    a.SetNamedSecurityInfoW.argtypes = [w.LPCWSTR, ctypes.c_int, w.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    a.CreateProcessAsUserW.argtypes = [w.HANDLE, w.LPCWSTR, w.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, w.BOOL, w.DWORD,
                                       ctypes.c_void_p, w.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p]
    return k, a


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [('Sid', ctypes.c_void_p), ('Attributes', w.DWORD)]


class _StartupInfo(ctypes.Structure):
    _fields_ = [('cb', w.DWORD), ('lpReserved', w.LPWSTR), ('lpDesktop', w.LPWSTR), ('lpTitle', w.LPWSTR), ('dwX', w.DWORD),
                ('dwY', w.DWORD), ('dwXSize', w.DWORD), ('dwYSize', w.DWORD), ('dwXCountChars', w.DWORD),
                ('dwYCountChars', w.DWORD), ('dwFillAttribute', w.DWORD), ('dwFlags', w.DWORD), ('wShowWindow', w.WORD),
                ('cbReserved2', w.WORD), ('lpReserved2', ctypes.c_void_p), ('hStdInput', w.HANDLE),
                ('hStdOutput', w.HANDLE), ('hStdError', w.HANDLE)]


class _StartupInfoEx(ctypes.Structure):
    _fields_ = [('StartupInfo', _StartupInfo), ('lpAttributeList', ctypes.c_void_p)]


class _ProcessInformation(ctypes.Structure):
    _fields_ = [('hProcess', w.HANDLE), ('hThread', w.HANDLE), ('dwProcessId', w.DWORD), ('dwThreadId', w.DWORD)]


def _sid(a, text):
    value = ctypes.c_void_p()
    if not a.ConvertStringSidToSidW(text, ctypes.byref(value)): raise ctypes.WinError(ctypes.get_last_error())
    return value


def _text(k, a, pointer):
    value = w.LPWSTR()
    if not a.ConvertSidToStringSidW(ctypes.c_void_p(pointer), ctypes.byref(value)): raise ctypes.WinError(ctypes.get_last_error())
    try: return value.value
    finally: k.LocalFree(ctypes.cast(value, ctypes.c_void_p))


def _info(a, token, kind):
    size = w.DWORD(); a.GetTokenInformation(token, kind, None, 0, ctypes.byref(size))
    buffer = ctypes.create_string_buffer(max(size.value, 8))
    if not a.GetTokenInformation(token, kind, buffer, size, ctypes.byref(size)): raise ctypes.WinError(ctypes.get_last_error())
    return buffer


def _groups(k, a, token, kind=2):
    """[(sid text, attributes)] of TokenGroups (2) or TokenRestrictedSids (11)."""
    buffer = _info(a, token, kind)
    count = ctypes.cast(buffer, ctypes.POINTER(w.DWORD))[0]
    entries = ctypes.cast(ctypes.addressof(buffer) + ctypes.sizeof(ctypes.c_void_p), ctypes.POINTER(_SidAndAttributes * count)).contents
    return [(_text(k, a, entry.Sid), entry.Attributes) for entry in entries]


def _own():
    k, a = _apis(); own = w.HANDLE()
    if not a.OpenProcessToken(k.GetCurrentProcess(), 0x0002 | 0x0008 | 0x0001 | 0x0080 | 0x0020, ctypes.byref(own)):
        raise ctypes.WinError(ctypes.get_last_error())  # DUPLICATE | QUERY | ASSIGN_PRIMARY | ADJUST_DEFAULT | ADJUST_PRIVILEGES
    return k, a, own


def user_sid():
    k, a, own = _own()
    try: return _text(k, a, ctypes.cast(_info(a, own, 1), ctypes.POINTER(ctypes.c_void_p))[0])
    finally: k.CloseHandle(own)


def _token(k, a, task):
    """Restricted Low-integrity copy of this process token for one task (a restricted version of the caller's own
    primary token, so CreateProcessAsUser needs no extra privilege)."""
    _, _, own = _own()
    pointers = []
    try:
        user = _text(k, a, ctypes.cast(_info(a, own, 1), ctypes.POINTER(ctypes.c_void_p))[0])
        # Enabled, not deny-only, not the integrity label, not Administrators: the restricted pass then grants what the ordinary
        # pass grants (system files, toolchains in the profile, the desktop), except where a task ACL says otherwise.
        keep = [s for s, attributes in _groups(k, a, own) if attributes & 0x4 and not attributes & 0x10 and not attributes & 0x20
                and s != ADMINISTRATORS]
        wanted = list(dict.fromkeys([user, *keep, task_sid(task), CONTAINED]))
        pointers = [_sid(a, s) for s in wanted]
        restricting = (_SidAndAttributes * len(pointers))(*[_SidAndAttributes(p, 0) for p in pointers])
        admins = _sid(a, ADMINISTRATORS); pointers.append(admins)
        deny = _SidAndAttributes(admins, 0)
        restricted = w.HANDLE()
        if not a.CreateRestrictedToken(own, 0x1, 1, ctypes.byref(deny), 0, None, len(restricting), restricting, ctypes.byref(restricted)):
            raise ctypes.WinError(ctypes.get_last_error())  # DISABLE_MAX_PRIVILEGE
        try:
            carried = {s for s, _ in _groups(k, a, restricted, 11)}
            if not {task_sid(task), CONTAINED} <= carried:
                # A parent token that is itself restricted intersects the list: the per-task boundary would not exist.
                raise LedgerError('environment: the per-task write boundary cannot be established under this host token '
                                  '(it is already restricted); commands are not run with a weaker boundary.')
            low = _sid(a, 'S-1-16-4096'); pointers.append(low)
            label = _SidAndAttributes(low, 0x20)  # SE_GROUP_INTEGRITY
            if not a.SetTokenInformation(restricted, 25, ctypes.byref(label), ctypes.sizeof(label) + a.GetLengthSid(low)):
                raise ctypes.WinError(ctypes.get_last_error())
            _own_defaults(k, a, restricted, user)
            return restricted
        except BaseException:
            k.CloseHandle(restricted); raise
    finally:
        k.CloseHandle(own)
        for pointer in pointers: k.LocalFree(pointer)


def _descriptor(a, sddl):
    descriptor = ctypes.c_void_p()
    if not a.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    return descriptor


def _own_defaults(k, a, token, user):
    """Objects the contained process creates for itself (its process, threads, sections) are owned by and open to the
    user, not to BUILTIN\\Administrators. With UAC off (this host) or under the Task Scheduler, the token's default owner
    and DACL name Administrators, which the restricted token holds deny-only, and every contained process then failed
    to initialise (0xC0000142) - acceptance runs N1-r2/N2-r1 on 13/10/2026."""
    owner = _sid(a, user)
    descriptor = _descriptor(a, f'D:(A;;GA;;;{user})(A;;GA;;;SY)')
    try:
        if not a.SetTokenInformation(token, 4, ctypes.byref(owner), ctypes.sizeof(owner)):  # TokenOwner
            raise ctypes.WinError(ctypes.get_last_error())
        present, dacl, defaulted = w.BOOL(), ctypes.c_void_p(), w.BOOL()
        a.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted))
        if not a.SetTokenInformation(token, 6, ctypes.byref(dacl), ctypes.sizeof(dacl)):  # TokenDefaultDacl
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        k.LocalFree(descriptor); k.LocalFree(owner)


def _apply(path, sddl, label):
    """Owner = the user, the given protected DACL (and Low label). The owner is set explicitly because tools check it:
    Git refuses a work tree or Git directory owned by BUILTIN\\Administrators when Administrators is deny-only in the
    caller's token, which it is in the contained token (safe.directory)."""
    k, a = _apis(); descriptor = _descriptor(a, 'O:' + user_sid() + sddl)
    try:
        owner, defaulted0 = ctypes.c_void_p(), w.BOOL()
        a.GetSecurityDescriptorOwner(descriptor, ctypes.byref(owner), ctypes.byref(defaulted0))
        present, dacl, defaulted = w.BOOL(), ctypes.c_void_p(), w.BOOL()
        a.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted))
        sacl = ctypes.c_void_p()
        if label:
            present2, defaulted2 = w.BOOL(), w.BOOL()
            a.GetSecurityDescriptorSacl(descriptor, ctypes.byref(present2), ctypes.byref(sacl), ctypes.byref(defaulted2))
        flags = 0x1 | 0x4 | 0x80000000 | (0x10 if label else 0)  # OWNER | DACL | PROTECTED_DACL (| LABEL)
        error = a.SetNamedSecurityInfoW(str(path), 1, flags, owner, None, dacl, sacl if label else None)
        if error: raise LedgerError('Cannot set the access rules of ' + str(path) + ': ' + str(ctypes.WinError(error))[:200])
    finally:
        k.LocalFree(descriptor)


def own(path):
    """Owner = the user for one existing object (a Git directory or gitfile the core created), nothing else changed."""
    k, a = _apis(); pointer = _sid(a, user_sid())
    try:
        error = a.SetNamedSecurityInfoW(str(path), 1, 0x1, ctypes.c_void_p(pointer.value), None, None, None)
        if error: raise LedgerError('Cannot set the owner of ' + str(path) + ': ' + str(ctypes.WinError(error))[:200])
    finally:
        k.LocalFree(pointer)


def protect(path, task):
    """Make a directory tree belong to one task: protected DACL (ALLOW S_task, DENY every contained process the write
    rights, ALLOW user/SYSTEM/Administrators, OWNER RIGHTS read-control only) and an inherited Low label, applied to
    existing children as well. The ACE order is deliberate and kept by SetNamedSecurityInfo: the owning task's ALLOW is met
    before the DENY. The OWNER RIGHTS entry removes the owner's implicit WRITE_DAC: the owner is the user, whose SID is in
    every contained token, so without it any task could rewrite another task's DACL and then write there."""
    path = Path(path); path.mkdir(parents=True, exist_ok=True)
    _apply(path, f'D:P(A;OICI;FA;;;{task_sid(task)})(D;OICI;{WRITE_RIGHTS};;;{CONTAINED})(A;OICI;FA;;;{user_sid()})'
                 '(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;RC;;;OW)S:(ML;OICI;NW;;;LW)', True)


def private(path):
    """Core-owned task home (its Git directory, metadata, logs): explicit ALLOW user/SYSTEM/Administrators, inherited by
    what the core creates later and independent of the token's default owner. No Low label, so contained processes can
    read it (git status in the workspace needs its Git directory) but never write it (no-write-up). Without this, a home
    created under a default owner of Administrators (Codex app, Task Scheduler) carries SYSTEM/Administrators/OWNER RIGHTS
    only, which the contained token (Administrators deny-only) cannot read."""
    path = Path(path); path.mkdir(parents=True, exist_ok=True)
    _apply(path, f'D:P(A;OICI;FA;;;{user_sid()})(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;RC;;;OW)', False)


class Contained:
    """Popen-shaped handle of a contained process, created suspended (assign it to a Job, then resume())."""
    def __init__(self, k, info):
        self._k = k; self._handle = int(info.hProcess); self._thread = int(info.hThread); self.pid = info.dwProcessId
        self.returncode = None

    def resume(self):
        if self._k.ResumeThread(w.HANDLE(self._thread)) == 0xFFFFFFFF: raise ctypes.WinError(ctypes.get_last_error())

    def poll(self):
        if self.returncode is None and self._k.WaitForSingleObject(w.HANDLE(self._handle), 0) == 0:
            code = w.DWORD(); self._k.GetExitCodeProcess(w.HANDLE(self._handle), ctypes.byref(code)); self.returncode = code.value
        return self.returncode

    def wait(self, timeout=None):
        milliseconds = 0xFFFFFFFF if timeout is None else int(timeout * 1000)
        if self._k.WaitForSingleObject(w.HANDLE(self._handle), milliseconds) != 0:
            raise subprocess.TimeoutExpired('contained process', timeout)
        return self.poll()

    def kill(self):
        if self.poll() is None: self._k.TerminateProcess(w.HANDLE(self._handle), 1)

    def __del__(self):
        try:
            for handle in (self._thread, self._handle):
                if handle: self._k.CloseHandle(w.HANDLE(handle))
            self._thread = self._handle = 0
        except Exception:
            pass


def _environment_block(env):
    items = sorted(((str(k), str(v)) for k, v in env.items() if '=' not in str(k)[1:] and '\0' not in str(v)), key=lambda x: x[0].upper())
    return ctypes.create_unicode_buffer(''.join(f'{k}={v}\0' for k, v in items) + '\0')


def spawn(line, cwd, env, out, err, task):
    """Start a contained process of `task` suspended. line: argv list or a full command line; out/err: open binary files."""
    k, a = _apis()
    command = line if isinstance(line, str) else subprocess.list2cmdline([str(x) for x in line])
    token = _token(k, a, task)
    null = open(os.devnull, 'rb')
    try:
        handles = [w.HANDLE(msvcrt.get_osfhandle(f.fileno())) for f in (null, out, err)]
        for handle in handles: k.SetHandleInformation(handle, 1, 1)  # inheritable, but only these three (attribute list)
        size = ctypes.c_size_t()
        k.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
        attributes = ctypes.create_string_buffer(size.value)
        if not k.InitializeProcThreadAttributeList(attributes, 1, 0, ctypes.byref(size)): raise ctypes.WinError(ctypes.get_last_error())
        unique = list({int(h.value): h for h in handles}.values())
        array = (w.HANDLE * len(unique))(*unique)
        try:
            if not k.UpdateProcThreadAttribute(attributes, 0, 0x20002, array, ctypes.sizeof(array), None, None):  # HANDLE_LIST
                raise ctypes.WinError(ctypes.get_last_error())
            info = _StartupInfoEx(); info.StartupInfo.cb = ctypes.sizeof(info); info.lpAttributeList = ctypes.cast(attributes, ctypes.c_void_p)
            info.StartupInfo.dwFlags = 0x100  # STARTF_USESTDHANDLES
            info.StartupInfo.hStdInput, info.StartupInfo.hStdOutput, info.StartupInfo.hStdError = handles
            process = _ProcessInformation()
            buffer = ctypes.create_unicode_buffer(command)
            flags = 0x4 | 0x08000000 | 0x400 | 0x80000  # suspended, no window, unicode environment, extended startup info
            if not a.CreateProcessAsUserW(token, None, buffer, None, None, True, flags, _environment_block(env), str(cwd),
                                          ctypes.byref(info), ctypes.byref(process)):
                raise LedgerError('Cannot start a contained command: ' + str(ctypes.WinError(ctypes.get_last_error()))[:200])
        finally:
            k.DeleteProcThreadAttributeList(attributes)
        return Contained(k, process)
    finally:
        null.close(); k.CloseHandle(token)


def available(task='onecrew-availability-probe'):
    """(True, None) when a per-task contained token can be created here, else (False, reason)."""
    try:
        k, a = _apis(); k.CloseHandle(_token(k, a, task)); return True, None
    except (OSError, LedgerError) as error:
        return False, str(error)[:300]
