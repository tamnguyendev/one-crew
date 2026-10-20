"""`onecrew plan lint --file <json> [--author <id>]`: every refusal that propose + approve would raise for the *form* of a contract, listed
at once, before anything is written (v2.1 job 11a).

Nothing here is a copy of a rule: `contract.validate` (schema, text limits), `step0.check_target` / `step0._bad_evidence` /
`step0.check_provenance` (target paths, evidence, origin and item sources) and the reviewer's `MODEL_LIKE` are the functions the
real path calls. What lint adds is only the list, the typed codes, and the argv control-character check.

It is read-only on purpose: the ledger is opened through `ReadOnlyLedger`, whose `transaction(write=True)` raises, and
`step0.evaluate(run=False)` neither runs a precondition nor stores a receipt. No ledger event and no file is written.
"""
from contextlib import contextmanager

from ..ledger import Ledger, LedgerError, content_hash, text_field
from . import contract as contracts, step0
from .plan import refuse_owner_author
from .ownership import OWNER_ACTORS
from .verifiers import command
from .verifiers.reviewer import MODEL_LIKE

# The reasons of evaluate() that are about the form of the contract. The rest (unknowns open, options not chosen, advice, preconditions)
# belong to the approval itself and say nothing about a typo, so lint leaves them to approve.
FORM_CODES = ('target_repo', 'target_ref', 'target_path', 'assumption_no_evidence', 'assumption_evidence_invalid', 'option_evidence_invalid',
              'origin_missing', 'item_without_source', 'unknown_decision')


class ReadOnlyLedger(Ledger):
    """The ledger of a lint run: reads work, a write is an error (not a convention)."""

    @contextmanager
    def transaction(self, write=False):
        if write: raise LedgerError('plan lint is read-only: it never writes the ledger.')
        with super().transaction() as conn:
            yield conn


def _argv_lists(raw):
    """(where, argv) for every command verifier and every command precondition of the raw JSON, as far as it is shaped like a contract."""
    found = []
    if not isinstance(raw, dict): return found
    for m in raw.get('milestones') if isinstance(raw.get('milestones'), list) else ():
        verifier = m.get('verifier') if isinstance(m, dict) else None
        config = verifier.get('config') if isinstance(verifier, dict) and verifier.get('type') == 'command' else None
        if isinstance(config, dict) and isinstance(config.get('argv'), list): found.append((f'milestone {m.get("id")}', config['argv']))
    for p in raw.get('preconditions') if isinstance(raw.get('preconditions'), list) else ():
        args = p.get('args') if isinstance(p, dict) else None
        if isinstance(args, dict) and isinstance(args.get('argv'), list): found.append((f'precondition {p.get("id")}', args['argv']))
    return found


def _control_chars(raw):
    reasons = []
    for where, argv in _argv_lists(raw):
        for number, element in enumerate(argv):
            if isinstance(element, str) and command.CONTROL.search(element):
                reasons.append(('argv_control_char', f'{where}: argv[{number}] contains a control character ({element[:40]!r}); '
                                                     'the command would not run as written.'))
    return reasons


def _author(author):
    if author is None: return []
    try:
        text_field(author, 'author', 100)
        refuse_owner_author(author)
    except LedgerError as error:
        return [('author_invalid', str(error))]
    if author not in OWNER_ACTORS and not MODEL_LIKE.fullmatch(author):
        return [('author_not_model_id', f'author "{author}" is not a model id (like claude-sonnet-5-5), so a reviewer cannot tell whether it is independent.')]
    return []


def lint(ledger, raw, author=None):
    """[(code, text)] in the order a reader fixes them; empty when the contract would pass the form checks of propose and approve."""
    reasons = _author(author) + _control_chars(raw)
    try:
        contract = contracts.validate(raw)
    except LedgerError as error:
        code = 'text_over_limit' if 'at most' in str(error) and 'characters' in str(error) else 'schema'
        return reasons + [(code, str(error))]
    verdict = step0.evaluate(ledger, 'lint', 0, content_hash(contract), contract, {}, choose=contract['options']['recommended'] if contract['options'] else None,
                             run=False, author=author)
    return reasons + [r for r in verdict['reasons'] if r[0] in FORM_CODES]


def render(reasons):
    return '\n'.join(f'[{code}] {text}' for code, text in reasons) if reasons else 'lint: clean'
