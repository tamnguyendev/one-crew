"""Read-only discovery of a Node/Chrome-extension project for the delivery planner: no execution, no network.

``discover(project, roots, env)`` returns ``{facts, problems[{code, detail}], fingerprint}``. Absent tools become problems,
never errors. ``env`` is the process environment (as in delivery_env.discover); an optional approved ``envelope`` adds the
operator's toolchain/stage pins (node_exe, package, build/e2e scripts and their env values), which win over defaults.
package.json scripts are mapped to node.exe argv only (the contained runner cannot start npm/npx .cmd shims).
"""
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex

from .delivery_env import _environ, _file_hash, which
from .ledger import LedgerError, content_hash
from .node_change import GENERATED_DIR
from .node_imports import DEFAULT_TEST_GLOBS, package_files, strip_comments, test_files, tsconfig

PROBLEMS = (  # every code discover() can report
    'root_missing', 'package_missing', 'node_missing', 'node_modules_missing', 'typescript_missing', 'vitest_missing',
    'lock_manifest_missing', 'build_script_unmappable', 'e2e_contract_missing', 'harness_sha_mismatch', 'chrome_missing',
    'backend_venv_missing')
TOOLS = {'tsc': 'node_modules/typescript/bin/tsc', 'vitest': 'node_modules/vitest/vitest.mjs'}
LOCK = 'node_modules/.package-lock.json'
UNMAPPABLE = ('npm', 'npx', 'pnpm', 'pnpx', 'yarn', 'bun', 'bunx', 'cross-env', 'dotenv')
SHELL = re.compile(r'\|\||[|;<>`$%^]|(?<!&)&(?!&)')
SCRIPT_SUFFIXES = ('.mjs', '.js', '.cjs')
VITEST_CONFIGS = tuple(base + ext for base in ('vitest.config', 'vite.config') for ext in ('.ts', '.mts', '.cts', '.js', '.mjs', '.cjs'))
MAX_SCRIPT_BYTES = 2_000_000
MAX_E2E_SCRIPTS = 200
MAX_TESTS = 5000
PACKAGE_DEPTH = 2
# The e2e contract: the harness prints 'N/M checks passed' (node_toolchain.CHECKS) as its verdict.
SUMMARY = re.compile(r'/[^\n]{0,80}?checks passed')
LIVE = {
    'persistent_profile': re.compile(r'\bNA_REAL_PROFILE\b|\bNA_PROFILE_DIR\b|userDataDir\s*:\s*PROFILE_DIR\b'),
    'action_line': re.compile(r'[\'"`]ACTION:'),
    'real_config': re.compile(r'[\'"`]harness[\'"`]\s*,\s*[\'"`]config\.json|harness/config\.json|'
                              r'https?://(?!(?:127\.0\.0\.1|localhost|0\.0\.0\.0)\b|\[::1\])[a-z0-9-]+(?:\.[a-z0-9-]+)+', re.I),
}
ENV_READ = re.compile(r'process\.env(?:\.([A-Z][A-Z0-9_]*)|\[\s*[\'"]([A-Z][A-Z0-9_]*)[\'"]\s*\])')
ENV_DEFAULT = re.compile(r'process\.env\.([A-Z][A-Z0-9_]*)\s*\?\?\s*[\'"`]([^\'"`\n$]{1,300})[\'"`]')


def _problem(code, detail):
    return {'code': code, 'detail': detail}


def _rel(value, what):
    rel = PurePosixPath(str(value).replace('\\', '/'))
    if (not isinstance(value, str) or not value.strip() or rel.is_absolute() or '..' in rel.parts
            or re.match(r'[A-Za-z]:', value)):
        raise LedgerError(what + ' must be a project-relative path: ' + str(value))
    return rel.as_posix()


def _text(path):
    try:
        path = Path(path)
        return path.read_text(encoding='utf-8-sig', errors='replace') if path.stat().st_size <= MAX_SCRIPT_BYTES else None
    except OSError:
        return None


def _json(path):
    try:
        value = json.loads(_text(path) or '')
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _packages(project, rel, depth):
    base = project / rel
    if (base / 'package.json').is_file():
        yield rel
    if depth <= 0:
        return
    try:
        children = sorted(c.name for c in base.iterdir()
                          if c.is_dir() and not c.name.startswith('.') and not GENERATED_DIR.search(c.name))
    except OSError:
        return
    for child in children:
        yield from _packages(project, (PurePosixPath(rel) / child).as_posix(), depth - 1)


def _envelope(envelope):
    envelope = envelope if isinstance(envelope, dict) else {}
    toolchain = envelope.get('toolchain') if isinstance(envelope.get('toolchain'), dict) else {}
    stages = envelope.get('stages') if isinstance(envelope.get('stages'), dict) else {}
    stages = {k: v for k, v in stages.items() if isinstance(v, dict)}
    pinned = {}
    for stage in stages.values():
        if isinstance(stage.get('env'), dict):
            pinned.update({k: v for k, v in stage['env'].items() if isinstance(v, str)})
    return toolchain, stages, pinned


def find_node(env, toolchain):
    """(absolute node.exe, source). An envelope-pinned node_exe is the only acceptable one: never silently swap toolchains."""
    if toolchain.get('node_exe'):
        candidates = [('envelope', toolchain['node_exe'])]
    else:
        candidates = [('NODE_EXE', env.get('NODE_EXE')), ('PATH', which('node', env))]
        candidates += [('default', Path(env[k]) / 'nodejs/node.exe') for k in ('PROGRAMFILES', 'PROGRAMW6432') if env.get(k)]
    for source, path in candidates:
        if path and Path(path).is_absolute() and Path(path).is_file() and Path(path).name.lower() in ('node.exe', 'node'):
            return os.path.abspath(path), source
    return None, None


def map_script(command, node):
    """(sequence of argv lists, None) for a package.json script, or (None, reason). Tool paths stay package-relative."""
    if not isinstance(command, str) or not command.strip():
        return None, 'empty script'
    if SHELL.search(command):
        return None, 'shell syntax (pipes, redirection, variables or ; / ||) cannot run as fixed argv'
    sequence = []
    for part in command.split('&&'):
        try:
            words = shlex.split(part, posix=True)
        except ValueError:
            return None, 'unbalanced quotes'
        if not words:
            return None, 'empty command in an && sequence'
        head, args = words[0], words[1:]
        if re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', head):
            return None, 'sets environment inline (' + head.split('=', 1)[0] + ')'
        if head.lower() in UNMAPPABLE:
            return None, head + ' is a .cmd shim the contained runner cannot start; call node <script> instead'
        if head.lower() in ('node', 'node.exe'):
            sequence.append([node, *args])
        elif head in TOOLS:
            sequence.append([node, TOOLS[head], *args])
        else:
            return None, 'no node entry known for ' + head
    return sequence, None


def _inside(script):
    rel = PurePosixPath(str(script).replace('\\', '/'))
    return not rel.is_absolute() and '..' not in rel.parts and not re.match(r'[A-Za-z]:', str(script))


def _script_target(sequence):
    """The package-relative script file of a one-step 'node <script>' mapping, else None."""
    if sequence and len(sequence) == 1 and len(sequence[0]) >= 2:
        target = sequence[0][1]
        if (not target.startswith('-') and target.lower().endswith(SCRIPT_SUFFIXES) and target not in TOOLS.values()
                and _inside(target)):
            return PurePosixPath(target.replace('\\', '/')).as_posix()
    return None


def vitest_include(package):
    """{'path', 'include', 'exclude', 'source'} from vitest/vite config ``test`` block; Vitest's default otherwise."""
    for name in VITEST_CONFIGS:
        text = _text(package / name)
        if text is None:
            continue
        code = strip_comments(text)
        block = re.search(r'\btest\s*:\s*\{', code)
        if not block:
            return {'path': name, 'include': list(DEFAULT_TEST_GLOBS), 'exclude': [], 'source': 'default'}
        depth = 0; end = len(code)
        for i in range(block.end() - 1, len(code)):
            depth += code[i] == '{'; depth -= code[i] == '}'
            if depth == 0:
                end = i; break
        body = code[block.end():end]
        lists = {}
        for key in ('include', 'exclude'):
            found = re.search(r'\b' + key + r'\s*:\s*\[([^\]]*)\]', body)
            lists[key] = [m[2] for m in re.finditer(r'([\'"`])([^\'"`\n]{1,300})\1', found[1])] if found else None
        if lists['include']:
            return {'path': name, 'include': lists['include'], 'exclude': lists['exclude'] or [], 'source': 'config'}
        return {'path': name, 'include': list(DEFAULT_TEST_GLOBS), 'exclude': lists['exclude'] or [], 'source': 'default'}
    return {'path': None, 'include': list(DEFAULT_TEST_GLOBS), 'exclude': [], 'source': 'default'}


def manifest(package):
    value = _json(package / 'manifest.json')
    if value is None:
        return None
    version = value.get('manifest_version')
    return {'path': 'manifest.json', 'name': value.get('name') if isinstance(value.get('name'), str) else None,
            'version': value.get('version') if isinstance(value.get('version'), str) else None,
            'manifest_version': version if isinstance(version, int) else None, 'mv3': version == 3}


def e2e_contract(package, script):
    """Facts of an e2e harness script: does it print the 'N/M checks passed' summary, and is it mock or live."""
    path = package / script if _inside(script) else None
    text = _text(path) if path and path.is_file() else None
    if text is None:
        return {'script': script, 'exists': bool(path and path.is_file()), 'contract': False, 'mode': None, 'signals': [],
                'env': [], 'env_defaults': {}, 'sha256': None}
    code = strip_comments(text)
    signals = sorted(name for name, pattern in LIVE.items() if pattern.search(code))
    return {'script': script, 'exists': True, 'contract': bool(SUMMARY.search(code)), 'mode': 'live' if signals else 'mock',
            'signals': signals, 'env': sorted({a or b for a, b in ENV_READ.findall(code)}),
            'env_defaults': dict(sorted(ENV_DEFAULT.findall(code))), 'sha256': _file_hash(path)}


def _e2e_candidates(package, scripts):
    named = {}
    for name, info in sorted(scripts.items()):
        target = info['target']
        if name.startswith('e2e') and target:
            named.setdefault(target, []).append(name)
    found = set(named)
    try:
        for child in sorted((package / 'e2e').iterdir()):
            if child.is_file() and child.name.lower().endswith(SCRIPT_SUFFIXES) and not child.name.startswith('_'):
                found.add('e2e/' + child.name)
    except OSError:
        pass
    return named, sorted(found)[:MAX_E2E_SCRIPTS]


def describe(project, root, node, problems, envelope_stages):
    package = project / root
    data = _json(package / 'package.json') or {}
    raw = data.get('scripts') if isinstance(data.get('scripts'), dict) else {}
    scripts = {}
    for name, command in sorted(raw.items()):
        sequence, reason = map_script(command, node or 'node.exe')
        scripts[name] = {'command': command if isinstance(command, str) else None, 'argv': sequence, 'reason': reason,
                         'target': _script_target(sequence)}
        if (name == 'build' or name.startswith('build:')) and sequence is None:
            problems.append(_problem('build_script_unmappable', root + ' script ' + name + ': ' + reason))
    modules = package / 'node_modules'
    tools = {k: os.path.abspath(package / v) if (package / v).is_file() else None for k, v in TOOLS.items()}
    if not modules.is_dir():
        problems.append(_problem('node_modules_missing', root + '/node_modules is missing; install dependencies there (npm ci).'))
    else:
        if not tools['tsc']:
            problems.append(_problem('typescript_missing', root + '/' + TOOLS['tsc'] + ' is missing.'))
        if not tools['vitest']:
            problems.append(_problem('vitest_missing', root + '/' + TOOLS['vitest'] + ' is missing.'))
        if not (package / LOCK).is_file():
            problems.append(_problem('lock_manifest_missing', root + '/' + LOCK + ' is missing; the dependency tree cannot be pinned.'))
    build = {name: info['target'] for name, info in scripts.items() if name == 'build' or name.startswith('build:')}
    for name, target in build.items():
        if target and not (package / target).is_file():
            problems.append(_problem('build_script_unmappable', root + ' script ' + name + ': ' + target + ' does not exist.'))
    named, candidates = _e2e_candidates(package, scripts)
    e2e = []
    for script in candidates:
        fact = e2e_contract(package, script)
        fact['npm_scripts'] = named.get(script, [])
        if fact['contract']:
            e2e.append(fact)
        elif fact['npm_scripts']:
            problems.append(_problem('e2e_contract_missing', root + '/' + script + ' (' + ', '.join(fact['npm_scripts']) + ') '
                                     + ('never prints an "N/M checks passed" summary' if fact['exists'] else 'does not exist')))
    stages = check_stages(package, root, envelope_stages or {}, problems)
    include = vitest_include(package)
    try:
        tests = test_files(package_files(package), include['include']); walked = None
    except LedgerError as error:
        tests = []; walked = str(error)
    return {'root': root, 'name': data.get('name') if isinstance(data.get('name'), str) else None,
            'type': data.get('type') if isinstance(data.get('type'), str) else None, 'scripts': scripts,
            'node_modules': modules.is_dir(), 'tools': tools, 'lock_manifest': (package / LOCK).is_file(),
            'manifest': manifest(package), 'tsconfig': tsconfig(package), 'vitest': include,
            'tests': tests[:MAX_TESTS], 'tests_total': len(tests), 'tests_unavailable': walked, 'build_scripts': build,
            'e2e': e2e, 'stages': stages}


def check_stages(package, root, stages, problems):
    """Envelope-pinned build/e2e scripts: present, mapped, honouring the e2e contract and mode, and matching pinned hashes."""
    facts = {}
    for name in ('build', 'e2e_mock', 'e2e_live'):
        stage = stages.get(name)
        if not stage:
            continue
        for key in ('script', 'build_script'):
            script = stage.get(key)
            if not isinstance(script, str):
                continue
            exists = _inside(script) and (package / script).is_file()
            if key == 'build_script' or name == 'build':
                if not exists or not script.lower().endswith(SCRIPT_SUFFIXES):
                    problems.append(_problem('build_script_unmappable', root + ' stage ' + name + ': ' + script
                                             + ' is not a node script file in the package.'))
                facts[name + '.' + key] = {'script': script, 'exists': exists}
                continue
            fact = e2e_contract(package, script)
            facts[name + '.' + key] = fact
            want = 'mock' if name == 'e2e_mock' else 'live'
            if not fact['contract']:
                problems.append(_problem('e2e_contract_missing', root + ' stage ' + name + ': ' + script
                                         + (' never prints an "N/M checks passed" summary' if fact['exists'] else ' does not exist')))
            elif fact['mode'] != want:
                problems.append(_problem('e2e_contract_missing', root + ' stage ' + name + ': ' + script + ' is a ' + fact['mode']
                                         + ' harness (' + (', '.join(fact['signals']) or 'no live signal') + '), not ' + want))
            pinned = stage.get('script_sha256')
            if isinstance(pinned, str) and fact['sha256'] and pinned.lower() != fact['sha256']:
                problems.append(_problem('harness_sha_mismatch', root + ' stage ' + name + ': ' + script + ' changed since approval.'))
    return facts


def _first_file(candidates):
    for source, path in candidates:
        if path and Path(path).is_file():
            return os.path.abspath(path), source
    return None, None


def browser_and_backend(project, packages, env, pinned, problems):
    """Chrome and the backend python the e2e harnesses start; relative values resolve against the package, as they do."""
    e2e = [(p, fact) for p in packages for fact in p['e2e']] + [
        (p, fact) for p in packages for fact in p['stages'].values() if 'contract' in fact and fact['exists']]
    if not e2e:
        return {'chrome': None, 'chrome_source': None, 'backend_python': None, 'backend_python_source': None, 'backend_dir': None}
    root = e2e[0][0]['root']
    relative = lambda value: Path(value) if Path(value).is_absolute() else project / root / value
    defaults = {}
    for _, fact in e2e:
        for key, value in fact['env_defaults'].items():
            defaults.setdefault(key, value)
    located = lambda key: relative(defaults[key]) if key in defaults else None

    # An envelope-pinned value is the only acceptable one: an approved harness never silently uses another browser or venv.
    pick = lambda key, rest: [('envelope', relative(pinned[key]))] if pinned.get(key) else rest
    chrome = pick('CHROME_PATH', [('CHROME_PATH', env.get('CHROME_PATH')), ('script_default', located('CHROME_PATH'))]
                  + [('default', Path(env[k]) / 'Google/Chrome/Application/chrome.exe')
                     for k in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA') if env.get(k)])
    chrome, chrome_source = _first_file(chrome)
    if not chrome:
        problems.append(_problem('chrome_missing', 'No chrome.exe for the e2e harnesses; tried the envelope CHROME_PATH, CHROME_PATH, '
                                 'the harness default and the standard install locations.'))
    python = pick('NA_PYTHON', [('NA_PYTHON', relative(env['NA_PYTHON']) if env.get('NA_PYTHON') else None),
                                ('script_default', located('NA_PYTHON'))])
    python, python_source = _first_file(python)
    if any('NA_PYTHON' in fact['env'] for _, fact in e2e) and not python:
        problems.append(_problem('backend_venv_missing', 'The e2e harness starts the backend with NA_PYTHON, but no python.exe was found '
                                 '(envelope, NA_PYTHON, harness default).'))
    backend = pinned.get('NA_BACKEND_DIR') or env.get('NA_BACKEND_DIR')
    backend = relative(backend) if backend else located('NA_BACKEND_DIR')
    return {'chrome': chrome, 'chrome_source': chrome_source, 'backend_python': python, 'backend_python_source': python_source,
            'backend_dir': os.path.abspath(backend) if backend and Path(backend).is_dir() else None}


def fingerprint(facts):
    """Content hash of node.exe, tsc, vitest.mjs, the build and e2e scripts and the installed dependency lock manifest."""
    paths = {'node': facts.get('node_exe')}
    for package in facts.get('packages', []):
        base = Path(facts['project']) / package['root']; prefix = package['root'] + ':'
        paths[prefix + 'tsc'] = package['tools']['tsc']; paths[prefix + 'vitest'] = package['tools']['vitest']
        paths[prefix + 'lock'] = base / LOCK
        for target in sorted({t for t in package['build_scripts'].values() if t}):
            paths[prefix + 'build:' + target] = base / target
        for fact in package['e2e']:
            paths[prefix + 'e2e:' + fact['script']] = base / fact['script']
        for key, fact in sorted(package['stages'].items()):
            if _inside(fact['script']):
                paths[prefix + 'stage:' + key] = base / fact['script']
    tools = {}
    for role, path in sorted(paths.items()):
        if path and Path(path).is_file():
            try:
                tools[role] = {'path': str(Path(path).resolve()), 'sha256': _file_hash(path)}
            except OSError:
                continue
    return content_hash(tools)


def discover(project, roots, env=None, envelope=None):
    project = Path(project)
    if not project.is_dir():
        raise LedgerError('Project directory unavailable: ' + str(project))
    if not isinstance(roots, (list, tuple)):
        raise LedgerError('Source roots must be a list of project-relative paths.')
    env = _environ(env)
    toolchain, stages, pinned = _envelope(envelope)
    problems = []; found = []
    for root in roots:
        rel = _rel(root, 'Source root')
        if not (project / rel).is_dir():
            problems.append(_problem('root_missing', 'Source root is not a directory: ' + rel)); continue
        found += [p for p in _packages(project, rel, PACKAGE_DEPTH) if p not in found]
    pinned_package = _rel(toolchain['package'], 'Toolchain package') if isinstance(toolchain.get('package'), str) else None
    if pinned_package:
        if pinned_package not in found:
            problems.append(_problem('package_missing', 'Envelope package has no package.json inside the source roots: ' + pinned_package))
        found = [p for p in found if p == pinned_package]
    elif not found:
        problems.append(_problem('package_missing', 'No package.json within depth ' + str(PACKAGE_DEPTH) + ' of source roots: '
                                 + ', '.join(map(str, roots))))
    node, node_source = find_node(env, toolchain)
    if not node:
        problems.append(_problem('node_missing', 'No node.exe; tried the envelope node_exe, NODE_EXE, node on PATH and the default install.'))
    target = pinned_package or (found[0] if len(found) == 1 else None)
    packages = [describe(project, root, node, problems, stages if root == target else None) for root in sorted(found)]
    facts = {'version': 1, 'kind': 'node_extension', 'project': str(project.resolve()), 'node_exe': node, 'node_source': node_source,
             'package': target, 'packages': packages}
    facts.update(browser_and_backend(project, packages, env, pinned, problems))
    return {'facts': facts, 'problems': problems, 'fingerprint': fingerprint(facts)}
