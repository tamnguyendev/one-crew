# Recipe native_change cho Node/TypeScript (toolchain "node")

Ngày 10/10/2026 (SOL-22fcd61f, entry tự duyệt theo uỷ quyền qua đêm của người dùng; xem `vm-agent/bao-cao/onecrew-approvals-2026-10-10.md`).

## Recipe làm gì
Recipe dùng chung luồng `native_change` với Flutter, gồm các bước work → verify → review → apply.
- Worker Claude chỉ đọc snapshot và trả về file đầy đủ.
- Runtime dựng một workspace kiểm chứng riêng, gồm snapshot, candidate và các file chỉ có ở máy cục bộ. File cục bộ không bao giờ vào prompt.
- `node_modules` đã cài của project được gắn vào bằng junction và gỡ ngay sau khi chạy xong.
- Runtime chạy ba bước cố định bằng `node.exe`:
  1. `tsc --noEmit -p .`
  2. `vitest run --reporter=json --no-cache <test owned + regression_tests>`
  3. `node <build_script>`

Kết quả chỉ **đạt** khi đủ cả các điều kiện sau:
- cả ba bước exit 0;
- Vitest báo > 0 test, 0 fail, và mỗi test owned có ít nhất một assertion passed;
- có `dist/manifest.json`;
- `node_modules/.package-lock.json` không đổi.

Khi không đạt, feedback gửi worker liệt kê từng assertion fail kèm vài dòng đầu của thông báo lỗi.

Các phần dùng chung nằm ở `onecrew/node_toolchain.py` để các stage của delivery root dùng lại: gắn/gỡ `node_modules`, hash lock, tóm tắt Vitest/E2E, `run_fixed` (chạy tuần tự các bước argv cố định, có giới hạn thời gian/output) và `classify_output`.

## Ví dụ (đã chạy thật: TASK-443d73868fef49f3aee0f96d398f51c6)
```json
{"toolchain":"node","source_roots":["extension","shared"],"package":"extension",
 "owned":["extension/src/content-floating/index.ts","extension/manifest.json","extension/test/panel-layout.test.ts"],
 "tests":["extension/test/panel-layout.test.ts"],
 "regression_tests":["extension/test/floating-chat-ui.test.ts","extension/test/panel-floating-shell.test.ts"],
 "extra_sources":{},"node_exe":"C:/Program Files/nodejs/node.exe","build_script":"scripts/build-demo.mjs",
 "reference":"<SOL đã duyệt>","trusted_native":true}
```
`job submit --mode change --native-change-config recipe.json --solution-id SOL-… --solution-revision … --start`

## Ràng buộc
- `owned` phải nằm trong `package` và có đuôi `.ts/.tsx/.mts/.cts/.js/.mjs/.cjs/.css/.html/.json`.
- Worker không được sở hữu các file sau, vì đây là cấu hình do operator giữ: `package.json`, lockfile, `.npmrc`, `tsconfig*.json`, `vite/vitest config`, và thư mục `dist`/`build`/`out`/`coverage`/`node_modules`.
- `tests` phải là file owned dưới `<package>/test/`.
- `regression_tests` chỉ đọc.
- `build_script` không được nằm trong owned.
- Không có `npm install`. Thiếu `typescript/vitest` trong `node_modules` thì task bị chặn vì môi trường, không mở vòng sửa bằng AI.
- File gốc dùng CRLF thì bản vá giữ CRLF. Diff gửi reviewer bỏ qua khác biệt CRLF/LF.
- Bản vá thiếu test bắt buộc hoặc thiếu thay đổi production thì thành một vòng sửa loại content (trần 2), không chặn cứng.
- Bước fail được `classify_output` xếp loại. Lỗi của máy chứ không phải của mã (`EADDRINUSE`, Chrome không khởi động, backend không sẵn sàng, thiếu `node_modules`/python, junction bị `EPERM`) là `environment`: task bị chặn với `recovery.kind=environment` (delivery root tự thử lại có giới hạn), không tốn vòng sửa product. Lỗi `error TS…`, esbuild `ERROR:`, assertion Vitest, dòng `FAIL` của E2E là `product` và vẫn thành vòng sửa. E2E không in dòng `N/M checks passed` là `runtime_bug`; trong job con nó vẫn là vòng sửa vì worker có thể sở hữu script E2E.

## Giới hạn (công bố)
Mô hình tin cậy giống recipe Flutter: đây là mã do project tự cung cấp và operator đã cho phép, chạy trong giới hạn thời gian, output và biến môi trường.
- Đây **không** phải sandbox OS.
- Không chặn mạng.
- Cho phép tiến trình con, vì esbuild cần.
- Không chứng minh hành vi trên trình duyệt thật hay hệ thống live. Probe Chrome nếu có là bằng chứng phụ do entry tự chạy.

## Dùng lại cho delivery Node (12/10/2026)
Hai module chỉ đọc, không chạy lệnh và không dùng mạng, phục vụ planner/stage của delivery kind `node_extension`:
- `onecrew/node_imports.py`: đồ thị import tĩnh của một package (import/export-from, `import()`, `require`, `vi.mock`; tsconfig `paths`/`baseUrl`, `./x.js` → `x.ts`, file index, bỏ hậu tố `?raw`). `affected_tests(package_dir, owned, test_globs)` trả về các file test import bắc cầu tới file owned, xếp theo khoảng cách import rồi theo đường dẫn, không gồm test owned. Job con lấy 30 file đầu làm `regression_tests`; root chạy toàn bộ. Có giới hạn số file, kích thước mỗi file và tổng dung lượng.
- `onecrew/delivery_env_node.py`: `discover(project, roots, env, envelope=None)` trả về `{facts, problems[{code, detail}], fingerprint}` cùng dạng với `delivery_env.discover`.
  - Script `package.json` được ánh xạ sang argv của `node.exe`: `node X` → `[node, X]`, `tsc` → `node_modules/typescript/bin/tsc`, `vitest` → `node_modules/vitest/vitest.mjs`, `a && b` → chuỗi bước. `npm`/`npx`/cú pháp shell thì không ánh xạ được.
  - Script E2E in dòng `N/M checks passed` được xếp `mock` hoặc `live`. `live` khi có profile bền (`NA_REAL_PROFILE`), dòng `ACTION:` hoặc đọc `harness/config.json`/URL thật.
  - Giá trị envelope đã ghim (`node_exe`, `CHROME_PATH`, `NA_PYTHON`) là ứng viên duy nhất; không âm thầm đổi sang bản khác.
  - Mã problem: `root_missing`, `package_missing`, `node_missing`, `node_modules_missing`, `typescript_missing`, `vitest_missing`, `lock_manifest_missing`, `build_script_unmappable`, `e2e_contract_missing`, `harness_sha_mismatch`, `chrome_missing`, `backend_venv_missing`.
  - `fingerprint` băm `node.exe`, tsc, `vitest.mjs`, script build/E2E và `node_modules/.package-lock.json`. Source, log và `dist` không làm đổi fingerprint.

## Kiểm chứng
- `tests/test_node_change.py` gồm 25 test, chạy `node.exe` thật với tsc/vitest/build giả lập. Các ca: đạt và apply, test fail kèm assertion trong feedback, test rỗng, lỗi kiểu, thiếu dist, thiếu dependency, `node_modules` bị đổi, quá thời gian và junction vẫn được gỡ, giữ CRLF, bản vá thiếu file.
- `tests/test_node_toolchain.py`: phân loại lỗi, `run_fixed`, các bản tóm tắt dùng chung, và job con bị chặn vì môi trường (cổng bận, backend không lên) mà không tốn vòng sửa.
- `tests/test_node_imports.py` và `tests/test_delivery_env_node.py`: project giả trong thư mục tạm, cộng một test chỉ đọc trên project linh-thuoc thật (bỏ qua nếu không có).
- Hồi quy `test_native_change`, `test_native_audit`, `test_owned`, `test_native_review_context`: 72 ok.
- Lần chạy thật trên linh-thuoc lộ ra ba lỗi; mỗi lỗi đều đã sửa và task chạy tiếp được:
  - feedback không có assertion: `e184895`;
  - bản vá thiếu file bị chặn cứng: `e184895`;
  - diff thô bị phình vì CRLF: `6436aed`.
