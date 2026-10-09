"""Observed usage only: deduplicate receipts and never add cached input twice."""
import math

from .ledger import content_hash


def record(state, attempt, reported, provider, model):
    value = {'attempt': attempt, 'reported': reported, 'provider': provider, 'model': model}
    previous = next((r for r in state['usage'] if r['attempt'] == attempt), None)
    if previous is None:
        state['usage'].append(value)
    elif previous['reported'] != reported:
        # Preserve conflicting evidence, but do not sum or silently select a winner.
        previous['usage_conflict'] = True
    else:
        previous.setdefault('provider', provider)
        previous.setdefault('model', model)


def _count(value):
    return type(value) is int and value >= 0


def summarize(records, attempt_rows=()):
    attempts, conflicts = {}, set()
    for row in records:
        key = row['attempt']
        if key in attempts and content_hash(attempts[key]) != content_hash(row):
            conflicts.add(key)
        attempts[key] = row
    for row in attempt_rows:
        if row.get('charged') or row['status'] == 'unknown':
            attempts.setdefault(row['id'], {'attempt': row['id'], 'reported': None})
    totals = {'input_tokens': 0, 'cached_input_tokens': 0, 'uncached_input_tokens': 0,
              'output_tokens': 0, 'total_tokens': 0, 'kiro_credits': 0.0}
    unknown, measured = [], []
    for key, row in attempts.items():
        provider = row.get('provider')
        reports = row.get('reported')
        if key in conflicts or row.get('usage_conflict') or not isinstance(reports, list):
            unknown.append(key)
            continue
        # Identical counters do not identify an event: two separate turns can
        # legitimately consume the same token count. Only the outer attempt
        # receipt has a verified dedup identity in these adapters today.
        if provider == 'codex' and len(reports) == 1 and isinstance(reports[0],dict):
            value = reports[0]
            inp, cached, out = (value.get(k) for k in ('input_tokens','cached_input_tokens','output_tokens'))
            if all(_count(v) for v in (inp,cached,out)) and cached <= inp:
                totals['input_tokens'] += inp
                totals['cached_input_tokens'] += cached
                totals['uncached_input_tokens'] += inp-cached
                totals['output_tokens'] += out
                totals['total_tokens'] += inp+out
                measured.append(key)
                continue
        if provider == 'kiro':
            metering = [r['metering'] for r in reports if isinstance(r,dict) and 'metering' in r]
            if len(metering) == 1:
                items = metering[0]
                if (isinstance(items, list) and len(items) == 1 and isinstance(items[0], dict)
                        and items[0].get('unit') == 'credit' and type(items[0].get('value')) in (int,float)
                        and math.isfinite(items[0]['value']) and items[0]['value'] >= 0):
                    totals['kiro_credits'] += items[0]['value']
                    measured.append(key)
                    continue
        # Legacy records without provenance, missing/ambiguous cumulative counters,
        # and unverified provider formats remain unknown rather than free.
        unknown.append(key)
    return {'totals_observed_only': totals, 'measured_attempts': measured, 'unknown_attempts': unknown,
            'attempts': len(attempts), 'cost_usd': None,
            'note': 'Cached input is a subset of Codex input; credits, tokens and account percentages are separate units. Ambiguous cumulative reports require a verified event/session contract.'}
