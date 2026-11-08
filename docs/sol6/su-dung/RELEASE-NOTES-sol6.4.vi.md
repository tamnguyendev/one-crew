# OneCrew 2.5.0.dev10+sol6.4 — beta thử có giám sát

**Đây là bản prerelease để thử có giám sát, chưa phải stable.** Bắt đầu tại [Bắt đầu sử dụng](BAT-DAU-SU-DUNG.vi.md): một trang cho tải, kiểm, cài, thử, nâng cấp, quay về và gửi góp ý.

| Mục | Giá trị |
|---|---|
| Version | `2.5.0.dev10+sol6.4` |
| Tag | `v2.5.0.dev10-sol6.4-beta` → code đã review `16b47d7453aa5a59d7a9986c737d4e579b4d7ef9` |
| Commit chỉ sửa test | `c0404506d6989d1094f470ea8fde881eb62859ed` (không đổi sản phẩm) |
| Hồ sơ đã review | `af7a2665fd1b58b3f996dc2687edc6022f8b5932` |
| Wheel | `onecrew-2.5.0.dev10+sol6.4-py3-none-any.whl`, SHA256 `4f25c3991dc503aaa61ab31573fa99e948670b66e591e0e2bf68dbecd024a64f` |
| Tải về | `onecrew-2.5.0.dev10-sol6.4-beta.zip` và `SHA256SUMS-release.txt`. Wheel nằm trong zip, đúng byte đã review: GitHub đổi ký tự `+` trong tên file đính kèm, mà pip cần đúng tên wheel |

## Sửa gì và được gì

So với `v2.5.0.dev10`, bản này gồm phần review chu kỳ 2 đã tích hợp trước đó và các đợt sửa quy trình làm việc. Lợi ích chính nằm ở root engine sau khi verdict cuối đỏ:

- **Không còn kẹt khi sửa nhiều vòng.** Nhiều finding cùng mở, sửa trượt rồi sửa tiếp, sửa mốc này làm đỏ mốc kia đều đi tiếp được tới nghiệm thu. Lặp lệnh sửa khi chưa có lỗi mới thì không tăng generation.
- **Mỗi trạng thái dẫn tới lệnh chạy được, hoặc một trạng thái dừng có lý do.** Replan chạy được; sau replan vẫn đỏ thì dừng rõ, không lặp. Câu hỏi cho chủ chỉ nêu lựa chọn làm được; `continue` không tự cấp Q5.
- **Đỡ tốn lần chạy.** Root nhiều node ghi chỉ chạy lại phần chịu ảnh hưởng và báo đủ chi phí trước khi đổi gì.
- **Trang theo dõi nhẹ lại.** Track, digest, list không băm cây nữa: `track show` trên project 5.000 file về khoảng 1 giây.
- **Lệnh đọc không ghi vào project.** `plan show`, báo cáo, `verdict diff` và hướng dẫn `engine.next_action` tính mã cây bằng kho object tạm.
- **Hết hạn, thiếu call, root cũ:** hướng dẫn nói đúng đường được hỗ trợ; root `plan:` cũ không báo lỗi sau verdict xanh; nghiệm thu từ terminal khác và sau hạn vẫn đạt khi đủ bằng chứng.

## Thay đổi hành vi cần biết

- **Lệnh đọc có thể dừng với lỗi.** Khi không lập được kho object tạm, `plan show`, `plan report`, `plan present`, `verdict diff` trả lỗi rõ, mã 2. `engine.next_action` trả `inspect/blocked`. Bản trước vẫn trả kết quả, có ca báo đạt mà không kiểm cây.
- **Repo thật sự hỏng** (`.git` trỏ sai) nay làm các lệnh đó báo lỗi, không in báo cáo như trước.
- **Trạng thái "đã dừng"** tách khỏi "bị chặn" trên CLI, trang theo dõi và digest; root đã dừng vẫn nằm trong danh sách việc mở.
- **Hết hạn mà thiếu bằng chứng thì dừng hẳn.** Không có lệnh gia hạn; hạn và số call được niêm phong từ lần duyệt đầu.

## Bằng chứng

**Codex kiểm độc lập trên wheel này:**

- 145/145 file wheel khớp commit và bản cài.
- Đọc bình thường: không ghi object vào project.
- Timeout hoặc mã lỗi khi tìm kho object: dừng rõ, không ghi object.
- Baseline Sol6.3 vẫn tái hiện việc ghi 2 object.

Kết quả gốc của Codex nằm nguyên byte trong `evidence/codex/` của gói.

**Người dựng tự kiểm trên wheel này. Không có lượt nào xanh hoàn toàn, và hai lượt không cộng thành một:**

| Lượt | Phạm vi | Passed | Failures | Errors | Skipped |
|---|---|---|---|---|---|
| 1 | 30 nhóm chịu ảnh hưởng | 395 | 0 | 1 | 0 |
| 2 | 4 module | 65 | 1 | 0 | 0 |

- **Error ở lượt 1 là lỗi mock của bộ kiểm:** test giả lập `subprocess.run` trên toàn tiến trình nên vướng bước mới. Sau khi sửa harness, `test_v2_report` chạy lại đạt 25/25 ở lượt 2; assertion giữ nguyên.
- **Failure ở lượt 2** là test đòi môi trường checkout (`test_v24_s1_bundle…test_version_hash_unknown_when_not_installed`), đỏ cả trên baseline khi chạy từ wheel. Không sửa test này.
- **Ngoài ra:** smoke 38/38 (fixture), 21/21 điều kiện đối chiếu. Trên 45 lần đọc có lỗi tiêm, Sol6.3 ghi object 35 lần và báo thành công 43 lần; bản này ghi 0 lần và dừng rõ cả 45.
- **Không chạy toàn gate.** Con số 727 test thuộc wheel Sol6.3, không tính cho wheel này.

**Sự cố bằng chứng.** Trong lúc tự kiểm, một lượt chạy của người dựng đã ghi đè file kết quả baseline trước đó của Codex (`codex-review-20261106-c/read-fault-result.json`), vì lệnh đổi đường dẫn trong bản copy probe không có tác dụng. File được khôi phục từ log gốc và đã ghi rõ trong hồ sơ. Sau đó Codex chạy đối chứng độc lập mới, đặt ở thư mục mới; đó là kết quả đính kèm trong gói, không phải file đã khôi phục.

## Giới hạn beta

- **Chưa chứng minh:** provider hay model thật, hook trong phiên Claude Code thật, terminal thật của chủ, repo cỡ MEP (108.897 file). Worker trong lab là tiến trình cục bộ; chủ là fixture.
- `plan show` và `engine.next_action` vẫn băm cây 1 lần mỗi lần gọi, như Sol4, nên chậm trên repo lớn.
- Trạng thái dừng trên trang web mới kiểm bằng test và cú pháp JS, chưa kiểm bằng trình duyệt.
- Lỗi kho tạm được tiêm ở bước xác định kho; ca thật không tiêm chỉ có `.git` trỏ sai.
- Việc phát triển bản này không có hợp đồng v2 và OneCrew không giám sát.
- Đã biết, chưa sửa: root engine có mốc `owner-manual` không tới được handoff; `engine replan` thiếu tham số trả `TypeError` dạng JSON.
- Đã diễn tập hướng dẫn trong lab, gồm nâng từ 2.3.0.dev11 và 2.5.0.dev10. Nâng từ version khác, và quay về dữ liệu sau khi runtime mới đã ghi việc, thì chưa kiểm.

**Không repo thật nào được nâng trong lần phát hành này:** runtime, hook, sổ đăng ký và sổ thật của SignSDK, MEP giữ nguyên.

## Góp ý

Xem mục 8 của [Bắt đầu sử dụng](BAT-DAU-SU-DUNG.vi.md#8-gửi-góp-ý).
