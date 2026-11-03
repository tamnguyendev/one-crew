# dung-trang-obs1.ps1 - dung server man hinh theo doi OBS-1 ma mo-trang-obs1.ps1 / `track open` da mo cho mot so; di qua `onecrew track stop`.
#   powershell -ExecutionPolicy Bypass -File "<goi>\verify\dung-trang-obs1.ps1" -Venv <venv> -Project <project> -StateRoot <so> [-PinFile <file>]
# Khong co -PinFile: chi dung tien trinh ma marker cua so tro toi VA /api/health cua no khop (PID, so, dinh danh); marker cu/sai thi chi xoa marker.
# Dung man hinh KHONG dung worker hay task nao. Thoat 0 khi da dung; 2 khi khong co server nao de dung (van in ly do).
# -PinFile (tuy chon, cung file voi mo-trang-obs1.ps1 -PinFile): dung DUNG phien do bang `track stop --url --instance --pid` (dinh danh da ghim), ke ca khi
#   marker cua so da tro sang server khac: chi tien trinh ma /api/health o url da ghim tra dung instance + pid + so moi bi dung; marker chi bi xoa khi no
#   ghi dung instance do. Khong co file ghim -> khong dung gi ("khong co phien nao do script mo nay mo"). Lech dinh danh (cong do server khac tra loi,
#   PID khac) -> khong dung gi, giu file ghim. Phien da ghim chac chan da het (tien trinh khong con, hoac PID nay thuoc tien trinh moi hon) -> xoa file ghim,
#   tru khi marker cua so dang tro toi server khac (giu file ghim de doc). Khong quet thu muc, khong tu giet tien trinh nao. Khong co -PinFile thi chay y nhu truoc.
#   Vong 5: -Venv/-Project/-StateRoot/-PinFile tuong doi duoc doi ra duong dan tuyet doi theo thu muc hien tai (nhu mo-trang-obs1.ps1).
param([Parameter(Mandatory=$true)][string]$Venv, [Parameter(Mandatory=$true)][string]$Project, [Parameter(Mandatory=$true)][string]$StateRoot,
      [string]$PinFile)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$exe = Join-Path $Venv 'Scripts\onecrew.exe'
if (-not (Test-Path -LiteralPath $exe)) { Write-Host "KHONG DAT: khong thay $exe" -ForegroundColor Red; exit 1 }
$Venv = (Resolve-Path -LiteralPath $Venv).ProviderPath; $exe = Join-Path $Venv 'Scripts\onecrew.exe'          # absolute from here on
if (Test-Path -LiteralPath $Project) { $Project = (Resolve-Path -LiteralPath $Project).ProviderPath }
if (Test-Path -LiteralPath $StateRoot) { $StateRoot = (Resolve-Path -LiteralPath $StateRoot).ProviderPath }
if ($PinFile) { $PinFile = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($PinFile) }
function Norm([string]$p) { if (-not $p) { return '' }; [IO.Path]::GetFullPath($p).TrimEnd('\').ToLowerInvariant() }
function Iso($v) { if ($v -is [datetime]) { return $v.ToUniversalTime().ToString('o') }; return [string]$v }
function Refuse([string]$t) { Write-Host ('KHONG DUNG GI: ' + $t) -ForegroundColor Yellow; exit 2 }
if ($PinFile) {
    if (-not (Test-Path -LiteralPath $PinFile)) { Refuse 'khong co phien nao do script mo nay mo (khong thay file ghim). Khong dung gi.' }
    try { $pin = Get-Content -Raw -Encoding UTF8 -LiteralPath $PinFile | ConvertFrom-Json } catch { Refuse "khong doc duoc file ghim $PinFile. Khong dung gi." }
    if (-not $pin -or $pin.kind -ne 'obs1-viewer-pin' -or -not $pin.url -or -not $pin.instance -or -not $pin.pid) { Refuse "file ghim $PinFile khong phai ban ghi ghim hop le. Khong dung gi." }
    if ((Norm $pin.state_root) -ne (Norm $StateRoot)) {
        $st = $null; try { $st = ((& $exe --project $Project --state-root $StateRoot track status) -join "`n") | ConvertFrom-Json } catch {}
        if (-not $st -or (Norm $pin.state_root) -ne (Norm ([string]$st.state_root))) { Refuse "file ghim la cua so khac ($($pin.state_root)), khong phai $StateRoot. Khong dung gi." }
    }
    $a = @('--project', $Project, '--state-root', $StateRoot, 'track', 'stop', '--url', [string]$pin.url, '--instance', [string]$pin.instance, '--pid', [string]$pin.pid)
    if ($pin.server_started_at) { $a += @('--started-at', (Iso $pin.server_started_at)) }
    $out = & $exe @a
    $code = $LASTEXITCODE
    Write-Host ($out -join "`n")
    $res = $null; try { $res = ($out -join "`n") | ConvertFrom-Json } catch {}
    if (-not $res -or $null -eq $res.stopped) { Refuse "track stop khong tra ket qua dung theo dinh danh (runtime nay co --url/--instance/--pid khong?). Khong dung gi; giu file ghim." }
    if ($code -eq 0 -and $res.stopped -and $res.pid -eq $pin.pid -and $res.instance -eq $pin.instance) {
        Remove-Item -LiteralPath $PinFile -Force
        Write-Host "DAT: da dung dung phien da ghim (pid $($pin.pid), instance $($pin.instance)); worker/task khong bi anh huong. Da xoa file ghim." -ForegroundColor Green
        exit 0
    }
    if ($res.gone -eq $true) {
        $mk = $res.marker_now
        if ($mk -and $mk.instance -and $mk.instance -ne $pin.instance) {
            Refuse "phien da ghim (instance $($pin.instance), pid $($pin.pid)) khong con chay; marker cua so nay dang tro toi server khac (instance $($mk.instance), pid $($mk.pid)) ma script nay khong dung. Giu file ghim de doc; lan mo sau ghi de no."
        }
        Remove-Item -LiteralPath $PinFile -Force
        Refuse "phien da ghim (instance $($pin.instance), pid $($pin.pid)) khong con: server da tu thoat hoac da bi dung. Da xoa file ghim cu; khong co tien trinh nao bi dung."
    }
    Refuse "$($res.reason) Giu file ghim (instance $($pin.instance), pid $($pin.pid))."
}
$out = & $exe --project $Project --state-root $StateRoot track stop
$code = $LASTEXITCODE
Write-Host ($out -join "`n")
if ($code -eq 0) { Write-Host 'DAT: da dung server trang theo doi (worker/task khong bi anh huong).' -ForegroundColor Green; exit 0 }
Write-Host 'Khong co server nao bi dung (xem "reason" o tren).' -ForegroundColor Yellow
exit $code
