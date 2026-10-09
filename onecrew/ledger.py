"""Durable P1a task/inbox records. No worker execution or trusted grants."""
from __future__ import annotations

from contextlib import contextmanager
import datetime as dt
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import uuid

from .specs import Project, SpecError, clean_text, digest

VERSION = 1
APP_ID = 0x4F435257
MAX_JSON = 65536
DDL = (
    """CREATE TABLE tasks (
        id TEXT PRIMARY KEY, project_id TEXT NOT NULL, project_path TEXT NOT NULL,
        request_key TEXT NOT NULL, revision TEXT NOT NULL, payload TEXT NOT NULL,
        created_at TEXT NOT NULL, deadline TEXT NOT NULL,
        UNIQUE(project_id, request_key))""",
    """CREATE TABLE requests (
        id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
        request_key TEXT NOT NULL, initial_hash TEXT NOT NULL,
        revision TEXT NOT NULL, previous_revision TEXT, version INTEGER NOT NULL,
        payload TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('pending','answered')),
        answer TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE(task_id, request_key))""",
    """CREATE TABLE events (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT NOT NULL REFERENCES tasks(id), kind TEXT NOT NULL,
        payload TEXT NOT NULL, created_at TEXT NOT NULL)""",
    "CREATE INDEX events_task ON events(task_id, seq)",
)


class LedgerError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def content_hash(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def utcnow():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def text_field(value, name, maximum=2000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or not clean_text(value):
        raise LedgerError(f'{name}: expected non-empty text, at most {maximum} characters.')
    return value


def key_field(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', value):
        raise LedgerError('Request key must contain 1-128 letters, digits, _, ., :, or -.')
    return value


def exact_fields(value, fields, name):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise LedgerError(f'{name}: expected fields {", ".join(fields)}.')


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise LedgerError(f'Duplicate JSON key: {key}')
            result[key] = value
        return result

    def invalid_constant(value):
        raise LedgerError(f'Invalid JSON constant: {value}')

    with Path(path).open('rb') as stream:
        data = stream.read(MAX_JSON + 1)
    if len(data) > MAX_JSON:
        raise LedgerError('JSON file exceeds 64 KiB.')
    return json.loads(data.decode('utf-8-sig'), object_pairs_hook=pairs, parse_constant=invalid_constant)


def validate_grant(value):
    exact_fields(value, ('schema_version', 'permissions', 'limits', 'source'), 'Grant intent')
    if type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise LedgerError('Unsupported grant schema_version.')
    permissions = value['permissions']
    if not isinstance(permissions, list) or len(permissions) > 20:
        raise LedgerError('permissions must be a list of at most 20 action names.')
    for permission in permissions:
        key_field(permission)
    if len(set(permissions)) != len(permissions):
        raise LedgerError('Duplicate permissions.')
    exact_fields(value['limits'], ('max_calls', 'max_seconds'), 'limits')
    for key, cap in (('max_calls', 10000), ('max_seconds', 28800)):
        number = value['limits'][key]
        if type(number) is not int or not 1 <= number <= cap:
            raise LedgerError(f'{key}: expected integer from 1 to {cap}.')
    text_field(value['source'], 'source')
    return json.loads(canonical(value))


def validate_question(value):
    exact_fields(value, ('schema_version', 'question', 'reason', 'impact', 'options',
                         'recommendation', 'action'), 'Question')
    if type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise LedgerError('Unsupported question schema_version.')
    for field in ('question', 'reason', 'impact'):
        text_field(value[field], field)
    options = value['options']
    if not isinstance(options, list) or not 2 <= len(options) <= 8:
        raise LedgerError('Question requires 2-8 options.')
    ids = []
    for option in options:
        exact_fields(option, ('id', 'label'), 'Option')
        ids.append(key_field(option['id']))
        text_field(option['label'], 'Option label', 500)
    if len(set(ids)) != len(ids) or value['recommendation'] not in ids:
        raise LedgerError('Options must be unique and recommendation must match an option.')
    exact_fields(value['action'], ('type', 'parameters'), 'Action')
    key_field(value['action']['type'])
    if not isinstance(value['action']['parameters'], dict):
        raise LedgerError('Action parameters must be an object.')
    encoded = canonical(value)
    if len(encoded.encode('utf-8')) > MAX_JSON:
        raise LedgerError('Question exceeds 64 KiB.')
    return json.loads(encoded)


class Ledger:
    def __init__(self, project, state_root=None):
        self.project = Path(project).resolve()
        if not self.project.is_dir():
            raise LedgerError('Project directory does not exist.')
        self.project_path = os.path.normcase(str(self.project))
        self.project_id = digest(self.project_path)
        default = Path(os.environ['LOCALAPPDATA']) / 'OneCrew' if os.environ.get('LOCALAPPDATA') else Path.home() / '.onecrew'
        self.state_root = Path(state_root if state_root is not None else default).resolve()
        if self.state_root.is_relative_to(self.project):
            raise LedgerError('Ledger state must be outside the project workspace.')
        self.path = self.state_root / 'ledger.sqlite3'

    @contextmanager
    def transaction(self, write=False):
        # Readers never create or migrate state. IMMEDIATE serializes local mutations.
        if not write and not self.path.exists():
            yield None
            return
        if write:
            self.state_root.mkdir(parents=True, exist_ok=True)
        uri = self.path.as_uri() + ('?mode=rwc' if write else '?mode=ro')
        conn = sqlite3.connect(uri, uri=True, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('PRAGMA foreign_keys=ON')
            if write:
                conn.execute('PRAGMA synchronous=FULL')
            conn.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            version = conn.execute('PRAGMA user_version').fetchone()[0]
            app_id = conn.execute('PRAGMA application_id').fetchone()[0]
            if version == 0 and app_id == 0:
                tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                if tables:
                    raise LedgerError('Unrecognized database; migration required, no changes made.')
                if not write:
                    yield None
                    conn.commit()
                    return
                for statement in DDL:
                    conn.execute(statement)
                conn.execute(f'PRAGMA application_id={APP_ID}')
                conn.execute(f'PRAGMA user_version={VERSION}')
            elif version not in (VERSION, 2, 3) or app_id != APP_ID:
                raise LedgerError('Unsupported ledger schema; use a compatible version or explicit migration.')
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _task(self, conn, task_id):
        row = conn.execute('SELECT * FROM tasks WHERE id=? AND project_id=?',
                           (task_id, self.project_id)).fetchone() if conn else None
        if row is None:
            raise LedgerError('Unknown task in this project.')
        return row

    def _request(self, conn, request_id):
        row = conn.execute('SELECT r.* FROM requests r JOIN tasks t ON t.id=r.task_id '
                           'WHERE r.id=? AND t.project_id=?', (request_id, self.project_id)).fetchone() if conn else None
        if row is None:
            raise LedgerError('Unknown request in this project.')
        return row

    def _event(self, conn, task_id, kind, payload):
        conn.execute('INSERT INTO events(task_id,kind,payload,created_at) VALUES(?,?,?,?)',
                     (task_id, kind, canonical(payload), utcnow()))

    @staticmethod
    def _request_view(row):
        return {key: row[key] for key in ('id', 'task_id', 'revision', 'previous_revision',
                                         'version', 'state', 'created_at', 'updated_at')} | {
            'question': json.loads(row['payload']),
            'answer': json.loads(row['answer']) if row['answer'] else None,
            'action_applied': False,
        }

    def _task_view(self, conn, row, full=False):
        payload = json.loads(row['payload'])
        pending = conn.execute("SELECT COUNT(*) FROM requests WHERE task_id=? AND state='pending'",
                               (row['id'],)).fetchone()[0]
        result = {key: row[key] for key in ('id', 'project_id', 'revision', 'created_at', 'deadline')}
        result.update(root_task_id=row['id'], title=payload['title'], spec_id=payload['spec_id'],
                      spec_revision=payload['spec_revision'], grant_revision=content_hash(payload['grant']),
                      execution='waiting' if pending else 'queued', waiting_reason='user' if pending else None,
                      verification='pending', acceptance='not_requested', pending_requests=pending,
                      dispatch_enabled=False, grant_status='unverified_local',
                      budget={'limits': payload['grant']['limits'], 'used_calls': 0, 'reserved_calls': 0},
                      deadline_expired=dt.datetime.now(dt.timezone.utc) >= dt.datetime.fromisoformat(row['deadline']))
        if conn.execute('PRAGMA user_version').fetchone()[0] >= 2:
            execution = conn.execute('SELECT * FROM executions WHERE task_id=?', (row['id'],)).fetchone()
            if execution:
                result['execution'] = execution['status']
                result['budget'].update(used_calls=execution['used_calls'], reserved_calls=execution['reserved_calls'])
                result['control_revision'] = execution['revision']
                result['cancel_requested'] = bool(execution['cancel_requested'])
                checkpoint = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='workflow.checkpoint' ORDER BY seq DESC LIMIT 1", (row['id'],)).fetchone()
                if checkpoint:
                    workflow = json.loads(checkpoint['payload'])
                    result.update(verification=workflow['verification'], acceptance=workflow['acceptance'],
                                  snapshot=workflow['snapshot'], message=workflow['message'],
                                  dispatch_enabled=True, grant_status='local_operator_enabled')
                    if workflow.get('waiting_reason') and execution['status'] not in ('cancelled', 'completed', 'failed', 'paused'):
                        result.update(execution='waiting', waiting_reason=workflow['waiting_reason'])
        if full:
            result['handoff'] = payload
            result['requests'] = [self._request_view(r) for r in conn.execute(
                'SELECT * FROM requests WHERE task_id=? ORDER BY created_at,id', (row['id'],))]
        return result

    def submit(self, spec_id, revision, request_key, grant):
        key_field(request_key)
        grant = validate_grant(grant)
        if not isinstance(revision, str) or not re.fullmatch('[0-9a-f]{64}', revision):
            raise LedgerError('Use the full 64-character spec revision from spec review --json.')
        # An acknowledged submission remains replayable even if the source spec is later removed.
        with self.transaction() as conn:
            existing = conn.execute('SELECT * FROM tasks WHERE project_id=? AND request_key=?',
                                    (self.project_id, request_key)).fetchone() if conn else None
            if existing:
                self._same_submission(existing, spec_id, revision, grant)
                return self._task_view(conn, existing)
        spec = Project(self.project).find(spec_id)
        if revision != spec.revision:
            raise LedgerError('Spec revision is stale; review the current spec before submitting.')
        payload = {'schema_version': 1, 'project_id': self.project_id, 'project_path': self.project_path,
                   'spec_id': spec.id, 'spec_revision': spec.revision, 'spec_text': spec.text,
                   'title': spec.title, 'grant': grant}
        created = utcnow()
        deadline = (dt.datetime.fromisoformat(created) + dt.timedelta(seconds=grant['limits']['max_seconds'])).isoformat()
        with self.transaction(write=True) as conn:
            existing = conn.execute('SELECT * FROM tasks WHERE project_id=? AND request_key=?',
                                    (self.project_id, request_key)).fetchone()
            if existing:
                self._same_submission(existing, spec_id, revision, grant)
                return self._task_view(conn, existing)
            task_id = 'TASK-' + uuid.uuid4().hex
            conn.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',
                         (task_id, self.project_id, self.project_path, request_key, content_hash(payload),
                          canonical(payload), created, deadline))
            self._event(conn, task_id, 'task.submitted', {'revision': content_hash(payload), 'request_key': request_key})
            return self._task_view(conn, self._task(conn, task_id))

    @staticmethod
    def _same_submission(row, spec_id, revision, grant):
        old = json.loads(row['payload'])
        if old['spec_id'] != spec_id or old['spec_revision'] != revision or old['grant'] != grant:
            raise LedgerError('Submission key already exists with different spec or grant content.')

    def tasks(self):
        with self.transaction() as conn:
            return [self._task_view(conn, row) for row in conn.execute(
                'SELECT * FROM tasks WHERE project_id=? ORDER BY created_at,id', (self.project_id,))] if conn else []

    def task(self, task_id, full=False):
        with self.transaction() as conn:
            return self._task_view(conn, self._task(conn, task_id), full)

    def requests(self, task_id=None, pending=False):
        with self.transaction() as conn:
            if task_id:
                self._task(conn, task_id)
            if conn is None:
                return []
            query = 'SELECT r.* FROM requests r JOIN tasks t ON t.id=r.task_id WHERE t.project_id=?'
            params = [self.project_id]
            if task_id:
                query += ' AND r.task_id=?'
                params.append(task_id)
            if pending:
                query += " AND r.state='pending'"
            return [self._request_view(r) for r in conn.execute(query + ' ORDER BY r.created_at,r.id', params)]

    def request(self, request_id):
        with self.transaction() as conn:
            view = self._request_view(self._request(conn, request_id))
            effect = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='request.consumed' AND json_extract(payload,'$.request_id')=? ORDER BY seq DESC LIMIT 1",
                                  (view['task_id'], request_id)).fetchone()
            view['controller_effect'] = json.loads(effect['payload']) if effect else None
            return view

    def create_request(self, task_id, request_key, question):
        key_field(request_key)
        question = validate_question(question)
        with self.transaction(write=True) as conn:
            task = self._task(conn, task_id)
            old = conn.execute('SELECT * FROM requests WHERE task_id=? AND request_key=?',
                               (task_id, request_key)).fetchone()
            initial_hash = content_hash(question)
            if old:
                if old['initial_hash'] != initial_hash:
                    raise LedgerError('Request key already exists with different content; use request revise.')
                return self._request_view(old)
            request_id = 'REQ-' + uuid.uuid4().hex
            revision = content_hash({'task_revision': task['revision'], 'id': request_id, 'version': 1, 'question': question})
            stamp = utcnow()
            conn.execute('INSERT INTO requests VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                         (request_id, task_id, request_key, initial_hash, revision, None, 1,
                          canonical(question), 'pending', None, stamp, stamp))
            view = self._request_view(self._request(conn, request_id))
            self._event(conn, task_id, 'request.created', view)
            return view

    def revise_request(self, request_id, revision, question):
        question = validate_question(question)
        with self.transaction(write=True) as conn:
            row = self._request(conn, request_id)
            if row['previous_revision'] == revision and json.loads(row['payload']) == question:
                return self._request_view(row)
            if row['revision'] != revision or row['state'] != 'pending':
                raise LedgerError('Stale revision or request already answered; inspect current request.')
            if json.loads(row['payload']) == question:
                return self._request_view(row)
            task = self._task(conn, row['task_id'])
            version = row['version'] + 1
            new_revision = content_hash({'task_revision': task['revision'], 'id': request_id,
                                         'version': version, 'question': question})
            conn.execute('UPDATE requests SET revision=?,previous_revision=?,version=?,payload=?,updated_at=? WHERE id=?',
                         (new_revision, revision, version, canonical(question), utcnow(), request_id))
            view = self._request_view(self._request(conn, request_id))
            self._event(conn, row['task_id'], 'request.revised', view)
            return view

    def reply(self, request_id, revision, choice, source='terminal', reference='local user input'):
        text_field(source, 'source', 200)
        text_field(reference, 'reference')
        with self.transaction(write=True) as conn:
            row = self._request(conn, request_id)
            if revision != row['revision']:
                raise LedgerError('Stale request revision; review the current question and action.')
            options = json.loads(row['payload'])['options']
            if choice not in [option['id'] for option in options]:
                raise LedgerError('Choice does not match an option in this revision.')
            if row['state'] == 'answered':
                receipt = json.loads(row['answer'])
                if receipt['choice'] == choice:
                    return receipt
                raise LedgerError('Conflicting reply: request already answered.')
            receipt = {'id': 'REPLY-' + uuid.uuid4().hex, 'request_id': request_id,
                       'revision': revision, 'choice': choice, 'recorded_at': utcnow(),
                       'provenance': {'actor': getpass.getuser(), 'source': source, 'reference': reference,
                                      'trust': 'local_attribution_only'}, 'action_applied': False}
            conn.execute("UPDATE requests SET state='answered',answer=?,updated_at=? WHERE id=? AND state='pending' AND revision=?",
                         (canonical(receipt), receipt['recorded_at'], request_id, revision))
            self._event(conn, row['task_id'], 'request.answered', receipt)
            return receipt

    def events(self, task_id, after=0):
        if type(after) is not int or after < 0:
            raise LedgerError('Event cursor must be a non-negative integer.')
        with self.transaction() as conn:
            self._task(conn, task_id)
            return [dict(row) | {'payload': json.loads(row['payload'])} for row in conn.execute(
                'SELECT * FROM events WHERE task_id=? AND seq>? ORDER BY seq LIMIT 200', (task_id, after))]
