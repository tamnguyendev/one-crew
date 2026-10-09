"""Two disjoint DAG units share a root; one coordinator publishes each checkpoint."""
from concurrent.futures import ThreadPoolExecutor, as_completed

from .control import CapacityWait
from .ledger import LedgerError, content_hash, canonical
from .supervisor import Supervisor


def ready_batch(state):
    ready = [r for r in state['plan']['tasks'] if r['id'] not in state['done'] and set(r['depends_on']) <= set(state['done'])]
    if len(ready) < 2:
        return ready[:1]
    first = ready[0]
    second = next((r for r in ready[1:] if not set(r['owned']) & set(first['owned'])), None)
    return [first, second] if second else [first]


def round(workflow, task_id, sequence, state, ready, common, profile):
    from .workflow import artifacts, artifact_schema
    control = workflow.control
    ledger = workflow.ledger
    started_here = False
    prompts = {}
    if not state.get('parallel_pending'):
        started_here = True
        state['parallel_pending'] = []
        base = state['snapshot']
        configuration = control.status(task_id)
        for item in ready[:2]:
            context = workflow.store.context(base)
            from .amendment import spec_for
            spec = spec_for(state, ledger.task(task_id, full=True))
            prompt = ('You implement ONE SLICE, not the entire project. No tools. Return complete UTF-8 contents only for the exact owned paths of YOUR ASSIGNMENT. All other paths are read-only, even if the full spec mentions them.\nREAD-ONLY PROJECT SPEC\n'
                      + spec + '\nREAD-ONLY SOURCE\n' + canonical(context)
                      + '\nYOUR ONLY ASSIGNMENT\n' + canonical(item)
                      + '\nOUTPUT FILES MUST BE A SUBSET OF: ' + canonical(item['owned']))
            schema = artifact_schema(item['owned'])
            if len(prompt) > 80_000:
                raise LedgerError('Parallel worker context exceeds 80000 characters.')
            operation = {'unit': 'task:' + item['id'], 'stage': item['id'], 'snapshot': base,
                         'owned': item['owned'], 'prompt_hash': content_hash(prompt),
                         'schema_hash': content_hash(schema)}
            next_sequence = [sequence]

            def checkpoint(conn, attempt):
                current = conn.execute("SELECT COALESCE(MAX(seq),0) FROM events WHERE task_id=? AND kind='workflow.checkpoint'", (task_id,)).fetchone()[0]
                if current != sequence:
                    raise LedgerError('Parallel checkpoint changed during admission.')
                state['parallel_pending'].append({'attempt': attempt['id'], 'task': item['id'],
                                                   'owned': item['owned'], 'base': base})
                ledger._event(conn, task_id, 'workflow.checkpoint', state)
                next_sequence[0] = conn.execute('SELECT last_insert_rowid()').fetchone()[0]

            try:
                attempt = control.reserve(task_id, configuration['revision'], f'parallel:{sequence}:{item["id"]}',
                                          operation, on_reserved=checkpoint)
                sequence = next_sequence[0]
                prompts[attempt['id']] = prompt
            except (CapacityWait, LedgerError):
                if not state['parallel_pending']:
                    raise
                break  # First admitted unit can progress even when the second slot/budget is unavailable.
    records = list(state['parallel_pending'])

    def execute(record):
        attempt = control.attempt(record['attempt'])
        if started_here and attempt['status'] == 'reserved':
            workflow.worker.run(attempt, prompts[attempt['id']], artifact_schema(record['owned']), profile)
        elif attempt['status'] != 'settled':
            outcome = Supervisor(control).reconcile(attempt['id'])
            if outcome['status'] != 'settled':
                raise LedgerError('Parallel writer must stop/reconcile before its unit can continue.')
        return workflow.worker.result(control.attempt(attempt['id']))

    # Thread workers write only their isolated provider IO; the coordinator alone merges artifacts.
    errors = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(execute, record): record for record in records}
        for future in as_completed(futures):
            record = futures[future]
            try:
                value, usage = future.result()
                if not any(r['attempt'] == record['attempt'] for r in state['usage']):
                    state['usage'].append({'attempt': record['attempt'], 'reported': usage})
                changes = artifacts(value, record['owned'])
                before = state['snapshot']
                # Disjoint ownership is validated before dispatch. Never merge a changed owned baseline.
                current = workflow.store.load(before)['files']
                original = workflow.store.load(record['base'])['files']
                if any(current[p]['working'] != original[p]['working'] for p in record['owned']):
                    raise LedgerError('Parallel ownership conflict; candidate not published.')
                after = workflow.store.overlay(before, changes, record['owned'])
                if workflow.store.context(before) == workflow.store.context(after):
                    raise LedgerError('No source progress from parallel unit.')
                state['snapshot'] = after
                state['done'].append(record['task'])
                state['outputs'].append({'revision': after, 'base': before, 'summary': value['summary'],
                                         'stage': record['task'], 'verification': 'pending', 'acceptance': 'pending'})
                state['backlog'].extend(value['backlog'])
                state['parallel_pending'] = [r for r in state['parallel_pending'] if r['attempt'] != record['attempt']]
            except ValueError as error:
                errors.append(record['task'] + ': ' + str(error))
            sequence = workflow.persist(task_id, sequence, state)
    if errors:
        raise LedgerError('; '.join(errors))
    return sequence
