# Hồ sơ phát hành OneCrew 2.5.0.dev10+sol6.4, 06/11/2026

Đã phát hành dưới nhãn beta thử có giám sát: <https://github.com/tamnguyendev/one-crew/releases/tag/v2.5.0.dev10-sol6.4-beta>. Đây là prerelease, không phải latest; chưa nghiệm thu thật.

| Mục | Giá trị |
|---|---|
| Tag | `v2.5.0.dev10-sol6.4-beta` (annotated `cfa907d`) → code đã review `16b47d7453aa5a59d7a9986c737d4e579b4d7ef9` |
| Commit chỉ sửa test | `c0404506d6989d1094f470ea8fde881eb62859ed` |
| Hồ sơ đã review | `af7a2665fd1b58b3f996dc2687edc6022f8b5932` |
| Hướng dẫn trong gói | `fdc04e9d25b4f3b25e91cf455ba1ea21cd647188` |
| Nhánh trên remote | `claude/sol6-close-s5`, tạo mới; không force, không merge vào nhánh khác |
| Wheel | `onecrew-2.5.0.dev10+sol6.4-py3-none-any.whl`, SHA256 `4f25c3991dc503aaa61ab31573fa99e948670b66e591e0e2bf68dbecd024a64f`; đúng byte của gói đóng băng `final4`, không dựng lại |
| Gói | `onecrew-2.5.0.dev10-sol6.4-beta.zip`, SHA256 `e105203efef9fce2d8fc4d04162e77cf1b26ec41b26d2b23f97ee8efd21fe48e`, 20 file; `SHA256SUMS` bên trong phủ 19 file còn lại, gồm hướng dẫn và script |
| Checksum | `SHA256SUMS-release.txt`, SHA256 `6661a9bf4308857bb72469e774406e483e7bc6a222dac69a723e7d319a0e9ce0` |

## Đã kiểm khi phát hành

Chỉ kiểm tính toàn vẹn, khả năng phân phối và lệnh hướng dẫn; không chạy lại hồi quy vì code và wheel không đổi.

- **Quét trước khi push,** 49 commit mới so với tag `v2.5.0.dev10` và toàn bộ gói: 0 key, 0 tên người dùng, email hay máy trong nội dung, 0 file sổ hay log. Định danh commit vẫn là `NUC@DESKTOP-7IJQ3JC`, như các commit đã có trên remote. Đường dẫn còn lại chỉ là thư mục lab.
- **Diễn tập hướng dẫn:** 57/57 trên gói dựng thử, 57/57 trên file tải từ bản nháp. Lượt đầu 47/57 có hai nguyên nhân: profile PowerShell của lab làm hỏng ký tự pipe vào `init`, và hướng dẫn dùng `--author` không phải mã model (đã sửa hướng dẫn).
- **Tải lại:** bản nháp và bản đã công bố đều khớp từng byte với file đã dựng. Không đăng nhập, lệnh tải trong hướng dẫn qua URL công khai cho `DAT`; `kiem-goi.ps1` đạt 19 file; wheel đúng SHA256.
- **Bằng chứng Codex:** hai file `read-fault-result.json` trong gói đúng byte với bản gốc.
- **Remote:** tag trỏ đúng code đã review; tag `v2.5.0.dev10` không đổi.

## Không làm

Không nâng runtime, không đổi hook, sổ đăng ký hay sổ thật; không đụng SignSDK hay MEP. Sổ đăng ký, hook và config SignSDK giữ đúng hash. Gói `final3`, `final4` khớp `SHA256SUMS` của chúng.

Điểm vào duy nhất cho người dùng: [Bắt đầu sử dụng](BAT-DAU-SU-DUNG.vi.md).
