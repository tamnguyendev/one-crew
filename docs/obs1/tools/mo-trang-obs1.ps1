# mo-trang-obs1.ps1 - mo man hinh theo doi OBS-1 (CHI DOC) cua mot so OneCrew bang venv rieng; di qua `onecrew track open` (dinh danh server: marker + /api/health).
#   powershell -ExecutionPolicy Bypass -File "<goi>\verify\mo-trang-obs1.ps1" -Venv <thu muc venv da cai wheel OBS-1> -Project <thu muc project> -StateRoot <so> [-ProjectOnly] [-NoBrowser]
# Chi doc so (sqlite mode=ro); khong init project, khong doi hook, khong nang runtime cua project. Server chay tach roi, tu thoat sau 30 phut khong ai mo;
# dong trinh duyet hay dung server (dung-trang-obs1.ps1) khong dung worker hay task nao. Khong bao gio dung tien trinh la: `track open` chi dung lai server
# khi /api/health tra dung instance + version wheel + state-root + pham vi; sai thi mo server moi va bao ly do trong JSON.
param([Parameter(Mandatory=$true)][string]$Venv, [Parameter(Mandatory=$true)][string]$Project, [Parameter(Mandatory=$true)][string]$StateRoot,
      [switch]$ProjectOnly, [switch]$NoBrowser, [double]$Interval = 2)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
function Fail([string]$t) { Write-Host ('KHONG DAT: ' + $t) -ForegroundColor Red; exit 1 }
$exe = Join-Path $Venv 'Scripts\onecrew.exe'
if (-not (Test-Path -LiteralPath $exe)) { Fail "khong thay $exe (venv chua cai wheel OBS-1)" }
if (-not (Test-Path -LiteralPath $Project)) { Fail "khong thay project $Project" }
if (-not (Test-Path -LiteralPath (Join-Path $StateRoot 'ledger.sqlite3'))) { Fail "khong thay so $StateRoot\ledger.sqlite3" }
$ver = (& $exe --version) -join ' '
Write-Host "== $ver | project $Project | so $StateRoot"
$args = @('--project', $Project, '--state-root', $StateRoot, 'track', 'open', '--interval', "$Interval")
if ($ProjectOnly) { $args += '--project-only' }
if ($NoBrowser) { $args += '--no-browser' }
$out = & $exe @args
$code = $LASTEXITCODE
Write-Host ($out -join "`n")
if ($code -ne 0) { Fail "track open thoat $code (xem JSON tren: 'refused' la ly do khong dung lai server cu)" }
$rec = ($out -join "`n") | ConvertFrom-Json
$how = if ($rec.reused) { 'dung lai server dang chay' } else { 'server moi' }
Write-Host ("DAT: trang theo doi (chi doc) o " + $rec.url + " (" + $how + ", wheel " + $rec.version + ", pid " + $rec.pid + "). Dung: dung-trang-obs1.ps1 cung tham so.") -ForegroundColor Green
exit 0
