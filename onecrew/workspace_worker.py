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
        path=runtime.ledger.state_root/'workspace-tools'/(uuid.uuid4().hex+'.json')
        if 'tool_baseline' not in native:
            native['tool_baseline']=inventory(Path(native['workspace']))
        native['tool_context']=str(path)
        context={'project':str(runtime.ledger.project),'state_root':str(runtime.ledger.state_root),
                 'task_id':task_id,'state':state,'recipe':recipe,'max_tests':8}
        durable_write(path,canonical(context).encode())
    command=' '.join(shlex.quote(p.replace('\\','/')) for p in (
        sys.executable,str(Path(__file__).with_name('workspace_tools.py')),str(path)))
    return {'test_command':command,'native_owned':recipe['owned']}


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

    def run(self,attempt,prompt,schema,profile):
        directory=self.prepare(attempt)
        durable_write(directory/'mcp.json',b'{"mcpServers":{}}')
        permissions=['Read','Glob','Grep','Bash('+profile['test_command']+')']
        for name in profile['native_owned']:
            permissions.extend((f'Edit(./{name})',f'Write(./{name})'))
        argv=[self.executable,'--print',*CLAUDE_AUTH_ARGS,'--tools','Read,Glob,Grep,Edit,Write,Bash',
              '--allowedTools',*permissions,'--permission-mode','dontAsk','--permission-prompts','none',
              '--disable-slash-commands','--strict-mcp-config','--mcp-config',str(directory/'mcp.json'),
              '--output-format','stream-json','--verbose','--max-turns','60','--model',profile['model'],
              '--json-schema',canonical(schema),
              '--resume' if profile['native_resume'] else '--session-id',profile['native_session'],
              '--append-system-prompt',profile['native_instructions']]
        return Supervisor(self.control).run(attempt,argv,cwd=Path(profile['native_workspace']),
            stdin=prompt,timeout=profile['step_seconds'],env=environment())
