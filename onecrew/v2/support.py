"""2.4-S1: user feedback (SF-01), classification and links (SF-03), status projection and notices (SF-05).

Storage: events on ONE support anchor task per project (request key ANCHOR_KEY, created through task_intake.submit like a plan anchor). No new
table, no new store, and nothing is ever written on a plan root (a closed root stays closed). The kinds are class A (compat.CLASS_A).

  support.feedback        {id, client_key, content_sha, text, expected, image, refs, refs_source, refs_unresolved, runtime, fingerprint, ...}
  support.classified      {feedback, class, basis, by, supersedes}        the latest one wins; the history stays
  support.linked          {feedback, target{kind: plan|finding|request, project_id, ...}, by, class_at_link}
  support.bundle          {feedback, manifest_blob, total_bytes, caps, files}     (diagnostics.py)
  support.user_confirmed  {feedback, reference, by: owner, session}      the owner's own signal; refused inside an AI session

A report is never a failure: it writes no node.verification, finding, receipt or attempt. Refs are attached only when provable (refs_source says
'user' or 'derived:<how>'). Text in a report or a log is data: no code path here reads it as a command, a pin or a permission.
"""
import hashlib
import json
import re
import sys
import uuid
from pathlib import Path

from ..display_core import safe
from ..ledger import LedgerError, canonical, content_hash, key_field, text_field
from . import namespaces, ownership, plan as plans, report as reports

ANCHOR_KEY = 'support:records'        # not a valid plan name: a plan called "support" can never bind this anchor to its root budget
GOAL = 'OneCrew support records (user feedback; no execution)'
KINDS = ('support.feedback', 'support.classified', 'support.linked', 'support.bundle', 'support.user_confirmed',
         'support.target', 'support.artifact', 'support.install_prepared', 'support.install', 'support.recheck', 'support.resumed')   # S2: hotfix.py
NOTICE_KINDS = ('support.classified', 'support.linked', 'support.user_confirmed', 'support.install_prepared', 'support.install', 'support.recheck')
CLASSES = ('task_result', 'environment', 'provider', 'onecrew_runtime', 'new_requirement', 'unclear')
TEXT_MAX = 4000
FEEDBACK_ID = re.compile(r'FB-[0-9a-f]{32}\Z')
ATTEMPT_ID = re.compile(r'ATT-[0-9a-f]{32}\Z')
TASK_ID = re.compile(r'TASK-[0-9a-f]{32}\Z')
CHILD_KEY = re.compile(r'wf:(TASK-[0-9a-f]{32}):([^:]+):g(\d+)\Z')
ENDED = ('accepted', 'closed')
LATER = ('workaround', 'trial_build', 'installed', 'verified_at_target')


class ReportRefused(LedgerError):
    """The report itself is refused (bad input, or the same key with other content). Not a broken ledger: never spooled."""


# ---- runtime ------------------------------------------------------------------------------------------------------------------

def runtime_probe(git=True):
    """What runs: the installed distribution (version + sha256 of its RECORD, or 'unknown' and why), the tree hash of the loaded onecrew code,
    the interpreter, and whether the running code is a checkout. git=False never starts a program (the bundle): the git fields are then the
    ones this process already knows, else 'not probed'."""
    import onecrew
    from importlib import metadata
    from .. import interventions
    here = Path(onecrew.__file__).resolve().parent
    probe = {'executable': sys.executable, 'python': sys.version.split()[0], 'platform': sys.platform, 'code_path': str(here),
             'checkout': (here.parent / 'pyproject.toml').is_file()}
    try:
        dist = metadata.distribution('onecrew')
        installed = Path(dist.locate_file('onecrew')).resolve()
        if installed != here:
            probe.update(dist_version='unknown', record_sha256='unknown',
                         dist_version_reason=f'the running code ({here}) is not the installed distribution {dist.version} ({installed})')
        else:
            record = dist.read_text('RECORD')
            probe.update(dist_version=dist.version,
                         record_sha256=hashlib.sha256(record.encode('utf-8')).hexdigest() if record else 'unknown')
    except Exception as error:                      # not installed (a checkout), or unreadable metadata: unknown, with the reason
        probe.update(dist_version='unknown', record_sha256='unknown', dist_version_reason=f'{type(error).__name__}: {error}'[:300])
    if probe['checkout']:
        found = re.search(r'(?m)^version = "([^"]+)"', (here.parent / 'pyproject.toml').read_text(encoding='utf-8', errors='replace'))
        probe['checkout_version'] = found.group(1) if found else 'unknown'
    if git:
        revision = interventions.runtime_revision()
    elif interventions._REVISION is not None:
        revision = dict(interventions._REVISION)
    else:
        revision = {'tree': interventions._tree(interventions.PACKAGE), 'git': 'not probed', 'dirty': 'not probed'}
    probe.update(tree=revision.get('tree') or 'unknown', git=revision.get('git'), dirty=revision.get('dirty'))
    return probe


# ---- reading ------------------------------------------------------------------------------------------------------------------

def _anchor(conn, project_id):
    row = conn.execute('SELECT id FROM tasks WHERE project_id=? AND request_key=?', (project_id, ANCHOR_KEY)).fetchone() if conn else None
    return row['id'] if row else None


def _rows(conn, anchor, kind=None):
    if not anchor: return []
    sql, args = 'SELECT seq,kind,payload,created_at FROM events WHERE task_id=?', [anchor]
    if kind:
        sql += ' AND kind=?'; args.append(kind)
    return [dict(seq=r['seq'], kind=r['kind'], created_at=r['created_at'], payload=json.loads(r['payload']))
            for r in conn.execute(sql + ' ORDER BY seq', args)]


def _feedback(conn, anchor, ident):
    found = conn.execute("SELECT seq,payload,created_at FROM events WHERE task_id=? AND kind='support.feedback' AND json_extract(payload,'$.id')=?",
                         (anchor, ident)).fetchone() if anchor else None
    return dict(seq=found['seq'], created_at=found['created_at'], payload=json.loads(found['payload'])) if found else None


def _require(conn, ledger, ident):
    if not isinstance(ident, str) or not FEEDBACK_ID.match(ident): raise LedgerError('A feedback id looks like FB-<32 hex>.')
    anchor = _anchor(conn, ledger.project_id)
    found = _feedback(conn, anchor, ident)
    if found is None: raise LedgerError(f'Unknown feedback {ident} in this project.')
    return anchor, found


def _about(conn, anchor, ident):
    return [r for r in _rows(conn, anchor) if r['kind'] != 'support.feedback' and r['payload'].get('feedback') == ident]


def _has_attempts(conn):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='attempts'").fetchone() is not None


# ---- refs: only what can be proven --------------------------------------------------------------------------------------------

def _root_state(ledger, conn, selector):
    try:
        return plans.derive(ledger, conn, selector)
    except LedgerError:
        return None


def _single_bad_node(ledger, conn, selector):
    """(node, generation) of the one held or failed node of an engine root, when there is exactly one; else None."""
    try:
        from . import engine
        view = engine.state(ledger, selector, conn)
    except (LedgerError, KeyError, TypeError, ValueError, OSError, StopIteration):
        return None
    bad = [(nid, r.get('generation')) for nid, r in view['nodes'].items() if r.get('phase') == 'held' or r.get('verification_result') == 'fail']
    return bad[0] if len(bad) == 1 else None


def _derive(ledger, conn, plan, task, attempt):
    refs, source, unresolved = {}, {}, {}

    def put(field, value, how):
        refs[field], source[field] = value, how

    def child(row, how):
        found = CHILD_KEY.match(row['request_key'])
        if found:
            put('root_task', found.group(1), how + '+child-key')
            put('node', found.group(2), how + '+child-key')
            put('generation', int(found.group(3)), how + '+child-key')
        elif row['request_key'].startswith((namespaces.LEGACY, namespaces.NAMESPACED)):
            put('root_task', row['id'], how)

    if attempt is not None:
        put('attempt', attempt, 'user')
        row = (conn.execute('SELECT a.task_id, a.status, t.project_id, t.request_key, t.id FROM attempts a JOIN tasks t ON t.id=a.task_id WHERE a.id=?',
                            (attempt,)).fetchone() if conn and _has_attempts(conn) else None)
        if row is None: unresolved['attempt'] = 'no such attempt in this ledger'
        elif row['project_id'] != ledger.project_id:
            unresolved['attempt'] = 'the attempt belongs to another project: nothing of it is attached'
        else:
            put('task', row['task_id'], 'derived:attempts.task_id')
            put('attempt_status', row['status'], 'derived:attempts.status')
            child(row, 'derived:attempts.task_id')
    if task is not None and 'task' not in refs:
        row = conn.execute('SELECT id, project_id, request_key FROM tasks WHERE id=?', (task,)).fetchone() if conn else None
        if row is None or row['project_id'] != ledger.project_id:
            unresolved['task'] = 'no such task in this project'
        elif not (CHILD_KEY.match(row['request_key']) or row['request_key'].startswith((namespaces.LEGACY, namespaces.NAMESPACED))):
            unresolved['task'] = 'not a plan root or one of its child tasks: not attached'      # the support anchor, a v1 job, ...
        else:
            put('task', task, 'user')
            child(row, 'derived:tasks.request_key')
    elif task is not None and refs.get('task') != task:
        unresolved['task'] = f'the attempt belongs to task {refs["task"]}, not {task}'
    state = None
    if plan is not None:
        state = _root_state(ledger, conn, plan)
        if state is None:
            unresolved['plan'] = 'no such plan in this project'
        elif 'root_task' in refs and refs['root_task'] != state['task_id']:
            unresolved['plan'] = f'{state["selector"]} is not the root of the given task/attempt; the task/attempt root is kept'
            state = None
        else:
            put('plan', state['selector'], 'user')
            put('root_task', state['task_id'], 'derived:plans.derive')
    if state is None and 'root_task' in refs:
        row = conn.execute('SELECT request_key FROM tasks WHERE id=? AND project_id=?', (refs['root_task'], ledger.project_id)).fetchone()
        state = _root_state(ledger, conn, row['request_key']) if row else None
        if state: put('plan', state['selector'], 'derived:root task')
    if state:
        put('revision', state['latest'], 'derived:plans.derive')
        put('status', state['status'], 'derived:plans.derive')
        if 'node' not in refs:
            single = _single_bad_node(ledger, conn, state['selector'])
            if single:
                put('node', single[0], 'derived:engine.state(the single held or failed node)')
                put('generation', single[1], 'derived:engine.state(the single held or failed node)')
    return refs, source, unresolved


# ---- SF-01: report --------------------------------------------------------------------------------------------------------------

def _normalized(text):
    text = re.sub(r'\b[0-9a-f]{12,}\b|\d+', '#', text.casefold())
    return ' '.join(text.split())


def _image(path=None, facts=None):
    if facts is not None:
        if not isinstance(facts, dict) or not re.fullmatch(r'[0-9a-f]{64}', str(facts.get('sha256'))): raise ReportRefused('Spooled image facts are malformed.')
        return {'name': str(facts.get('name', ''))[:200], 'sha256': facts['sha256'], 'bytes': int(facts.get('bytes', 0)), 'stored': False}
    if path is None: return None
    from . import support_spool
    try:
        return support_spool._image(path)
    except (OSError, ValueError) as error:
        raise ReportRefused(str(error)) from error


def _validate(text, expected, plan, task, attempt, client_key, feedback_id):
    try:
        text_field(text, 'text', TEXT_MAX)
        if expected is not None: text_field(expected, 'expected', TEXT_MAX)
        if client_key is not None: key_field(client_key)
        if plan is not None: namespaces.parse(plan)
    except LedgerError as error:
        raise ReportRefused(str(error)) from error
    if feedback_id is not None and not FEEDBACK_ID.match(str(feedback_id)): raise ReportRefused('A feedback id looks like FB-<32 hex>.')
    if attempt is not None and not ATTEMPT_ID.match(str(attempt)): raise ReportRefused('--attempt: an attempt id looks like ATT-<32 hex>.')
    if task is not None and not TASK_ID.match(str(task)): raise ReportRefused('--task: a task id looks like TASK-<32 hex>.')


def _recurrence(text):
    return content_hash({'text': re.sub(r'[^0-9a-z#]+', ' ', _normalized(text)).strip()})[:32]


def report(ledger, *, text, expected=None, image=None, plan=None, task=None, attempt=None, client_key=None, feedback_id=None, spooled=None,
           image_facts=None, runtime_at_report=None):
    """Record one user report on the support anchor; idempotent by client_key (same key + other content -> ReportRefused). Without a key
    the key is support_spool.content_key(text, expected, explicit refs): the same report sent again in this project is the same feedback
    (S1-R08). A spooled report keeps the runtime it was reported under (runtime_at_report) and adds runtime_at_import (S1-R05).

    Returns {recorded, id, duplicate, spooled: False, refs, refs_source, refs_unresolved, possible_duplicates, recurrence_of, runtime, status}."""
    from . import support_spool
    _validate(text, expected, plan, task, attempt, client_key, feedback_id)
    picture = _image(image, image_facts)
    given = {k: v for k, v in (('plan', plan), ('task', task), ('attempt', attempt)) if v is not None}
    content_sha = content_hash({'text': support_spool.lite(text), 'expected': support_spool.lite(expected), 'image': picture and picture['sha256'],
                                'refs': given})
    with ledger.transaction() as conn:
        refs, source, unresolved = _derive(ledger, conn, plan, task, attempt)
    live = runtime_probe()
    if runtime_at_report is not None:
        runtime = dict(runtime_at_report, source='spool')
        if runtime.get('installed_vs_running') not in (None, 'same'): runtime['dist_version'] = 'unknown'
    else:
        runtime = dict(live, source='live')
    fingerprint = content_hash({'text': _normalized(text), 'dist_version': runtime.get('dist_version', 'unknown'), 'plan': refs.get('plan'),
                                'node': refs.get('node')})[:32]
    recurrence = _recurrence(text)
    ident = feedback_id or 'FB-' + uuid.uuid4().hex
    key = client_key or support_spool.content_key(text, expected, given)
    outcome = {}

    def then(conn, anchor):
        prior = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='support.feedback' AND json_extract(payload,'$.client_key')=?",
                             (anchor, key)).fetchone()
        if prior:
            payload = json.loads(prior['payload'])
            if payload['content_sha'] != content_sha:
                raise ReportRefused(f'Report key {key} was already used for a different report ({payload["id"]}); use another --key.')
            outcome.update(payload=payload, duplicate=True, duplicates=[])
            return
        if _feedback(conn, anchor, ident): raise ReportRefused(f'Feedback id {ident} already exists under another key.')
        earlier = _rows(conn, anchor, 'support.feedback')
        duplicates = [r['payload']['id'] for r in earlier if r['payload'].get('fingerprint') == fingerprint]
        handled = {r['payload'].get('feedback') for r in _rows(conn, anchor) if r['kind'] in ('support.install', 'support.recheck')}
        recurs = [r['payload']['id'] for r in earlier if r['payload']['id'] in handled and r['payload'].get('recurrence') == recurrence
                  and (r['payload'].get('refs') or {}).get('plan') == refs.get('plan')]
        payload = {'id': ident, 'client_key': key, 'content_sha': content_sha, 'text': text, 'expected': expected, 'image': picture,
                   'project_id': ledger.project_id, 'project_path': ledger.project_path, 'refs': refs, 'refs_source': source,
                   'refs_unresolved': unresolved, 'runtime': runtime, 'runtime_at_report': runtime, 'fingerprint': fingerprint,
                   'possible_duplicates': duplicates, 'recurrence': recurrence, 'recurrence_of': recurs,
                   'status': 'reported', 'reproduced': 'unknown', 'spooled': spooled}
        if runtime_at_report is not None: payload['runtime_at_import'] = dict(live, source='import')
        plans.emit(ledger, conn, anchor, 'support.feedback', payload)
        outcome.update(payload=payload, duplicate=False, duplicates=duplicates)

    from ..task_intake import submit
    submit(ledger, GOAL, ANCHOR_KEY, mode='audit', _then=then)
    payload = outcome['payload']
    return {'recorded': True, 'id': payload['id'], 'duplicate': outcome['duplicate'], 'spooled': False, 'refs': payload['refs'],
            'refs_source': payload['refs_source'], 'refs_unresolved': payload['refs_unresolved'],
            'possible_duplicates': outcome['duplicates'], 'recurrence_of': payload.get('recurrence_of', []), 'runtime': payload['runtime'],
            'client_key': payload['client_key'], 'status': 'reported',
            'note': 'A report is not a reproduced finding: nothing was marked failed. Sending the same report again gives the same id.'}


def import_spool(ledger):
    """Import every spool file of this project once (by its client key); a malformed file is moved to rejected/ with its reason and the
    others are still imported (S1-R06). Only the bounded fields support_spool.validate checks are read. Each imported file moves to
    imported/ after the commit. Returns {imported, already_recorded, rejected, skipped, counts, other_projects}."""
    from . import support_spool
    imported, already, rejected, skipped = [], [], [], []
    found, others = support_spool.spooled_files(ledger.project, ledger.state_root)
    for path, document in found:
        why = support_spool.validate(document) if document is not None else 'not a JSON object'
        if why is None:
            refs = document.get('refs') or {}
            try:
                result = report(ledger, text=document['text'], expected=document.get('expected'), image_facts=document.get('image'),
                                plan=refs.get('plan'), task=refs.get('task'), attempt=refs.get('attempt'), client_key=document['client_key'],
                                feedback_id=document['id'], runtime_at_report=document.get('runtime_probe') or {'dist_version': 'unknown'},
                                spooled={'spool_id': document['id'], 'reason': document.get('reason'), 'created_at': document.get('created_at'),
                                         'error': document.get('error'), 'ledger': document.get('ledger'),
                                         'provenance': 'spool file (unauthenticated: written by whoever could write the spool folder)'})
            except ReportRefused as error:
                skipped.append({'path': str(path), 'why': str(error)})        # e.g. the same key with other content: kept, never merged
                continue
            (already if result['duplicate'] else imported).append(result['id'])
            try:
                support_spool.mark_imported(path)
            except OSError as error:
                skipped.append({'path': str(path), 'why': f'imported, but the file could not be moved ({type(error).__name__}); a later import skips it'})
            continue
        try:
            moved = support_spool.mark_rejected(path, why)
            rejected.append({'path': str(moved), 'why': why})
        except OSError as error:
            rejected.append({'path': str(path), 'why': why + f' (could not be moved: {type(error).__name__})'})
    return {'imported': imported, 'already_recorded': already, 'rejected': rejected, 'skipped': skipped, 'other_projects': others,
            'counts': {'imported': len(imported), 'already': len(already), 'rejected': len(rejected), 'skipped': len(skipped)}}


# ---- SF-03: classify and link -----------------------------------------------------------------------------------------------------

OWNER_WORDS = ('owner', 'user', 'human')


def _ai_session():
    import os
    return any(name in os.environ for name in ('CLAUDE_CODE_CHILD_SESSION', 'CLAUDECODE'))


def _actor(by):
    """Who records: the --by text, but a claim to be the owner/user is refused inside an AI session (S1-R07); the session is recorded too."""
    if by is not None:
        text_field(by, 'by', 100)
        if by.strip().casefold() in OWNER_WORDS and _ai_session():
            raise LedgerError(f'--by {by} refused: this process runs inside an AI tool session (CLAUDE_CODE_CHILD_SESSION or CLAUDECODE is set).')
        return by
    from ..interventions import actor
    return actor()


def classification(rows):
    found = [r for r in rows if r['kind'] == 'support.classified']
    return dict(found[-1]['payload'], seq=found[-1]['seq']) if found else None


def classify(ledger, ident, cls, basis, by=None):
    """Record the class of a feedback; the latest one wins (supersedes names the previous class). Grants and changes nothing else."""
    if cls not in CLASSES: raise LedgerError(f'A class is one of {", ".join(CLASSES)}.')
    if not isinstance(basis, (list, tuple)) or not 1 <= len(basis) <= 20: raise LedgerError('Give 1-20 --basis references (evidence of the class).')
    basis = [text_field(item, 'basis', 300) for item in basis]
    who = _actor(by)
    with ledger.transaction(write=True) as conn:
        anchor, found = _require(conn, ledger, ident)
        previous = classification(_about(conn, anchor, ident))
        payload = {'feedback': ident, 'class': cls, 'basis': basis, 'by': who, 'session': ownership.session_info(),
                   'supersedes': previous['class'] if previous else None}
        plans.emit(ledger, conn, anchor, 'support.classified', payload)
    return payload


def _plan_row(conn, project_id, value):
    name, explicit = namespaces.parse(value)
    keys = (explicit,) if explicit else (namespaces.LEGACY + name, namespaces.NAMESPACED + name)
    marks = ','.join('?' for _ in keys)
    rows = conn.execute(f'SELECT id, project_id, project_path, request_key FROM tasks WHERE project_id=? AND request_key IN ({marks})',
                        (project_id, *keys)).fetchall()
    if len(rows) > 1: raise LedgerError(f'Plan {name} is ambiguous in that project: name plan:{name} or plan-ns:{name}.')
    if not rows: raise LedgerError(f'No plan {value} in project {project_id}.')
    return rows[0]


def _reader(ledger, row):
    return ledger if row['project_id'] == ledger.project_id else reports._Reader(ledger.state_root, row['project_id'], row['project_path'])


def link(ledger, ident, *, finding=None, plan=None, project_id=None, request=None, by=None):
    """Link a feedback to the work that handles it: a plan (in the OneCrew project for a onecrew_runtime class), a finding with a real receipt,
    or a request. Linking never changes that work (no event on it, no budget, no permission)."""
    if sum(x is not None for x in (finding, request)) + (plan is not None and finding is None) != 1:
        raise LedgerError('Link to exactly one of --finding ID [--plan P], --plan P [--project-id ID] or --request ID.')
    who = _actor(by)
    with ledger.transaction(write=True) as conn:
        anchor, found = _require(conn, ledger, ident)
        rows = _about(conn, anchor, ident)
        latest = classification(rows)
        cls = latest['class'] if latest else None
        home = found['payload']['project_id']
        project = project_id or home
        if cls == 'onecrew_runtime' and (project == home or request is not None):
            raise LedgerError('A onecrew_runtime report is fixed in the OneCrew project with its own plan, approval and budget: link a plan of '
                              'that project (--plan NAME --project-id ID), never a plan, finding, request or budget of the reporting project.')
        if request is not None:
            target = conn.execute('SELECT r.id, r.task_id, r.revision, r.state, t.project_id FROM requests r JOIN tasks t ON t.id=r.task_id '
                                  'WHERE r.id=? AND t.project_id=?', (request, project)).fetchone()
            if target is None: raise LedgerError(f'No request {request} in project {project}.')
            value = {'kind': 'request', 'project_id': project, 'id': target['id'], 'task': target['task_id'], 'revision': target['revision'],
                     'state_at_link': target['state']}
        else:
            root = _plan_row(conn, project, plan or found['payload']['refs'].get('plan') or '')
            reader = _reader(ledger, root)
            state = plans.derive(reader, conn, root['request_key'])
            value = {'kind': 'plan', 'project_id': project, 'selector': root['request_key'], 'root_task': root['id'],
                     'status_at_link': state['status'] if state else None}
            if finding is not None:
                from . import findings as register
                from ..snapshots import Snapshots
                item = next((f for f in register.list_findings(reader, root['request_key']) if f['id'] == finding), None)
                receipt = ((item or {}).get('source') or {}).get('receipt')
                try:
                    real = bool(receipt) and bool(Snapshots(ledger.state_root).read_blob(receipt))
                except (LedgerError, OSError):
                    real = False
                if item is None or not real:
                    raise LedgerError(f'No finding {finding} with a real receipt in {root["request_key"]}: a report alone is not a reproduced finding.')
                value.update(kind='finding', id=finding, receipt=receipt, finding_status=item['status'])
        if any(r['kind'] == 'support.linked' and r['payload']['target'] == value for r in rows):
            return next(r['payload'] for r in rows if r['kind'] == 'support.linked' and r['payload']['target'] == value)
        payload = {'feedback': ident, 'target': value, 'by': who, 'session': ownership.session_info(), 'class_at_link': cls}
        plans.emit(ledger, conn, anchor, 'support.linked', payload)
    return payload


# ---- SF-05: status, confirmation, notices -----------------------------------------------------------------------------------------

def confirm(ledger, ident, reference):
    """The owner says the problem is gone for them. An owner verb: refused inside an AI tool session (like `question answer`)."""
    ownership.refuse_in_ai_session('support confirm')
    text_field(reference, 'reference', 500)
    with ledger.transaction(write=True) as conn:
        anchor, found = _require(conn, ledger, ident)
        prior = [r for r in _about(conn, anchor, ident) if r['kind'] == 'support.user_confirmed']
        if prior: return dict(prior[0]['payload'], already=True)
        payload = {'feedback': ident, 'reference': reference, 'by': 'owner', 'session': ownership.session_info()}
        plans.emit(ledger, conn, anchor, 'support.user_confirmed', payload)
    return payload


def _field(value, evidence=(), **extra):
    return dict({'value': value, 'evidence': list(evidence)}, **extra)


def _status(ledger, conn, anchor, found):
    feedback, rows = found['payload'], _about(conn, anchor, found['payload']['id'])
    links = [r for r in rows if r['kind'] == 'support.linked']
    out = {'feedback': feedback['id'], 'reported': _field(True, [f'event:{found["seq"]}'])}
    proofs = [r for r in links if r['payload']['target']['kind'] == 'finding']
    out['reproduced'] = (_field('yes', [f'finding:{p["payload"]["target"]["selector"]}#{p["payload"]["target"]["id"]}' for p in proofs] +
                                [f'receipt:{p["payload"]["target"]["receipt"]}' for p in proofs]) if proofs else _field('unknown'))
    open_plans, linked = [], []
    for r in links:
        target = r['payload']['target']
        if target['kind'] not in ('plan', 'finding'): continue
        status_now = _plan_status(ledger, conn, target['root_task'])
        linked.append({'kind': target['kind'], 'project_id': target['project_id'], 'selector': target['selector'], 'status': status_now,
                       'event': r['seq']})
        if status_now == 'approved':                   # S1-R04: approved and open; proposed, stopped, accepted or closed is not in progress
            open_plans.append(f'plan:{target["project_id"]}/{target["selector"]} status approved (event:{r["seq"]})')
    out['in_progress'] = _field(bool(open_plans), open_plans)
    out['linked'] = linked
    out['workaround'] = _field(False, [], note='no workaround record exists in this version')
    prepared = [r for r in rows if r['kind'] == 'support.install_prepared' and (r['payload'].get('identity') or {}).get('version') == r['payload'].get('version')]
    out['trial_build'] = _field(bool(prepared), [f'venv {r["payload"]["venv"]} holds onecrew {r["payload"]["version"]} (event:{r["seq"]})' for r in prepared[-1:]],
                                artifact=[f'event:{r["seq"]}' for r in rows if r['kind'] == 'support.artifact'][-1:])
    installs = [r for r in rows if r['kind'] == 'support.install' and r['payload'].get('result') in ('switched', 'rolled_back')]
    switched = bool(installs) and installs[-1]['payload']['result'] == 'switched'
    out['installed'] = _field(switched, [f'event:{installs[-1]["seq"]} hooks run {installs[-1]["payload"]["new_venv"]}'] if switched else [])
    rechecks = [r for r in rows if r['kind'] == 'support.recheck']
    last = rechecks[-1] if rechecks else None
    at_target = bool(last) and last['payload']['environment'] == 'target' and last['payload']['result'] == 'pass' and bool(last['payload'].get('receipt'))
    out['verified_at_target'] = _field(at_target, [f'receipt:{last["payload"]["receipt"]} (event:{last["seq"]})'] if at_target else [],
                                       **({'note': f'last recheck: {last["payload"]["result"]} on the {last["payload"]["environment"]}'} if last and not at_target else {}))
    gates = [r for r in rows if (r['kind'] == 'support.install_prepared' and r['payload'].get('blocked_by'))
             or (r['kind'] == 'support.install' and r['payload'].get('result', '').startswith(('refused', 'blocked')))]
    gate = gates[-1] if gates and (not installs or gates[-1]['seq'] > installs[-1]['seq']) else None
    out['install_blocked'] = _field(None if gate is None else ('blocked_by_' + gate['payload']['blocked_by'] if gate['kind'] == 'support.install_prepared'
                                                              else gate['payload']['result']), [f'event:{gate["seq"]}'] if gate else [])
    refs = feedback['refs']
    blocked = _field('unknown', [], note='no node of a root is referenced')
    if refs.get('node') and refs.get('plan'):
        try:
            from . import engine
            record = engine.state(ledger, refs['plan'], conn)['nodes'].get(refs['node'])
        except (LedgerError, KeyError, TypeError, ValueError, OSError, StopIteration):
            record = None
        if record is not None:
            bad = record.get('phase') == 'held' or record.get('verification_result') == 'fail'
            blocked = _field(bad, [f'node:{refs["plan"]}/{refs["node"]} phase {record.get("phase")} verification {record.get("verification_result")}'])
    if last and last['payload']['result'] != 'pass':
        blocked = _field(True, [f'receipt:{last["payload"].get("receipt")} result {last["payload"]["result"]} on the {last["payload"]["environment"]}'])
    elif at_target:
        blocked = _field(False, [f'receipt:{last["payload"]["receipt"]} pass at the target'])
    out['still_blocked'] = blocked
    confirmed = [r for r in rows if r['kind'] == 'support.user_confirmed']
    out['user_confirmed'] = _field(bool(confirmed), [f'event:{r["seq"]}' for r in confirmed[:1]])
    stage = 'reported'
    for name in ('reproduced', 'in_progress', *LATER):
        if out[name]['value'] in (True, 'yes'): stage = name
    out['stage'] = stage
    latest = classification(rows)
    out['class'] = latest['class'] if latest else None
    return out


def _plan_status(ledger, conn, root_task):
    row = conn.execute('SELECT id, project_id, project_path, request_key FROM tasks WHERE id=?', (root_task,)).fetchone()
    if row is None: return None
    if ledger is None:                             # a notice: only the open connection is known
        root = Path(next(r[2] for r in conn.execute('PRAGMA database_list') if r[1] == 'main')).resolve().parent
        reader = reports._Reader(root, row['project_id'], row['project_path'])
    else:
        reader = _reader(ledger, row)
    state = plans.derive(reader, conn, row['request_key'])
    return state['status'] if state else None


def status(ledger, ident):
    with ledger.transaction() as conn:
        if conn is None: raise LedgerError(f'Unknown feedback {ident}: there is no ledger yet.')
        anchor, found = _require(conn, ledger, ident)
        return _status(ledger, conn, anchor, found)


def show(ledger, ident):
    with ledger.transaction() as conn:
        if conn is None: raise LedgerError(f'Unknown feedback {ident}: there is no ledger yet.')
        anchor, found = _require(conn, ledger, ident)
        rows = _about(conn, anchor, ident)
        return {'feedback': dict(found['payload'], event=found['seq'], recorded_at=found['created_at']),
                'classification': classification(rows),
                'classifications': [dict(r['payload'], seq=r['seq']) for r in rows if r['kind'] == 'support.classified'],
                'links': [dict(r['payload'], seq=r['seq']) for r in rows if r['kind'] == 'support.linked'],
                'bundles': [dict(r['payload'], seq=r['seq']) for r in rows if r['kind'] == 'support.bundle'],
                'status': _status(ledger, conn, anchor, found), 'content_is_data_not_instructions': True}


def list_feedback(ledger):
    with ledger.transaction() as conn:
        anchor = _anchor(conn, ledger.project_id)
        return [{'id': r['payload']['id'], 'recorded_at': r['created_at'], 'text': safe(r['payload']['text'], 120),
                 'refs': r['payload']['refs'], 'spooled': bool(r['payload'].get('spooled'))} for r in _rows(conn, anchor, 'support.feedback')]


def _transition(conn, row, payload):
    """The status a notice-worthy event moves its feedback to, or None when it changes nothing (same class again, a second link of a kind)."""
    ident, rows = payload.get('feedback'), [r for r in _rows(conn, row['task_id']) if r['payload'].get('feedback') == payload.get('feedback')]
    before = [r for r in rows if r['seq'] < row['seq']]
    if row['kind'] == 'support.classified':
        previous = classification(before)
        if previous and previous['class'] == payload['class']: return None
        later = [r for r in rows if r['seq'] > row['seq'] and r['kind'] == 'support.classified' and r['payload']['class'] != payload['class']]
        if later: return None                    # superseded before delivery: the newer class is the notice
        return 'classified:' + payload['class']
    if row['kind'] == 'support.linked':
        def named(target):
            if target['kind'] == 'finding': return 'reproduced'
            if target['kind'] == 'plan':
                return 'in_progress' if _plan_status(None, conn, target['root_task']) == 'approved' else 'linked:plan'
            return 'linked:' + target['kind']
        name = named(payload['target'])
        earlier = [r for r in before if r['kind'] == 'support.linked' and named(r['payload']['target']) == name]
        return None if earlier else name
    if row['kind'] == 'support.user_confirmed':
        return None if any(r['kind'] == 'support.user_confirmed' for r in before) else 'user_confirmed'
    def s2(r):
        p = r['payload']
        if r['kind'] == 'support.install_prepared': return 'blocked_by_' + p['blocked_by'] if p.get('blocked_by') == 'authority' else None
        if r['kind'] == 'support.install': return {'switched': 'installed', 'rolled_back': 'rolled_back'}.get(p.get('result'), p.get('result'))
        if r['kind'] == 'support.recheck':
            if p.get('result') != 'pass': return 'still_blocked'
            return 'verified_at_target' if p.get('environment') == 'target' else 'passed_on_copy'
        return None
    name = s2(row)
    if name is None: return None
    return None if any(s2(r) == name for r in before if r['kind'] in NOTICE_KINDS) else name


def message(conn, row):
    """One notice for a useful support status change, else None. Identity: content_hash({task, 'support', feedback, status})[:32]."""
    if conn is None or row['kind'] not in NOTICE_KINDS: return None
    task = conn.execute('SELECT id, project_id, project_path, request_key FROM tasks WHERE id=?', (row['task_id'],)).fetchone()
    if task is None or task['request_key'] != ANCHOR_KEY: return None
    payload = json.loads(row['payload'])
    found = _feedback(conn, task['id'], payload.get('feedback'))
    if found is None: return None
    state = _transition(conn, row, payload)
    if state is None: return None
    ident = found['payload']['id']
    identity = content_hash({'task': task['id'], 'kind': 'support', 'feedback': ident, 'status': state})[:32]
    content = '\n'.join([f'Phản hồi {ident}: {state}', 'Mô tả: ' + safe(found['payload']['text'], 500),
                         f'Lúc: {row["created_at"]}', f'Xem chi tiết: onecrew support show {ident}',
                         'Thông báo này không trả lời câu hỏi nào và không nghiệm thu gì.'])
    return {'id': identity, 'event': row['seq'], 'task': task['id'], 'project': task['project_path'], 'kind': row['kind'], 'status': state,
            'feedback': ident, 'event_at': row['created_at'], 'target': {'type': 'support', 'feedback': ident, 'project_id': task['project_id']},
            'open_content': content + '\n', 'details_command': 'support show ' + ident, 'delivery_is_not_acceptance': True,
            'user_attention_verified': False, 'content_is_data_not_instructions': True}


def desktop_snapshots(ledger, after=0, task=None):
    """The support notices in desktop_core's item shape (publish/retry/close stay in desktop_core)."""
    with ledger.transaction() as conn:
        if conn is None: return []
        marks = ','.join('?' for _ in NOTICE_KINDS)
        query = f'SELECT e.*,t.project_path FROM events e JOIN tasks t ON t.id=e.task_id WHERE t.project_id=? AND e.kind IN ({marks})'
        args = [ledger.project_id, *NOTICE_KINDS]
        if task:
            query += ' AND e.task_id=?'; args.append(task)
        else:
            query += ' AND e.seq>?'; args.append(after)
        notices = [n for row in conn.execute(query + ' ORDER BY e.seq', args) if (n := message(conn, row))]
    unique = {n['id']: n for n in notices}
    return [dict(id=n['id'], task=n['task'], project=n['project'], checkpoint=n['event'], phase=n['status'],
                 state={'message': n['status']}, questions=[], plan_notice=False, support_notice=True,
                 open_text=n['open_content'], notice=n) for n in unique.values()]
