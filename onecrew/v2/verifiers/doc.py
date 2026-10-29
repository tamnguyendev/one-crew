"""Verifier adapter `doc` (W22, RX1): does a set of Markdown documents keep its promises?

Declared in the contract as a milestone `verifier: {"type": "doc", "config": {...}}` and run by `verdict run` like every other verifier, on a
clean checkout of the artifact (the Git tree hash the verdict is bound to). It reads files through the core's `Port` and nothing else: no
network, no command, no write. The result is computed by the core from the checks it returns.

Config (the adapter's own keys; `authority` is the core's):
  docs   [ "path.md" | {path, headings, ordered, tables, sources} ]   the documents (1-20, Markdown, relative POSIX paths)
           headings  [ "Text" | {text, level} ]    each must exist (outside code blocks); `ordered` makes their order matter
           tables    [ {under: "Heading", columns: [...]} ]   a table under that heading whose header holds the columns, in that order
           sources   {section, min, cite, external}   `section` lists the sources as `[S1] <path or link> - ...`; every id cited in the
                      text (`cite` is the id pattern, default S\\d+; a citation is a `[label]` that it accepts in full, so `[S1]` is one
                      and `[ S1 ]` is not) must have an entry, every entry a locator, a local locator must exist
                      (and its #anchor too); `external` is "unverified" (default: an http source is listed, never said to be reachable)
                      or "forbid"
  links  true (default) | false     every internal link and image resolves to a file, and its #anchor to a heading, inside the checkout
  ids    [ {name, pattern, defined_in} ]   every id matching `pattern` that is used must be defined once (a heading, list item or table
                      row that starts with it) in `defined_in` (default: the documents)

What it does not prove: that a web address is alive (it is listed as not verified), that a source says what the document claims, or that
the text is good. It proves the references hold together.
"""
import hashlib
import posixpath
import re
import sys
import unicodedata
from urllib.parse import unquote

from ...ledger import LedgerError, text_field
from ...snapshots import scoped_path
from . import port

NAME = 'doc'
MAX_DOCS, MAX_FILE, MAX_LINE, MAX_EXTRA = 20, 1_000_000, 4000, 200
MARKDOWN = ('.md', '.markdown')
DEFAULT_CITE = 'S\\d+'
EXTERNAL = ('unverified', 'forbid')

FENCE = re.compile(r'^ {0,3}(`{3,}|~{3,})')
HEADING = re.compile(r'^ {0,3}(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$')
INLINE_LINK = re.compile(r'(!?)\[(?:[^\]\\]|\\.)*\]\(\s*(<[^>]*>|[^)\s]*)(?:\s+(?:"[^"]*"|\'[^\']*\'))?\s*\)')
REF_USE = re.compile(r'\[((?:[^\]\\]|\\.)+)\]\[([^\]]*)\]')
REF_DEF = re.compile(r'^ {0,3}\[([^\]]+)\]:\s*(<[^>]*>|\S+)')
CODE_SPAN = re.compile(r'(`+)(.+?)\1')
TABLE_SEP = re.compile(r'^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$')
HTML_ANCHOR = re.compile(r'''(?:id|name)\s*=\s*["']([^"']+)["']''')
SCHEME = re.compile(r'^[A-Za-z][A-Za-z0-9+.-]+:')
DRIVE = re.compile(r'^[A-Za-z]:[\\/]')
BAD_NAME = re.compile(r'[<>:"|?*\x00-\x1f]')
URL = re.compile(r'https?://[^\s<>)\]]+')
ENTRY = re.compile(r'^\s*(?:[-*+]|\d+[.)])?\s*\[([^\]]+)\]')
BRACKET = re.compile(r'\[([^\[\]]+)\](?!\()')            # a bracketed label that is not the text of an inline link: a citation if `cite` accepts it in full


# ---- the contract form ----------------------------------------------------------------------------------------------------

def _keys(value, allowed, label):
    if not isinstance(value, dict) or set(value) - set(allowed): raise LedgerError(f'{label}: expected an object with {", ".join(allowed)}.')
    return value


def _list(value, label, low, high):
    if not isinstance(value, list) or not low <= len(value) <= high: raise LedgerError(f'{label}: expected a list of {low}-{high} entries.')
    return value


def _path(value, label):
    scoped_path(value)
    if not value.lower().endswith(MARKDOWN): raise LedgerError(f'{label}: {value} is not a Markdown file ({", ".join(MARKDOWN)}).')
    return value


def _regex(value, label):
    text_field(value, label, 100)
    try:
        re.compile(value)
    except re.error as error:
        raise LedgerError(f'{label} is not a regular expression: {error}') from error
    return value


def _heading(value, label):
    if isinstance(value, str): return {'text': text_field(value, label, 120), 'level': None}
    value = _keys(value, ('text', 'level'), label)
    level = value.get('level')
    if level is not None and (type(level) is not int or not 1 <= level <= 6): raise LedgerError(label + '.level: 1-6.')
    return {'text': text_field(value.get('text'), label + '.text', 120), 'level': level}


def _table(value, label):
    value = _keys(value, ('under', 'columns'), label)
    columns = [text_field(c, label + '.columns', 80) for c in _list(value.get('columns'), label + '.columns', 1, 12)]
    return {'under': text_field(value.get('under'), label + '.under', 120), 'columns': columns}


def _sources(value, label):
    value = _keys(value, ('section', 'min', 'cite', 'external'), label)
    minimum = value.get('min', 1)
    if type(minimum) is not int or not 0 <= minimum <= 50: raise LedgerError(label + '.min: 0-50.')
    mode = value.get('external', 'unverified')
    if mode not in EXTERNAL: raise LedgerError(f'{label}.external: one of {", ".join(EXTERNAL)}.')
    return {'section': text_field(value.get('section'), label + '.section', 120), 'min': minimum, 'cite': _regex(value.get('cite', DEFAULT_CITE), label + '.cite'), 'external': mode}


def _document(value, label):
    if isinstance(value, str): value = {'path': value}
    value = _keys(value, ('path', 'headings', 'ordered', 'tables', 'sources'), label)
    ordered = value.get('ordered', False)
    if not isinstance(ordered, bool): raise LedgerError(label + '.ordered: true or false.')
    return {'path': _path(value.get('path'), label + '.path'),
            'headings': [_heading(h, label + '.headings') for h in _list(value.get('headings', []), label + '.headings', 0, 30)],
            'ordered': ordered,
            'tables': [_table(t, label + '.tables') for t in _list(value.get('tables', []), label + '.tables', 0, 10)],
            'sources': _sources(value['sources'], label + '.sources') if value.get('sources') is not None else None}


def _id_spec(value, label):
    value = _keys(value, ('name', 'pattern', 'defined_in'), label)
    return {'name': text_field(value.get('name'), label + '.name', 40), 'pattern': _regex(value.get('pattern'), label + '.pattern'),
            'defined_in': [_path(p, label + '.defined_in') for p in _list(value.get('defined_in', []), label + '.defined_in', 0, MAX_DOCS)]}


def validate_config(config, label):
    config = _keys(config, ('docs', 'links', 'ids'), label)
    docs = [_document(d, label + '.docs') for d in _list(config.get('docs'), label + '.docs', 1, MAX_DOCS)]
    if len({d['path'] for d in docs}) != len(docs): raise LedgerError(label + '.docs: a document is listed twice.')
    links = config.get('links', True)
    if not isinstance(links, bool): raise LedgerError(label + '.links: true or false.')
    return {'docs': docs, 'links': links, 'ids': [_id_spec(i, label + '.ids') for i in _list(config.get('ids', []), label + '.ids', 0, 10)]}


# ---- reading Markdown -----------------------------------------------------------------------------------------------------

def _norm(text):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFC', text)).strip().casefold()


def _plain(text):
    """Heading or cell text as a reader sees it: links reduced to their label, code and emphasis marks dropped."""
    text = re.sub(r'!?\[([^\]]*)\]\([^)]*\)', r'\1', text)
    return unicodedata.normalize('NFC', re.sub(r'[`*]', '', text)).strip()


def _slug(text):
    text = _plain(text).lower()
    return re.sub(r'\s', '-', re.sub(r'[^\w\s-]', '', text))


def _strip_code(line):
    return CODE_SPAN.sub(lambda m: ' ' * len(m.group(0)), line)


def _cells(line):
    inner = line.strip()
    inner = inner[1:] if inner.startswith('|') else inner
    inner = inner[:-1] if inner.endswith('|') and not inner.endswith('\\|') else inner
    return [_norm(_plain(c)) for c in re.split(r'(?<!\\)\|', inner)]


class Parsed:
    def __init__(self, text):
        self.lines, self.headings, self.tables, self.links, self.refdefs, self.anchors = [], [], [], [], {}, set()
        fence = None
        for number, raw in enumerate(text.lstrip('﻿').splitlines(), 1):
            if len(raw) > MAX_LINE:
                raise port.Inconclusive(f'line {number} exceeds {MAX_LINE} characters; it is not checked in part')
            marker = FENCE.match(raw)
            if fence:
                if marker and marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence) and raw.strip() == marker.group(1): fence = None
                self.lines.append((number, raw, True))
            else:
                if marker: fence = marker.group(1)
                self.lines.append((number, raw, bool(marker)))
        stack, seen = [], {}
        for index, (number, raw, code) in enumerate(self.lines):
            if code: continue
            for found in HTML_ANCHOR.findall(raw): self.anchors.add(found.lower())
            heading = HEADING.match(raw)
            if heading:
                level, title = len(heading.group(1)), heading.group(2)
                while stack and stack[-1][0] >= level: stack.pop()
                stack.append((level, _norm(_plain(title))))
                slug = _slug(title)
                count = seen.get(slug, 0)
                seen[slug] = count + 1
                self.anchors.add(slug if not count else f'{slug}-{count}')
                self.headings.append({'level': level, 'text': _norm(_plain(title)), 'line': number, 'raw': _plain(title)})
                continue
            definition = REF_DEF.match(raw)
            if definition:
                self.refdefs[definition.group(1).strip().casefold()] = (number, definition.group(2).strip('<>'))
                continue
            if '|' in raw and index + 1 < len(self.lines):
                after = self.lines[index + 1]
                if not after[2] and '-' in after[1] and '|' in after[1] and TABLE_SEP.match(after[1]):
                    self.tables.append({'columns': _cells(raw), 'chain': [t for _, t in stack], 'line': number})
            clean = _strip_code(raw)
            for match in INLINE_LINK.finditer(clean):
                self.links.append((number, match.group(2).strip('<>')))
            for match in REF_USE.finditer(clean):
                label = (match.group(2) or match.group(1)).strip().casefold()
                self.links.append((number, ('ref', label, ((match.start(), match.end(1) + 1), (match.start(2) - 1, match.end())))))     # where the brackets stand

    def body_lines(self):
        return [(n, _strip_code(r)) for n, r, code in self.lines if not code]

    def section(self, title):
        """(heading, [(line number, text)]) of the first section called `title`: up to the next heading of the same or a higher level."""
        wanted = _norm(title)
        for position, heading in enumerate(self.headings):
            if heading['text'] != wanted: continue
            end = next((h['line'] for h in self.headings[position + 1:] if h['level'] <= heading['level']), 10 ** 9)
            return heading, [(n, t) for n, t in self.body_lines() if heading['line'] < n < end]
        return None, []


class Folder:
    """The documents of the run: read once, parsed once; files that are only link targets are read on demand (at most MAX_EXTRA)."""

    def __init__(self, box):
        self.box, self.parsed, self.extra, self.files = box, {}, 0, set(box.files())

    def load(self, path, required=False):
        if path in self.parsed: return self.parsed[path]
        if not required:
            self.extra += 1
            if self.extra > MAX_EXTRA: raise port.Inconclusive(f'more than {MAX_EXTRA} link targets to read')
        try:
            self.parsed[path] = Parsed(self.box.read_text(path, limit=MAX_FILE))
        except UnicodeDecodeError:
            self.parsed[path] = None
        return self.parsed[path]

    def exists(self, path):
        if BAD_NAME.search(path): return False
        return path in self.files or any(f.startswith(path.rstrip('/') + '/') for f in self.files)

    def kept(self, path):
        """(exists, why) for a path the core keeps from every reader (port.kept_reason: .env*, .git, ...), else None. Such a file is never in the
        listing and never read, so a link or a source naming it is checked by name only (beta report B5)."""
        why = port.kept_reason(path)
        return None if why is None else (self.box.exists(path), why)


def _locate(base, target):
    """(kind, resolved path, anchor, why): where an internal target points, relative to the document at `base`."""
    target = target.strip()
    if SCHEME.match(target):
        return ('web' if target.lower().startswith(('http://', 'https://')) else 'other'), target, '', ''
    if DRIVE.match(target): return 'outside', target, '', 'a drive path'
    path, _, anchor = target.partition('#')
    path = unquote(path.split('?')[0]).replace('\\', '/')
    anchor = unquote(anchor)
    resolved = posixpath.normpath(path.lstrip('/')) if path.startswith('/') else posixpath.normpath(posixpath.join(posixpath.dirname(base), path)) if path else base
    if resolved == '..' or resolved.startswith('../'): return 'outside', target, '', 'it leaves the project'
    return 'file', resolved, anchor, ''


def _anchor_problem(folder, resolved, anchor, where, target):
    """None, or why the #anchor of a link to a Markdown file is not there."""
    if not anchor or not resolved.lower().endswith(MARKDOWN) or resolved not in folder.files: return None
    parsed = folder.load(resolved)
    if parsed is None: return f'{where}: link {target}: {resolved} is not valid UTF-8, its anchor #{anchor} cannot be checked'
    if unicodedata.normalize('NFC', anchor).lower() not in parsed.anchors: return f'{where}: link {target}: no heading with the anchor #{anchor} in {resolved}'
    return None


# ---- the checks -----------------------------------------------------------------------------------------------------------

def _check_structure(entry, parsed):
    problems, checked, path = [], 0, entry['path']
    firsts = []
    for wanted in entry['headings']:
        checked += 1
        text = _norm(wanted['text'])
        found = [h for h in parsed.headings if h['text'] == text]
        if not found:
            problems.append(f'{path}: required heading "{wanted["text"]}" is missing')
        elif wanted['level'] is not None and all(h['level'] != wanted['level'] for h in found):
            problems.append(f'{path}: heading "{wanted["text"]}" exists only at level {found[0]["level"]}, level {wanted["level"]} is required')
        else:
            firsts.append((wanted['text'], min(h['line'] for h in found if wanted['level'] in (None, h['level']))))
    if entry['ordered'] and [line for _, line in firsts] != sorted(line for _, line in firsts):
        late = next(t for (t, a), (_, b) in zip(firsts, firsts[1:]) if a > b)
        problems.append(f'{path}: headings are not in the required order ("{late}" comes after the heading that must follow it)')
    for wanted in entry['tables']:
        checked += 1
        under, columns = _norm(wanted['under']), [_norm(c) for c in wanted['columns']]
        def holds(table):
            at = 0
            for name in table['columns']:
                if at < len(columns) and name == columns[at]: at += 1
            return at == len(columns)
        if not any(under in table['chain'] and holds(table) for table in parsed.tables):
            problems.append(f'{path}: no table under "{wanted["under"]}" with the columns {", ".join(wanted["columns"])} in that order')
    return problems, checked


def _citations(parsed, heading, body, cite):
    """[(label, line number, (start, end))]: the ids cited in the text outside the sources section, as the sources check reads them. A citation is a
    `[label]` (not the text of an inline link) whose WHOLE label the compiled pattern `cite` accepts: the pattern is applied to the label alone
    (fullmatch, as to the entries of the section), so an anchored or flagged pattern means what it says, and a padded `[ S1 ]` is not a citation."""
    skip = {n for n, _ in body} | ({heading['line']} if heading else set())
    found = []
    for number, text in parsed.body_lines():
        if number in skip or REF_DEF.match(text): continue
        found += [(m.group(1), number, m.span()) for m in BRACKET.finditer(text) if cite.fullmatch(m.group(1))]
    return found


def _entries(parsed, config):
    """(entries, citations) of one document: the `[S1] locator` lines of its sources section, and the ids cited in the text outside it."""
    heading, body = parsed.section(config['section'])
    cite = re.compile(config['cite'])
    entries = []
    for number, text in body:
        match = ENTRY.match(text)
        if not match or not cite.fullmatch(match.group(1).strip()): continue
        rest = text[match.end():]
        locator = None
        direct = re.match(r'\s*\(\s*([^)\s]+)', rest)
        if direct: locator = direct.group(1)
        else:
            link = INLINE_LINK.search(rest)
            if link: locator = link.group(2).strip('<>')
            else:
                web = URL.search(rest)
                if web: locator = web.group(0).rstrip('.,;')
                else:
                    for token in rest.replace('`', ' ').split():
                        token = token.strip('.,;:()<>—–')
                        if token and ('/' in token or re.search(r'\.\w{1,8}(#\S*)?$', token)):
                            locator = token
                            break
        entries.append({'id': match.group(1).strip(), 'line': number, 'locator': locator})
    return heading, entries, [(label, number) for label, number, _ in _citations(parsed, heading, body, cite)]


def _check_sources(entry, parsed, folder, unverified):
    path, config = entry['path'], entry['sources']
    heading, entries, cited = _entries(parsed, config)
    problems, checked = [], len(entries) + len(cited)
    if heading is None: return [f'{path}: no section "{config["section"]}" for the sources'], checked
    if len(entries) < config['min']: problems.append(f'{path}: {len(entries)} source(s) in "{config["section"]}", at least {config["min"]} required')
    ids = [e['id'] for e in entries]
    for repeated in sorted({i for i in ids if ids.count(i) > 1}): problems.append(f'{path}: source {repeated} has more than one entry')
    for item in entries:
        where, name = f'{path}:{item["line"]}', item['id']
        if not item['locator']:
            problems.append(f'{where}: source {name} has no locator (a path or a link)')
            continue
        kind, resolved, anchor, why = _locate(path, item['locator'])
        if kind == 'web':
            if config['external'] == 'forbid': problems.append(f'{where}: source {name} is an external address ({item["locator"]}); external sources are forbidden here')
            else: unverified.add(f'{where}: source {name} {item["locator"]} (not checked: no network)')
        elif kind == 'outside':
            problems.append(f'{where}: source {name} {item["locator"]} leaves the project ({why})')
        elif kind == 'other':
            problems.append(f'{where}: source {name} {item["locator"]} is not a file or an http(s) address')
        else:
            root = posixpath.normpath(item['locator'].partition('#')[0].replace('\\', '/').lstrip('/'))
            candidates = [c for c in (resolved, root) if not c.startswith('..')]
            found = next((c for c in candidates if folder.exists(c)), None)
            if found is None:
                hidden = next(((c, kept[1]) for c in candidates for kept in [folder.kept(c)] if kept and kept[0]), None)
                if hidden: unverified.add(f'{where}: source {name} {item["locator"]}: {hidden[0]} is {hidden[1]}; it exists, what it says is not checked')
                else: problems.append(f'{where}: source {name} {item["locator"]}: file not found ({resolved})')
                continue
            bad = _anchor_problem(folder, found, anchor, where, item['locator'])
            if bad: problems.append(bad.replace('link ', f'source {name} ', 1))
    have = set(ids)
    for name, number in cited:
        if name not in have: problems.append(f'{path}:{number}: [{name}] is cited but has no entry in "{config["section"]}"')
    return list(dict.fromkeys(problems)), checked


def _check_links(path, parsed, folder, unverified, sources=None):
    """`sources`: the sources config of the document, or None. `[S21][S20]` where both brackets are citations is two citations, not a reference link
    labelled S20 (beta report B3) -- but only where the sources check itself reads both brackets as citations of that line (_citations), so a
    pair is never lost between the two checks (review R9, R13, 29/10). Whatever it does not read keeps the Markdown rule: a padded `[ S9 ]`, a
    bracket the pattern does not accept in full, a pair inside the sources section, a document without sources."""
    problems, checked = [], 0
    cited = set()
    if sources:
        heading, body = parsed.section(sources['section'])
        cited = {(number, span) for _, number, span in _citations(parsed, heading, body, re.compile(sources['cite']))}
    targets = [(n, t) for n, t in parsed.links if not isinstance(t, tuple)]
    for number, (_, label, brackets) in [(n, t) for n, t in parsed.links if isinstance(t, tuple)]:
        if cited and all((number, span) in cited for span in brackets): continue
        found = parsed.refdefs.get(label)
        if found is None: problems.append(f'{path}:{number}: reference [{label}] is used but never defined')
    targets += [(n, t) for n, t in parsed.refdefs.values()]
    for number, target in targets:
        if not target: continue
        checked += 1
        where = f'{path}:{number}'
        kind, resolved, anchor, why = _locate(path, target)
        if kind == 'web': unverified.add(f'{where}: {target} (not checked: no network)')
        elif kind == 'outside': problems.append(f'{where}: link {target} leaves the project ({why}), outside the checkout')
        elif kind == 'file':
            kept = None if folder.exists(resolved) else folder.kept(resolved)
            if kept and kept[0]: unverified.add(f'{where}: link {target}: {resolved} is {kept[1]}; it exists, what it says is not checked')
            elif not folder.exists(resolved): problems.append(f'{where}: link {target} points to {resolved}, which does not exist')
            else:
                bad = _anchor_problem(folder, resolved, anchor, where, target)
                if bad: problems.append(bad)
        # other schemes (mailto:, tel:, ...) are not files: left alone
    return problems, checked


def _check_ids(spec, folder, names):
    pattern = spec['pattern']
    wrapped = r'(?<![\w-])(?:' + pattern + r')(?![\w-])'
    start = re.compile(r'^\s*(?:#{1,6}[ \t]+|[-*+][ \t]+|\d+[.)][ \t]+|\|[ \t]*)[\[\*_`(]*(' + pattern + r')(?![\w-])')
    use = re.compile(wrapped)
    problems, defined, where_ = [], {}, spec['defined_in'] or names
    for path in where_:
        if path not in folder.files:
            problems.append(f'{spec["name"]}: definition file {path} is not in the artifact')
            continue
        parsed = folder.load(path, required=path in names)
        if parsed is None: continue
        for number, text in parsed.body_lines():
            match = start.match(text)
            if match: defined.setdefault(match.group(1), []).append(f'{path}:{number}')
    for name, spots in sorted(defined.items()):
        if len(spots) > 1: problems.append(f'{spec["name"]}: {name} is defined twice ({", ".join(spots)})')
    used = {}
    for path in names:
        parsed = folder.parsed.get(path)
        if parsed is None: continue
        for number, text in parsed.body_lines():
            head = start.match(text)
            for match in use.finditer(text):
                if head and match.start() == head.start(1) and path in where_: continue        # this occurrence is the definition itself
                used.setdefault(match.group(0), f'{path}:{number}')
    for name, spot in sorted(used.items()):
        if name not in defined: problems.append(f'{spot}: {name} is used but never defined ({spec["name"]})')
    return problems, len(defined) + len(used)


def run(config, box):
    """The report for the core: checks (each with how many things it examined), findings (every problem, open), and what could not be verified."""
    folder, unverified = Folder(box), set()
    names = [d['path'] for d in config['docs']]
    documents, problems, loaded = [], [], {}
    for entry in config['docs']:
        path = entry['path']
        if path not in folder.files:
            problems.append(f'{path}: document is missing from the artifact')
            continue
        parsed = folder.load(path, required=True)
        if parsed is None: problems.append(f'{path}: document is not valid UTF-8')
        elif not parsed.lines or not any(t.strip() for _, t, _ in parsed.lines): problems.append(f'{path}: document is empty')
        else: loaded[path] = (entry, parsed)
    checks = [{'id': 'documents', 'ok': not problems, 'checked': len(config['docs']), 'problems': problems}]
    ready = {p: v for p, v in loaded.items()}
    if any(e['headings'] or e['tables'] for e in config['docs']):
        found, count = [], 0
        for path, (entry, parsed) in ready.items():
            more, seen = _check_structure(entry, parsed)
            found += more; count += seen
        checks.append({'id': 'structure', 'ok': not found, 'checked': count, 'problems': found})
    if any(e['sources'] for e in config['docs']):
        found, count = [], 0
        for path, (entry, parsed) in ready.items():
            if entry['sources']:
                more, seen = _check_sources(entry, parsed, folder, unverified)
                found += more; count += seen
        checks.append({'id': 'sources', 'ok': not found, 'checked': count, 'problems': found})
    if config['links']:
        found, count = [], 0
        for path, (entry, parsed) in ready.items():
            more, seen = _check_links(path, parsed, folder, unverified, entry['sources'])
            found += more; count += seen
        checks.append({'id': 'links', 'ok': not found, 'checked': count, 'problems': found})
    if config['ids']:
        found, count = [], 0
        for spec in config['ids']:
            more, seen = _check_ids(spec, folder, [n for n in names if n in ready])
            found += more; count += seen
        checks.append({'id': 'ids', 'ok': not found, 'checked': count, 'problems': found})
    findings = []
    for check in checks:
        for problem in check['problems']:
            finding = {'id': 'F-' + hashlib.sha1(f'{check["id"]}|{problem}'.encode('utf-8')).hexdigest()[:10], 'text': problem}
            where = re.match(r'([^\s:]+\.(?:md|markdown))\b', problem)
            if where: finding['path'] = where.group(1)
            findings.append(finding)
    return {'checks': checks, 'findings': findings, 'unverified': sorted(unverified)}


port.register(sys.modules[__name__])
