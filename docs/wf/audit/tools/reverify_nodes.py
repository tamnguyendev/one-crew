"""Re-check the stored candidate artifacts of an engine plan against the declared-output / reference check (round 10).

    python reverify_nodes.py <state-root> <project> <plan> [--out DIR] [--mode out|full] [--allow-state-writes]

No model call and no new worker run. Every path is explicit (nothing is hard-coded). Old receipts are never modified.

mode out  (default, READ-ONLY on the ledger and the snapshot store): for every node with a stored artifact, rebuild its candidate tree,
          materialize it and run the generic output check (`common_verification.output_check`) exactly as CandidateChecker does.
          Milestone commands are NOT re-run. `engine.verify` is not used: it only accepts a node in state `produced` and refuses a
          node that is already `verified`, so this mode calls the checker's own structural function directly.
mode full re-runs the whole CandidateChecker (command and reviewer milestones too) directly on the stored artifact. That appends
          decision events and evidence blobs to the state root; it therefore needs --allow-state-writes and should only be pointed at
          a COPY of a ledger. Reviewer milestones make provider calls through the metered root budget.

Object store: rebuilding a candidate tree writes UNREFERENCED tree/blob objects (no refs, no index, no working-tree change) into the
project's own .git object store, because the shipped GitCandidate adapter does so; point the tool at a copy of the project. The
ledger/state root is not written in mode out.

Writes inventory.json and inventory.md into --out (default: next to this script's cwd, ./reverify-<plan>).
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))   # the worktree this tool ships in

from onecrew import common_verification as cv   # noqa: E402
from onecrew.ledger import Ledger               # noqa: E402
from onecrew.snapshots import Snapshots         # noqa: E402
from onecrew.v2 import engine, internal_plan as ip   # noqa: E402


def stored_receipt(store, receipt):
    if not receipt: return None
    try:
        body = json.loads(store.read_blob(receipt))
    except (OSError, ValueError):
        return {'error': 'unreadable'}
    rows = ((body.get('observed') or {}).get('checks') or [])
    return {'sha': receipt, 'result': body.get('result'), 'milestones': {r.get('id'): r.get('result') for r in rows if isinstance(r, dict)},
            'has_output_check': 'output_check' in (body.get('observed') or {})}


def inspect(ledger, store, view, item, mode, checker, contract=None):
    nid = item['id']; record = view['nodes'][nid]; artifact = record.get('artifact')
    row = {'node': nid, 'state_before': str(record['state']) + '/' + str(record.get('phase')), 'artifact': artifact, 'writes': item['write'],
           'previous_receipt': stored_receipt(store, record.get('verification_receipt')), 'new_receipt': None, 'out': None, 'milestones': None}
    if not artifact:
        row['skipped'] = 'no stored artifact'; return row
    try:
        if mode == 'full':
            observed = checker(item, artifact)
            row['out'] = observed.get('output_check')
            row['milestones'] = {r['id']: r['result'] for r in observed['checks']}
            row['new_receipt'] = {'tree': observed['candidate_tree'], 'rows': observed['checks'], 'note': 'direct CandidateChecker call; engine.verify refuses a verified node'}
        else:
            manifest = cv.snapshot_candidate(ledger, view, nid, artifact)
            tree = cv.candidate_tree(ledger, manifest)
            with tempfile.TemporaryDirectory(prefix='oc-reverify-') as temp:
                checkout = cv.materialized_tree(ledger, tree, temp)
                # R11: the same declared-output expectations CandidateChecker builds (write permission vs required outputs)
                row['out'] = cv.output_check(checkout, item['write'], cv.output_expectations(store, manifest, item, contract, ledger=ledger, view=view), store)
            row['new_receipt'] = {'tree': tree, 'note': 'read-only structural check; no receipt written'}
    except Exception as error:   # keep the inventory complete: a node that cannot be rebuilt is a row, not a crash
        row['error'] = type(error).__name__ + ': ' + str(error)[:300]
    return row


def markdown(plan, mode, rows):
    lines = [f'# Re-verification inventory: {plan}', '', f'Mode: `{mode}`. Nodes: {len(rows)}. '
             f"OUT fail: {sum(1 for r in rows if r['out'] and r['out']['result'] == 'fail')}, "
             f"OUT pass: {sum(1 for r in rows if r['out'] and r['out']['result'] == 'pass')}, "
             f"errors: {sum(1 for r in rows if r.get('error'))}.", '',
             '| node | state before | artifact | previous receipt | new receipt | OUT | refs total/resolved/unresolvable/unverifiable | missing | milestones | reason |',
             '|---|---|---|---|---|---|---|---|---|---|']
    for r in rows:
        out, prev = r['out'] or {}, r['previous_receipt'] or {}
        counts = out.get('counts') or {}
        lines.append('| ' + ' | '.join([
            r['node'], r['state_before'], (r['artifact'] or '-')[:12], (prev.get('sha') or '-')[:10] + ' ' + str(prev.get('result') or ''),
            ((r['new_receipt'] or {}).get('tree') or '-')[:10], out.get('result') or ('error' if r.get('error') else '-'),
            '/'.join(str(counts.get(k, '-')) for k in ('total', 'resolved', 'unresolvable', 'unverifiable')),
            str(len(out.get('missing') or [])) , json.dumps(r['milestones'] or prev.get('milestones') or {}),
            (json.dumps({k: v for k, v in (out.get('reasons') or {}).items() if v}) + ' ' + (out.get('reason') or r.get('error') or r.get('skipped') or '')).replace('|', '/')[:240]]) + ' |')
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('state_root'); parser.add_argument('project'); parser.add_argument('plan')
    parser.add_argument('--out'); parser.add_argument('--mode', choices=('out', 'full'), default='out')
    parser.add_argument('--allow-state-writes', action='store_true')
    args = parser.parse_args(argv)
    if args.mode == 'full' and not args.allow_state_writes:
        parser.error('--mode full appends events and blobs to the state root; pass --allow-state-writes (use a copy of the ledger)')
    ledger = Ledger(args.project, args.state_root)
    store = Snapshots(ledger.state_root)
    with ledger.transaction() as conn:
        root, contract, _sha = ip.context(ledger, conn, args.plan, 'sequential-engine')
        view = engine.state(ledger, root['selector'], conn)
    checker = cv.CandidateChecker(ledger, root['selector']) if args.mode == 'full' else None
    rows = [inspect(ledger, store, view, item, args.mode, checker, contract) for item in view['definition']['nodes']]
    out_dir = Path(args.out or ('reverify-' + args.plan)); out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'inventory.json').write_text(json.dumps({'plan': args.plan, 'root': root['selector'], 'mode': args.mode, 'nodes': rows}, indent=1, sort_keys=True), encoding='utf-8')
    (out_dir / 'inventory.md').write_text(markdown(args.plan, args.mode, rows), encoding='utf-8')
    print(markdown(args.plan, args.mode, rows))
    return 0


if __name__ == '__main__':
    sys.exit(main())
