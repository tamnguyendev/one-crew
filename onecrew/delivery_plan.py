"""Sealed solution delivery plans. Workers cannot author executable recipes."""
import copy
import re
from pathlib import Path

from .ledger import LedgerError, canonical, content_hash, exact_fields
from .snapshots import scoped_path, scope_list

KINDS = {'change', 'regression', 'review', 'build', 'apk_audit', 'device', 'handover'}


def validate(value):
    p = copy.deepcopy(value)
    exact_fields(p, ('version', 'source_roots', 'acceptance', 'nodes', 'max_repairs'), 'Delivery plan')
    if p['version'] != 1 or type(p['max_repairs']) is not int or not 0 <= p['max_repairs'] <= 5:
        raise LedgerError('Delivery plan version/recovery bound invalid.')
    p['source_roots'] = scope_list(p['source_roots'])
    if not p['source_roots']: raise LedgerError('Captured source roots required.')
    if not isinstance(p['nodes'], list) or not 2 <= len(p['nodes']) <= 30:
        raise LedgerError('Delivery needs 2-30 nodes.')
    ids = set()
    for n in p['nodes']:
        exact_fields(n, ('id', 'kind', 'depends', 'config'), 'Delivery node')
        if not isinstance(n['id'], str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,49}', n['id']) or n['id'] in ids:
            raise LedgerError('Unique bounded node IDs required.')
        if n['kind'] not in KINDS or not isinstance(n['config'], dict): raise LedgerError('Unknown delivery recipe.')
        if not isinstance(n['depends'], list) or len(set(n['depends'])) != len(n['depends']) or not set(n['depends']) <= ids:
            raise LedgerError('Nodes must be topologically ordered with explicit dependencies.')
        ids.add(n['id'])
        if n['kind'] == 'change':
            exact_fields(n['config'], ('goal', 'recipe'), 'Change node')
            from .native_change import validate as native_validate
            recipe = native_validate(n['config']['recipe'])
            if recipe.get('apk_build'): raise LedgerError('Build belongs to a delivery node, not a child.')
            if not set(recipe['source_roots']) <= set(p['source_roots']): raise LedgerError('Child exceeds root source envelope.')
            n['config']['recipe'] = recipe
            if not isinstance(n['config']['goal'], str) or not 1 <= len(n['config']['goal']) <= 9000:
                raise LedgerError('Bounded child goal required.')
        elif n['kind'] == 'handover':
            if n['config']: raise LedgerError('Handover does not accept commands.')
        else:
            from .delivery_steps import validate_config
            validate_config(n['kind'], n['config'], p['source_roots'])
    if p['nodes'][-1]['kind'] != 'handover' or set(p['nodes'][-1]['depends']) != ids - {p['nodes'][-1]['id']}:
        raise LedgerError('Final handover must depend on every node.')
    if not isinstance(p['acceptance'], list) or not 1 <= len(p['acceptance']) <= 30:
        raise LedgerError('Acceptance criteria required.')
    ac = set()
    for a in p['acceptance']:
        exact_fields(a, ('id', 'text', 'nodes'), 'Acceptance criterion')
        if not isinstance(a['id'], str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,49}', a['id']) or a['id'] in ac:
            raise LedgerError('Unique acceptance IDs required.')
        if not isinstance(a['text'], str) or not 1 <= len(a['text']) <= 1200: raise LedgerError('Acceptance text required.')
        if not isinstance(a['nodes'], list) or not a['nodes'] or not set(a['nodes']) <= ids - {p['nodes'][-1]['id']}:
            raise LedgerError('Criterion must refer to executable evidence nodes.')
        ac.add(a['id'])
    reviews = [n for n in p['nodes'] if n['kind'] == 'review']
    if not reviews or not any(n['kind'] == 'regression' for n in p['nodes']):
        raise LedgerError('Aggregate regression and independent review are mandatory.')
    ancestors = {}
    changes=set()
    verification_started=False
    for n in p['nodes']:
        ancestors[n['id']] = set(n['depends']).union(*(ancestors[d] for d in n['depends']))
        if n['kind']=='change':
            if verification_started or not changes<=ancestors[n['id']]:
                raise LedgerError('Serial changes must precede final verification.')
            changes.add(n['id'])
        else:
            verification_started=True
            if not changes<=ancestors[n['id']]:raise LedgerError('Verification must depend on every source change.')
        target=n['config'].get('repair_node')
        if target and (target not in changes or target not in ancestors[n['id']]):
            raise LedgerError('Repair target must be an upstream approved change.')
        if n['kind'] == 'review' and not any(x['kind'] == 'regression' and x['id'] in ancestors[n['id']] for x in p['nodes']):
            raise LedgerError('Review requires final regression evidence.')
        if n['kind'] == 'build' and not any(r['id'] in ancestors[n['id']] for r in reviews):
            raise LedgerError('Build requires reviewed source.')
        if n['kind'] in ('apk_audit', 'device'):
            build = n['config']['build_node']
            if not any(x['id'] == build and x['kind'] == 'build' for x in p['nodes']) or build not in ancestors[n['id']]:
                raise LedgerError('Artifact node must depend on its build.')
        if n['kind'] == 'device' and not any(x['kind'] == 'apk_audit' and x['config']['build_node'] == n['config']['build_node'] and x['id'] in ancestors[n['id']] for x in p['nodes']):
            raise LedgerError('Device install requires APK audit.')
        if n['kind'] in ('apk_audit','device'):
            build=next(x for x in p['nodes'] if x['id']==n['config']['build_node'])
            if n['kind']=='apk_audit' and n['config']['signer_sha256'].lower()!=build['config']['signer_sha256'].lower():
                raise LedgerError('Audit signer must equal approved build signer.')
            if n['kind']=='device' and any(x['config']['package_id']!=n['config']['package_id'] for x in p['nodes']
                    if x['kind']=='apk_audit' and x['config']['build_node']==build['id'] and x['id'] in ancestors[n['id']]):
                raise LedgerError('Device package must equal audited package.')
    if len(canonical(p)) > 80000: raise LedgerError('Delivery plan too large.')
    return p


def revision(plan):
    return content_hash(plan)
