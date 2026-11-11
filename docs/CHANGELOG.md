# CHANGELOG

## v2.5.0.dev24 (10/11/2026) — gộp dòng verifier MEP (mep2…mep7) vào 2.5; chủ: "Gộp MEP rồi gửi" — LOCAL, chưa tag/push/phát hành

- **Gộp** `claude/mep-field-fixes-0911` (`4836971`, chứa `claude/hotfix-verifier-inputs`):
  - `verifier.config.inputs` (bộ kiểm lệnh chỉ chép và chụp những gì nó khai);
  - `inputs_unscanned`;
  - dấu vân tay chương trình (`input_scope.tool`, gồm alias Windows);
  - job object trên Windows;
  - `verdict artifact` trả hợp các input;
  - trang theo dõi hiện "Mốc tiếp theo".
- **Mọi quyết định của 2.5 được giữ:** đúng byte git lưu, symlink là tệp thường, git 2.40, giờ sửa cố định, `checkout_policy` và mốc chính sách, `before_verifier` bắt `BaseException`, reviewer chuẩn bị trước khi ghi "đã khởi chạy", thẻ phần cho chủ.
- **Khớp nhau:**
  - receipt `inputs` cũng qua quy tắc chính sách chép;
  - đổi `inputs` hay `inputs_unscanned` là thay đổi nghiệm thu (#9);
  - lỗi trước khi lệnh chạy được đánh dấu "chưa chạy".
- **Vá hai lỗ của mep7:**
  - (a) với bộ kiểm lệnh, dọn và tạo thư mục tạm, kiểm thư mục, scope, hạn chót đều nằm trong `before_verifier`: lỗi ở đó mang dấu "chưa khởi chạy", run được đóng là chưa dispatch và chạy lại được không cần release-run. Marker `dispatched` vẫn ghi trước khi gọi bộ kiểm (như T08a): lỗi không mang dấu đó là kết quả không rõ và bị giữ;
  - (b) `tool_changed` tìm lại tên trần trên PATH và đọc lại đích của alias.
- **P1 review dev24 (Kiro), chủ 10/11: "Sửa ngay":** pass của `inputs` không còn được mang sang khi môi trường của chương trình đổi. Trình thông dịch Python được băm cùng các gói đã cài (dist-info/egg-info kèm `RECORD`, `.pth`, `pyvenv.cfg`); hợp đồng khai được `env_inputs` (1–20 đường tuyệt đối ngoài repo, tối đa 20 000 tệp / 512 MB), đổi nó là thay đổi nghiệm thu. Receipt chưa có dấu vân tay môi trường, hay môi trường không đọc được, không được mang sang. Test đỏ trên `e96e386`: `tests/test_dev24_p1_environment.py`.
- **Review lại `8172655` (Kiro, 2 P1 + 2 P2), chủ 10/11: "Sửa ngay":**
  - P1-a: tên trần như `python` được tìm một lần trên PATH của bộ kiểm và chạy bằng đúng đường tuyệt đối đó (Windows không tìm theo PATH của môi trường truyền cho tiến trình con); receipt băm đúng tệp đã chạy. Không tìm thấy: mốc có `inputs` bị từ chối trước khi lệnh chạy; mốc khác cho receipt `executable_not_found` như trước, không tìm theo PATH của OneCrew;
  - P1-b: `env_inputs` thiếu hay không đọc được thì lượt kiểm bị từ chối trước khi lệnh chạy, và pass không được mang sang lúc `plan show`/nghiệm thu;
  - P2: `env_inputs` nằm trong repo (sau khi giải `..`, hoa/thường, junction) hay chứa repo bị từ chối ở `plan propose`/`amend` và lúc chạy; hai tên cùng một chỗ bị từ chối;
  - P2: giới hạn 20 000 tệp / 512 MB đếm ngay lúc duyệt, áp cả cho môi trường Python; một `RECORD`/`.pth`/`pyvenv.cfg` tối đa 16 MB;
  - P3 (OneCrew bị tắt cứng giữa lúc đánh dấu và lúc chạy lệnh) ghi vào `LOI-DA-BIET.vi.md`.
  - Test đỏ trên `8172655`: `tests/test_dev24_p1b_review.py`.
- **Review vòng 3 trên `84ef359` (Kiro, 3 P1 + 8 P2 + 1 P3), chủ 11/11: "Sửa cả lỗi cũ":**
  - **mọi receipt của bộ kiểm lệnh** (có hay không có `inputs`) ghi chương trình đã chạy (`program`: đường khởi động, tệp thật sự chạy, sha256, gói Python) và `env_inputs` khi có khai; `plan show`, nghiệm thu và việc dùng lại bằng chứng (`proof_mismatch`) đều kiểm lại chúng bằng một quy tắc (`command.program_reasons`). Bộ kiểm bằng mô hình không thuộc quy tắc này;
  - cách chép lên `exact-blob-bytes/3`: pass làm trước bản này trên plan chưa nghiệm thu phải chạy lại một lần (mốc chính sách); plan đã nghiệm thu giữ nguyên;
  - liên kết: gói Python tìm từ đường khởi động (venv POSIX có `bin/python` là symlink); lúc kiểm lại, đường khởi động được giải lại, nên symlink tệp hay thư mục nay trỏ chỗ khác là "đổi";
  - chương trình không có thật (tên trần hay đường tuyệt đối) bị từ chối trước khi lệnh chạy, với mọi mốc;
  - PATH của bộ kiểm bỏ các thư mục trong repository chứa project (theo thành phần đường, không theo `cwd` của mốc, không theo tiền tố chữ);
  - tiến trình khởi động từ tệp tìm được (`executable=`) nhưng vẫn thấy `argv[0]` như hợp đồng viết; tên trần không bao giờ tìm trong thư mục hiện tại của OneCrew;
  - giới hạn đếm cả thư mục; việc dò site-packages cũng bị giới hạn; thêm/bớt thư mục con trong `env_inputs` là "đổi";
  - `env_inputs` dùng được không cần `inputs`; hai tên cùng một chỗ bị từ chối ở `propose`/`amend`; trong repo hay ngoài repo được xét theo repository chứa project, giống nhau ở `propose` và lúc chạy;
  - P2 liên kết lồng bên trong `env_inputs` và P3 tranh chấp giữa lúc băm và lúc chạy ghi vào `LOI-DA-BIET.vi.md`.
  - Test đỏ trên `84ef359`: `tests/test_dev24_p1c_review.py`.
- **Review toàn bộ trên `945afdc` (Kiro, 3 P1 + 3 P2 + 1 P3), chủ 11/11: "Sửa cả lỗi cũ":**
  - P1 (workflow): đã thử áp quy tắc chương trình cho kết quả kiểm node đã ghi, rồi **gỡ ra ở vòng 6** (chủ 11/11, phương án A): xem dòng vòng 6 dưới đây. Môi trường tra cứu chỉ dựng khi chương trình là tên trần (giữ);
  - P1: đường có `.`/`..` (dòng lệnh và nội dung input) được chuẩn hóa trước các bước chặn cây làm việc thật, kể cả đường chưa có;
  - P1: `inputs_unscanned` so tên đã chuẩn hóa (`./`, `..`, hoa/thường trên Windows); lúc chạy, các đường viết nguyên văn trên dòng lệnh luôn được quét (tệp mà công cụ kiểm chạy gián tiếp thì không: xem vòng 7);
  - P2: chương trình tương đối có thư mục mà bản chép không có bị từ chối trước khi lệnh chạy;
  - P2: trang theo dõi trình nghiệm thu plan có các mốc khai `inputs` khác nhau, trên cây hợp các input như `verdict artifact`;
  - P2: dấu vân tay tệp được nhớ theo (đường, kích thước, giờ sửa ns, mã tệp): một lượt cập nhật trang theo dõi đo được khoảng 0,2 giây thay vì 2,9 giây;
  - P3: các dòng mốc trên trang theo dõi dùng đúng view sống mà thẻ nghiệm thu đã tính.
  - Test đỏ trên `945afdc`: `tests/test_dev24_p1d_review.py`.
- **Review vòng 5 trên `1d29b43` (Kiro):** `inputs_unscanned` bằng, nằm dưới **hay nằm trên** một đường viết nguyên văn trên dòng lệnh (`pytest tool`, `pytest .`) bị hợp đồng từ chối và bị bỏ miễn lúc chạy. Các P2/P3 còn lại ghi vào `LOI-DA-BIET.vi.md` theo quy tắc dừng. Test đỏ trên `1d29b43`: `tests/test_dev24_p1e_review.py`.
- **Vòng 6, chủ 11/11 chọn phương án A ("ok, làm theo lời khuyên"):** gỡ quy tắc chương trình khỏi kết quả kiểm node **đã ghi** của plan workflow. `engine.py`, `common_handoff.py`, `incidents.py`, `common_verification.py` trở lại đúng từng byte như `945afdc`, nên `engine.state`, handoff và `next_action` chạy như 2.5.0.dev23 với các lần kiểm đã ghi. Giữ nguyên: quy tắc chương trình trên plan thường (`plan show`, nghiệm thu), xét lại proof khi **dùng lại** (`proof_mismatch`), mốc chính sách `exact-blob-bytes/3`, các sửa còn lại của vòng 4–5. Ghi lỗi đã biết vào `LOI-DA-BIET.vi.md`; sẽ sửa bằng một việc riêng, thiết kế trước. Test P1-1 trong `tests/test_dev24_p1d_review.py` nay khẳng định hành vi dev23.
- **Vòng 7 (Kiro trên `2b85352`), chủ 11/11 chọn A, chỉ sửa tài liệu:** `inputs_unscanned` không bảo vệ tệp mà công cụ kiểm chạy hay đọc gián tiếp (selector `file::test`, `@argfile`, cấu hình tự tìm, `addopts`, mẫu `*`, `pytest` không kèm đường): ghi thành **P1 đã biết** với quy tắc cho chủ (chỉ miễn tệp dữ liệu). Hướng dẫn chỉ hứa quét các đường viết nguyên văn trên dòng lệnh. Ghi thêm hai lỗi đã biết: thẻ sửa hợp đồng ghi "chỉ đổi lời hay thêm kiểm" khi thêm một mốc ở cuối hay một tiêu chí reviewer (P2); và lỗi có từ dev22: sau khi nâng OneCrew, bước đã đạt của luồng nhiều bước bị "cần kiểm lại" mà chế độ tự chạy không kiểm lại (P2). `NANG-RUNTIME.vi.md` mục C0 ghi lỗi sau cho việc nâng cấp.
- **Hướng dẫn** `docs/mep-hotfix/HUONG-DAN-inputs.vi.md` có mục «Trên 2.5»: mọi mốc lệnh ghi chương trình, cách tìm và chạy chương trình, gói Python, `env_inputs`, giới hạn, hệ quả khi nâng, phần còn chưa phủ. `NANG-RUNTIME.vi.md` mục C0 ghi hệ quả khi nâng.

## v2.5.0.dev23 (10/11/2026) — review dev21+dev22 `b015155` (Kiro, có P1) — LOCAL, chưa tag/push/phát hành

Test đỏ trên `b015155`: `tests/test_dev23_review_fixes.py`.
- **P1:** nghiệm thu nội bộ một node (`node.accepted`) trước mốc chính sách, ở plan chưa nghiệm thu, không còn tính. Node đó "cần kiểm lại", ở trạng thái `produced`, nên `engine verify` kiểm lại được.
- **P1:** handoff có trước mốc không còn là bằng chứng. `root_ready` từ chối nó, và handoff chạy lại thay vì trả kết quả cũ.
- **P2:**
  - mốc được ghi cả ở `plan propose` và các đường hồi phục (`publish_retained`, `adopt_managed`, `release_paused`, đầu `run_batch`);
  - `plan show` qua CLI không còn ghi sổ;
  - bản chép của work mode dừng hẳn khi `git update-index --refresh` hay `git status` lỗi hoặc báo bẩn;
  - reconcile verdict top-level không ghi receipt của chính sách chép khác.
- **Lỗi đã biết** (chủ quyết không sửa trong 2.5, ghi ở `docs/obs2/su-dung/LOI-DA-BIET.vi.md`):
  - receipt legacy không có sự kiện cấp phát thì được tính theo seq lúc ghi nhận; chỉ xảy ra khi hai runtime cùng ghi một sổ;
  - observation của investigation không khóa chính sách chép (không cấp quyền).

## v2.5.0.dev22 (10/11/2026) — trả lời review dev20 theo quyết định của chủ ("Đồng ý cả 3", 10/11) — LOCAL, chưa tag/push/phát hành

Test đỏ trên `9d23ed4`: `tests/test_dev22_review_fixes.py`.
- **A-lite, mốc chính sách:**
  - lần ghi đầu tiên của runtime vào một plan ghi sự kiện `checkout.policy_epoch` cho chính sách chép hiện hành (lớp A; mỗi giá trị mới một mốc; lệnh chỉ đọc không ghi);
  - với plan chưa nghiệm thu, bằng chứng có trước mốc không tính: verdict top-level theo seq của `verdict.receipt_issued`, kết quả node theo seq của `node.verification`;
  - các chỗ chặn: `plan.accept`, `engine.accept_node`, handoff, `root_ready`, `eligible` (qua `engine.state`);
  - `plan show` và trang theo dõi ghi "cần kiểm lại"; plan đã nghiệm thu giữ nguyên;
  - runbook nâng cấp (`NANG-RUNTIME.vi.md` C0) ghi: còn plan mở thì phải chạy lại verdict.
- **(B) Chế độ work:** `work_tools.checkout_candidate` dùng lõi exact-bytes (`command.exact_bytes`): không attributes, không filter, không cấu hình máy, symlink là tệp thường, giờ sửa cố định, từ chối git dưới 2.40. Cấu hình riêng và `info/attributes` của repo kiểm giữ cho `git status` sạch.

## v2.5.0.dev21 (10/11/2026) — review lại dev20 `c0d62b3` (Kiro, FAIL): phần không cần chủ quyết — LOCAL, chưa tag/push/phát hành

Test đỏ trên `c0d62b3`: `tests/test_dev21_review_fixes.py`.
- **Issue #4:** mọi tệp và thư mục trong bản chép mang một giờ sửa cố định (01/01/2000 00:00 UTC). Chính sách chép lên `exact-blob-bytes/2`, nên receipt của chính sách trước thành stale. Hướng dẫn ghi rõ.
- **Issue #2:** reviewer Codex và Kiro tìm CLI trước khi ghi "đã khởi chạy", như Claude; thiếu CLI là chưa chạy, không tính lượt, ở cả đường có ngân sách root lẫn đường cũ.
- **Test qua caller thật:** quy tắc chính sách được kiểm qua bộ kiểm candidate (`prior_pass` rồi `_reused_row`).

## v2.5.0.dev20 (10/11/2026) — review lại dev19 `45ccc76` (Kiro, FAIL) — LOCAL, chưa tag/push/phát hành

Test đỏ trên `45ccc76`: `tests/test_dev20_review_fixes.py`.
- **Issue #4, chặn ở một chỗ chung** (phiên điều phối: "đừng vá từng đường nữa"):
  - mọi receipt bộ kiểm ghi ra đều mang `checkout_policy`: lệnh, reviewer, dữ liệu/tài liệu/vận hành, receipt của node;
  - một quy tắc duy nhất, `command.policy_current`, được áp ở mọi chỗ dùng lại hay publish: `proof_mismatch` (candidate `_reuse`, `_reused_row`, `verdict._reuse_candidate_pass`), `_reuse` trên receipt node, `publish_issued`, `receipt_assessment`;
  - reviewer không còn được miễn: định danh yêu cầu và ràng buộc bằng chứng của mọi loại verifier mang `checkout_policy`.
- **Issue #2:**
  - Claude CLI và credential được quyết một lần (`reviewer.prepare`), lời gọi chạy đúng cái đã tìm;
  - reviewer cũ (không có ngân sách root) chuẩn bị trong `before_verifier`, nên thiếu CLI là chưa chạy, run không bị giữ.

## v2.5.0.dev19 (10/11/2026) — review lại dev18 `ad6b59e` (Kiro, FAIL) — LOCAL, chưa tag/push/phát hành

3 test đỏ trên `ad6b59e` (`tests/test_dev19_review_fixes.py`).
- **Issue #4:**
  - ràng buộc bằng chứng và định danh yêu cầu của bộ kiểm candidate (`CandidateChecker`), cùng định danh yêu cầu của milestone (`review_dispatch`), nay mang `checkout_policy`: receipt candidate theo cách chép cũ không được dùng lại;
  - `materialized_tree` khởi tạo repo theo đúng định dạng đối tượng của dự án (SHA-256 cũng chạy được).
- **Issue #2:** reviewer có ngân sách tìm Claude CLI trước khi ghi "đã khởi chạy"; máy không có CLI thì chốt "không bắt đầu", không tính lượt.

## v2.5.0.dev18 (10/11/2026) — review lại dev17 `b77966e` (Kiro, FAIL) — LOCAL, chưa tag/push/phát hành

5 test đỏ trên `b77966e` (`tests/test_dev18_review_fixes.py`).
- **Issue #9:** thẻ duyệt so bản sửa với bản **đã duyệt** gần nhất, không phải bản ngay trước. Sự kiện `plan.amended` ghi `compared_with`.
- **Issue #4:**
  - receipt tạo theo cách chép cũ thành stale ("checker configuration changed"): ràng buộc bằng chứng của verifier lệnh và dữ liệu/tài liệu nay mang `checkout_policy`;
  - bước dựng lại candidate (`materialized_tree`) chạy git dưới cùng cách cô lập với bản chép: không attributes, không filter, không cấu hình máy, symlink là tệp thường.
- **Issue #2:**
  - reviewer `auth api` thiếu key dưới ngân sách root không bị tính lượt gọi (chốt "không bắt đầu" trước khi ghi "đã khởi chạy");
  - Ctrl+C sau khi ghi "đã khởi chạy" mà trước lời gọi model được chốt, không để "chưa rõ kết quả". Lượt gọi vẫn bị tính theo quy tắc của Control: một lượt đã khởi chạy không bao giờ được hoàn.

## v2.5.0.dev17 (09/11/2026) — review lại dev16 `5d7c289` (Kiro, FAIL); chủ: "Đồng ý" kiểm trên đúng nội dung git — LOCAL, chưa tag/push/phát hành

Test đỏ trên `5d7c289`/`293db4a`: `tests/test_dev17_review_fixes.py`.
- **Issue #9:** milestone mới chỉ là "thêm bước kiểm" khi nằm sau mọi milestone cũ; chèn trước một milestone đã duyệt là thay đổi nghiệm thu.
- **Issue #2:** reviewer có ngân sách: mọi bước trước khi gọi model mang `verifier_started=False`. Hạn chót được kiểm trước khi ghi "đã khởi chạy", nên khi hết hạn thì lượt gọi được chốt không bắt đầu, không tính lượt.
- **Issue #4, chủ duyệt 09/11** ("bước kiểm chạy trên đúng nội dung đã khóa trong git, giống hệt trên mọi máy"):
  - bản chép giữ đúng byte của blob, không áp attributes nào, kể cả `.gitattributes` trong cây (`--attr-source` là cây rỗng);
  - symlink là tệp thường chứa đích, trên mọi hệ điều hành;
  - git cũ hơn 2.40 bị từ chối với lời báo rõ.
- **Hướng dẫn** (`BAT-DAU-SU-DUNG`) ghi hai hệ quả: tệp cần CRLF lúc chạy sẽ thấy LF; repo cần symlink thật phải bỏ symlink khỏi artifact.

## v2.5.0.dev16 (09/11/2026) — review lại dev15 `cecd9c5` (Kiro, FAIL) — LOCAL, chưa tag/push/phát hành

4 test đỏ trên `cecd9c5` (`tests/test_dev16_review_fixes.py`).
- **Issue #9:** đổi thứ tự milestone là thay đổi nghiệm thu (milestone chạy theo thứ tự danh sách).
- **Issue #2:** ngân sách chung của root từ chối reviewer trước khi gọi model nay ghi `verifier_started=False`. Ctrl+C trước khi gọi bộ kiểm cũng được đánh dấu, và vẫn là một lần ngắt.
- **Issue #4:** bản chép không đọc cấu hình git toàn cục hay hệ thống, nên `filter.<tên>.smudge` (như Git LFS) không đổi byte. Trên Windows, `core.longpaths=true` và `core.symlinks=false` được đặt cố định.

## v2.5.0.dev15 (09/11/2026) — review lại dev14 `3662b47` (Kiro, FAIL) — LOCAL, chưa tag/push/phát hành

Mỗi mục có test đỏ trên `3662b47` (`tests/test_dev15_review_fixes.py`).
- **Issue #9, tiêu chí reviewer:** chỉ đổi khoảng trắng mới là "routine". Đổi bất kỳ ký tự nào khác (dấu câu, chữ hoa thường, chữ trong ngoặc như `"safe-mode"` thành `"safe mode"`), đổi thứ tự tiêu chí, hay một mã tiêu chí lặp lại đều là thay đổi nghiệm thu, cần chủ duyệt. Tiêu chí được thêm vẫn là "routine".
- **Issue #2, các chỗ còn sót:** đọc `ONECREW_SNAPSHOT_MINUTES` sai; verifier dữ liệu/tài liệu trước khi gọi adapter (hạn chót, ràng buộc bằng chứng, chuẩn bị); reviewer trước khi gọi model (kiểm thư mục, môi trường, ràng buộc bằng chứng, thư mục tạm). Tất cả nay mang dấu `verifier_started=False`.
- **Issue #4, nguồn attributes ngoài cây:** bản chép chạy với một thư mục git rỗng của riêng nó (đối tượng vẫn của repo), `core.attributesFile` trỏ vào tệp rỗng, tắt attributes hệ thống. `.git/info/attributes`, `core.attributesFile` của repo hay của người dùng không còn đổi byte. `.gitattributes` trong cây vẫn áp.
- **Lời thường:** `docs/` (thư mục có `/` cuối), cờ ngắn `-v`, tên file có đuôi bất kỳ (`report.pdf`) nay là cảnh báo, không chặn.
- **Cảnh báo hiện lại** khi `--reuse-existing` và khi duyệt lặp.

## v2.5.0.dev14 (09/11/2026) — review lại dev13 `698e118` (Kiro, FAIL); chủ: "Đồng ý" lọc hai mức — LOCAL, chưa tag/push/phát hành

Mỗi mục có test đỏ trên `698e118` (`tests/test_dev13_review_fixes.py`).
- **Lọc lời thường hai mức.**
  - **Chặn** (`owner_view_technical`) chỉ chữ chắc chắn kỹ thuật:
    - đường dẫn Windows hoặc UNC, đường dẫn bắt đầu bằng `/ ./ ../ ~/`;
    - URL có scheme, tên file có đuôi đã biết;
    - `--cờ`, đoạn trong backtick, mã băm, tên lỗi hệ thống;
    - mã OneCrew trong ngữ cảnh rõ (`mốc M1`, `rev 2`, `v2.5`, `dev12`, `Sol6`).
  - **Cảnh báo** (`owner_view_maybe_technical`) cho chữ có thể kỹ thuật: `api/v2`, `src/app`, `Dockerfile`, `REQ-123`, `www.example.com`, `TEN_HANG`, mã trần như `U1`, `F7`. `plan lint` vẫn exit 0; `propose`/`amend`/`approve` trả kèm `warnings`; `owner approve --human` in "Cảnh báo (không chặn)".
  - **Câu y tế qua sạch:** mã ICD (`F32.1`, `I10`, `J18.9`, `T39`), liều (`5 mg/kg/ngày`, `1 mg/kg/24 giờ`), `vitamin D3/B12`, `phòng B12`, `SpO2 95%`, `120/80 mmHg`.
- **Thư viện `propose`/`amend`/`--reuse-existing`** từ chối mọi quy tắc trên chữ của hợp đồng mà approve áp, gồm cả "fail if".
- **`plan rules init` ghi owner-rules dưới khóa ghi của ledger,** nên file không thể xuất hiện giữa lần kiểm cuối của approve và lúc ghi duyệt.
- **Issue #9 (từ MEP; chủ: "Đưa vào"):** bộ phân loại của `plan amend` chuyển sang danh sách cho phép.
  - Mọi thay đổi của milestone, của verifier và cấu hình verifier, của phạm vi (`owned` hẹp lại hay nới rộng, khóa khác của `scope`) là thay đổi nghiệm thu, cần chủ duyệt.
  - Chỉ còn "routine": tiêu chí review được thêm hay chỉ đổi chữ, milestone được thêm, tiêu đề milestone.
  - Trước đây, verifier dữ liệu hay tài liệu bỏ đếm dòng hoặc mẫu, một khóa miễn kiểm mới, `auth` khác của reviewer, hay `owned` nới ra cả repo đều hiện là "chỉ đổi chữ".
- **Issue #2, phần áp cho 2.5:** mọi lỗi xảy ra trước khi gọi bộ kiểm (checkout git hỏng, `OSError`, `LedgerError` của môi trường, thiếu thư mục làm việc, không tạo được thư mục tạm, hạn chót) đều mang dấu `verifier_started=False`, ở verifier lệnh và verifier dữ liệu/tài liệu. Run vì thế không bị giữ "unknown outcome" và không cần `release-run`.
- **Issue #4:** bản chép mà bộ kiểm lệnh chạy trên đó không còn đổi kiểu xuống dòng theo `core.autocrlf`/`core.eol` của máy; byte khớp nội dung git lưu, `.gitattributes` vẫn được áp. Hướng dẫn ghi rõ giờ sửa tệp không được giữ.

## v2.5.0.dev13 (09/11/2026) — review lại dev12 `b0d3bdb` (Kiro, FAIL); chủ: "Sửa tiếp hết" — LOCAL, chưa tag/push/phát hành

Mỗi mục có test đỏ trên `b0d3bdb` (`tests/test_dev12b_review_fixes.py`).
- **Tiêu chí reviewer phải có "fail if" ở mọi đường** (trước là F3, ngoài phạm vi; nay sửa): lint, lệnh `plan propose`/`plan amend` và `approve` (thư viện, `plan approve`, `owner approve`) cùng từ chối `criterion_no_fail_clause`.
- **Plan đã duyệt theo quy tắc hiện hành:** duyệt lặp và `plan propose --reuse-existing` kiểm phần cho chủ (và "fail if") theo quy tắc hôm nay. Lời từ chối chỉ cách gỡ: `plan amend` thêm bốn câu rồi duyệt bản mới. Lần duyệt cũ vẫn được ghi giữ.
- **Thư viện `propose`/`amend`** từ chối phần cho chủ thiếu (khi có owner-rules) hoặc có chữ kỹ thuật, trước khi ghi gì.
- **Race khi owner-rules ra đời giữa lúc duyệt:** giao dịch ghi cuối của `approve` kiểm lại phần cho chủ và "fail if".
- **Nhận chữ kỹ thuật thiết kế lại:**
  - giữ lời thường: `A/B/C`, `Q1/Q2`, `vitamin B12`, `phòng B12`, `A4`, `online/offline`;
  - vẫn bắt mã nội bộ OneCrew theo tiền tố đã biết (`M1`, `R3`, `U1`, `F7`, `P2`, `dev12`, ...), trừ khi đứng sau từ chỉ chỗ hay nhóm (`phòng`, `tầng`, `nhóm`, ...);
  - bắt thêm `src/app`, URL viết hoa, hash viết hoa thường lẫn lộn.
- **Test bị kit-guard khóa:** 6 file chỉ thêm "fail if" vào câu hỏi tiêu chí trong dữ liệu test. U1 do chủ chạy một script.

## v2.5.0.dev12 (09/11/2026) — sửa các lỗi thật của review độc lập trên dev11 `1fba2a4` — LOCAL, chưa tag/push/phát hành

Review: Kiro CLI (gpt-5.6-sol), chỉ đọc, kết luận FAIL. Chủ duyệt sửa ngày 09/11. Mỗi lỗi có test đỏ trên `1fba2a4` trước khi sửa (`tests/test_dev12_review_fixes.py`).
- **`--revision 0` vượt cổng phần cho chủ:** `approve()` coi 0 là số bản, nên từ chối vì đó không phải bản mới nhất.
- **Cổng phần cho chủ ở mọi đường duyệt (chủ quyết 09/11: "Mở khóa test, bật hết"):** phần cho chủ nay là một lý do của step 0. Vì vậy `approve()` từ chối ở mọi đường gọi: thư viện, `plan approve`, `owner approve`. Lời từ chối gộp chung với các lý do step 0 khác, và kiểm trên đúng bản sẽ ghi, nên hết race với bản amend chen giữa. Hợp đồng chương trình mẫu (`wfkit/program_contract.py`) có phần cho chủ. Sửa test bị khóa: `tests/test_v2_advisor.py`, cần U1 của chủ (script chủ chạy); `tests/test_wf_program_transition.py` không phải sửa.
- **`plan propose --reuse-existing`:** không dùng lại plan đang chờ duyệt mà lint từ chối. Plan đã được duyệt ở đúng bản đó vẫn vào lại như cũ.
- **Nhận chữ kỹ thuật:** dấu `/` giữa lời thường (`10 km/h`, `mg/kg`, `có/không`) không còn bị bắt. Thêm đường dẫn tuyệt đối, home và Windows tương đối, URL, đuôi file, tên errno, hằng và hash viết hoa. Giới hạn: đường dẫn hai đoạn toàn chữ (`src/app`) chưa bắt được.
- **Ô tìm kiếm trên trang theo dõi** tìm cả trong phần cho chủ, tức tiêu đề và mô tả của thẻ.
- **Ngoài phạm vi:** `criterion_no_fail_clause` vẫn chỉ là ghi chú của lint (có từ trước dev11).

## v2.5.0.dev11 (08/11/2026) — gộp dòng Sol6.4 vào dòng UI dev10; khép 4 lỗi dùng thật — LOCAL, chưa tag/push/phát hành

- **Gộp:** `claude/sol6-close-s5` (`9df359a`, beta giám sát Sol6.4, đã chứa `claude/review-cycle2` `9933bbf`) vào `main` (`f1205bc`). Xung đột duy nhất: `docs/proposal-coverage.md`. Code sau gộp trùng `9df359a`.
- **Không gộp:** `claude/mrr-r3` (nền 2.4, va chạm ngữ nghĩa với cách ly đọc của Sol6: hai bên cùng đặt `GIT_OBJECT_DIRECTORY`); `claude/hotfix-verifier-inputs` (chờ phiên MEP).
- **Đã khép:**
  - `owner enforce --human` báo "chưa xác nhận" + exit 1 dù đã bật chặn: đã sửa trong dòng Sol, test đỏ trên `main`, xanh sau gộp;
  - `test_a_r13` giữ node khi hai cửa chạy đua: nguyên nhân là ghi lại manifest snapshot định danh theo nội dung trong lúc luồng kia đang đọc (Windows từ chối thay file đang mở); `Snapshots.save` không ghi lại manifest đã đúng byte;
  - stdout/stderr của verifier lệnh mở được qua `track evidence` và trang theo dõi; plan không `--workflow` nói rõ không có sổ finding;
  - lệnh `plan propose` từ chối trước khi ghi các lý do hình thức mà `plan lint` báo và `owner approve` sẽ từ chối.
- **Thay đổi hợp đồng — phần viết cho người theo dõi (chủ giao 08/11):** `presentation.request` (việc này làm gì), `user_sees` (xong bạn thấy gì), `acceptance_steps` (làm sao biết đạt), `not_doing` (không làm gì), lời thường, không tên file, đường dẫn, cờ lệnh, mã lỗi hay mã nội bộ. Bắt buộc khi state root có file owner-rules (`onecrew init` tạo); `plan lint`, lệnh `plan propose`/`plan amend` và `plan approve`/`owner approve` cùng từ chối. Hợp đồng cũ vẫn đọc được. Trang theo dõi (danh sách và bảng cột) dùng phần này làm tiêu đề, mô tả và câu "đang chờ bạn"; mục tiêu kỹ thuật, tên plan, mã task vào "chi tiết kỹ thuật"; hợp đồng cũ hiện như trước với nhãn "chưa có mô tả cho chủ".
- **Chưa kiểm:** provider thật, hook phiên thật, repo cỡ MEP. Xem bàn giao trong gói dev11 (ngoài repo, chưa phát hành).

## v2.5.0.dev10 (05/11/2026) — beta UI OBS-2 (prerelease)

**Bản prerelease beta của giao diện theo dõi OBS-2, không phải bản ổn định 2.5 và không phải toàn bộ lộ trình 2.5** (MR-R, 2.5-A/B, RD-A, CP-1 không có). Tag `v2.5.0.dev10` → snapshot `c4951f6`; wheel SHA256 `57445419e7c616f8e7c9f00039c7ac1b8ccc384c4cf464a27e3bc04b9d6879a1`. Codex đã review dev10, không phát hiện blocker mới trong phạm vi bản vá. Chưa nghiệm thu.

- **UI chỉ đọc:**
  - bảng thẻ công việc theo giai đoạn;
  - chi tiết thẻ: phương án và thay đổi, đầu ra hiện hành, kết quả kiểm, vòng kiểm/sửa;
  - timeline và bằng chứng;
  - "Quyết định cần bạn" có mẫu lệnh PowerShell, chỉ hiện khi hook của project khớp đúng runtime và sổ của trang.
- **Đã khép:** P3 focus sau sao chép (dev9); P2 sao chép dự phòng từ kết quả trả muộn của lần sao chép cũ (dev10).
- **Vấn đề đã biết:** clipboard còn chờ mà trang vẽ lại thì có thể tạm báo "Không sao chép được"; khi có kết quả thì cập nhật đúng.
- **Chưa kiểm:** clipboard native, pilot và sổ lớn, provider thật.
- **Tài liệu:**
  - ghi chú phát hành và hướng dẫn sử dụng (repo mới; repo đang dùng OneCrew: chỉ mở UI hoặc nâng runtime) ở `docs/obs2/su-dung/`, cùng script kiểm gói, ghi hiện trạng và sao chép sổ an toàn;
  - hồ sơ bàn giao ở `docs/obs2/HANDOVER.vi.md`.

## v2.4.0.dev13 (04/11/2026) — OBS-1: P2 của review Codex trên dev12 `4cdb384` (chi tiết task "đang tải" mãi khi API trả lời chậm hơn 20 s) — LOCAL, chưa tag/push

- **Nguyên nhân:** `loadDetail` của trang thay lượt đọc chi tiết đang chờ quá 20 s bằng lượt mới ở mỗi poll; trả lời của lượt cũ bị bỏ. Trả lời ~25 s → lặp mãi, "đang tải chi tiết…" không bao giờ kết thúc (Codex trên wheel dev12: sau 82,47 s, 4 request đã bắt đầu, 3 trả lời đã xong, UI vẫn tải).
- **Sửa (trang, `onecrew/v2/tracking_web.py`):** mỗi task đang chọn chỉ có một lượt đọc; poll (hay bấm lại đúng task đó) chờ lượt đang chạy, không thay nó; chờ tối đa 45 s (dòng "đang tải" đếm số giây đã chờ); quá 45 s → trang hủy lượt đó và báo "quá 45 s không có trả lời"; sau 3 lần quá hạn mà chưa có trả lời nào được hiện → ngừng tự thử, hiện nút "Thử lại"; lỗi trả về ngay (mạng, HTTP) không đếm và không xóa chuỗi đó, vẫn thử lại sau mỗi lần làm mới danh sách như R4; chỉ một trả lời được hiện mới kết thúc chuỗi; bấm vào một task (kể cả task đang xem), bấm nút, hoặc nối lại kết nối mở chuỗi mới; trong lúc thử lại, dòng trạng thái và đầu trang ghi "đang thử lại" kèm số giây; sau "Thử lại" bằng bàn phím, focus ở lại dòng trạng thái rồi về tiêu đề task; đổi task hay đóng task hủy lượt đọc đang chạy (mở lại là lượt mới, trả lời muộn của lượt cũ không bao giờ chạm trang). Tìm thêm khi sửa, cùng loại lỗi: overview treo thì trang đứng yên dưới huy hiệu "kết nối OK" → đọc overview nay chờ tối đa 5 phút (overview chỉ chậm vẫn chạy như dev12; không bao giờ trả lời thì huy hiệu báo MẤT KẾT NỐI).
- **Kiểm:** harness có đồng hồ giả (`/?__fake=1`: bộ hẹn giờ, `Date`, `fetch` của trang; dữ liệu thật của server) và chế độ thời gian thực (`run(..., realtime=True)`, proxy `/__log`, `/__hold`, `/__fault` có `count`); kịch bản mới fk_fast, fk_slow25, fk_cycles, fk_switch, fk_timeout (1280, 390), fk_timeout1, fk_disc, fk_ovhang, fk_ovslow, fk_mixed, fk_reselect, fk_reconnect, rt_slow — trong test trình duyệt và V14 của gói (bằng chứng `evidence/ux-fk_*/rt_*.json`).

## v2.4.0.dev12 (03–04/11/2026) — OBS-1 beta: bốn P2 + một P3 của review phát hành độc lập Codex trên dev11 `7c8bfca` (nguồn gốc bằng chứng, phạm vi project, lọc bí mật, chi tiết theo lựa chọn, lối mở/dừng ghim cứng)

**`2.4.0.dev12` = `2.4.0.dev11` + các bản sửa R1–R5 của review phát hành Codex 03/11 ~20:57 (`D:\OneCrewRuns\codex-obs1-release-review\review.json`); giữ hướng Gantt/waterfall; không thêm tính năng UI ngoài sửa lỗi; chưa nghiệm thu, chưa Codex review lại.** Tiêu chí giao trước khi sửa: `docs/obs1/UX-OBS-1.vi.md` §5; nguyên nhân/cách khép: `docs/obs1/GIAI-PHAP-OBS-1.vi.md` §10. Mỗi finding có test đỏ trên code dev11 trước khi sửa (log trong `D:\OneCrewRuns\obs1\logs\r15\`).

- **R1 — nguồn gốc bằng chứng theo từng lần dùng:** `evidence_index` một mục cho mỗi (seq sự kiện, khóa) với loại, thời điểm, phần việc, thế hệ, lượt (+ `attempt_basis`), vai trò (`role`) và `output`; dựng từ toàn bộ lịch sử root + task con, không từ cửa sổ hiển thị; `attempt.*` lấy (phần việc, thế hệ) từ `node.started` của lượt; mới `timeline_limit`, `timeline_complete`, `evidence_basis`, `timeline[].evidence_count`, `gantt.rows[].inherits[].source_occurrence`; cửa bằng chứng kiểm thành viên trên toàn lịch sử (không gọi `detail` nữa: ~20 ms thay vì 3–4 s); `evidence_index[].generation_basis`; `gantt.rows[].inherits` cho MỌI dòng từ `node.resumed` (`resumed_seq`; không còn `retained_candidate`); chỉ khóa có trong kho là bằng chứng: blob hoặc ảnh chụp manifest (`evidence_index[].stored` = `blob`|`manifest`|null, `.blob` = có trong kho; `evidence_keys` chỉ khóa có trong kho; mã định danh 64-hex khác không còn là mục; `estimate.*` không còn là lần dùng; dòng timeline chỉ liệt kê lần dùng của chính sự kiện); mở ảnh chụp trả JSON danh sách tệp (`kind: manifest`, `files`, `verified`); `/api/evidence` và `track evidence` của khóa được nêu mà không có trong kho → 404 "Không có trong kho bằng chứng…" (trước: 503, tăng bộ đếm lỗi); chữ `track show` khi timeline bị cắt chỉ tới `--json` và trang. Trang: nhật ký/ngăn bước/dấu mốc/mục Bằng chứng dùng lần dùng của đúng sự kiện; kế thừa và đầu ra mới cùng hiện; nhật ký nói phần chưa tải. Test `tests/test_obs1_r1_provenance.py`, kịch bản `prov`.
- **R2 — phạm vi project cho toàn mô hình:** mục registry hook so theo định danh sổ (`tracking.project_identity`), dưới phạm vi chỉ còn mục của chính project; chế độ mọi project giữ nguyên. Test `tests/test_obs1_r23_scope_secrets.py` (R2).
- **R3 — một chốt lọc đầu ra:** `tracking.outward` áp `diagnostics.redact_line` cho mọi chuỗi của overview/detail/evidence, hai bản chữ (`track list/show`), mọi thân JSON của server (cả `/api/health` và lỗi) và JSON lỗi của CLI; JSON định danh của `track status/open/stop/serve` (marker, url, pid, instance, sổ) giữ nguyên vì script ghim dùng đúng các giá trị đó; trường thô qua `clean` (không cắt id/ref: `clean(value, limit=None)`); sổ không đổi; chuỗi thường giữ nguyên từng byte. Test R3 (+ tăng cường lúc gộp).
- **R4 — chi tiết theo lựa chọn:** dữ liệu chi tiết gắn lựa chọn (`detailFor`); trạng thái `loading/error/stale` (`window.__track.state()` thêm `detailFor`, `detailState`, `detailError`, `detailOkAt`), `#dconn` và cảnh báo độ mới `#dstatus`; lỗi mạng/HTTP/không vẽ được không còn bị nuốt; mẫu lệnh của dữ liệu cũ được đánh dấu. Gộp: yêu cầu chi tiết đang chạy được chờ (chi tiết chậm hơn chu kỳ poll trước đây không bao giờ hiện), bản sao chép xong muộn, ô "Từ khi duyệt" không nhảy lùi. Kịch bản `stale_detail` (desktop, mobile), `slow_detail`; harness có công tắc lỗi chỉ dùng trong test (`/__fault`, proxy).
- **R5 — lối mở/dừng ghim cứng:** script chung `mo-/dung-trang-obs1.ps1` có `-PinFile`; `track stop --url U --instance I --pid P [--started-at T]` dừng đúng một server theo định danh (giữ handle tiến trình trước khi kiểm, chỉ xóa marker khi marker nêu đúng instance đó; thiếu một trong ba → exit 2, không dừng gì); `track open` chờ server tới 30 s và không để lại server khi hết giờ; mở từ chối trước khi khởi động khi phiên ghim cùng sổ còn sống mà không dùng lại được; cặp script ghim cứng cho bản phát hành sinh từ gói + lần chạy đã nghiệm (`D:\OneCrewRuns\wf-dev-tools\obs1\tao-loi-vao-obs1.py`, công cụ phát triển, không nằm trong gói); script quét thư mục cũ đánh dấu lỗi thời. Vòng 5 (review rủi ro trên ứng viên tích hợp): `/api/health` hỏi thẳng, không qua proxy HTTP của máy (biến `HTTP_PROXY` từng làm `track open`/`stop` không thấy server); tiến trình con của `track open` nhận đường dẫn tuyệt đối (`--state-root` tương đối từng hỏng); định danh sổ so bằng `state_root_id` (SHA-256 đường dẫn đã resolve) trong `/api/health` và marker, nên đường dẫn trông như bí mật (bị che bởi R3) không làm hỏng dùng lại/dừng; dưới khóa `track open` đọc lại marker (dùng lại server vừa được lần mở khác dựng, chỉ xóa marker đã thất bại); script đọc lại file ghim ngay trước khi ghi và dừng server mình vừa mở khi không ghi được ghim.
- **Review rủi ro trên ứng viên tích hợp (04/11, 4 hướng + phản biện từng finding):** V14 của gói trả lời tín hiệu `prov_more` mà harness gửi (trước đó `prov` chắc chắn hỏng trong gói); V17 không còn đạt suông (lệnh/yêu cầu phải thành công, có đối chứng dương cho danh sách tiến trình, `--release-review` ghi đúng wheel đã kiểm); server đọc thân request (tới 8 MiB) trước khi trả 405 (Windows từng reset kết nối: WinError 10053); khi một trả lời không vẽ được, trang khôi phục cả ghi chú câu hỏi, trạng thái sao chép và chuỗi lỗi; manifest gói mô tả đúng bản dựng.
- **Kiểm gói:** V14 thêm `stale_detail` (desktop, mobile), `slow_detail`, `prov` (cuối); bước mới V17 kiểm R1/R2/R3/R5 từ wheel đã cài (CLI + server thật + script chung với `-PinFile`), có đối chứng hợp lệ.

## v2.4.0.dev11 (03/11/2026) — OBS-1: ba P2 + một P3 của review Codex trên dev10 `5e66903` (đồng hồ timeline, bằng chứng theo thế hệ, so thời gian theo giá trị, bố cục 1280) — LOCAL, chưa tag/push

**`2.4.0.dev11` = `2.4.0.dev10` + bốn bản sửa theo review Codex 03/11 ~16:00 (bằng chứng `D:\OneCrewRuns\codex-obs1-dev10-review\evidence\review.json`); giữ hướng Gantt/waterfall; chưa phát hành, chưa nghiệm thu, chưa Codex review lại.** Bảng acceptance viết trước khi sửa: `docs/obs1/UX-OBS-1.vi.md` §4. Phản chứng đỏ trên wheel dev10 đóng băng `93ae9f31…` trước khi sửa: `D:\OneCrewRuns\obs1\red-on-dev10\results.json`.

- **P2-A — đoạn "tới hiện tại" của timeline đứng yên khi `seq` không đổi:** `loadDetail` bỏ qua dựng lại khi sổ không có event mới (đúng cho phần còn lại), nhưng đoạn `to_now`, đường "hiện tại" và cuối trục phụ thuộc `gantt.axis.now` của *từng* reply server. Nay poll không đổi seq vẫn nhận `detailData` mới và chỉ dựng lại timeline (`repaintGantt`, giữ bước chọn/gập/focus/cuộn ngang/cuộn dọc); đoạn đã xác nhận giữ nguyên mốc có nguồn, lượt đã kết thúc không kéo; mất kết nối → timeline đóng băng và ghi "mất kết nối: đang hiện dữ liệu cũ lúc …, đồng hồ dừng"; nối lại → theo `axis.now` của reply mới (không cộng đồng hồ máy, không cộng đôi). Đầu timeline ghi "hiện tại (… theo server)". Harness `gantt_now`: ba mẫu cách ≥ 1,1 s khi seq đứng yên → `data-to` của `to_now` tăng theo đồng hồ server (so với một lần đọc trực tiếp `/api/task`), bằng đúng `axis.now` của reply, cạnh phải thanh đã kết thúc dịch trái (trục giãn), đường "hiện tại" ở cuối trục, không đoạn nào từ chưa-xác-nhận thành xác-nhận; chặn `/api/*` → đứng + nhãn; mở lại → tiến tiếp. Đỏ trên dev10: `to` đứng ở một giá trị qua ba mẫu, không nhãn.
- **P2-B — ngăn chi tiết hiện đầu ra của thế hệ cũ cho lượt hiện hành:** `evidence_index` nay một mục cho mỗi (khóa, phần việc, thế hệ, lượt) — blob nội dung-định-địa-chỉ nên hai thế hệ cùng đầu ra có cùng khóa, mỗi thế hệ vẫn có mục riêng — và mọi mục của một phần việc mang `generation` (sự kiện `attempt.*` lấy thế hệ từ bảng `attempts`). Ngăn chi tiết lọc theo lượt (nếu mục có `attempt`) hoặc theo (phần việc, thế hệ) của thanh/dấu mốc đang chọn; tách "Đầu ra của lượt này (thế hệ n)" (node.produced/verification/attempt.settled/receipt) khỏi "Bằng chứng khác của lượt này"; lượt đang chạy chưa có đầu ra ghi "lượt này chưa có đầu ra (đang chạy)". Kế thừa hợp lệ theo cơ chế engine (`node.resumed` với `resume_artifact`/`continues_attempt`, `retained_candidate`) hiện riêng ở mục "Kế thừa" với thế hệ/lượt nguồn và trường nguồn (`nodes[C].resume_artifact`), mở được nội dung; không bị lọc mất. Dữ liệu thử P9 (thế hệ 1 tiếp tục từ đầu ra dở thế hệ 0 và có đầu ra riêng); harness `evid` (P4 lượt hiện hành thế hệ mới không có mục "thế hệ 0 đã tạo đầu ra", nói rõ chưa có đầu ra; lượt cũ có đúng đầu ra thế hệ 0; dấu mốc "đã tạo đầu ra" dẫn tới cùng bằng chứng; P9 kế thừa + đầu ra riêng); unit `EvidenceByGeneration`. Đỏ trên dev10: mục không có `generation`, lượt hiện hành liệt kê receipt thế hệ 0, mô hình không có `inherits`.
- **P2-C — so chuỗi ISO khác offset theo từ điển:** `_timeline_spans` nay so mọi mốc bằng datetime có múi (`_at`, chuẩn về UTC): mốc mới nhất, bắt đầu/kết thúc, min/max trục, `now` so cuối trục, chờ/kiểm, sắp xếp dấu mốc; chuỗi phát ra là `_iso` của giá trị đã parse (giữ offset như sổ ghi); mốc hỏng bị bỏ, không bịa. Unit `TimelineClock`: quan sát `+07:00` với `now` UTC → cuối trục = now, đoạn thực thi kết thúc ở 08:01Z; offset âm qua nửa đêm; hai cách viết cùng thời điểm → cùng thứ tự/thời lượng; observed_at ≠ received (lấy observed); observed_at hỏng → lấy received; `launched` hỏng → chỉ đặt chỗ + tới hiện tại. Đỏ trên dev10: cùng dữ liệu, `_timeline_spans` dev10 lấy cuối trục = chuỗi `+07:00` (lớn hơn theo từ điển) thay vì now.
- **P3-D — timeline chật/cắt ở 1280×720:** cột chi tiết rộng hơn khi đang đọc (`minmax(220px,1fr) minmax(420px,3.4fr)`), cây 170 px, bỏ `min-width` cứng của biểu đồ ở ≥ 900 px (dưới 900 px vẫn cuộn trong vùng riêng), ngăn chi tiết bước nằm dưới biểu đồ cho tới 1400 px (từ 1400 px: cột phải 300 px), nhãn vạch đầu/cuối không lòi khỏi biểu đồ (từng gây 27 px cuộn ngang), chữ cây ≥ 12 px ở mọi cỡ. Harness `gantt` desktop: `.gscroll.scrollWidth ≤ clientWidth` cho P8 và P4 "toàn khoảng", cây ≤ 180 px, biểu đồ ≥ 500 px; ux08 vẫn 390/390. Đỏ trên dev10: `scrollWidth` 667 > `clientWidth` 540, cây 210 px.
- **Dữ liệu thử:** P9 (unit fixture + kịch bản gói `ux`); harness thêm `gantt_now`, `evid` (V14 = 22 lượt kịch bản); `OBS1_UX_ONLY` để chạy một phần khi phát triển.
- **Verifier (snapshot thứ ba của dev11):** `powershell_template()` chỉ dùng env đã lọc `AI_MARKERS` (trước đó hợp env nguyên của shell gọi, nên shell mang `CLAUDECODE` làm verb chủ bị guard phiên AI từ chối → `p2a`/V16 hỏng từ phiên điều phối dù trang đúng); kiểm gói nay chạy được từ shell có dấu; mã sản phẩm không đổi.
- **Giới hạn:** Chrome headless chạy theo thời gian ảo (`--virtual-time-budget`) nên mọi phép đo thời gian trong harness so với đồng hồ server, không so đồng hồ trang; gói `onecrew-2.4.0.dev10-obs1-beta` (Codex đã xem) không bị ghi đè — gói mới `onecrew-2.4.0.dev11-obs1-beta`. Gate 2.2 không chạy lại. Chi tiết `docs/obs1/limits-obs1.md`.

## v2.4.0.dev10 (03/11/2026) — OBS-1: timeline Gantt/waterfall làm trung tâm màn chi tiết; hai P2 của dev9 (câu hỏi bám chỉ số, quote PowerShell) — LOCAL, chưa tag/push

**`2.4.0.dev10` = `2.4.0.dev9` + hướng thiết kế chủ chốt 03/11 ~13:30; chưa phát hành, chưa nghiệm thu, chưa Codex review lại.** Bảng acceptance viết trước khi sửa: `docs/obs1/UX-OBS-1.vi.md` §3.

- **Timeline Gantt/waterfall (`tracking.py` `_timeline_spans` → `detail.gantt`, trang `gantt()`):** cây *phần việc → lượt* bên trái (gập/mở từng phần việc; lượt cũ gập "lịch sử (n)", mờ), các thanh trên **cùng trục thời gian** ở giữa (đoạn `reserved` đặt chỗ = `attempts.created_at`→`attempt.launched`, `execution` = `attempt.launched`→`attempts.updated_at` khi settled, `wait` = executor wait có `until`, `verification` = `node.produced`→`node.verification`, `to_now` = từ mốc dữ liệu mới nhất tới "hiện tại" cho lượt đang chạy — sọc, "chưa xác nhận"), dấu mốc ◆ cho sự kiện tức thời (node.started/produced/verification/held/resumed, quan sát blocked; plan.approved/accepted/closed/câu hỏi trên hàng Plan), đường "hiện tại", chú giải, chọn khoảng (toàn bộ / 1 giờ cuối / 15 phút cuối), cuộn ngang chỉ trong vùng timeline; ngăn chi tiết bên phải (≥ 1100 px) hoặc dưới: mốc chính xác, giây, chờ, kiểm, lý do giữ, quan sát gần nhất, đầu ra/bằng chứng của lượt hoặc sự kiện được chọn (xem nội dung ngay). Bấm/Tab+Enter chọn thanh hoặc dấu mốc; lựa chọn giữ qua poll và đổi kích thước. Thiếu mốc → không vẽ, ghi "chưa xác định"; không ETA/phần trăm/khoảng chờ suy đoán. Thứ tự màn chi tiết: đầu (tên, trạng thái, bước, cần bạn) → Cần bạn (gập) → **Timeline** → thẻ số liệu → bảng phần việc → nhật ký sự kiện (gập) → kỹ thuật.
- **P2-A (dev9) — mục câu hỏi đang đọc nhảy sang request khác khi danh sách đổi:** `data-k` của thẻ câu hỏi nay là `need:<REQ id>:<revision>` (không phải chỉ số); trạng thái mở/focus/sao chép bám theo đó; khi request đang mở biến mất (đã trả lời/đóng) hoặc đổi bản, trang hiện ghi chú "không còn chờ / đã đổi bản: mẫu lệnh cũ không còn hiệu lực" (ẩn được) và bỏ trạng thái sao chép. Phản chứng harness `p2a` (trả lời câu 1 khi đang mở câu 2, rồi trả lời chính câu 2, qua CLI thật) đỏ trên wheel dev9.
- **P2-B (dev9) — mẫu lệnh quote sai trong PowerShell:** shell hỗ trợ chốt là **PowerShell**; đối số bọc nháy đơn (`'`→`''`), lệnh bắt đầu bằng `& '<venv>\Scripts\onecrew.exe'` (runtime rõ) rồi `--project '…' --state-root '…' question answer … --reference '<…>'`; `reply_shell`. Kiểm bằng `powershell.exe` thật từ file `.ps1` với `$SDK = "CHANGED"` trên đường dẫn `demo$SDK 'q' (a)&b``t` (unit + V16 từ wheel): đường dẫn tới parser nguyên vẹn, câu trả lời ghi sổ thử; dạng dev9 (nháy kép) làm đường dẫn thành `demoCHANGED…` → từ chối.
- **Dữ liệu thử:** P8 hai phần việc chạy đồng thời qua `engine.run_batch(slots=2)` với executor khai báo `isolate` (chồng lấp thật trên trục), project PS có ký tự đặc biệt; kịch bản gói `ux` tương ứng.
- **Kiểm:** unit `GanttSpans`, `PowerShellTemplate`; harness `gantt` (so left/width từng đoạn với mốc JSON ≤ 0,6 % trục; chồng lấp; `to_now`; dấu mốc; chú giải; chọn + poll + resize; P3/PB không vẽ; P5 chờ; khoảng 15 phút), `p2a`; gói V14 (20 lượt) + V16 (PowerShell thật, đường dẫn đặc biệt). Gate 2.2 không chạy lại.

## v2.4.0.dev9 (03/11/2026) — OBS-1 vòng UI/UX theo review Codex trên dev8: hai P2 (đồng hồ, mẫu lệnh trả lời), tràn 402 px, UX A–D — LOCAL, chưa tag/push

**`2.4.0.dev9` = `2.4.0.dev8` + review Codex UX trên dev8; chưa phát hành, chưa nghiệm thu, chưa Codex review lại.** Bảng acceptance viết trước khi sửa: `docs/obs1/UX-OBS-1.vi.md` §2.

- **P2-A — đồng hồ "Từ khi duyệt (lịch)" đứng khi sổ không có event mới:** trang chỉ dựng lại chi tiết khi `seq` đổi (đúng), nhưng đồng hồ cộng `(now − lần poll cuối)` vào giá trị đã dựng, nên mỗi poll không đổi seq lại kéo đồng hồ về giá trị cũ. Nay giá trị mang mốc dựng (`data-live-at`) và tiến theo đồng hồ máy từ mốc đó; dựng lại/đổi task/reload lấy giá trị có nguồn mới + mốc mới (không cộng đôi); task đã kết thúc hay chưa duyệt không có đồng hồ. Phản chứng: harness `clock` đỏ trên wheel dev8 (`D:\OneCrewRuns\obs1\red-on-dev8\results.json`), xanh trên dev9; test giá trị với giờ giả ở model (`ElapsedClock`).
- **P2-B — lệnh trả lời do trang sinh thiếu `--reference` (parser `questions.py` bắt buộc) và thiếu project/sổ:** `needs_user[].options[].reply_command` nay là **mẫu lệnh đầy đủ** `onecrew --project "<p>" --state-root "<s>" question answer <id> --revision <rev> --choice <id> --reference "<lý do hoặc bằng chứng của bạn>"`; phần `--reference` là chỗ người dùng tự điền, được đánh dấu (`mark`) và gọi là mẫu, nút "Sao chép mẫu lệnh"; `placeholders`, `reference_placeholder`, `reply_note`. Guard chủ sở hữu/bản/AI-session giữ nguyên. Kiểm: unit test chạy mẫu qua `onecrew.console` từ cwd có khoảng trắng (thiếu `--reference` → exit 2, sổ không đổi; điền → ghi sổ thử, câu hỏi rời "cần bạn"); gói V16 cùng bài trên CLI cài từ wheel; harness `ux03` kiểm nội dung clipboard thật (`readText`) và copy hỏng báo hỏng kèm ô chép tay.
- **Tràn 402 px ở 390 px (lượt 11:06 của phiên điều phối, không tái lập ở lượt 10:50):** nguyên nhân là `<select>` project có option = đường dẫn dài (`…obs1 thu 2.4.0.dev8 20261103-110652\project with space`): `max-width:100%` của select tính theo `label` cha, mà label (flex item, `min-width:auto`) lại rộng theo nội dung → trang rộng 402 px. Sửa gốc: `label{min-width:0;max-width:100%}`, `select{min-width:0}`; fixture/scenario dùng tên thư mục project dài; harness `ux08` liệt kê phần tử vượt mép phải (không chỉ `scrollWidth`) và kiểm cả khi mở mẫu lệnh.
- **UX A–D:** chip lọc nhanh "cần bạn / bị chặn / đang thực hiện (n)" từ dữ liệu có sẵn; khi đang đọc chi tiết (≥ 900 px) cột danh sách thu gọn (ẩn dòng ID/đường dẫn); vùng đầu chi tiết: tên + trạng thái + **bước hiện tại** + "n câu hỏi chờ bạn" (liên kết xuống mục); thẻ số liệu đứng trước; mục **Cần bạn (n)** với từng câu hỏi gập (`details`, tiêu đề riêng, không gộp), mở ra thấy lý do/ảnh hưởng/lựa chọn/mẫu lệnh, trạng thái mở giữ qua poll; bảng attempt có thanh thời lượng chỉ khi attempt có mốc kết thúc và số đo (`measure.attempts[].execution_seconds`), đang chạy = "chưa xác định" (không thanh); pha/đầu ra phần việc tiếng Việt (mã gốc ở `title`), lý do giữ ghi "lý do (engine)"; badge có ký hiệu (▶ ◔ ■ ✔ ✓ □ ?) ngoài màu; `current_step` "chờ bạn trả lời n câu hỏi".
- **Kiểm:** `test_obs1_ux` (+3), harness thêm `clock`, `ux03b` (3 câu hỏi), sửa `ux03/05/06/07/08`; dữ liệu thử: P1 có 3 câu hỏi, tên task dài tự nhiên, project có tên thư mục dài; gói V14 (17 lượt) + V16 mới. Gate 2.2 không chạy lại.

## v2.4.0.dev8 (03/11/2026) — beta OBS-1 vòng UI/UX theo hướng Blazo + định danh server của `track open`, nhánh `claude/onecrew-obs1`

**Prerelease `2.4.0.dev8` = `2.4.0.dev7` + vòng UI/UX (review Codex UX trên dev7: UX-01…UX-08) + P2 định danh server; chưa nghiệm thu, chưa Codex review lại.** Nhánh `claude/onecrew-2.4`, tag/gói `v2.4.0.dev6` và `v2.4.0.dev7` không đổi. Ma trận UX viết trước khi sửa: `docs/obs1/UX-OBS-1.vi.md`.

- **Trang (`tracking_web.py`), bố cục mới:** tổng quan (danh sách dạng dòng: trạng thái, tên/mục tiêu, bước hiện tại, cập nhật tương đối; ID/đường dẫn/adapter mờ; lọc project + trạng thái + "cần bạn", tìm) → chi tiết task (tiêu đề + project đang xem, mục tiêu, thẻ câu hỏi với từng lựa chọn và lệnh `--choice <id>` để **sao chép**, thẻ trạng thái/đầu ra/từ khi duyệt (lịch)/thực hiện (attempt)/chờ/ước lượng, bảng phần việc) → timeline nhóm theo plan và từng phần việc, cũ → mới theo seq, lịch sử thế hệ/attempt cũ và sự kiện kỹ thuật gập lại, bấm một bước để xem bằng chứng của bước đó → bằng chứng có tên/loại/thời điểm, xem nội dung ngay trong trang. Hai cột (≥ 900 px, chi tiết cố định cuộn riêng) / một cột với "← Danh sách" (< 900 px); không cuộn ngang trang, bảng kỹ thuật cuộn trong vùng riêng. Chọn bằng chuột hoặc bàn phím (dòng `role=option tabindex=0`, ↑↓/Home/End/Enter/Esc), Enter đưa focus vào tiêu đề chi tiết; URL `?plan=&project_id=` theo lựa chọn (`pushState`/`popstate`), reload và Back giữ ngữ cảnh. Chi tiết chỉ dựng lại khi `seq` của sổ đổi; khi dựng lại giữ các mục đang mở, phần tử focus, vị trí cuộn và bước đang chọn; thời gian tương đối cập nhật tại chỗ. Trả lời chi tiết của task đã bỏ chọn bị bỏ qua (token). Đổi project đóng chi tiết của task thuộc project khác. Focus nhìn thấy (`:focus-visible`), một theme sáng mặc định + tối theo hệ điều hành. Không có nút điều khiển task.
- **Mô hình (`tracking.py`), cùng nguồn cho CLI/JSON:** `status.outcome` + nhãn riêng cho ba kiểu "xong" (`OUTCOME_WORDS`: đã nghiệm thu / đã kiểm, chờ nghiệm thu / đã đóng) thay "hoàn tất" chung; `elapsed.label` = "từ khi duyệt (thời gian lịch, gồm cả chờ)" (CLI in "từ khi duyệt", bỏ "đã chạy"); `current_step` (một dòng bước hiện tại có nguồn); `needs_user[].options[].reply_command` (mỗi lựa chọn một lệnh), `reason`/`impact`/`recommendation`; `evidence_index` (mỗi blob: sự kiện đầu tiên nêu nó — kind/at/node/attempt/label/stale).
- **P2 định danh server (`track open`):** `/api/health` và marker `tracking/server.json` mang `instance` (nonce), `version` wheel, `state_root`, `project_id`, `pid`; `open_page` chỉ dùng lại khi `reusable()` khớp cả bốn (+PID), marker không có instance (wheel cũ), server không trả lời, cổng do tiến trình khác trả lời, version/sổ/phạm vi khác → mở server mới, báo `refused.reason`, không kill gì; khóa `tracking/open.lock` (O_EXCL, cũ > 60 s coi là bỏ sót) cho mở đồng thời; marker ghi atomic và chỉ xóa khi còn là của mình. Mới: `track status` (marker + health + kết luận), `track stop` (chỉ dừng server khớp marker: PID + sổ + instance; marker cũ/sai chỉ bị xóa), `track open --no-browser`; `ONECREW_TRACK_MARKER_DIR` đặt marker/khóa ngoài thư mục sổ (sổ thật không có thêm file). Script gói: `verify/mo-trang-obs1.ps1`, `verify/dung-trang-obs1.ps1`.
- **Kiểm:** `tests/test_obs1_ux.py` (14: nhãn/outcome, `current_step`, lệnh theo lựa chọn, `evidence_index`, định danh server với server thật trên cổng thật, marker wheel cũ, cổng bị chiếm, khóa, hai lần mở đồng thời qua tiến trình con thật, `stop`); `tests/test_obs1_browser.py` + `tests/obs1_ux_harness.py` + `tests/obs1_ux_fixture.py` (trang thật trong Chrome headless, harness cùng origin: 14 lượt kịch bản × kích thước, ≥ 3 lượt poll, ghi sổ trong lúc đọc, reload, Back, race, mất/nối lại kết nối; ảnh); gói: V14 (harness từ wheel đã cài trên scenario `ux`), V15 (`track open` thật từ wheel). Bốn P2 cũ (`test_obs1_p2`) và bộ OBS-1 giữ xanh. Gate 2.2 đầy đủ không chạy lại.
- **Giới hạn:** `claude` giả; thao tác do harness phát (không phải người dùng thật, không screen-reader); Chrome headless; chi tiết `docs/obs1/limits-obs1.md`.

## v2.4.0.dev7 (03/11/2026) — beta OBS-1: màn hình theo dõi chỉ đọc (`onecrew track`), nhánh `claude/onecrew-obs1`

**Prerelease `2.4.0.dev7` = `2.4.0.dev6` + lát OBS-1 (roadmap §0.9, thiết kế §2.10); không phải toàn bộ roadmap (MR-R, OBS-2 chưa có); chưa nghiệm thu production.** Đặt trên nhánh `claude/onecrew-obs1` tách từ `01b6f62`; nhánh `claude/onecrew-2.4`, tag `v2.4.0.dev6` và gói dev6 không đổi. Điểm vào thử: `BAT-DAU-THU.vi.md` trong gói OBS-1 (`verify/thu-goi-obs1.ps1`).

- **Mới:** nhóm lệnh `onecrew track list|show|evidence|serve|open` trên một mô hình trạng thái chỉ đọc (`onecrew/v2/tracking.py`: plan.*, `engine.state`, bảng `attempts`, `executor.observed`, `requests`, `notice.exception`, `estimates`, `execution_mode.measure`, `hold_views`; sổ mở `mode=ro`); CLI và trang web local (`tracking_web.py`, `http.server` stdlib trên 127.0.0.1, chỉ GET, HTML một file, poll 2 s) đọc cùng dict. Trạng thái có nguồn (đang thực hiện / đang chờ / bị chặn / hoàn tất / chưa xác định) tách khỏi mức đầu ra (chưa có / đã tạo / đã kiểm / đã nghiệm thu); thế hệ cũ và attempt cũ không đổi trạng thái (timeline đánh dấu); overlap = union; ETA là khoảng hoặc "chưa xác định"; phiên ngoài OneCrew = "chưa được theo dõi"; mọi chuỗi qua `diagnostics.redact_line`. Không nút điều khiển, không sổ tiến độ riêng, không model.
- **Sửa (review Codex 03/11 trên snapshot `bf6994f`, 4 P2):** P2-01 plan đóng (`plan.closed`) không còn hiện "đã nghiệm thu": mức đầu ra lấy từ node; P2-02 quan sát tiến độ của attempt cũ đến muộn không đổi trạng thái attempt đang chạy (progress ràng theo attempt hiện hành; lịch sử đánh dấu `attempt cũ`); P2-03 khoảng chờ đã ghi `until` (cùng attempt + ref) là lịch sử, không phải chờ hiện hành; sự kiện trùng/đến muộn không mở lại; khoảng chờ của attempt đã kết thúc không ghi `until` = "chưa rõ kết thúc"; P2-04 server `--project-only` từ chối (403) mọi `project_id` khác trên overview/task/evidence; chế độ mọi project vẫn thu hẹp được.
- **Kiểm:** `tests/test_obs1_p2.py` (10, đỏ trên `bf6994f` → xanh), `test_obs1_tracking` (18), `test_obs1_web` (7, Chrome headless), `test_obs1_installed` (1, wheel ngoài checkout); bước gói V13 (bốn phản chứng từ wheel đã cài qua CLI/HTTP). Gate 2.2 đầy đủ không chạy lại cho lát này.
- **Giới hạn:** `claude` giả trong mọi kiểm; độ trễ đo trên sổ nhỏ; Chrome headless; không xác thực (127.0.0.1); bản sửa P2 chưa Codex review lại. Chi tiết `docs/obs1/limits-obs1.md`.

## v2.4.0.dev6 (02/11/2026) — beta 2.4: S1/S2/A/B/C, xác thực API cho advisor/reviewer, bộ thử trong gói

**Bản beta (prerelease) `2.4.0.dev6` của 2.4, không phải bản ổn định `2.4.0`; chưa nghiệm thu production.** Dùng trên bản sao project và sổ riêng; không tự cài lên runtime/sổ thật. Điểm vào thử: `BAT-DAU-THU.vi.md` trong gói (script `verify/thu-tay/`).

- **Mới (so với 2.3.0.dev10/dev11):** S1 báo lỗi một lần + hồ sơ chẩn đoán (`support report|show|status|bundle|…`); S2 bản vá OneCrew từ báo cáo tới tiếp tục việc cũ (`support target|artifact|install|recheck|rollback`, diễn tập trên bản sao, chuyển hook ở điểm an toàn, quay lui có điều kiện, không chạy bytecode `.pyc` chưa kiểm); A worker tự đọc nguồn theo quyền (`authority.read`, `sources`); B working context theo consumer (`knowledge.delivered`, delta, cổng kiểm lại, `wiki consumers`); C thẻ bước 0 và cách chạy node (`plan step0 show`, `execution-mode`, `engine measure`).
- **Xác thực API cho advisor/reviewer Claude CLI** (hotfix 2.3 `2.3.0.dev11`, tích hợp nguyên bản sửa + phản chứng): `auth: subscription|api` trên hợp đồng, `plan advise --auth api`; key chỉ vào tiến trình CLI; `credential_missing`; không fallback; **thêm ở 2.4:** key mà provider phản chiếu lại bị che `[withheld]` trong lỗi/blob/problem. Chưa gọi API thật trong lượt dựng (CLI giả); `~/.claude/settings.json` của máy có thể đổi cách CLI xác thực.
- **Lỗi đã sửa qua các bản dev2→dev6:** F1 danh tính venv theo nội dung và mốc tạo; F2 quyết định chuyển/quay lui gắn dữ liệu đã diễn tập, cửa sổ chuyển hai phía; F3 duyệt đủ chuỗi phụ thuộc, không mặc định publish; P1 dev3 bytecode `.pyc` sai chạy trước khi bị từ chối; P1 dev4 quay lui chạy bytecode bị thay sau phép kiểm (mọi chương trình của venv đã kiểm đọc bytecode từ thư mục trống riêng, không nhận `PYTHON*`); P3 tài liệu trong gói; review bộ thử (cách ly registry, quay về A/B, tên thư mục kết quả, dọn dẹp chỉ xóa lab có dấu sở hữu, dot-source, giữ marker phiên AI).
- **Cài/nâng cấp/quay về:** README của gói §2–3; `BAT-DAU-THU.vi.md` §2 (lab cách ly), §5 (quay về: A cài lại wheel; B sau S2 chỉ `support rollback`, từ chối là đúng). Nâng từ 2.3 (dev10/dev11) giữ sổ, plan, lịch sử; plan có `auth` đọc được ở cả hai chiều (dev10 bỏ qua `auth`).
- **Giới hạn / chưa thử thật:** model/provider thật (worker giả trong mọi kiểm), pilot, nghiệm thu; bài S2 thủ công trên máy người dùng; chi tiết `docs/limits-final.md`.

## v2.4.0.dev5 (02/11/2026) — bản thử 2.4 sau review Codex trên dev4 (ứng viên beta, chưa nghiệm thu)

Sửa một finding của Codex trên `2.4.0.dev4` (`4f03e54`, wheel `8fa0dfde…`): 1 P1, phản chứng đỏ trên code dev4 trước khi sửa (test của checkout và bước kiểm chạy trên chính gói dev4).

**P1 (2.4-S2) — bytecode bị thay sau phép kiểm vẫn chạy khi quay lui:** `_old_runtime` so `.pyc` của runtime cũ, nhưng bước đọc sổ (`_read_check`, `onecrew compat scan`/`plan show`/`engine …`) và bước phân loại sự kiện (`event_classes`) chạy runtime cũ sau đó với `__pycache__` của venv, nên `.pyc` bị thay ngay sau phép so được thực thi (Codex: `marker_created true`, `reader_pair[0].problems []`). Nay mọi chương trình của venv đã kiểm mà `hotfix` chạy (phép kiểm danh tính, bước đọc sổ khi diễn tập cài/quay lui và recheck, bước phân loại sự kiện) chạy trong `checked_run`: bytecode chỉ từ một thư mục trống riêng (`PYTHONPYCACHEPREFIX`, `-X pycache_prefix` + `-B` cho lần chạy `-I`), không ghi bytecode, không nhận biến `PYTHON*` của terminal (cùng lớp: một `PYTHONPATH` làm bước đọc sổ nạp onecrew khác runtime đã kiểm). Phép kiểm ngay trước khi ghi hook vẫn thấy và từ chối `.pyc` bị thay.
**Bộ kiểm gói:** thêm V31 (từ wheel đã cài, qua caller `_rollback` thật trên sổ thật: `.pyc` bị thay ngay sau phép so → bước đọc sổ và phân loại vẫn chạy nhưng file đánh dấu không xuất hiện, phép kiểm trước khi ghi hook từ chối; runtime cũ nguyên vẹn đọc và phân loại được). V31 FAIL trên gói dev4.
**Giữ nguyên:** 2.3.0.dev10, 2.2, sổ/hook/runtime thật; không push/tag/publish.

## v2.4.0.dev4 (02/11/2026) — bản thử 2.4 sau review Codex trên dev3 (ứng viên beta, chưa nghiệm thu)

Sửa hai finding của Codex trên `2.4.0.dev3` (`5a7a8ef`, wheel `35c78a49…`): 1 P1, 1 P3; mỗi finding có phản chứng đỏ trên baseline trước khi sửa (test của checkout và bước kiểm chạy trên chính gói dev3).

**P1 (2.4-S2) — bytecode sai vẫn được thực thi trước khi bị từ chối:** `hotfix.identity` nhận kết quả so `.pyc` của trình thông dịch rồi vẫn chạy `onecrew --version`, nên bytecode bị thay đã chạy trước khi `verify_installed` báo lỗi. Nay `onecrew --version` chỉ chạy khi mọi `.pyc` của nguồn trong wheel có câu trả lời và giống bản biên dịch (`unproven_caches`); trình thông dịch không trả lời, trả lời thiếu hay `.pyc` không đọc được cũng dừng ở đó (`entry_blocked`). Lần chạy của phép kiểm đọc bytecode từ thư mục trống riêng (`PYTHONPYCACHEPREFIX`), nên `.pyc` bị thay ngay sau phép so cũng không chạy. Cùng lớp lỗi ở quay lui: mọi `.pyc` của runtime cũ (mốc runtime cũ bỏ qua cache) được so trước khi chạy runtime cũ (`_old_runtime`, `venv_caches`); danh sách dài đi qua file thay cho dòng lệnh.
**P3 — tài liệu trong gói không đồng bộ:** gói dev3 có `docs/limits-final.md` (mục S2, B) khác `limits-s2.md`/`limits-b.md` và câu claim cũ; README ghi "chưa được Codex review" trong khi giới hạn ghi khác. Nay gói dựng từ snapshot có tài liệu đã sửa; test `test_v24_docs_sync` buộc mỗi mục của giới hạn tổng hợp đúng từng dòng file giới hạn của mốc; README trỏ về dòng trạng thái review trong mục Giới hạn.
**Bộ kiểm gói:** thêm V29 (từ wheel đã cài: `.pyc` bị thay → từ chối, file đánh dấu không xuất hiện, `onecrew` của venv không được chạy; runtime cũ khi quay lui cũng vậy; venv nguyên vẹn vẫn chạy) và V30 (tài liệu trong gói khớp nhau, README nêu đúng version/commit/wheel). Cả hai FAIL trên gói dev3.
**Giữ nguyên:** 2.3.0.dev10, 2.2, sổ/hook/runtime thật; không push/tag/publish.

## v2.4.0.dev3 (02/11/2026) — bản thử 2.4 sau review Codex vòng 1 trên dev2 (ứng viên beta, chưa nghiệm thu)

Sửa bốn finding của Codex trên `2.4.0.dev2` (`61862e6`): 2 P1, 1 P2, 1 P3; mỗi finding có phản chứng đỏ trên baseline trước khi sửa, và bốn vòng review độc lập trên S2 sau review Codex (vòng sửa thứ năm, `bb19222`, chỉ có test, chưa review lại riêng), hai vòng trên B (hồ sơ: `D:/OneCrewRuns/v24/codex-r1/`).

**F1 (P1, 2.4-S2) — runtime bị sửa vẫn được nhận là đúng artifact:** `verify_installed` băm NỘI DUNG từng file đã cài so với RECORD của wheel đã kiểm (không tin RECORD trong venv); kiểm `.pth` (đọc utf-8-sig), `.pyc`, link/junction, file lạ; mốc tạo venv (`pyvenv.cfg`, `Scripts/`, phần còn lại của site-packages) ghi vào sổ ngay sau lần kiểm đầu, mọi lần dùng lại/recheck/rollback phải khớp; không chạy chương trình nào trong venv trước khi mọi kiểm tĩnh đạt; kiểm entrypoint thật qua `PYTHONVERBOSE`; venv không có mốc trong sổ này không được dùng lại và không chạy; mỗi sổ một venv (`<venv>-<version>-<sha8>-<root8>`). Lệnh mới của chủ `support cleanup --venv` (bị từ chối trong phiên AI, kể cả viết tắt tùy chọn) xóa venv dở dang đúng hình dạng của sổ này, không qua link/junction, không bao giờ xóa venv đích đã khai.
**F2 (P1, 2.4-S2) — rollback lấy mốc dữ liệu sau khi diễn tập:** fence và ảnh chụp attempt/action đọc trong MỘT lượt SQLite trước khi chép, so lại ngay trước lần ghi hook đầu và sau lần ghi cuối; dữ liệu đổi giữa diễn tập và chuyển → `refused`/`refused_unsafe`, không bao giờ `rolled_back`/`switched` trên dữ liệu chưa diễn tập; vi phạm cửa sổ (hai phía) không còn là ngõ cụt: chủ chạy lại `rollback`/`install` thì diễn tập lại dữ liệu hiện tại; trạng thái báo theo hook đang chạy thật; claim có pid/thời điểm tạo/host, được gia hạn trước mỗi pha, claim của tiến trình đã chết trên máy này được tiếp quản; venv cũ được so với mốc ghi lúc cài trước khi rollback; không ghi đè file settings đã bị trỏ sang exe thứ ba.
**F3 (P2, 2.4-B) — chuỗi phụ thuộc dài bỏ lọt tri thức đã thu hồi:** bỏ `INPUT_DEPTH`; `working_context.decide` duyệt hết mọi attempt producer tới được qua `node.started` (stack tường minh, memo đầy đủ, chặn vòng, trần `MAX_WALK` thất bại đóng); attempt producer luôn lấy từ sổ theo node + receipt + generation, receipt nêu attempt khác → "không kiểm được" → `input_changed`, không bao giờ mặc định `publish`; lý do hold nêu rõ phần không kiểm được.
**F4 (P3) — hồ sơ:** số test tách total/pass/fail/skip/expected failure; gate `61862e6` ghi đúng 217 lượt module 2.097/2.097, receipt dùng chung log không cộng trùng; giới hạn S2 không còn ghi "alpha chỉ S1/S2"; báo cáo/hợp đồng/wiki đồng bộ với gói dev3.
**Bộ kiểm gói:** thêm V26 (chuỗi 6 node, thu hồi ở đầu → `engine verify` từ chối, node độc lập vẫn verify), V27 (venv đã chuyển bị sửa file giữ RECORD → recheck và install lại từ chối, hook không đổi), V28 (ghi vào sổ sau diễn tập rollback → không `rolled_back` trên dữ liệu chưa diễn tập); cả ba FAIL trên gói dev2, đạt trên code dev3; gói FINAL kiểm 28 bước.
**Giữ nguyên:** 2.3.0.dev10, 2.2, sổ/hook/runtime thật; không push/tag/publish.

## v2.4.0.dev2 (01/11/2026) — bản thử 2.4 đủ năm mốc S1, S2, A, B, C (ứng viên beta, chưa nghiệm thu)

**Gói thử dựng từ snapshot này** (các gói `2.4.0.dev1` trong `D:\OneCrewRuns\v24\pkg-trial` chỉ là lượt thử công cụ dựng/kiểm). Hướng dẫn: `docs/v24/HUONG-DAN-SUPPORT.vi.md`, `HUONG-DAN-SOURCE.vi.md`, `HUONG-DAN-CONTEXT.vi.md`, `HUONG-DAN-BUOC-0.vi.md`; báo cáo `docs/v24/BAO-CAO-2.4-2026-11-01.vi.md`.

**2.4-S1 — báo lỗi một lần:**
- `onecrew support report`: một mã `FB-…`, idempotent theo `--key`; tự gắn plan/revision/attempt/node/phiên bản khi chứng minh được; không tạo lỗi giả.
- `support bundle`: hồ sơ chẩn đoán local theo allow-list, manifest từng nguồn (included/missing/truncated/withheld/not_applicable…), lọc từng dòng, giới hạn 256 KB/file, 200 sự kiện/task, 8 MB/hồ sơ; không upload, không chạy chương trình.
- Sổ/runtime hỏng: báo cáo vào spool (`support-spool/`, `python -I -m onecrew.v2.support_spool`), `support import-spool` nhập đúng một lần; không ghi được thì báo NOT recorded.
- `support classify/link/status/show/confirm` và thông báo chuyển trạng thái qua outbox sẵn có; `support confirm` là lệnh của chủ, bị từ chối trong phiên AI.
- `install.doctor_facts()` tách khỏi `doctor` (output `doctor` không đổi).
- **2.4-S2:** `support target add` (lệnh của chủ), `artifact` (byte wheel = sha manifest, commit = cây đã kiểm của plan sửa), `install` (venv mới cạnh venv cũ, diễn tập trên bản sao, chuyển hook chỉ tại điểm an toàn, thiếu quyền `support_install:<id>` thì `blocked_by_authority`), `recheck` (check gốc chạy lại qua engine, tại đích hoặc bản sao có tên), `resume` (qua guard engine), `rollback` (chỉ khi runtime cũ đọc được dữ liệu hiện tại), `learn` (bài học trên root plan sửa).
- Sửa sau review độc lập S2 (S2-R01–R12, S1-R21/R22): wheel phải chứa đúng các file của commit đã kiểm (không thừa/thiếu, RECORD/METADATA đúng); venv mới `<venv>-<version>-<sha8>`, dùng lại chỉ khi đúng wheel; `support rollback` là lệnh của chủ và cần quyền `support_install:<đích>`; "đã cài/đã kiểm tại đích" tính theo hook đang chạy; khóa mặc định gồm phiên bản và ảnh, tái phát sau bản vá là báo cáo mới; quay lui chỉ khi runtime cũ đọc được, tính được trạng thái và biết mọi loại sự kiện mới; consumer không đọc được thì từ chối; intent trước mỗi lần chuyển, claim độc quyền, kiểm cửa sổ chuyển; `target add` không đổi được (trừ `--replace`); thêm mẫu bí mật; bản sao diễn tập chỉ chứa blob cần thiết và bị xóa, có `support cleanup`.
- Sửa sau review độc lập S1 (R01–R08, P3): lọc bí mật thay đúng phần bí mật (header, URL, `export`, `--password`, dạng khóa, PEM) cả trong `feedback.json`; `--task` chỉ nhận root/task con, hồ sơ không chứa báo cáo khác; giới hạn 8 MB áp cho mọi nguồn (`over_cap`); "đang xử lý" chỉ khi plan đã duyệt và còn mở; spool giữ phiên bản lúc báo, file spool hỏng vào `rejected/`, spool từ thư mục con được nhập; luật chặn `support confirm` trong hook, `--by owner` bị từ chối trong phiên AI; gửi lại cùng nội dung không `--key` nhận lại đúng mã; task support không bao giờ chạy được; bản 2.2.0.dev18/2.3.0.dev10 vẫn đọc được sổ có bản ghi support.

**Mốc 2.4-C** (hướng dẫn: `docs/v24/HUONG-DAN-BUOC-0.vi.md`):
- Đề xuất bước 0 (W47) có ba trường tùy chọn `preserve`, `investigation`, `estimate`; dùng một trường là bật luật thẻ (điều giữ nguyên khi sửa/xoá, ước lượng có căn cứ hoặc "chưa đủ dữ liệu", điều tra có đường dẫn rõ và trần, unknown mà việc duyệt chờ). Đề xuất không dùng thì kiểm như cũ. `plan step0 show <plan> [--json]` xem thẻ, chỉ đọc.
- Khảo sát bước 0 bị từ chối khi trần điều tra đã hết, và chỉ đọc trong đường dẫn điều tra; unknown còn mở thì vẫn giữ việc duyệt.
- Capability tùy chọn `execution-mode`: engine chọn và ghi `run_now` / `overlap` / `continue_worker` / `tools` / `wait` kèm lý do (Q2, `node.started`, sự kiện mới `workflow.mode` lớp B); đọc↔ghi cùng file và nhãn `resources` chung không được chạy song song; chi phí bàn giao chưa đo là `unknown`, không phải 0; kiểm không cần model chạy cạnh worker không tạo task con. Không adapter nào giữ phiên model (`session.reuse: false`). Root không khai capability chạy như 2.3.
- `engine measure <plan>`: số đo từ sổ (chỉ đọc), thiếu quan sát là `unknown`.

**Mốc 2.4-A và 2.4-B** (hướng dẫn: `docs/v24/HUONG-DAN-SOURCE.vi.md`, `docs/v24/HUONG-DAN-CONTEXT.vi.md`):
- **2.4-A — worker tự đọc nguồn theo quyền:** node khai `sources` {read, max_rounds, max_chars_per_round} xin `list`/`search`/`read`/`page` bằng JSON kèm `continuation`; lượt sau của chuỗi thực thi trên cây làm việc đã ghim ở lần chạy đầu (file sửa dở và chưa commit có mặt, hard link và junction bị từ chối) và đưa trang kết quả có nguồn, dòng, blob, coverage, `withheld`, `next_cursor`. Root cấp quyền đọc bằng `authority.read` (không có thì `scope.owned` + `understanding.target.paths`); node đọc ngoài quyền bị từ chối khi revise. Giới hạn theo yêu cầu, theo lượt (Kiro 15 000 ký tự tính cả schema), theo chuỗi (`max_rounds` đếm từ sổ, không reset khi đổi task con hay controller); yêu cầu lặp bị từ chối, trang tiếp được phép. Node báo cáo cũng tiếp tục được. Node không khai `sources` giữ nguyên prompt, schema và receipt của 2.3. `onecrew.paging` và `onecrew.v2.source_tools` vào wheel. Hướng dẫn: `docs/v24/HUONG-DAN-SOURCE.vi.md`.
- **2.4-A sau review độc lập:** mọi tên Git hợp lệ được khớp hoặc thành dòng `withheld` có lý do (không âm thầm biến mất, coverage nói rõ); `max_rounds` là trần cứng tính trên mọi lượt của node qua các chuỗi (vượt thì giữ `rounds_exhausted`); `authority.read` cũng giới hạn `read` của node; yêu cầu lặp so theo yêu cầu thực; dòng bị cắt có dấu, mọi dòng khớp của file dài đọc tiếp được; receipt ghi kết quả không giao và lỗi lúc chạy; bằng chứng chuỗi không đọc được thì từ chối lượt; node ghi file vẫn phải ghi ít nhất một file ở câu trả lời cuối.
- **2.4-B — working context theo consumer:** mỗi attempt được giao tri thức hay đọc file có sự kiện `knowledge.delivered` (lớp A); lượt tiếp theo nhận `delta` (thu hồi, đổi, mục bắt buộc mới) thay vì cả lịch sử; candidate dựng trên mục `must`/`fact` đã thu hồi hay đổi, file đã đọc đã đổi, hay đầu vào như vậy không được công bố hay kiểm như hiện hành: node chạy lại ở thế hệ mới trong ngân sách còn lại (tối đa 2 lần) hoặc bị giữ `knowledge_changed`; nhánh độc lập chạy tiếp. Lệnh chỉ đọc `onecrew wiki consumers --plan P`. Hướng dẫn: `docs/v24/HUONG-DAN-CONTEXT.vi.md`.

## v2.3.0.dev10 (31/10/2026) — beta 2.3 sau review Codex trên dev9

**Bản beta (prerelease), chưa nghiệm thu, chưa được Codex review lại; không phải bản ổn định `2.3.0`.** Kết quả, giới hạn và lệnh thử: `docs/v23/BAO-CAO-2.3-DEV10-2026-10-31.vi.md`.

So với beta `2.3.0.dev9`:
- **P1:** một file đổi thành hard link hay một thư mục đổi thành junction giữa lúc OneCrew kiểm và lúc đọc không còn lọt vào kho Git, kho snapshot, cây bàn giao hay trang wiki. Git không tự duyệt cây làm việc khi tính danh tính nữa: mỗi file được mở, xét trên handle và giữ mở trong lúc git đọc.
- **P2:** gate tách đạt, hỏng, bỏ qua, expected failure và unexpected success; expected failure không bao giờ được tính là đạt (chỉ được chấp nhận khi testcase khai rõ). Ngoại lệ U1 hẹp `U1-20261031-V23-GATECOUNT-1..3` theo quyền chủ sở hữu 31/10.
- Báo cáo dev9 đính chính nguồn thực thi của gate (source trên snapshot; 22/217 lượt có ghi nhận dùng wheel) và số test B2 (13).

## v2.3.0.dev9 (30/10/2026) — bản beta 2.3

**Bản beta (prerelease), chưa nghiệm thu, chưa được Codex review lại; không phải bản ổn định `2.3.0`.** Dùng trên bản sao project và sổ riêng. Gate 2.2 đầy đủ chạy trên đúng snapshot của gói; kết quả, giới hạn và lệnh thử: `docs/v23/BAO-CAO-2.3-DEV9-2026-10-30.vi.md`.

So với alpha `2.3.0.dev8`:
- **B2:** các lệnh chỉ xem trạng thái (`plan show`, báo cáo, so evidence, handoff) không còn băm nội dung tên có hard link hay nằm sau junction vào kho object của repo; chỗ đó là marker từ dữ liệu stat, nên artifact đổi vẫn thấy đổi. Sparse checkout không mở lại đường đọc này.
- Ảnh chụp phạm vi node chỉ lưu byte khi hai lần đọc khớp nhau (một thư mục thành junction giữa hai lần không để lại gì trong sổ).

## v2.3.0.dev8 (30/10/2026) — bản alpha 2.3

**Bản alpha (prerelease), chưa nghiệm thu, chưa được Codex review lại; gate 2.2 đầy đủ chưa chạy trên snapshot này.** Dùng trên bản sao project và sổ riêng. Hồ sơ alpha: `docs/v23/ALPHA-2.3.0.dev8.vi.md` (bước thử, kết quả mong đợi, giới hạn, danh sách blocker A/B/C, phần còn lại cho beta).

So với `2.3.0.dev7` (không bàn giao):
- **Không đọc file có tên khác trên đĩa (AL-01):** ảnh chụp phạm vi node cho worker (và định danh thư mục không Git) từ chối file có hard link, vì tên kia có thể là `.env`, thư mục home hay sổ; trước đây nội dung đó vào snapshot và prompt của worker. Node không chạy, lý do nêu tên file.
- **Trình đọc wiki không đi theo link (AL-02):** trang là hard link hay symlink không được đọc, junction trong wiki không được đi vào, thư mục wiki là link không được đọc; mỗi tên được nêu trong `problems` của `wiki pages`.
- **Script thử một lệnh có luồng alpha:** `verify/thu-goi.ps1` chạy thêm `verify/alpha_flow.py` (init và wiki, tri thức cho task, kết quả đã kiểm thành tri thức, root mới dùng lại, guard hard link) và để lại `feedback-alpha.zip` để gửi lại.
- Race `.onecrew` của index tạm khi tính artifact (có từ 2.2) đã sửa (`git rm --cached -f`).

## v2.3.0.dev7 (30/10/2026, không bàn giao: thay bằng 2.3.0.dev8) — bản thử 2.3: wiki của project, tri thức có bằng chứng, dọn và tiếp quản

**Bản thử (prerelease), chưa nghiệm thu, chưa được Codex review lại.** Dùng trên bản sao project và sổ riêng. Chưa có nghiệm thu của chủ sở hữu, pilot thật và provider thật đầy đủ, nên đây không phải bản ổn định `2.3.0`. Bản này dựng trên beta 2.2 (`2.2.0.dev18`). Các bản 2.2.0.dev4…dev19 không có mục ở đây; ghi chú của chúng nằm trong báo cáo và gói bàn giao từng bản.

Người dùng có gì:
- **Wiki khi init (2.3-A1, WI-01…05):** `onecrew init` tạo khung wiki `docs/wiki/` (`README.md`, `project.md`, `lessons.md`), hoặc dùng lại wiki đã có hay thư mục `wiki.paths`. Chạy lại không đổi byte nào. Init không ghi đè, không ghi ra ngoài repo hay qua link/junction. `config.json` hỏng thì init dừng và không ghi gì (bản trước ghi đè nó). Project đã init bằng 2.2: init lại giữ sổ, config, plan, ngân sách và hook. Hướng dẫn: `docs/HUONG-DAN-WIKI.vi.md` §0.
- **Đọc và giao tri thức (2.3-A1):** worker của engine nhận gói tri thức có nguồn từ wiki và sổ, theo quyền đọc của node, độ liên quan và trần. Mục bắt buộc không bị cắt âm thầm. Worker đọc tiếp bằng con trỏ. Receipt niêm phong đúng gói đã giao. Lệnh: `onecrew wiki show|read|pages`.
- **Ghi tri thức có bằng chứng và dùng lại (2.3-A2):** điều check của node chứng minh được thì được ghi cho project. Root mới, process mới dùng lại. Sửa, thay thế, thu hồi, lưu trữ có hiệu lực ở lần truy xuất sau. Cập nhật đồng thời không mất bản nào. Chủ thể tri thức thuộc project đã ghi: hai project cùng `--key` là hai chủ thể. Lệnh: `onecrew wiki record|withdraw|archive|summarize|export|history`.
- **Dọn và tiếp quản (2.3-B):** controller `engine step` chết thì `onecrew executor recover` xác nhận đã dọn trước. Bước sau giữ node, chạy lại đúng một lần trong ngân sách cũ.
- **Hook và plan lint** (sửa của beta R15 B1, B2, B4, B6, như `2.2.0.dev19`): `Remove-Item Env:X -ErrorAction SilentlyContinue` không bị coi là ghi file; `<`, `>`, `|` trong chuỗi có dấu nháy không bị đọc là chuyển hướng; `plan lint` nói rõ `budget.max_calls` không được đếm cho phiên AI dưới hook; hook Stop nhắc một lần khi mốc chờ chủ sở hữu.
- **Sửa lỗi:**
  - các finding Codex review dev2 (P2-01…03), dev3 (bản ghi general không áp dụng), dev5 (P2-A script thử, P2-B khóa tri thức giữa project, P2-C `.env.example`, P2-D `[S1][S2]`);
  - verifier: mẫu `ids` có neo hay cờ; với `(?i)` hai id chỉ khác chữ hoa/thường là một id; kiểm `ids` không thấy id nào thì không đạt; tên 8.3 bị từ chối ngay lúc đề xuất; thư mục không Git có `.env` định danh được; file bị cấm không bị đọc dưới tên khác (artifact Git có một tên là hard link hay đi qua junction thì lượt kiểm và `plan approve` dừng, nêu lý do, trước khi Git đọc nội dung); nguồn viết trần giữ dấu chấm đầu và `./x`, `../x` chỉ tính cạnh trang: trước đây nguồn thiếu ở thư mục cha có thể đạt nhờ file cùng tên ở gốc repo (lỗi có từ 2.2);
  - tri thức: yêu cầu đọc tiếp qua nâng cấp giao đúng chủ thể; mục 2.2 khóa `lesson-` không trùng lesson thật; `wiki history` không lộ mã project khác; thu hồi được mục ở trang ngoài ngân sách đọc.
- `onecrew --version`.

Thay đổi hành vi cần biết: kiểm `ids` không thấy id nào thì không đạt, kể cả với plan đã duyệt trước bản này (bỏ kiểm `ids` khỏi mốc hoặc thêm id); `plan approve` và verifier từ chối cây làm việc Git có hard link hay junction, kể cả repo cố ý giữ file trùng bằng hard link (tách thành bản sao rồi duyệt, kiểm lại).

Cài, thử, giới hạn và cách quay về 2.2: `docs/v23/BAO-CAO-2.3-DEV7-2026-10-30.vi.md` (§3.1, §4), `docs/v23/tools/limits-final.md`, `README.md` của gói.

## v2.2.0.dev3 (v22-trust-fixes: sửa các lỗi Codex tìm ở 8383446, không thêm tính năng)

- **Hook di động** (P0.1): không có `--project`, hook gom các plan áp dụng cho một lời gọi và chặn nếu **bất kỳ plan enforce nào chặn**, theo hai vai: **plan của phiên** (`CLAUDE_PROJECT_DIR`) xét cả lời gọi; **plan của repo khác mà lời gọi chạm tới** (repo chứa đường dẫn Edit/Write ghi — cwd không phải nơi tìm của Edit/Write —; với lệnh shell: repo chứa cwd và repo của mọi đường dẫn ghi đọc được) chỉ xét những gì lời gọi làm trong chính repo đó (đường dẫn ghi nằm trong repo ấy, cộng `bash_deny` và luật nhắc tên); plan `stopped_with_report` của nó chỉ từ chối lời gọi có ghi vào repo của nó. Mỗi nơi tìm chỉ lên tới gốc repo của nó. Plan chưa duyệt (accepted, proposed), ở chế độ log hay vắng mặt không bao giờ nới lệnh chặn của plan khác. Luật nhắc tên của hook xét từng đoạn của lệnh. (Bản dev3 đầu chỉ xét `CLAUDE_PROJECT_DIR`; bản thứ hai cho "plan tìm thấy đầu tiên thắng" rồi gom mọi plan xét cả lời gọi, nên plan của một repo anh em hay của checkout cha khóa nhầm một phiên worker.) Hệ quả có chủ ý: thư mục scratch hay worktree lồng nằm trong repo khác có plan enforce vẫn bị plan đó chặn. Luật nhắc tên chỉ khớp `.onecrew` (và `onecrew/plans`) khi đó là một thành phần đường dẫn, không phải đuôi của `11.OneCrew`. Khi phiên không có plan enforce của riêng nó, plan của repo chứa cwd từ chối cả đích ghi không giải được (`$PWD/x`), như 2.1. Giới hạn (bãi đỗ): phiên mở ở thư mục con của project mà AI ghi một `.git` giả trong thư mục con thì mất plan của project; khóa sổ đăng ký không nguyên tử tuyệt đối; chi phí tìm plan mỗi lần gọi hook chưa tối ưu; cách hook đọc lệnh shell là văn bản nên còn các ca: `cd x && …`, `Set-Location` hay `git -C` trong cùng lệnh (cwd đổi giữa lệnh), một junction tạo ngay trong cùng lệnh, lệnh con trong `$(...)`, dấu backtick, `Get-Content (...)` hay `where { }`, và ký tự thoát backtick của PowerShell. Mất `<project>/.onecrew/active-plan.json`, hay cả `.onecrew/` (mất `config.json`), mà bản sao state-root của chính project còn thì vẫn tìm thấy và vẫn chặn: sổ `hook-projects.json` (project → state-root, trong state-root mặc định, ngoài project) do **hook tự ghi mỗi khi đọc được `config.json`** và `onecrew init` cũng ghi; sổ nằm trong `permissions.deny` và danh sách đường dẫn được bảo vệ, ghi bằng khóa + file tạm đổi tên, và không xóa mục của ổ đĩa không gắn.
- **Reviewer** (P0.2, P0.3): cây reviewer = index thật + sửa đổi của file đã có trong index (file mới đã `git add` có trong diff); cây đó phải trùng artifact (so bằng danh sách đường dẫn của git): chỗ khác nhau — file chưa theo dõi không ignore, `git rm --cached`, `git add -f` file ignore chưa commit, assume-unchanged/skip-worktree, submodule chưa stage — làm mốc `inconclusive`, lý do nêu đường dẫn và các nguyên nhân (`not_shown` trong biên nhận); artifact lấy trước, cây chụp một lần, diff cắt từ đúng cây đó (biên nhận có `base_tracked` và `tracked_tree`); thay đổi trong lúc review → `inconclusive`; artifact không dựng được → biên nhận `inconclusive` có lý do, không làm `verdict run` lỗi. Diff cắt với `--ignore-submodules=none` (cấu hình `ignore=all` không giấu một submodule đổi commit, và nó không bao giờ là thay đổi trung lập), `--submodule=short` (`diff.submodule=log` không làm mất dòng tiêu đề), `--no-renames`, tiền tố cố định; mỗi đường dẫn đổi phải có đúng dòng `diff --git a/<path> b/<path>` (so cả dòng, theo cách git viết tên có ký tự đặc biệt). Đường dẫn git chỉ hiện `Binary files differ`: file **nhị phân thật** — MỌI bản đang có (cũ và mới) có byte NUL và không bản nào bắt đầu bằng BOM UTF-16/32 (ảnh, jar) — đã được diff nêu tên và **không** chặn pass; mọi trường hợp khác (chữ bị `-diff`, diff driver binary hay `core.bigFileThreshold` giữ ra khỏi diff; nhị phân bị thay bằng script; chữ bị chèn NUL; chữ UTF-16/32) → `inconclusive` kèm tên. Giới hạn: phép thử là byte NUL nên file chữ chỉ có NUL (không BOM, một bản) bị coi là nhị phân. Các lệnh git liệt kê đường dẫn chạy ở gốc repo (`diff.relative=true` không giấu file khi chạy từ thư mục con).
- **Trung lập** (P0.4): bỏ danh sách mặc định (`NEUTRAL_DEFAULT`); chỉ `scope.neutral` hợp đồng tự khai mới trung lập, và một submodule (gitlink) đổi commit không bao giờ là thay đổi trung lập, kể cả khi đường dẫn của nó nằm trong `scope.neutral`. Đổi hành vi so với 2.2.0.dev2: commit chỉ sửa `docs/**`, `*.md`, `CHANGELOG*` nay chạy lại mốc `command` nếu hợp đồng không khai.
- **Kế thừa** (P0.6): chữ ký gồm tiêu đề, verifier, `covers` và toàn văn từng output mốc phủ (sửa chữ output không phủ vẫn giữ pass); mốc `reviewer` kiểm lại luật độc lập cho revision mới. Giới hạn còn lại (bãi đỗ): output được nhận biết bằng vị trí (`O<n>`), nên chèn một output lên đầu đổi chữ của mọi `O<n>` sau nó và các mốc phủ chúng chạy lại; chưa phân biệt đổi chữ với đổi nghĩa.
- **Report** (P0.5): `plan report` dùng cùng view mốc với `plan show` và in đúng trạng thái đó (mốc `stale` hiện `cũ`, mốc kế thừa hiện `pass (kế thừa từ bản N)`, kể cả dòng kết luận), không in kết quả verdict cuối; ghi chú reviewer của lần pass được kế thừa có trong report. Plan đã nghiệm thu được đọc **từ bản ghi `plan.accepted`** (verdict ghi sau cùng của mỗi `receipts`), không tính lại bằng luật mới và **không có chữ `kế thừa`/`trung lập`/`stale`** (cái đã mang pass qua nằm trong `carried` của sự kiện), nên một plan đã nghiệm thu bằng 2.1 hay luật cũ vẫn đọc đúng như lúc nghiệm thu và report của nó **không đổi byte**. Ngoại lệ duy nhất: plan đã nghiệm thu bằng bản dev2 nhờ verdict kế thừa — report cũ ghi sai "chưa có verdict" cho mốc đó, nay hiện pass mà nó được nghiệm thu bằng. `accept` từ chối artifact toàn số 0. `plan digest` không đổi.
- **UTF-8** (P0.7): mọi lệnh hook ép stdout/stderr UTF-8 (module và `onecrew hook <verb>`); `init`/`merge_settings` chỉ thay handler do OneCrew cài, giữ handler của công cụ khác có nhắc tên module.
- **`init` nhận handler của mình theo cấu trúc** (sau review thứ năm và thứ sáu): `is_ours` không còn tìm chuỗi `from onecrew.v2.hook_cli import main` + `hook check` trong cả dòng lệnh (một `echo` hay `audit-tool python -c "<mã OneCrew>" hook check` bị `merge_settings` xóa nhầm). Nay tách dòng lệnh như shell (dấu nháy kép/đơn gom từ, `\"` trong nháy kép là một nháy, `\` còn lại là ký tự thường như trong đường dẫn Windows; chương trình lấy tên file sau khi bỏ nháy) và chỉ nhận các dạng OneCrew tự sinh: `onecrew[.exe|.cmd] hook <verb>` (chuỗi lệnh hay `args`), và `python [-u|-B|-E|-I|-s|-S] [-X <x>|-X<x>] -c "<đúng mã checkout>" [--project P] [--state-root S] hook <verb>` (mã sau `-c` phải khớp từng chữ với mã `hook install --print` sinh, 2.1 và 2.2; cả dạng `-X utf8` và `-Xutf8` của verify-kit, dạng cũ có `--project`/`--state-root`, đường dẫn python có dấu cách); mỗi tùy chọn tối đa một lần. Ở dạng chuỗi lệnh (không có `args`, nên một shell đọc nó), từ nào có `;` `&` `|` `<` `>` `$` hay backtick, hoặc dòng có xuống dòng, thì không phải của ta (`--project D:/p;audit-tool hook check`, `--project "$(audit-tool --log)"`); riêng từ mã sau `-c`, vốn có `;` và `(`, chỉ bị từ chối khi có `$` hay backtick. Không nhận: `echo`, công cụ audit/wrapper đứng trước, mã có thêm gì, verb lạ, tham số thừa hay lặp, handler chỉ nhắc tên module, handler khác trong cùng entry. Giới hạn: dạng lệnh OneCrew sinh ở bản sau phải được thêm vào `is_ours` (trước đó handler ấy được giữ, không bị xóa nhầm). `onecrew doctor` nay tìm chương trình của handler dạng chuỗi lệnh (từ đầu của dòng), không coi cả dòng là đường dẫn file (trước đó báo `hook_stale`).
- **Luật nhắc tên `.onecrew`** (sau review thứ năm và thứ sáu): `.onecrew` được tính là nhắc tới khi sau nó (và sau các dấu chấm cuối) KHÔNG có chữ, số, `_` hay `-`: nên `.onecrew.` và `.onecrew..` (Windows bỏ dấu chấm cuối), `.onecrew{,.bak}`, `.onecrew*`, `.onecrew,x`, `.onecrew)`, `.onecrew::$INDEX_ALLOCATION` đều là thư mục được bảo vệ, còn `.onecrew.bak`, `.onecrew-old`, `.onecrew_old`, `.onecrew.bak.`, `11.OneCrew/x` vẫn là tên khác. Phần miễn trừ `.onecrew/scratch/` không còn là `replace` mù: một đường dẫn `.onecrew/…` chỉ được miễn khi đọc được theo CẢ HAI cách — từ shell (tới khoảng trắng, ngoặc, `;`, `&`, `|`, `<`, `>`, nháy) và chuỗi dài nhất có thể (tới nháy hoặc backtick kế tiếp, hay hết đoạn lệnh; một đường dẫn trong chuỗi có thể chứa khoảng trắng, ngoặc và `;`) — mà vẫn nằm dưới `.onecrew/scratch/` theo từng thành phần, sau khi đổi `\` thành `/`, bỏ khoảng trắng và dấu chấm cuối của mỗi thành phần như Windows (một thành phần chỉ toàn dấu chấm là `.`/`..`) và gấp `..` như `posixpath.normpath`. Vì vậy `.onecrew/scratch/../config.json`, `.onecrew\scratch\..\config.json`, `.onecrew/scratch/a/../../config.json`, `.onecrew/scratchy/..`, `.onecrew/scratch /..`, `.onecrew/scratch/a(/../../config.json`, `.onecrew/scratch/a;/../../config.json` bị chặn, còn `.onecrew/scratch/x`, `.onecrew/scratch/a/../b`, đường dẫn scratch có khoảng trắng hay ngoặc mà không thoát ra, `pytest -o cache_dir=.onecrew/scratch/cache` vẫn qua. Chỉ từ chứa đường dẫn đó được cắt khỏi văn bản, nên một tên được bảo vệ khác đứng cạnh (`cp .onecrew/scratch/x policy.json`) vẫn bị bắt. Hệ quả: `.onecrew/scratch,out` (thư mục `scratch,out`, không phải scratch) bị chặn, và một đường dẫn scratch trong chuỗi không nháy, theo sau bởi một chuỗi khác mà gấp `..` lên khỏi scratch, có thể bị chặn thừa (đó là hai ca chặn thừa đã biết). Ca bỏ sót còn lại là giới hạn (cách hook đọc lệnh shell là văn bản, không chạy nó): đường dẫn tính lúc chạy (`'\x2e\x2e'`, `os.path.join('.onecrew/scratch/', '..', 'config.json')`, `'.one' + 'crew'`) và tên ngắn 8.3 không thấy được.
- **Mã cây** (D3): mã cây đọc từ biên nhận/sổ phải là hex 40/64 và đứng sau `--end-of-options`; plan không có cây tracked-only dùng được → biên nhận `inconclusive` có lý do, không làm `verdict run` lỗi.
- Tests: `tests/test_v2_trust_fixes.py` (mỗi lỗi có test thất bại trên mã có lỗi, `8383446` hoặc bản dev3 đầu `38e1703`; vài test bảo vệ hành vi không được đổi xanh cả trên mã cũ). Bốn test của `tests/test_v3_verify_cost.py` đổi kỳ vọng theo D4/D5 (`test_the_default_neutral_paths_are_read_not_written`, `test_neutral_globs_do_not_cross_a_slash_except_double_star`, `test_an_untracked_file_is_never_in_the_diff_and_verdict_diff_makes_no_call_and_writes_nothing`, `test_the_same_after_a_pass_the_pass_remembers_the_tracked_tree_not_the_untracked_files`); hai kiểm version đổi sang `2.2.0.dev3`. `docs/v2-verify-cost.vi.md`.

## v2.2.0.dev2 (đợt 1: kiểm rẻ hơn, giữ sáu bất biến)

- Verdict được **kế thừa** sang revision mới đã duyệt khi mốc (tiêu đề + verifier) byte-giống và artifact giống, hoặc (mốc `command`) chỉ khác ở `scope.neutral`; `plan show` có `carried_from`, `neutral_diff`, `stale`; `verdict run` kiểm thứ tự và "đã đạt" trước khi chạy. Không thêm sự kiện/bảng. `docs/v2-verify-cost.vi.md`.
- `scope.neutral` (mặc định đọc là `docs/**`, `*.md`, `CHANGELOG*`, không ghi vào hợp đồng); `accept` nhận verdict kế thừa qua khác biệt trung lập và ghi `carried`.
- Reviewer chỉ đọc file có theo dõi: diff giữa hai cây tracked-only ghi sẵn trong sổ (`base_tracked` ở `plan.approved` đầu tiên, `tracked_tree` ở biên nhận reviewer; cơ sở = lần pass gần nhất của chính mốc đó với cùng cấu hình, chưa có thì `base_tracked`; thiếu cả hai thì lỗi rõ, không có đường dự phòng); `verdict diff --plan P --milestone M`, `verdict artifact --plan P`. `owner accept --artifact-sha` chỉ nhận mã hex 40/64 và git nhận mã sau `--end-of-options`.
- `plan lint`: `criterion_literal_present`, `criterion_vs_non_goal` (cảnh báo), `criterion_no_fail_clause` (từ chối), `--ack-criteria`; `unknowns_missing` + `understanding.no_unknowns_because` ở lint và approve. `examples/contract-template.json`.
- `plan report`: mục "Reviewer ghi chú ngoài tiêu chí".
- Tests: `tests/test_v3_verify_cost.py`. Hai assert cũ đổi theo luật mới (nêu ở đây để không lẫn): `test_a_verdict_does_not_survive_an_amendment` nay đổi chính mốc M1 (mốc không đổi thì kế thừa); `test_a_diff_over_the_cap_is_not_reviewed_in_part` nay commit file lớn (file chưa theo dõi không vào diff); hai kiểm version đổi sang `2.2.0.dev2`.

## v2.2.0.dev1 (G2: cài xong là có sổ, hook và lệnh chủ sở hữu)

- `onecrew init [--state-root P] [--shared] [--yes]`: tạo sổ, `plans/owner-rules.md` (mẫu trong wheel), `.onecrew/config.json`, và gộp hook vào `.claude/settings.local.json` (`--shared`: `settings.json`) theo khóa; có `.bak`, hỏi y/N, chạy lần hai không đổi byte nào. Kiểm Claude CLI (tìm thấy + đã đăng nhập), không tự đăng nhập; thiếu thì vẫn ghi và exit 1.
- Hook do init ghi dùng chính file `onecrew` đã cài (`onecrew hook <verb>`), không ghi đường dẫn python, repo hay `--project/--state-root`; hook lấy project từ `CLAUDE_PROJECT_DIR` và sổ từ `.onecrew/config.json`. `permissions.deny` thêm `owner approve|accept|enforce|record`. `hook install --print` (checkout) giữ dạng cũ, dùng chung danh sách deny.
- `onecrew doctor`: một dòng PASS/WARN/FAIL cho Python, git, Claude CLI, đăng nhập, sổ, config.json, hook, plan đang mở; exit 1 khi có FAIL.
- `onecrew owner approve|accept|enforce|record`: thay bốn script `scripts/owner/*.ps1`; cố định `--by owner`, bị từ chối trong phiên AI như các động từ cũ.
- Ba lệnh mới nói tiếng Anh, `ONECREW_LANG=vi` đổi sang tiếng Việt (`onecrew/v2/messages.py`); output cũ không đổi. `docs/README.en.md`.
- Mẫu quy tắc `owner-rules.vi.md` + `owner-rules.en.md` là package data của wheel (`onecrew/templates`); `plan rules init` đọc từ đó (mặc định bản vi như trước, `ONECREW_LANG=en` cho bản en). Lệnh `plan`/`verdict`/`owner` không có `--state-root` thì đọc `.onecrew/config.json` của project.
- `tests/test_g2_install.py`.

## v2.2.0.dev0 (G1: lõi v2 cài được bằng pip)

- Wheel chỉ gồm lõi + `onecrew.v2` + `onecrew.v2.verifiers` (danh sách `py-modules` trong `pyproject.toml`); lệnh `onecrew` của wheel là router v2 (`plan`, `verdict`, `hook`), `onecrew_cli.py` ở checkout vẫn là router đầy đủ v1 + v2. Chi tiết: `docs/v2-core.vi.md`.
- Tách lõi khỏi v1 bằng cách dời phần dùng chung (một nguồn; v1 import lại): `budget_core` (đọc ngân sách), `independence`, `task_intake` (`submit` của task neo, `outcomes`, `recommend`), `onecrew/v2/changes.py` → `onecrew/solution_changes.py`. Sổ cái, loại và payload sự kiện không đổi; sổ cũ đọc y nguyên.
- Tìm Claude CLI theo hệ điều hành (PATH, rồi `~/.local/bin`, npm global...), lỗi nêu mọi nơi đã tìm; model mặc định (Opus 5.5) ở một module (`onecrew/v2/claude_cli.py`), ghi đè bằng `ONECREW_DEFAULT_MODEL`.
- `tests/test_g1_core.py`: closure import, tìm CLI (posix/nt giả lập), metadata đóng gói, model mặc định.
- Không còn trong wheel: `onecrew-entry-mcp` (chạy từ checkout).

## v2.1.0 (20/10/2026) có gì

v2 = **hợp đồng công việc cho AI**: AI chỉ chạy trong một hợp đồng đã được chủ sở hữu duyệt. Sáu bất biến cứng: không có hợp đồng đã duyệt thì không chạy; ngoài phạm vi thì bị chặn; hết ngân sách thì dừng; mốc chưa có verdict thì không qua; tác giả không tự duyệt việc của mình; chỉ con người mới nghiệm thu.

Phần lõi v2 (lát L1–L2, item 3, item 4):
- Sổ cái (ledger) ghi biên lai và verdict cho từng mốc (L1).
- Hook cho Claude Code: PreToolUse, UserPromptSubmit, Stop; `hook install --print` in cấu hình (L2).
- Verifier `command`: chạy lệnh kiểm trên checkout sạch (L1).
- Verifier `reviewer`: model độc lập duyệt diff theo 3 tiêu chí (item 3).
- Mốc `owner-manual`: chủ sở hữu tự đọc và nghiệm thu (L1).
- `plan report` (kết luận tiếng Việt 4 dòng + 7 mục) và `plan digest` (item 4).

v2.1 bổ sung:
- Job 9: trường `origin`, `decisions`, `items[].source`, trường trình bày; cổng `approve` chặt khi có `<state-root>/plans/owner-rules.md`; `plan advise` (cố vấn Opus, 3 câu hỏi cố định so với file quy tắc; bắt buộc khi `decisions` không rỗng hoặc cỡ M/L); `plan rules init|show`.
- Job 11a: `plan lint`; verifier `command` fail-closed (đầu ra rỗng, chạy nhanh mà im lặng, ký tự điều khiển, thiếu file thực thi → `inconclusive`); hook Stop nhả khi có biên lai chưa verdict hoặc câu hỏi chủ sở hữu đang mở; `amend` sau khi duyệt chỉ đóng băng lại các mốc bị đổi.

Bằng chứng: 14 job thật trong `state-v2-real` (11 đã nghiệm thu), khoảng 290 test.

## Giới hạn đã biết

- Hook Stop chỉ thấy biên lai sau khi lệnh chạy xong; cần sự kiện "bắt đầu chạy" — **dự kiến 11b**.
- `contract.validate` vẫn nhận ký tự điều khiển trong `argv`; chỉ `plan lint` và verifier bắt được.
- Mốc `command` im lặng luôn `inconclusive` dù đạt: lệnh kiểm phải in kết quả.
- Verifier `command` của Flutter không giải được path dependency anh em trên checkout sạch; chạy kiểm trong worktree (như `run_flutter_checks.py`).
- Tỉ lệ bắt lỗi của cố vấn chưa được đo.
- Quy tắc R1 trong `examples/owner-rules.vi.md` ghi sai ("debug cho chạy thử"); đúng: build debug khi đang phát triển, chỉ release khi đã xong, test đạt và chủ sở hữu đã thử trên thiết bị — **dự kiến sửa ở 11b**.
- Hook chỉ đọc chữ của lệnh; script Python dựng lệnh bằng ghép chuỗi vẫn qua lớp hook (xem `docs/v2-parking-lot.vi.md`).
- Reviewer: mỗi lần gọi tốn khoảng 9k token cache; diff quá 120 KB không được review (`inconclusive`); chưa kiểm `evidence.file` có nằm trong diff.
- `plan report` chưa đếm số lệnh/token, chưa có HTML.
- Một số test v1 đỏ sẵn có (ví dụ `test_sandbox_gate` khi đường dẫn worktree dài); không do v2.

## Cách chạy

CLI (từ thư mục repo):

```
<python> -X utf8 onecrew_cli.py --project <repo> --state-root <state-root> plan|verdict|hook ...
```

- Hook: `hook install --print` in cấu hình, dán vào `.claude/settings.json` của project.
- Chạy verifier: `verdict run --plan <tên> --milestone <Mx>`.
- Báo cáo: `plan report`, `plan digest`.
- Các động từ của chủ sở hữu (`approve`, `accept`, `enforce`, `verdict record --by owner`) chỉ gõ từ terminal của chính chủ sở hữu, không từ phiên AI.
- Sổ cái và hợp đồng nằm trong `<state-root>` (`ledger.sqlite3`, `plans/`, `policy.json`); `.onecrew/active-plan.json` trong project là bản xuất để hook đọc.
