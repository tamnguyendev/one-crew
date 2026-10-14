"""One paging contract for what the worker receives of a tool result (P4-B, Codex deep review P3).

A tool result is stored whole (its receipt; a command's full log stays on disk). What reaches the model is a PAGE of it: the same
JSON object in which only VALUES are cut (characters of a string, items of a list), never the serialized JSON, with one entry per
cut field in `page`: offset, delivered, total, eof and `next`, the exact call that returns the following part. The numbers describe
what this prompt really delivers, so a cursor or an end-of-file claim never covers text the model did not receive.

Before this, the latest result was the record's JSON text cut at a fixed length (its next_cursor said "end of file" for a page the
model saw a quarter of), a receipt lookup was cut the same way again, a `limit` argument was ignored and the middle of a long command
log could not be reached at all."""
import json

from .ledger import LedgerError, canonical

RECEIPT_KEYS = ('index', 'field', 'offset', 'item_offset')
# Results whose stored part is itself one page of something larger, continued by the tool with its own cursor.
CURSOR_TOOLS = {'read': ('text', ('path',)), 'list': ('entries', ('directory',)), 'search': ('matches', ('directory', 'query')),
                'git_log': ('commits', ('directory', 'query'))}


def _cursor_field(action, result):
    """(field the tool's next_cursor continues, argument names of that call). git_show pages its diff when a path was given,
    otherwise its list of paths."""
    if action == 'git_show':
        return ('diff' if 'diff' in result else 'paths'), ('directory', 'commit', 'path')
    return CURSOR_TOOLS.get(action, (None, ()))
LOG_FIELDS = {'stdout': '.out', 'stderr': '.err'}
SMALL = 160  # a field this size or smaller is always delivered whole


def receipt_arguments(args, receipts):
    """Validate receipt {index, field?, offset?, item_offset?}; unknown keys are refused with the contract, never ignored."""
    if not isinstance(args, dict): raise LedgerError('receipt takes {index, field, offset} and optionally item_offset.')
    unknown = sorted(set(args) - set(RECEIPT_KEYS))
    if unknown:
        raise LedgerError('receipt takes {index, field, offset} and optionally item_offset (field and offset select a page; '
                          'item_offset a part of one list item too large for a page; the page size follows the prompt budget): '
                          'unknown ' + ', '.join(unknown) + '.')
    index = args.get('index')
    if type(index) is not int or not 0 <= index < len(receipts): raise LedgerError('Unknown receipt index.')
    field, offset, item_offset = args.get('field'), args.get('offset', 0), args.get('item_offset', 0)
    if field is not None and not isinstance(field, str): raise LedgerError('receipt field must be a result field name.')
    if type(offset) is not int or offset < 0: raise LedgerError('receipt offset must be an integer >= 0.')
    if type(item_offset) is not int or item_offset < 0: raise LedgerError('receipt item_offset must be an integer >= 0.')
    if item_offset and field is None: raise LedgerError('receipt item_offset needs the field of the list.')
    return index, field, offset


def unwrap(record, arguments=None):
    """A receipt lookup wraps the record it returned (possibly another lookup): the innermost tool record, the receipt index it
    came from and the page the lookup asked for (field, offset and, for one oversized list item, item_offset)."""
    shown, field, offset, item_offset = None, None, 0, 0
    while record.get('action') == 'receipt' and isinstance(record.get('result'), dict) and 'action' in record['result']:
        args = record.get('arguments') or {}
        if shown is None:  # the outermost lookup decides which page is wanted
            field, offset, item_offset = args.get('field'), args.get('offset') or 0, args.get('item_offset') or 0
        if isinstance(args.get('index'), int): shown = args['index']
        record = record['result']
    return record, shown, field, offset, item_offset


def _size(value):
    return len(canonical(value))


def _fit_string(text, start, budget):
    """Longest text[start:start+k] whose JSON encoding fits budget (escapes make it longer than k)."""
    low, high = 0, max(0, len(text) - start)
    while low < high:
        middle = (low + high + 1) // 2
        if _size(text[start:start + middle]) <= budget: low = middle
        else: high = middle - 1
    return low


def _fit_suffix(text, budget):
    """Length of the longest tail of text whose JSON encoding fits budget."""
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if _size(text[len(text) - middle:]) <= budget: low = middle
        else: high = middle - 1
    return low


def _fit_list(items, start, budget):
    used, count = 2, 0
    for item in items[start:]:
        cost = _size(item) + 1
        if used + cost > budget: break
        used += cost; count += 1
    return count


def view(record, budget, *, index, field=None, offset=0, item_offset=0, log_text=None):
    """The page of one tool record that fits `budget` characters of JSON.
    record: {'action', 'result', 'arguments'?/'request'?}. index: the receipt the record is stored as (continuations name it).
    field/offset: the page asked for (a receipt lookup); otherwise the default page (start of everything; the END of a command
    log, where its outcome is). log_text(token, field) -> the full text of a command's stdout/stderr log, or None."""
    action = record.get('action'); result = record.get('result')
    arguments = record.get('arguments') or record.get('request')
    out = {'index': index, 'action': action}
    if arguments is not None: out['arguments'] = arguments
    if not isinstance(result, dict):
        out['result'] = result
        return out, []
    result = dict(result)
    sources = {}
    for name, suffix in LOG_FIELDS.items():  # a command's output is paged over its full retained log, not the stored excerpt
        if name in result and result.get('log') and log_text:
            full = log_text(result['log'], name)
            if full is not None and full != result[name]: sources[name] = full
    def value(name):
        return sources.get(name, result.get(name))
    large = [k for k, v in ((k, value(k)) for k in result) if isinstance(v, (str, list)) and _size(v) > SMALL]
    if field is not None and field not in result:
        raise LedgerError(f'Receipt {index} has no field {field!r}; its fields: ' + ', '.join(sorted(result)))
    if field is not None and not isinstance(value(field), (str, list)): field = None  # a scalar is always delivered whole
    if field is not None and field not in large: large.append(field)
    cursor_field, continuation_keys = _cursor_field(action, result)
    whole = dict(result, **sources)
    if field is None and _size(dict(out, result=whole)) <= budget:
        out['result'] = whole  # everything, command logs in full
        return out, []
    # Fields delivered whole cost their size; large ones share what is left, the asked-for field first.
    skeleton = {k: v for k, v in result.items() if k not in large}
    if cursor_field in large: skeleton.pop('next_cursor', None)  # replaced by the page's own next
    order = sorted(large, key=lambda k: (k != field, k not in LOG_FIELDS, -_size(value(k))))
    meta_cost = 300 * len(order) + 40
    remaining = budget - _size(dict(out, result=skeleton)) - meta_cost
    if remaining < 0: raise LedgerError('Tool result page does not fit the prompt budget.')
    shown, pages = dict(skeleton), []
    for position, name in enumerate(order):
        content = value(name)
        share = remaining if name == field or position == len(order) - 1 else max(0, remaining // (len(order) - position))
        if name == field: start = offset
        elif name in sources or (name in LOG_FIELDS and isinstance(content, str)):
            start = None  # a log: its tail first (where the outcome is), unless a page of it was asked for
        else: start = 0
        item = None
        if isinstance(content, str):
            if start is None: start = len(content) - _fit_suffix(content, share)
            start = min(start, len(content)); k = _fit_string(content, start, share)
            shown[name] = content[start:start + k]
        else:
            start = min(start or 0, len(content)); k = _fit_list(content, start, share)
            shown[name] = content[start:start + k]
            if k == 0 and start < len(content) and position == 0:
                # P4b-R2 (Codex review of P4): an item larger than the whole page used to give a page of zero items whose next
                # pointed at the same offset, forever. Now that item comes as pages of its own JSON text (page.item), so every
                # page advances and no item is skipped.
                text = canonical(content[start]); at = min(item_offset if name == field else 0, len(text))
                n = _fit_string(text, at, max(0, share - 120))
                if n == 0: raise LedgerError('Tool result page does not fit the prompt budget.')
                item = {'index': start, 'offset': at, 'delivered': n, 'total': len(text), 'unit': 'chars of the item JSON',
                        'text': text[at:at + n]}
                remaining -= _size(item)
        if k == 0 and item is None and position == 0 and start < len(content):
            raise LedgerError('Tool result page does not fit the prompt budget.')  # never a page that does not advance
        remaining -= _size(shown[name])
        total = len(content); end = start + k
        page = {'field': name, 'offset': start, 'delivered': k, 'total': total, 'unit': 'chars' if isinstance(content, str) else 'items'}
        if name in sources: page['source'] = 'full command log'
        if item is not None:
            page['item'] = item
            if item['offset'] + item['delivered'] < item['total']:
                page['next'] = {'action': 'receipt', 'arguments': {'index': index, 'field': name, 'offset': start,
                                                                   'item_offset': item['offset'] + item['delivered']}}
            else:
                end = start + 1  # that item is now complete: continue after it
        if 'next' in page: pass
        elif end < total:
            # The rest of what was STORED comes from the receipt itself: exactly the content this result had, even if the file
            # changed since (a re-read would page the current file at the old offsets).
            page['next'] = {'action': 'receipt', 'arguments': {'index': index, 'field': name, 'offset': end}}
        elif name == cursor_field and result.get('next_cursor') is not None:
            # Everything stored was delivered; the tool itself has more beyond this page (its own cursor).
            continuation = {k: v for k in continuation_keys
                            if (v := (arguments or {}).get(k, result.get(k, '' if k == 'directory' else None))) is not None}
            continuation['cursor'] = result['next_cursor']
            page['next'] = {'action': action, 'arguments': continuation}
        if start > 0:
            page['from_start'] = {'action': 'receipt', 'arguments': {'index': index, 'field': name, 'offset': 0}}
        page['eof'] = 'next' not in page
        pages.append(page)
    out['result'] = shown
    return out, pages
