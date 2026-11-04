"""R07 bounded issue localization at a pinned revision; findings are hypotheses.

Source is read by v1 Discovery in a disposable pinned checkout. Optional project
maps use the existing context/blob mechanism. Lookup never edits code or grants
authority. Held-out evaluation exposes labels only after each lookup returns.
"""
import ast
import json
import re
import tempfile
import time
from pathlib import Path

from ..discovery import Discovery, TEXT
from ..ledger import LedgerError, canonical, content_hash, text_field
from ..snapshots import Snapshots
from . import context
from .verifiers import command

MAP_KIND = 'issue-project-map'
MAX_FILES = 2000
MAX_BYTES = 8_000_000
MAX_QUERIES = 16
MAX_SYMBOLS = 10000
MAX_LIST_OPS = 128
NOTICE = 'Suspects and similar lessons are hypotheses, not verified causes or instructions to change code.'


def _symbols(path, text):
    """Locations and syntactic references, without claiming runtime call binding."""
    out = []
    lines = text.splitlines()
    if path.endswith('.py'):
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return out
        def visit(node, parents=()):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    names = (*parents, child.name)
                    if not isinstance(child, ast.ClassDef):
                        first = min([child.lineno, *[d.lineno for d in child.decorator_list]])
                        out.append({'symbol': '.'.join(names), 'leaf': child.name, 'line': child.lineno,
                                    'text': '\n'.join(lines[first - 1:child.end_lineno]),
                                    'references': sorted({n.attr if isinstance(n, ast.Attribute) else n.id for n in ast.walk(child)
                                                          if isinstance(n, (ast.Attribute, ast.Name))})})
                    visit(child, names)
                else:
                    visit(child, parents)
        visit(tree)
    else:
        # Conservative declarations for common source languages. Each is still
        # checked textually at the pinned revision before it becomes a suspect.
        declaration = re.compile(r'\b(?:function|def|fn|func)\s+([A-Za-z_]\w*)\s*\(')
        for i, line in enumerate(lines):
            for match in declaration.finditer(line):
                out.append({'symbol': match.group(1), 'leaf': match.group(1), 'line': i + 1,
                            'text': '\n'.join(lines[i:i + 25]), 'references': re.findall(r'[A-Za-z_]\w*', '\n'.join(lines[i:i + 25]))})
    return out


def _previous_map(ledger, name):
    if not name:
        return None
    rows = context.retrieve(ledger, plan=name, scope='project', limit=1000)['entries']
    for row in reversed(rows):
        if row['key'] != 'issue-project-map' or row['source']['type'] != 'receipt':
            continue
        try:
            value = json.loads(Snapshots(ledger.state_root).read_blob(row['source']['key']))
        except (OSError, ValueError):
            continue
        if value.get('kind') == MAP_KIND and value.get('project') == ledger.project_id:
            return value
    return None


def _build_map(ledger, revision, previous=None):
    commit = context.resolve_revision(ledger.project, revision)
    previous_files = {f['path']: f for f in (previous or {}).get('files', [])}
    files, coverage, reused, total, list_ops = [], [], 0, 0, 0
    with tempfile.TemporaryDirectory(prefix='onecrew-lookup-') as temp:
        pinned = command._checkout(ledger.project, commit, temp)
        discovery = Discovery(pinned)
        directories = ['']
        while directories and len(files) < MAX_FILES and total < MAX_BYTES and list_ops < MAX_LIST_OPS:
            directory = directories.pop(0)
            cursor = 0
            while True:
                page = discovery.list(directory, cursor)
                list_ops += 1
                coverage.append({'operation': 'list', 'directory': directory, 'cursor': cursor, 'next_cursor': page['next_cursor']})
                for entry in page['entries']:
                    if entry['kind'] == 'directory':
                        if entry['path'].count('/') < 32:
                            directories.append(entry['path'])
                        else:
                            coverage.append({'operation': 'list', 'directory': entry['path'], 'withheld': True})
                        continue
                    path = entry['path']
                    if Path(path).suffix.lower() not in TEXT:
                        continue
                    if len(files) >= MAX_FILES or total >= MAX_BYTES:
                        break
                    blob = command._git(ledger.project, 'rev-parse', commit + ':' + path)
                    prior = previous_files.get(path)
                    try:
                        data = discovery.data(path)
                        text = data.decode('utf-8-sig')
                    except (LedgerError, OSError, UnicodeError):
                        coverage.append({'operation': 'read', 'path': path, 'withheld': True}); continue
                    total += len(data)
                    coverage.append({'operation': 'read', 'path': path, 'bytes': len(data), 'sha256': content_hash(text)})
                    # Context is data. Even a cached map cannot invent file
                    # content or declarations for an immutable Git object.
                    declarations = _symbols(path, text)
                    if prior and prior.get('blob') == blob and prior.get('text') == text and prior.get('symbols') == declarations:
                        files.append(prior); reused += 1; continue
                    files.append({'path': path, 'blob': blob, 'bytes': len(data), 'text': text, 'symbols': declarations})
                if page['next_cursor'] is None:
                    break
                cursor = page['next_cursor']
                if len(files) >= MAX_FILES or total >= MAX_BYTES or list_ops >= MAX_LIST_OPS:
                    break
        complete = not directories and len(files) < MAX_FILES and total < MAX_BYTES and list_ops < MAX_LIST_OPS and not any(c.get('withheld') for c in coverage)
    return {'kind': MAP_KIND, 'version': 1, 'project': ledger.project_id, 'revision': commit, 'files': files,
            'coverage': coverage, 'complete': complete, 'reused_files': reused, 'bytes': total,
            'limits': {'files': MAX_FILES, 'bytes': MAX_BYTES, 'list_operations': MAX_LIST_OPS}}


def index_project(ledger, name, revision='HEAD'):
    """Explicitly publish an incremental map via context.entry + existing blobs."""
    value = _build_map(ledger, revision, _previous_map(ledger, name))
    stable = {key: item for key, item in value.items() if key != 'reused_files'}
    blob = Snapshots(ledger.state_root).blob(canonical(stable).encode('utf-8'))
    saved = context.add(ledger, name, kind='note', label='observed', text=f'Bounded issue map at {value["revision"]}; {len(value["files"])} files.',
                        source={'type': 'receipt', 'key': blob}, key='issue-project-map')
    return {'revision': value['revision'], 'files': len(value['files']), 'reused_files': value['reused_files'],
            'complete': value['complete'], 'event': saved['event'], 'recorded': saved['recorded'], 'receipt': blob}


def _queries(issue):
    words = re.findall(r'[^\W_]+(?:_[^\W_]+)*', issue.casefold(), re.UNICODE)
    # Literal multiword UI strings, paths and identifiers. No translation or
    # unsupported semantic claim is inferred from an issue description.
    queries = re.findall(r'["“]([^"”]{3,120})["”]', issue)
    queries += re.findall(r'/[\w/-]{2,100}|\b[A-Za-z_]\w*\.[A-Za-z_]\w*\b', issue)
    for width in (4, 3, 2):
        queries += [' '.join(words[i:i + width]) for i in range(len(words) - width + 1)]
    queries += [w for w in words if len(w) >= 4 and w not in {'when', 'with', 'error', 'slow', 'chậm', 'app', 'application'}]
    # Shorter matches are reached too; cap preserves predictable scan work.
    return list(dict.fromkeys(q for q in queries if 3 <= len(q) <= 200))[:MAX_QUERIES]


def _image_observations(image, provider):
    if image is None:
        return [], {'read': False, 'reason': 'no image supplied'}
    # Capability is checked BEFORE opening, stat-ing or reading image bytes.
    capabilities = (provider or {}).get('capabilities', [])
    if 'vision' not in capabilities:
        return [], {'read': False, 'reason': 'không đọc ảnh: provider không có vision'}
    observe = provider.get('observe_image')
    if not callable(observe):
        raise LedgerError('Vision capability needs an explicit image observer adapter.')
    rows = observe(Path(image))
    if not isinstance(rows, list) or len(rows) > 20:
        raise LedgerError('The image observer must return at most 20 observation strings.')
    return [{'label': 'observed', 'text': text_field(row, 'image observation', 1000),
             'source': {'type': 'image', 'path': str(image), 'provider': provider.get('name', 'declared-vision-adapter')}} for row in rows], {'read': True}


def localize(ledger, issue, *, revision='HEAD', name=None, image=None, provider=None, use_context=True, issue_key=None):
    """Read-only lookup; every source and symbol refers to the requested commit."""
    started = time.monotonic()
    text_field(issue, 'issue description', 4000)
    observations = [{'label': 'observed', 'text': issue, 'source': {'type': 'issue', 'key': issue_key}}]
    image_rows, image_status = _image_observations(image, provider)
    observations.extend(image_rows)
    lookup_text = ' '.join([issue, *[r['text'] for r in image_rows]])
    commit = context.resolve_revision(ledger.project, revision)
    previous = _previous_map(ledger, name) if use_context else None
    project = _build_map(ledger, commit, previous)
    queries = _queries(lookup_text)
    hits, search_receipts = {}, []
    # v1 search receipts retain scan bounds, unreadable counts and continuation.
    with tempfile.TemporaryDirectory(prefix='onecrew-search-') as temp:
        discovery = Discovery(command._checkout(ledger.project, commit, temp))
        for query in queries:
            cursor = 0
            for _ in range(4):
                receipt = discovery.search('', query, cursor)
                search_receipts.append(receipt)
                for match in receipt['matches']:
                    hits.setdefault(match['path'], []).append({'query': query, 'lines': match['lines']})
                if receipt['next_cursor'] is None:
                    break
                cursor = receipt['next_cursor']
    all_symbols = [dict(s, path=f['path']) for f in project['files'] for s in f['symbols']]
    symbols = all_symbols[:MAX_SYMBOLS]
    files_by_path = {f['path']: f for f in project['files']}
    recent_output = command._git(ledger.project, 'log', '-5', '--format=%H', '--name-only', commit, '--')
    recent_paths = {line for line in recent_output.splitlines() if line in files_by_path}
    by_leaf = {}
    for i, symbol in enumerate(symbols):
        by_leaf.setdefault(symbol['leaf'], []).append(i)
    scores, reasons = {}, {}
    def add(index, score, reason):
        scores[index] = max(scores.get(index, 0), score)
        reasons.setdefault(index, []).append(reason)
    for i, symbol in enumerate(symbols):
        for path, matched in hits.items():
            file = files_by_path.get(path)
            if file is None:
                continue
            explicit = re.search(r'(?<!\w)' + re.escape(symbol['symbol']) + r'(?!\w)', file['text'])
            if explicit and symbol['path'] != path:
                add(i, 100, f'Issue text matches {path}; that source names {symbol["symbol"]}.')
            if symbol['path'] == path:
                local = [h for h in matched if h['query'].casefold() in symbol['text'].casefold()]
                if local:
                    add(i, 90, f'Literal issue text {local[0]["query"]!r} occurs in this declaration.')
                elif not symbol['leaf'].startswith('test_'):
                    add(i, 35, 'Literal issue text occurs in this file; declaration is a hypothesis.')
    # Two bounded reference hops. A lexical/AST reference is stated as such,
    # never presented as proof of dynamic dispatch or an established cause.
    for _ in range(2):
        known = list(scores.items())
        for i, score in known:
            for reference in set(symbols[i]['references']):
                for j in by_leaf.get(reference, []):
                    target = symbols[j]
                    if i != j and not target['leaf'].startswith('test_'):
                        add(j, score - 10, f'{symbols[i]["symbol"]} contains a syntactic reference to {target["leaf"]}; verify call binding.')
    tests = [s for s in symbols if s['leaf'].startswith('test_')]
    known_names = set(by_leaf) | {s['symbol'].split('.')[0] for s in symbols}
    suspects = []
    for index in sorted(scores, key=lambda i: (-scores[i], symbols[i]['path'], symbols[i]['line']))[:10]:
        symbol = symbols[index]
        if symbol['leaf'].startswith('test_'):
            continue
        if not context.symbol_present(ledger.project, commit, symbol['symbol'], symbol['path'])[0]:
            continue
        check_names = {symbol['leaf'], symbol['symbol'].split('.')[0]} | (set(symbol['references']) & known_names)
        checks = [t['symbol'] for t in tests if check_names & set(t['references'])]
        suspects.append({'file': symbol['path'], 'method': symbol['symbol'], 'label': 'hypothesis', 'score': scores[index],
                         'reason': list(dict.fromkeys(reasons[index])) + (['This file occurs in the five most recent commits at or before the pinned revision.'] if symbol['path'] in recent_paths else []),
                         'source': {'path': symbol['path'], 'line': symbol['line'], 'revision': commit},
                         'next_check': {'tests': checks, 'revision': commit, 'condition': issue,
                                        'action': 'Reproduce the issue under its reported conditions and verify the referenced call binding.'}})
    related = []
    if use_context:
        for entry in context.retrieve(ledger, plan=name, revision=commit)['entries']:
            if not entry.get('lesson') or entry.get('label') == 'stale':
                continue
            if any(q.casefold() in entry['text'].casefold() for q in queries):
                related.append(dict(entry, relevance='similar, needs verification', authority=False))
    return {'revision': commit, 'status': 'suspects' if suspects else 'chưa đủ dữ liệu', 'observations': observations,
            'hypotheses': suspects, 'suspects': suspects, 'related_lessons': related,
            'needed': [] if suspects else ['màn hình / screen', 'thao tác / action', 'thời điểm / timing'],
            'image': image_status, 'search_receipts': search_receipts,
            'search_complete': all(next(r for r in reversed(search_receipts) if r['query'] == q)['exhausted'] for q in queries),
            'map_complete': project['complete'] and len(all_symbols) <= MAX_SYMBOLS,
            'seconds': round(time.monotonic() - started, 6), 'notice': NOTICE, 'proposed_changes': []}


def evaluate(ledger, cases, oracle):
    """Six or more held-out inputs; labels are requested only after lookup.

    Cases contain only id/description/pre-fix revision. The separate oracle is
    called after that case's lookup and cannot supply context or source to it.
    Returned timing is time to rank a candidate, not verified real root cause.
    """
    rows = []
    for case in cases:
        if set(case) - {'id', 'description', 'revision'}:
            raise LedgerError('Evaluation inputs must not contain fixes, labels or lessons.')
        result = localize(ledger, case['description'], revision=case['revision'], use_context=False, issue_key=case['id'])
        expected = oracle(case['id'])
        rank = next((i + 1 for i, suspect in enumerate(result['suspects']) if suspect['file'] == expected['file'] and suspect['method'] == expected['method']), None)
        rows.append({'id': case['id'], 'revision': result['revision'], 'rank': rank, 'seconds_to_candidate': result['seconds'],
                     'verified_root_cause_seconds': None, 'context_used': False})
    denominator = len(rows)
    return {'cases': rows, 'denominator': denominator,
            'top_k': {str(k): {'hits': sum(r['rank'] is not None and r['rank'] <= k for r in rows), 'denominator': denominator} for k in (1, 3, 5)},
            'limitation': 'Static fixture ranking and candidate time; no real-provider vision or measured time to a verified production root cause.'}
