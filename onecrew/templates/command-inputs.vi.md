# Mẫu hợp đồng kiểm theo phần thay đổi

Ví dụ này dành cho dự án có gói `catalog` và thư mục `tests` có `__init__.py`. Mốc đầu kiểm phần tìm kiếm. Mốc giao chạy toàn bộ bài thử. Điền lời giao việc của chủ, tên gói, tên test và đường dẫn tuyệt đối trên máy trước khi chạy `plan lint`.

```json
{
  "schema_version": 2, "title": "Tìm sách theo tên", "size": "S",
  "origin": {"by": "owner", "at": "<ngày giao>", "quote": "<lời chủ>"},
  "presentation": {
    "request": "Tìm một cuốn sách bằng tên.",
    "user_sees": ["Gõ tên và thấy các sách khớp."],
    "acceptance_steps": ["Tìm một tên đã có và một tên chưa có."],
    "not_doing": "Giữ nguyên cách thêm sách."
  },
  "understanding": {
    "restated_goal": "Tìm sách theo tên và kiểm lại các chức năng của danh mục.",
    "target": {"repo": ".", "ref": "HEAD", "paths": ["catalog", "tests"]},
    "assumptions": [], "confidence": "high", "unknowns": []
  },
  "preconditions": [{"id": "P1", "check": "ref_resolves", "args": {"repo": ".", "ref": "HEAD"}, "why": "Có bản gốc để so."}],
  "output": ["Danh sách sách khớp tên", "Bản giao qua bộ thử của danh mục"],
  "scope": {"owned": ["catalog/**", "tests/**"]}, "non_goals": ["Đổi cách thêm sách"],
  "items": [
    {"id": "I1", "title": "Tìm theo tên", "tier": "must", "milestone": "M1", "source": "origin"},
    {"id": "I2", "title": "Kiểm bản giao", "tier": "must", "milestone": "M2", "source": "origin"}
  ],
  "milestones": [
    {"id": "M1", "title": "Kiểm tìm kiếm", "covers": ["O1"], "verifier": {"type": "command", "config": {
      "argv": ["python", "-I", "D:/checks/verify.py", "tests.test_search"],
      "inputs": ["catalog", "tests/__init__.py", "tests/test_search.py"],
      "env_inputs": ["D:/checks/verify.py"]
    }}},
    {"id": "M2", "title": "Kiểm toàn bộ danh mục", "covers": ["O2"], "verifier": {"type": "command", "config": {
      "argv": ["python", "-I", "D:/checks/verify.py", "--all"],
      "env_inputs": ["D:/checks/verify.py"]
    }}}
  ],
  "budget": {"max_calls": 20, "time": 60}, "attention": {"questions": 1}, "profile_version": null
}
```

Lưu đoạn dưới thành `verify.py` ở vị trí đã khai trong `env_inputs`. Thay cả bốn đường dẫn tới script bằng vị trí trên máy và chọn trình thông dịch đã cài. Bộ kiểm in từng ca và trả mã lỗi nếu có ca trượt, bị bỏ qua hoặc không tìm thấy ca nào.

```python
import os
import sys
import unittest

sys.path.insert(0, os.getcwd())
loader = unittest.defaultTestLoader
if sys.argv[1:] == ["--all"]:
    suite = loader.discover("tests", top_level_dir=".")
elif sys.argv[1:]:
    suite = loader.loadTestsFromNames(sys.argv[1:])
else:
    sys.exit("Supply test modules or --all")
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.testsRun and result.wasSuccessful() and not result.skipped else 1)
```

Ở M1, khai thêm fixture, module hỗ trợ và mọi gói mà test import. Nếu bộ kiểm đọc dữ liệu nền ngoài repo, thêm đường dẫn đó vào `env_inputs`. Mỗi lần sửa cần có ca hồi quy trong các module mốc thực sự chạy. Với sản phẩm giao bằng wheel, dành bước dựng và cài sạch cho mốc giao, rồi chạy mọi test mới và các module chịu ảnh hưởng trên bản cài.
