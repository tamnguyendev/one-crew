"""Reviewed local probes. Never a model prompt, dispatch recipe or held-out set."""

VERSION = 1


def case(key, title, fix, tests, support, kind='runtime_contract'):
    return dict(id=key, title=title, fix=fix, before=fix+'^', tests=tests,
                support=support, kind=kind, split='known_case',
                oracle='All pinned assertions pass, no errors or skips; simulated dependencies only.')


CASES = [
    case('handoff-backlog', 'Owned outputs without legacy backlog', '920d000', [
        'tests.test_owned_handoff.OwnedHandoffTests.test_audit_and_running_checkpoints_need_no_legacy_backlog'],
        'Entry previously repaired runtime handoff; no product worker changes required.'),
    case('timeout-checkpoint', 'Resume settled timeout without resetting budget or scope', '019af9e', [
        'tests.test_workspace_timeout.WorkspaceTimeoutTests.test_checkpoint_is_idempotent_preserves_budget_scope_and_session',
        'tests.test_workspace_timeout.WorkspaceTimeoutTests.test_restart_continues_then_independent_verify_review_and_apply',
        'tests.test_workspace_timeout.WorkspaceTimeoutTests.test_no_progress_does_not_spend_another_call'],
        'Entry repaired timeout controller; provider and compiler are fixtures here.', 'workflow_fixture'),
    case('snapshot-2mb', 'Large metadata chunking while preserving source cap', '9bb8993', [
        'tests.test_runtime_evidence.EvidenceTests.test_large_utf8_roundtrip_and_original_source_cap',
        'tests.test_runtime_evidence.EvidenceTests.test_tampered_missing_or_reordered_chunks_never_read_as_valid'],
        'Entry repaired metadata transport; growing source permissions is not recovery.'),
    case('review-80k', 'Complete paged review without dropping tests or diff', 'bc57da1', [
        'tests.test_native_review_context.NativeReviewContextTests.test_large_diff_pages_are_complete_unicode_and_keep_tests',
        'tests.test_native_review_context.NativeReviewContextTests.test_tampered_evidence_is_rejected_not_overwritten'],
        'Entry repaired review input transport; passing transport does not grade reviewer judgement.'),
    case('missing-cache', 'Missing dependency blocks before compiler and retains candidate', 'aeb7d7a', [
        'tests.test_native_change.NativeChangeTests.test_missing_dependency_cache_blocks_before_compiler_and_preserves_candidate'],
        'Environment owner must supply the exact approved cache. A correct block is NOT a completed build.'),
    case('windows-once', 'One result per outcome, no silent read-as-delivery', '0e33a44', [
        'tests.test_desktop_notifications.DesktopTests.test_terminal_once_even_after_repeated_checkpoint_and_reopen',
        'tests.test_desktop_notifications.DesktopTests.test_block_resume_complete_has_two_outcomes'],
        'Window launcher is mocked; actual visible receipt and user attention remain unverified.'),
    case('parent-checkpoint', 'Parent restart reuses verified nodes; stale evidence blocks', '4e8253f', [
        'tests.test_solution_delivery.DeliveryTests.test_restart_does_not_repeat_verified_nodes',
        'tests.test_solution_delivery.DeliveryTests.test_stale_passed_receipt_cannot_finish',
        'tests.test_solution_delivery.DeliveryTests.test_crash_in_build_never_replays_blindly'],
        'Unknown side effects still require operator reconciliation.'),
    case('parent-handover', 'Parent drives child, tests, review, build, device and handover', '4e8253f', [
        'tests.test_solution_delivery.DeliveryTests.test_parent_drives_real_child_lifecycle_through_typed_fixture_handover'],
        'Provider/Flutter/ADB are fixtures; live APK/server task still needs pinned environment and acceptance.', 'workflow_fixture'),
    case('review-gate', 'Conditional review cannot complete required criteria', '4e8253f', [
        'tests.test_solution_delivery.DeliveryTests.test_review_conditional_acceptance_is_rejected',
        'tests.test_solution_delivery.DeliveryTests.test_missing_evidence_blocks_instead_of_complete'],
        'Semantic correctness of reviewer on unseen code remains unmeasured.'),
    case('apk-device-gate', 'APK identity, signer and foreground checked before E2E', '4e8253f', [
        'tests.test_delivery_android.AndroidDeliveryTests.test_different_installed_hash_blocks_e2e',
        'tests.test_delivery_android.AndroidDeliveryTests.test_overlay_window_prevents_tap_even_with_background_app_node',
        'tests.test_delivery_android.AndroidDeliveryTests.test_wrong_signer_and_oversized_or_duplicate_zip_fail_audit'],
        'Pinned device/scenario/private configuration still authored by entry; no physical device used.'),
]

LIMITS = [
    'Known historical cases, not held-out tasks or estimates of generalization.',
    'Passing a correct blocker means the safety contract passed, not product completion.',
    'Fixture results never enter product autonomy, model cost or device-success denominators.',
    'Historical mode uses different pre-fix commits; it is not a release-level before/after rate.',
    'No model calls, live server, ADB or Windows display in replay. No automatic promotion.',
]


def catalog(ids=None):
    rows = [dict(c) for c in CASES if ids is None or c['id'] in ids]
    if not rows or (ids is not None and set(ids) != {c['id'] for c in rows}):
        raise ValueError('Unknown or empty eval case selection.')
    return dict(version=VERSION, cases=rows, limits=LIMITS)
