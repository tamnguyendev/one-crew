"""`onecrew plan lint --file <json> [--author <id>]`: every refusal that propose + approve would raise for the *form* of a contract, listed
at once, before anything is written (v2.1 job 11a).

Nothing here is a copy of a rule: `contract.validate` (schema, text limits), `step0.check_target` / `step0._bad_evidence` /
`step0.check_provenance` (target paths, evidence, origin and item sources) and the reviewer's `MODEL_LIKE` are the functions the
real path calls. What lint adds is only the list, the typed codes, and the argv control-character check.

It is read-only on purpose: the ledger is opened through `ReadOnlyLedger`, whose `transaction(write=True)` raises, and
`step0.evaluate(run=False)` neither runs a precondition nor stores a receipt. No ledger event and no file is written.
"""
import os
import re
import subprocess
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
              'origin_missing', 'item_without_source', 'unknown_decision', 'unknowns_missing')


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
        code = ('text_over_limit' if 'at most' in str(error) and 'characters' in str(error)
                else 'authority' if str(error).startswith('authority') else 'schema')
        return reasons + [(code, str(error))]
    verdict = step0.evaluate(ledger, 'lint', 0, content_hash(contract), contract, {}, choose=contract['options']['recommended'] if contract['options'] else None,
                             run=False, author=author)
    return reasons + [r for r in verdict['reasons'] if r[0] in FORM_CODES]


QUOTED = (re.compile(r"'([^'\n]{4,}?)'"), re.compile(r'"([^"\n]{4,}?)"'), re.compile(r'`([^`\n]{4,}?)`'))
WORD = re.compile(r'[^\W\d_]{6,}')
SHARED = 6                      # letters two words must share at the start to count as the same word (message / messages, translated / translating)


def _criteria(raw):
    """(milestone id, criterion id, question) of every reviewer criterion of the raw JSON, as far as it is shaped like a contract."""
    found = []
    for m in raw.get('milestones') if isinstance(raw, dict) and isinstance(raw.get('milestones'), list) else ():
        verifier = m.get('verifier') if isinstance(m, dict) else None
        config = verifier.get('config') if isinstance(verifier, dict) and verifier.get('type') == 'reviewer' else None
        for c in config.get('criteria') if isinstance(config, dict) and isinstance(config.get('criteria'), list) else ():
            if isinstance(c, dict) and isinstance(c.get('question'), str): found.append((m.get('id'), c.get('id'), c['question']))
    return found


def _in_base_tree(project, literal):
    """Does `git grep -F` find `literal` in HEAD of the project? False when it cannot be asked (no repository, no commit)."""
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith('GIT_')}
    try:
        done = subprocess.run(['git', '-C', str(project), 'grep', '-F', '-q', '-e', literal, 'HEAD'], capture_output=True, env=env, timeout=60,
                              creationflags=0x08000000 if os.name == 'nt' else 0)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def _no_fail_clause(raw):
    return [('criterion_no_fail_clause', f'milestone {m} criterion {c}: the question has no "fail if ..." clause, so nobody can tell what would make it fail; '
                                         'say what a fail looks like (the reviewer answers pass or fail, never "pass with remarks").')
            for m, c, question in _criteria(raw) if 'fail if' not in question.lower()]


def _warnings(ledger, raw, contract):
    """Two checks that can be wrong in both directions, so they only warn: a quoted literal the base tree already contains (the reviewer would
    fail a criterion the work cannot change), and a word a criterion shares with a non_goal (the criterion may ask for what the contract excludes)."""
    out = []
    for m, c, question in _criteria(raw):
        seen = set()
        for pattern in QUOTED:
            for literal in pattern.findall(question):
                if literal in seen: continue
                seen.add(literal)
                if _in_base_tree(ledger.project, literal):
                    out.append(('criterion_literal_present', f'milestone {m} criterion {c}: "{literal[:60]}" already appears in the base tree (HEAD); '
                                                              'a criterion that fails on it fails before any work. Ask about what the diff adds or removes.'))
        stems = {w.lower()[:SHARED] for w in WORD.findall(question)}
        for goal in contract['non_goals']:
            shared = sorted(stems & {w.lower()[:SHARED] for w in WORD.findall(goal)})
            if shared:
                out.append(('criterion_vs_non_goal', f'milestone {m} criterion {c} shares "{shared[0]}..." with the non_goal "{goal[:80]}"; '
                                                      'check the criterion does not ask for what the contract excludes.'))
    return out


def check(ledger, raw, author=None, ack_criteria=False):
    """(reasons, warnings): reasons make `plan lint` exit 1, warnings are printed and change nothing. `ack_criteria` silences the two criteria
    warnings (the author has read them); the missing "fail if" is a reason either way."""
    reasons = lint(ledger, raw, author)
    try:
        contract = contracts.validate(raw)
    except LedgerError:
        return reasons, []
    reasons = reasons + _no_fail_clause(raw)
    return reasons, ([] if ack_criteria else _warnings(ledger, raw, contract))


def render(reasons, warnings=()):
    lines = [f'[{code}] {text}' for code, text in list(reasons) + list(warnings)]
    return '\n'.join(lines) if lines else 'lint: clean'
