# OneCrew eval: runtime trước–sau

Đạt: 0/20 → 20/20 case-trials.
Baseline riêng trước từng fix.
Không phải tỷ lệ tự hoàn thành sản phẩm; không tự approve skill/routing.

| Case | Lượt | Trước | Sau | Phân loại |
|---|---:|---|---|---|
| apk-device-gate | 1 | capability_unavailable | passed | capability_added |
| apk-device-gate | 2 | capability_unavailable | passed | capability_added |
| handoff-backlog | 1 | runtime_error | passed | recovered |
| handoff-backlog | 2 | runtime_error | passed | recovered |
| missing-cache | 1 | assertion_failed | passed | recovered |
| missing-cache | 2 | assertion_failed | passed | recovered |
| parent-checkpoint | 1 | capability_unavailable | passed | capability_added |
| parent-checkpoint | 2 | capability_unavailable | passed | capability_added |
| parent-handover | 1 | capability_unavailable | passed | capability_added |
| parent-handover | 2 | capability_unavailable | passed | capability_added |
| review-80k | 1 | capability_unavailable | passed | capability_added |
| review-80k | 2 | capability_unavailable | passed | capability_added |
| review-gate | 1 | capability_unavailable | passed | capability_added |
| review-gate | 2 | capability_unavailable | passed | capability_added |
| snapshot-2mb | 1 | capability_unavailable | passed | capability_added |
| snapshot-2mb | 2 | capability_unavailable | passed | capability_added |
| timeout-checkpoint | 1 | capability_unavailable | passed | capability_added |
| timeout-checkpoint | 2 | capability_unavailable | passed | capability_added |
| windows-once | 1 | capability_unavailable | passed | capability_added |
| windows-once | 2 | capability_unavailable | passed | capability_added |

- Known historical cases, not held-out tasks or estimates of generalization.
- Passing a correct blocker means the safety contract passed, not product completion.
- Fixture results never enter product autonomy, model cost or device-success denominators.
- Historical mode uses different pre-fix commits; it is not a release-level before/after rate.
- No model calls, live server, ADB or Windows display in replay. No automatic promotion.
