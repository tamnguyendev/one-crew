"""A FAKE `claude` command for 2.3 tests and the wiki comparison harness: no model, a deterministic policy over the prompt.

Installed as the console script `claude` (tests/v23_harness.py builds a tiny wheel for it), it answers exactly what the real adapter
(onecrew.artifact_provider_core.ClaudeArtifact) asks: `--version`, `auth status --json`, and one `--print` run with the prompt on stdin
and `--json-schema`, printing the CLI's JSON result envelope. It goes through the real Supervisor/Job path, so these runs are real
processes — but the "model" is this file: it proves the plumbing (what reached the worker, what it declared, what the checks judged),
never that a real model understands or uses knowledge. Every run appends one JSON line to $ONECREW_FAKE_LOG.

Policy ($ONECREW_FAKE_POLICY, JSON): {"target": "a.txt", "default": "<naive value>", "careful": true}.
  * a delivered `fact` whose text says `VALUE: <x>` is followed (mandatory ones first);
  * `rejected` entries with `VALUE: <x>` are never chosen;
  * a `lead` with `VALUE: <x>` is used only when `careful` and <x> is visible in the node's source (the lead was checked);
  * otherwise the default is written. The declaration names the entries the choice relied on.
A2 runs may add "claims": [{"kind", "text", "applies_to", "check"}] which the fake returns as knowledge.new (observations to record).
"""
import json
import os
import re
import sys
import time
from pathlib import Path

VERSION = '2.1.286 (Claude Code)'
VALUE = re.compile(r'VALUE:\s*([A-Za-z0-9_-]+)')


def _values(entries, use):
    out = []
    for entry in entries:
        if entry.get('use') != use: continue
        match = VALUE.search(entry.get('text', ''))
        if match: out.append((entry, match.group(1)))
    return sorted(out, key=lambda item: not item[0].get('must'))


def decide(body, policy):
    node = body['node']
    knowledge = body.get('knowledge') or {}
    entries = (knowledge.get('entries') or []) + (knowledge.get('requested') or [])
    source_text = '\n'.join(str(v) for v in (body.get('source') or {}).values() if isinstance(v, str))
    rejected = {value for _, value in _values(entries, 'rejected')}
    used, how, value = [], 'default', None
    for entry, candidate in _values(entries, 'fact'):
        if candidate not in rejected:
            value, used, how = candidate, [entry['id']], 'fact'; break
    if value is None and policy.get('careful', True):
        for entry, candidate in _values(entries, 'lead'):
            if candidate not in rejected and re.search(r'(?<![A-Za-z0-9_])' + re.escape(candidate) + r'(?![A-Za-z0-9_])', source_text):
                value, used, how = candidate, [entry['id']], 'lead_checked_in_source'; break
    if value is None:
        value = policy.get('default', 'naive')
        if value in rejected: value, how = 'unknown', 'default_rejected'
    target = policy.get('target') or node['write'][0]
    result = {'summary': f'wrote {target} ({how})', 'files': [{'path': target, 'content': value + '\n'}], 'backlog': []}
    declaration = {'used': used, 'rejected': [], 'requests': []}
    claims = policy.get('claims')
    if claims: declaration['new'] = claims
    result['knowledge'] = declaration
    return result, {'how': how, 'value': value, 'delivered': [e['id'] for e in entries], 'used': used}


def main():
    argv = sys.argv[1:]
    if argv == ['--version']:
        print(VERSION); return 0
    if 'auth' in argv and 'status' in argv:
        print(json.dumps({'loggedIn': True, 'authMethod': 'claude.ai'})); return 0
    if '--print' not in argv:
        print('fake claude: unsupported invocation', file=sys.stderr); return 2
    started = time.perf_counter()
    model = argv[argv.index('--model') + 1] if '--model' in argv else None
    schema = json.loads(argv[argv.index('--json-schema') + 1])
    prompt = sys.stdin.buffer.read().decode('utf-8')
    body = json.loads(prompt.split('\n', 1)[1])
    policy = json.loads(Path(os.environ['ONECREW_FAKE_POLICY']).read_text(encoding='utf-8'))
    value, trace = decide(body, policy)
    if 'new' in value.get('knowledge', {}) and 'new' not in schema['properties'].get('knowledge', {}).get('properties', {}):
        del value['knowledge']['new']                        # an A1 build has no place for claims: the fake never breaks the schema
    log = os.environ.get('ONECREW_FAKE_LOG')
    if log:
        knowledge = body.get('knowledge')
        record = dict(trace, node=body['node']['id'], model=model, prompt_chars=len(prompt),
                      knowledge_chars=len(json.dumps(knowledge, ensure_ascii=False, separators=(',', ':'), sort_keys=True)) if knowledge else 0,
                      seconds=round(time.perf_counter() - started, 4))
        with open(log, 'a', encoding='utf-8') as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + '\n')
    print(json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False, 'structured_output': value,
                      'usage': {'input_tokens': len(prompt) // 4, 'output_tokens': 50, 'fake': True}}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
