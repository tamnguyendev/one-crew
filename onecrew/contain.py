"""OS write boundary for worker commands on Windows (GX-P1-01, 13/10/2026).

A contained command runs with a restricted copy of the runner's token: BUILTIN\\Administrators is deny-only, every
privilege except change-notify is removed and the integrity level is Low. Mandatory integrity control then refuses every
write to an object that is not labelled Low, so the command can write only where the core labelled Low: the task's
workspace, temporary and cache directories. The user's project, the OneCrew state/ledger, the user profile and other
repositories are refused by the operating system, whichever program the command runs.

Stated plainly, this is a WRITE boundary: a contained command can still read what the user can read and use the
network. The process tree also runs in a Job object (see work_tools._spawn)."""
import ctypes
from ctypes import wintypes as w
import msvcrt
import os
from pathlib import Path
import subprocess

from .ledger import LedgerError

ICACLS = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'icacls.exe'


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
    a.SetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
    a.GetLengthSid.argtypes = [ctypes.c_void_p]
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


def _token(k, a):
    """Restricted Low-integrity copy of this process token (a restricted version of the caller's own primary token, so
    CreateProcessAsUser needs no extra privilege)."""
    own = w.HANDLE()
    if not a.OpenProcessToken(k.GetCurrentProcess(), 0x0002 | 0x0008 | 0x0001 | 0x0080 | 0x0020, ctypes.byref(own)):
        raise ctypes.WinError(ctypes.get_last_error())  # DUPLICATE | QUERY | ASSIGN_PRIMARY | ADJUST_DEFAULT | ADJUST_PRIVILEGES
    admins = _sid(a, 'S-1-5-32-544'); low = _sid(a, 'S-1-16-4096')
    try:
        restricted = w.HANDLE()
        deny = _SidAndAttributes(admins, 0)
        if not a.CreateRestrictedToken(own, 0x1, 1, ctypes.byref(deny), 0, None, 0, None, ctypes.byref(restricted)):  # DISABLE_MAX_PRIVILEGE
            raise ctypes.WinError(ctypes.get_last_error())
        label = _SidAndAttributes(low, 0x20)  # SE_GROUP_INTEGRITY
        if not a.SetTokenInformation(restricted, 25, ctypes.byref(label), ctypes.sizeof(label) + a.GetLengthSid(low)):
            k.CloseHandle(restricted); raise ctypes.WinError(ctypes.get_last_error())
        _own_defaults(k, a, restricted)
        return restricted
    finally:
        k.CloseHandle(own); k.LocalFree(admins); k.LocalFree(low)


def _own_defaults(k, a, token):
    """Objects the contained process creates for itself (its process, threads, sections) are owned by and open to the
    user, not to BUILTIN\\Administrators. With UAC off (this host) or under the Task Scheduler, the token's default owner
    and DACL name Administrators, which the restricted token holds deny-only, and every contained process then failed
    to initialise (0xC0000142) - acceptance runs N1-r2/N2-r1 on 13/10/2026."""
    a.GetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)]
    a.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(w.LPWSTR)]
    a.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [w.LPCWSTR, w.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    a.GetSecurityDescriptorDacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(w.BOOL), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(w.BOOL)]
    size = w.DWORD(); a.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
    buffer = ctypes.create_string_buffer(size.value)
    if not a.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)): raise ctypes.WinError(ctypes.get_last_error())
    user = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]  # TOKEN_USER.User.Sid
    text = w.LPWSTR()
    if not a.ConvertSidToStringSidW(ctypes.c_void_p(user), ctypes.byref(text)): raise ctypes.WinError(ctypes.get_last_error())
    sid = text.value; k.LocalFree(text)
    owner = ctypes.c_void_p(user)
    if not a.SetTokenInformation(token, 4, ctypes.byref(owner), ctypes.sizeof(owner)):  # TokenOwner
        raise ctypes.WinError(ctypes.get_last_error())
    descriptor = ctypes.c_void_p()
    if not a.ConvertStringSecurityDescriptorToSecurityDescriptorW(f'D:(A;;GA;;;{sid})(A;;GA;;;SY)', 1, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        present, dacl, defaulted = w.BOOL(), ctypes.c_void_p(), w.BOOL()
        a.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted))
        if not a.SetTokenInformation(token, 6, ctypes.byref(dacl), ctypes.sizeof(dacl)):  # TokenDefaultDacl
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        k.LocalFree(descriptor)


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


def spawn(line, cwd, env, out, err):
    """Start a contained process suspended. line: argv list or a full command line; out/err: open binary files."""
    k, a = _apis()
    command = line if isinstance(line, str) else subprocess.list2cmdline([str(x) for x in line])
    token = _token(k, a)
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


def label_low(path):
    """Let contained commands write in this directory tree (inherited Low label, also applied to existing children).
    The directory's ordinary permissions are unchanged; only the integrity label is added."""
    path = Path(path); path.mkdir(parents=True, exist_ok=True)
    done = subprocess.run([str(ICACLS), str(path), '/setintegritylevel', '(OI)(CI)L'], capture_output=True, timeout=600,
                          creationflags=0x08000000)
    if done.returncode: raise LedgerError('Cannot label the workspace for contained commands: ' + done.stdout.decode(errors='replace')[-300:])


def is_low(path):
    done = subprocess.run([str(ICACLS), str(path)], capture_output=True, timeout=60, creationflags=0x08000000)
    return done.returncode == 0 and b'Low Mandatory Level' in done.stdout


def available():
    """(True, None) when contained processes can be created here, else (False, reason)."""
    try:
        k, a = _apis(); k.CloseHandle(_token(k, a)); return True, None
    except (OSError, LedgerError) as error:
        return False, str(error)[:300]
