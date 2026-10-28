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
MAX_PAGES = 2000
HEADING = re.compile(r'^(#{2,3})\s+(.+?)\s*#*\s*$')
FENCE_OPEN = re.compile(r'^```onecrew\s*$')
IDENT = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$')


def slug(text):
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


def parse(text, path):
    """{'entries': [...], 'problems': [...]} of one page; `path` is how the page is named in the package (repo-relative or absolute)."""
    problems, entries, seen = [], [], {}
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
        body, meta_raw, i = [], None, 0
        rows = section['body']
        while i < len(rows):
            if FENCE_OPEN.match(rows[i]) and meta_raw is None:
                j = i + 1
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
            problems.append(f'{where}: id {ident} repeats the section at line {seen[ident]}; this section is skipped.'); continue
        seen[ident] = section['line']
        text_body = '\n'.join(body).strip()
        entries.append(dict(meta, id=ident, title=meta['title'] or section['title'], text=text_body, line=section['line'], typed=typed))
    return {'entries': entries, 'problems': problems}


def configured_paths(project):
    """The wiki folders of a project: `.onecrew/config.json` "wiki": {"paths": [...]} when present, else docs/wiki."""
    config = Path(project) / '.onecrew' / 'config.json'
    try:
        value = json.loads(config.read_text(encoding='utf-8'))
        paths = value.get('wiki', {}).get('paths') if isinstance(value, dict) and isinstance(value.get('wiki'), dict) else None
        if isinstance(paths, list) and paths and all(isinstance(p, str) and p for p in paths):
            return list(paths)
    except (OSError, ValueError):
        pass
    return list(DEFAULT_PATHS)


def pages(project, paths=None):
    """Every page of the wiki folders: [{'path', 'origin', 'sha256', 'bytes', 'text'}] plus problems; a missing folder is no page, not an error."""
    project = Path(project)
    found, problems = [], []
    for folder in (paths if paths is not None else configured_paths(project)):
        external = Path(folder).is_absolute()
        base = Path(folder) if external else project / folder
        if not base.is_dir(): continue
        try:
            files = sorted(p for p in base.rglob('*.md') if p.is_file())
        except OSError as error:
            problems.append({'path': str(folder), 'problem': f'cannot list the folder: {str(error)[:120]}'}); continue
        for file in files:
            if len(found) >= MAX_PAGES:
                problems.append({'path': str(folder), 'problem': f'more than {MAX_PAGES} pages; the rest is not read'}); break
            name = str(file) if external else file.relative_to(project).as_posix()
            try:
                data = file.read_bytes()
            except OSError as error:
                problems.append({'path': name, 'problem': f'cannot read: {str(error)[:120]}'}); continue
            if len(data) > MAX_PAGE_BYTES:
                problems.append({'path': name, 'problem': f'page larger than {MAX_PAGE_BYTES} bytes; not read'}); continue
            try:
                text = data.decode('utf-8')
            except UnicodeDecodeError:
                problems.append({'path': name, 'problem': 'not UTF-8 text; not read'}); continue
            found.append({'path': name, 'origin': 'external' if external else 'repo', 'sha256': hashlib.sha256(data).hexdigest(),
                          'bytes': len(data), 'text': text})
    return found, problems
