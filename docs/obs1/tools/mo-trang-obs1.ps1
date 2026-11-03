# mo-trang-obs1.ps1 - mo man hinh theo doi OBS-1 (CHI DOC) cua mot so OneCrew bang venv rieng; di qua `onecrew track open` (dinh danh server: marker + /api/health).
#   powershell -ExecutionPolicy Bypass -File "<goi>\verify\mo-trang-obs1.ps1" -Venv <thu muc venv da cai wheel OBS-1> -Project <thu muc project> -StateRoot <so> [-ProjectOnly] [-NoBrowser] [-PinFile <file>]
# -PinFile (tuy chon): ghi ban ghi "phien nay do toi mo" (url, pid, instance, version, so, project, opened_at) vao <file>, dat NGOAI venv, goi va thu muc chay;
#   dung-trang-obs1.ps1 -PinFile <cung file> chi dung dung phien do (xem dung-trang-obs1.ps1). Khong co -PinFile thi chay y nhu truoc, khong ghi gi.
#   Neu <file> da giu ghim cua mot phien CON SONG (/api/health van tra dung instance + pid) cua SO KHAC (hoac khong doc duoc), script tu choi: khong de len
#   ghim do, khong mo them server; dung phien cu bang dung-trang-obs1.ps1 -PinFile <file> truoc.
# Chi doc so (sqlite mode=ro); khong init project, khong doi hook, khong nang runtime cua project. Server chay tach roi, tu thoat sau 30 phut khong ai mo;
# dong trinh duyet hay dung server (dung-trang-obs1.ps1) khong dung worker hay task nao. Khong bao gio dung tien trinh la: `track open` chi dung lai server
# khi /api/health tra dung instance + version wheel + state-root + pham vi; sai thi mo server moi va bao ly do trong JSON.
param([Parameter(Mandatory=$true)][string]$Venv, [Parameter(Mandatory=$true)][string]$Project, [Parameter(Mandatory=$true)][string]$StateRoot,
      [switch]$ProjectOnly, [switch]$NoBrowser, [double]$Interval = 2, [string]$PinFile)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
function Fail([string]$t) { Write-Host ('KHONG DAT: ' + $t) -ForegroundColor Red; exit 1 }
$exe = Join-Path $Venv 'Scripts\onecrew.exe'
if (-not (Test-Path -LiteralPath $exe)) { Fail "khong thay $exe (venv chua cai wheel OBS-1)" }
if (-not (Test-Path -LiteralPath $Project)) { Fail "khong thay project $Project" }
if (-not (Test-Path -LiteralPath (Join-Path $StateRoot 'ledger.sqlite3'))) { Fail "khong thay so $StateRoot\ledger.sqlite3" }
$ver = (& $exe --version) -join ' '
Write-Host "== $ver | project $Project | so $StateRoot"
function Norm([string]$p) { if (-not $p) { return '' }; [IO.Path]::GetFullPath($p).TrimEnd('\').ToLowerInvariant() }
$old = $null
if ($PinFile -and (Test-Path -LiteralPath $PinFile)) {
    try { $old = Get-Content -Raw -Encoding UTF8 -LiteralPath $PinFile | ConvertFrom-Json } catch { Fail "file ghim $PinFile co san nhung khong doc duoc: khong biet con phien nao dang mo khong. Khong mo gi; xoa tay file do neu chac khong con phien." }
    if (-not $old -or $old.kind -ne 'obs1-viewer-pin' -or -not $old.url) { Fail "file ghim $PinFile co san nhung khong phai ban ghi ghim hop le. Khong mo gi; xoa tay file do neu chac khong con phien." }
    $h = $null; try { $h = Invoke-RestMethod -Uri ($old.url + 'api/health') -TimeoutSec 3 } catch {}
    if (-not ($h -and $h.instance -eq $old.instance -and $h.pid -eq $old.pid)) { $old = $null }       # ghim cu cua phien da chet: duoc ghi de
    elseif ((Norm $old.state_root) -ne (Norm $StateRoot)) {
        Fail "file ghim $PinFile dang giu mot phien con song cua so khac ($($old.state_root), pid $($old.pid)): khong ghi de, khong mo them server. Dung phien do bang dung-trang-obs1.ps1 -PinFile truoc."
    }
}
$args = @('--project', $Project, '--state-root', $StateRoot, 'track', 'open', '--interval', "$Interval")
if ($ProjectOnly) { $args += '--project-only' }
if ($NoBrowser) { $args += '--no-browser' }
$out = & $exe @args
$code = $LASTEXITCODE
Write-Host ($out -join "`n")
if ($code -ne 0) { Fail "track open thoat $code (xem JSON tren: 'refused' la ly do khong dung lai server cu)" }
$rec = ($out -join "`n") | ConvertFrom-Json
$how = if ($rec.reused) { 'dung lai server dang chay' } else { 'server moi' }
if ($PinFile) {
    $pin = [ordered]@{ kind = 'obs1-viewer-pin'; url = $rec.url; pid = [int]$rec.pid; instance = $rec.instance; version = $rec.version; state_root = $rec.state_root
        project = $Project; project_scope = $rec.project_id; venv = $Venv; reused = [bool]$rec.reused; opened_at = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') }
    if (-not $rec.instance -or -not $rec.pid) { Fail 'track open khong tra instance/pid: khong ghim duoc phien' }
    if ($old -and $old.instance -ne $rec.instance) { Fail "file ghim $PinFile van giu phien con song instance $($old.instance) (pid $($old.pid)), khac server vua mo (instance $($rec.instance)): khong ghi de ghim. Dung phien cu truoc." }
    $pinDir = Split-Path -Parent ([IO.Path]::GetFullPath($PinFile)); New-Item -ItemType Directory -Force -Path $pinDir | Out-Null
    $tmp = $PinFile + '.' + [guid]::NewGuid().ToString('N').Substring(0, 8) + '.tmp'
    [IO.File]::WriteAllText($tmp, ($pin | ConvertTo-Json), (New-Object System.Text.UTF8Encoding $false))
    Move-Item -LiteralPath $tmp -Destination $PinFile -Force
    Write-Host "Da ghim phien (pid $($rec.pid), instance $($rec.instance)) vao $PinFile"
}
Write-Host ("DAT: trang theo doi (chi doc) o " + $rec.url + " (" + $how + ", wheel " + $rec.version + ", pid " + $rec.pid + "). Dung: dung-trang-obs1.ps1 cung tham so.") -ForegroundColor Green
exit 0
