"""Reviewed local probes. Never a model prompt, dispatch recipe or held-out set."""

VERSION = 2


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
    # TASK-5f472cdf (2026-10-12, Samsung SM-A546E Android 16): real blockers of a live known-case run.
    case('delivery-longpath', 'Short delivery workspace; deep Windows paths fail before capture', '7a095ae', [
        'tests.test_delivery_recovery.RecoveryTests.test_short_home_and_capture_deep_source',
        'tests.test_delivery_recovery.RecoveryTests.test_deep_destination_fails_before_creating_partial_capture'],
        'Windows-only assertions; the live baseline capture still needs a pinned resume to prove.'),
    case('nested-plugin-rebase', 'Nested path dependencies build from the capture, never the original', '7a095ae', [
        'tests.test_delivery_recovery.RecoveryTests.test_nested_dependency_rebased_in_all_build_inputs_and_red'],
        'Entry had relocated pdfrx outside source roots during the live run; this fixture does not run Gradle/CMake.'),
    case('observe-null-source', 'Observation of a task blocked before source capture', '7a095ae', [
        'tests.test_delivery_recovery.RecoveryTests.test_blocked_before_source_capture_remains_unverified'],
        'Pre-capture blocks stay unverified; nothing is inferred from them.'),
    case('android16-focus', 'Foreground focus read per top display on Android 16', '7a095ae', [
        'tests.test_delivery_recovery.RecoveryTests.test_android16_focus_is_read_from_top_display',
        'tests.test_delivery_recovery.DeviceRecoveryTests.test_tap_allowed_when_android16_focus_is_the_app'],
        'Fixture copied from one Samsung Android 16 dump; other vendors and versions are unverified.'),
    case('ime-scroll', 'Scroll above the keyboard; refuse unsafe gestures without input', '7a095ae', [
        'tests.test_delivery_recovery.RecoveryTests.test_scroll_avoids_ime_and_rejects_unknown_or_ambiguous_surface',
        'tests.test_delivery_recovery.RecoveryTests.test_keyboard_edge_ignores_stale_flags_and_full_screen_ime_window',
        'tests.test_delivery_recovery.DeviceRecoveryTests.test_scroll_without_safe_surface_rereads_ui_without_input'],
        'The visible-keyboard InsetsSource line is inferred from the hidden-state dump; not yet observed live.'),
    case('bounded-wait', 'Read-only bounded UI wait; ADB failure stays fatal', '7a095ae', [
        'tests.test_delivery_recovery.DeviceRecoveryTests.test_wait_for_polls_without_input_and_records_receipt',
        'tests.test_delivery_recovery.DeviceRecoveryTests.test_wait_timeout_does_not_swipe_or_repeat_install',
        'tests.test_delivery_recovery.DeviceRecoveryTests.test_wait_validation_rejects_unbounded_duration',
        'tests.test_delivery_recovery.DeviceRecoveryTests.test_wait_for_adb_failure_is_not_retried_as_missing_ui'],
        'Scenario authors must still choose correct selectors and timeouts.'),
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
