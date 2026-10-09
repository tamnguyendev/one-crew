# Chọn model từ công việc và quota

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

Sáu test kiểm risk/complexity floor, nhiều quota windows, unknown/stale/reserve, quyền/capability/API, kiểu dữ liệu strict và AI không tự tạo authority/evidence. Atomic root-call reservation vẫn thuộc Control; phối hợp atomic quota reservation + usage feed/fallback còn thiếu để hoàn thành OC10.
