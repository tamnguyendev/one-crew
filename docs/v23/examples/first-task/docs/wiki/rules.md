# Quy ước của project mẫu

## Giá trị của a.txt
```onecrew
{"id": "a-value", "kind": "constraint", "label": "verified", "must": true, "applies_to": ["a.txt"],
 "sources": [{"type": "file", "path": "a.txt", "revision": "HEAD"}]}
```
a.txt phải chứa đúng VALUE: right — không phải giá trị mặc định. (Thay "HEAD" bằng commit lúc quy ước này được kiểm.)

## Hướng đã thử và loại
```onecrew
{"id": "no-two-lines", "kind": "rejected", "label": "refuted", "applies_to": ["a.txt"],
 "sources": [{"type": "file", "path": "a.txt", "revision": "HEAD"}]}
```
Đã thử ghi a.txt thành hai dòng; check của project từ chối.

## Ghi chú chưa có nguồn
Người viết nghĩ a.txt sẽ cần thêm dấu thời gian ở bản sau. (Không có khối onecrew: chỉ là đầu mối.)
