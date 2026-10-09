"""Immutable, bounded review receipts with explicit retrieval rather than hidden truncation."""
import json
from .ledger import LedgerError, canonical

PROTOCOL = 2
MAX_ROUNDS = 3
MAX_CONTENT = 45000


class ReviewRejected(LedgerError):
    pass


def packet(runtime, state, *, worker=False):
    requested = [] if worker else state.get('review_requests', [])
    refs = {r['index']:r for r in state['receipts']}
    if len(requested) > 4 or any(type(i) is not int or i not in refs for i in requested):
        raise LedgerError('Invalid review evidence request.')
    # Keep full unique source reads/git metadata ahead of exploratory search pages.
    priority = requested + ([r['index'] for r in reversed(state['receipts'][-3:]) if r['action']!='finish'] if worker else []) + [r['index'] for r in reversed(state['receipts'])
                            if r['action'] in ('read','git_status','git_show','test','deliver','branch_before')]
    manifest=[]; records={}
    for ref in state['receipts'][-100:]:
        record=json.loads(runtime.store.read_blob(ref['blob']))
        result=record['result']
        manifest.append({'index':ref['index'],'action':ref['action'],'blob':ref['blob'],
            'path':result.get('path',result.get('repository',record.get('arguments',{}).get('path'))), 'next_cursor':result.get('next_cursor'),
            'arguments':record.get('arguments') if ref['action'] in ('search','read') else None,
            **{k:result[k] for k in ('sha256','cursor','start_line','head','branch','dirty','error') if k in result}})
        records[ref['index']]=record
    included=[]; seen=set(); seen_records=set(); used=0
    limit=36000 if worker else MAX_CONTENT
    for index in dict.fromkeys(priority):
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
    return {'protocol':PROTOCOL,'manifest':manifest,'manifest_omitted':max(0,len(refs)-100),
            'full_receipts':included,'requested':requested,
            'not_included':[i for i in requested if refs[i]['blob'] not in seen],
            'instructions':('Worker: use included source and metadata directly; do not reread them just to recover context. '
                'For omitted evidence use receipt(index); absence from this packet is not absence from source. '
                'Preserve the latest review corrections in your report. Policy-withheld files are a stated limitation, '
                'not permission to bypass policy or invent their contents. '
                if worker else '') + 'Full receipts are complete tool outputs, but read next_cursor still means more source pages exist. '
                + ('' if worker else 'For omitted receipts set accepted=false and evidence_requests to up to 4 manifest indices. ')
                +
                'Do not reject a claim solely because this packet omitted evidence. Reject genuine unsupported claims, '
                'missing investigation or false completion; do not invent source. If a requested receipt cannot fit, '
                'give actionable feedback asking the worker for a smaller source page.'}


def requests(review, state):
    values=review.get('evidence_requests',[])
    valid={r['index'] for r in state['receipts']}
    if (not isinstance(values,list) or len(values)>4 or
            any(type(i) is not int or i not in valid for i in values)):
        raise LedgerError('Reviewer requested unknown evidence.')
    if values and review['accepted']: raise LedgerError('Reviewer cannot accept while requesting evidence.')
    return list(dict.fromkeys(values))
