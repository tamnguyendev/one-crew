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
REQUEST_KEYS = ('index', 'field', 'offset', 'item_offset')
# P6 (F2/F3 of the probe): what a review remembers of itself between its rounds. The reviewer is stateless, so its findings and notes
# are KEPT HERE, whole, in the checkpoint (state['review_findings'], state['review_notes']): identity, the evidence it was looking
# at, status. The prompt receives a bounded rendering of them (MEMORY_TIERS: the richest that still leaves a valid page of the
# evidence it asked for), and the core, not the model, refuses to accept while a finding is open.
MAX_FINDINGS = 12     # findings one review can hold; a reviewer that has recorded this many has decided (the rest are counted)
KEPT = 2000           # characters of one finding or note kept in the checkpoint (the reviewer's own length is recorded beside it)
MEMORY_TIERS = (900, 450, 160)   # characters of the prompt the memory may take, richest first; the last always fits (ids, heads)
FINDINGS_RULE = ('findings: defects you see (strings, "r<receipt>:" prefix optional). Close an open_findings id in resolved: '
                 '"RF<n>:<receipt shown in this review>:<why>". Accepting with one open is refused.')
_CLOSE = re.compile(r'^\s*(RF\d+)\s*:\s*(\d+)\s*:\s*(.*\S)\s*$', re.S | re.I)
_CITE = re.compile(r'^\s*r(\d+)\s*:\s*(.*\S)\s*$', re.S | re.I)


class ReviewRejected(LedgerError):
    pass


class ReviewEvidenceIncomplete(LedgerError):
    """P6: the completion reviewer asked for evidence the review could not be given within its bound (the rounds were used up, or
    the same page was asked again). It is neither an acceptance nor a rejection of the work: the job is blocked, naming what was
    missing, and the worker is not called for it."""


def _checked(item, valid):
    """One request: a receipt index, or {index, field, offset, item_offset} (the arguments of the worker's `receipt` action, copied
    from the `next` of a page). A request that names only the index is that index."""
    if type(item) is int and item in valid: return item
    if isinstance(item, dict):
        index, field = item.get('index'), item.get('field')
        offset, item_offset = item.get('offset', 0), item.get('item_offset', 0)
        if (not set(item) <= set(REQUEST_KEYS) or type(index) is not int or index not in valid
                or not (field is None or isinstance(field, str))
                or type(offset) is not int or offset < 0 or type(item_offset) is not int or item_offset < 0
                or (field is None and (offset or item_offset))):
            raise LedgerError('Reviewer requested unknown evidence.')
        if field is None: return index
        return {'index': index, 'field': field, 'offset': offset, 'item_offset': item_offset}
    raise LedgerError('Reviewer requested unknown evidence.')


def request_key(item):
    return canonical(item)


def describe(item):
    if isinstance(item, int): return f'receipt {item}'
    return f"receipt {item['index']} {item['field']} from offset {item['offset']}" + (f", item_offset {item['item_offset']}" if item['item_offset'] else '')


def requests(review, state):
    values = review.get('evidence_requests', [])
    valid = {r['index'] for r in state['receipts']}
    if not isinstance(values, list) or len(values) > 4:
        raise LedgerError('Reviewer requested unknown evidence.')
    wanted = []
    for value in values:
        item = _checked(value, valid)
        if item not in wanted: wanted.append(item)
    if wanted and review['accepted']: raise LedgerError('Reviewer cannot accept while requesting evidence.')
    return wanted


def _sha(value):
    return hashlib.sha256((value if isinstance(value, str) else canonical(value)).encode()).hexdigest()


def _requested_pages(runtime, state, refs, requested, seen, page, task_id):
    """The requested receipts that did not fit whole, as pages of the receipt through paging.view (the worker's own paging, not a
    cutter of the reviewer's). Returns (pages, not_delivered). A page that cannot be a VALID page (MIN_PAGE of the receipt's own
    content, or all that is left of it) is not delivered: the runtime is told (_page_starved) and the prompt is not sent."""
    from .paging import MIN_PAGE
    todo = []
    for r in requested:
        if isinstance(r, dict): todo.append(r)
        elif refs[r]['blob'] not in seen: todo.append({'index': r, 'field': None, 'offset': 0, 'item_offset': 0})
    if not todo or page == 0: return [], []
    whole, sizes = [], []
    for r in todo:  # what each request would deliver with all the room it wants
        try:
            if r['item_offset']:  # the worker's `receipt` action refuses this the same way (owned._tool)
                held = (runtime._receipt_source(state, refs[r['index']])[0].get('result') or {}).get(r['field'])
                if not isinstance(held, list): raise LedgerError(f"item_offset selects part of one item of a list field; {r['field']!r} is not a list.")
            value, pages = runtime._review_page(state, refs[r['index']], task_id, 10 ** 8, r['field'], r['offset'], r['item_offset'])
            whole.append((value, pages)); sizes.append(len(canonical(value)) + len(canonical(pages)) + PAGE_WRAPPER + PAGE_SLACK)
        except LedgerError as error:
            whole.append(error); sizes.append(PAGE_WRAPPER + 400)
    budget = PAGE_DEFAULT if page is None else page
    order, left, alloc = sorted(range(len(todo)), key=lambda i: sizes[i]), budget, {}
    for n, i in enumerate(order):  # the room is shared like water: small requests whole, the rest to the large ones
        alloc[i] = min(sizes[i], left // (len(order) - n)); left -= alloc[i]
    delivered, missing = [], []
    for i, r in enumerate(todo):
        ref = refs[r['index']]
        if isinstance(whole[i], LedgerError):  # a wrong request (no such field...): the reviewer is told, not starved
            delivered.append({'index': r['index'], 'blob': ref['blob'], 'request': r, 'error': str(whole[i])[:300]}); continue
        full_value, full_pages = whole[i]
        want = min(MIN_PAGE, runtime._content(dict(full_value), full_pages))
        try:
            value, pages = runtime._review_page(state, ref, task_id, max(200, alloc[i] - PAGE_WRAPPER), r['field'], r['offset'], r['item_offset'])
            content = runtime._content(dict(value), pages)
        except LedgerError as error:
            value, pages, content = None, [], -1
            runtime._starved_reason = f"receipt {r['index']}: {str(error)[:200]}"
        if content < want or value is None:
            runtime._page_starved = True
            if value is not None: runtime._starved_reason = f"receipt {r['index']}: the largest page that fits carries {content} characters of it; a valid page carries {want}"
            missing.append(r['index']); continue
        entry = dict(value, blob=ref['blob'], request=r)
        if pages: entry['page'] = pages
        else: entry['complete'] = True
        source = runtime._receipt_source(state, ref)[0].get('result') or {}
        hashes = {p['field']: _sha(source[p['field']]) for p in pages if 'source' not in p and p['field'] in source}
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
    return ' '.join(str(text).split()).casefold()


def open_findings(state):
    return [f for f in state.get('review_findings') or [] if f.get('status') == 'open']


def record_round(state, review, *, shown, round_no):
    """Put what the reviewer reported in one round into the review's memory in the checkpoint, BEFORE anything is decided from the
    answer. `shown`: the receipts that round's prompt carried (a finding is closed only by evidence the reviewer was given in this
    review). Returns {'opened': [ids], 'closed': [ids], 'refused': [why]}; a closure that is not understood or has no evidence leaves
    the finding open, with the reason on it (the next prompt shows it)."""
    findings = state.setdefault('review_findings', [])
    reached = sorted(set(state.get('review_shown') or []) | set(shown))
    state['review_shown'] = reached
    result = {'opened': [], 'closed': [], 'refused': []}
    for text in _texts(review.get('resolved')):
        match = _CLOSE.match(text)
        if not match: result['refused'].append('not understood (RF<n>:<receipt>:<why>): ' + text[:60]); continue
        ident, receipt, how = match.group(1).upper(), int(match.group(2)), match.group(3)
        target = next((f for f in findings if f['id'] == ident), None)
        if target is None or target['status'] != 'open': result['refused'].append(f'{ident} is not an open finding'); continue
        if receipt not in reached:
            target['closure_refused'] = f'receipt {receipt} was not shown in this review'
            result['refused'].append(f'{ident}: ' + target['closure_refused']); continue
        target.pop('closure_refused', None)
        target.update(status='resolved', resolution={'round': round_no, 'receipt': receipt, 'how': how[:600], 'chars': len(how)})
        result['closed'].append(ident)
    known = {_norm(f['claim']) for f in findings if f['status'] == 'open'}
    number = max([int(f['id'][2:]) for f in findings] or [0])
    pages = list(state.get('review_requests') or [])
    for text in _texts(review.get('findings')):
        cite = _CITE.match(text)
        receipt, claim = (int(cite.group(1)), cite.group(2)) if cite else (None, text.strip())
        key = _norm(claim[:KEPT])
        if key in known: continue  # the same defect reported again: one finding
        if len(findings) >= MAX_FINDINGS:
            state['review_findings_unrecorded'] = state.get('review_findings_unrecorded', 0) + 1
            continue
        number += 1; known.add(key)
        findings.append({'id': f'RF{number}', 'round': round_no, 'status': 'open', 'claim': claim[:KEPT], 'chars': len(claim),
                         'source': {'round': round_no, 'receipt': receipt, 'pages': pages}})
        result['opened'].append(f'RF{number}')
    return result


def keep_note(state, feedback, round_no):
    """A reviewer's note of an evidence round, kept whole (to KEPT characters, its own length recorded) with the pages it was written
    over. Notes are progress; what is wrong is a finding."""
    text = (feedback or '').strip()
    if not text: return
    notes = state.setdefault('review_notes', [])
    number = max([int(n['id'][1:]) for n in notes] or [0]) + 1
    notes.append({'id': f'N{number}', 'round': round_no, 'text': text[:KEPT], 'chars': len(text),
                  'pages': list(state.get('review_requests') or [])})


def memory(state, budget):
    """(open_findings, notes, closed) for the prompt within `budget` characters of JSON. An open finding is never left out: it is its
    id, then its claim as long as the room allows; notes come newest first while they fit and the ones that do not are named, never
    dropped without a word. The full text of both stays in the checkpoint."""
    opened = open_findings(state)
    notes = state.get('review_notes') or []
    closed = [f['id'] for f in state.get('review_findings') or [] if f.get('status') == 'resolved']
    def size(a, b, c):
        return len(canonical({'open_findings': a, 'review_notes': b, **({'findings_closed': c} if c else {})}))
    def entries(limit):
        out = []
        for f in opened:
            claim = f['claim'] if len(f['claim']) <= limit else f['claim'][:limit] + '…'
            entry = {'id': f['id'], 'claim': claim}
            if len(f['claim']) > limit: entry['chars'] = f['chars']
            if f.get('closure_refused'): entry['closure_refused'] = f['closure_refused']
            out.append(entry)
        return out
    share = budget if not notes else max(budget * 2 // 3, min(budget, 120))
    limit, shown = 600, entries(600)
    while opened and size(shown, [], closed) > share and limit > 16:
        limit = max(16, limit * 7 // 10); shown = entries(limit)
    if opened and size(shown, [], closed) > share: shown = [f['id'] for f in opened]  # ids: the count and names always survive
    lines, omitted, remaining = [], [], budget - size(shown, [], closed) - 70
    for note in reversed(notes):
        line = f"{note['id']} r{note['round']}: {note['text']}"
        if len(canonical(line)) <= remaining:
            lines.append(line); remaining -= len(canonical(line)) + 1
        elif remaining >= 70 and not lines:  # the newest note that does not fit whole: its head, with its length
            head = f"{note['id']} r{note['round']}: {note['text'][:remaining - 60]}…[{note['chars']} chars kept in the review state]"
            lines.append(head); remaining = 0
        else: omitted.append(note['id'])
    lines.reverse()
    if omitted: lines.insert(0, f"{len(omitted)} older note(s) kept in the review state, not shown: " + ', '.join(reversed(omitted[:6])))
    if size(shown, lines, closed) > budget: lines = lines[-1:] if lines and size(shown, lines[-1:], closed) <= budget else []
    return shown, lines, closed


def findings_text(state, limit=2200):
    """The open findings in full for whoever has to act on them (the worker after a rejection, the operator of a blocked job)."""
    opened = open_findings(state)
    if not opened: return ''
    per = max(160, limit // len(opened))
    parts = []
    for f in opened:
        cite = f['source'].get('receipt')
        claim = f['claim'] if len(f['claim']) <= per else f['claim'][:per] + f"…[{f['chars']} chars, kept in the review state]"
        parts.append(f"{f['id']} (round {f['round']}{'' if cite is None else f', receipt {cite}'}): {claim}")
    extra = state.get('review_findings_unrecorded', 0)
    return (f'{len(opened)} finding(s) recorded in this review and not closed with evidence: ' + ' | '.join(parts)
            + (f' | {extra} more finding(s) were reported than the {MAX_FINDINGS} the review can hold' if extra else ''))


def with_findings(state, feedback):
    """The reviewer's feedback with the open findings in FRONT of it (the rejection text is cut at the end, not at the findings)."""
    text = findings_text(state)
    return f'{text}\n{feedback}' if text else feedback


def packet(runtime, state, *, worker=False, limit=None, manifest_size=100, compact=False, page=None, task_id=None):
    """compact (P5, worker under a tight prompt cap): the same rules for the worker in one short sentence.
    page (P6, completion review): characters for the requested receipts that do not fit whole, delivered as pages (None: a default
    room; 0: the caller is measuring the fixed part and no page is fetched)."""
    requested = [] if worker else list(state.get('review_requests', []))
    refs = {r['index']:r for r in state['receipts']}
    if len(requested) > 4 or any(not (type(i) is int and i in refs or isinstance(i, dict) and type(i.get('index')) is int and i['index'] in refs) for i in requested):
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
