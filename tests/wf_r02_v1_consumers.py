"""Runs the v1 consumers of `learning.outcome` against one ledger, from whichever tree PYTHONPATH names (the checkout or the archive of the
rollback target), and prints one JSON object. Used by tests/test_wf_r02_outcome.py (T35a E39/E40): the same script, the same ledger, before and
after a v2 root's outcome is written.

  python wf_r02_v1_consumers.py <project> <state-root> <goal> <provider> <model> <v2-task-id|-> <v1-task-id>...
"""
import json
import sys
from pathlib import Path

from onecrew.ledger import Ledger


def main(argv):
    project, state, goal, provider, model, v2_task, *v1_tasks = argv
    ledger = Ledger(Path(project), Path(state))
    out = {}
    from onecrew import budget_policy, eval_observe, learning, skills, task_intake
    rows = task_intake.outcomes(ledger, 200)
    out['task_intake.outcomes'] = {'rows': len(rows), 'tasks': sorted({r['task'] for r in rows})}
    out['learning.outcomes'] = {'rows': len(learning.outcomes(ledger, 200))}
    out['task_intake.recommend'] = task_intake.recommend(ledger, goal, 'audit', provider, model)
    out['budget_policy.recommend'] = budget_policy.recommend(ledger, goal, 'audit', provider, model)
    with ledger.transaction() as conn:
        latest = skills.latest(ledger, conn)
    out['skills.latest'] = {'rows': len(latest), 'tasks': sorted(r['task'] for r in latest), 'good': sorted(r['task'] for r in latest if skills.good(r))}
    out['skills.refresh'] = {'created': len(skills.refresh(ledger))}
    seen = eval_observe.observe(state, list(v1_tasks))
    out['eval_observe.v1'] = json.loads(json.dumps(seen['tasks'], sort_keys=True))
    if v2_task != '-':
        mixed = eval_observe.observe(state, [v2_task])
        out['eval_observe.v2_anchor'] = {'tasks': len(mixed['tasks'])}
    print(json.dumps(out, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
