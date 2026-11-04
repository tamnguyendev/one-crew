T28 [E1] evidence (round 7, 25/10/2026): the two v1 register suites (tests.test_review_lifecycle, tests.test_review_p6) run on the commit
BEFORE onecrew/finding_core.py was split out (1b4f4c6^ = 54b802c, git archive, no wrapper) and on the integration HEAD e61b2c2 (same files).
Same test list (test-list-diff.txt empty), same results (both OK, exit 0). Produced by hand (not a gate check); the gate's after-split side is
R05/check.register_v1_guard and check.register_v1_guard_p6.
