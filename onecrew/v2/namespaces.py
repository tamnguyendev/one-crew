"""W12b storage identity: new roots are project-scoped; old roots stay in place."""
from pathlib import Path

from ..ledger import LedgerError

LEGACY = 'plan:'
NAMESPACED = 'plan-ns:'
WORKFLOW_VERSION = 1
DEFAULT_CAPABILITIES = ('namespaced-storage', 'finding-register', 'root-budget')
CAPABILITIES = (*DEFAULT_CAPABILITIES, 'internal-plan', 'sequential-engine','parallel-engine', 'execution-mode')
DEPENDENCIES = {'internal-plan': {'namespaced-storage', 'root-budget'},
                'sequential-engine': {'namespaced-storage', 'root-budget', 'internal-plan'},
                'parallel-engine': {'namespaced-storage','root-budget','internal-plan','sequential-engine'},
                'execution-mode': {'namespaced-storage', 'root-budget', 'internal-plan', 'sequential-engine'}}   # 2.4-C, opt-in


def parse(value):
    """Return (bare name, explicit anchor or None), validating the name itself."""
    from .plan import valid_plan_name
    for prefix in (NAMESPACED, LEGACY):
        if isinstance(value, str) and value.startswith(prefix):
            return valid_plan_name(value[len(prefix):]), value
    return valid_plan_name(value), None


def resolve(ledger, conn, value):
    """Find exactly one root in this project; a bare ambiguous name never wins."""
    name, explicit = parse(value)
    if conn is None:
        return None
    keys = (explicit,) if explicit else (LEGACY + name, NAMESPACED + name)
    marks = ','.join('?' for _ in keys)
    rows = conn.execute(f'SELECT id, project_id, project_path, request_key FROM tasks '
                        f'WHERE project_id=? AND request_key IN ({marks})', (ledger.project_id, *keys)).fetchall()
    if len(rows) > 1:
        raise LedgerError(f'Plan {name} is ambiguous in this project: select {LEGACY + name} or {NAMESPACED + name} explicitly.')
    return rows[0] if rows else None


def selector(ledger, value):
    name, explicit = parse(value)
    if explicit:
        return explicit
    with ledger.transaction() as conn:
        row = resolve(ledger, conn, name)
    return row['request_key'] if row else NAMESPACED + name


def _file_sha(path):
    """content_sha of a revision file when the file is well formed and its contract hashes to it, else None (read-only)."""
    import json
    from ..ledger import content_hash
    try:
        document = json.loads(path.read_bytes().decode('utf-8-sig'))
    except (OSError, ValueError):
        return None
    contract = document.get('contract') if isinstance(document, dict) else None
    sha = content_hash(contract) if isinstance(contract, dict) else None
    return sha if sha is not None and sha == document.get('content_sha') else None


def legacy_location(ledger, name):
    """Where the files of THIS project's `plan:<name>` root live (R7-E, T49d E7 / DUPk).

    The old version wrote every `plan:` root to the shared plans/<name>/. A `plan:` root whose files were written in the per-project layout
    plans/<project_id>/<name>/ (EV-J: "root đường dẫn mới mang anchor cũ") must read its OWN files, never another project's same-named root:
    - the shared directory belongs to the earliest `plan:<name>` anchor of the whole ledger (the old version refused a second one across
      projects); a `plan:` root of another project that is not that owner reads plans/<its project_id>/<name>/;
    - the owner reads the shared directory, unless its revision 1 there does not hash to the ledger's revision-1 sha while the per-project
      file does (and no `plan-ns:<name>` root of this project owns that directory).
    Returns (directory, note): note is None on the shared path, else why the per-project path was taken (for error messages)."""
    root = Path(ledger.state_root) / 'plans'
    shared, own = root / name, root / ledger.project_id / name
    with ledger.transaction() as conn:
        if conn is None:
            return shared, None
        rows = conn.execute('SELECT id, project_id, project_path FROM tasks WHERE request_key=? ORDER BY created_at, id', (LEGACY + name,)).fetchall()
        mine = next((r for r in rows if r['project_id'] == ledger.project_id), None)
        if mine is None or rows[0]['id'] == mine['id']:
            if mine is None:
                return shared, None
            first = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='plan.proposed' ORDER BY seq LIMIT 1", (mine['id'],)).fetchone()
            peer = conn.execute('SELECT 1 FROM tasks WHERE project_id=? AND request_key=?', (ledger.project_id, NAMESPACED + name)).fetchone()
            import json
            want = (json.loads(first['payload']) if first else {}).get('sha')
            if peer is None and want and _file_sha(shared / 'v1.json') != want and _file_sha(own / 'v1.json') == want:
                return own, f'revision 1 under plans/{name}/ does not match the ledger hash; plans/{ledger.project_id}/{name}/ does'
            return shared, None
        if conn.execute('SELECT 1 FROM tasks WHERE project_id=? AND request_key=?', (ledger.project_id, NAMESPACED + name)).fetchone():
            raise LedgerError(f'Plan {LEGACY + name} of project {ledger.project_id}: plans/{name}/ belongs to project {rows[0]["project_id"]} and '
                              f'plans/{ledger.project_id}/{name}/ belongs to {NAMESPACED + name} of this project; this root has no directory of its own.')
        return own, f'plans/{name}/ belongs to {LEGACY + name} of project {rows[0]["project_id"]} ({rows[0]["project_path"]}), which is not read'


def plan_dir(ledger, value):
    chosen = selector(ledger, value)
    name, _ = parse(chosen)
    root = Path(ledger.state_root) / 'plans'
    return legacy_location(ledger, name)[0] if chosen.startswith(LEGACY) else root / ledger.project_id / name


def active_file(ledger, value):
    chosen = selector(ledger, value)
    if chosen.startswith(LEGACY):
        name, _ = parse(chosen)
        directory, note = legacy_location(ledger, name)
        if note is None:
            return directory / 'active-plan.json'
    return Path(ledger.state_root) / 'plans' / ledger.project_id / 'active-plan.json'


def workflow_metadata(enabled, capabilities=None):
    if type(enabled) is not bool:
        raise LedgerError('workflow must be a boolean; unsupported workflow versions/capabilities cannot be enabled.')
    if not enabled:
        if capabilities is not None: raise LedgerError('Explicit capabilities require workflow=True.')
        return {}
    selected = list(DEFAULT_CAPABILITIES) if capabilities is None else capabilities
    value = {'workflow_version': WORKFLOW_VERSION, 'capabilities': selected}
    check_workflow(value)
    return {'workflow_version': WORKFLOW_VERSION, 'capabilities': [capability for capability in CAPABILITIES if capability in selected]}


def has_capability(state, capability):
    """Only the original proposal's explicit workflow declaration enables it."""
    return (state.get('workflow_version') == WORKFLOW_VERSION
            and capability in state.get('capabilities', ()))


def check_workflow(payload):
    """Only implemented storage capability is declared in this first slice."""
    if 'workflow_version' not in payload and 'capabilities' not in payload:
        return
    capabilities = payload.get('capabilities')
    if (type(payload.get('workflow_version')) is not int or payload.get('workflow_version') != WORKFLOW_VERSION or not isinstance(capabilities, list)
            or not capabilities or any(not isinstance(capability, str) for capability in capabilities)
            or len(set(capabilities)) != len(capabilities)
            or any(capability not in CAPABILITIES for capability in capabilities)):
        raise LedgerError('Unsupported workflow version or capability; supported: ' + ', '.join(CAPABILITIES) + '.')
    for capability in capabilities:
        if not DEPENDENCIES.get(capability, set()) <= set(capabilities):
            raise LedgerError('Capability ' + capability + ' requires ' + ', '.join(sorted(DEPENDENCIES[capability])) + '.')
