# OneCrew: bằng chứng task thật

Đây là đọc ledger, không chạy lại test hoặc xác minh artifact/thiết bị.
**Tỷ lệ tự hoàn thành độc lập: chưa đo được.**

| Task | Trạng thái | Calls | Hỗ trợ | Chưa có bằng chứng OneCrew tự làm |
|---|---|---:|---|---|
| TASK-8c1aa25368cc4b119b9275803cc3c986 | completed | 2 | unknown | build, device, notification |
| TASK-b9a0c151d7274e97b5515f8318ad44e2 | completed | 5 | entry-runtime-repair | build, device |
| TASK-726bd48fdcdf4f4e85d0b17c5d74d0e5 | completed | 3 | entry-device-or-server-verification, entry-runtime-repair | device |
| TASK-1e6d37de0e9a475b9758191c74b98833 | completed | 3 | unknown | build, device |

- Recorded evidence only; no tests/build/device rerun and no artifact revalidation.
- Explicit task sample, not a random population; no causal before/after inference.
- Unknown assistance is not zero. Missing/skipped test counts cannot imply full coverage.
- Entry device/server evidence is assistance, not autonomous worker E2E.
- No report text/credentials exported. Windows shown is not user attention.
- No prospective held-out eval enrollment: unassisted rate remains null.
