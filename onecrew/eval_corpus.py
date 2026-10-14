"""Reviewed local probes. Never a model prompt, dispatch recipe or held-out set."""

VERSION = 3


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
    case('parent-checkpoint', 'Parent restart reuses verified nodes', '4e8253f', [
        # v3: the 'never replay' and 'stale evidence blocks' oracles changed with the autopilot; see the autopilot cases.
        'tests.test_solution_delivery.DeliveryTests.test_restart_does_not_repeat_verified_nodes'],
        'Unknown side effects still require operator reconciliation.'),
    case('parent-handover', 'Parent drives child, tests, review, build, device and handover', '4e8253f', [
        'tests.test_solution_delivery.DeliveryTests.test_parent_drives_real_child_lifecycle_through_typed_fixture_handover'],
        'Provider/Flutter/ADB are fixtures; live APK/server task still needs pinned environment and acceptance.', 'workflow_fixture'),
    case('review-gate', 'Conditional review cannot complete required criteria', '4e8253f', [
        # v3: missing evidence now asks one typed question instead of 'blocked'; see the autopilot cases.
        'tests.test_solution_delivery.DeliveryTests.test_review_conditional_acceptance_is_rejected'],
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
    # Codex review findings P1/P2 on 356fb82: red by behaviour there, not by a missing API.
    case('ime-occluded-target', 'Target under a visible keyboard is scrolled clear or refused, never tapped through', 'cfc77a2', [
        'tests.test_delivery_review_regressions.KeyboardCoverTests.test_target_under_keyboard_is_scrolled_clear_before_tap',
        'tests.test_delivery_review_regressions.KeyboardCoverTests.test_target_that_stays_under_keyboard_fails_without_any_tap',
        'tests.test_delivery_review_regressions.KeyboardCoverTests.test_direct_tap_on_covered_target_is_refused',
        'tests.test_delivery_review_regressions.KeyboardCoverTests.test_unknown_keyboard_bounds_refuse_tap',
        'tests.test_delivery_review_regressions.KeyboardCoverTests.test_hidden_keyboard_keeps_full_screen_reachable'],
        'The visible-keyboard InsetsSource line is inferred from a hidden-state Samsung Android 16 dump; not observed live.'),
    case('pubspec-path-scope', 'Only local path dependencies are rebased; hosted, git and asset paths untouched', 'cfc77a2', [
        'tests.test_delivery_review_regressions.PubspecRebaseTests.test_only_local_path_sources_move_through_capture_and_red',
        'tests.test_delivery_review_regressions.PubspecRebaseTests.test_text_outside_dependency_sections_is_untouched'],
        'Line-structured YAML subset; flow mappings in dependency sections fail closed.'),
    # Delivery autopilot (docs/delivery-autopilot.vi.md). Old-API probes fail on 356fb82 by behaviour; probes in
    # modules importing new autopilot modules report capability_unavailable there (capability, not a reproduced bug).
    case('autopilot-transient-retry', 'Transient node failure retries within the grant, silently, instead of blocking', '8207d61', [
        'tests.test_autopilot_behaviour.CoordinatorBehaviourTests.test_transient_node_failure_is_retried_not_blocked',
        'tests.test_autopilot_behaviour.CoordinatorBehaviourTests.test_automatic_recovery_opens_no_window'],
        'Backoff is fast-forwarded in the fixture; wall-clock waits and real ADB transports are not exercised.'),
    case('autopilot-ask-once', 'Unrecoverable failure asks one typed question; the answer continues without an entry resume', '8207d61', [
        'tests.test_autopilot_behaviour.CoordinatorBehaviourTests.test_unrecoverable_failure_asks_one_typed_question',
        'tests.test_autopilot_behaviour.CoordinatorBehaviourTests.test_answer_continues_without_entry_resume',
        'tests.test_solution_delivery.DeliveryTests.test_stale_passed_receipt_cannot_finish',
        'tests.test_solution_delivery.DeliveryTests.test_missing_evidence_blocks_instead_of_complete',
        'tests.test_solution_delivery.DeliveryTests.test_source_drift_is_not_silently_accepted',
        'tests.test_solution_delivery.DeliveryTests.test_missing_dependency_blocks_preflight_without_worker'],
        'Answers go through the ledger API; the Windows window launch is mocked and user attention is unverified.'),
    case('crash-replay-once', 'A killed coordinator resumes from its checkpoint; interrupted capture work replays once', '8207d61', [
        'tests.test_solution_delivery.DeliveryTests.test_crash_in_build_replays_once_then_asks',
        'tests.test_delivery_restart.CoordinatorRestartTests.test_kill_mid_node_then_restart_continues_from_checkpoint'],
        'Real TerminateProcess of a coordinator process with fixture native nodes; device effects are covered by reconcile cases.',
        'workflow_fixture'),
    case('escalation-episodes', 'Each decision episode is one single-use request; cancel, pause and capacity waits are not failures', '8207d61', [
        'tests.test_delivery_review_findings.EscalationEpisodeTests.test_answered_request_is_never_reused_for_the_next_episode',
        'tests.test_delivery_review_findings.EscalationEpisodeTests.test_changed_question_text_after_retry_never_crashes_run',
        'tests.test_delivery_review_findings.EscalationEpisodeTests.test_user_cancel_during_a_node_asks_nothing',
        'tests.test_delivery_review_findings.EscalationEpisodeTests.test_pause_during_a_node_is_not_a_failure',
        'tests.test_delivery_review_findings.EscalationEpisodeTests.test_capacity_wait_is_not_an_interruption',
        'tests.test_delivery_review_findings.EscalationEpisodeTests.test_resume_accepts_an_uncertain_row_for_reconcile',
        'tests.test_delivery_review_findings.EscalationEpisodeTests.test_unsettled_attempt_keeps_the_row_running_until_it_settles'],
        'Adversarial review findings of the autopilot core (2026-10-12) before its first commit; no earlier runtime had them.'),
    case('child-question-continuation', 'A child stopped only by an answered question or by the root fence continues', '8207d61', [
        'tests.test_delivery_review_findings.ChildQuestionTests.test_child_waiting_on_an_answered_solution_question_is_continued',
        'tests.test_delivery_review_findings.ChildQuestionTests.test_child_fenced_by_the_root_is_resumed_not_regenerated',
        'tests.test_delivery_review_findings.ChildQuestionTests.test_regeneration_retires_the_superseded_child_so_intake_accepts_the_new_one'],
        'Child worker is the fixture worker; CREQ answers are represented by the child checkpoint state.'),
    case('device-effect-safety', 'Device scenarios replay only when proven safe; an optional stage that ran and failed is a finding', '8207d61', [
        'tests.test_delivery_review_findings.DeviceEffectTests.test_failure_after_scenario_steps_is_never_a_free_retry',
        'tests.test_delivery_review_findings.OptionalFailureTests.test_optional_device_that_ran_and_failed_is_a_finding_not_not_run',
        'tests.test_delivery_autopilot.RecoveryTests.test_device_interruption_reconciles_read_only',
        'tests.test_delivery_autopilot.OptionalDeviceTests.test_unavailable_optional_device_is_reported_not_run'],
        'ADB is a fixture; the read-only reconcile probe was not run against a physical device.'),
    case('goal-level-planning', 'Goal + approved envelope -> OneCrew plan sealed only inside the envelope', '8207d61', [
        'tests.test_delivery_autopilot.EnvelopeTests.test_envelope_validated_and_bound_to_approved_text',
        'tests.test_delivery_autopilot.EnvelopeTests.test_entry_plan_and_budget_must_fit_the_approved_envelope',
        'tests.test_delivery_autopilot.EnvelopeTests.test_covers_reports_widening',
        'tests.test_delivery_autopilot.EnvelopeTests.test_planner_output_is_checked_by_code',
        'tests.test_delivery_autopilot.PlanningTests.test_goal_level_submit_plans_inside_envelope_and_seals',
        'tests.test_delivery_autopilot.PlanningTests.test_invalid_plan_gets_bounded_same_session_corrections_then_one_question',
        'tests.test_delivery_autopilot.PlanningTests.test_out_of_envelope_need_asks_once_and_retry_replans_inside',
        'tests.test_delivery_review_findings.PlannerFindingTests.test_private_reference_inside_source_roots_stops_before_capture',
        'tests.test_delivery_review_findings.PlannerFindingTests.test_nested_package_is_an_environment_question_before_any_model_call',
        'tests.test_delivery_review_findings.PlannerFindingTests.test_malformed_scenario_from_the_model_is_feedback_not_a_crash',
        'tests.test_delivery_review_findings.PlannerFindingTests.test_out_of_envelope_question_names_the_need_and_a_new_need_asks_again',
        'tests.test_delivery_review_findings.PlannerFindingTests.test_failed_planning_call_is_dropped_on_retry_and_called_again',
        'tests.test_delivery_review_findings.CoversTests.test_execution_features_and_required_device_are_envelope_bound',
        'tests.test_delivery_review_findings.CoversTests.test_effective_application_id_and_launcher_class'],
        'The model proposal is a fixture; plan quality on unseen goals is measured only by live trials, not here.'),
    case('recovery-policy', 'Classified failures, bounded retries, no repeat without progress, one window per decision', '8207d61', [
        'tests.test_delivery_autopilot.RecoveryTests.test_transient_failure_retries_with_backoff_then_asks_once',
        'tests.test_delivery_autopilot.RecoveryTests.test_failure_history_survives_coordinator_restart',
        'tests.test_delivery_autopilot.RecoveryTests.test_answer_retry_continues_without_entry_resume_and_stop_cancels',
        'tests.test_delivery_autopilot.RecoveryTests.test_repeated_product_failure_without_progress_stops_repairing',
        'tests.test_delivery_autopilot.RecoveryTests.test_review_killed_during_model_call_drops_only_a_settled_attempt',
        'tests.test_delivery_autopilot.RecoveryTests.test_classification_prefers_structured_fields',
        'tests.test_delivery_autopilot.NotificationTests.test_automatic_recovery_is_silent_and_escalation_shows_once'],
        'Classification tables are code; misclassification of unseen messages falls back to one question.'),
    case('coordinator-keeper', 'A dead delivery coordinator is restarted with bounded backoff and attributed', '8207d61', [
        'tests.test_keeper.ScanTests.test_scan_restarts_only_eligible_dead_roots',
        'tests.test_keeper.ScanTests.test_unknown_probe_is_never_restarted',
        'tests.test_keeper.ScanTests.test_backoff_and_hourly_bound_persist_and_exhaust_once',
        'tests.test_keeper.RunnerRecordTests.test_runner_started_includes_runtime_and_initiator'],
        'Process spawning is mocked here; the live trial records the real keeper restart separately.'),
    case('intervention-recording', 'Entry mutations and runtime changes are recorded automatically', '8207d61', [
        'tests.test_interventions.RecordTests.test_record_payload_is_evidence_without_task_mutation',
        'tests.test_interventions.RecordTests.test_summary_orders_interventions_assistance_and_runtime_changes',
        'tests.test_interventions.EntryRecordingTests.test_cli_reply_records_once_and_standalone_task_has_no_continuation',
        'tests.test_interventions.EntryRecordingTests.test_mcp_mutations_record_source_actor'],
        'Actor identity is local attribution (ONECREW_ACTOR/MCP source), not authentication.'),
    # Found by the first live autonomy trial (2026-10-12, TASK-fd13e281): runtime defects, not product failures.
    case('flutter-reporter-red', 'Widget-test assertion text reaches red matching and repair feedback', '8207d61', [
        'tests.test_delivery_review_regressions.FlutterJsonReporterTests.test_widget_assertion_text_is_part_of_the_error_for_red_matching'],
        'Synthetic flutter_test JSON events modelled on the trial log; other reporters are not covered.'),
    case('regression-attribution', 'An existing suite failing on the baseline too is environment, not a product repair', '8207d61', [
        'tests.test_delivery_review_findings.RegressionAttributionTests.test_suite_failing_on_baseline_too_is_environment_not_product',
        'tests.test_delivery_review_findings.RegressionAttributionTests.test_suite_passing_on_baseline_is_a_product_regression'],
        'Flutter is a fixture here; the live trial showed the ink_sparkle shader failure without test assets.'),
    case('review-protocol', 'An accepted review citing wrong refs is corrected by the reviewer, never turned into code repair', '2d46da3', [
        'tests.test_delivery_review_findings.ReviewProtocolTests.test_accepted_review_with_a_wrong_ref_goes_back_to_the_reviewer_not_to_code_repair',
        'tests.test_delivery_review_findings.ReviewProtocolTests.test_persistent_protocol_defect_asks_instead_of_repairing'],
        'Found by autonomy trial 2 (TASK-03a6a3a9); the reviewer is a fixture here.'),
    # Codex review P1 (2026-10-12): red by behaviour on d7410c1 (the fix's parent), green after.
    case('deadline-answer', 'An answer recorded after the root deadline is applied: stop cancels, retry asks the next budget episode', '153c553', [
        'tests.test_codex_review_p1.DeadlineAnswerTests.test_stop_answered_after_the_deadline_cancels_the_root',
        'tests.test_codex_review_p1.DeadlineAnswerTests.test_retry_answered_without_an_extension_asks_a_new_budget_question',
        'tests.test_codex_review_p1.DeadlineAnswerTests.test_retry_after_a_user_extension_continues_to_completion'],
        'In-process runner.loop with a one-second fixture deadline; the extension probe is a guard that also passed before.'),
    case('scorecard-levels', 'Completion and assistance are separate levels; partial work is never autonomous_complete', '153c553', [
        'tests.test_codex_review_p1.ScorecardLevelTests.test_partial_delivery_is_never_autonomous_complete',
        'tests.test_codex_review_p1.ScorecardLevelTests.test_full_verified_delivery_without_help_is_autonomous_complete',
        'tests.test_codex_review_p1.ScorecardLevelTests.test_partial_and_assisted_are_reported_on_both_levels'],
        'Synthetic observed-task records; the classifier reads ledger projections only.'),
    case('device-permission-window', 'No device command after valid_until; unknown device state asks and never replays', '153c553', [
        'tests.test_codex_review_p1.DevicePermissionWindowTests.test_no_device_command_after_the_window_expires_during_install',
        'tests.test_codex_review_p1.DevicePermissionWindowTests.test_expiry_after_a_scenario_step_stops_without_cleanup_and_reports_uncertain',
        'tests.test_codex_review_p1.PermissionWindowPathTests.test_reconcile_after_expiry_sends_nothing_and_never_replays',
        'tests.test_codex_review_p1.PermissionWindowPathTests.test_preflight_skips_an_expired_optional_device_and_stops_a_required_one',
        'tests.test_codex_review_p1.PermissionWindowDeliveryTests.test_optional_device_expired_before_the_scenario_is_not_run',
        'tests.test_codex_review_p1.PermissionWindowDeliveryTests.test_required_device_expired_asks_for_a_new_window',
        'tests.test_codex_review_p1.PermissionWindowDeliveryTests.test_expiry_after_scenario_steps_asks_and_never_replays'],
        'ADB and clock are fixtures; the window is enforced per command, not by a device-side lock.'),
    # Round 2 (2026-10-12): Codex scorecard finding and the two causes trial 3 stopped at E2E.
    case('decision-provenance', 'An entry deciding or relaying is assisted, an unattributed answer unknown, a user answer autonomous', '9e97460', [
        'tests.test_autonomy_round2.DecisionProvenanceTests.test_entry_decision_under_delegation_is_assisted',
        'tests.test_autonomy_round2.DecisionProvenanceTests.test_relayed_user_decision_is_assisted_not_autonomous',
        'tests.test_autonomy_round2.DecisionProvenanceTests.test_unattributed_answer_is_unknown',
        'tests.test_autonomy_round2.DecisionProvenanceTests.test_users_own_answer_keeps_autonomy',
        'tests.test_autonomy_round2.DecisionProvenanceTests.test_ledger_cli_and_observation_record_who_decided',
        'tests.test_eval_scorecard.ScorecardTests.test_each_outcome_class_needs_positive_evidence'],
        'Provenance is attributed locally (ONECREW_ACTOR, MCP source); it is evidence, not identity proof.'),
    case('live-ui-selectors', 'Selectors resolve on the real Flutter tree by recorded tiers; a wait timeout is a selector finding', '9e97460', [
        'tests.test_autonomy_round2.LiveSelectorTests.test_flutter_labels_resolve_with_recorded_tiers',
        'tests.test_autonomy_round2.LiveSelectorTests.test_absence_needs_no_mention_at_all',
        'tests.test_autonomy_round2.LiveSelectorTests.test_snapshot_keeps_labels_and_masks_private_values',
        'tests.test_autonomy_round2.LiveDeviceTests.test_flutter_scenario_passes_with_tier_evidence',
        'tests.test_autonomy_round2.LiveDeviceTests.test_absent_assertion_fails_as_a_product_finding',
        'tests.test_autonomy_round2.LiveDeviceTests.test_unresolved_selector_leaves_a_sanitized_snapshot',
        'tests.test_autonomy_round2.LiveDeviceTests.test_wait_that_never_matches_is_a_selector_finding_not_a_scenario_timeout'],
        'Fixture tree is the real dump of the trial app; other apps/OEM trees may expose labels differently.'),
    case('device-environment-recovery', 'System dialog answered with Wait inside the grant; only the envelope emulator is booted', '9e97460', [
        'tests.test_autonomy_round2.LiveDeviceTests.test_system_ui_not_responding_is_answered_with_wait_inside_the_grant',
        'tests.test_autonomy_round2.LiveDeviceTests.test_dialog_that_takes_focus_mid_scenario_is_answered_once_then_input_continues',
        'tests.test_autonomy_round2.LiveDeviceTests.test_physical_device_with_a_stuck_dialog_is_never_rebooted',
        'tests.test_autonomy_round2.LiveDeviceTests.test_absent_emulator_is_booted_only_when_the_envelope_names_it',
        'tests.test_autonomy_round2.EnvelopeEmulatorTests.test_only_an_emulator_serial_may_be_booted',
        'tests.test_autonomy_round2.PlannedDeviceTests.test_preflight_defers_an_absent_approved_emulator_and_requires_its_avd'],
        'ADB and the emulator process are fixtures; a live boot is covered only by the trial.'),
    case('boot-settle', 'A just-booted System UI that hangs repeatedly is waited out with Wait, not restarted at once', 'a9a5020', [
        'tests.test_autonomy_round2.LiveDeviceTests.test_a_just_booted_system_ui_that_hangs_repeatedly_is_waited_out_not_restarted'],
        'Found by a live smoke run on the emulator; boot load and timing are simulated here.'),
    case('app-crash-evidence', 'A crashed app is crash evidence (Java: product; native on the emulator: one restart), not a focus problem', 'c113c10', [
        'tests.test_autonomy_round2.AppCrashTests.test_crash_summary_keeps_structure_only',
        'tests.test_autonomy_round2.AppCrashTests.test_a_dead_app_is_a_crash_finding_not_another_window',
        'tests.test_autonomy_round2.AppCrashTests.test_native_crash_at_launch_restarts_the_approved_emulator_once',
        'tests.test_autonomy_round2.AppCrashTests.test_java_crash_is_a_product_finding_and_never_restarts',
        'tests.test_autonomy_round2.AppCrashTests.test_a_previous_native_crash_restarts_the_emulator_before_install',
        'tests.test_autonomy_round2.AppCrashTests.test_own_crash_dialog_is_not_a_system_hang'],
        'Found by live trial 5; crash buffer lines are real but shortened, the emulator restart is a fixture here.'),
    case('red-only-repair', 'Correct code with a non-behavioural red check gets a tests-only repair, not a demand for a production fix', 'fe94a63', [
        'tests.test_autonomy_round2.RedEvidenceRepairTests.test_red_only_failure_is_a_tests_only_repair_with_actionable_feedback',
        'tests.test_autonomy_round2.RedEvidenceRepairTests.test_a_real_failing_test_still_needs_a_production_fix',
        'tests.test_autonomy_round2.RedEvidenceRepairTests.test_tests_only_scope_cannot_be_claimed_outside_a_delivery',
        'tests.test_autonomy_round2.TestsOnlyPatchTests.test_scope_tests_accepts_a_test_only_patch_and_refuses_production_edits'],
        'Found by live trial 6; worker quality on the narrowed repair is shown only by a trial.'),
    case('scenario-calibration', 'A planned scenario is recalibrated from the live-UI snapshot without weakening assertions, bounded', '9e97460', [
        'tests.test_autonomy_round2.CalibrationTests.test_selector_failure_of_a_planned_replay_safe_scenario_is_calibrated',
        'tests.test_autonomy_round2.CalibrationTests.test_validator_keeps_operations_passed_steps_and_assertions',
        'tests.test_autonomy_round2.CalibrationDeliveryTests.test_live_ui_calibration_reruns_the_stage_and_completes',
        'tests.test_autonomy_round2.CalibrationDeliveryTests.test_expected_text_missing_on_screen_is_a_product_repair_without_a_model_call',
        'tests.test_autonomy_round2.CalibrationDeliveryTests.test_calibration_is_bounded_then_one_question',
        'tests.test_autonomy_round2.PlannedDeviceTests.test_compiled_device_node_carries_calibration_and_the_approved_emulator'],
        'Relocation is code since e7ac37a (before: the model was a fixture); a live relocation is only shown by a trial.'),
    # Codex review of round 2 (REVIEW-CODEX-ONECREW-ROUND2-742a139-2026-10-12.txt) and the real-device mode it reviewed.
    case('calibration-equivalence', 'Calibration may relocate a selector but never weaken what it checks (state, verbatim labels, absence)', 'b19b35e', [
        'tests.test_codex_review_round2.CalibrationEquivalenceTests.test_dropping_an_expected_state_is_refused',
        'tests.test_codex_review_round2.CalibrationEquivalenceTests.test_changing_an_absence_check_is_refused',
        'tests.test_codex_review_round2.CalibrationEquivalenceTests.test_future_assertions_and_cleanup_keep_their_conditions',
        'tests.test_codex_review_round2.CalibrationEquivalenceTests.test_a_label_less_locator_cannot_be_repointed'],
        'Codex P1-1; the model is not involved here, only the validator that gates its proposals.'),
    case('emulator-identity', 'Install, input or kill only on the approved AVD; unknown identity or another AVD blocks', 'b19b35e', [
        'tests.test_codex_review_round2.EmulatorIdentityTests.test_another_avd_on_the_serial_gets_no_install_input_or_kill',
        'tests.test_codex_review_round2.EmulatorIdentityTests.test_an_unverifiable_identity_blocks',
        'tests.test_codex_review_round2.EmulatorIdentityTests.test_the_approved_avd_opened_by_the_user_is_used_but_never_killed'],
        'Codex P1-2; emulator console is a fixture, a live check of emu avd name is separate.'),
    case('emulator-ownership', 'Ownership of a booted emulator survives retries; only that instance is stopped', 'b19b35e', [
        'tests.test_codex_review_round2.EmulatorOwnershipTests.test_boot_then_failure_then_retry_success_stops_the_owned_instance',
        'tests.test_codex_review_round2.EmulatorOwnershipTests.test_a_replaced_instance_is_not_stopped'],
        'Codex P2 (trial 7 left its emulator running); coordinator restart is modelled by a fresh device run.'),
    # Codex follow-up of b19b35e (REVIEW-CODEX-ONECREW-b19b35e-FOLLOWUP-2026-10-12.txt): the two P1s as principles.
    case('relocation-proof', 'A locator is relocated only when the live UI proves the same object; identity and condition never change', 'e7ac37a', [
        'tests.test_codex_followup_b19b35e.RelocationPrincipleTests.test_codex_probe_dropping_an_observable_id_moves_the_check_to_another_account',
        'tests.test_codex_followup_b19b35e.RelocationPrincipleTests.test_several_nodes_with_the_same_label_never_prove_one',
        'tests.test_codex_followup_b19b35e.RelocationPrincipleTests.test_one_same_label_node_is_no_proof_for_an_unexposed_id',
        'tests.test_codex_followup_b19b35e.RelocationPrincipleTests.test_changing_resource_id_or_class_is_refused',
        'tests.test_codex_followup_b19b35e.RelocationPrincipleTests.test_a_class_the_screen_does_not_show_is_not_dropped',
        'tests.test_codex_followup_b19b35e.RelocationPrincipleTests.test_moving_a_label_attribute_onto_a_merged_label_shared_by_siblings_is_refused',
        'tests.test_codex_followup_b19b35e.RelocationPrincipleTests.test_a_later_assertion_and_cleanup_are_never_relocated',
        'tests.test_codex_followup_b19b35e.RelocationPrincipleTests.test_an_absence_check_is_never_relocated',
        'tests.test_codex_followup_b19b35e.CalibrationRoutingTests.test_codex_probe_keeps_the_assertion_and_reports_the_product'],
        'Codex P1-1 follow-up; adversarial variants beyond the probe (same label on several nodes, id/class/label attribute, later steps, cleanup).'),
    case('relocation-capability', 'A locator that failed only on incidental state or label placement is still relocated, without a model', 'e7ac37a', [
        'tests.test_codex_followup_b19b35e.RelocationCapabilityTests.test_trial5_locator_that_named_focus_is_relocated_with_identity_kept',
        'tests.test_codex_followup_b19b35e.RelocationCapabilityTests.test_a_label_written_in_another_attribute_or_as_a_merged_part_is_relocated',
        'tests.test_codex_followup_b19b35e.RelocationCapabilityTests.test_codex_probe_is_a_condition_finding_not_a_relocation',
        'tests.test_codex_followup_b19b35e.RelocationCapabilityTests.test_relocation_never_calls_a_model',
        'tests.test_codex_review_round2.CalibrationEquivalenceTests.test_relocating_the_failing_locator_with_its_identity_kept_is_accepted',
        'tests.test_autonomy_round2.CalibrationDeliveryTests.test_at_the_calibration_bound_a_selector_failure_is_one_question'],
        'Capability control for relocation-proof (trial 5 snapshot); blocking more is not counted as autonomy.'),
    case('emulator-instance-binding', 'Every emulator change, recovery and cleanup goes only to the verified instance; loss blocks all of them', 'e7ac37a', [
        'tests.test_codex_followup_b19b35e.InstanceBindingTests.test_codex_probe_replacement_between_prepare_and_install',
        'tests.test_codex_followup_b19b35e.InstanceBindingTests.test_same_avd_new_boot_between_steps_stops_main_steps_and_cleanup',
        'tests.test_codex_followup_b19b35e.InstanceBindingTests.test_replacement_before_cleanup_gets_no_cleanup',
        'tests.test_codex_followup_b19b35e.InstanceBindingTests.test_replacement_before_system_recovery_gets_no_recovery_input',
        'tests.test_codex_followup_b19b35e.InstanceBindingTests.test_replacement_before_an_emulator_restart_gets_no_kill',
        'tests.test_codex_followup_b19b35e.InstanceBindingTests.test_replacement_before_the_stop_after_a_pass_is_not_stopped',
        'tests.test_codex_followup_b19b35e.InstanceBindingTests.test_an_emulator_serial_without_an_approved_avd_is_bound_to_its_first_instance',
        'tests.test_codex_followup_b19b35e.InstanceBindingTests.test_an_unreadable_identity_is_read_again_but_never_assumed',
        'tests.test_codex_followup_b19b35e.CoordinatorRestartTests.test_an_interrupted_attempt_is_not_replayed_on_a_replacement',
        'tests.test_codex_followup_b19b35e.CoordinatorRestartTests.test_an_interrupted_attempt_replays_on_the_same_instance',
        'tests.test_codex_followup_b19b35e.CoordinatorRestartTests.test_a_new_attempt_after_restart_verifies_again_and_only_stops_its_own_boot'],
        'Codex P1-2 follow-up; ADB is scripted. One command may still race a replacement inside one adb round trip (no atomic compare-and-execute).'),
    case('emulator-instance-capability', 'An unchanged instance runs, stops after a pass and pays one identity read per change', 'e7ac37a', [
        'tests.test_codex_followup_b19b35e.ValidInstanceTests.test_an_unchanged_instance_passes_and_every_change_is_checked_right_before_it',
        'tests.test_codex_followup_b19b35e.ValidInstanceTests.test_only_exact_read_shapes_skip_the_gate',
        'tests.test_codex_followup_b19b35e.ValidInstanceTests.test_a_physical_device_is_not_gated_by_boot_id'],
        'Capability control for emulator-instance-binding; physical devices keep their path.'),
    # Generic execution foundation (13/10/2026): work contracts instead of per-task modes/recipes.
    case('work-contract', 'A work contract runs with isolated edits/commands, exact-name branches at a pinned commit and independent core verification', '4e00059', [
        'tests.test_work_contract.ContractTests.test_contract_rejects_push_unknown_fields_bad_names_and_missing_authorization',
        'tests.test_work_contract.ContractTests.test_work_job_is_admitted_without_a_separate_solution_and_keeps_the_pinned_provider',
        'tests.test_work_contract.BranchTests.test_exact_name_branch_at_pinned_head_preserves_checkout_source_stash_and_index',
        'tests.test_work_contract.BranchTests.test_existing_ref_is_reported_never_overwritten_and_unauthorized_names_or_commits_refused',
        'tests.test_work_contract.WorkspaceTests.test_edit_run_verify_handover_in_workspace_without_touching_the_project',
        'tests.test_work_contract.WorkspaceTests.test_independent_verification_rejects_false_claims_without_a_review_call',
        'tests.test_work_contract.WorkspaceTests.test_deleted_modified_or_skipped_tests_and_zero_tests_are_findings',
        'tests.test_work_contract.WorkspaceTests.test_project_changed_during_the_job_is_not_reported_as_preserved',
        'tests.test_work_contract.WorkspaceTests.test_authority_is_enforced_by_the_core',
        'tests.test_work_contract.WorkspaceTests.test_background_process_is_contained_and_stopped',
        'tests.test_work_contract.WorkspaceTests.test_apply_and_export_need_authority_and_never_overwrite_user_edits'],
        'Scripted worker, real Git and the real Python on PATH; no model call. Live behaviour is shown only by acceptance tasks.'),
    case('work-durability', 'Work jobs continue after a coordinator restart without repeating effects; hints, Kiro version and prompt size are bounded', '4e00059', [
        'tests.test_work_contract.BranchTests.test_lost_ack_is_reconciled_without_a_second_update_ref',
        'tests.test_work_contract.DurabilityTests.test_coordinator_restart_continues_without_repeating_effects_or_calls',
        'tests.test_work_contract.DurabilityTests.test_verified_commands_of_a_completed_job_are_offered_to_the_next_job_as_hints',
        'tests.test_work_contract.DurabilityTests.test_unverified_kiro_version_stays_unavailable',
        'tests.test_work_contract.PromptTests.test_kiro_prompt_keeps_the_contract_within_the_verified_cap'],
        'Coordinator restart is modelled by a new runtime object over the same ledger; Kiro version via a patched CLI probe.'),
    case('work-acceptance-fixes', 'Defects found by live acceptance runs stay fixed: finish matches the authority, Kiro prose around JSON, Node 24 test counts, no repeated failed reads, user git config honoured, work lands on a branch the job created', 'b8ce393', [
        'tests.test_work_contract.ExportAdvanceTests.test_a_branch_this_job_created_can_carry_the_work_but_a_user_branch_never_moves',
        'tests.test_work_contract.GitEnvironmentTests.test_user_config_selection_is_honoured_and_user_hooks_never_run',
        'tests.test_work_contract.RepeatTests.test_missing_path_names_what_exists_and_an_identical_failed_request_is_not_repeated',
        'tests.test_work_contract.PromptTests.test_finish_offers_verification_commands_only_with_the_commands_authority',
        'tests.test_work_contract.DurabilityTests.test_kiro_reply_with_prose_around_the_json_is_parsed_and_a_reply_without_json_is_refused',
        'tests.test_work_contract.TestCountTests.test_node_spec_and_tap_reporters_are_counted'],
        'From acceptance runs A2-r1 (finish), A5-r1 (Kiro JSON) and held-out preparation (Node 24); failures retained in the handover.'),
    # Codex review of the generic execution foundation (13/10/2026, runtime 8603e74): GX-P1-01..03 and GX-GAP-04.
    # Adversarial probes are red by behaviour on 8603e74; positive controls must stay green on both sides.
    case('work-scope-gate', 'A command, a verification or a formatter cannot deliver changes that write/edit may not make', 'b01a5b8', [
        'tests.test_work_boundary.ScopeGateTests.test_a_command_cannot_deliver_what_write_may_not',
        'tests.test_work_boundary.ScopeGateTests.test_commands_without_edit_authority_deliver_nothing_until_restored',
        'tests.test_work_boundary.ScopeGateTests.test_a_verification_command_cannot_change_the_candidate',
        'tests.test_work_boundary.ScopeGateTests.test_restore_brings_back_the_pinned_version'],
        'Codex probe GX-P1-01 and variants; scripted worker, real Git and Python. restore is a new action (absent on 8603e74).'),
    case('work-write-boundary', 'Contained commands cannot write the project, the OneCrew state or elsewhere, nor redirect core Git', 'b01a5b8', [
        'tests.test_work_boundary.ScopeGateTests.test_contained_commands_cannot_write_the_project_the_state_or_elsewhere',
        'tests.test_work_boundary.ScopeGateTests.test_a_command_cannot_redirect_core_git_into_the_user_repository',
        'tests.test_work_boundary.ScopeGateTests.test_unconfined_commands_are_a_user_grant'],
        'Real Windows Low-integrity boundary on this host. A write boundary only: reads and network are not contained.'),
    case('work-intent-reconcile', 'A restart between a side effect and its receipt reconciles and never re-runs a command or verification', 'b01a5b8', [
        'tests.test_work_boundary.IntentTests.test_a_command_that_ran_before_the_crash_is_not_run_again',
        'tests.test_work_boundary.IntentTests.test_a_command_interrupted_before_it_started_is_reported_not_replayed',
        'tests.test_work_boundary.IntentTests.test_a_write_applied_before_the_crash_is_reconciled_not_failed',
        'tests.test_work_boundary.IntentTests.test_an_interrupted_verification_is_a_finding_and_is_not_run_again'],
        'Codex probe GX-P1-02; the crash is a BaseException in-process. Real process kills are shown by the live acceptance run.'),
    case('work-output-binding', 'Verification evidence is bound to the candidate and the real delivered refs/files until completion', 'b01a5b8', [
        'tests.test_work_boundary.OutputBindingTests.test_a_branch_moved_after_export_is_a_finding',
        'tests.test_work_boundary.OutputBindingTests.test_a_stale_apply_is_a_finding_until_the_candidate_is_applied_again',
        'tests.test_work_boundary.OutputBindingTests.test_a_project_change_outside_the_applied_files_is_still_a_finding',
        'tests.test_work_boundary.OutputBindingTests.test_an_output_changed_during_the_review_is_not_completed'],
        'Codex probe GX-P1-03 variants A/B and the long-review window; the reviewer is a fixture.'),
    case('work-positive-controls', 'Valid work still completes: in-scope changes through commands, ignored build output, a full verified delivery', 'b01a5b8', [
        'tests.test_work_boundary.ScopeGateTests.test_positive_control_in_scope_work_through_a_command_is_delivered',
        'tests.test_work_boundary.ScopeGateTests.test_positive_control_output_ignored_by_the_repository_is_not_delivered',
        'tests.test_work_boundary.OutputBindingTests.test_positive_control_valid_work_completes_with_a_patch_of_the_verified_candidate'],
        'Expected green on both sides: the fixes must not block valid work.'),
    case('work-boundary-under-host', 'Contained commands start under the Task Scheduler host token; a Windows status exit is named, not guessed', 'bbef812', [
        'tests.test_work_boundary.ContainTokenTests.test_the_contained_token_owns_its_objects_as_the_user',
        'tests.test_work_boundary.ContainTokenTests.test_a_windows_status_exit_is_named_not_left_as_a_decimal'],
        'Found by runs N1-r2/N2-r1. The token property is green in a chat context on older revisions too; the red/green '
        'evidence for the host context is the Task Scheduler probe in D:/OneCrewRuns/gxp1-acc.'),
    case('work-repeat-guard', 'A failed command is not repeated unchanged; a missing path argument is named; timings do not hide repeats', '6028118', [
        'tests.test_work_boundary.RepeatAndHintTests.test_a_failed_command_is_not_run_again_until_the_command_or_the_workspace_changes',
        'tests.test_work_boundary.RepeatAndHintTests.test_a_missing_path_argument_is_not_called_a_missing_dependency',
        'tests.test_work_boundary.RepeatAndHintTests.test_timing_noise_does_not_hide_a_repeated_result'],
        'Found by acceptance run N2-r2 (Kiro repeated node --test test five times). Worker judgement itself is not graded here.'),
    case('host-dispatch', 'Dispatched jobs run under a host outside the entry: admitted once, bounded restarts, user waits, reboot and cancel', '02199f6', [
        'tests.test_host.DispatchTests.test_dispatch_needs_a_live_host_that_serves_this_state_root',
        'tests.test_host.DispatchTests.test_runner_start_uses_the_host_only_for_a_served_state_root',
        'tests.test_host.DispatchTests.test_a_request_the_host_cannot_see_is_withdrawn_with_a_clear_error',
        'tests.test_host.DispatchTests.test_the_host_home_is_outside_appdata',
        'tests.test_host.AdmissionTests.test_admits_once_and_never_starts_a_second_runner',
        'tests.test_host.AdmissionTests.test_a_cancelled_or_finished_task_is_refused',
        'tests.test_host.SupervisionTests.test_a_dead_runner_is_restarted_with_backoff_then_blocked_once',
        'tests.test_host.SupervisionTests.test_a_launched_runner_that_has_not_registered_yet_is_not_restarted',
        'tests.test_host.SupervisionTests.test_a_task_waiting_for_the_user_is_released_not_restarted',
        'tests.test_host.SupervisionTests.test_a_runner_lost_with_a_reboot_needs_an_explicit_resume',
        'tests.test_host.SupervisionTests.test_cancel_is_enforced_when_the_runner_does_not_stop_by_itself',
        'tests.test_host.LeaseTests.test_lease_is_trusted_only_with_a_fresh_heartbeat_from_a_live_process',
        'tests.test_host.LeaseTests.test_serve_once_writes_a_lease_and_scans_registered_roots',
        'tests.test_host.LeaseTests.test_task_xml_is_a_per_user_least_privilege_logon_task_without_time_limit'],
        'Launch is a fixture (capability absent on 8603e74). 808610b+d45fb68+02199f6 (found by runs N1-r1, N1-r2). '
        'The Task Scheduler host and a closed entry are live acceptance evidence.'),
    case('device-exact-mode', 'Real device: exact selectors, masked mismatch evidence, no calibration, recovery only when granted', '742a139', [
        'tests.test_device_exact_mode.ExactSelectorTests.test_a_relaxed_match_is_a_mismatch_with_masked_evidence_and_no_calibration',
        'tests.test_device_exact_mode.ExactSelectorTests.test_empty_content_description_is_a_valid_pinned_value',
        'tests.test_device_exact_mode.ExactSelectorTests.test_calibration_step_refuses_exact_mode',
        'tests.test_device_exact_mode.RecoveryPermissionTests.test_without_a_grant_nothing_is_sent_and_it_is_a_permission_question',
        'tests.test_device_exact_mode.RecoveryPermissionTests.test_locked_screen_needs_its_own_grant'],
        'A54/HIS mode added at the user request; mocks only, no live A54 run.'),
    case('environment-discovery', 'Toolchain, package, application id and tests discovered without the entry', '8207d61', [
        'tests.test_delivery_env.EnvironmentDiscoveryTests.test_flutter_root_precedence_and_rejections',
        'tests.test_delivery_env.EnvironmentDiscoveryTests.test_build_tools_selection',
        'tests.test_delivery_env.EnvironmentDiscoveryTests.test_effective_application_ids_and_launch_class',
        'tests.test_delivery_env.EnvironmentDiscoveryTests.test_missing_tools_are_reported_not_raised'],
        'Gradle files are parsed as text; flavors and computed ids are reported unresolved, not guessed.'),
    case('work-task-boundary', 'Per-task write boundary, independent of the token owner; a task keeps full control of its own files', '07d7ad6', [
        'tests.test_work_isolation.TaskBoundaryTests.test_a_task_cannot_write_another_tasks_workspace_temp_or_cache',
        'tests.test_work_isolation.TaskBoundaryTests.test_a_task_cannot_rewrite_the_access_rules_of_another_task_the_core_or_the_project',
        'tests.test_work_isolation.TaskBoundaryTests.test_positive_control_the_core_writes_every_task_and_toolchains_start',
        'tests.test_work_isolation.TaskBoundaryTests.test_positive_control_python_private_directories_work_in_the_workspace_and_the_checkout',
        'tests.test_work_isolation.OwnerIndependenceTests.test_contained_commands_write_their_workspace_when_the_core_owner_is_administrators',
        'tests.test_work_isolation.LegacyHomeTests.test_a_legacy_workspace_of_another_task_is_protected_by_the_first_contained_run'],
        'Codex review 2 findings 1 and 4 (13/10/2026) plus three adversarial reviews. Reads outside the task region are not '
        'contained (documented limit); owner = Administrators is also run by owner_env.py outside this harness.'),
    case('work-clean-verification', 'Verification runs in a clean Git checkout of the candidate; nothing comes from the workspace', '07d7ad6', [
        'tests.test_work_isolation.CleanVerificationTests.test_an_ignored_package_cannot_make_a_wrong_delivered_module_pass',
        'tests.test_work_isolation.CleanVerificationTests.test_positive_control_setup_recreates_ignored_inputs_and_is_recorded',
        'tests.test_work_isolation.CleanVerificationTests.test_verification_does_not_run_in_the_workspace',
        'tests.test_work_isolation.VerificationIdentityTests.test_verification_runs_in_the_checkout_and_refuses_arguments_into_the_workspace',
        'tests.test_work_isolation.VerificationIdentityTests.test_git_works_in_the_checkout_at_the_candidate_commit',
        'tests.test_work_isolation.VerificationIsolationRound2Tests.test_an_earlier_verification_cannot_seed_the_next',
        'tests.test_work_isolation.VerificationIsolationRound2Tests.test_arguments_with_dot_dot_segments_are_refused_in_verification'],
        'Codex review 2 finding 2. By the user decision of 13/10/2026 verification runs as the task identity; the clean checkout '
        'and confined arguments bind it to the candidate.'),
    case('work-verification-tampering', 'A candidate file changed by any verification command, or shadowed by setup output, is a finding', '07d7ad6', [
        'tests.test_work_isolation.VerificationIdentityTests.test_a_touched_but_unchanged_candidate_file_is_not_a_finding',
        'tests.test_work_isolation.VerificationIdentityTests.test_a_candidate_change_restored_by_a_later_command_is_still_found',
        'tests.test_work_isolation.VerificationIdentityTests.test_read_only_leftovers_do_not_break_the_next_verification',
        'tests.test_work_isolation.VerificationIdentityTests.test_a_package_made_by_setup_that_shadows_a_delivered_module_is_a_finding',
        'tests.test_work_isolation.VerificationIsolationRound2Tests.test_a_same_size_change_with_restored_times_is_found',
        'tests.test_work_isolation.VerificationIsolationRound2Tests.test_the_shadow_rule_spares_build_outputs_and_metadata_but_not_compiled_modules',
        'tests.test_work_isolation.VerificationIsolationRound2Tests.test_a_shadow_behind_a_large_dependency_tree_is_still_found',
        'tests.test_work_isolation.VerificationIsolationRound2Tests.test_a_compiled_cache_entry_that_python_would_not_check_is_a_shadow'],
        'Found by the adversarial reviews of 13/10/2026. A change made and undone inside one command is not detectable (limit).'),
    case('host-durable-admission', 'One runner per task across requests, retries, host crashes and failed launches; failures reach the user', '07d7ad6', [
        'tests.test_host.DurableAdmissionTests.test_requests_before_the_runner_registers_launch_once',
        'tests.test_host.DurableAdmissionTests.test_a_host_stopped_between_launch_record_and_identity_does_not_launch_again_within_grace',
        'tests.test_host.DurableAdmissionTests.test_a_held_runner_lock_is_an_owner',
        'tests.test_host.DurableAdmissionTests.test_a_launch_that_fails_is_recorded_failed_and_does_not_hold_off_the_next_request',
        'tests.test_host.DurableAdmissionTests.test_a_launch_refused_by_the_core_is_a_failed_request_not_an_admission',
        'tests.test_host.DurableAdmissionTests.test_an_admission_in_progress_elsewhere_is_not_doubled',
        'tests.test_host.DurableAdmissionTests.test_supervision_follows_the_identity_of_the_runner_that_owns_the_task',
        'tests.test_host.DurableAdmissionTests.test_a_probe_of_the_runner_lock_does_not_make_a_starting_runner_give_up',
        'tests.test_host.DurableAdmissionTests.test_a_restart_that_cannot_launch_counts_and_ends_in_a_block',
        'tests.test_host.DurableAdmissionTests.test_callers_with_their_own_retry_still_fail_fast'],
        'Codex review 2 finding 3. Launch is a fixture; the Task Scheduler host and duplicate dispatch are live acceptance evidence.'),
    case('work-review-facts', 'The completion review always gets bounded, core-established facts; stale records and prompts are not reused', '07d7ad6', [
        'tests.test_work_isolation.ReviewFactsTests.test_core_facts_survive_the_kiro_cap_and_name_untouched_tests',
        'tests.test_work_isolation.ReviewFactsTests.test_a_very_large_change_still_fits_the_kiro_review',
        'tests.test_work_isolation.ReviewFactsTests.test_many_applied_files_stay_bounded_in_the_facts',
        'tests.test_work_isolation.ReviewFactsTests.test_many_verification_outputs_stay_bounded_in_the_facts',
        'tests.test_work_isolation.ReviewFactsTests.test_a_current_verification_is_reused_and_an_interrupted_one_is_not_rerun',
        'tests.test_work_isolation.ReviewFactsTests.test_a_stored_review_prompt_is_not_reused_after_verification_ran_again',
        'tests.test_work_isolation.LegacyHomeTests.test_a_verification_stored_by_an_older_runtime_is_not_reused_for_review',
        'tests.test_work_isolation.LegacyHomeTests.test_an_existing_test_turned_into_another_kind_of_entry_is_a_test_change',
        'tests.test_work_isolation.LegacyHomeTests.test_common_test_files_outside_the_old_name_rule_are_tests'],
        'Codex review 2 N4 blocker. The reviewer model itself is not graded here; live run M2 is the large-packet evidence.'),
    case('work-manifest-survey', 'The worker sees what the project declares about build and test; bounded and robust to odd manifests', '07d7ad6', [
        'tests.test_work_isolation.ManifestTests.test_declared_test_commands_are_surveyed_across_ecosystems',
        'tests.test_work_isolation.ManifestTests.test_the_worker_prompt_carries_the_manifests',
        'tests.test_work_isolation.ManifestTests.test_unusual_manifests_neither_crash_nor_overflow',
        'tests.test_work_isolation.ManifestTests.test_a_directory_given_where_a_module_was_expected_is_named',
        'tests.test_work_isolation.ManifestTests.test_a_relative_directory_is_resolved_against_the_command_directory'],
        'Codex review 2 N2 blocker. Whether a worker uses the declared command is judged by live run M3, not here.'),
    case('work-progress-and-replay', 'Progress and failure replay follow real workspace changes; real loops are still stopped', 'f8023ae', [
        'tests.test_review_07d7ad6.ProgressTests.test_codex_probe_lists_between_real_edits_are_progress',
        'tests.test_review_07d7ad6.ProgressTests.test_the_runner_reaches_past_the_m2_block_point',
        'tests.test_review_07d7ad6.ProgressTests.test_a_real_loop_without_changes_is_still_stopped',
        'tests.test_review_07d7ad6.ProgressTests.test_no_op_and_failed_writes_are_not_progress',
        'tests.test_review_07d7ad6.ProgressTests.test_timestamps_and_rewritten_caches_are_not_progress',
        'tests.test_review_07d7ad6.ProgressTests.test_a_generated_ignored_output_is_progress',
        'tests.test_review_07d7ad6.ProgressTests.test_progress_state_survives_restart',
        'tests.test_review_07d7ad6.FailureReplayTests.test_codex_probe_a_file_created_after_a_failed_read_is_read',
        'tests.test_review_07d7ad6.FailureReplayTests.test_a_build_output_created_by_a_command_is_read',
        'tests.test_review_07d7ad6.FailureReplayTests.test_with_nothing_changed_the_failure_is_replayed',
        'tests.test_review_07d7ad6.FailureReplayTests.test_restore_counts_as_a_change'],
        'Codex review of 07d7ad6, R1 and R2 (14/10/2026). Live evidence: M2 resumed past its step-13 block.'),
    case('host-admission-retry', 'Transient ledger errors never lose a dispatch or launch twice; a lasting one blocks with the cause', 'f8023ae', [
        'tests.test_review_07d7ad6.AdmissionRetryTests.test_codex_probe_a_busy_ledger_keeps_the_request_and_admits_later',
        'tests.test_review_07d7ad6.AdmissionRetryTests.test_busy_while_recording_the_outcome_after_a_launch_does_not_launch_again',
        'tests.test_review_07d7ad6.AdmissionRetryTests.test_a_persistently_busy_ledger_ends_with_a_block_and_the_reason',
        'tests.test_review_07d7ad6.AdmissionRetryTests.test_a_malformed_request_is_still_ended_at_once',
        'tests.test_review_07d7ad6.AdmissionRetryTests.test_the_entry_retries_a_busy_ledger_and_reports_a_lasting_one'],
        'Codex review of 07d7ad6, R3. SQLite errors are injected; WinError 5 of 13/10 is not covered (no stack yet).'),
    case('runner-priority', 'Host and runners run at Normal priority, never inheriting below-normal or above it', 'f8023ae', [
        'tests.test_review_07d7ad6.PriorityTests.test_the_host_task_runs_at_normal_priority',
        'tests.test_review_07d7ad6.PriorityTests.test_runners_are_started_at_normal_priority'],
        'Codex review of 07d7ad6, R4. The live priority under Task Scheduler is acceptance evidence.'),
    case('work-checkout-setup-feedback', 'A test that fails only in the clean checkout is reported with its output and the setup it lacks', '3f86010', [
        'tests.test_review_07d7ad6.VerificationFeedbackTests.test_a_missing_generated_file_in_the_checkout_points_to_setup'],
        'Found in the M1 resume of 14/10/2026: the worker then declared the project build as setup and M1 completed.'),
    case('work-latest-result', 'The last result, and which receipt a lookup showed, reach the worker under the provider prompt cap', '3e632c1', [
        'tests.test_review_07d7ad6.LatestResultTests.test_the_last_result_reaches_the_worker_even_when_the_packet_is_at_its_minimum'],
        'Found in the M2 resume of 14/10/2026 (receipt asked three times). M2 itself did not complete: see the GX-P3 handover.'),
    case('work-changed-files', 'The worker sees which files it has changed against the pinned commit', '63f51cd', [
        'tests.test_review_07d7ad6.LatestResultTests.test_the_worker_sees_which_files_it_has_changed'],
        'Found in the M2 resume of 14/10/2026. M2 was still stopped by the progress guard afterwards (worker reasoning loop).'),
    case('host-queue-reads', 'A request that cannot be read for a moment is never dropped, decided twice or launched twice', '198a640',
         [f'tests.test_review_p3.HostQueueTests.{t}' for t in (
             'test_a_locked_queue_file_is_admitted_from_the_ledger_once', 'test_restart_between_retries_keeps_the_request_and_admits_it_once',
             'test_real_malformed_json_without_a_ledger_record_is_ended_and_with_one_is_admitted',
             'test_an_unreadable_launch_record_never_allows_a_second_runner_or_a_false_block',
             'test_a_launch_record_that_cannot_be_written_defers_instead_of_blocking',
             'test_an_unreadable_supervision_file_is_neither_overwritten_nor_lost')] +
         [f'tests.test_review_p3.HostReviewTests.{t}' for t in (
             'test_a_locked_ledger_never_ends_a_request', 'test_a_supervision_file_that_cannot_be_replaced_still_supervises_the_launched_runner',
             'test_a_corrupt_supervision_file_is_rebuilt_with_restarted_tasks_and_their_restarts',
             'test_exhausted_retries_with_an_unreadable_launch_record_do_not_stall_the_root',
             'test_a_damaged_foreign_request_is_kept_aside_with_its_reason')],
         'Codex deep review P3, finding A; real Windows locks. Second half from the adversarial review of the P4 diff.'),
    case('paging-contract', 'The model receives every character of a long result through exact continuations within the Kiro cap', '198a640',
         [f'tests.test_review_p3.PagingTests.{t}' for t in (
             'test_a_9kb_file_is_delivered_to_its_last_line', 'test_a_file_larger_than_one_read_page_is_delivered_without_a_gap',
             'test_the_middle_of_a_long_command_log_is_reachable', 'test_a_long_listing_is_paged_by_items_and_then_by_the_tool_cursor',
             'test_receipt_refuses_arguments_outside_its_contract')] +
         [f'tests.test_review_p3.PagingUnitTests.{t}' for t in (
             'test_git_show_continues_with_its_own_cursor', 'test_a_cut_read_continues_by_receipt_and_a_list_without_directory_by_its_cursor',
             'test_a_scalar_field_is_delivered_whole')],
         'Codex deep review P3, finding B; the real _fit and Kiro cap, never mocked.'),
    case('workspace-key', 'One workspace key: a retest runs after generated ignored inputs change; real loops are still stopped', '198a640',
         [f'tests.test_review_p3.IgnoredInputTests.{t}' for t in (
             'test_a_retest_runs_after_the_build_generated_the_missing_ignored_input', 'test_a_content_change_of_an_existing_ignored_input_counts',
             'test_with_nothing_changed_the_failed_command_is_still_refused', 'test_a_rewritten_log_or_cache_is_not_a_change',
             'test_retests_after_only_ignored_inputs_changed_are_bounded', 'test_a_cosmetic_argv_change_of_a_failing_command_is_a_repeat',
             'test_different_silent_failing_probes_are_not_one_repeated_result',
             'test_a_large_ignored_dependency_tree_does_not_hide_the_generated_input',
             'test_a_file_written_by_a_background_command_is_read_after_it_failed', 'test_the_failed_read_replay_follows_the_same_key')],
         'Codex deep review P3, finding C (controls included: unchanged workspace, log/cache noise).'),
    case('resume-recovery', 'Resume rebuilds the context, keeps counters, budget and effects, and every block gets a blocker handover', '198a640',
         [f'tests.test_review_p3.ResumeTests.{t}' for t in (
             'test_the_worker_is_warned_before_the_guard_stops_the_task',
             'test_a_block_writes_a_core_blocker_handover_and_notifies_once_from_the_checkpoint',
             'test_resume_rebuilds_the_context_keeps_counters_budget_and_work_and_bounds_the_loop',
             'test_resume_never_repeats_a_finished_effect', 'test_resume_respects_cancel_and_the_deadline')],
         'Codex deep review P3, part 2 (resume as recovery). Live evidence is the new task U1 of 14/10/2026.'),
    case('p4b-repeat-order', 'The latest repeat warnings survive the checkpoint, a restart and the compact prompt; real loops still stop',
         '55448b8', [f'tests.test_review_p4.RepeatOrderTests.{t}' for t in (
             'test_the_most_recent_repeats_are_kept_and_shown_across_checkpoints',
             'test_the_latest_warning_reaches_the_real_prompt_after_a_restart',
             'test_an_older_checkpoint_without_sequence_numbers_is_ordered_by_step', 'test_a_real_loop_is_still_stopped')],
         'Codex review of P4, R1 (U1 step 13 lost the warning for receipt@565).'),
    case('p4b-page-progress', 'Every page advances under the real Kiro cap: oversized list items come as text pages, never a self-loop',
         '55448b8', [f'tests.test_review_p4.PageProgressTests.{t}' for t in (
             'test_list_items_larger_than_the_page_are_delivered_and_the_continuation_advances',
             'test_a_long_single_line_is_delivered_with_the_same_extra_context', 'test_view_never_returns_a_page_that_does_not_advance')],
         'Codex review of P4, R2 (git_log with three 500-character subjects and ~5,200 characters of extra context).'),
    case('p4b-supervision-reconcile', 'A launched runner is never left unsupervised by successive host I/O errors; released tasks stay released',
         '55448b8', [f'tests.test_review_p4.SupervisionReconcileTests.{t}' for t in (
             'test_successive_io_errors_never_lose_the_supervision_of_a_launched_runner', 'test_a_released_task_is_not_supervised_again',
             'test_an_older_supervision_file_does_not_revive_launch_records_it_had_released')],
         'Codex review of P4, R3; real Windows locks.'),
    case('p4b-incomplete-key', 'An incomplete workspace key is never trusted: bounded retests/re-reads after changes it cannot see',
         '55448b8', [f'tests.test_review_p4.IncompleteKeyTests.{t}' for t in (
             'test_a_dependency_fix_allows_the_retest', 'test_a_same_size_dependency_change_allows_a_bounded_retest',
             'test_a_same_size_change_of_a_large_generated_file_allows_a_bounded_retest',
             'test_a_failed_read_is_retried_after_a_same_size_change_of_an_unhashed_file',
             'test_no_op_churn_with_an_incomplete_key_is_still_bounded')],
         'Codex review of P4, R4 (dependency "wrong" -> "correct-value"; a 2,000,001-byte file rewritten with the same size).'),
    case('p4c-legacy-supervision', 'A runner launched before the upgrade whose supervision was never saved is recovered once; a released task never',
         '1ae7782', [f'tests.test_review_p4b.LegacySupervisionTests.{t}' for t in (
             'test_a_runner_admitted_before_the_upgrade_whose_supervision_was_never_saved_is_recovered_once',
             'test_a_runner_still_running_at_the_upgrade_is_recovered_even_after_an_answered_question',
             'test_a_runner_that_ended_by_itself_after_its_question_was_answered_is_recovered',
             'test_an_alive_runner_whose_admission_was_recorded_as_not_launched_is_recovered',
             'test_a_record_unread_during_the_first_scan_after_the_upgrade_is_judged_by_the_same_evidence',
             'test_a_task_released_before_the_upgrade_is_not_revived', 'test_a_task_waiting_already_at_its_launch_is_not_revived_after_the_upgrade',
             'test_waiting_cancelled_and_paused_tasks_are_not_restarted_after_the_upgrade')],
         'Codex review of P4b, R3 (host.py:608 of 55448b8); controls included; real Windows locks.'),
    case('p4c-progress-trust', 'One trust rule for an incomplete workspace key: real unseen changes are never called unchanged, loops stay bounded',
         '1ae7782', [f'tests.test_review_p4b.ProgressTrustTests.{t}' for t in (
             'test_same_size_dependency_changes_between_identical_listings_are_not_called_unchanged',
             'test_real_changes_beyond_the_bound_are_stopped_without_claiming_nothing_changed',
             'test_an_older_checkpoint_keeps_its_counters_and_a_later_change_is_not_called_unchanged',
             'test_an_older_checkpoint_upgraded_right_after_a_change_does_not_call_the_next_listing_unchanged',
             'test_an_immediate_repeat_is_named_as_such_after_a_real_change_used_one_allowance',
             'test_one_rule_with_nothing_run_in_between_an_incomplete_key_refuses_like_a_complete_one',
             'test_identical_listings_with_nothing_run_in_between_are_still_a_repeat',
             'test_no_op_churn_between_identical_listings_is_still_bounded',
             'test_one_rule_after_a_same_size_change_the_check_and_the_read_run_again_bounded',
             'test_a_background_process_started_before_the_failed_command_is_a_possible_change')],
         'Codex review of P4b, R4 (progress.py:94 of 55448b8: wrong -> list -> right -> list -> final -> list); controls included.'),
    case('p5-page-delivery', 'Under the Kiro cap the worker receives every character of a result, in order, in real pages (live S1)',
         '1e3d27a', [f'tests.test_review_p5.PromptBudgetTests.{t}' for t in (
             'test_s1_shape_a_long_contract_still_delivers_the_whole_file',
             'test_a_growing_history_and_a_long_plan_still_leave_room_for_results',
             'test_a_large_vietnamese_file_arrives_whole_in_order_under_the_long_contract',
             'test_escape_heavy_text_is_paged_and_concatenates_to_the_exact_file',
             'test_the_last_page_and_a_page_at_the_end_are_valid_and_the_job_goes_on',
             'test_other_shape_long_english_contract_and_a_300_entry_listing',
             'test_a_command_result_with_many_fields_gives_its_output_real_room')]
         + ['tests.test_review_p5.GrowthTests.test_a_result_that_fits_whole_is_never_paged_for_the_partial_note',
            'tests.test_review_p5.NormalJobControlTests.test_a_normal_job_keeps_its_full_contract_and_gets_small_results_whole'],
         'Live S1 on 1ae7782 (TASK-04129bfc, 14/10/2026): 0 characters of a 2,381-character file in 7 results; control: normal job.'),
    case('p5-budget-refusal', 'A job or step the cap cannot serve is refused before any model call, naming the parts; never a does_not_fit prompt',
         '1e3d27a', [f'tests.test_review_p5.PromptBudgetTests.{t}' for t in (
             'test_a_contract_that_cannot_be_served_is_refused_before_any_model_call',
             'test_a_fallback_chain_to_kiro_is_checked_before_the_first_call',
             'test_the_completion_review_must_carry_the_full_contract_or_the_job_is_refused_first',
             'test_a_result_no_valid_page_can_show_is_refused_before_the_next_call_naming_the_part',
             'test_context_that_grows_past_the_cap_mid_job_is_refused_before_its_call')]
         + ['tests.test_review_p5.GrowthTests.test_a_review_that_cannot_fit_for_its_core_facts_blocks_once_before_any_call'],
         'Codex review of 1ae7782: _fit sent prompts carrying does_not_fit; the S1 refusal came after 8 calls.'),
    case('p5-receipts-contract', 'Lookups stay exact through layers; cut contract texts, answers and the plan are reachable whole',
         '1e3d27a', [f'tests.test_review_p5.{t}' for t in (
             'PromptBudgetTests.test_receipts_of_receipts_point_at_the_original_and_do_not_grow',
             'PromptBudgetTests.test_an_item_offset_past_the_end_is_refused_when_asked_and_the_job_goes_on',
             'PromptBudgetTests.test_a_cut_contract_item_is_returned_whole_by_the_contract_action',
             'GrowthTests.test_fetching_a_cut_contract_item_again_after_other_reads_is_not_a_repeat',
             'GrowthTests.test_a_long_plan_shown_cut_is_returned_whole_by_the_contract_action')],
         'Live S1: receipt of receipt of receipt, each wrapping the previous (+~110 characters per layer).'),
    case('p5-repair-review', 'After a failed verification or a review rejection the job keeps room for its repair; review prompts stay within the cap',
         '1e3d27a', [f'tests.test_review_p5.{t}' for t in (
             'PromptBudgetTests.test_s1_contract_after_a_failed_core_verification_the_worker_gets_a_repair_step',
             'GrowthTests.test_real_s1_size_contract_repairs_after_a_failed_core_verification_and_rereads_the_file',
             'PromptBudgetTests.test_a_rejected_finish_with_long_feedback_keeps_a_normal_job_running',
             'PromptBudgetTests.test_a_finish_whose_report_the_review_cannot_carry_is_sent_back_to_shorten',
             'GrowthTests.test_an_accepted_review_whose_finish_fails_in_the_core_is_shown_as_it_is',
             'GrowthTests.test_the_reviewer_and_an_uncapped_worker_see_an_earlier_rejection_whole',
             'GrowthTests.test_core_added_parts_stay_bounded_under_a_tight_cap')],
         'Review rounds of the P5 fix (S1 contract blocked on its first repair step, review loops); controls included.'),
    case('p5-full-flow-resume', 'Read, edit, test, review and handover under the cap through the real core; a runner restart keeps the page and counters',
         '1e3d27a', ['tests.test_review_p5.FullFlowTests.test_read_edit_test_review_and_handover_under_the_s1_shape_contract',
                     'tests.test_review_p5.FullFlowTests.test_a_runner_restart_mid_paging_continues_at_the_next_page_with_the_same_counters'],
         'Fixture only (scripted model); proves the mechanism, not autonomy.'),
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
