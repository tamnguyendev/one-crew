# dung-trang-obs1.ps1 - dung server man hinh theo doi OBS-1 ma mo-trang-obs1.ps1 / `track open` da mo cho mot so; di qua `onecrew track stop`.
#   powershell -ExecutionPolicy Bypass -File "<goi>\verify\dung-trang-obs1.ps1" -Venv <venv> -Project <project> -StateRoot <so>
# Chi dung tien trinh ma marker <so>\tracking\server.json tro toi VA /api/health cua no khop (PID, so, dinh danh); marker cu/sai thi chi xoa marker, khong dung gi.
# Dung man hinh KHONG dung worker hay task nao. Thoat 0 khi da dung; 2 khi khong co server nao de dung (van in ly do).
param([Parameter(Mandatory=$true)][string]$Venv, [Parameter(Mandatory=$true)][string]$Project, [Parameter(Mandatory=$true)][string]$StateRoot)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$exe = Join-Path $Venv 'Scripts\onecrew.exe'
if (-not (Test-Path -LiteralPath $exe)) { Write-Host "KHONG DAT: khong thay $exe" -ForegroundColor Red; exit 1 }
$out = & $exe --project $Project --state-root $StateRoot track stop
$code = $LASTEXITCODE
Write-Host ($out -join "`n")
if ($code -eq 0) { Write-Host 'DAT: da dung server trang theo doi (worker/task khong bi anh huong).' -ForegroundColor Green; exit 0 }
Write-Host 'Khong co server nao bi dung (xem "reason" o tren).' -ForegroundColor Yellow
exit $code
