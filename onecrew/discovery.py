"""Bounded, root-scoped discovery shared by all owned-execution jobs."""
from pathlib import Path
import re

from .ledger import LedgerError
from .snapshots import safe_file, bytes_hash

EXCLUDED = {'.git', '.onecrew', '.ssh', '.aws', '.azure', '.config', '.codex',
            '.claude', '.kiro', '.venv', 'venv', 'node_modules', '__pycache__',
            'build', 'dist', '.dart_tool', '.idea', '.vscode'}
PRIVATE = re.compile(r'(credential|secret|token|password|private.?key|id_rsa|id_ed25519|^auth\.json$)', re.I)
from .display_core import SECRET
TEXT = {'.py','.js','.mjs','.cjs','.ts','.mts','.cts','.tsx','.jsx','.json','.md','.txt','.toml','.yaml','.yml',
        '.dart','.xml','.sql','.xsql','.html','.css','.scss','.go','.rs','.java',
        '.kt','.cs','.cpp','.c','.h','.sh','.ps1','.bat','.ini','.cfg','.lock','.arb'}

SEARCH_ENTRIES = 10000
SEARCH_PAGE = 100
# Per-op scan budget: one search op scans up to SEARCH_SCAN_FILES files (or until SEARCH_SCAN_BYTES of content
# is read), so a large repo is covered in a few ops instead of one model call per 100-file page. Output stays
# capped (matches truncated); files are never dropped - next_cursor resumes exactly where scanning stopped.
SEARCH_SCAN_FILES = 2000
SEARCH_SCAN_BYTES = 8_000_000


def permitted(name):
    parts = name.split('/')
    return not any(p.lower() in EXCLUDED or p.lower().startswith('.env') or PRIVATE.search(p) for p in parts)


def scan_text(data):
    try:
        value = data.decode('utf-8-sig')
    except UnicodeError:
        raise LedgerError('Binary/non-UTF8 content is not available to workers.') from None
    if '\0' in value or SECRET.search(value):
        raise LedgerError('Potential credential or binary content withheld by discovery policy.')
    return value


class Discovery:
    def __init__(self, project):
        self.root = Path(project).resolve()

    def path(self, name):
        if not permitted(name):
            raise LedgerError('Path excluded by discovery policy.')
        return safe_file(self.root, name)

    def data(self, name, limit=200_000):
        # limit: the worker read API keeps 200 KB; a native snapshot copies larger source files (CAPTURE_MAX).
        path = self.path(name)
        if path.suffix.lower() not in TEXT and path.name not in ('Dockerfile','Makefile','LICENSE','.gitignore'):
            raise LedgerError('File type unavailable to workers.')
        if not path.is_file() or path.stat().st_size > limit:
            raise LedgerError('Read requires a regular file of at most ' + str(limit) + ' bytes.')
        data = path.read_bytes()
        scan_text(data)
        return data

    def list(self, directory='', cursor=0):
        if type(cursor) is not int or cursor < 0:
            raise LedgerError('Cursor must be a nonnegative integer.')
        root = self.root if directory == '' else self.path(directory)
        if not root.is_dir():
            raise LedgerError('Directory does not exist.')
        # Bound enumeration as well as returned JSON. Large trees are traversed directory by directory.
        entries = []
        for p in root.iterdir():
            if len(entries) >= 10000:
                raise LedgerError('Directory exceeds discovery enumeration limit.')
            entries.append(p)
        entries.sort(key=lambda p: p.name.casefold())
        output = []
        for p in entries[cursor:cursor+100]:
            name = p.relative_to(self.root).as_posix()
            linked = p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction())
            if linked or not permitted(name):
                continue
            output.append({'path': name, 'kind': 'directory' if p.is_dir() else 'file',
                           'repository': p.is_dir() and (p/'.git').exists()})
        end = cursor+100
        return {'entries': output, 'next_cursor': end if end < len(entries) else None,
                'repository': (root/'.git').exists()}

    def read(self, name, cursor=0):
        if type(cursor) is not int or cursor < 0:
            raise LedgerError('Cursor must be a nonnegative integer.')
        data = self.data(name)
        value = scan_text(data)
        return {'path': name, 'sha256': bytes_hash(data), 'text': value[cursor:cursor+12000],
                'next_cursor': cursor+12000 if cursor+12000 < len(value) else None}

    def search(self, directory, query, cursor=0):
        if not isinstance(query, str) or not 1 <= len(query) <= 200:
            raise LedgerError('Search requires 1-200 literal characters.')
        if type(cursor) is not int or cursor < 0:
            raise LedgerError('Cursor must be a nonnegative integer.')
        root = self.root if directory == '' else self.path(directory)
        if not root.is_dir(): raise LedgerError('Directory does not exist.')
        # Deterministic bounded DFS. Never traverse excluded paths or links.
        stack = [(root, 0)]; files = []; directories = []; visited = 0
        truncated = False; omitted = 0
        while stack:
            current, depth = stack.pop()
            children = []
            try:
                for p in current.iterdir():
                    visited += 1
                    if visited > SEARCH_ENTRIES:
                        truncated = True; break
                    name = p.relative_to(self.root).as_posix()
                    if p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()) or not permitted(name):
                        omitted += 1; continue
                    children.append(p)
            except OSError:
                omitted += 1; continue
            # Discard a partially enumerated directory rather than page an unstable prefix.
            if truncated: break
            pending = []
            for p in sorted(children, key=lambda p: p.name.casefold()):
                name = p.relative_to(self.root).as_posix()
                if p.is_dir():
                    if depth == 0: directories.append(name)
                    if depth < 32: pending.append((p, depth+1))
                    else: omitted += 1
                elif p.suffix.lower() in TEXT or p.name in ('Dockerfile','Makefile','LICENSE','.gitignore'):
                    files.append(name)
                else: omitted += 1
            stack.extend(reversed(pending))
        matches = []; scanned = 0; unreadable = 0; bytes_read = 0; pos = cursor
        # Scan a budgeted span this op: up to SEARCH_SCAN_FILES files or SEARCH_SCAN_BYTES of content, whichever first.
        # Covering many files per op (not 100) is what stops a large repo from costing one model call per page; the
        # byte budget keeps a single op bounded, and next_cursor resumes at the exact file so nothing is skipped.
        while pos < len(files) and scanned < SEARCH_SCAN_FILES and bytes_read < SEARCH_SCAN_BYTES:
            name = files[pos]; pos += 1
            try:
                value = scan_text(self.data(name))
            except (LedgerError, OSError):
                unreadable += 1; continue
            scanned += 1; bytes_read += len(value)
            hits = [i+1 for i,line in enumerate(value.splitlines()) if query.casefold() in line.casefold()]
            if hits:
                matches.append({'path': name, 'lines': hits[:20], 'total_matches':len(hits)})
        end = pos
        exhausted = end >= len(files) and not truncated
        stop_reason = ('scanned the whole permitted tree' if exhausted else
            ('file budget for one op reached' if scanned >= SEARCH_SCAN_FILES else
             ('content byte budget for one op reached' if bytes_read >= SEARCH_SCAN_BYTES else
              ('enumeration truncated: narrow directory' if truncated else 'more files remain'))))
        return {'matches':matches, 'directories':directories[:100], 'directory':directory,
                'query':query, 'cursor':cursor, 'recursive':True,
                'next_cursor':end if end < len(files) else None,
                'files_total':len(files), 'scanned_from':cursor, 'scanned_through':end,
                'files_scanned':scanned, 'files_withheld_or_unreadable':unreadable,
                'entries_excluded':omitted, 'tree_truncated':truncated,
                'exhausted':exhausted, 'stop_reason':stop_reason,
                'coverage':('Scanned permitted readable text files '+str(cursor)+'..'+str(end)+' of '+str(len(files))+' in '
                    +'this directory scope ('+stop_reason+'). If next_cursor is set, MORE FILES REMAIN - follow it to keep '
                    +'scanning, or narrow directory / change query / view structure / check git history. Empty matches mean '
                    +'NOT FOUND in the scanned range only, never the whole repo unless exhausted=true.')}
