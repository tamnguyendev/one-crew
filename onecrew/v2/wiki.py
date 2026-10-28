"""2.3-A1 — the wiki pages of a project read as sourced knowledge entries (docs/v23/HOP-DONG-2.3.vi.md §3).

A wiki is a folder of Markdown pages the project keeps (default `docs/wiki/` of the repository; `.onecrew/config.json` may name other
folders under `"wiki": {"paths": [...]}`, inside the repository or absolute). A page is cut into entries at its `##`/`###` headings. An
entry is typed only by a fenced block with the info string `onecrew` holding one JSON object:

    ## a.txt keeps one line
    ```onecrew
    {"id": "one-line", "kind": "constraint", "label": "verified", "must": true, "applies_to": ["a.txt"],
     "sources": [{"type": "file", "path": "a.txt", "revision": "<commit>"}]}
    ```
    Never split a.txt into two lines.

The heading and the prose (fence removed) are the entry text. A section without the block is an `unverified` note: delivered as a lead,
never as a fact. A `verified`/`refuted` label needs a checkable source (file, file_line, symbol, receipt or event); without one it is read
as `unverified` and the page gets a problem. Malformed metadata is a problem of that page, never a crash of the reader: the other entries
of the project still count. Pages are read from the working tree (what the next worker will see) and identified by the SHA-256 of their
bytes; the delivered text is sealed in the attempt receipt by the caller.

A reading limit never hides a mandatory section (Codex review P2-02): the first MAX_PAGES pages are read whole, every later page is
looked through for a section that declares `"must": true` or `"supersedes"` and only such a page is read (its mandatory and
superseding sections and what they derive from count, the rest is reported as not read). A section that declares itself mandatory but cannot be delivered (the page is too large or not UTF-8, the
metadata is invalid, the id repeats, the block is outside a section...) is listed as `undelivered`; past MAX_SCAN_BYTES nothing more is
looked through and the pages left are `unscanned`. knowledge.py holds the consumer such a constraint may concern before the model.

Nothing here decides permissions, applicability or relevance (knowledge.py does), and nothing here writes.
"""
import hashlib
import json
import re
from pathlib import Path

KINDS = ('decision', 'constraint', 'finding', 'lesson', 'rejected', 'note', 'summary')
LABELS = ('observed', 'hypothesis', 'verified', 'refuted', 'unverified')
STATUSES = ('active', 'superseded', 'withdrawn', 'archived')
SOURCE_TYPES = ('file', 'file_line', 'symbol', 'receipt', 'event', 'url')
CHECKABLE = ('file', 'file_line', 'symbol', 'receipt', 'event')
CONDITION_TYPES = ('file_contains', 'file_unchanged', 'env', 'text')
META_KEYS = {'id', 'kind', 'label', 'must', 'applies_to', 'sources', 'conditions', 'supersedes', 'derived_from', 'ledger_id', 'status', 'title'}
DEFAULT_PATHS = ('docs/wiki',)
MAX_PAGE_BYTES = 2_000_000
MAX_PAGES = 2000                                   # pages read whole; later pages are looked through for mandatory sections only
MAX_SCAN_BYTES = 256 * 1024 * 1024                 # bytes looked through per reading; past it the mandatory set is unknown
SCAN_CHUNK = 1 << 20
MUST_BYTES = re.compile(rb'"must"\s*:\s*true')
MUST_TEXT = re.compile(r'"must"\s*:\s*true')
SUPERSEDES_BYTES = re.compile(rb'"supersedes"\s*:')
HEADING = re.compile(r'^(#{2,3})\s+(.+?)\s*#*\s*$')
FENCE_OPEN = re.compile(r'^```onecrew\s*$')
IDENT = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$')
RESERVED = ('ctx-', 'lesson-')                     # ids of ledger subjects; a page may not take them (2.3 review r1 #9)
FULL_COMMIT = re.compile(r'^(?:[0-9a-f]{40}|[0-9a-f]{64})$')


def slug(text):
    """A stable ASCII id part from a heading: accents dropped (Vietnamese "Ghi chú về a.txt" -> "ghi-chu-ve-a-txt")."""
    import unicodedata
    text = unicodedata.normalize('NFKD', text.replace('đ', 'd').replace('Đ', 'D'))
    text = ''.join(c for c in text if not unicodedata.combining(c))
    value = re.sub(r'[^a-z0-9]+', '-', text.casefold()).strip('-')
    return value[:60] or 'section'


def _relpath(value):
    if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value): return None
    value = value.replace('\\', '/')
    if value.startswith('/') or re.match(r'^[A-Za-z]:', value) or '..' in value.split('/'): return None
    return value


def _source(value, problems, where):
    if not isinstance(value, dict) or value.get('type') not in SOURCE_TYPES:
        problems.append(f'{where}: a source is an object with type one of {", ".join(SOURCE_TYPES)}.'); return None
    kind = value['type']
    out = {'type': kind}
    if kind in ('file', 'file_line', 'symbol'):
        path = _relpath(value.get('path'))
        if path is None: problems.append(f'{where}: source path must be a path inside the repository.'); return None
        out['path'] = path
        for key in ('revision', 'blob'):
            if key in value:
                if not isinstance(value[key], str) or not re.fullmatch(r'[0-9A-Za-z_./^~-]{1,80}', value[key]):
                    problems.append(f'{where}: source {key} must be a commit-ish or a blob id.'); return None
                out[key] = value[key]
        if 'revision' in out and not FULL_COMMIT.match(out['revision']):
            problems.append(f'{where}: source revision {out["revision"][:40]!r} is not a commit id; a symbolic name always resolves to "now", '
                            f'so the entry cannot be rechecked (pin the full commit; it is delivered as unknown until then).')
        if kind == 'file_line':
            if type(value.get('line')) is not int or value['line'] < 1: problems.append(f'{where}: file_line needs a positive line.'); return None
            out['line'] = value['line']
        if kind == 'symbol':
            if not isinstance(value.get('name'), str) or not value['name'].strip(): problems.append(f'{where}: symbol needs a name.'); return None
            out['name'] = value['name']
    elif kind == 'receipt':
        if not isinstance(value.get('key'), str) or not value['key']: problems.append(f'{where}: receipt needs a key.'); return None
        out['key'] = value['key']
    elif kind == 'event':
        if type(value.get('id')) is not int or value['id'] < 1: problems.append(f'{where}: event needs a numeric id.'); return None
        out['id'] = value['id']
    else:
        if not isinstance(value.get('url'), str) or not value['url']: problems.append(f'{where}: url needs a url.'); return None
        out['url'] = value['url'][:500]
    return out


def _condition(value, problems, where):
    if isinstance(value, str):
        return {'type': 'text', 'text': value[:500]}
    if not isinstance(value, dict) or value.get('type') not in CONDITION_TYPES:
        problems.append(f'{where}: a condition is text or an object with type one of {", ".join(CONDITION_TYPES)}.'); return None
    kind = value['type']
    if kind in ('file_contains', 'file_unchanged'):
        path = _relpath(value.get('path'))
        if path is None: problems.append(f'{where}: condition path must be inside the repository.'); return None
        if kind == 'file_contains':
            if not isinstance(value.get('text'), str) or not value['text']: problems.append(f'{where}: file_contains needs text.'); return None
            return {'type': kind, 'path': path, 'text': value['text'][:500]}
        if not isinstance(value.get('sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}', value['sha256']):
            problems.append(f'{where}: file_unchanged needs the sha256 of the file.'); return None
        return {'type': kind, 'path': path, 'sha256': value['sha256']}
    if kind == 'env':
        if value.get('key') not in ('platform', 'python', 'provider', 'model') or not isinstance(value.get('value'), str):
            problems.append(f'{where}: env condition needs key platform|python|provider|model and a string value.'); return None
        return {'type': kind, 'key': value['key'], 'value': value['value'][:100]}
    if not isinstance(value.get('text'), str) or not value['text'].strip(): problems.append(f'{where}: text condition needs text.'); return None
    return {'type': 'text', 'text': value['text'][:500]}


def _strings(value, problems, where, name, check=None):
    if value is None: return []
    if isinstance(value, str): value = [value]
    if not isinstance(value, list) or len(value) > 40 or not all(isinstance(v, str) and v for v in value):
        problems.append(f'{where}: {name} must be a list of strings (at most 40).'); return []
    if check:
        out = []
        for item in value:
            checked = check(item)
            if checked is None: problems.append(f'{where}: {name} entry {item[:60]!r} is not valid.')
            else: out.append(checked)
        return out
    return list(value)


def _meta(raw, problems, where):
    try:
        value = json.loads(raw)
    except ValueError as error:
        problems.append(f'{where}: the onecrew block is not valid JSON ({str(error)[:80]}).'); return None
    if not isinstance(value, dict):
        problems.append(f'{where}: the onecrew block must be one JSON object.'); return None
    unknown = sorted(set(value) - META_KEYS)
    if unknown:
        problems.append(f'{where}: unknown metadata key(s) {", ".join(unknown)}.'); return None
    if 'id' in value and (not isinstance(value['id'], str) or not IDENT.match(value['id'])):
        problems.append(f'{where}: id must be 1-80 letters, digits, ".", "_" or "-".'); return None
    if isinstance(value.get('id'), str) and value['id'].startswith(RESERVED):
        problems.append(f'{where}: ids starting with {" or ".join(RESERVED)} belong to ledger subjects.'); return None
    for name in ('sources', 'conditions'):
        if value.get(name) is not None and not isinstance(value[name], list):
            problems.append(f'{where}: {name} must be a list.'); return None
    for name in ('applies_to', 'supersedes', 'derived_from'):
        if value.get(name) is not None and not isinstance(value[name], (list, str)):
            problems.append(f'{where}: {name} must be a list of strings.'); return None
    if value.get('kind', 'note') not in KINDS: problems.append(f'{where}: kind must be one of {", ".join(KINDS)}.'); return None
    if value.get('label', 'unverified') not in LABELS: problems.append(f'{where}: label must be one of {", ".join(LABELS)}.'); return None
    if value.get('status', 'active') not in STATUSES: problems.append(f'{where}: status must be one of {", ".join(STATUSES)}.'); return None
    if 'must' in value and type(value['must']) is not bool: problems.append(f'{where}: must is true or false.'); return None
    sources = []
    for item in value.get('sources') or []:
        source = _source(item, problems, where)
        if source is None: return None
        sources.append(source)
    conditions = []
    for item in value.get('conditions') or []:
        condition = _condition(item, problems, where)
        if condition is None: return None
        conditions.append(condition)
    meta = {'id': value.get('id'), 'kind': value.get('kind', 'note'), 'label': value.get('label', 'unverified'),
            'must': value.get('must', False), 'status': value.get('status', 'active'), 'sources': sources, 'conditions': conditions,
            'applies_to': _strings(value.get('applies_to'), problems, where, 'applies_to', _relpath_or_glob),
            'supersedes': _strings(value.get('supersedes'), problems, where, 'supersedes'),
            'derived_from': _strings(value.get('derived_from'), problems, where, 'derived_from'),
            'ledger_id': value.get('ledger_id') if isinstance(value.get('ledger_id'), str) else None,
            'title': value.get('title') if isinstance(value.get('title'), str) else None}
    if meta['label'] in ('verified', 'refuted') and not any(s['type'] in CHECKABLE for s in sources):
        problems.append(f'{where}: label {meta["label"]} needs a checkable source; read as unverified.')
        meta['label'] = 'unverified'
    return meta


def _relpath_or_glob(value):
    if '*' in value or '?' in value:
        cleaned = _relpath(value.replace('*', 'x').replace('?', 'x'))
        return value.replace('\\', '/') if cleaned else None
    return _relpath(value)


def declares_must(raw):
    """Whether the text of an onecrew block declares a mandatory section (also when it is not valid JSON)."""
    try:
        value = json.loads(raw)
    except ValueError:
        return bool(MUST_TEXT.search(raw))
    return value.get('must') is True if isinstance(value, dict) else bool(MUST_TEXT.search(raw))


def _declared(raw, line, reason):
    """What can be said of an undeliverable mandatory section: its line, id, applies_to and cited files when the block is readable JSON."""
    out = {'line': line, 'reason': reason[:200], 'id': None, 'applies_to': None, 'source_paths': None}
    try:
        value = json.loads(raw)
    except ValueError:
        return out
    if not isinstance(value, dict): return out
    if isinstance(value.get('id'), str): out['id'] = value['id'][:80]
    applies = value.get('applies_to')
    applies = [applies] if isinstance(applies, str) else applies
    if isinstance(applies, list) and all(isinstance(a, str) for a in applies):
        out['applies_to'] = [a.replace('\\', '/') for a in applies][:40]
    sources = value.get('sources')
    if isinstance(sources, list) and all(isinstance(s, dict) for s in sources):
        paths = [s['path'] for s in sources if 'path' in s]
        clean = [_relpath(p) for p in paths]
        if all(clean): out['source_paths'] = clean[:20]   # review r1 F3: an absolute or invalid path says nothing about permission
    return out


def parse(text, path, mandatory_only=False):
    """{'entries': [...], 'problems': [...], 'undelivered': [...]} of one page; `path` is how the page is named in the package
    (repo-relative or absolute). `undelivered`: every onecrew block of the page that declares `"must": true` and did not become a
    mandatory entry. `mandatory_only` (a page past the reading budget): only the mandatory entries are returned."""
    problems, entries, seen, delivered = [], [], {}, set()
    stem = slug(Path(str(path)).stem)
    lines = text.splitlines()
    sections, current = [], None
    for number, line in enumerate(lines, start=1):
        match = HEADING.match(line)
        if match:
            current = {'title': match.group(2).strip(), 'line': number, 'body': []}
            sections.append(current)
        elif current is not None:
            current['body'].append(line)
    for section in sections:
        where = f'{path}:{section["line"]}'
        try:
            _section(section, where, stem, seen, problems, entries, delivered)
        except Exception as error:                       # a section that breaks the parser is a page problem, never a crash of the reader
            problems.append(f'{where}: section not read ({type(error).__name__}: {str(error)[:120]}).')
    undelivered, number = [], 0
    while number < len(lines):                           # P2-02: every block that declares must and did not become a mandatory entry
        number += 1
        if not FENCE_OPEN.match(lines[number - 1]): continue
        start, raw = number, []
        while number < len(lines) and lines[number].strip() != '```':
            raw.append(lines[number]); number += 1
        raw = '\n'.join(raw)
        if start in delivered or not declares_must(raw): continue
        owner = max((s['line'] for s in sections if s['line'] < start), default=None)
        said = [q for q in problems if owner is not None and q.startswith(f'{path}:{owner}:')]
        reason = (said[-1].split(': ', 1)[-1] if said else 'outside a ## or ### section' if owner is None
                  else 'not the metadata block of its section')
        undelivered.append(_declared(raw, start, reason))
    skipped = 0
    if mandatory_only:                                   # a page past the reading budget: what can act on mandatory knowledge
        by_id, wanted = {e['id']: e for e in entries}, set()
        todo = [d for e in entries if e['must'] for d in e['derived_from']]
        while todo:                                      # review r2 R2-02: what a mandatory entry derives from, at any depth
            d = todo.pop()
            if d in wanted: continue
            wanted.add(d); todo += by_id[d]['derived_from'] if d in by_id else []
        kept = [e for e in entries if e['must'] or e['supersedes'] or e['id'] in wanted]
        skipped, entries = len(entries) - len(kept), kept
    return {'entries': entries, 'problems': problems, 'undelivered': undelivered, 'skipped': skipped}


def _section(section, where, stem, seen, problems, entries, delivered=None):
    body, meta_raw, i, fence_line = [], None, 0, None
    rows = section['body']
    while i < len(rows):
        if FENCE_OPEN.match(rows[i]) and meta_raw is None:
            j = i + 1
            fence_line = section['line'] + 1 + i
            while j < len(rows) and rows[j].strip() != '```': j += 1
            if j >= len(rows):
                problems.append(f'{where}: the onecrew block is not closed.'); meta_raw = ''
                i = len(rows); break
            meta_raw = '\n'.join(rows[i + 1:j]); i = j + 1; continue
        body.append(rows[i]); i += 1
    meta = _meta(meta_raw, problems, where) if meta_raw is not None else None
    typed = meta is not None
    meta = meta or {'id': None, 'kind': 'note', 'label': 'unverified', 'must': False, 'status': 'active', 'sources': [],
                    'conditions': [], 'applies_to': [], 'supersedes': [], 'derived_from': [], 'ledger_id': None, 'title': None}
    ident = meta['id'] or f'{stem}-{slug(section["title"])}'
    if ident in seen:
        problems.append(f'{where}: id {ident} repeats the section at line {seen[ident]}; this section is skipped.'); return
    seen[ident] = section['line']
    text_body = '\n'.join(body).strip()
    entries.append(dict(meta, id=ident, title=meta['title'] or section['title'], text=text_body, line=section['line'], typed=typed))
    if typed and meta['must'] and delivered is not None and fence_line is not None: delivered.add(fence_line)


def configured_paths(project, problems=None):
    """The wiki folders of a project: `.onecrew/config.json` "wiki": {"paths": [...]} when present, else docs/wiki. The file is read like
    the rest of OneCrew reads it (UTF-8 with or without a BOM); one that cannot be read, or a "wiki" value that is not a list of folder
    names, is a problem in `problems` (review r1 F2), never a silent fall back."""
    config = Path(project) / '.onecrew' / 'config.json'
    if not config.is_file(): return list(DEFAULT_PATHS)
    try:
        value = json.loads(config.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as error:
        if problems is not None:
            problems.append({'path': '.onecrew/config.json', 'problem': f'config.json cannot be read ({type(error).__name__}); the wiki folders it '
                                                                   f'may name are unknown, only {", ".join(DEFAULT_PATHS)} is read'})
        return list(DEFAULT_PATHS)
    if not isinstance(value, dict) or 'wiki' not in value: return list(DEFAULT_PATHS)
    paths = value['wiki'].get('paths') if isinstance(value['wiki'], dict) else None
    if isinstance(paths, list) and paths and all(isinstance(p, str) and p for p in paths):
        return list(paths)
    if problems is not None:
        problems.append({'path': '.onecrew/config.json', 'problem': f'"wiki" is not {{"paths": [folder, ...]}}; only {", ".join(DEFAULT_PATHS)} is read'})
    return list(DEFAULT_PATHS)


def _decode(data):
    """(text, None) of a UTF-8 page (a BOM is dropped: review r1 F15), else (None, reason)."""
    if b'\x00' in data: return None, 'not UTF-8 text (NUL bytes: UTF-16?)'   # review r2 R2-06: UTF-16 without a BOM is valid "UTF-8"
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        return None, 'not UTF-8 text'
    return (text[1:] if text.startswith('\ufeff') else text), None


def _declares_must_bytes(data):
    """Whether bytes that cannot be read as UTF-8 still declare a mandatory section: ASCII-compatible encodings, and UTF-16 (what Windows
    PowerShell 5.1 writes) in either byte order (review r1 F1)."""
    if MUST_BYTES.search(data): return True
    if b'\x00' in data[:4096]:
        for encoding in ('utf-16', 'utf-16-le', 'utf-16-be'):
            try:
                if MUST_TEXT.search(data.decode(encoding, 'ignore')): return True
            except LookupError:
                continue
    return False


def _scan_for_must(path):
    """Whether a file declares a mandatory section, read in chunks (a page too large to read whole is still looked through)."""
    tail = b''
    with open(path, 'rb') as handle:
        while True:
            chunk = handle.read(SCAN_CHUNK)              # an even size: UTF-16 code units stay aligned (review r2 R2-05)
            if not chunk: return False
            if _declares_must_bytes(tail + chunk): return True
            tail = chunk[-128:]


def pages(project, paths=None, coverage=None):
    """The wiki pages to parse: [{'path', 'origin', 'sha256', 'bytes', 'text'[, 'mandatory_only']}] plus problems; the default folder
    missing is no wiki, not an error; a configured folder missing is a problem (review r1 F2). `coverage` (a dict, optional) receives
    what was not read: {'pages', 'read_whole', 'mandatory_only', 'not_read' (later pages that declare nothing mandatory or superseding),
    'unreadable' (names), 'missing_folders', 'undelivered' (pages whose mandatory section cannot be delivered, with the reason),
    'unscanned' (pages past MAX_SCAN_BYTES), 'scanned_bytes'}."""
    project = Path(project)
    found, problems = [], []
    cov = coverage if coverage is not None else {}
    cov.update(pages=0, read_whole=0, mandatory_only=0, not_read=0, unreadable=[], missing_folders=[], undelivered=[], unscanned=0, scanned_bytes=0)
    folders = paths if paths is not None else configured_paths(project, problems)
    if problems: cov['config_problem'] = True
    for folder in folders:
        external = Path(folder).is_absolute()
        base = Path(folder) if external else project / folder
        if not base.is_dir():
            if paths is not None or tuple(folders) != DEFAULT_PATHS:      # a folder the project named: say it was not read
                problems.append({'path': str(folder), 'problem': 'configured wiki folder not found or not a folder; not read'})
                cov['missing_folders'].append(str(folder))
            continue
        try:
            files = sorted(p for p in base.rglob('*.md') if p.is_file())
        except OSError as error:
            problems.append({'path': str(folder), 'problem': f'cannot list the folder: {str(error)[:120]}'}); cov['unreadable'].append(str(folder)); continue
        not_read = unscanned = 0
        for file in files:
            cov['pages'] += 1
            name = str(file) if external else file.relative_to(project).as_posix()
            if cov['scanned_bytes'] >= MAX_SCAN_BYTES:
                unscanned += 1; continue
            whole = cov['read_whole'] < MAX_PAGES
            try:
                size = file.stat().st_size
                cov['scanned_bytes'] += size
                if size > MAX_PAGE_BYTES:
                    problems.append({'path': name, 'problem': f'page larger than {MAX_PAGE_BYTES} bytes; not read'}); cov['unreadable'].append(name)
                    if _scan_for_must(file):
                        cov['undelivered'].append({'path': name, 'line': None, 'id': None, 'applies_to': None, 'source_paths': None,
                                                   'reason': f'the page declares a mandatory section but is larger than {MAX_PAGE_BYTES} bytes'})
                    continue
                data = file.read_bytes()
            except OSError as error:
                problems.append({'path': name, 'problem': f'cannot read: {str(error)[:120]}'}); cov['unreadable'].append(name); continue
            text, why = _decode(data)
            if text is None:
                problems.append({'path': name, 'problem': f'{why}; not read'}); cov['unreadable'].append(name)
                if _declares_must_bytes(data):
                    cov['undelivered'].append({'path': name, 'line': None, 'id': None, 'applies_to': None, 'source_paths': None,
                                               'reason': f'the page declares a mandatory section but is {why}'})
                continue
            if not whole and not (MUST_TEXT.search(text) or SUPERSEDES_BYTES.search(data)):
                not_read += 1; continue                  # past the reading budget and nothing mandatory or superseding in it
            page = {'path': name, 'origin': 'external' if external else 'repo', 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data), 'text': text}
            if whole: cov['read_whole'] += 1
            else: page['mandatory_only'] = True; cov['mandatory_only'] += 1
            found.append(page)
        cov['not_read'] += not_read; cov['unscanned'] += unscanned
        if not_read:
            problems.append({'path': str(folder), 'problem': f'{not_read} page(s) after the first {MAX_PAGES} were looked through for mandatory '
                                                             'and superseding sections only: they declare none; the rest of their text is not read'})
        if unscanned:
            problems.append({'path': str(folder), 'problem': f'{unscanned} page(s) not looked through: more than {MAX_SCAN_BYTES} bytes of wiki; '
                                                             'mandatory constraints cannot be established'})
    return found, problems
