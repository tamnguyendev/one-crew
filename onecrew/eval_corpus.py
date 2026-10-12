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
    case('scenario-calibration', 'A planned scenario is recalibrated from the live-UI snapshot without weakening assertions, bounded', '9e97460', [
        'tests.test_autonomy_round2.CalibrationTests.test_selector_failure_of_a_planned_replay_safe_scenario_is_calibrated',
        'tests.test_autonomy_round2.CalibrationTests.test_validator_keeps_operations_passed_steps_and_assertions',
        'tests.test_autonomy_round2.CalibrationDeliveryTests.test_live_ui_calibration_reruns_the_stage_and_completes',
        'tests.test_autonomy_round2.CalibrationDeliveryTests.test_expected_text_missing_on_screen_is_a_product_repair_without_a_model_call',
        'tests.test_autonomy_round2.CalibrationDeliveryTests.test_calibration_is_bounded_then_one_question',
        'tests.test_autonomy_round2.PlannedDeviceTests.test_compiled_device_node_carries_calibration_and_the_approved_emulator'],
        'The model is a fixture here; semantic quality of a live calibration is only shown by a trial.'),
    case('environment-discovery', 'Toolchain, package, application id and tests discovered without the entry', '8207d61', [
        'tests.test_delivery_env.EnvironmentDiscoveryTests.test_flutter_root_precedence_and_rejections',
        'tests.test_delivery_env.EnvironmentDiscoveryTests.test_build_tools_selection',
        'tests.test_delivery_env.EnvironmentDiscoveryTests.test_effective_application_ids_and_launch_class',
        'tests.test_delivery_env.EnvironmentDiscoveryTests.test_missing_tools_are_reported_not_raised'],
        'Gradle files are parsed as text; flavors and computed ids are reported unresolved, not guessed.'),
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
