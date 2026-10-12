"""Static import graph of a Node/TypeScript package: which test files reach which modules. Read-only, no execution.

Covers import/export-from, side-effect imports, dynamic import(), require() and vi.mock/importActual of
.ts/.tsx/.mts/.cts/.js/.jsx/.mjs/.cjs files; relative, package-root ('/x'), tsconfig ``paths`` and ``baseUrl`` specifiers;
'./x.js' written for './x.ts'; directory index files; Vite query suffixes ('?raw', '?url') are stripped. Bare package
specifiers are external and ignored. Ordering is deterministic (import distance, then path).
"""
import json
import os
from pathlib import Path
import posixpath
import re

from .ledger import LedgerError
from .node_change import GENERATED_DIR

CODE_SUFFIXES = ('.ts', '.tsx', '.mts', '.cts', '.js', '.jsx', '.mjs', '.cjs')
RESOLVE_SUFFIXES = CODE_SUFFIXES + ('.d.ts', '.json')
TS_FOR_JS = {'.js': ('.ts', '.tsx'), '.jsx': ('.tsx',), '.mjs': ('.mts',), '.cjs': ('.cts',)}
DEFAULT_TEST_GLOBS = ('**/*.{test,spec}.?(c|m)[jt]s?(x)',)  # Vitest's default include
MAX_FILES = 20000
MAX_FILE_BYTES = 2_000_000
MAX_TOTAL_BYTES = 128_000_000
MAX_TSCONFIG_DEPTH = 5

# Comments are blanked, string literals kept (they hold the specifiers). Regex literals are not tokenized: a quote
# inside one can at worst swallow the rest of that line.
TOKENS = re.compile(r'//[^\n]*|/\*.*?(?:\*/|\Z)|\'(?:\\.|[^\'\\\n])*\'?|"(?:\\.|[^"\\\n])*"?|`(?:\\.|[^`\\])*`?', re.S)
STATIC = re.compile(r'''\b(?:import|export)\b[^;'"`]*?\bfrom\s*(['"])([^'"\n]{1,400})\1|\bimport\s*(['"])([^'"\n]{1,400})\3''')
CALL = re.compile(r'''\b(?:import|require|(?:vi|vitest|jest)\s*\.\s*(?:mock|doMock|unmock|importActual|importMock|requireActual))'''
                  r'''\s*\(\s*(['"`])([^'"`\n$]{1,400})\1\s*[,)]''')


def strip_comments(text):
    return TOKENS.sub(lambda m: m[0] if m[0][0] in '\'"`' else ' ', text)


def specifiers(text):
    """Module specifiers a JS/TS source imports (static forms first), without duplicates."""
    code = strip_comments(text)
    found = [m[2] or m[4] for m in STATIC.finditer(code)] + [m[2] for m in CALL.finditer(code)]
    return list(dict.fromkeys(s for s in found if s))


def read_jsonc(path):
    """JSON with comments and trailing commas (tsconfig.json); None when absent or unreadable."""
    try:
        text = Path(path).read_text(encoding='utf-8-sig')
    except OSError:
        return None
    text = re.sub(r',(\s*[}\]])', r'\1', strip_comments(text))
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _inside(rel):
    return rel not in ('', '.') and not rel.startswith(('../', '/')) and rel != '..'


def tsconfig(package_dir, name='tsconfig.json'):
    """{'path', 'base_url', 'paths_base', 'paths', 'include'} from a package tsconfig and its relative ``extends`` chain.

    Paths are package-relative POSIX; ``paths_base`` is where ``paths`` targets resolve (baseUrl, else the defining file).
    """
    package = Path(package_dir)
    result = {'path': None, 'base_url': None, 'paths_base': None, 'paths': {}, 'include': None}
    chain = []; rel = name
    while rel and len(chain) < MAX_TSCONFIG_DEPTH:
        if not _inside(rel) or rel in [c[0] for c in chain]:
            break
        value = read_jsonc(package / rel)
        if value is None:
            break
        chain.append((rel, value))
        parent = value.get('extends')
        if not isinstance(parent, str) or not parent.startswith('.'):
            break
        rel = posixpath.normpath(posixpath.join(posixpath.dirname(rel), parent))
        if not rel.endswith('.json'):
            rel += '.json'
    if not chain:
        return None
    result['path'] = chain[0][0]
    for rel, value in reversed(chain):  # the extending file wins
        here = posixpath.dirname(rel)
        options = value.get('compilerOptions') if isinstance(value.get('compilerOptions'), dict) else {}
        if isinstance(options.get('baseUrl'), str):
            result['base_url'] = posixpath.normpath(posixpath.join(here, options['baseUrl']))
        if isinstance(options.get('paths'), dict):
            result['paths'] = {k: [t for t in v if isinstance(t, str)] for k, v in options['paths'].items()
                               if isinstance(k, str) and isinstance(v, list)}
            result['paths_base'] = here
        if isinstance(value.get('include'), list):
            result['include'] = [i for i in value['include'] if isinstance(i, str)]
    if result['base_url'] is not None:
        result['paths_base'] = result['base_url']
    return result


def _aliases(spec, config):
    if not config:
        return []
    found = []; best = None
    for pattern, targets in config['paths'].items():
        prefix, star, suffix = pattern.partition('*')
        if not star:
            if spec == pattern and (best is None or len(prefix) > best[0]):
                best = (len(prefix), targets, '')
        elif spec.startswith(prefix) and spec.endswith(suffix) and len(spec) >= len(prefix) + len(suffix):
            if best is None or len(prefix) > best[0]:
                best = (len(prefix), targets, spec[len(prefix):len(spec) - len(suffix)])
    if best:
        base = config['paths_base'] or ''
        found += [posixpath.normpath(posixpath.join(base, t.replace('*', best[2], 1))) for t in best[1]]
    if config['base_url'] is not None:
        found.append(posixpath.normpath(posixpath.join(config['base_url'], spec)))
    return found


def package_files(package_dir, max_files=None):
    """Package-relative POSIX paths of all files, skipping dot, generated (node_change.GENERATED_DIR) and linked dirs."""
    package = Path(package_dir); limit = max_files or MAX_FILES; files = []
    for directory, dirs, names in os.walk(package, followlinks=False):
        base = Path(directory)
        dirs[:] = sorted(d for d in dirs if not (d.startswith('.') or GENERATED_DIR.search(d) or (base / d).is_symlink()
                                                 or (hasattr(base / d, 'is_junction') and (base / d).is_junction())))
        for name in sorted(names):
            files.append((base / name).relative_to(package).as_posix())
            if len(files) > limit:
                raise LedgerError('Package has more than ' + str(limit) + ' files.')
    return frozenset(files)


class Graph:
    """Forward import edges between files of one package (package-relative POSIX paths).

    ``skipped``: code files over the size bound (no outgoing edges); ``unresolved``/``outside``: relative specifiers that
    match no file / leave the package, per importer."""

    def __init__(self, package_dir, max_files=None, max_file_bytes=None, max_total_bytes=None):
        self.package = Path(package_dir)
        if not self.package.is_dir():
            raise LedgerError('Package directory unavailable: ' + str(package_dir))
        self.max_files = max_files or MAX_FILES
        self.max_file_bytes = max_file_bytes or MAX_FILE_BYTES
        self.max_total_bytes = max_total_bytes or MAX_TOTAL_BYTES
        self.files = package_files(self.package, self.max_files)
        self.lower = {f.lower(): f for f in self.files}
        self.config = tsconfig(self.package)
        self.skipped = []; self.unresolved = {}; self.outside = {}; self.edges = {}; total = 0
        for rel in self.files:
            if not rel.endswith(CODE_SUFFIXES):
                continue
            path = self.package / rel
            size = path.stat().st_size
            if size > self.max_file_bytes:
                self.skipped.append(rel); continue
            total += size
            if total > self.max_total_bytes:
                raise LedgerError('Import graph sources exceed ' + str(self.max_total_bytes) + ' bytes.')
            text = path.read_text(encoding='utf-8', errors='replace')
            targets = set()
            for spec in specifiers(text):
                target = self.resolve(spec, rel)
                if target:
                    targets.add(target)
                elif spec.startswith('.'):
                    escapes = not _inside(posixpath.normpath(posixpath.join(posixpath.dirname(rel), spec.split('?', 1)[0])))
                    (self.outside if escapes else self.unresolved).setdefault(rel, []).append(spec)
            targets.discard(rel)
            self.edges[rel] = sorted(targets)

    def _file(self, base):
        if not _inside(base):
            return None
        candidates = [base]
        stem, ext = posixpath.splitext(base)
        candidates += [stem + alt for alt in TS_FOR_JS.get(ext, ())]
        candidates += [base + s for s in RESOLVE_SUFFIXES] + [base + '/index' + s for s in RESOLVE_SUFFIXES]
        for candidate in candidates:
            if candidate in self.files:
                return candidate
        for candidate in candidates:  # Windows resolves case-insensitively
            if candidate.lower() in self.lower:
                return self.lower[candidate.lower()]
        return None

    def resolve(self, spec, importer):
        spec = spec.split('?', 1)[0]
        if not spec or re.match(r'^[a-z][a-z0-9+.-]*:', spec, re.I):  # node:, data:, https:, virtual: ...
            return None
        if spec.startswith('./') or spec.startswith('../') or spec in ('.', '..'):
            return self._file(posixpath.normpath(posixpath.join(posixpath.dirname(importer), spec)))
        if spec.startswith('/'):
            return self._file(posixpath.normpath(spec.lstrip('/')))
        for base in _aliases(spec, self.config):
            found = self._file(base)
            if found:
                return found
        return None

    def distances(self, owned):
        """{file: hops to the nearest owned file} over reverse import edges; owned files are 0."""
        importers = {}
        for source, targets in self.edges.items():
            for target in targets:
                importers.setdefault(target, []).append(source)
        frontier = sorted(set(owned)); seen = {p: 0 for p in frontier}; depth = 0
        while frontier:
            depth += 1; following = set()
            for item in frontier:
                for source in importers.get(item, ()):
                    if source not in seen:
                        seen[source] = depth; following.add(source)
            frontier = sorted(following)
        return seen


def glob_regex(pattern):
    """Regex for a package-relative test glob: **, *, ?, [..], {a,b} and the extglobs ?() *() +() @() !()."""
    pattern = pattern[2:] if pattern.startswith('./') else pattern
    return re.compile('(?:' + '|'.join(_glob(p) for p in _braces(pattern)) + r')\Z')


def _braces(pattern, limit=64):
    match = re.search(r'\{([^{}]*)\}', pattern)
    if not match:
        return [pattern]
    result = []
    for option in match[1].split(','):
        result += _braces(pattern[:match.start()] + option + pattern[match.end():], limit)
        if len(result) > limit:
            raise LedgerError('Test glob expands to too many patterns: ' + pattern)
    return result


def _glob(pattern):
    out = []; i = 0; n = len(pattern)
    while i < n:
        c = pattern[i]
        if c in '?*+@!' and i + 1 < n and pattern[i + 1] == '(':
            depth = 0; j = i + 1
            while j < n:
                depth += pattern[j] == '('; depth -= pattern[j] == ')'
                if depth == 0:
                    break
                j += 1
            inner = '|'.join(_glob(part) for part in pattern[i + 2:j].split('|'))
            out.append({'?': '(?:%s)?', '*': '(?:%s)*', '+': '(?:%s)+', '@': '(?:%s)', '!': '(?!(?:%s))[^/]*'}[c] % inner)
            i = j + 1; continue
        if pattern.startswith('**/', i):
            out.append('(?:.*/)?'); i += 3; continue
        if pattern.startswith('**', i):
            out.append('.*'); i += 2; continue
        if c == '*':
            out.append('[^/]*')
        elif c == '?':
            out.append('[^/]')
        elif c == '[':
            j = pattern.find(']', i + 2)
            if j < 0:
                out.append(r'\['); i += 1; continue
            body = pattern[i + 1:j]
            body = '^' + body[1:] if body.startswith('!') else body
            out.append('[' + body.replace('\\', '\\\\') + ']'); i = j + 1; continue
        else:
            out.append(re.escape(c))
        i += 1
    return ''.join(out)


def test_files(files, test_globs=None):
    """Sorted files matching the globs (Vitest's default include when none are given)."""
    patterns = [glob_regex(g) for g in (test_globs or DEFAULT_TEST_GLOBS)]
    return sorted(f for f in files if f.endswith(CODE_SUFFIXES) and any(p.match(f) for p in patterns))


def _owned(package, owned):
    result = set()
    for item in owned or ():
        path = Path(str(item))
        if path.is_absolute():
            try:
                path = path.resolve().relative_to(package.resolve())
            except ValueError:
                continue
        rel = posixpath.normpath(path.as_posix())
        if _inside(rel):
            result.add(rel)
    return result


def affected_tests(package_dir, owned, test_globs=None, limit=None, graph=None):
    """Test files that transitively import any owned module, nearest first (import distance, then path).

    ``owned``: package-relative or absolute paths inside the package (others are ignored). Owned test files are not
    returned (they are the slice's own tests, never read-only regression tests). ``limit`` keeps the first N.
    """
    graph = graph or Graph(package_dir)
    targets = _owned(graph.package, owned)
    distance = graph.distances(targets)
    ranked = sorted((distance[t], t) for t in test_files(graph.files, test_globs) if t in distance and t not in targets)
    tests = [t for _, t in ranked]
    return tests[:limit] if limit is not None else tests
