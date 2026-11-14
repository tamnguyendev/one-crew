"""A FAKE `claude` command for the MR-R installed run (D:/OneCrewRuns/wf-dev-tools/mrr/e2e_mrr.py): no model, a deterministic policy over the
prompt. It answers what onecrew.artifact_provider_core.ClaudeArtifact asks (`--version`, `auth status --json`, one `--print` run with the
prompt on stdin and `--json-schema`) through the real Supervisor path, like tests/v24_fake_claude.py.

For a node whose `source_tools` name repositories: when the round may ask and nothing was searched or read yet in this chain's pins, it asks,
for every pinned repository, a search of the policy query and the reads the policy names for that repository (plus the policy's `extra`
requests, and with `cross_cursor` the next_cursor of the first catalogue offered to another repository). Otherwise it writes the node's
report: every match and read cited with its `cite`, every coverage gap named, and "PARTIAL" when there is one. A node without source tools
(unavailable) reports its gaps. It proves the plumbing only, never that a real model uses the protocol.

Policy ($ONECREW_FAKE_POLICY, JSON): {"query": "needle", "reads": {"core": ["src/shared.py"]}, "extra": [{...request...}], "cross_cursor": bool}.
Every run appends one JSON line to $ONECREW_FAKE_LOG: what it did, the repositories and gaps it saw, the cites it wrote, and whether any of
the policy's `never` strings reached its prompt.
"""
import json
import os
import sys
import time
from pathlib import Path

VERSION = '2.1.286 (Claude Code)'


def report(node, tools, previous=None):
    """The report: this round's matches and reads with their cites, plus the findings of the carried candidate (`previous`, after a recheck)
    whose repository snapshot is still the pinned one now (a repeat of their request on that snapshot is refused, and they stay valid)."""
    rows = tools.get('results') or []
    cites = []
    for row in rows:
        result = row.get('result') or {}
        for match in result.get('matches') or []:
            if match.get('cite'): cites.append(f'{match["cite"]} {match.get("text", "")}'.rstrip())
        if isinstance(result.get('text'), str) and result.get('cite'):
            first = result['text'].splitlines()[0] if result['text'] else ''
            cites.append(f'{result["cite"]} {first}'.rstrip())
    current = {r['repo']: (r.get('tree') or '')[:12] for r in tools.get('repos') or [] if r.get('status') == 'pinned'}
    fresh = {c.split(' ', 1)[0] for c in cites}
    kept = []
    for line in (previous or '').splitlines():
        entry = line[2:] if line.startswith('- ') else None
        if not entry or '@' not in entry: continue
        cite = entry.split(' ', 1)[0]
        alias, _, rest = cite.partition('@')
        if current.get(alias) and rest[:12] == current[alias] and cite not in fresh: kept.append(entry)
    cites = kept + cites
    gaps = tools.get('coverage_gaps') or []
    pinned = [r['repo'] for r in tools.get('repos') or [] if r.get('status') == 'pinned']
    old = [r['repo'] for r in tools.get('repos') or [] if r.get('status') == 'pinned' and r.get('current') is False]
    lines = ['# MR-R analysis (fake worker, no model)', '',
             'Coverage: ' + ('PARTIAL - not read: ' + '; '.join(f'{g["repo"]} ({g["status"]}: {g.get("reason", "")})' for g in gaps)
                             if gaps else 'the pinned repositories ' + ', '.join(pinned) + ' (read scope only)'),
             *(['Older snapshot: ' + ', '.join(old)] if old else []), '', 'Findings:']
    lines += [f'- {c}' for c in cites] or ['- none found in the covered part']
    return '\n'.join(lines) + '\n', cites, gaps


def decide(body, schema, policy):
    node = body['node']
    tools = body.get('source_tools') or {}
    if not node.get('write'):
        evidence = [v['receipt'] for v in (body.get('input_artifacts') or {}).values() if isinstance(v, dict) and v.get('receipt')]
        return {'summary': 'integrated the declared inputs', 'evidence': evidence}, {'how': 'report-node'}
    target = node['write'][0]
    rows = tools.get('results') or []
    pinned = [r['repo'] for r in tools.get('repos') or [] if r.get('status') == 'pinned']
    asked = any(r.get('action') in ('search', 'read') for r in rows)
    # ask while rounds are left, nothing was searched or read in this round's results (a catalogue round: the first of a chain, or after a
    # re-pin) and nothing of the last round was refused (refused requests are not asked again; the round count spans the node's generations)
    can_ask = ('source' in schema.get('properties', {}) and (tools.get('rounds') or {}).get('left', 0) > 0
               and not tools.get('refused_last_round'))
    if can_ask and not asked and pinned:
        requests = []
        for repo in pinned:
            if policy.get('query'): requests.append({'op': 'search', 'repo': repo, 'query': policy['query']})
            requests += [{'op': 'read', 'repo': repo, 'path': p} for p in (policy.get('reads') or {}).get(repo, [])]
        requests += list(policy.get('extra') or [])
        if policy.get('cross_cursor'):
            lists = [(r['result']['source']['repo'], r['result'].get('next_cursor')) for r in rows
                     if r.get('action') == 'list' and (r.get('result') or {}).get('next_cursor')]
            others = [p for p in pinned if lists and p != lists[0][0]]
            if lists and others: requests.append({'op': 'list', 'repo': others[0], 'cursor': lists[0][1]})
        return ({'summary': 'reading the declared repositories', 'files': [], 'backlog': [], 'continuation': {'remaining': 'read the requested files'},
                 'source': {'requests': requests[:8]}}, {'how': 'ask', 'asked': requests[:8]})
    text, cites, gaps = report(node, tools, (body.get('source') or {}).get(target))
    return ({'summary': 'MR-R analysis written', 'files': [{'path': target, 'content': text}], 'backlog': []},
            {'how': 'report', 'cites': cites, 'gaps': gaps})


def stall(policy, trace, node):
    """A controlled hold for the real process-kill test (e2e S8): policy {"stall": {"node": "R", "when": "ask"|"report", "marker": path,
    "seconds": n}}. The first run of that node that is about to do `when` writes the marker (its pid) and sleeps, so a harness can kill the whole
    process tree of the controller while this worker is mid-step. Once the marker exists no later run holds."""
    spec = policy.get('stall')
    if not spec or spec.get('node') != node or spec.get('when') != trace.get('how') or Path(spec['marker']).exists(): return
    Path(spec['marker']).write_text(json.dumps({'pid': os.getpid(), 'node': node, 'how': trace['how']}), encoding='utf-8')
    time.sleep(spec.get('seconds', 600))


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
    log =os.environ.get('ONECREW_FAKE_LOG')
    if log:
        tools = body.get('source_tools') or {}
        with open(log, 'a', encoding='utf-8') as handle:
            handle.write(json.dumps(dict(trace, node=body['node']['id'], prompt_chars=len(prompt), sources='source_tools' in body,
                                         repos=tools.get('repos'), coverage_gaps=tools.get('coverage_gaps'),
                                         refused_last_round=tools.get('refused_last_round'),
                                         results=[{'action': r.get('action'), 'arguments': r.get('arguments'),
                                                   'refused': (r.get('result') or {}).get('refused'),
                                                   'repo': ((r.get('result') or {}).get('source') or {}).get('repo')} for r in tools.get('results') or []],
                                         leaked=[s for s in policy.get('never') or [] if s in prompt]), ensure_ascii=False) + '\n')
    stall(policy, trace, body['node']['id'])           # after the log line: a killed run still leaves its trace
    print(json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False, 'structured_output': value,
                      'usage': {'input_tokens': len(prompt) // 4, 'output_tokens': 50, 'fake': True}}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
