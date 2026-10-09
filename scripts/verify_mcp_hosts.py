"""Opt-in live two-CLI MCP verification on the synthetic rev9 fixture only."""
import json
from pathlib import Path
from onecrew.ledger import Ledger,canonical
from onecrew import consultations as q,conversations as c
from onecrew.providers import ClaudeArtifact
from onecrew.workflow import CodexArtifact
from onecrew.supervisor import Supervisor,native_python
from onecrew.subscription import environment,CLAUDE_AUTH_ARGS,CODEX_AUTH_ARGS
from onecrew.snapshots import durable_write

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'.onecrew/rev9-live'


def server(provider):
    launcher=FIXTURE/'mcp_entry.py'
    launcher.write_text('import sys\nsys.path.insert(0,'+repr(str(ROOT))+')\nfrom onecrew.mcp_entry import main\nraise SystemExit(main())\n',encoding='utf-8')
    executable=Path.home()/'AppData/Local/Programs/Python/Python313/python.exe'
    if not executable.is_file():raise RuntimeError('Supply a native Python accessible to MCP child processes; Store Python failed live startup.')
    return {'command':str(executable),'args':['-X','utf8',str(launcher),'--project',str(FIXTURE/'project'),
        '--state-root',str(FIXTURE/'state'),'--allow-discussion','--source','live-'+provider]}


class ClaudeHost(ClaudeArtifact):
    def run(self,a,prompt,schema,profile):
        directory=self.prepare(a)
        durable_write(directory/'mcp.json',canonical({'mcpServers':{'onecrew':server('claude')}}).encode())
        names=['mcp__onecrew__conversation_read','mcp__onecrew__conversation_append']
        argv=[self.executable,'--print',*[a for a in CLAUDE_AUTH_ARGS if a!='--safe-mode'],'--tools','','--allowedTools',','.join(names),
            '--permission-mode','dontAsk','--permission-prompts','none','--disable-slash-commands',
            '--strict-mcp-config','--mcp-config',str(directory/'mcp.json'),'--no-session-persistence',
            '--output-format','json','--model',profile['model'],'--max-turns','6','--json-schema',canonical(schema)]
        return Supervisor(self.control).run(a,argv,cwd=directory,stdin=prompt,timeout=120,env=environment())


class CodexHost(CodexArtifact):
    def run(self,a,prompt,schema,profile):
        self.capability();directory=self.control.ledger.state_root/'worker-io'/a['id'];directory.mkdir(parents=True)
        durable_write(directory/'schema.json',canonical(schema).encode())
        config=server('codex');config['enabled_tools']=['conversation_read','conversation_append']
        config['tool_timeout_sec']=20
        # The verification explicitly authorizes these two fixture-local operations only.
        config['tools.conversation_read.approval_mode']='approve'
        config['tools.conversation_append.approval_mode']='approve'
        argv=[self.executable,'--no-daemon','-a','never','exec','--ignore-user-config',*CODEX_AUTH_ARGS,
            '--ephemeral','--skip-git-repo-check','--sandbox','read-only','--model',profile['model'],
            '-c','model_reasoning_effort="low"','-c','web_search="disabled"',
            '--disable','shell_tool','--disable','apps','--disable','plugins','--disable','hooks','--disable','multi_agent',
            '--json','--color','never','--output-schema',str(directory/'schema.json'),'-o',str(directory/'result.json')]
        for key,value in config.items():argv+=['-c','mcp_servers.onecrew.'+key+'='+json.dumps(value)]
        argv+=['-']
        return Supervisor(self.control).run(a,argv,cwd=directory,stdin=prompt,timeout=120,env=environment())

    def result(self,a):
        receipt=json.loads(a['result'])
        if receipt.get('exit_code')!=0 or receipt.get('reason'):raise ValueError('Host process did not complete.')
        usage=[]
        for line in Path(receipt['stdout']).read_text(encoding='utf-8').splitlines():
            event=json.loads(line);item=event.get('item',{})
            if item.get('type')=='mcp_tool_call':
                if item.get('server')!='onecrew' or item.get('tool') not in ('conversation_read','conversation_append') or item.get('error'):
                    raise ValueError('Unexpected or unsuccessful host tool call.')
            elif item.get('type') not in (None,'agent_message','reasoning'):raise ValueError('Unexpected host tool.')
            if event.get('type')=='turn.completed':usage.append(event.get('usage'))
        path=self.control.ledger.state_root/'worker-io'/a['id']/'result.json'
        return json.loads(path.read_text(encoding='utf-8')),usage


def main():
    ledger=Ledger(FIXTURE/'project',FIXTURE/'state');base=json.loads((FIXTURE/'receipt.json').read_text(encoding='utf-8'))
    cid=base['conversation'];sol=base['request']['solution'];rev=base['request']['revision'];results=[]
    for provider,model,cls in [('claude','haiku',ClaudeHost),('codex','gpt-6-luna',CodexHost)]:
        key=('mcp-host-v3-' if provider=='claude' else 'mcp-host-v4-')+provider
        result=q.submit(ledger,cid,key,sol,rev,'Synthetic MCP entry interoperability test','integration-test',
            'User authorized OneCrew architecture verification',provider=provider,model=model,max_seconds=180)
        worker=cls(q.ConsultationControl(ledger,result['id']))
        run=worker.run
        prompt=f'Use onecrew MCP tools: first conversation_read with conversation {cid}; then conversation_append exactly once with conversation {cid}, key {key}, text "Verified shared entry {provider}", kind "evidence". Do not call any other tools. Then return the required JSON report, all fields strings. Verdict should say whether both tools returned durable success. Do not invent tool results.'
        worker.run=lambda a,p,s,f,run=run,prompt=prompt:run(a,prompt,s,f)
        output=q.run(ledger,result['id'],worker)
        with ledger.transaction() as conn:
            event=conn.execute('SELECT id,payload FROM conversation_events WHERE conversation=? AND request_key=?',(cid,key)).fetchone()
        results.append({'provider':provider,'status':output['status'],'error':output.get('error'),'consultation':result['id'],
            'durable_ack':dict(event) if event else None,'output':output['output']})
        print(json.dumps(results[-1]),flush=True)
    (FIXTURE/'hosts.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':main()
