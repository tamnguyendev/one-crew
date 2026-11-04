"""Who may review whom (core): the reviewer providers the native path can run and how independent a reviewer is from an author.
Moved here from qc_gate.py so that v2 (contract, reviewer verifier) imports no QC module; qc_gate imports these names back."""
import re

from .ledger import LedgerError

NATIVE_REVIEWERS = ('claude',)  # the native review path runs the Claude CLI only; Codex/Kiro reviewers are not adapted here
VENDORS = {'claude': 'claude', 'codex': 'codex', 'openai': 'codex', 'gpt': 'codex', 'kiro': 'kiro'}


def author_vendor(author, provider=None):
    if provider: return VENDORS.get(provider.lower())
    for token in re.split(r'[^a-z0-9]+', str(author).lower()):
        if token in VENDORS: return VENDORS[token]
    return None


def independence(author, author_provider, author_model, provider, model):
    """How independent the reviewer is from the author. Same provider AND model is refused: an author does not approve itself."""
    if provider not in NATIVE_REVIEWERS:
        raise LedgerError('The native review path runs Claude only; reviewer provider ' + str(provider) + ' is not available in MVP-1.')
    vendor = author_vendor(author, author_provider)
    base = {'author_vendor': vendor, 'author_model': author_model, 'reviewer_provider': provider, 'reviewer_model': model}
    if vendor is None:
        return dict(base, level='unknown_author_vendor', note='The author vendor is unknown, so independence cannot be shown.')
    if vendor != provider:
        return dict(base, level='cross_vendor', note='The reviewer is another vendor than the author.')
    if author_model and author_model == model:
        raise LedgerError('The reviewer would be the author (same provider and model); choose another reviewer model.')
    if not author_model:
        raise LedgerError('The author is ' + vendor + ' and the native reviewer is ' + provider + ' too: pass --author-model so a reviewer '
                          'model that differs from the author\'s can be shown. An unknown author model is not accepted as independent.')
    return dict(base, level='same_vendor_other_model',
                note='No other vendor can review on the native path in MVP-1 (Claude only); a different model of the same vendor reviews.')
