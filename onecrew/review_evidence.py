"""Immutable, bounded review receipts with explicit retrieval rather than hidden truncation."""
import hashlib
import json
import re
from .ledger import LedgerError, canonical

PROTOCOL = 2
MAX_ROUNDS = 10      # P6: evidence round trips of ONE completion review (work mode). A receipt that does not fit arrives page by page,
                     # one round each (a 12,000-character read is ~8 pages of an S1-shape review under Kiro's cap); before, 3 rounds of
                     # whole receipts. Every round is a reviewer call, so the bound is explicit.
LEGACY_ROUNDS = 3    # the other modes keep their earlier rule: three rounds, the same request twice is "unavailable"
MAX_CONTENT = 45000
PAGE_DEFAULT = 12000  # characters for the requested pages when the caller has no prompt cap to respect
PAGE_WRAPPER = 260    # what one requested page adds around the paged result: blob, field hashes, the request itself
PAGE_SLACK = 400      # paging.view reserves the worst case for its page entries (large offsets, both continuations)
DEFERRED_ENTRY = 200  # what the entry of a deferred request (its request, the message) takes in the prompt
REQUEST_KEYS = ('index', 'field', 'offset', 'item_offset')
# P6 (finding lifecycle). What a completion review finds is a property of the JOB, not of one review: the reviewer is stateless and the
# worker may be rejected, fix, finish again, be reviewed by a different round, candidate or runner. The findings and the reviewer's
# notes are therefore kept in a register in the checkpoint (state['review_register']) that no review, rejection, candidate change or
# restart empties; the only way out of "open" is a recorded resolution naming evidence the reviewer was given. The text of each
# (finding, note, closing reason) is stored WHOLE, as written, once, in the content-addressed blob store; the register holds its
# reference, its length and a head. The prompt receives a bounded rendering and fetches the rest through the same paging the receipts
# use (evidence_requests {index: "RF3" | "N2" | "RF", ...}). Nothing here is cut to fit a number: what cannot be held is an
# explicit incomplete review (ReviewEvidenceIncomplete), never an acceptance.
MAX_TRACKED = 500     # OPEN findings one job's register holds (closed ones stay, as heads, up to four times that); beyond it the
                      # review is incomplete, not accepted
MAX_TEXT = 200000     # characters of one finding, note or closing reason kept whole (beyond it: incomplete, not cut)
HEAD = 500            # characters of a text kept in the register itself (prompt rendering, handover); the whole is in the blob
HEAD_CLOSED = 160     # the head a closed finding / an older review's note keeps
RECEIPT_BYTES = 1200000  # serialized bytes of finding text a rejection receipt carries whole (the blob store takes 2,000,000); beyond it
                         # entries carry their head, then only their id and where the whole is
MEMORY_TIERS = (900, 400, 120)   # characters of the prompt the memory may take, richest first; the last always fits (ids, heads)
FINDINGS_RULE = ('findings: defects you see (strings). Close an open_findings id in resolved: "RF<n>:<receipt shown>:<why>". '
                 'Accepting with one open is refused.')
RETRIEVE_RULE = ' Cut text (chars) or open_more: evidence_requests {index:"RF3"|"N2"|"RF",field:"claim"|"text"|"open"}.'
# both are matched against the STRIPPED string: (.*\S)\s*$ backtracks quadratically on a long whitespace tail
_CLOSE = re.compile(r'^(RF\d+)\s*:\s*(\d+)\s*:\s*(.+)$', re.S | re.I)
_CITE = re.compile(r'^r(\d+)\s*:\s*(.+)$', re.S | re.I)
_ID = re.compile(r'^(RF\d+|N\d+|RF)$')


class ReviewRejected(LedgerError):
    pass


class ReviewEvidenceIncomplete(LedgerError):
    """P6: the completion reviewer asked for evidence the review could not be given within its bound (the rounds were used up, or
    the same page was asked again), or what it reported could not be held whole. It is neither an acceptance nor a rejection of the
    work: the job is blocked, naming what was missing, and the worker is not called for it."""


def known_ids(state):
    """The ids the reviewer can ask for besides receipt indexes: findings (RF<n>), notes (N<n>) and the list of findings (RF)."""
    register = state.get('review_register') or {}
    return {'RF'} | {f['id'] for f in register.get('findings') or []} | {n['id'] for n in register.get('notes') or []}


def _virtual_id(value):
    """'RF3', 'rf3', ' N2 ' -> 'RF3' / 'N2' (the ids of the register); None when the string is not the form of one."""
    if not isinstance(value, str): return None
    ident = value.strip().upper()
    return ident if _ID.match(ident) else None


def _checked(item, valid, ids=()):
    """One request: a receipt index, a finding/note id, or {index, field, offset, item_offset} (the arguments of the worker's
    `receipt` action, copied from the `next` of a page). A request that names only the index is that index. A finding or note id that
    is of the right form but names nothing is still a request: it is answered with an error entry that says so (not with a failed
    provider call); only a request of no valid form is refused."""
    if type(item) is int and item in valid: return item
    if isinstance(item, str):
        ident = _virtual_id(item)  # a finding, a note or the list of findings: its first page
        if ident: return {'index': ident, 'field': None, 'offset': 0, 'item_offset': 0}
        # A bare string is only ever a register id (RF<n>/N<n>/RF). A receipt index is an int, or the {index,...}
        # arguments of a page; a numeric string is neither, so it is refused, not read as an index.
        raise LedgerError('Reviewer requested unknown evidence.')
    if isinstance(item, dict):
        index, field = item.get('index'), item.get('field')
        offset, item_offset = item.get('offset', 0), item.get('item_offset', 0)
        if isinstance(index, str):
            ident = _virtual_id(index)
            index = ident if ident else (int(index) if index.strip().isdigit() else index)
        known = (type(index) is int and index in valid) or (isinstance(index, str) and bool(_ID.match(index)))
        if (not set(item) <= set(REQUEST_KEYS) or not known
                or not (field is None or isinstance(field, str))
                or type(offset) is not int or offset < 0 or type(item_offset) is not int or item_offset < 0
                or (field is None and (offset or item_offset))):
            raise LedgerError('Reviewer requested unknown evidence.')
        if field is None: return index if type(index) is int else {'index': index, 'field': None, 'offset': 0, 'item_offset': 0}
        return {'index': index, 'field': field, 'offset': offset, 'item_offset': item_offset}
    raise LedgerError('Reviewer requested unknown evidence.')


def request_key(item, state=None):
    """The identity of a request within one review (the same page is not given twice). A finding/note request also names the state
    of the register it was asked in: the list of findings after a closure is not the page it was given before."""
    if state is not None and isinstance(item, dict) and isinstance(item.get('index'), str):
        findings = (state.get('review_register') or {}).get('findings') or []
        version = [len(findings), sum(1 for f in findings if f.get('status') == 'resolved'),
                   len((state.get('review_register') or {}).get('notes') or [])]
        return canonical([item, version])
    return canonical(item)


def describe(item):
    if isinstance(item, int): return f'receipt {item}'
    subject = f"receipt {item['index']}" if isinstance(item['index'], int) else str(item['index'])
    where = f"{item['field']} from offset {item['offset']}" if item.get('field') else 'from the start'
    return f"{subject} {where}" + (f", item_offset {item['item_offset']}" if item.get('item_offset') else '')


def requests(review, state):
    values = review.get('evidence_requests', [])
    valid = {r['index'] for r in state['receipts']}
    ids = known_ids(state)
    if not isinstance(values, list) or len(values) > 4:
        raise LedgerError('Reviewer requested unknown evidence.')
    wanted = []
    for value in values:
        item = _checked(value, valid, ids)
        if item not in wanted: wanted.append(item)
    if wanted and review['accepted']: raise LedgerError('Reviewer cannot accept while requesting evidence.')
    return wanted


def _sha(value):
    return hashlib.sha256((value if isinstance(value, str) else canonical(value)).encode('utf-8', 'surrogatepass')).hexdigest()


def _put(store, text, what):
    """The whole of `text`, as written, in the blob store. A text that cannot be held whole, or a store that cannot be written, is an
    incomplete review: the caller has changed nothing yet, so nothing is half recorded."""
    if len(text) > MAX_TEXT:
        raise ReviewEvidenceIncomplete(f'{what} is {len(text)} characters; the review keeps at most {MAX_TEXT} characters of one finding or '
                                       'note whole and never cuts it, so nothing was accepted.')
    try: return store.blob(text.encode('utf-8', 'surrogatepass'))
    except (OSError, LedgerError) as error:
        raise ReviewEvidenceIncomplete(f'{what} could not be stored whole ({str(error)[:200]}); the review is incomplete and nothing was accepted.')


def _full(store, entry):
    """The whole text of a finding, note or closing reason: its blob (or the text itself when it was kept without a store)."""
    if 'text' in entry: return entry['text']
    return store.read_blob(entry['blob']).decode('utf-8', 'surrogatepass')


def _label(index):
    return f'receipt {index}' if isinstance(index, int) else str(index)


def virtual(state, store, ident):
    """The record behind a finding / note id, as a stored result the paging contract can page: {'action', 'result'} and the blob its
    long text is in (the reviewer puts the pages back together and checks them against it and the field's sha256)."""
    register = state.get('review_register') or {}
    findings, notes = register.get('findings') or [], register.get('notes') or []
    if ident == 'RF':
        listing = {'open': [], 'resolved': []}
        for f in findings:
            row = {'id': f['id'], 'review': f['review'], 'round': f['round'], 'chars': f['chars'], 'head': f['head']}
            if f['status'] == 'open':
                if f.get('closure_refused'): row['closure_refused'] = f['closure_refused']
                listing['open'].append(row)
            else:
                row['resolution'] = {k: f['resolution'].get(k) for k in ('review', 'round', 'receipt', 'kind', 'chars')}
                listing['resolved'].append(row)
        return {'action': 'review_findings', 'result': listing}, None
    finding = next((f for f in findings if f['id'] == ident), None)
    if finding is not None:
        result = {'id': finding['id'], 'status': finding['status'], 'claim': _full(store, finding), 'chars': finding['chars'],
                  'review': finding['review'], 'round': finding['round'], 'receipt': finding['source'].get('receipt')}
        if finding.get('closure_refused'): result['closure_refused'] = finding['closure_refused']
        resolution = finding.get('resolution')
        if resolution:
            result['resolution'] = {k: resolution.get(k) for k in ('review', 'round', 'receipt', 'kind', 'candidate', 'chars')}
            result['resolution_text'] = _full(store, resolution)
        return {'action': 'review_finding', 'result': result}, finding.get('blob')
    note = next((n for n in notes if n['id'] == ident), None)
    if note is not None:
        return {'action': 'review_note', 'result': {'id': note['id'], 'review': note['review'], 'round': note['round'],
                                                   'chars': note['chars'], 'text': _full(store, note), 'pages': note.get('pages')}}, note.get('blob')
    raise LedgerError(f'The job has no finding or note {ident!r}.')


def _requested_pages(runtime, state, refs, requested, seen, page, task_id):
    """The requested receipts (and findings/notes) that did not fit whole, as pages through paging.view (the worker's own paging, not
    a cutter of the reviewer's). Returns (pages, not_delivered). A page that cannot be a VALID page (MIN_PAGE of the receipt's own
    content, or all that is left of it) is not delivered: the runtime is told (_page_starved) and the prompt is not sent. When several
    requests do not all get a valid page in the room there is, the first ones are served and the others are DEFERRED: an entry that
    says so, and their keys in runtime._deferred (the run loop forgets them, so they can be asked again alone)."""
    from .paging import MIN_PAGE, view
    runtime._deferred = []
    todo, originals = [], []
    for r in requested:
        if isinstance(r, dict): todo.append(r); originals.append(r)
        elif refs[r]['blob'] not in seen: todo.append({'index': r, 'field': None, 'offset': 0, 'item_offset': 0}); originals.append(r)
    if not todo or page == 0: return [], []

    def source(r):  # the stored record, the blob it is addressed by, and the page of it within a budget
        if isinstance(r['index'], str):
            record, blob = virtual(state, runtime.store, r['index'])
            return record, blob, lambda budget: view(record, budget, index=r['index'], field=r['field'], offset=r['offset'],
                                                      item_offset=r['item_offset'])
        ref = refs[r['index']]
        return (runtime._receipt_source(state, ref)[0], ref['blob'],
                lambda budget: runtime._review_page(state, ref, task_id, budget, r['field'], r['offset'], r['item_offset']))
    whole, sizes, held, wants = [], [], [], []
    for r in todo:  # what each request would deliver with all the room it wants, and the least room a valid page of it takes
        try: record, blob, pager = source(r)
        except LedgerError as error:  # no such finding or note
            held.append((None, None, None)); whole.append(error); sizes.append(PAGE_WRAPPER + 400); wants.append(PAGE_WRAPPER + 400); continue
        held.append((record, blob, pager))
        try:
            if r['item_offset']:  # the worker's `receipt` action refuses this the same way (owned._tool)
                field_value = (record.get('result') or {}).get(r['field'])
                if not isinstance(field_value, list): raise LedgerError(f"item_offset selects part of one item of a list field; {r['field']!r} is not a list.")
            value, pages = pager(10 ** 8)
            size = len(canonical(value)) + len(canonical(pages)) + PAGE_WRAPPER + PAGE_SLACK
            whole.append((value, pages)); sizes.append(size)
            wants.append(min(size, min(MIN_PAGE, runtime._content(dict(value), pages)) + PAGE_WRAPPER + PAGE_SLACK))
        except LedgerError as error:
            whole.append(error); sizes.append(PAGE_WRAPPER + 400); wants.append(PAGE_WRAPPER + 400)
    budget = PAGE_DEFAULT if page is None else page
    chosen = list(range(len(todo)))  # the first ones asked are served; the last are deferred until the rest fit with the entries that
    while len(chosen) > 1:           # say so (the first is always tried: the page itself decides whether it starves the prompt)
        if sum(wants[i] for i in chosen) + DEFERRED_ENTRY * (len(todo) - len(chosen)) <= budget: break
        chosen.pop()
    deferred = [i for i in range(len(todo)) if i not in chosen]
    order, left, alloc = sorted(chosen, key=lambda i: sizes[i]), budget - DEFERRED_ENTRY * len(deferred), {}
    for n, i in enumerate(order):  # the room is shared like water: small requests whole, the rest to the large ones
        alloc[i] = min(sizes[i], left // (len(order) - n)); left -= alloc[i]
    delivered, missing = [], []
    for i, r in enumerate(todo):
        record, blob, pager = held[i]
        if i in deferred:
            delivered.append({'index': r['index'], 'request': r, 'error': 'deferred: no room beside the others; ask it alone',
                              'deferred': True})
            runtime._deferred.append(request_key(originals[i], state)); continue
        if isinstance(whole[i], LedgerError):  # a wrong request (no such field...): the reviewer is told, not starved
            entry = {'index': r['index'], 'request': r, 'error': str(whole[i])[:300]}
            if blob: entry['blob'] = blob
            delivered.append(entry); continue
        full_value, full_pages = whole[i]
        want = min(MIN_PAGE, runtime._content(dict(full_value), full_pages))
        try:
            value, pages = pager(max(200, alloc[i] - PAGE_WRAPPER))
            content = runtime._content(dict(value), pages)
        except LedgerError as error:
            value, pages, content = None, [], -1
            runtime._starved_reason = f"{_label(r['index'])}: {str(error)[:200]}"
        if content < want or value is None:
            runtime._page_starved = True
            if value is not None: runtime._starved_reason = f"{_label(r['index'])}: the largest page that fits carries {content} characters of it; a valid page carries {want}"
            missing.append(r['index']); continue
        entry = dict(value, request=r)
        if blob: entry['blob'] = blob
        if pages: entry['page'] = pages
        else: entry['complete'] = True
        source_result = record.get('result') or {}
        hashes = {p['field']: _sha(source_result[p['field']]) for p in pages if 'source' not in p and p['field'] in source_result}
        if hashes: entry['field_sha256'] = hashes
        delivered.append(entry)
    return delivered, missing


def shown_receipts(prompt):
    """The receipt indexes a review prompt carried: whole (full_receipts) or as a page (requested_pages)."""
    _, _, body = (prompt or '').rpartition('\n{')
    try: value = json.loads('{' + body)
    except ValueError: return set()
    evidence = value.get('evidence') if isinstance(value, dict) else None
    shown = set()
    for key in ('full_receipts', 'requested_pages'):
        for item in (evidence or {}).get(key) or []:
            if isinstance(item, dict) and type(item.get('index')) is int and 'error' not in item: shown.add(item['index'])
    return shown


def shown_findings(prompt):
    """The finding ids a review prompt put in front of the reviewer: listed in open_findings, or delivered as pages (RF<n>, or the
    rows of the RF list)."""
    _, _, body = (prompt or '').rpartition('\n{')
    try: value = json.loads('{' + body)
    except ValueError: return set()
    if not isinstance(value, dict): return set()
    ids = set()
    for item in value.get('open_findings') or []:
        ident = item.get('id') if isinstance(item, dict) else item
        if isinstance(ident, str): ids.add(ident)
    for entry in ((value.get('evidence') or {}).get('requested_pages') or []):
        if not isinstance(entry, dict) or 'error' in entry or not isinstance(entry.get('index'), str): continue
        if entry['index'].startswith('RF') and entry['index'] != 'RF': ids.add(entry['index'])
        result = entry.get('result') if isinstance(entry.get('result'), dict) else {}
        for key in ('open', 'resolved'):
            for row in result.get(key) or []:
                if isinstance(row, dict) and isinstance(row.get('id'), str): ids.add(row['id'])
    return ids


def _texts(value):
    """What the reviewer wrote in findings / resolved, as non-empty strings. Nothing it wrote is dropped for its shape."""
    if isinstance(value, (str, dict)): value = [value]
    elif not isinstance(value, list): return []
    out = []
    for item in value:
        text = item if isinstance(item, str) else canonical(item)
        if text.strip(): out.append(text)
    return out


def _norm(text):
    """What makes two findings the same defect: the same words in the same case (whitespace is not a difference). Two defects that
    differ in a name's case or in code are two findings; one finding is never silently merged into another."""
    return ' '.join(str(text).split())


def _safe(text):
    """A text as the checkpoint can hold it (a lone surrogate cannot be written as UTF-8); the blob keeps the exact characters."""
    return str(text).encode('utf-8', 'replace').decode('utf-8')


def open_findings(state):
    found = [f for f in (state.get('review_register') or {}).get('findings') or [] if f.get('status') == 'open']
    # a checkpoint written by the unreleased d5a0c43 intermediate (state['review_findings']): its open findings cannot be closed here,
    # but they are never invisible to the gate - the job stays unaccepted until an operator decides (fail closed)
    for old in state.get('review_findings') or []:
        if isinstance(old, dict) and old.get('status') == 'open':
            claim = str(old.get('claim', ''))
            found.append({'id': str(old.get('id', 'RF?')), 'status': 'open', 'review': 0, 'round': old.get('round', 0), 'candidate': None,
                          'chars': old.get('chars', len(claim)), 'head': claim[:HEAD], 'norm': '', 'legacy': True,
                          'source': dict(old.get('source') or {})})
    return found


def _candidate(state):
    return ((state.get('work') or {}).get('verification') or {}).get('candidate')


def record_round(state, review, *, shown, round_no, store=None, listed=None, close=True):
    """Put what the reviewer reported in one round into the job's register in the checkpoint, BEFORE anything is decided from the
    answer. `shown`: the receipts that round's prompt carried (a finding is closed only by evidence the reviewer was given in this
    review); `listed`: the finding ids the prompts of this review put in front of it (None: not checked). `close=False`: the answer
    is not usable (its request was invalid) - what it REPORTS still binds, what it closes does not. Returns {'opened': [ids],
    'closed': [ids], 'refused': [why]}; a closure that is not understood or has no evidence leaves the finding open, with the reason
    on it (the next prompt shows it).

    All or nothing: the answer is checked and every text stored before the state changes. A finding that cannot be held whole (a text
    over MAX_TEXT, a full register, a store that cannot be written) raises ReviewEvidenceIncomplete with the register untouched."""
    register = state.get('review_register')
    findings = (register or {}).get('findings') or []
    ordinal = (register or {}).get('review', 1)
    reached = sorted(set(state.get('review_shown') or []) | set(shown))
    seen_ids = sorted(set(state.get('review_listed') or []) | set(listed or ()))
    candidate = _candidate(state)
    held = {r['index']: r for r in state.get('receipts') or []}
    by_id = {f['id']: f for f in findings}
    result = {'opened': [], 'closed': [], 'refused': []}
    closing, refused_on, taken = [], {}, set()
    for text in _texts(review.get('resolved')) if close else []:
        match = _CLOSE.match(text.strip())
        if not match: result['refused'].append('not understood (RF<n>:<receipt>:<why>): ' + text[:60]); continue
        ident, receipt = match.group(1).upper(), int(match.group(2))
        target = by_id.get(ident)
        if target is None or target['status'] != 'open' or ident in taken:
            result['refused'].append(f'{ident} is not an open finding'); continue
        if listed is not None and ident not in seen_ids:
            refused_on[ident] = f'{ident} was not shown to the reviewer in this review'
        elif receipt not in reached:
            refused_on[ident] = f'receipt {receipt} was not shown in this review'
        elif (held.get(receipt) or {}).get('action') == 'finish':
            refused_on[ident] = f'receipt {receipt} is a finish: the rejection that carries a finding is not evidence that it is resolved'
        if ident in refused_on:
            result['refused'].append(f'{ident}: ' + refused_on[ident]); continue
        closing.append((target, receipt, text)); taken.add(ident)
    # the same defect reported again alongside the closure of the finding that states it is a NEW finding: closing and re-reporting
    # one claim in one answer contradict each other, and the claim must not vanish between them
    known = {f['norm'] for f in findings if f['status'] == 'open' and f['id'] not in taken}
    pages = list(state.get('review_requests') or [])
    new = []
    for text in _texts(review.get('findings')):
        cite = _CITE.match(text.strip())
        receipt, claim = (int(cite.group(1)), cite.group(2).strip()) if cite else (None, text.strip())
        norm = _sha(_norm(claim))  # the whole claim: two findings that share a prefix are two findings
        if norm in known: continue  # the same defect reported again: one finding
        known.add(norm); new.append((text, receipt, norm))
    tracked = sum(1 for f in findings if f['status'] == 'open') - len(taken) + len(new)
    if tracked > MAX_TRACKED or len(findings) + len(new) > 4 * MAX_TRACKED:
        where = ''
        if store is not None and new:
            try: where = f' Its findings are kept whole in blob {_put(store, canonical([t for t, _, _ in new]), "the findings of this answer")}.'
            except ReviewEvidenceIncomplete: pass
        raise ReviewEvidenceIncomplete(f'The reviewer reported {len(new)} new finding(s) and the job already has '
                                       f'{sum(1 for f in findings if f["status"] == "open")} open; one job tracks at most {MAX_TRACKED} open '
                                       'findings, so none of this answer was recorded and nothing was accepted.' + where)
    # every text goes to the blob store first: a failure leaves the register exactly as it was
    stored = {}
    if store is not None:
        for _, _, how in closing: stored[('how', how)] = _put(store, how, 'a closing reason')
        for text, _, _ in new: stored[('claim', text)] = _put(store, text, 'a finding')
    def keep(text, blob):
        return {'blob': blob} if blob is not None else {'text': _safe(text)}
    register = state.setdefault('review_register', {'next': 1, 'notes_next': 1, 'review': 1, 'findings': [], 'notes': []})
    state['review_shown'] = reached
    if listed is not None: state['review_listed'] = seen_ids
    for ident, why in refused_on.items(): by_id[ident]['closure_refused'] = why
    for target, receipt, how in closing:
        target.pop('closure_refused', None)
        target['head'] = target['head'][:HEAD_CLOSED]
        target.update(status='resolved', resolution=dict(
            {'review': ordinal, 'round': round_no, 'receipt': receipt, 'candidate': candidate, 'chars': len(how),
             'head': _safe(how[:HEAD_CLOSED]),
             'kind': 'new_evidence' if receipt > target.get('receipts_at', 0) else 'earlier_evidence'},
            **keep(how, stored.get(('how', how)))))
        result['closed'].append(target['id'])
    for text, receipt, norm in new:
        number = register['next']; register['next'] = number + 1
        register['findings'].append(dict(
            {'id': f'RF{number}', 'status': 'open', 'review': ordinal, 'round': round_no, 'candidate': candidate,
             'receipts_at': len(state.get('receipts') or []), 'chars': len(text), 'head': _safe(text[:HEAD]), 'norm': norm,
             'source': {'round': round_no, 'receipt': receipt, 'pages': pages}},
            **keep(text, stored.get(('claim', text)))))
        result['opened'].append(f'RF{number}')
    return result


def record_rejection(state, review, *, round_no, store=None):
    """A decided rejection that named no defect in `findings` is still the reviewer's recorded verdict: when the job has no open
    finding and the answer opened none, its feedback is registered whole as one finding (source kind 'feedback'), so a later review
    of an unchanged candidate cannot forget it. Returns the new id, or None."""
    text = review.get('feedback')
    if review.get('accepted') or review.get('core') or not isinstance(text, str) or not text.strip(): return None
    if open_findings(state): return None
    blob = _put(store, text, 'the rejection') if store is not None else None
    register = state.setdefault('review_register', {'next': 1, 'notes_next': 1, 'review': 1, 'findings': [], 'notes': []})
    number = register['next']; register['next'] = number + 1
    entry = {'id': f'RF{number}', 'status': 'open', 'review': register['review'], 'round': round_no, 'candidate': _candidate(state),
             'receipts_at': len(state.get('receipts') or []), 'chars': len(text), 'head': _safe(text[:HEAD]),
             'norm': _sha(_norm(text)), 'source': {'round': round_no, 'receipt': None, 'kind': 'feedback',
                                                    'pages': list(state.get('review_requests') or [])}}
    entry.update({'blob': blob} if blob is not None else {'text': _safe(text)})
    register['findings'].append(entry)
    return entry['id']


def adopt_legacy(state, store):
    """A checkpoint of the unreleased d5a0c43 intermediate kept the findings of a review in state['review_findings'] and its notes in
    state['review_notes'] (text cut to 2,000 characters). They move into the register - ids, status, round, source, resolution kept,
    the text they still have stored whole in the blob store and marked as cut - and the old keys go, so such a job is closable."""
    old_findings, old_notes = state.get('review_findings'), state.get('review_notes')
    if not old_findings and not old_notes:
        for key in ('review_findings', 'review_notes', 'review_findings_unrecorded'): state.pop(key, None)
        return
    register = state.setdefault('review_register', {'next': 1, 'notes_next': 1, 'review': 1, 'findings': [], 'notes': []})
    cut = 'the earlier runtime kept at most 2,000 characters of this text'
    for old in old_findings or []:
        if not isinstance(old, dict): continue
        claim = str(old.get('claim', ''))
        ident = str(old.get('id', f"RF{register['next']}"))
        entry = {'id': ident, 'status': 'resolved' if old.get('status') == 'resolved' else 'open', 'review': register['review'],
                 'round': old.get('round', 0), 'candidate': None, 'receipts_at': 0, 'chars': old.get('chars', len(claim)),
                 'head': _safe(claim[:HEAD]), 'norm': _sha(_norm(claim)), 'source': dict(old.get('source') or {}), 'legacy': cut}
        entry['blob'] = _put(store, claim, 'a finding of the earlier runtime')
        resolution = old.get('resolution')
        if entry['status'] == 'resolved' and isinstance(resolution, dict):
            how = str(resolution.get('how', ''))
            entry['resolution'] = {'review': register['review'], 'round': resolution.get('round', 0), 'receipt': resolution.get('receipt'),
                                   'candidate': None, 'chars': resolution.get('chars', len(how)), 'head': _safe(how[:HEAD_CLOSED]),
                                   'kind': 'earlier_evidence', 'blob': _put(store, how, 'a closing reason of the earlier runtime')}
        if old.get('closure_refused') and entry['status'] == 'open': entry['closure_refused'] = str(old['closure_refused'])
        register['findings'].append(entry)
        if ident[2:].isdigit(): register['next'] = max(register['next'], int(ident[2:]) + 1)
    for old in old_notes or []:
        text = str(old.get('text', '')) if isinstance(old, dict) else str(old)
        ident = str(old.get('id', f"N{register['notes_next']}")) if isinstance(old, dict) else f"N{register['notes_next']}"
        register['notes'].append({'id': ident, 'review': register['review'], 'round': old.get('round', 0) if isinstance(old, dict) else 0,
                                  'chars': old.get('chars', len(text)) if isinstance(old, dict) else len(text), 'head': _safe(text[:HEAD]),
                                  'pages': list(old.get('pages') or []) if isinstance(old, dict) else [], 'blob': _put(store, text, 'a note'),
                                  'legacy': cut})
        if ident[1:].isdigit(): register['notes_next'] = max(register['notes_next'], int(ident[1:]) + 1)
    for key in ('review_findings', 'review_notes', 'review_findings_unrecorded'): state.pop(key, None)


def keep_note(state, feedback, round_no, store=None):
    """A reviewer's note of an evidence round, kept whole (as written) with the pages it was written over. Notes are progress; what is
    wrong is a finding. Returns the note's id (None: nothing was written)."""
    text = feedback if isinstance(feedback, str) else ''
    if not text.strip(): return None
    blob = _put(store, text, 'a review note') if store is not None else None
    register = state.setdefault('review_register', {'next': 1, 'notes_next': 1, 'review': 1, 'findings': [], 'notes': []})
    number = register['notes_next']; register['notes_next'] = number + 1
    note = {'id': f'N{number}', 'review': register['review'], 'round': round_no, 'chars': len(text), 'head': _safe(text[:HEAD]),
            'pages': list(state.get('review_requests') or [])}
    note.update({'blob': blob} if blob is not None else {'text': _safe(text)})
    register['notes'].append(note)
    return note['id']


def close_review(state):
    """The rounds of one completion review are over (decided, or not decided): its page cursors, requests and what it was shown go.
    The register stays whole - open findings carry into the next review, which numbers one higher. Only the heads of the finished
    review's notes are shortened (their text is in the blob store)."""
    for key in ('review_requests', 'review_evidence_rounds', 'review_seen', 'review_shown', 'review_listed'):
        state.pop(key, None)
    register = state.get('review_register')
    if register:
        for note in register.get('notes') or []:
            if note.get('review') == register['review']: note['head'] = note['head'][:HEAD_CLOSED]
        register['review'] += 1


def memory(state, budget):
    """(open_findings, notes, closed, more) for the prompt within `budget` characters of JSON. An open finding is never left out
    without a word: it is its id, then its claim as long as the room allows; when even the ids do not fit, a window of them and
    `more` (how many open ones are not listed; the list is one evidence request away). Notes of this review come newest first
    while they fit and the ones that do not are named, never dropped without a word. The whole text of both is in the blob store."""
    register = state.get('review_register') or {}
    ordinal = register.get('review', 1)
    opened = open_findings(state)
    notes = [n for n in register.get('notes') or [] if n.get('review') == ordinal]
    closed = [f['id'] for f in register.get('findings') or []
              if f.get('status') == 'resolved' and (f.get('resolution') or {}).get('review') == ordinal]
    def size(a, b, c, m):
        return len(canonical({'open_findings': a, **({'open_more': m} if m else {}), 'review_notes': b, **({'findings_closed': c} if c else {})}))
    def entries(limit):
        out = []
        for f in opened:
            head = f['head']
            claim = head if len(head) <= limit else head[:limit] + '…'
            entry = {'id': f['id'], 'claim': claim}
            if f['chars'] > min(len(head), limit): entry['chars'] = f['chars']
            if f.get('closure_refused'): entry['closure_refused'] = f['closure_refused']
            out.append(entry)
        return out
    share = budget if not notes else max(budget * 2 // 3, min(budget, 120))
    limit, shown, more = HEAD, entries(HEAD), 0
    while opened and size(shown, [], closed, 0) > share and limit > 16:
        limit = max(16, limit * 7 // 10); shown = entries(limit)
    if opened and size(shown, [], closed, 0) > share:
        shown = [f['id'] for f in opened]  # ids: the names survive as long as there is room
        if size(shown, [], closed, 0) > share: closed = []  # which findings are closed is information; the first to go
        if size(shown, [], closed, 0) > share:  # a window of ids, and how many are not in it
            total = len(shown)
            while shown and size(shown, [], closed, total - len(shown)) > share: shown.pop()
            more = total - len(shown)
    lines, omitted, remaining = [], [], budget - size(shown, [], closed, more) - 64
    for note in reversed(notes):
        cut = '' if note['chars'] <= len(note['head']) else f"…[{note['chars']} chars kept in the review state]"
        line = f"{note['id']} r{note['round']}: {note['head']}{cut}"
        if len(canonical(line)) <= remaining:
            lines.append(line); remaining -= len(canonical(line)) + 1
        elif remaining >= 70 and not lines:  # the newest note that does not fit whole: its head, with its length
            lines.append(f"{note['id']} r{note['round']}: {note['head'][:remaining - 60]}…[{note['chars']} chars kept in the review state]")
            remaining = 0
        else: omitted.append(note['id'])
    lines.reverse()
    earlier = [n['id'] for n in register.get('notes') or [] if n.get('review') != ordinal]
    if omitted:  # their ids and text are in the register / blob store
        lines.insert(0, f"{len(omitted)} older note(s) kept in the review state: {', '.join(reversed(omitted[-4:]))}" + ('…' if len(omitted) > 4 else ''))
    if closed and size(shown, lines, closed, more) > budget: closed = []
    if size(shown, lines, closed, more) > budget:  # the smallest room: no note, only how many there are, when even that fits
        count = [f"{len(notes)} note(s) kept in the review state"] if notes else []
        lines = count if size(shown, count, closed, more) <= budget else []
    if earlier:  # notes of the job's earlier reviews are not in the prompt; they are named so they can be asked for by id
        pointer = f"notes of earlier reviews, ask by id: {earlier[0]}..{earlier[-1]}" if len(earlier) > 1 else f"note of an earlier review: {earlier[0]}"
        if size(shown, [pointer] + lines, closed, more) <= budget: lines = [pointer] + lines
    return shown, lines, closed, more


def _listing(state, limit, skip=()):
    """(text, whole): the open findings, each with its head, and whether every one of them is in the text with its whole claim."""
    opened = [f for f in open_findings(state) if f['id'] not in skip]
    if not opened: return '', True
    per = max(120, min(HEAD, limit // len(opened)))
    parts, used, rest, whole = [], 0, [], True
    for position, f in enumerate(opened):
        cite = f['source'].get('receipt')
        complete = f['chars'] <= len(f['head']) <= per
        claim = f['head'] if complete else f['head'][:per] + f"…[{f['chars']} chars]"
        refused = f" [closure refused: {f['closure_refused']}]" if f.get('closure_refused') else ''
        part = f"{f['id']} (review {f['review']}, round {f['round']}{'' if cite is None else f', receipt {cite}'}): {claim}{refused}"
        if parts and used + len(part) > limit: rest = opened[position:]; break
        parts.append(part); used += len(part) + 3
        whole = whole and complete
    tail = f" | and {len(rest)} more, not closed: {', '.join(f['id'] for f in rest)}" if rest else ''
    text = f'{len(opened)} finding(s) recorded by the reviewer for this job and not closed with evidence: ' + ' | '.join(parts) + tail
    return text, whole and not rest


def findings_text(state, limit=400, skip=()):
    """The open findings, each with its head, for whoever has to act on them (the worker after a rejection, the operator of a blocked
    job). `limit` bounds the text; a finding that does not fit is named by its id with the others it stands with."""
    return _listing(state, limit, skip)[0]


def findings_whole(state, limit=400):
    """True when findings_text(state, limit) carries every open finding with its whole claim (nothing cut, nothing only named)."""
    return _listing(state, limit)[1]


LISTING = 400         # characters of findings_text a rejection carries when it can hold every open finding whole; when it cannot
                      # the rejection is one short line and the whole texts are in the `findings` of its receipt (receipt_findings)


def with_findings(state, feedback, skip=()):
    """The reviewer's feedback with the open findings in FRONT of it (the rejection text is cut at the end, not at the findings).
    `skip`: ids that are this very feedback registered as a finding (it is not said twice)."""
    text = findings_text(state, LISTING, skip)
    return f'{text}\n{feedback}' if text else feedback


def receipt_findings(store, state):
    """Every open finding for the worker, as the `findings` list of a rejection's receipt (the worker pages it with the receipt
    action): the whole text while the serialized list stays within RECEIPT_BYTES, then each entry's head, then only its id and where
    the whole is - the receipt is a blob (2,000,000 bytes at most) and must always be writable."""
    rows, used = [], 0
    for f in open_findings(state):
        row = {'id': f['id'], 'review': f['review'], 'round': f['round'], 'receipt': f['source'].get('receipt'), 'chars': f['chars']}
        if f.get('closure_refused'): row['closure_refused'] = f['closure_refused']
        try: text = _full(store, f)
        except (OSError, ValueError, KeyError): text = None
        pointer = f"{f['chars']} characters, kept whole in blob {f.get('blob')}; ask the review for {f['id']}"
        for claim, cut in ((text, None), (f['head'], pointer), (None, pointer)):
            if claim is None and cut is None: continue
            candidate = dict(row, **({'claim': claim} if claim is not None else {}), **({'cut': cut} if cut else {}))
            size = len(canonical(candidate).encode('utf-8'))
            if used + size <= RECEIPT_BYTES or claim is None:
                rows.append(candidate); used += size; break
    return rows


def _compact(f, head=True):
    keys = ('id', 'status', 'review', 'round', 'candidate', 'chars', 'blob') + (('head',) if head else ())
    out = {k: f[k] for k in keys if f.get(k) is not None}
    out['receipt'] = (f.get('source') or {}).get('receipt')
    if f.get('closure_refused'): out['closure_refused'] = f['closure_refused']
    resolution = f.get('resolution')
    if resolution:
        out['resolution'] = {k: resolution[k] for k in ('review', 'round', 'receipt', 'kind', 'candidate', 'chars', 'blob') + (('head',) if head else ())
                             if resolution.get(k) is not None}
        out['resolution']['candidate_changed'] = resolution.get('candidate') != f.get('candidate')
    return out


def summary(state, ordinal):
    """The register as one review's record keeps it: every open finding by id and pointers, and - with their heads - the ones opened
    or closed in review `ordinal` (the record is kept for the life of the job: it must not repeat the register)."""
    rows = []
    for f in (state.get('review_register') or {}).get('findings') or []:
        mine = f['review'] == ordinal or (f.get('resolution') or {}).get('review') == ordinal
        if f['status'] == 'open' or mine: rows.append(_compact(f, head=mine))
    return rows


def handover_view(state, store=None):
    """What a handover says of the register: counts, every finding with its status, resolution and where its whole text is."""
    register = state.get('review_register') or {}
    findings = register.get('findings') or []
    return {'tracked': len(findings), 'open': sum(1 for f in findings if f['status'] == 'open'),
            'resolved': sum(1 for f in findings if f['status'] == 'resolved'),
            'findings': [_compact(f) for f in findings],
            'notes': [{k: n[k] for k in ('id', 'review', 'round', 'chars', 'blob') if k in n} for n in register.get('notes') or []],
            'text_store': 'blob store of the job state root (snapshots/blobs/<blob>); each blob is the text as the reviewer wrote it'}


def packet(runtime, state, *, worker=False, limit=None, manifest_size=100, compact=False, page=None, task_id=None):
    """compact (P5, worker under a tight prompt cap): the same rules for the worker in one short sentence.
    page (P6, completion review): characters for the requested receipts that do not fit whole, delivered as pages (None: a default
    room; 0: the caller is measuring the fixed part and no page is fetched)."""
    requested = [] if worker else list(state.get('review_requests', []))
    refs = {r['index']:r for r in state['receipts']}
    ids = known_ids(state)
    def known(i):
        if type(i) is int: return i in refs
        if not isinstance(i, dict): return False
        index = i.get('index')
        return (type(index) is int and index in refs) or (isinstance(index, str) and bool(_ID.match(index)))
    if len(requested) > 4 or any(not known(i) for i in requested):
        raise LedgerError('Invalid review evidence request.')
    as_page = {i['index'] for i in requested if isinstance(i, dict)}  # asked as a page: never also shown whole
    whole_wanted = [i for i in requested if isinstance(i, int)]
    # Keep full unique source reads/git metadata ahead of exploratory search pages.
    priority = whole_wanted + ([r['index'] for r in reversed(state['receipts'][-3:]) if r['action']!='finish'] if worker else []) + [r['index'] for r in reversed(state['receipts'])
                            if r['action'] in ('read','git_status','git_show','test','deliver','branch_before','run','create_branch','export_branch','apply','edit','write','workspace_commit')]
    manifest=[]; records={}
    for ref in state['receipts'][-manifest_size:]:
        record=json.loads(runtime.store.read_blob(ref['blob']))
        result=record['result']
        manifest.append({'index':ref['index'],'action':ref['action'],'blob':ref['blob'],
            'path':result.get('path',result.get('repository',record.get('arguments',{}).get('path'))), 'next_cursor':result.get('next_cursor'),
            'arguments':record.get('arguments') if ref['action'] in ('search','read') else None,
            **{k:result[k] for k in ('sha256','cursor','start_line','head','branch','dirty') if k in result},
            # P5 (review of the fix): in the compact worker packet an index entry, not the result: a 2,000-character review
            # rejection repeated here took the room of the latest result. The full error stays in the receipt (receipt(index)).
            # The reviewer and uncapped workers keep it whole.
            **({} if 'error' not in result else {'error':result['error']} if not (worker and compact) else
               {'error':str(result['error'])[:300]+('…[cut: receipt has the full error]' if len(str(result['error']))>300 else '')})})
        records[ref['index']]=record
    included=[]; seen=set(); seen_records=set(); used=0
    limit=limit if limit is not None else (36000 if worker else MAX_CONTENT)
    for index in dict.fromkeys(priority):
        if index in as_page: continue
        ref=refs[index]
        if ref['blob'] in seen: continue
        record=records.get(index) or json.loads(runtime.store.read_blob(ref['blob']))
        # A receipt lookup wraps an earlier record. Retain its original immutable
        # wrapper, but count equivalent content only once in the bounded packet.
        semantic=record
        while semantic.get('action')=='receipt' and isinstance(semantic.get('result'),dict) and 'action' in semantic['result']:
            semantic=semantic['result']
        identity=canonical({'action':semantic['action'],'result':semantic['result']} if semantic['action']=='read' else semantic)
        if worker and identity in seen_records: continue
        raw=canonical(record)
        if used+len(raw)>limit: continue
        included.append({'index':index,'blob':ref['blob'],'record':record})
        seen.add(ref['blob']);seen_records.add(identity);used+=len(raw)
    # Included receipts are COMPLETE. Oversized/omitted receipts are never claimed absent.
    value = {'protocol':PROTOCOL,'manifest':manifest,'manifest_omitted':max(0,len(refs)-manifest_size),
             'full_receipts':included,'requested':requested}
    if not worker:
        # P6: what was asked for and did not come whole comes as pages (paging.view), with the receipt's blob and the sha256 of each
        # whole field, so the pages can be put back together and checked. 'not_included' now means: no valid page fit.
        pages, missing = _requested_pages(runtime, state, refs, requested, seen, page, task_id)
        value['requested_pages'] = pages
        value['not_included'] = missing
    else:
        value['not_included'] = []  # a worker packet requests nothing
    if worker and compact:
        return dict(value, instructions='Worker: use included source directly, do not reread it to recover context; included receipts '
                                        'are complete; for others use receipt(index) (absence here is not '
                                        'absence from source); read next_cursor means more source exists; never invent content. Keep '
                                        'the latest review corrections in your report. Policy-withheld files are a stated limitation, '
                                        'never permission to bypass policy or invent their contents.')
    return dict(value, **{
            'instructions':('Worker: use included source and metadata directly; do not reread them just to recover context. '
                'For omitted evidence use receipt(index); absence from this packet is not absence from source. '
                'Preserve the latest review corrections in your report. Policy-withheld files are a stated limitation, '
                'not permission to bypass policy or invent their contents. '
                if worker else '') + 'Full receipts are complete tool outputs, but read next_cursor still means more source pages exist. '
                + ('' if worker else 'A receipt not shown whole: accepted=false and evidence_requests (up to 4): a manifest index, or '
                   '{index, field, offset, item_offset} copied from the next of a page you were given; requested_pages hold them page by page '
                   '(blob of the receipt, sha256 of each whole field). A page you were given is not returned again: write what you verified '
                   'in feedback (it comes back as review_notes). ')
                +
                'Do not reject a claim solely because this packet omitted evidence. Reject genuine unsupported claims, '
                'missing investigation or false completion; do not invent source.'})
