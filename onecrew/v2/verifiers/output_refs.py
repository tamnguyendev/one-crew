"""Generic declared-output and source-reference check for a produced candidate (round 10).

A node declares what it writes. A node that writes a text report (`.md`, `.txt`, `.rst`) usually cites the repository as
`path:line`. The contract's own milestone commands may read none of that, so the engine itself owes two structural facts:

1. the node's outputs are what its artifact declared (rule and caller: common_verification.output_expectations / output_check);
2. every source reference in a written text report resolves against the candidate tree at the pinned revision.

This is a STRUCTURAL check only. Passing it is never evidence that a finding is true or that the cited line says what the report
claims; the reviewer milestone (M2) remains the semantic gate. It does not repair, guess or map anything.

Reference grammar (strict; anything else that looks like a reference is `unverifiable`, never a silent pass):

    ref      := path ':' item (',' [spaces] item)*        (each item is checked on its own)
    item     := line [ ('-' | en-dash) line ]
    path     := [drive ':'] segment ('/' segment)* ['.' extension]    (extension starts with a letter, 1-10 letters/digits)
                (R12: any segment, the last one included, may be a hidden name: one leading '.', see "R12 hidden files" below)
    line     := decimal digits (no sign, no 'L' prefix)
    boundary := after the ref the next character is not a word character, not '.' or ',' followed by a digit, not a dash followed
                by a letter or digit, and not ':' followed by a non-space (so `a.cs:3-5:extra` and `a.cs:3:7` are unverifiable)

A text "looks like a reference" when a path is followed immediately by ':' and then a digit, '-digit', 'L'+digit or 'line'.

R11 extensionless names. `Dockerfile:999999` has no dotted extension; before R11 it was not even scanned, so a report could cite a
file that does not exist and pass. The LAST segment of a path decides its family:
  * dotted with a letter extension (`a.cs`, `CMakeLists.txt`) -> a reference, as before;
  * dotted with a non-letter extension (`127.0.0.1`, `nginx-1.2`) -> not a file reference (addresses, versions); never counted;
  * no dot at all (`Dockerfile`, `src/Dockerfile`, `Note`, `localhost`, `nginx`, `12`) -> AMBIGUOUS. Prose (`Note:3`), host:port
    (`localhost:8080`), image tags (`nginx:1.25`, `library/nginx:1.25`), times and ratios (`12:30`, `16:9`) have exactly this shape,
    so the shape alone cannot decide. An ambiguous token IS a reference (then judged like any other: resolved, `unresolvable` or
    `unverifiable`; an offender unless it resolves) when ANY of these holds against the candidate tree:
      - the path is a file of the tree;
      - its last segment is a well-known extensionless repository file name (KNOWN_EXTENSIONLESS: Dockerfile, Makefile, LICENSE, ...),
        case-sensitive, wherever it is cited (so `Dockerfile:999999` with no such file in the tree is `unresolvable`);
      - it contains a path separator and its first segment is a top-level directory of the tree (`src/Gonefile:3`): a path anchored
        in the repository that does not exist is a wrong citation, not prose;
      - it has no separator and equals the basename of a tree file (`gradlew:3` when only `tools/gradlew` exists): a bare basename,
        `unresolvable` exactly like `publish.yml:32`.
    Otherwise it is not a reference and not an offender; it is only counted in `ignored` (count and first examples) so the decision
    stays visible. Justification: every rule that promotes a token is anchored in the candidate tree or in a closed list of generic
    build/legal file names, so ordinary prose can never fail a report while a citation of a repository file can never silently pass.
    Residual: an extensionless citation that is neither in the closed list nor anchored in the tree (`Gonefile:3` with no such
    basename and no separator) is ignored; the reviewer milestone remains the semantic gate for that.

R12 hidden files and directories (Codex P1-C). Before R12 a last segment could not start with '.', so `.gitignore:999999` was never
scanned (total=0, ignored=0) and a report citing a line beyond EOF passed. A segment of the HIDDEN shape is exactly one leading '.'
followed by an ASCII letter or '_' and then the ordinary segment characters (`.gitignore`, `.editorconfig`, `.env`, `.github`,
`.husky`, `.env.example`, `.eslintrc.json`). That is the shape of a repository hidden file or directory; the rule is general, there
is no name list. For a dot-leading LAST segment the leading dot is NOT a dotted extension (`.gitignore` has no extension in the R11
sense); the family is decided by the rest after that dot:
  * rest starts with a lowercase letter or '_' and has no further dot (`.gitignore`, `.env`, `.tool-versions`) -> a reference;
  * rest starts with a lowercase letter or '_' and has further dots -> R11's dotted rule applied to the rest: a letter extension
    (`.env.example`, `.eslintrc.json`, `.env.local`) is a reference, and the host-extension exemption does NOT apply (a host name
    never starts with '.'); a non-letter or empty extension (`.v1.2`, `.gitignore.`) is not a file reference;
  * rest starts with an UPPERCASE letter (`.NET:8`, `.DS_Store:1`) -> AMBIGUOUS and judged by R11's tree anchoring above (a product
    name in prose has this shape; repository hidden files are conventionally lowercase);
  * rest starts with anything else (`.5:1` decimal or ratio, `..`/`...` ellipses, `.-x`, `.:3`) -> not a reference, never counted.
A path whose DIRECTORY segments include a lowercase hidden segment (`.husky/pre-commit:2`, `.circleci/config:3`) is a reference even
when its last segment alone would be ambiguous: prose, URLs (removed first), host:port, image tags, times and ratios never contain
`.name/`. Every such reference is then resolved exactly like any other: full path from the repository root in the candidate tree,
line/range within the file; a bare hidden name that is not a top-level file (`.env.example:3` when only `src/.env.example` exists)
is `bare_basename`, a missing file is `unresolvable` (never "nothing to check"), a malformed tail is `unverifiable`.
Still not references: `e.g.:1`, `i.e.:2`, `etc.:3`, `Wait...:3` (a dotted name with an empty extension), `1.5:1`, `v1.2:3`.
Residual false positives (fail-closed): a lowercase dot word glued to ':digit' in prose (`.local:8080`, `.io:3`) is judged as a hidden
file and fails unless the tree has it. Residual false negatives: an uppercase hidden name not anchored in the tree (`.Rprofile:2`
with no such file) and a hidden name starting with a digit (`.1password:1`) are not counted (the uppercase one is listed in
`ignored`); the reviewer milestone remains the semantic gate for those.
Resolution against the candidate tree (case-sensitive, full path from the repository root):
  * the path must be a file of the tree; a path with no '/' is accepted only when it is exactly a top-level file of the tree.
    A bare basename (`publish.yml:32`) that is not a top-level file is `unresolvable`; it is never mapped to a file elsewhere;
  * line >= 1 and <= the file's line count (count of b'\\n', a trailing partial line counts as a line);
  * a range must be ordered (start <= end) and its end within the file.
Not references (never counted): URLs (`scheme://...`), host:port tokens (`example.com:443`, `localhost:8080`, `127.0.0.1:5000`),
the ambiguous extensionless tokens above that no rule promotes (`Note:3`, `12:30`, `image: nginx:1.25`), Windows drive paths without
a line part (`C:\\Users\\x`), paths that are outputs of the node
itself (counted only as `skipped_outputs`), and everything inside a fenced code block whose info string is `text`, `log`,
`console` or `output` (other fenced blocks, and inline code, are scanned).
A backslash path (`src\\a.cs:3`) is `unverifiable`: references are POSIX paths from the repository root.
"""
import re
from collections import namedtuple

TEXT_SUFFIXES = ('.md', '.txt', '.rst')
SKIP_FENCES = {'text', 'log', 'console', 'output'}
HOST_EXTENSIONS = {'com', 'org', 'net', 'io', 'dev', 'local', 'edu', 'gov', 'info', 'app'}
# R11: well-known extensionless repository files (a closed list of generic build/legal/metadata names; nothing project specific).
KNOWN_EXTENSIONLESS = frozenset({
    'Dockerfile', 'Containerfile', 'Makefile', 'makefile', 'GNUmakefile', 'Jenkinsfile', 'Vagrantfile', 'Procfile', 'Gemfile',
    'Rakefile', 'Podfile', 'Brewfile', 'Pipfile', 'Justfile', 'justfile', 'Caddyfile', 'Tiltfile', 'Earthfile', 'Snakefile',
    'Berksfile', 'Guardfile', 'Fastfile', 'Appfile', 'Dangerfile', 'Cakefile', 'BUILD', 'WORKSPACE', 'CODEOWNERS', 'OWNERS',
    'LICENSE', 'LICENCE', 'COPYING', 'NOTICE', 'AUTHORS', 'CONTRIBUTORS', 'CHANGELOG', 'CHANGES', 'README', 'VERSION', 'MANIFEST',
    'PKGBUILD', 'APKBUILD', 'Kconfig', 'Kbuild', 'configure', 'gradlew', 'mvnw'})
_EXTENSION = re.compile(r'[A-Za-z][A-Za-z0-9]{0,9}')
_SEPARATORS = re.compile(r'[/\\]')

# kind: 'ref' | 'unverifiable', or 'ref?' | 'unverifiable?' for an ambiguous extensionless token (check() decides it); line = 1-based line of the report that holds it
Ref = namedtuple('Ref', 'path start end raw line kind reason')

_URL = re.compile(r'[A-Za-z][A-Za-z0-9+.-]*://\S+')
_CANDIDATE = re.compile(
    r'(?<![A-Za-z0-9_./\\@+~-])'
    r'(?P<path>(?:[A-Za-z]:)?(?:[A-Za-z0-9_.@+~\\-]+[/\\])*\.?[A-Za-z0-9_@+~-][A-Za-z0-9_.@+~-]*)'
    r':(?=-?\d|L\d|line)')
_ITEM = r'\d+(?:[-–]\d+)?'
_LINES = re.compile(r'(?P<list>' + _ITEM + r'(?:, *(?=\d)' + _ITEM + r')*)')
_FENCE = re.compile(r'^\s{0,3}(?P<mark>`{3,}|~{3,})\s*(?P<info>[^`\s]*)')
_DASHES = '-‐‑‒–—'
_HIDDEN = re.compile(r'\.[a-z_]')   # R12: a lowercase hidden file/directory segment (`.gitignore`, `.github`); prefix match


def is_text_report(path):
    return path.lower().endswith(TEXT_SUFFIXES)


def _tail_problem(line, end):
    nxt = line[end:end + 2]
    if not nxt: return None
    if nxt[0].isalnum() or nxt[0] == '_': return 'text continues after the line number'
    if nxt[0] in '.,' and len(nxt) > 1 and nxt[1].isdigit(): return 'a second number follows the line number'
    if nxt[0] in _DASHES and len(nxt) > 1 and nxt[1].isalnum(): return 'malformed line range'
    if nxt[0] == ':' and len(nxt) > 1 and not nxt[1].isspace(): return 'more fields follow the line number'
    return None


def _token_end(line, start):
    end = start
    while end < len(line) and not line[end].isspace(): end += 1
    return end


def scan(text):
    """Every reference-looking token of a text report, in order, as Ref tuples. Pure; no tree needed."""
    refs, fence = [], None   # fence = (mark, skipped)
    for number, raw_line in enumerate(text.splitlines(), 1):
        match = _FENCE.match(raw_line)
        if fence is not None and match and match.group('mark')[0] == fence[0][0] and len(match.group('mark')) >= len(fence[0]) and not match.group('info'):
            fence = None
            continue
        if fence is None and match:
            fence = (match.group('mark'), match.group('info').lower() in SKIP_FENCES)
            continue
        if fence is not None and fence[1]:
            continue
        line = _URL.sub(lambda m: ' ' * len(m.group(0)), raw_line)
        for found in _CANDIDATE.finditer(line):
            refs.extend(_one(found, line, number))
    return refs


def _one(found, line, number):
    path, where = found.group('path'), found.end()
    parts = _SEPARATORS.split(path)
    name = parts[-1]
    if name.startswith('.'):   # R12 hidden-name family (module docstring); the leading dot is not an extension
        rest = name[1:]
        if not (rest[:1].isascii() and (rest[:1].isalpha() or rest[:1] == '_')):
            return []   # `.5:1`, `.-x:3`: a decimal, a ratio or punctuation, not a file
        if '.' in rest and not _EXTENSION.fullmatch(rest.rsplit('.', 1)[1]):
            return []   # `.v1.2:3`, `.gitignore.:3`
        ambiguous = rest[0].isupper()   # `.NET:8`: R11 tree anchoring decides
    else:
        ambiguous = '.' not in name
        if not ambiguous:
            ext = name.rsplit('.', 1)[1]
            if not _EXTENSION.fullmatch(ext):
                return []   # `127.0.0.1:5000`, `nginx-1.2:3`: an address or a version, not a file
            if '/' not in path and '\\' not in path and ext.lower() in HOST_EXTENSIONS:
                return []   # host:port, not a source reference
    if ambiguous and any(_HIDDEN.match(part) for part in parts[:-1]):
        ambiguous = False   # `.husky/pre-commit:2`: a path through a hidden directory is a repository path, never prose
    mark = '?' if ambiguous else ''
    token = line[found.start():_token_end(line, where)]
    lines = _LINES.match(line, where)
    if not lines:
        return [Ref(path, 0, 0, token, number, 'unverifiable' + mark, 'line part is not decimal digits or a digits-digits range')]
    end = lines.end()
    problem = _tail_problem(line, end)
    if problem or '\\' in path:
        return [Ref(path, 0, 0, token, number, 'unverifiable' + mark, problem or 'backslash path; references are POSIX paths from the repository root')]
    result = []
    for item in lines.group('list').split(','):
        item = item.strip()
        first, _, last = item.replace('–', '-').partition('-')
        result.append(Ref(path, int(first), int(last or first), path + ':' + item, number, 'ref' + mark, ''))
    return result


def check(tree_files, refs, outputs):
    """Judge references against a tree. `tree_files` maps every file path of the candidate tree to its line count (or to a zero-argument
    callable returning it, evaluated only for files actually cited); `refs` are Ref tuples of one or more reports; `outputs` are this
    node's own output paths. Returns {'result': 'pass'|'fail', 'counts', 'reasons', 'offenders' (first five), 'offender_count',
    'ignored' {'count', 'examples'}}; `ignored` are ambiguous extensionless tokens that no rule of the module docstring promotes."""
    counts = {'total': 0, 'resolved': 0, 'unresolvable': 0, 'unverifiable': 0, 'skipped_outputs': 0}
    offenders, cache, mine = [], {}, set(outputs)
    reasons = {'bare_basename': 0, 'no_such_file': 0, 'line_outside_file': 0, 'unverifiable': 0}
    ignored = []
    top_dirs = {path.split('/', 1)[0] for path in tree_files if '/' in path}
    basenames = {path.rsplit('/', 1)[-1] for path in tree_files}

    def promoted(path):
        """R11: is an ambiguous extensionless token a reference? (rule in the module docstring)"""
        if path in tree_files: return True
        parts = _SEPARATORS.split(path)
        if parts[-1] in KNOWN_EXTENSIONLESS: return True
        if len(parts) > 1: return parts[0] in top_dirs
        return path in basenames

    def lines_of(path):
        if path not in cache:
            value = tree_files[path]
            cache[path] = value() if callable(value) else value
        return cache[path]

    for ref in refs:
        if ref.kind.endswith('?'):
            if not promoted(ref.path):
                ignored.append(ref.raw); continue
            ref = ref._replace(kind=ref.kind[:-1])
        if ref.path in mine:
            counts['skipped_outputs'] += 1
            continue
        counts['total'] += 1
        if ref.kind != 'ref':
            counts['unverifiable'] += 1; reasons['unverifiable'] += 1
            offenders.append(f'unverifiable {ref.raw} ({ref.reason})')
        elif ref.path not in tree_files:
            counts['unresolvable'] += 1; reasons['no_such_file' if '/' in ref.path else 'bare_basename'] += 1
            how = 'no such file in the candidate tree' if '/' in ref.path else 'bare basename is not a top-level file'
            offenders.append(f'unresolvable {ref.raw} ({how})')
        else:
            size = lines_of(ref.path)
            if ref.start < 1 or ref.end < ref.start or ref.end > size:
                counts['unresolvable'] += 1; reasons['line_outside_file'] += 1
                offenders.append(f'unresolvable {ref.raw} (line outside 1..{size})')
            else:
                counts['resolved'] += 1
    failed = counts['unresolvable'] or counts['unverifiable']
    return {'result': 'fail' if failed else 'pass', 'counts': counts, 'reasons': reasons, 'offenders': offenders[:5], 'offender_count': len(offenders),
            'ignored': {'count': len(ignored), 'examples': ignored[:5]}}
