"""W30a - ONE decision-card schema for the owner (R01). No model is called here.

A card is what step 0 shows the owner when a choice is theirs: six fields, always the same - problem, options, recommendation,
evidence, scope and decide_by (the moment by which it must be decided). The one schema has three renderings, so there is no second
vocabulary for the same question:

  * REQ   - `to_request`: the ledger question (`Ledger.create_request`), action type `v2.decision_card`;
  * CREQ  - `to_creq`: the text/kind of a conversation question (solution_gate.question);
  * decisions - `to_decision`: an entry of the contract's `decisions` list (a decision the author took, with its cost).

Step 0 shows only the IMPORTANT choices, merged into ONE card. A technical choice that sits inside a granted authority is decided and
written as an HD-05 decision record (`decisions.record`, W03): it is never asked. A technical choice with no authority is not "inside
the authority", so it joins the card instead of being decided silently; nor is one whose authority does not resolve to the root's
APPROVED grant (decisions.resolve_grant: made up, stale, an unapproved root, or a root with no `authority` field). The subject may not
be the owner/human from an AI session (W03). The same decision never gets a second card: asking again with
the same content returns the card, with changed content revises it (one card), and a card that overlaps an existing one is refused.

Answering a card (and what the answer changes) is W30b (R03); this module only builds, validates and presents it.
"""
import hashlib
import re

from ..ledger import LedgerError, key_field, text_field

KIND = 'v2.decision_card'                       # action.type of the REQ that carries a card
CARD_FIELDS = ('problem', 'options', 'recommendation', 'evidence', 'scope', 'decide_by')
CLASSES = ('business', 'technical')
DECIDE_BY = re.compile(r'before_start|before_approve|milestone:[A-Za-z][A-Za-z0-9_-]{0,31}')
MAX_OPTIONS, MAX_EVIDENCE, MAX_PARTS = 8, 10, 5
MAX_PROBLEM = 1500
CHOICE_KEYS = {'id', 'class', 'problem', 'options', 'recommendation', 'evidence', 'scope', 'decide_by', 'authority', 'basis'}
DECISION_ID = re.compile(r'D[1-9][0-9]?')


def _options(value, name):
    if not isinstance(value, list) or not 2 <= len(value) <= MAX_OPTIONS:
        raise LedgerError(f'{name}.options: expected 2-{MAX_OPTIONS} options.')
    out = []
    for option in value:
        if not isinstance(option, dict) or set(option) != {'id', 'label'}:
            raise LedgerError(f'{name}.options: each option is {{"id", "label"}}.')
        out.append({'id': key_field(option['id']), 'label': text_field(option['label'], f'{name}.options label', 500)})
    if len({o['id'] for o in out}) != len(out):
        raise LedgerError(f'{name}.options: duplicate option id.')
    return out


def _evidence(value, name, ledger):
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_EVIDENCE:
        raise LedgerError(f'{name}.evidence: give 1-{MAX_EVIDENCE} pieces of evidence (a blob key, a URL or a file:line).')
    out = [text_field(item, f'{name}.evidence', 500).strip() for item in value]
    if ledger is not None:
        from . import step0
        for item in out:
            try:
                step0.evidence_kind(ledger, item)           # a pointer that does not resolve is not evidence
            except LedgerError as error:
                raise LedgerError(f'{name}.evidence: {error}') from error
    return out


def _decide_by(value, name):
    if not isinstance(value, str) or not DECIDE_BY.fullmatch(value):
        raise LedgerError(f'{name}.decide_by: before_start, before_approve or milestone:<id> (the moment this must be decided).')
    return value


def validate_choice(choice, ledger=None):
    """One choice step 0 found: the six card fields plus id and class (business | technical); a technical one may carry the
    authority {grant_id, revision} it rests on and its own basis."""
    if not isinstance(choice, dict) or set(choice) - CHOICE_KEYS:
        raise LedgerError('choice: unknown fields ' + ', '.join(sorted(set(choice) - CHOICE_KEYS)) if isinstance(choice, dict) else 'choice: expected an object.')
    missing = [f for f in CARD_FIELDS + ('id', 'class') if f not in choice]
    if missing:
        raise LedgerError('choice ' + str(choice.get('id', '?')) + ': missing ' + ', '.join(missing) + '.')
    cid = key_field(choice['id'])
    if '.' in cid: raise LedgerError(f'choice {cid}: the id may not contain a dot (a merged card joins the choice id and the option id with one).')
    name = 'choice ' + cid
    if choice['class'] not in CLASSES: raise LedgerError(f'{name}: class is business or technical.')
    options = _options(choice['options'], name)
    recommendation = choice['recommendation']
    if recommendation not in {o['id'] for o in options}: raise LedgerError(f'{name}.recommendation: must be one of the option ids.')
    out = {'id': cid, 'class': choice['class'], 'problem': text_field(choice['problem'], f'{name}.problem', MAX_PROBLEM), 'options': options,
           'recommendation': recommendation, 'evidence': _evidence(choice['evidence'], name, ledger),
           'scope': text_field(choice['scope'], f'{name}.scope', 300), 'decide_by': _decide_by(choice['decide_by'], name)}
    authority = choice.get('authority')
    if authority is not None:
        if not isinstance(authority, dict) or set(authority) != {'grant_id', 'revision'}:
            raise LedgerError(f'{name}.authority: {{"grant_id", "revision"}} - the grant this choice rests on.')
        out['authority'] = {k: text_field(authority[k], f'{name}.authority.{k}', 200) for k in ('grant_id', 'revision')}
    if choice.get('basis') is not None: out['basis'] = text_field(choice['basis'], f'{name}.basis', 2000)
    return out


def _earliest(moments):
    """The strictest moment of several: before_start, then before_approve, then the milestones in id order."""
    order = {'before_start': 0, 'before_approve': 1}
    return sorted(set(moments), key=lambda m: (order.get(m, 2), m))[0]


def build_card(choices):
    """ONE card from the important choices (already validated). One choice: its own fields. Several: the problem lists them, every
    option id is `<choice>.<option>`, and `recommendation` has one option per part, so a reply can still be read part by part."""
    if not choices: raise LedgerError('A card needs at least one choice.')
    if len(choices) > MAX_PARTS: raise LedgerError(f'A card merges at most {MAX_PARTS} choices; decide the less important ones inside the authority.')
    parts = [{'id': c['id']} for c in choices]
    if len(choices) == 1:
        only = choices[0]
        return {'problem': only['problem'], 'options': only['options'], 'recommendation': [only['recommendation']],
                'evidence': only['evidence'], 'scope': only['scope'], 'decide_by': only['decide_by'], 'parts': parts}
    evidence = list(dict.fromkeys(e for c in choices for e in c['evidence']))[:MAX_EVIDENCE]
    return {'problem': ' | '.join(f'[{c["id"]}] {c["problem"]}' for c in choices)[:MAX_PROBLEM],
            'options': [{'id': f'{c["id"]}.{o["id"]}', 'label': f'{c["id"]}: {o["label"]}'} for c in choices for o in c['options']],
            'recommendation': [f'{c["id"]}.{c["recommendation"]}' for c in choices], 'evidence': evidence,
            'scope': '; '.join(dict.fromkeys(c['scope'] for c in choices))[:300], 'decide_by': _earliest([c['decide_by'] for c in choices]),
            'parts': parts}


def validate_card(card, ledger=None):
    """A card in its stored form: the six fields (non-empty, evidence resolving when a ledger is given) plus `parts`."""
    if not isinstance(card, dict) or set(card) - set(CARD_FIELDS + ('parts',)):
        raise LedgerError('card: expected the fields ' + ', '.join(CARD_FIELDS) + ' (and parts).')
    missing = [f for f in CARD_FIELDS if not card.get(f)]
    if missing: raise LedgerError('card: missing ' + ', '.join(missing) + '.')
    options = _options(card['options'], 'card')
    ids = {o['id'] for o in options}
    parts = card.get('parts') or [{'id': 'D'}]
    recommendation = card['recommendation'] if isinstance(card['recommendation'], list) else [card['recommendation']]
    if len(recommendation) != len(parts) or not set(recommendation) <= ids:
        raise LedgerError('card.recommendation: one option id per part, each one of the options.')
    return {'problem': text_field(card['problem'], 'card.problem', MAX_PROBLEM), 'options': options, 'recommendation': recommendation,
            'evidence': _evidence(card['evidence'], 'card', ledger), 'scope': text_field(card['scope'], 'card.scope', 300),
            'decide_by': _decide_by(card['decide_by'], 'card'), 'parts': parts}


# ---- the three renderings ---------------------------------------------------------------------------------------------------

def to_request(card):
    """The ledger question (REQ). The ledger takes one recommendation; the card keeps the whole list in the action parameters."""
    return {'schema_version': 1, 'question': card['problem'], 'reason': 'Decision needed ' + card['decide_by'].replace('_', ' ') + '.',
            'impact': card['scope'], 'options': card['options'], 'recommendation': card['recommendation'][0],
            'action': {'type': KIND, 'parameters': {'card': card}}}


def to_creq(card):
    """The text and kind of a conversation question (CREQ): the same six fields as one block of words."""
    lines = [card['problem'], 'Options:'] + [f'  {o["id"]}: {o["label"]}' for o in card['options']]
    lines += ['Recommended: ' + ', '.join(card['recommendation']), 'Evidence: ' + '; '.join(card['evidence']),
              'Scope: ' + card['scope'], 'Decide by: ' + card['decide_by']]
    return {'kind': 'clarification', 'text': '\n'.join(lines)[:1500], 'reason': 'Decision needed ' + card['decide_by'].replace('_', ' ') + '.'}


def to_decision(card, decision_id, chosen):
    """An entry of the contract's `decisions` list for the option taken (`alternative` = the others, `cost` = the scope it touches)."""
    if not DECISION_ID.fullmatch(decision_id or ''): raise LedgerError('decision id: D1, D2, ...')
    by_id = {o['id']: o['label'] for o in card['options']}
    if chosen not in by_id: raise LedgerError('chosen: not an option of the card.')
    others = '; '.join(label for oid, label in by_id.items() if oid != chosen)
    return {'id': decision_id, 'choice': by_id[chosen][:300], 'alternative': others[:300], 'cost': ('affects ' + card['scope'])[:300]}


# ---- presenting (step 0) --------------------------------------------------------------------------------------------------------

def _card_key(ids):
    return 'card-' + hashlib.sha256('|'.join(sorted(ids)).encode()).hexdigest()[:24]


def present(ledger, name, choices, subject):
    """Decide what step 0 shows the owner. Returns {card, request, decisions, escalated}.

    Everything is validated first, so a refusal writes nothing. Technical choices inside an authority are recorded as HD-05 decisions
    (idempotent per plan and choice) and never asked; every other choice goes into the single card."""
    from . import decisions, plan as plans
    if not isinstance(choices, list) or not choices: raise LedgerError('choices: expected a non-empty list.')
    parsed = [validate_choice(c, ledger) for c in choices]
    if len({c['id'] for c in parsed}) != len(parsed): raise LedgerError('choices: duplicate id.')
    subject = decisions._subject(subject)
    if decisions.owner_subject(subject):                          # W03: refused before the card or any decision is written
        from .ownership import refuse_in_ai_session
        refuse_in_ai_session('presenting decisions with the owner/human as their subject')
    with ledger.transaction() as conn:
        state = plans.anchor_events(ledger, conn, name)
    task_id = state['task_id']
    # W30a: a technical choice is decided silently only when its authority IS the root's approved grant and that root declares an
    # `authority` field (a root without one delegates nothing); any other grant - made up, stale, of an unapproved root - goes on the card.
    def inside(choice):
        if choice['class'] != 'technical' or not choice.get('authority'): return False
        resolved, _, contract = decisions.resolve_grant(ledger, task_id, choice['authority'])
        return resolved is True and bool((contract or {}).get('authority'))
    decided = [c for c in parsed if inside(c)]
    important = [c for c in parsed if c not in decided]
    escalated = [c['id'] for c in important if c['class'] == 'technical']
    card = request_key = existing = None
    if important:
        card = validate_card(build_card(important), ledger)
        ids = {p['id'] for p in card['parts']}
        request_key = _card_key(ids)
        for view in ledger.requests(task_id):
            action = view['question'].get('action', {})
            if action.get('type') != KIND: continue
            have = {p['id'] for p in action['parameters']['card']['parts']}
            if have == ids: existing = view
            elif have & ids:
                raise LedgerError(f'choice {", ".join(sorted(have & ids))} already has a decision card ({view["id"]}); a decision gets one card - '
                                  f'revise that card with the same choices instead of asking again.')
        if existing and existing['state'] != 'pending':
            raise LedgerError(f'The decision card {existing["id"]} was already answered; a changed decision is a change request, not a new card.')
    recorded = []
    for choice in decided:
        others = [o['label'] for o in choice['options'] if o['id'] != choice['recommendation']]
        basis = choice.get('basis') or f'Technical choice {choice["id"]} inside the granted authority: {choice["problem"]} Chose {choice["recommendation"]} over {"; ".join(others)}.'
        decisions.record(ledger, task_id, subject=subject, authority=choice['authority'], evidence=[{'ref': e} for e in choice['evidence']],
                         basis=basis, scope=choice['scope'], key=f'{name}:{choice["id"]}')
        recorded.append({'choice': choice['id'], 'chosen': choice['recommendation'], 'recorded': True})
    request = None
    if card:
        question = to_request(card)
        if existing is None:
            view = ledger.create_request(task_id, request_key, question)
        elif existing['question'] == question:
            view = existing
        else:
            view = ledger.revise_request(existing['id'], existing['revision'], question)
        request = {'id': view['id'], 'revision': view['revision'], 'state': view['state']}
    return {'card': card, 'request': request, 'decisions': recorded, 'escalated': escalated}
