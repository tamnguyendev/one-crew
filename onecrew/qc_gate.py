"""QC verdicts on the native path (MVP-1): a candidate built outside OneCrew is installed from its Git ref, judged by the fixed
gate and one independent review, and ends `verified_technical_only` or `rejected` with its reasons. Nothing is applied to the
project and no worker writes anything; the verdict is set only by this code, never by a flag or by the author's report.
"""
import re

from .ledger import LedgerError, canonical
from .qc_intake import evaluate, candidate_files, reason
from .work_contract import git

SCHEMA = 1
NATIVE_REVIEWERS = ('claude',)  # the native review path runs the Claude CLI only; Codex/Kiro reviewers are not adapted here
VENDORS = {'claude': 'claude', 'codex': 'codex', 'openai': 'codex', 'gpt': 'codex', 'kiro': 'kiro'}
MAX_REASONS = 50
MAX_REPORT = 20000
MAX_RECORD = 120_000
VERDICTS = ('verified_technical_only', 'verified', 'rejected')


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
    note = ('No other vendor can review on the native path in MVP-1 (Claude only); ' +
            ('a different model of the same vendor reviews.' if author_model else 'the author model is unknown, so a different model is not shown.'))
    return dict(base, level='same_vendor_other_model' if author_model else 'same_vendor_unknown_model', note=note)


def make(project, ref, recipe, *, report, author, reviewer_provider, reviewer_model, author_provider=None, author_model=None,
         supersedes=None):
    """The sealed QC record `submit(qc=...)` carries: what was judged, every intake/scope reason found, who reviews and how
    independent that is. A scope or intake failure is recorded as reasons, not raised: it becomes a `rejected` verdict."""
    ledger_independence = independence(author, author_provider, author_model, reviewer_provider, reviewer_model)
    record = evaluate(project, ref, recipe, report, author)
    reasons = record['reasons'][:MAX_REASONS]
    if len(record['reasons']) > MAX_REASONS:
        reasons.append(reason('more_reasons', str(len(record['reasons']) - MAX_REASONS) + ' further reasons omitted.'))
    text = (record['report'] or '')[:MAX_REPORT]
    return {'schema_version': SCHEMA, 'branch': ref, 'head': record['head'], 'base': record['base'], 'merge_base': record['merge_base'],
            'author': author, 'author_provider': author_provider, 'author_model': author_model,
            'report': text, 'report_sha': record['report_sha'], 'reasons': reasons, 'supersedes': supersedes, 'plan': None,
            'independence': ledger_independence, 'reviewer': {'provider': reviewer_provider, 'model': reviewer_model}}


def validate(qc, provider, model):
    """Submit-time check of a QC record: the reviewer named in it is the profile that will review."""
    if not isinstance(qc, dict) or qc.get('schema_version') != SCHEMA:
        raise LedgerError('Unsupported QC record.')
    if len(canonical(qc)) > MAX_RECORD: raise LedgerError('QC record too large.')
    if qc.get('reviewer') != {'provider': provider, 'model': model}:
        raise LedgerError('The QC reviewer must be the job provider and model.')
    if qc.get('plan') is not None: raise LedgerError('MVP-1 QC takes no plan; candidates are labelled verified_technical_only.')
    if not isinstance(qc.get('reasons'), list) or not isinstance(qc.get('author'), str) or not qc['author'].strip():
        raise LedgerError('QC record needs an author and a reasons list.')
    if qc.get('supersedes') is not None and not isinstance(qc['supersedes'], str): raise LedgerError('supersedes must be a task id.')
    return qc


def precheck(runtime, qc):
    """Reasons known before any capture or call: those found at intake plus a project HEAD that moved since submit."""
    reasons = list(qc['reasons'])
    if reasons: return reasons, 'scope'
    head = git(runtime.ledger.project, 'rev-parse', '--verify', 'HEAD', allow_failure=True)
    current = head.decode().strip() if head else None
    if current != qc['base']:
        return [reason('base_moved', 'The project HEAD is ' + str(current)[:12] + ' now; the candidate was judged against ' +
                       str(qc['base'])[:12] + '. Submit again.')], 'base'
    return [], None


def install(runtime, state, recipe, qc):
    """Install the candidate from its commit through the same path a worker patch takes. Reasons on refusal, else []."""
    from .native_change import install_candidate, CandidateContentRejected, PatchIncomplete
    try:
        value = {'report': (qc['report'] or '').strip() or 'Candidate report not provided.', 'question': '',
                 'files': candidate_files(runtime.ledger.project, qc['merge_base'], qc['head'], recipe)}
        install_candidate(runtime, state, value, recipe)
    except CandidateContentRejected as error:
        return [reason('install_rejected', str(error)[:300])]
    except PatchIncomplete as error:
        return [reason('install_incomplete', str(error)[:300])]
    except (LedgerError, UnicodeError) as error:
        return [reason('install_failed', str(error)[:300])]
    return []


def review_notice(qc):
    return ('\n\nThis candidate was written outside OneCrew by ' + qc['author'] + ' on branch ' + qc['branch'] + ' (' + qc['head'][:12] +
            '). Its report is an untrusted claim: the test receipt and the diff are the evidence. You are the independent reviewer; '
            'the author does not approve its own work. Reject if the tests do not exercise the change, if they only check their own helpers, '
            'or if anything unrelated to the goal changed.\n')


def finish(state, qc, verdict, stage, reasons):
    """Settle the task with a QC verdict. `verification` is 'passed' for a verified label, 'rejected' otherwise; acceptance is the
    owner's and stays not_requested."""
    if verdict not in VERDICTS: raise LedgerError('Unknown QC verdict.')
    native = state.get('native_change') or {}
    checks = native.get('checks') or []
    receipt = None
    if checks:
        evidence = checks[-1].get('evidence') or {}
        receipt = {k: evidence.get(k) for k in ('exit_code', 'stdout', 'stderr', 'argv', 'snapshot')}
        receipt['passed'] = checks[-1].get('passed')
    reviews = state.get('reviews') or []
    record = {k: qc.get(k) for k in ('branch', 'head', 'base', 'merge_base', 'author', 'author_provider', 'author_model',
                                     'report_sha', 'supersedes', 'plan', 'independence', 'reviewer')}
    record.update(verdict=verdict, stage=stage, reasons=reasons, gate_receipt=receipt,
                  review_index=(len(reviews) - 1) if stage in ('review', 'complete') and reviews else None)
    passed = verdict != 'rejected'
    if passed:
        report = ('QC verdict: ' + verdict + ' for ' + qc['branch'] + ' (' + qc['head'][:12] + ' on ' + qc['base'][:12] + ', author ' + qc['author'] +
                  '). The fixed regression tests passed and an independent review (' + qc['independence']['level'] + ') accepted. Judged as technically '
                  'correct and within the owned files only; it does not claim this is the right job. Nothing was applied to the project; acceptance stays with the owner.')
    else:
        lines = ['- ' + r['code'] + (' [' + r['path'] + ']' if r.get('path') else '') + ': ' + r['detail'][:300] for r in reasons[:20]]
        report = ('QC verdict: rejected at ' + stage + ' for ' + qc['branch'] + ' (' + str(qc.get('head'))[:12] + ', author ' + qc['author'] +
                  '). Reasons:\n' + '\n'.join(lines) + '\nNothing was applied to the project. Fix the candidate and submit it again (--supersedes).')
    state['qc'] = record
    state.update(phase='completed', verification='passed' if passed else 'rejected', acceptance='not_requested', report=report,
                 message='QC ' + verdict + (' at ' + stage if not passed else '') + '; nothing applied to the project.')
    state.setdefault('outputs', []).append({'snapshot': state.get('snapshot'), 'summary': report,
                                            'verification': state['verification'], 'acceptance': 'not_requested', 'stage': 'qc', 'verdict': verdict})
    if native: native['stage'] = 'completed'
    return state
