# don-dep.ps1 - ket thuc bai thu: xoa DUNG lab ma chuan-bi.ps1 da tao, khong gi khac. Chay:
#   powershell -ExecutionPolicy Bypass -File "D:\OneCrewRuns\v24\pkg\thu-tay-dev5\don-dep.ps1" -Lab "<lab>"
# Xoa chi khi: duong dan tuyet doi cuoi cung (sau GetFullPath) khong nam trong goi, sau it nhat 3 muc (D:\<muc>\<lab>), khong di qua link/junction
# o lab hay thu muc cha nao, co <lab>\.lab-thu-dev5.json ghi dung duong dan nay voi nonce trung muc trong labs.json canh script (ca hai do
# chuan-bi.ps1 ghi; script nay khong bao gio tao chung), co cau truc lab (env\LocalAppData, venv, so). Moi truong khong qua kiem -> KHONG DAT ma 2,
# khong xoa gi. Sau khi xoa: kiem thu muc da mat (neu con -> KHONG DAT ma 1) va registry that khong doi hash; moi xoa muc khoi labs.json.
param([string]$Lab = 'D:\OneCrewRuns\v24 thu tay dev5')
$ErrorActionPreference = 'Stop'
$pkg = $null
foreach ($cand in @((Split-Path -Parent (Split-Path -Parent $PSScriptRoot)), 'D:\OneCrewRuns\v24\pkg\onecrew-2.4.0.dev5-beta')) {   # <package>\verify\thu-tay -> <package>; else the known package
    if ($cand -and (Test-Path -LiteralPath (Join-Path $cand 'manifest.json') -PathType Leaf) -and (Test-Path -LiteralPath (Join-Path $cand 'wheel') -PathType Container)) { $pkg = [System.IO.Path]::GetFullPath($cand).TrimEnd('\'); break }
}
if (-not $pkg) { Write-Host 'KHONG DAT: khong tim thay goi (manifest.json) canh script hay o duong dan da biet' -ForegroundColor Red }
$man = if ($pkg) { Get-Content -LiteralPath (Join-Path $pkg 'manifest.json') -Raw | ConvertFrom-Json } else { $null }
$labsFile = Join-Path $env:USERPROFILE '.onecrew-thu-tay\labs.json'       # ngoai goi, ngoai lab: bang chung thu hai cua don-dep.ps1
function Refuse([string]$t) { Write-Host ('KHONG DAT: ' + $t + ' (khong xoa gi)') -ForegroundColor Red; exit 2 }
function Hash([string]$p) { if (Test-Path -LiteralPath $p) { (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash } else { 'absent' } }
$lab = [System.IO.Path]::GetFullPath($Lab).TrimEnd('\')
if (-not [System.IO.Path]::IsPathRooted($lab)) { Refuse "duong dan khong tuyet doi: $lab" }
if (-not $pkg) { Refuse 'khong tim thay goi' }
if (($lab + '\').StartsWith($pkg + '\', [StringComparison]::OrdinalIgnoreCase) -or ($pkg + '\').StartsWith($lab + '\', [StringComparison]::OrdinalIgnoreCase)) { Refuse "lab trung hoac chua goi: $lab" }
if ((($lab -split '\\') | Where-Object { $_ }).Count -lt 3) { Refuse "duong dan qua nong, khong phai lab: $lab" }
if (-not (Test-Path -LiteralPath $lab -PathType Container)) { Refuse "khong co thu muc: $lab" }
$cur = $lab
while ($cur -and $cur -ne [System.IO.Path]::GetPathRoot($cur)) {
    if ((Get-Item -LiteralPath $cur -Force).Attributes -band [System.IO.FileAttributes]::ReparsePoint) { Refuse "duong dan di qua link/junction tai $cur" }
    $cur = Split-Path -Parent $cur
}
$marker = Join-Path $lab '.lab-thu-dev5.json'
if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) { Refuse "$lab khong co .lab-thu-dev5.json: khong phai lab do chuan-bi.ps1 tao" }
try { $m = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json } catch { Refuse 'dau so huu khong doc duoc' }
if ($m.created_by -ne 'chuan-bi.ps1' -or -not $m.nonce -or -not $m.lab) { Refuse 'dau so huu khong hop le' }
if ($m.lab.TrimEnd('\').ToLowerInvariant() -ne $lab.ToLowerInvariant()) { Refuse "dau so huu ghi lab khac ($($m.lab)): khong xoa $lab" }
if (-not (Test-Path -LiteralPath $labsFile -PathType Leaf)) { Refuse "khong co ${labsFile}: khong co bang chung chuan-bi.ps1 da tao lab nay" }
try { $raw = Get-Content -LiteralPath $labsFile -Raw | ConvertFrom-Json } catch { Refuse 'labs.json khong doc duoc' }
if ($raw -ne $null -and $raw.PSObject.Properties['value'] -and -not ($raw -is [array])) { $raw = $raw.value }   # a wrapped list written by an older build
$all = @($raw)
$hit = @($all | Where-Object { $_.lab -and $_.lab.TrimEnd('\').ToLowerInvariant() -eq $lab.ToLowerInvariant() -and $_.nonce -eq $m.nonce })
if ($hit.Count -ne 1) { Refuse "labs.json khong co muc cua $lab voi nonce cua dau so huu: khong phai lab da dang ky" }
foreach ($need in @("$lab\env\LocalAppData", "$lab\venv", "$lab\so")) { if (-not (Test-Path -LiteralPath $need -PathType Container)) { Refuse "thieu ${need}: khong giong lab" } }
$real = if ($env:ONECREW_LAB_REAL_LOCALAPPDATA) { $env:ONECREW_LAB_REAL_LOCALAPPDATA } else { $env:LOCALAPPDATA }
$registryThat = Join-Path $real 'OneCrew\hook-projects.json'
if (($env:LOCALAPPDATA + '\').StartsWith($lab + '\', [StringComparison]::OrdinalIgnoreCase) -or ($env:TEMP + '\').StartsWith($lab + '\', [StringComparison]::OrdinalIgnoreCase)) { Refuse 'cua so nay dang o TRONG lab (LOCALAPPDATA/TEMP tro vao lab): dong no, mo cua so PowerShell moi (chua dot-source) roi chay lai' }
if (($registryThat + '\').StartsWith($lab + '\', [StringComparison]::OrdinalIgnoreCase)) { Refuse 'khong xac dinh duoc registry that de doi chieu: mo cua so moi roi chay lai' }
$truoc = Hash $registryThat
Write-Host "xoa lab: $lab (dau so huu $($m.nonce.Substring(0,8))..., tao $($m.created_at))"
Remove-Item -LiteralPath $lab -Recurse -Force
if (Test-Path -LiteralPath $lab) { Write-Host "KHONG DAT: $lab van con sau khi xoa" -ForegroundColor Red; exit 1 }
$sau = Hash $registryThat
if ($sau -ne $truoc) { Write-Host "KHONG DAT: registry that doi trong luc don dep ($truoc -> $sau)" -ForegroundColor Red; exit 1 }
$rest = New-Object System.Collections.Generic.List[object]
foreach ($e in $all) { if ($e -and $e.lab -and $e.lab.TrimEnd('\').ToLowerInvariant() -ne $lab.ToLowerInvariant()) { $rest.Add([pscustomobject]@{ lab = $e.lab; nonce = $e.nonce; created_at = $e.created_at }) } }
(ConvertTo-Json -InputObject $rest.ToArray() -Depth 3) | Set-Content -LiteralPath $labsFile -Encoding utf8
Write-Host "DAT: da xoa $lab (kiem: khong con); registry that $registryThat khong doi ($truoc); muc lab da bo khoi labs.json."
exit 0
