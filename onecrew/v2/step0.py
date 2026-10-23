"""Step 0 of the AI work contract, enforced by code: the plan cannot be approved until the AI has stated its understanding,
every unknown is closed by evidence the ledger recorded, a choice between options was made by the owner, and the starting
point passed its cheap checks. Nothing here calls a model.

* `evaluate` collects EVERY reason approve would refuse for (never only the first) and runs the preconditions once, outside any
  ledger lock (a command may take minutes).
* An unknown is closed only by an `unknown.closed` event (written by `close_unknown` / `poc_record`, each with an amendment in the
  same transaction). A contract file that merely says `closed` is not believed.
* `chosen` is never in the contract: it exists only in the owner's `plan.approved` event.
"""
import json
import os
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

from ..ledger import LedgerError, canonical, text_field
from ..qc_intake import _commit, locate
from ..snapshots import Snapshots
from . import contract as contracts
from .ownership import OWNER_ACTORS, session_info
from .verifiers import command

KINDS = ('unknown.closed', 'poc.answered', 'precondition.recorded', 'plan.step0_closed')
BLOB = re.compile(r'[0-9a-f]{64}')
URL = re.compile(r'https?://\S{4,}')
FILE_LINE = re.compile(r'[\w./\\-]+\.\w+:\d+')
PLACEHOLDER_HOSTS = ('example.com', 'example.org', 'example.net')
PLACEHOLDER_TLDS = ('example', 'invalid', 'test', 'localhost', 'local')
TAIL = 600
MIN_BECAUSE = 20          # understanding.no_unknowns_because: shorter than this ("None", "n/a") says what was NOT checked


def _actor(by=None):
    return os.environ.get('ONECREW_ACTOR') or by


# ---- evidence ---------------------------------------------------------------------------------------------------------

def _bad_url(url):
    """Why `url` cannot be evidence (not http/https, no dotted host, a placeholder host), or None."""
    try:
        parts = urlsplit(url.rstrip('.,;:)]}>\'"'))
        host = parts.hostname or ''
    except ValueError:
        return 'is not a URL'
    labels = host.split('.')
    if parts.scheme not in ('http', 'https') or len(labels) < 2 or not all(labels):
        return 'has no http(s) scheme and a host with a dot'
    if not re.fullmatch(r'[a-z]{2,}', labels[-1]): return 'has a host that does not end in a name (an IP address or a number is not a source)'
    if labels[-1] in PLACEHOLDER_TLDS or '.'.join(labels[-2:]) in PLACEHOLDER_HOSTS or len(set(host.replace('.', ''))) == 1:
        return f'has the placeholder host {host}'
    return None


def _bad_file_line(ledger, reference):
    """Why `path:line` does not resolve under the project (no such file, outside the project, a line past the end), or None."""
    path, _, number = reference.rpartition(':')
    project = Path(ledger.project).resolve()
    target = (project / path).resolve()
    if project != target and project not in target.parents: return 'is outside the project'
    if not target.is_file(): return f'names {path}, which is not a file under the project'
    data = target.read_bytes()
    lines = data.count(b'\n') + (1 if data and not data.endswith(b'\n') else 0)
    if not 1 <= int(number) <= lines: return f'names line {number}, but {path} has {lines} line{"s" if lines != 1 else ""}'
    return None


def evidence_kind(ledger, text, closer=None):
    """What an evidence string points at: a blob in this state root, a URL, a file:line reference; the owner may also state it
    in words. Returns the kind, or raises. A pointer must resolve (C12): the blob is in the store, the file and the line exist under
    `ledger.project`, the URL has a scheme and a real-looking host. (It proves a pointer resolves, not that the claim is true:
    the owner reads it.) Every pointer in the text is checked, so a good one next to a bad one does not pass."""
    text = text_field(text, 'evidence', 1000).strip()
    if BLOB.fullmatch(text):
        try:
            Snapshots(ledger.state_root).read_blob(text)
        except (OSError, LedgerError) as error:
            raise LedgerError('evidence: no such blob in this state root.') from error
        return 'blob'
    urls = [m.group(0) for m in URL.finditer(text)]
    files = FILE_LINE.findall(URL.sub(' ', text))
    for pointer, problem in [(u, _bad_url(u)) for u in urls] + [(f, _bad_file_line(ledger, f)) for f in files]:
        if problem: raise LedgerError(f'evidence: {pointer} {problem}.')
    if urls: return 'url'
    if files: return 'file_line'
    if closer == 'owner' and len(text) >= 10: return 'owner_statement'
    raise LedgerError('evidence: give a blob key, a URL or a file:line reference' + (' (or, as the owner, a statement).' if closer != 'poc' else '.'))


# ---- closing unknowns ---------------------------------------------------------------------------------------------------

def closed_events(conn, task_id):
    """unknown id -> the latest unknown.closed payload recorded on the anchor task."""
    out = {}
    for row in conn.execute('SELECT payload FROM events WHERE task_id=? AND kind=? ORDER BY seq', (task_id, 'unknown.closed')):
        payload = json.loads(row['payload'])
        out[payload['unknown']] = payload
    return out


def _closing(ledger, name, unknown_id, by, evidence, extra_events=()):
    from . import plan as plans
    if by not in contracts.CLOSERS: raise LedgerError('--by: doc, poc or owner.')
    if by == 'owner': plans.require_owner('owner', 'Closing an unknown as the owner\'s decision')
    kind = evidence_kind(ledger, evidence, by)
    with ledger.transaction() as conn:
        state = plans.anchor_events(ledger, conn, name)
        contract, _ = plans.load(ledger, state)
    raw = json.loads(json.dumps(contract))
    target = next((u for u in raw['understanding']['unknowns'] if u['id'] == unknown_id), None)
    if target is None: raise LedgerError(f'Plan {name} has no unknown {unknown_id}.')
    if target['status'] == 'closed': raise LedgerError(f'Unknown {unknown_id} is already closed.')
    target.update(status='closed', closed_by=by, evidence=evidence.strip())

    def events(revision):
        closed = {'plan': name, 'revision': revision, 'unknown': unknown_id, 'by': by, 'evidence': evidence.strip(), 'evidence_kind': kind,
                  **session_info()}
        return list(extra_events) + [('unknown.closed', closed)]
    return plans.amend(ledger, name, raw, f'unknown {unknown_id} closed', _actor(by) or by, events=events, keep_content_author=True)


def close_unknown(ledger, name, unknown_id, by, evidence):
    """Record the closure and make the amendment (a new revision) in one transaction."""
    return _closing(ledger, name, unknown_id, by, evidence)


def poc_record(ledger, name, unknown_id, answer, evidence_file, confidence, poc_contract=None, by='poc'):
    """A PoC done by hand (the coordinator or the owner). The evidence file becomes a blob; a PoC that was allowed to change the
    project is refused. Low confidence records the answer but leaves the unknown open. `by` is `poc` (an AI may do this, the evidence file
    is the proof) or `owner` (the owner's own PoC; refused in an AI session, C11/C13)."""
    from . import plan as plans
    if by not in ('poc', 'owner'): raise LedgerError('--by: poc or owner.')
    if by == 'owner': plans.require_owner('owner', 'Recording a PoC as the owner decision')
    text_field(answer, 'answer', 1000)
    if confidence not in contracts.CONFIDENCE: raise LedgerError('--confidence: high, medium or low.')
    if poc_contract is not None:
        authority = (poc_contract.get('authority') or {}) if isinstance(poc_contract, dict) else {}
        if authority.get('apply_to_project') or authority.get('local_branches') or authority.get('push'):
            raise LedgerError('A PoC never applies: its contract may not carry apply_to_project, local_branches or push.')
    path = Path(evidence_file)
    if not path.is_file(): raise LedgerError('--evidence: no such file ' + str(path))
    blob = Snapshots(ledger.state_root).blob(path.read_bytes())
    answered = ('poc.answered', {'plan': name, 'unknown': unknown_id, 'answer': answer, 'confidence': confidence, 'evidence': blob,
                                 'by': by, **session_info()})
    if confidence == 'low':
        with ledger.transaction(write=True) as conn:
            state = plans.anchor_events(ledger, conn, name)
            contract, _ = plans.load(ledger, state)
            if not any(u['id'] == unknown_id and u['status'] == 'open' for u in contract['understanding']['unknowns']):
                raise LedgerError(f'Unknown {unknown_id} is not open in plan {name}.')
            plans.emit(ledger, conn, state['task_id'], *answered)
        return {'recorded': 'poc.answered', 'unknown': unknown_id, 'status': 'still open (confidence low)', 'evidence': blob}
    return _closing(ledger, name, unknown_id, by, blob, extra_events=[answered])   # the PoC's evidence file is the closing evidence


# ---- mechanical checks (0 AI calls) -------------------------------------------------------------------------------------

def _repo_root(project, path):
    """The Git repository holding project/path (qc_intake.locate: the repository may be the project, above it or below it)."""
    if not (Path(project) / path).exists(): return None, 'does not exist'
    layout = locate(project, {'package': path})
    return (layout.root, None) if layout else (None, 'is not inside a Git repository')


def check_target(ledger, contract):
    """Is the work pointed at the right place? repo exists and is a Git repository, the ref resolves, the target paths exist."""
    target, project, reasons = contract['understanding']['target'], Path(ledger.project), []
    root, problem = _repo_root(project, target['repo'])
    if root is None:
        return [('target_repo', f'target.repo {target["repo"]} {problem} (project {project}).')]
    if _commit(root, target['ref']) is None:
        reasons.append(('target_ref', f'target.ref {target["ref"]} does not resolve in {root}.'))
    directory = project if target['repo'] == '.' else project / target['repo']
    for path in target['paths']:
        if not (directory / path).exists(): reasons.append(('target_path', f'target path {path} does not exist under {directory}.'))
    return reasons


def _tail(data):
    return data.decode('utf-8', 'replace')[-TAIL:]


def _run(ledger, argv, cwd, minutes):
    env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')   # children are UTF-8 (S1)
    begin, out, err, code, timed_out = time.monotonic(), b'', b'', None, False
    try:
        process = subprocess.Popen(argv, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   creationflags=0x08000000 if os.name == 'nt' else 0)
        try:
            out, err = process.communicate(timeout=minutes * 60)
            code = process.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            command._kill_tree(process)
            out, err = process.communicate()
    except OSError as problem:
        return {'exit_code': None, 'timed_out': False, 'error': f'{type(problem).__name__}: {problem}'[:300], 'stdout': '', 'stderr': '', 'seconds': 0}
    return {'exit_code': code, 'timed_out': timed_out, 'error': None, 'stdout': _tail(out), 'stderr': _tail(err),
            'seconds': round(time.monotonic() - begin, 2)}


def run_precondition(ledger, pre):
    """One check -> {id, check, ok, detail, ...}. Never raises: a broken check is a red one."""
    project, args, check = Path(ledger.project), pre['args'], pre['check']
    result = {'id': pre['id'], 'check': check, 'why': pre['why'], 'ok': False, 'detail': ''}
    try:
        if check == 'path_exists':
            result['ok'] = (project / args['path']).exists()
            result['detail'] = args['path'] + (' exists' if result['ok'] else ' does not exist')
        elif check == 'repo_exists':
            root, problem = _repo_root(project, args['path'])
            result['ok'], result['detail'] = root is not None, f'{args["path"]} ' + (f'is in the repository {root}' if root else problem)
        elif check == 'ref_resolves':
            root, problem = _repo_root(project, args['repo'])
            commit = _commit(root, args['ref']) if root else None
            result['ok'] = commit is not None
            result['detail'] = f'{args["ref"]} -> {commit}' if commit else f'{args["ref"]} does not resolve ({problem or "unknown ref"})'
        else:
            ran = _run(ledger, args['argv'], project / args['cwd'] if args['cwd'] != '.' else project, args['max_minutes'])
            result.update(ran)
            if ran['timed_out']: result['detail'] = f'exceeded {args["max_minutes"]} minutes'
            elif ran['error']: result['detail'] = ran['error']
            elif ran['exit_code'] != 0: result['detail'] = f'exit {ran["exit_code"]}: ' + (ran['stderr'] or ran['stdout']).strip()[-200:]
            elif check == 'command_ok': result.update(ok=True, detail='exit 0')
            else:
                found = re.search(args['pattern'], ran['stdout'] + '\n' + ran['stderr'])
                result.update(ok=bool(found), detail=('matched ' + found.group(0)[:80]) if found else f'output does not match /{args["pattern"]}/')
    except (OSError, ValueError, LedgerError) as error:
        result['detail'] = f'{type(error).__name__}: {error}'[:300]
    return result


# ---- the approve gate ---------------------------------------------------------------------------------------------------

def rules_path(ledger):
    return Path(ledger.state_root) / 'plans' / 'owner-rules.md'


def is_strict(ledger, contract):
    """Is the contract held to the provenance rules? When it uses origin / decisions /
    presentation / item sources, and always once the owner-rules file exists in this state root; presence counts, not truthiness."""
    return (any(contract.get(k) is not None for k in ('origin', 'decisions', 'presentation')) or any('source' in i for i in contract['items'])
            or rules_path(ledger).exists())


def check_provenance(ledger, contract, sha, advice):
    """Where the contract comes from (origin, item sources, decisions) and whether the advisor looked at it. The full check applies to a contract
    that uses any of those fields and to every contract once the owner-rules file exists in this state root (`plan rules init`); a contract
    written before the fields existed, in a state root without the rules, is not held to them. An unknown decision id is refused always.
    An objection in the advice is never a reason: only the absence of usable advice is."""
    decisions = contract.get('decisions') or []
    known, items, reasons = {d['id'] for d in decisions}, contract['items'], []
    strict = is_strict(ledger, contract)
    if strict and not contract.get('origin'):
        reasons.append(('origin_missing', 'the contract has no origin {by, at, quote}: what the owner actually asked for, in their words.'))
    if strict:
        bare = [i['id'] for i in items if not i.get('source')]
        if bare: reasons.append(('item_without_source', 'item ' + ', '.join(bare) + ' has no source: "origin" or the id of a decision.'))
    for item in items:
        if item.get('source') not in (None, 'origin') and item['source'] not in known:
            reasons.append(('unknown_decision', f'item {item["id"]} has source {item["source"]}, which is not in decisions ({", ".join(sorted(known)) or "none"}).'))
    if decisions or (strict and contract['size'] in ('M', 'L')):
        if not advice or advice.get('sha') != sha:
            reasons.append(('advice_missing', 'no plan.advised event for this revision: run plan advise (decisions or size M/L need the advisor\'s three answers; objections do not block).'))
        elif advice.get('provider_error'):
            pass    # W27a: a typed provider error (unavailable / timeout / invalid_response) makes the advice inconclusive, with the reason
                    # recorded on plan.advised; it does NOT block approval and never becomes advice_missing (T09a). The pinned provider is unchanged.
        elif not advice.get('usable'):
            reasons.append(('advice_missing', 'the advice recorded for this revision is inconclusive (' + str(advice.get('problems') or advice.get('note') or 'no usable answers')[:100]
                            + '); run plan advise again.'))
    return reasons


def evaluate(ledger, name, revision, sha, contract, closed, choose=None, run=True, author=None, advice=None):
    """Every reason approve would refuse for. `closed` = closed_events(...). With run=False the preconditions are not executed
    (used by tests of the pure rules); approve and precheck always run them. `author` = who wrote the revision (recorded, never trusted).
    `advice` = the plan.advised payload of this revision, if any (check_provenance)."""
    u, reasons = contract['understanding'], []
    if u['confidence'] == 'low':
        reasons.append(('confidence_low', 'understanding.confidence is low: find the document, run a PoC or brainstorm until it is not.'))
    if contract['size'] in ('M', 'L') and not u['unknowns'] and len((u.get('no_unknowns_because') or '').strip()) < MIN_BECAUSE:
        reasons.append(('unknowns_missing', 'size M/L with no unknowns: either list what is not yet known, or say in understanding.no_unknowns_because '
                                            f'({MIN_BECAUSE} to 300 characters) what you checked that leaves nothing open. An empty text or "None" is not an answer.'))
    for unknown in u['unknowns']:
        if unknown['status'] == 'open':
            reasons.append(('unknown_open', f'unknown {unknown["id"]} is open: {unknown["question"][:120]} (plan unknown close / plan poc record).'))
        elif closed.get(unknown['id'], {}).get('evidence') != unknown['evidence']:
            reasons.append(('unknown_unrecorded', f'unknown {unknown["id"]} is marked closed in the file but the ledger has no matching '
                                                  'unknown.closed event; close it with plan unknown close.'))
    closer = 'owner' if author in OWNER_ACTORS else None      # C12: a statement instead of a pointer only when the owner wrote the revision
    for number, assumption in enumerate(u['assumptions'], 1):
        if not assumption['evidence']:
            reasons.append(('assumption_no_evidence', f'assumption {number} has no evidence: {assumption["text"][:100]}'))
        else:
            bad = _bad_evidence(ledger, assumption['evidence'], f'understanding.assumptions[{number}].evidence', closer)
            if bad: reasons.append(('assumption_evidence_invalid', bad))
    options = contract['options']
    if options is None:
        if choose is not None: reasons.append(('choose_without_options', f'--choose {choose}: this plan has no options.'))
    elif choose is None:
        reasons.append(('options_not_chosen', 'the plan has options and the owner has not chosen one: plan approve --choose <id> '
                                              f'(options: {", ".join(o["id"] for o in options["items"])}; recommended {options["recommended"]}).'))
    elif choose not in {o['id'] for o in options['items']}:
        reasons.append(('choose_unknown', f'--choose {choose} is not one of the options.'))
    elif not next(o for o in options['items'] if o['id'] == choose)['evidence']:
        reasons.append(('option_no_evidence', f'option {choose} has no evidence, so it counts as an unknown.'))
    for option in (options['items'] if options else ()):         # C12: every option the owner reads, not only the chosen one
        for number, text in enumerate(option['evidence'], 1):
            bad = _bad_evidence(ledger, text, f'options.items[{option["id"]}].evidence[{number}]', closer)
            if bad: reasons.append(('option_evidence_invalid', bad))
    reasons += check_target(ledger, contract)
    reasons += check_provenance(ledger, contract, sha, advice)
    results = [run_precondition(ledger, p) for p in contract['preconditions']] if run else []
    reasons += [('precondition_red', f'precondition {r["id"]} ({r["check"]}) is red: {r["detail"]}') for r in results if not r['ok']]
    receipt = None
    if results:
        body = {'kind': 'precondition-receipt', 'plan': name, 'revision': revision, 'plan_sha': sha, 'results': results}
        receipt = Snapshots(ledger.state_root).blob(canonical(body).encode('utf-8'))
    return {'ok': not reasons, 'reasons': reasons, 'results': results, 'receipt': receipt,
            'unknowns': [{'id': k['id'], 'closed_by': k['closed_by'], 'evidence': k['evidence']} for k in u['unknowns'] if k['status'] == 'closed']}


def _bad_evidence(ledger, text, field, closer):
    """C12: the reason text when `text` is not evidence by the rule that closes unknowns (blob / URL / file:line), else None."""
    try:
        evidence_kind(ledger, text, closer)
    except LedgerError as error:
        return f'{field} "{str(text)[:60]}" is not evidence: {error}'
    return None


def refusal_text(verdict):
    return (f'Approve refused: step 0 is not done ({len(verdict["reasons"])} reason{"s" if len(verdict["reasons"]) != 1 else ""}):\n'
            + '\n'.join(f' - [{code}] {text}' for code, text in verdict['reasons']))


def record_run(ledger, conn, task_id, name, revision, sha, verdict, phase):
    from . import plan as plans
    plans.emit(ledger, conn, task_id, 'precondition.recorded',
               {'plan': name, 'revision': revision, 'sha': sha, 'phase': phase, 'ok': all(r['ok'] for r in verdict['results']),
                'receipt': verdict['receipt'], 'results': [{k: r[k] for k in ('id', 'check', 'ok', 'detail')} for r in verdict['results']]})


def record_closed(ledger, conn, task_id, name, revision, sha, verdict, chosen):
    from . import plan as plans
    plans.emit(ledger, conn, task_id, 'plan.step0_closed',
               {'plan': name, 'revision': revision, 'sha': sha, 'unknowns': verdict['unknowns'], 'chosen': chosen,
                'precondition_receipt': verdict['receipt']})


def precheck(ledger, name):
    """Run the preconditions and the target check without approving anything; record the run. Plain text for the owner."""
    from . import plan as plans
    with ledger.transaction() as conn:
        state = plans.anchor_events(ledger, conn, name)
        contract, sha = plans.load(ledger, state)
        closed = closed_events(conn, state['task_id'])
        latest = state['revisions'][state['latest']]
        advice = state['advice'].get(state['latest'])
    verdict = evaluate(ledger, name, state['latest'], sha, contract, closed, choose=contract['options']['recommended'] if contract['options'] else None,
                       author=latest.get('content_author') or latest.get('author'), advice=advice)
    with ledger.transaction(write=True) as conn:
        record_run(ledger, conn, state['task_id'], name, state['latest'], sha, verdict, 'precheck')
    lines = [f'PRECHECK {name} revision {state["latest"]} (0 AI calls)']
    target = [r for r in verdict['reasons'] if r[0].startswith('target_')]
    lines.append(f'  {"RED  " if target else "GREEN"} target {contract["understanding"]["target"]["repo"]}@{contract["understanding"]["target"]["ref"]}'
                 + ''.join('\n        ' + text for _, text in target))
    lines += [f'  {"GREEN" if r["ok"] else "RED  "} {r["id"]} {r["check"]}: {r["detail"]}' for r in verdict['results']]
    lines.append('  receipt ' + str(verdict['receipt']))
    return '\n'.join(lines)


def step0_status(conn, task_id, revision):
    """For `plan show`: has step 0 been closed on this revision, and what did the last precondition run say."""
    last = {}
    for row in conn.execute('SELECT kind,payload FROM events WHERE task_id=? AND kind IN (?,?) ORDER BY seq', (task_id, 'plan.step0_closed', 'precondition.recorded')):
        payload = json.loads(row['payload'])
        if payload.get('revision') == revision: last[row['kind']] = payload
    run = last.get('precondition.recorded')
    return {'closed': 'plan.step0_closed' in last, 'chosen': (last.get('plan.step0_closed') or {}).get('chosen'),
            'preconditions': {'ok': run['ok'], 'phase': run['phase'], 'receipt': run['receipt']} if run else None}


# ---- brainstorm table ---------------------------------------------------------------------------------------------------

def _cut(text, width=112):
    text = ' '.join(str(text).split())
    return text if len(text) <= width else text[:width - 1] + '…'


def brainstorm_table(contract, chosen=None):
    """The options as a page the owner reads once: at most 30 lines (header 3 + 5 per option, options capped at 5)."""
    options = contract['options']
    if options is None: raise LedgerError('This plan has no options (size ' + contract['size'] + ').')
    lines = [f'OPTIONS for "{_cut(contract["title"], 70)}"  size {contract["size"]}  recommended {options["recommended"]}: {_cut(options["reason"], 70)}',
             'The owner chooses once: plan approve <plan> --by owner --reference ... --choose <id>', '-' * 100]
    for o in options['items']:
        mark = ('CHOSEN ' if o['id'] == chosen else '') + ('(recommended)' if o['id'] == options['recommended'] else '')
        lines += [f'{o["id"]} {mark} {_cut(o["summary"], 90)}',
                  f'   evidence {len(o["evidence"])}: {_cut("; ".join(o["evidence"]) or "NONE - counts as an unknown", 90)}',
                  f'   + {_cut("; ".join(o["strengths"]) or "-", 100)}',
                  f'   - {_cut("; ".join(o["weaknesses"]) or "-", 100)}   unknowns: {_cut("; ".join(o["unknowns"]) or "-", 60)}',
                  f'   cost {_cut(o["cost"], 40)} | risk {_cut(o["risk"], 40)}']
    return '\n'.join(lines)
