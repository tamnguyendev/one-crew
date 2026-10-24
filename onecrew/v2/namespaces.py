"""W12b storage identity: new roots are project-scoped; old roots stay in place."""
from pathlib import Path

from ..ledger import LedgerError

LEGACY = 'plan:'
NAMESPACED = 'plan-ns:'
WORKFLOW_VERSION = 1
DEFAULT_CAPABILITIES = ('namespaced-storage', 'finding-register', 'root-budget')
CAPABILITIES = (*DEFAULT_CAPABILITIES, 'internal-plan', 'sequential-engine')
DEPENDENCIES = {'internal-plan': {'namespaced-storage', 'root-budget'},
                'sequential-engine': {'namespaced-storage', 'root-budget', 'internal-plan'}}


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


def plan_dir(ledger, value):
    chosen = selector(ledger, value)
    name, _ = parse(chosen)
    root = Path(ledger.state_root) / 'plans'
    return root / name if chosen.startswith(LEGACY) else root / ledger.project_id / name


def active_file(ledger, value):
    chosen = selector(ledger, value)
    if chosen.startswith(LEGACY):
        return plan_dir(ledger, chosen) / 'active-plan.json'
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
