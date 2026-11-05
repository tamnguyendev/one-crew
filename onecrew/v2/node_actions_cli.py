"""CLI inputs for preparation and bounded recovery on the common engine."""
import json
from pathlib import Path

from ..ledger import LedgerError
from . import recovery_policy, repair_tasks, test_preparation

ACTIONS = ('prepare-tests', 'repair', 'diagnose', 'replan')


def register(sub):
    for verb in ACTIONS:
        parser = sub.add_parser(verb)
        parser.add_argument('plan')
        if verb == 'diagnose':
            parser.add_argument('node')
        else:
            parser.add_argument('--file', type=Path, required=True)


def execute(opts, ledger):
    if opts.command == 'diagnose':
        from . import engine
        node = engine.state(ledger, opts.plan)['nodes'].get(opts.node, {})
        if node.get('phase') == 'held' and str(node.get('classification', '')).startswith('executor_'):
            return engine.next_action(ledger, opts.plan, node=opts.node)
        return recovery_policy.assess(ledger, opts.plan, opts.node)
    body = json.loads(opts.file.read_text(encoding='utf-8-sig'))
    allowed = {
        'prepare-tests': {'implementation', 'node_id', 'write', 'checks', 'estimate_seconds',
                          'execution_cap_seconds', 'budget_calls', 'reason', 'evidence', 'read', 'executor'},
        'repair': {'target', 'failed_node', 'reason', 'evidence', 'receipt'},
        'replan': {'failed_node', 'nodes', 'reason', 'evidence'},
    }
    if not isinstance(body, dict) or set(body) - allowed[opts.command]:
        raise LedgerError('Unexpected fields for ' + opts.command + '; authority and acceptance cannot be changed here.')
    handler = {'prepare-tests': test_preparation.prepare, 'repair': repair_tasks.prepare,
               'replan': recovery_policy.replan}[opts.command]
    return handler(ledger, opts.plan, **body)
