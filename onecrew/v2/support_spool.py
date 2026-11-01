"""2.4-S1 (SF-01/SF-02): `onecrew support ...` enters here, and a report is never lost silently when the runtime or the ledger is broken.

Standard library only, and no relative import: this module must import and run when onecrew.ledger (or anything else of the package) cannot.
`entry` (called by the router before anything else is imported) loads the normal support CLI; when that import fails, or when the normal path
cannot open or write the ledger, the same report is written to a spool file:

  <state-root>/support-spool/<FB-id>.json, else <project>/.onecrew/support-spool/, else <tempdir>/onecrew-support-spool/

(each write: O_EXCL temporary file + fsync + os.replace). The spool id IS the feedback id and the client key of the report, so
`onecrew support import-spool` later inserts exactly one support.feedback with that id. The spool is a fallback, never a second status store.
When no place can be written the command exits non-zero and says NOT recorded, with every place it tried.

Also runnable when the `onecrew` executable itself fails:  python -I -m onecrew.v2.support_spool [--project P] [--state-root S] report --text ...
"""
import argparse
import datetime
import hashlib
import importlib
import json
import os
import re
import sys
import tempfile
import uuid
from pathlib import Path

FORMAT = 'onecrew-support-spool-v1'
FOLDER = 'support-spool'
TEXT_MAX = 4000
IMAGE_MAX = 32_000_000


def new_id():
    return 'FB-' + uuid.uuid4().hex


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def default_state_root():
    """The Ledger's own default (where.default_state_root, copied: this module imports nothing of the package)."""
    local = os.environ.get('LOCALAPPDATA')
    return (Path(local) / 'OneCrew' if local else Path.home() / '.onecrew').resolve()


def configured_state_root(project):
    """The state root named by <git root or project>/.onecrew/config.json (where.configured, copied), or None."""
    try:
        start = Path(project).resolve()
        top = next((d for d in (start, *start.parents) if (d / '.git').exists()), None)
        for directory in ([top] if top else []) + [start]:
            try:
                value = json.loads((directory / '.onecrew' / 'config.json').read_text(encoding='utf-8-sig'))
            except (OSError, ValueError):
                continue
            found = value.get('state_root') if isinstance(value, dict) else None
            if isinstance(found, str) and found.strip(): return Path(found)
    except (OSError, ValueError, TypeError):
        pass
    return None


def state_root_for(project, explicit=None):
    return Path(explicit) if explicit else (configured_state_root(project) or default_state_root())


def git_root(project):
    """The folder at or above `project` that holds a .git (where.git_root, copied), else `project` itself."""
    try:
        start = Path(project).resolve()
        return next((d for d in (start, *start.parents) if (d / '.git').exists()), start)
    except OSError:
        return Path(project)


def _norm(path):
    return os.path.normcase(str(Path(path).resolve()))


def locations(project, state_root):
    """The spool folders in the order they are tried (duplicates removed). The project one is at the git root, so a report spooled from a
    subfolder is found by an import run from the repository (S1-R13)."""
    found = []
    for place in (Path(state_root) / FOLDER, git_root(project) / '.onecrew' / FOLDER, Path(tempfile.gettempdir()) / ('onecrew-' + FOLDER)):
        try:
            key = os.path.normcase(str(place.absolute()))
        except OSError:
            key = str(place)
        if key not in [os.path.normcase(str(p.absolute())) for p in found]: found.append(place)
    return found


def runtime_probe():
    """What this process can say about the code it runs without importing the package's other modules (S1-R05): the interpreter, the
    installed distribution's version and RECORD sha256 when the running code IS that distribution (else unknown, with the installed
    version kept apart), and the sha256 of this very file as code_probe."""
    probe = {'executable': sys.executable, 'python': sys.version.split()[0], 'platform': sys.platform, 'source': 'spool'}
    here = Path(__file__).resolve()
    try:
        probe['code_probe'] = {'file': str(here), 'sha256': hashlib.sha256(here.read_bytes()).hexdigest()}
    except OSError as error:
        probe['code_probe'] = {'file': str(here), 'sha256': 'unknown', 'reason': type(error).__name__}
    try:
        from importlib import metadata
        dist = metadata.distribution('onecrew')
        installed = Path(dist.locate_file('onecrew')).resolve()
        running = here.parent.parent
        same = installed == running
        probe['installed_vs_running'] = 'same' if same else 'different'
        record = dist.read_text('RECORD')
        if same:
            probe['dist_version'] = dist.version
            probe['record_sha256'] = hashlib.sha256(record.encode('utf-8')).hexdigest() if record else 'unknown'
        else:
            probe.update(dist_version='unknown', record_sha256='unknown', dist_version_installed=dist.version,
                         dist_version_reason=f'the running code ({running}) is not the installed distribution ({installed})')
    except Exception as error:                     # not installed, or broken metadata: say so, never guess
        probe.update(dist_version='unknown', record_sha256='unknown', installed_vs_running='unknown',
                     dist_version_reason=f'{type(error).__name__}: {error}'[:300])
    return probe


def lite(text):
    """Case and whitespace folded: what makes two sendings of one report the same report."""
    return ' '.join(str(text).casefold().split()) if text is not None else None


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def content_key(text, expected, refs):
    """S1-R08: the client key of a report sent without --key: the same text, expected result and explicit refs in one project are the
    same report (resent: the same id); anything else is a new report. support.report uses this same function."""
    value = {'text': lite(text), 'expected': lite(expected), 'refs': refs or {}}
    return 'auto-' + hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()[:40]


def _image(path):
    if path is None: return None
    image = Path(path)
    if image.is_symlink() or not image.is_file():
        raise ValueError(f'--image {path}: not a regular file')
    if image.stat().st_size > IMAGE_MAX: raise ValueError('--image: larger than 32 MB')
    data = image.read_bytes()
    return {'name': image.name[:200], 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data), 'stored': False}


def _ledger_facts(state_root):
    path = Path(state_root) / 'ledger.sqlite3'
    try:
        stat = path.stat()
        return {'path': str(path), 'bytes': stat.st_size, 'mtime': datetime.datetime.fromtimestamp(stat.st_mtime, datetime.timezone.utc).isoformat()}
    except OSError as error:
        return {'path': str(path), 'error': f'{type(error).__name__}: {error}'[:300]}


def record(*, text, expected=None, image=None, plan=None, task=None, attempt=None, key=None, project, state_root, reason, error=None):
    """The spool document of one report. `image` is a path (only its sha256, size and file name are kept, never the bytes)."""
    if not isinstance(text, str) or not text.strip() or len(text) > TEXT_MAX:
        raise ValueError(f'--text: expected non-empty text, at most {TEXT_MAX} characters')
    if expected is not None and (not isinstance(expected, str) or len(expected) > TEXT_MAX):
        raise ValueError(f'--expected: at most {TEXT_MAX} characters')
    ident = new_id()
    refs = {k: v for k, v in (('plan', plan), ('task', task), ('attempt', attempt)) if v is not None}
    return {'format': FORMAT, 'id': ident, 'client_key': key or content_key(text, expected, refs), 'text': text, 'expected': expected,
            'image': _image(image), 'refs': refs,
            'project': _norm(project), 'git_root': _norm(git_root(project)), 'state_root': str(Path(state_root)),
            'runtime_probe': runtime_probe(), 'error': error, 'reason': reason, 'ledger': _ledger_facts(state_root), 'created_at': _now()}


def write_new(folder, name, data):
    """Create folder/name durably: O_EXCL temporary file, fsync, os.replace. Raises OSError (disk full, read-only, ...)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    temporary = folder / ('.oc-' + uuid.uuid4().hex + '.tmp')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o600)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except BaseException:
        try: os.unlink(temporary)
        except OSError: pass
        raise
    return target


def spool(document, *, project, state_root, tried=()):
    """Write `document` to the first spool folder that takes it. Returns the printed result: recorded true/false, path, tried."""
    tried = list(tried)
    data = json.dumps(document, ensure_ascii=False, indent=1, sort_keys=True).encode('utf-8')
    for folder in locations(project, state_root):
        try:
            path = write_new(folder, document['id'] + '.json', data)
            return {'recorded': True, 'id': document['id'], 'path': str(path), 'spooled': True, 'reason': document.get('reason'), 'tried': tried,
                    'message': f'Recorded in the spool (not yet in the ledger): {path}. Run `onecrew support import-spool` once the ledger works.'}
        except OSError as error:
            tried.append({'path': str(folder), 'error': f'{type(error).__name__}: {error}'[:300]})
    return {'recorded': False, 'id': None, 'path': None, 'spooled': False, 'reason': document.get('reason'), 'tried': tried,
            'message': 'NOT recorded: no place could be written (' + '; '.join(t['path'] + ' -> ' + t['error'] for t in tried) + ').'}


KEY = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z')
FEEDBACK = re.compile(r'FB-[0-9a-f]{32}\Z')


def _text(value, name, maximum, optional=False):
    if value is None and optional: return None
    if not isinstance(value, str) or len(value) > maximum or (not optional and not value.strip()):
        return f'{name}: expected text of at most {maximum} characters'
    return None


def validate(document):
    """None when a spool document has the shape and sizes `record` writes; else why not (S1-R06, S1-R12: a spool file is unauthenticated
    input; only these bounded fields are ever imported)."""
    if not isinstance(document, dict) or document.get('format') != FORMAT: return 'not a OneCrew support spool document'
    if not isinstance(document.get('id'), str) or not FEEDBACK.match(document['id']): return 'id: expected FB-<32 hex>'
    if not isinstance(document.get('client_key'), str) or not KEY.match(document['client_key']): return 'client_key: 1-128 letters, digits, _ . : -'
    for name, maximum, optional in (('text', TEXT_MAX, False), ('expected', TEXT_MAX, True), ('reason', 600, True), ('created_at', 64, True),
                                    ('project', 1000, False), ('git_root', 1000, True), ('state_root', 1000, True)):
        why = _text(document.get(name), name, maximum, optional)
        if why: return why
    refs = document.get('refs', {})
    if not isinstance(refs, dict) or set(refs) - {'plan', 'task', 'attempt'} or any(not isinstance(v, str) or len(v) > 200 for v in refs.values()):
        return 'refs: an object of plan / task / attempt texts'
    image = document.get('image')
    if image is not None and (not isinstance(image, dict) or not re.fullmatch(r'[0-9a-f]{64}', str(image.get('sha256')))
                              or type(image.get('bytes')) is not int or not 0 <= image['bytes'] <= IMAGE_MAX
                              or not isinstance(image.get('name', ''), str) or len(image.get('name', '')) > 200):
        return 'image: {name, sha256, bytes} expected'
    error = document.get('error')
    if error is not None and (not isinstance(error, dict) or _text(error.get('type'), 'error.type', 100)
                              or _text(error.get('text'), 'error.text', 1000, True)):
        return 'error: {type, text} of bounded size expected'
    for name, maximum in (('runtime_probe', 4000), ('ledger', 1000)):
        value = document.get(name)
        if value is not None and (not isinstance(value, dict) or len(_canonical(value)) > maximum):
            return f'{name}: an object of at most {maximum} characters'
    return None


def spooled_files(project, state_root):
    """([(path, document)], other_projects): the spool files of this project (by path, or by the same git root: a report spooled from a
    subfolder) in every spool folder. A file that is not a JSON object comes with document None (the import rejects it); documents of
    other projects are counted and left alone."""
    mine, top = _norm(project), _norm(git_root(project))
    found, others = [], 0
    for folder in locations(project, state_root):
        try:
            names = sorted(folder.glob('FB-*.json'))
        except OSError:
            continue
        for path in names:
            try:
                document = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                document = None
            if isinstance(document, dict) and document.get('project') != mine and document.get('git_root') != top:
                others += 1
                continue
            found.append((path, document if isinstance(document, dict) else None))
    return found, others


def mark_rejected(path, why):
    """Move a malformed spool file to <folder>/rejected/ with a sidecar .reason.txt; the other files are still imported."""
    target = Path(path).parent / 'rejected'
    target.mkdir(exist_ok=True)
    os.replace(path, target / Path(path).name)
    (target / (Path(path).name + '.reason.txt')).write_text(why[:1000] + '\n', encoding='utf-8')
    return target / Path(path).name


def mark_imported(path):
    """Move an imported spool file to <folder>/imported/ (after the ledger committed it). A failure only leaves it to be skipped next time."""
    target = Path(path).parent / 'imported'
    target.mkdir(exist_ok=True)
    os.replace(path, target / Path(path).name)
    return target / Path(path).name


# ---- the command line -----------------------------------------------------------------------------------------------------------------

def report_parser():
    parser = argparse.ArgumentParser(prog='onecrew support report', allow_abbrev=False)
    parser.add_argument('--project', type=Path, default=argparse.SUPPRESS)
    parser.add_argument('--state-root', type=Path, default=argparse.SUPPRESS)
    parser.add_argument('--text', required=True, help='what went wrong, in your words')
    parser.add_argument('--expected', help='what you expected instead')
    parser.add_argument('--image', type=Path, help='a screenshot: only its sha256 is recorded, it is never copied into an export')
    parser.add_argument('--plan'); parser.add_argument('--task'); parser.add_argument('--attempt')
    parser.add_argument('--key', help='your own idempotency key: sending the same report again with it records nothing new')
    parser.add_argument('--json', action='store_true')
    return parser


def split(args):
    """(global options, words from the group on) of a router argv; the globals --project / --state-root may also follow the command."""
    project, state, rest, index = None, None, [], 0
    while index < len(args):
        word = args[index]
        if word in ('--project', '--state-root') and index + 1 < len(args):
            if word == '--project': project = args[index + 1]
            else: state = args[index + 1]
            index += 2
            continue
        if word.startswith(('--project=', '--state-root=')):
            name, _, value = word.partition('=')
            if name == '--project': project = value
            else: state = value
        else:
            rest.append(word)
        index += 1
    return project, state, rest


def print_result(result, as_json):
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result.get('recorded'):
        print(f'{result["id"]}: ' + (result.get('message') or 'recorded.'))
    else:
        print(result.get('message') or 'NOT recorded.')


def spool_report(argv, *, reason, error=None, tried=()):
    """The fallback of `support report`: parse the same options and spool. Exit 0 recorded, 3 not recorded, 2 bad options."""
    project, state, rest = split(argv)
    words = rest[rest.index('report') + 1:] if 'report' in rest else rest
    args = report_parser().parse_args(words)
    project = Path(project) if project else Path.cwd()
    state_root = state_root_for(project, state)
    try:
        document = record(text=args.text, expected=args.expected, image=args.image, plan=args.plan, task=args.task, attempt=args.attempt,
                          key=args.key, project=project, state_root=state_root, reason=reason,
                          error={'type': type(error).__name__, 'text': str(error)[:1000]} if error is not None else None)
    except (OSError, ValueError) as bad:
        print(json.dumps({'error': str(bad), 'type': type(bad).__name__, 'recorded': False}, ensure_ascii=False))
        return 2
    result = spool(document, project=project, state_root=state_root, tried=tried)
    print_result(result, args.json)
    return 0 if result['recorded'] else 3


def entry(args, index):
    """`onecrew ... support <command> ...` from the router (args still holds the global options before index)."""
    words = [w for w in args[index + 1:] if not w.startswith('-')]
    command = words[0] if words else None
    try:
        support_cli = importlib.import_module('onecrew.v2.support_cli')
    except Exception as error:                      # ImportError, or a broken module of the install: the report still gets written
        if command == 'report':
            return spool_report(args, reason=f'the support runtime could not be imported (ImportError: {type(error).__name__}: {error})'[:500],
                                error=error)
        print(json.dumps({'error': f'support {command or ""} needs the OneCrew runtime, which could not be imported '
                                   f'({type(error).__name__}: {error}); only `support report` works without it.'[:800],
                          'type': type(error).__name__}, ensure_ascii=False))
        return 2
    return support_cli.main(args, index)


def main(argv=None):
    """`python -I -m onecrew.v2.support_spool [--project P] [--state-root S] report ...` (the group word `support` is optional)."""
    args = list(sys.argv[1:] if argv is None else argv)
    index = 0
    while index < len(args):
        if args[index] in ('--project', '--state-root'): index += 2
        elif args[index].startswith(('--project=', '--state-root=')): index += 1
        else: break
    if args[index:index + 1] != ['support']: args.insert(index, 'support')
    return entry(args, index)


if __name__ == '__main__':
    sys.exit(main())
