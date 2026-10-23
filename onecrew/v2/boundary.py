"""W40 — the install-boundary check (R00, T33a), reusable by every release.

At the end of a run on the INSTALLED package, every module in sys.modules must belong to a valid group, computed from the distribution
and the interpreter — never hard-coded:

  onecrew     — the name is in the shipped set (py-modules + every dotted prefix + the data packages, exactly test_g1_core.shipped()) AND
                the loaded file is in the installed distribution's RECORD. A right name loaded from a file outside RECORD (a checkout) is a
                violation (M4, M5).
  stdlib      — markers derived from the interpreter: `python -I -S` + importlib.util.find_spec over sys.stdlib_module_names gives the marker
                files and their directories. A module is stdlib when it is built-in (sys.builtin_module_names), frozen (_imp.is_frozen), a
                top-level module whose file equals the marker file, or a submodule whose file is under a marker directory. NOT "any file under
                the Python prefix": site-packages is not a marker directory. So _sqlite3 / _socket in DLLs pass (M2); a fake csv shadowing the
                stdlib fails (M7).
  dependency  — the top-level belongs to a distribution in Requires-Dist (recursively; empty here) AND the file is in its RECORD. An undeclared
                package (pip) fails (M6).
  __main__    — an installed command, or a kit driver whose file sha256 is in the kit manifest (WK0).

Modules loaded at STARTUP are NOT exempt: every module in sys.modules at the end is judged. The only exemption is the clean-venv base packages
loaded via .pth before the wheel (e.g. pip), listed explicitly in the receipt; it never covers onecrew or a file outside the venv and the marker
dirs. That is why a startup-loaded checkout module is still caught (M8).

`classify(name, info, ctx)` -> (group, reason); group 'VIOLATION' carries the why. `markers(python)` builds the stdlib marker set from an
interpreter. `shipped_names(pyproject_text)` reuses test_g1_core's computation. The actual sys.modules dump and the subprocess cases live in the
kit harness (tests/wf_wheel.py) so this module stays import-light and shippable.
"""
import os
import re


def norm(path):
    return os.path.normcase(os.path.realpath(path)) if path else path


def shipped_names(pyproject_text):
    """(modules, packages, parents) exactly as test_g1_core.shipped() computes them: py-modules, the data packages, and every dotted prefix
    of a module (the parent packages the build adds)."""
    modules = set(re.findall(r'"([\w.]+)"', re.search(r'py-modules\s*=\s*\[(.*?)\]', pyproject_text, re.S).group(1)))
    pkg_match = re.search(r'^\s*packages\s*=\s*\[(.*?)\]', pyproject_text, re.M | re.S)
    packages = set(re.findall(r'"([\w.]+)"', pkg_match.group(1))) if pkg_match else set()
    parents = {'.'.join(m.split('.')[:i]) for m in modules for i in range(1, len(m.split('.')))}
    return modules, packages, parents


def classify(name, info, ctx):
    """(group, reason) for one module. `info` = {file, origin, frozen, builtin}. `ctx` has: modules, packages, parents, record_files (a set of
    normalised paths), stdlib_names, ref (name->marker origin), builtin (set), marker_dirs (list), dep_tops, dep_files, base_exempt (startup
    base packages to skip, e.g. pip), driver (the allowed __main__ file or None)."""
    if name in ctx.get('base_exempt', ()):                    # clean-venv base package loaded before the wheel (listed in the receipt)
        return 'base (venv)', ''
    if name == '__main__':
        return ('__main__', '') if info.get('file') in (None, ctx.get('driver')) else ('VIOLATION', 'unknown driver: ' + str(info.get('file')))
    top = name.split('.')[0]
    origin = info.get('origin')
    f = norm(info.get('file') or (origin if origin not in (None, 'built-in', 'frozen') else None))
    if top == 'onecrew':
        allowed = ctx['modules'] | ctx['packages'] | ctx['parents']
        if name not in allowed and not any(name.startswith(p + '.') for p in ctx['packages']):
            return 'VIOLATION', f'onecrew name not in the shipped list: {name}'
        if f is None or f not in ctx['record_files']:
            return 'VIOLATION', f'onecrew loaded from a file outside RECORD: {info.get("file")}'
        return 'onecrew', ''
    if info.get('builtin') or origin == 'built-in':
        return ('built-in', '') if name in ctx['builtin'] else ('VIOLATION', 'built-in not in sys.builtin_module_names')
    if info.get('frozen') or origin == 'frozen':
        return ('frozen', '') if top in ctx['stdlib_names'] else ('VIOLATION', 'frozen module outside stdlib')
    if top in ctx['stdlib_names']:
        if f is None:
            return 'VIOLATION', 'stdlib module with no source'
        if '.' not in name and ctx['ref'].get(name) and norm(ctx['ref'][name]) != f:
            return 'VIOLATION', f'stdlib shadowed: {info.get("file")} != {ctx["ref"][name]}'
        if not any(f.startswith(d + os.sep) or f == d for d in ctx['marker_dirs']):
            return 'VIOLATION', f'stdlib name loaded from outside a marker directory: {info.get("file")}'
        return 'stdlib', ''
    if top in ctx['dep_tops']:
        return ('dependency', '') if f in ctx['dep_files'] else ('VIOLATION', 'declared dependency loaded from outside its RECORD')
    return 'VIOLATION', f'module outside the install boundary (undeclared dependency?): {info.get("file")}'


def violations(modules, ctx):
    """[(name, reason)] for every module in `modules` (a dict name -> info) that is not in a valid group."""
    return [(name, why) for name in sorted(modules) for group, why in [classify(name, modules[name], ctx)] if group == 'VIOLATION']
