"""Exact-command bridge for a worker's authorized, bounded Flutter test recipe.

No ledger checkpoint writes or task locks: the parent owns those while waiting.
The context is outside the editable workspace; tests remain trusted native code.
"""
import json
import sys
from pathlib import Path

if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent))

from onecrew.ledger import Ledger, LedgerError, canonical
from onecrew.owned import Owned
from onecrew.snapshots import durable_write
from onecrew.sandbox_gate import task_guard, GateUnavailable
from onecrew.workflow import task_lock


def execute(path):
    context=json.loads(path.read_text(encoding='utf-8'))
    runtime=Owned(Ledger(Path(context['project']),Path(context['state_root'])))
    task_guard(runtime.control,context['task_id'])()
    receipt=path.with_suffix('.receipt.json')
    # Concurrent shell invocations cannot overspend the fixed test cap.
    with task_lock(runtime.ledger,path.stem+'.workspace-tool'):
        history=json.loads(receipt.read_text(encoding='utf-8')) if receipt.exists() else {'results':[]}
        if len(history['results'])>=context['max_tests']:
            raise LedgerError('Test recipe limit reached; preserve evidence and report the blocker.')
        previous=(context.get('prior_test_results',[])+history['results'])[-3:]
        if len(previous)==3 and len({r.get('fingerprint') for r in previous})==1:
            raise LedgerError('Three identical test checkpoints; stop repeating and report evidence.')
        history['results'].append({'status':'started'})
        durable_write(receipt,canonical(history).encode())
        state=context['state'];recipe=context['recipe']
        for prior in context.get('prior_test_results',[])+history['results'][:-1]:
            if 'compiler_only_sources' in prior:
                state['native_change']['local_test_sources']=prior['compiler_only_sources'];break
        try:
            from onecrew.workspace_worker import collect_candidate
            from onecrew.native_change import install_candidate, verify
            value=collect_candidate(runtime,state,{'report':'Worker local test checkpoint.','question':''},recipe,require_test=False)
            install_candidate(runtime,state,value,recipe)
            if recipe.get('restore_cache'):
                from onecrew.workspace_cache import restore
                restore(runtime,context['task_id'],state,recipe)
            result=verify(runtime,context['task_id'],state,recipe)
            result['cache_recoveries']=state['native_change'].get('cache_recoveries',[])
            result['compiler_only_sources']=state['native_change'].get('local_test_sources',{})
        except (LedgerError,OSError,ValueError) as error:
            result={'passed':False,'failure_kind':'environment' if isinstance(error,GateUnavailable) else 'candidate',
                    'detail':str(error)[:2000]}
        from onecrew.snapshots import bytes_hash
        fingerprint=bytes_hash(canonical({'snapshot':state.get('snapshot'),'detail':result.get('detail')}).encode())
        history['results'][-1]=dict(result,status='finished',fingerprint=fingerprint)
        durable_write(receipt,canonical(history).encode())
        # Compiler-only paths/hashes and full receipts stay local, outside model context.
        return {k:v for k,v in result.items() if k in ('passed','detail','failure_kind')}


if __name__=='__main__':
    # canonical() keeps non-ASCII text; a legacy console codepage must not turn a test name into a charmap crash.
    sys.stdout.reconfigure(encoding='utf-8');sys.stderr.reconfigure(encoding='utf-8')
    try:print(canonical(execute(Path(sys.argv[1]))))
    except (LedgerError,OSError,ValueError) as error:
        print(canonical({'passed':False,'detail':str(error)[:2000]}));sys.exit(1)
