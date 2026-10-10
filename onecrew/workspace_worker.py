"""Scoped Claude edit/test sessions; the independent gate still owns acceptance."""
import json
import shlex
import sys
import uuid
from pathlib import Path

from .ledger import LedgerError, canonical
from .native_audit import NativeClaude
from .snapshots import safe_file, bytes_hash, durable_write
from .subscription import CLAUDE_AUTH_ARGS, environment
from .supervisor import Supervisor

REPORT_SCHEMA={'type':'object','properties':{'report':{'type':'string'},'question':{'type':'string'}},
               'required':['report','question'],'additionalProperties':False}


def edit_permissions(workspace,owned):
    """CLI Edit rules also govern Write; anchor exact files independently of cwd."""
    rules=[]
    for name in owned:
        target=safe_file(Path(workspace),name).resolve().as_posix()
        if len(target)>2 and target[1]==':':target='/'+target[0].lower()+target[2:]
        if not target.startswith('/'):raise LedgerError('Native scope must be absolute.')
        # Claude uses gitignore pattern syntax. Literal bracket/negation names
        # must never broaden a grant or stop matching their own path.
        target=''.join('\\'+c if c in '[]*!?#' else c for c in target)
        rules.append('Edit(/'+target+')')
    return rules


def inventory(workspace):
    result={}
    for path in workspace.rglob('*'):
        name=path.relative_to(workspace).as_posix()
        safe_file(workspace,name)  # also rejects links/junctions
        if path.is_file():result[name]=bytes_hash(path.read_bytes())
        if len(result)>30000:raise LedgerError('Worker workspace inventory exceeds limit.')
    return result


def invocation_context(runtime,task_id,state,recipe):
    native=state['native_change']
    # Reuse the durable invocation context when consuming an already paid result.
    if ('result_pending' in native or state.get('pending')) and native.get('tool_context'):
        path=Path(native['tool_context'])
    else:
        if native.get('continuation_ready'):
            collect_candidate(runtime,state,{},recipe,require_test=False)
            observed=inventory(Path(native['workspace']))
            if {p:observed.get(p) for p in recipe['owned']}!=native['timeout_checkpoints'][-1]['owned']:
                raise LedgerError('Owned files changed after timeout checkpoint; reconcile before continuation.')
            native.pop('continuation_ready')
        path=runtime.ledger.state_root/'workspace-tools'/(uuid.uuid4().hex+'.json')
        if 'tool_baseline' not in native:
            native['tool_baseline']=inventory(Path(native['workspace']))
        native['tool_context']=str(path)
        context={'project':str(runtime.ledger.project),'state_root':str(runtime.ledger.state_root),
                 'task_id':task_id,'state':state,'recipe':recipe,'max_tests':8,
                 'prior_test_results':native.get('continuation_tests',[])}
        durable_write(path,canonical(context).encode())
    command=' '.join(shlex.quote(p.replace('\\','/')) for p in (
        sys.executable,str(Path(__file__).with_name('workspace_tools.py')),str(path)))
    return {'test_command':command,'native_owned':recipe['owned']}


def checkpoint_timeout(runtime,task_id):
    """Consume a settled timeout once; preserve scope/session, never replay a launch.

    Called under the task lock. Returning True means a durable continuation was
    recorded, not that a new model call or a successful candidate exists.
    """
    from .native_audit import check_native_tools
    from .sandbox_gate import task_guard
    from .ledger import content_hash
    seq,state=runtime.state(task_id)
    control=runtime.control.status(task_id)
    recipe=control['configuration']['profile'].get('native_change',{})
    native=state.get('native_change',{})
    if (recipe.get('execution')!='workspace' or native.get('stage')!='work'
            or not state.get('pending')):return False
    attempt=runtime.control.attempt(state['pending'])
    if attempt['status']!='settled':return False
    receipt=json.loads(attempt['result'])
    if receipt.get('reason')!='timeout':return False
    if receipt.get('tree_stopped') is not True:
        raise LedgerError('Timeout process tree is not confirmed stopped; no continuation.')
    if any(a['status']!='settled' for a in control['attempts']):
        raise LedgerError('Another attempt is unsettled; no timeout continuation.')
    task_guard(runtime.control,task_id)()
    if runtime.ledger.requests(task_id,pending=True):raise LedgerError('Pending user decision blocks continuation.')
    if control['used_calls']+control['reserved_calls']>=control['budget']['limits']['max_calls']:
        raise LedgerError('Root call budget exhausted; timeout evidence preserved.')
    path=Path(receipt['stdout'])
    if path.stat().st_size>16_000_000:raise LedgerError('Timeout stream exceeds evidence limit.')
    raw=path.read_bytes();lines=raw.splitlines(keepends=True);events=[]
    for index,line in enumerate(lines):
        if not line.strip():continue
        try:event=json.loads(line)
        except (ValueError,UnicodeError):
            # A killed writer can leave one incomplete final JSON line.
            if index==len(lines)-1 and not line.endswith(b'\n'):break
            raise LedgerError('Malformed timeout stream; cannot continue safely.') from None
        if not isinstance(event,dict):raise LedgerError('Malformed timeout envelope.')
        events.append(event)
    init=[e for e in events if e.get('type')=='system' and e.get('subtype')=='init']
    session=native['worker_session']
    if (len(init)!=1 or init[0].get('session_id')!=session
            or any(e.get('session_id') not in (None,session) for e in events)):
        raise LedgerError('Timeout session identity is missing or mismatched.')
    if any(e.get('type')=='result' for e in events):
        raise LedgerError('Timeout contains terminal result; preserve for reconciliation, not replay.')
    calls,denied=check_native_tools(events,WorkspaceClaude.allowed_native_tools)
    if any(c.get('name')=='StructuredOutput' and c.get('input',{}).get('question') for c in calls):
        raise LedgerError('Timeout includes an unresolved solution question; no automatic continuation.')
    # Verify all non-owned bytes and retain the unfinished owned files as-is.
    collect_candidate(runtime,state,{},recipe,require_test=False)
    observed=inventory(Path(native['workspace']))
    owned={name:observed.get(name) for name in recipe['owned']}
    history_path=Path(native['tool_context']).with_suffix('.receipt.json')
    history=json.loads(history_path.read_text(encoding='utf-8')) if history_path.exists() else {'results':[]}
    tests=history.get('results',[])
    for row in tests:
        if 'compiler_only_sources' in row:native['local_test_sources']=row['compiler_only_sources']
    from .native_test_workspace import check_inputs
    check_inputs(runtime,state)
    prior=native.get('timeout_checkpoints',[])
    # Test counts/log paths are not progress. Only changed source or a changed
    # test outcome can justify spending another invocation after a timeout.
    finished=[r for r in tests if r.get('status')=='finished']
    result={k:finished[-1].get(k) for k in ('passed','failure_kind')} if finished else None
    fingerprint=content_hash({'owned':owned,'test_outcome':result})
    baseline=content_hash({'owned':{p:native['tool_baseline'].get(p) for p in recipe['owned']},'test_outcome':None})
    if fingerprint in {p['fingerprint'] for p in prior} or fingerprint==baseline:
        raise LedgerError('Timeout has no new source/test progress; continuation stopped.')
    checkpoint={'attempt':attempt['id'],'session':session,'workspace':native['workspace'],
                'owned':owned,'fingerprint':fingerprint,'stdout_hash':bytes_hash(raw),
                'test_receipt':str(history_path),'test_outcome':result,'tree_stopped':True}
    native.setdefault('timeout_checkpoints',[]).append(checkpoint)
    native['continuation_tests']=tests[-3:]
    native['continuation_ready']=True
    native['worker_started']=True
    native['feedback']='The previous invocation reached its time slice and its entire process tree was stopped. '+\
        'Continue from the existing files and this same session; do not restart discovery or undo completed work. '+\
        'Inspect the last test receipt and complete the remaining fix/tests and report. Do not skip or weaken tests to pass. '+\
        'The newly supplied test command replaces the previous invocation command. Scope and total budget are unchanged.'
    native['attempts'].append({'stage':'work','session_id':session,'log':str(path),
        'tool_calls':len(calls),'denied_tool_calls':denied,'outcome':'timeout_checkpoint','usage':'unknown'})
    state.update(pending=None,phase='running',message='Native time slice ended; progress checkpoint saved for automatic continuation.',
                 recovery={'kind':'native_timeout','automatic_retry':True,'attempt':attempt['id']},step=state['step']+1)
    state.pop('pending_solution_context',None);state.pop('revalidate_pending',None)
    runtime.persist(task_id,seq,state)
    return True


def collect_candidate(runtime,state,value,recipe,*,require_test=True):
    native=state['native_change'];workspace=Path(native['workspace'])
    baseline=native['tool_baseline'];observed=inventory(workspace);owned=set(recipe['owned'])
    # The fixed recipe may create precisely this generated metadata file.
    graph=recipe['package']+'/.dart_tool/package_graph.json'
    if graph not in baseline and graph in observed:
        original=safe_file(runtime.ledger.project,graph)
        if observed[graph]!=bytes_hash(original.read_bytes()):raise LedgerError('Generated graph changed.')
        observed.pop(graph)
    for name in set(baseline)|set(observed):
        if name not in owned and baseline.get(name)!=observed.get(name):
            raise LedgerError('Native worker changed an unowned path: '+name)
    if require_test:
        receipt=Path(native['tool_context']).with_suffix('.receipt.json')
        if not receipt.is_file():raise LedgerError('Native worker did not invoke the authorized test recipe.')
        evidence=json.loads(receipt.read_text(encoding='utf-8'))
        if not any(r.get('status')=='finished' for r in evidence.get('results',[])):
            raise LedgerError('Native worker has no finished test execution receipt.')
        native['worker_tests']=evidence
        for result in evidence['results']:
            if 'compiler_only_sources' in result:
                native['local_test_sources']=result['compiler_only_sources'];break
        from .native_test_workspace import check_inputs
        check_inputs(runtime,state)
    files=[]
    for name in recipe['owned']:
        path=safe_file(workspace,name)
        if path.is_file():
            if path.stat().st_size>200000:raise LedgerError('Native file exceeds limit.')
            files.append({'path':name,'text':path.read_text(encoding='utf-8')})
    return dict(value,files=files)


class WorkspaceClaude(NativeClaude):
    allowed_native_tools={'Read','Glob','Grep','Edit','Write','Bash','StructuredOutput'}

    def capability(self):
        value=super().capability()
        return dict(value,mode='native-scoped-workspace',tools=sorted(self.allowed_native_tools),
                    max_native_turns_per_invocation=60,max_tests_per_invocation=8,
                    shell='fixed test recipe plus CLI built-in read-only permissions',os_sandbox=False)

    def arguments(self,directory,schema,profile):
        permissions=['Read','Glob','Grep','Bash('+profile['test_command']+')']
        permissions.extend(edit_permissions(profile['native_workspace'],profile['native_owned']))
        return [self.executable,'--print',*CLAUDE_AUTH_ARGS,'--tools','Read,Glob,Grep,Edit,Write,Bash',
              '--allowedTools',*permissions,'--permission-mode','dontAsk','--permission-prompts','none',
              '--disable-slash-commands','--strict-mcp-config','--mcp-config',str(directory/'mcp.json'),
              '--output-format','stream-json','--verbose','--max-turns','60','--model',profile['model'],
              '--json-schema',canonical(schema),
              '--resume' if profile['native_resume'] else '--session-id',profile['native_session'],
              '--append-system-prompt',profile['native_instructions']]

    def run(self,attempt,prompt,schema,profile):
        directory=self.prepare(attempt)
        durable_write(directory/'mcp.json',b'{"mcpServers":{}}')
        argv=self.arguments(directory,schema,profile)
        return Supervisor(self.control).run(attempt,argv,cwd=Path(profile['native_workspace']),
            stdin=prompt,timeout=profile['step_seconds'],env=environment())


def recover_permissions(runtime,task_id,reference):
    """Explicit operator recovery of a settled pre-fix denial, without replaying it.

This does not answer any inbox/solution request or expand file/tool authority.
The paid response is retained and other unresolved decisions remain for worker review.
"""
    from .ledger import text_field
    from .discovery import scan_text
    from .workflow import task_lock
    from .runner import status
    from .sandbox_gate import task_guard
    from .native_change import check_snapshot
    from .usage import record
    text_field(reference,'operator reference',1000);scan_text(reference.encode())
    if status(runtime.ledger,task_id)['status']!='stopped':raise LedgerError('Stop the runner before recovery.')
    with task_lock(runtime.ledger,task_id):
        seq,state=runtime.state(task_id);control=runtime.control.status(task_id)
        recipe=control['configuration']['profile'].get('native_change',{})
        native=state.get('native_change',{})
        if (recipe.get('execution')!='workspace' or native.get('stage')!='work'
                or state['phase'] in ('completed','failed','cancelled') or not state.get('pending')):
            raise LedgerError('Recovery requires a pending native workspace result.')
        if runtime.ledger.requests(task_id,pending=True):raise LedgerError('Pending requests must be answered by the user.')
        task_guard(runtime.control,task_id)()
        attempt=runtime.control.attempt(state['pending'])
        if attempt['status']!='settled':raise LedgerError('Reconcile the prior worker before recovery.')
        worker=WorkspaceClaude(runtime.control)
        value,usage=worker.result(attempt)
        telemetry=value.pop('_native')
        if not isinstance(value.get('report'),str) or not isinstance(value.get('question'),str):
            raise LedgerError('Invalid recovered workspace response.')
        scan_text(value['report'].encode());scan_text(value['question'].encode())
        if telemetry.get('session_id')!=native['worker_session']:raise LedgerError('Recovery session mismatch.')
        events=[json.loads(line) for line in worker.stdout(attempt).splitlines() if line.strip()]
        calls={b['id']:b for e in events if e.get('type')=='assistant'
               for b in e.get('message',{}).get('content',[]) if b.get('type')=='tool_use'}
        owned={str(safe_file(Path(native['workspace']),p).resolve()).casefold() for p in recipe['owned']}
        scoped_denials=[]
        for event in events:
            if event.get('type')!='system' or event.get('subtype')!='permission_denied':continue
            call=calls.get(event.get('tool_use_id'),{})
            path=call.get('input',{}).get('file_path')
            if call.get('name') in ('Edit','Write') and isinstance(path,str):
                target=Path(path)
                if not target.is_absolute():target=Path(native['workspace'])/target
                if str(target.resolve()).casefold() in owned:scoped_denials.append(event['tool_use_id'])
        if not scoped_denials:raise LedgerError('No proven denial of an already owned file; generic recovery refused.')
        check_snapshot(runtime,state)
        collect_candidate(runtime,state,value,recipe,require_test=False)
        # Recovery is deliberately limited to an unchanged failed workspace.
        observed=inventory(Path(native['workspace']))
        if observed!=native['tool_baseline']:raise LedgerError('Worker changed files; reconcile candidate before recovery.')
        native.setdefault('permission_recoveries',[]).append({'attempt':attempt['id'],'reference':reference,
            'response':value,'scoped_denials':scoped_denials,'policy':'absolute-file-rules-v2'})
        native['attempts'].append(dict(telemetry,stage='work',recovered_permission_failure=True))
        record(state,attempt['id'],usage,'claude',state['worker']['model'])
        native.update(worker_started=True,feedback='Operator repaired the mapping of existing exact file permissions. '
            'Use Edit/Write for the owned files; never use Bash to write source. Run only the provided test command. '
            'No scope or permission expansion was granted. Reassess the prior question: continue if it only asks '
            'for these already granted operations; ask again for any separate product/solution decision. Prior question: '+str(value.get('question',''))[:1500])
        state.update(pending=None,phase='running',message='Scoped permission mapping repaired; paid response preserved.',
                     step=state['step']+1,assistance='entry-runtime-repair')
        state.pop('pending_solution_context',None);state.pop('revalidate_pending',None)
        runtime.persist(task_id,seq,state,unpause=True)
        return {'task':task_id,'recovered_attempt':attempt['id'],'used_calls':control['used_calls'],
                'new_model_calls':0,'permissions_expanded':False,'assistance':'entry-runtime-repair'}
