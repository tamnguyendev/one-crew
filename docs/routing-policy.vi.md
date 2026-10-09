# Chọn model từ công việc và quota

Revision 6 thêm [preference và JEV shadow](skills-routing.vi.md): ưu tiên provider sau hard gates rồi mới cost_rank; `--jev --brief ...` là opt-in một request evaluator bên ngoài, không tự dispatch. Không có `--jev` thì vẫn chạy hoàn toàn bằng code. Preference và reset hint không thay quota evidence hoặc benchmark. CLI `provider prefer/preference` quản lý default cho job mới.

`onecrew provider choose --file policy.json --json` là decision layer deterministic, không gọi model. Input gồm `workload` và `candidates`; code ở `onecrew/routing.py`. Đây là đề xuất có lý do, **chưa reserve quota subscription hoặc tự dispatch/switch**.

Workload có `complexity` 1–3, `risk` low/medium/high và danh sách provider được phép. Mỗi candidate có ID/provider/model, tier 1–3, `cost_rank` do policy cung cấp, boolean capability_verified, auth_mode=subscription và quota evidence. Tier tối thiểu bằng max(complexity, risk floor); chỉ sau khi đạt quyền/capability/tier/quota mới chọn cost_rank thấp nhất. Không tự coi model nhỏ luôn phù hợp, hoặc model đắt luôn cần thiết. Tier/cost_rank cần calibration cho nhóm việc thực tế; chưa phải benchmark đã chứng minh.

Quota evidence cần thời điểm quan sát/hết hiệu lực, nguồn và **tất cả cửa sổ áp dụng**. Mỗi cửa sổ dùng cùng đơn vị phần trăm: remaining, reserved, keep_for_chat, estimated_call, resets_at. Cửa sổ tuần hết thì bị loại dù cửa sổ ngắn còn; quota unknown/stale hoặc đã qua reset cần dữ liệu mới, không coi unlimited. Không nhận estimate=0 cho chi phí chưa biết. Dữ liệu hiện do operator/connector cung cấp; CLI chưa tự đọc toàn bộ subscription quotas.

`validate_decision` là boundary cho đề xuất AI/JEV tùy chọn: action phải thuộc tập core đưa ra, confidence là số thực hữu hạn, reason ngắn, evidence chỉ tham chiếu ID có thật. Output luôn `proposal_only`; confidence thấp cần review. Không biến phân loại AI thành permission, không tự triển khai JEV ở mọi bước. Chưa có benchmark hoặc nối JEV vào routing tự động.

Ví dụ shape (thay timestamps/số liệu bằng evidence mới trước khi dùng):

```json
{
  "workload": {"complexity": 1, "risk": "low", "allowed_providers": ["codex"]},
  "candidates": [{
    "id": "small", "provider": "codex", "model": "gpt-6-luna",
    "tier": 1, "cost_rank": 1, "capability_verified": true, "auth_mode": "subscription",
    "quota": {
      "observed_at": "2026-10-09T00:00:00+00:00", "expires_at": "2026-10-09T00:05:00+00:00",
      "source": "operator-provided example, not actual account usage",
      "windows": [{"name": "weekly", "remaining": 50, "reserved": 2,
        "keep_for_chat": 10, "estimated_call": 1, "resets_at": "2026-10-12T00:00:00+00:00"}]
    }
  }]
}
```

Sáu test của recommendation kiểm risk/complexity floor, nhiều quota windows, unknown/stale/reserve, quyền/capability/API, kiểu dữ liệu strict và AI không tự tạo authority/evidence. [Account reservation](account-reservations.vi.md) đã nối optional binding vào Control và dedup attempt usage; [feed Codex](quota-feed.vi.md) đọc được subscription. Recommendation vẫn không tự dispatch. Authoritative cumulative settlement, calibrated auto-routing/fallback và feed Claude/Kiro còn thiếu để hoàn thành OC10.

## Bổ sung cần triển khai: hiệu chỉnh từ lịch sử

[Kiến trúc mục 9.1–9.3](architecture.vi.md) và LR01–LR05 trong [SPEC-006](../specs/SPEC-006-portable-orchestration.md) quy định hồ sơ quyết định/kết quả, knowledge project, lessons có evidence, đánh giá sau task và benchmark/promotion/rollback policy. T31–T35 trong backlog là các ca nghiệm thu dự kiến.

Model thực chạy hiện vẫn do profile hoặc lệnh switch explicit quyết định. Chưa tự sinh tier/cost_rank từ lịch sử; chưa có kho lessons được router sử dụng. Test bộ chọn chỉ chứng minh tuân thủ rule, chưa chứng minh rule tối ưu. Hiệu quả phải đo trên cùng loại task/cấu hình bằng tổng chi phí tới kết quả đạt, kể cả sửa lỗi/review và can thiệp; dữ liệu thiếu không coi là miễn phí. Bài học AI đề xuất chưa là fact, và một lần thành công chưa đủ thay policy. JEV vẫn chưa nằm trong đường dispatch.
