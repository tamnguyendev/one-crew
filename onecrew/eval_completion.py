"""Full-loop completion: every loop stage of the project kind ran, passed and verified the final source.

Read-only over a recorded checkpoint. Exports stage statuses and booleans only, never receipts or report text."""
import hashlib
from pathlib import Path
import re

COMPLETION_LEVELS = ('full_loop', 'plan_complete', 'partial', 'tests_only', 'blocked', 'incomplete', 'unknown')
LOOP = {'node_extension': ('change', 'regression', 'review', 'build', 'e2e_mock', 'e2e_live', 'commit', 'handover', 'notice'),
        'flutter_android': ('change', 'regression', 'review', 'build', 'apk_audit', 'device', 'handover', 'notice')}
# Plan node kind -> loop stage. 'version' edits the manifest; it is not a loop stage.
STAGES = {'change': 'change', 'regression': 'regression', 'node_regression': 'regression', 'review': 'review',
          'build': 'build', 'node_build': 'build', 'node_build_live': 'build', 'apk_audit': 'apk_audit', 'device': 'device',
          'e2e_mock': 'e2e_mock', 'e2e_live': 'e2e_live', 'commit': 'commit', 'handover': 'handover'}
# A run that passed none of these only proved its tests.
BEYOND_TESTS = {'build', 'apk_audit', 'device', 'e2e_mock', 'e2e_live'}
SHA = re.compile(r'[0-9a-f]{40,64}\Z')


def kind_of(plan):
    kind = plan.get('kind')
    if isinstance(kind, str):
        return kind if kind in LOOP else 'unknown'
    return 'flutter_android' if plan.get('version', 1) == 1 else 'unknown'


def node_status(stage, row, receipt, final):
    if receipt.get('skipped') is True:
        return 'skipped'
    if row.get('phase') != 'passed' or receipt.get('passed') is not True:
        return 'not_passed'
    # A change produces the source; every other stage must have run on the final one.
    return 'passed' if stage == 'change' or (final and receipt.get('source') == final) else 'stale'


def combined(values):
    for status in ('skipped', 'not_passed', 'stale'):
        if status in values:
            return status
    return 'passed'


def commit_verified(receipt):
    """The commit node's own verification: ref checked against the commit, and nothing pushed."""
    commits = receipt.get('commits') if isinstance(receipt.get('commits'), list) else [receipt.get('commit')]
    return (receipt.get('verified') is True and receipt.get('pushed') is False and bool(commits)
            and all(isinstance(c, str) and SHA.fullmatch(c) for c in commits))


def report_present(receipt):
    path, digest = receipt.get('report'), receipt.get('sha256')
    if not isinstance(path, str) or not isinstance(digest, str):
        return False
    try:
        with open(Path(path), 'rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest() == digest
    except OSError:
        return False


def evidence(state, windows=None):
    """Loop evidence of one delivery checkpoint; None for a task that is not a delivery."""
    plan, delivery = state.get('plan'), state.get('delivery')
    if not isinstance(plan, dict) or not isinstance(delivery, dict) or not delivery:
        return None
    final = (delivery.get('source') or {}).get('hash') if isinstance(delivery.get('source'), dict) else None
    rows = delivery.get('nodes') if isinstance(delivery.get('nodes'), dict) else {}
    stages, commit, report = {}, None, None
    for node in plan.get('nodes') or []:
        stage = STAGES.get(node.get('kind')) if isinstance(node, dict) else None
        if not stage:
            continue
        row = rows.get(node.get('id')) if isinstance(rows.get(node.get('id')), dict) else {}
        receipt = row.get('receipt') if isinstance(row.get('receipt'), dict) else {}
        stages.setdefault(stage, []).append(node_status(stage, row, receipt, final))
        if stage == 'commit':
            commit = (commit is not False) and commit_verified(receipt)
        if stage == 'handover':
            report = (report is not False) and report_present(receipt)
    notice = isinstance(windows, dict) and windows.get('episode') == 'outcome' and windows.get('status') in ('shown', 'closed')
    return {'kind': kind_of(plan), 'stages': {k: combined(v) for k, v in stages.items()},
            'commit_verified': commit, 'handover_report': report, 'notice_shown': notice}


def fallback(delivery):
    """An observation without loop evidence (older shape): stage presence only, never a full loop."""
    nodes = (delivery or {}).get('nodes') or {}
    stages = {}
    for row in nodes.values():
        stage = STAGES.get(row.get('kind'))
        if stage:
            stages.setdefault(stage, []).append('skipped' if row.get('skipped') else 'passed' if row.get('phase') == 'passed' else 'not_passed')
    return {'kind': 'unknown', 'stages': {k: combined(v) for k, v in stages.items()}, 'commit_verified': None,
            'handover_report': None, 'notice_shown': False}


def completed_level(t, gaps):
    """Level of a completed phase whose partial-work gaps are already known."""
    loop, d = t.get('loop'), t.get('delivery')
    if not isinstance(d, dict):
        # A standalone job (native_change included) proves its tests at most.
        return ('partial', gaps) if gaps else ('tests_only', ['not_a_delivery_loop'])
    stages = (loop or fallback(d))['stages']
    gaps = gaps + sorted(stage + '_not_run' for stage, status in stages.items() if status == 'skipped')
    if gaps:
        return 'partial', gaps
    if not any(stages.get(stage) == 'passed' for stage in BEYOND_TESTS):
        return 'tests_only', ['no_build_or_e2e']
    loop = loop or dict(fallback(d), missing_evidence=True)
    kind, missing = loop['kind'], ['loop_evidence_missing'] if loop.get('missing_evidence') else []
    for stage in LOOP.get(kind, ()):
        status = loop['notice_shown'] if stage == 'notice' else stages.get(stage)
        if stage == 'notice':
            if not status: missing.append('notice_not_shown')
        elif status is None:
            missing.append('commit_missing' if stage == 'commit' else 'loop_stage_missing:' + stage)
        elif status != 'passed':
            missing.append('loop_stage_' + status + ':' + stage)
    if kind not in LOOP:
        missing.append('loop_kind_unknown')
    # Any commit in the plan must be verified and unpushed, whether or not the kind requires one.
    if stages.get('commit') == 'passed' and loop['commit_verified'] is not True:
        missing.append('commit_unverified')
    if stages.get('handover') == 'passed' and loop['handover_report'] is not True:
        missing.append('handover_report_missing')
    return ('plan_complete', missing) if missing else ('full_loop', [])
