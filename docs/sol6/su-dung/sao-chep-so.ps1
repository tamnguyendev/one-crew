# sao-chep-so.ps1 - ban sao NHAT QUAN cua mot so OneCrew (state root) de thu, bang co che cua chinh OneCrew (onecrew.v2.hotfix.copy_state):
#   ledger.sqlite3 qua SQLite backup API (so nguon mo o che do chi doc, ban sao nhat quan ca khi so dang duoc ghi), cac thu muc khac
#   (plans, snapshots, ...) chep nguyen. Khong chep support-work, support-spool; bo marker trang theo doi cua so nguon (tracking\server.json).
#
#   powershell -ExecutionPolicy Bypass -File sao-chep-so.ps1 -Venv <venv da cai onecrew> -Nguon <so dang dung> -Dich <thu muc MOI>
#
# Khong ghi gi vao -Nguon. -Dich phai CHUA ton tai: script khong ghi de va khong xoa thu muc nao. Thoat 0 + "DAT" khi ban sao mo duoc o che do chi doc.
param([Parameter(Mandatory=$true)][string]$Venv, [Parameter(Mandatory=$true)][string]$Nguon, [Parameter(Mandatory=$true)][string]$Dich)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
function Fail([string]$t) { Write-Host ('KHONG DAT: ' + $t) -ForegroundColor Red; exit 1 }
function Norm([string]$p) { [IO.Path]::GetFullPath($p).TrimEnd('\').ToLowerInvariant() }
$py = Join-Path $Venv 'Scripts\python.exe'
$exe = Join-Path $Venv 'Scripts\onecrew.exe'
if (-not (Test-Path -LiteralPath $py) -or -not (Test-Path -LiteralPath $exe)) { Fail "khong thay $py hoac $exe (venv chua cai onecrew)" }
if (-not (Test-Path -LiteralPath (Join-Path $Nguon 'ledger.sqlite3'))) { Fail "khong thay so: $Nguon\ledger.sqlite3" }
$Nguon = (Resolve-Path -LiteralPath $Nguon).ProviderPath
$Dich = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Dich)
if (Test-Path -LiteralPath $Dich) { Fail "$Dich da ton tai: chon mot thu muc MOI (script khong ghi de, khong xoa gi)" }
$n = Norm $Nguon; $d = Norm $Dich
if ($d.StartsWith($n + '\') -or $n.StartsWith($d + '\')) { Fail 'ban sao khong duoc nam trong so nguon (va nguoc lai)' }
$ver = ((& $exe --version) -join ' ').Trim()
Write-Host "== $ver | nguon $Nguon | ban sao $Dich"
$copy = "import sys; from onecrew.v2.hotfix import copy_state; target, size = copy_state(sys.argv[1], sys.argv[2], full=True); print(size)"
$size = & $py -I -B -c $copy $Nguon $Dich
if ($LASTEXITCODE -ne 0) { Fail 'chep so loi (xem thong bao o tren); so nguon khong bi ghi' }
$marker = Join-Path $Dich 'tracking\server.json'
if (Test-Path -LiteralPath $marker) { Remove-Item -LiteralPath $marker -Force; Write-Host 'Da bo marker trang theo doi cua so nguon khoi ban sao.' }
$check = "import sqlite3, sys, pathlib; p = pathlib.Path(sys.argv[1]) / 'ledger.sqlite3'; c = sqlite3.connect(p.as_uri() + '?mode=ro', uri=True); print(c.execute('PRAGMA user_version').fetchone()[0], c.execute('SELECT COUNT(*) FROM tasks').fetchone()[0], c.execute('SELECT COUNT(*) FROM events').fetchone()[0]); c.close()"
$facts = (& $py -I -B -c $check $Dich) -join ' '
if ($LASTEXITCODE -ne 0) { Fail 'ban sao khong mo duoc o che do chi doc' }
$parts = $facts.Trim() -split '\s+'
Write-Host ("DAT: ban sao o $Dich ({0} byte; schema {1}; {2} task; {3} su kien). So nguon khong bi ghi." -f $size, $parts[0], $parts[1], $parts[2]) -ForegroundColor Green
exit 0
