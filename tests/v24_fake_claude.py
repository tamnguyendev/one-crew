"""A FAKE `claude` command for the 2.4-A installed test (tests/test_v24_a_installed.py): no model, a deterministic policy over the prompt.

It answers what onecrew.artifact_provider_core.ClaudeArtifact asks (`--version`, `auth status --json`, one `--print` run with the prompt
on stdin and `--json-schema`) through the real Supervisor path. For a node with `source_tools` it reads by request: in the first round it
asks to read the catalogue entry named by the policy; once a read result shows `VALUE: <x>` it writes <x> to the node's write file. It
proves the plumbing only, never that a real model uses the protocol. Every run appends one JSON line to $ONECREW_FAKE_LOG.

Policy ($ONECREW_FAKE_POLICY, JSON): {"read": "<path suffix to read from the catalogue>"}.
"""
import json
import os
import re
import sys
from pathlib import Path

VERSION = '2.1.286 (Claude Code)'
VALUE = re.compile(r'VALUE:\s*([A-Za-z0-9_-]+)')


def decide(body, schema, policy):
    node = body['node']
    if not node.get('write'):
        evidence = [v['receipt'] for v in (body.get('input_artifacts') or {}).values() if isinstance(v, dict) and v.get('receipt')]
        return {'summary': 'integrated the declared inputs', 'evidence': evidence}, {'how': 'report'}
    target = node['write'][0]
    tools = body.get('source_tools') or {}
    for row in tools.get('results') or []:
        text = (row.get('result') or {}).get('text')
        match = VALUE.search(text) if isinstance(text, str) else None
        if match:
            return ({'summary': 'value read from ' + row['result']['path'], 'files': [{'path': target, 'content': match.group(1) + '\n'}],
                     'backlog': []}, {'how': 'read', 'value': match.group(1), 'from': row['result']['path']})
    if 'source' in schema.get('properties', {}):
        listed = [e['path'] for row in tools.get('results') or [] if row.get('action') == 'list'
                  for e in (row.get('result') or {}).get('entries') or []]
        wanted = [p for p in listed if p.endswith(policy.get('read', ''))][:1]
        if wanted:
            return ({'summary': 'reading ' + wanted[0], 'files': [], 'backlog': [], 'continuation': {'remaining': 'read the value file'},
                     'source': {'requests': [{'op': 'read', 'path': wanted[0]}]}}, {'how': 'ask', 'asked': wanted})
    return {'summary': 'default', 'files': [{'path': target, 'content': 'naive\n'}], 'backlog': []}, {'how': 'default'}


def main():
    argv = sys.argv[1:]
    if argv == ['--version']:
        print(VERSION); return 0
    if 'auth' in argv and 'status' in argv:
        print(json.dumps({'loggedIn': True, 'authMethod': 'claude.ai'})); return 0
    if '--print' not in argv:
        print('fake claude: unsupported invocation', file=sys.stderr); return 2
    schema = json.loads(argv[argv.index('--json-schema') + 1])
    prompt = sys.stdin.buffer.read().decode('utf-8')
    body = json.loads(prompt.split('\n', 1)[1])
    policy = json.loads(Path(os.environ['ONECREW_FAKE_POLICY']).read_text(encoding='utf-8'))
    value, trace = decide(body, schema, policy)
    log = os.environ.get('ONECREW_FAKE_LOG')
    if log:
        with open(log, 'a', encoding='utf-8') as handle:
            handle.write(json.dumps(dict(trace, node=body['node']['id'], prompt_chars=len(prompt),
                                         sources='source_tools' in body), ensure_ascii=False) + '\n')
    print(json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False, 'structured_output': value,
                      'usage': {'input_tokens': len(prompt) // 4, 'output_tokens': 50, 'fake': True}}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
