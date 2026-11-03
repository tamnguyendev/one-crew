# dung-trang-obs1.ps1 - dung server man hinh theo doi OBS-1 ma mo-trang-obs1.ps1 / `track open` da mo cho mot so; di qua `onecrew track stop`.
#   powershell -ExecutionPolicy Bypass -File "<goi>\verify\dung-trang-obs1.ps1" -Venv <venv> -Project <project> -StateRoot <so> [-PinFile <file>]
# Chi dung tien trinh ma marker <so>\tracking\server.json tro toi VA /api/health cua no khop (PID, so, dinh danh); marker cu/sai thi chi xoa marker, khong dung gi.
# Dung man hinh KHONG dung worker hay task nao. Thoat 0 khi da dung; 2 khi khong co server nao de dung (van in ly do).
# -PinFile (tuy chon, cung file voi mo-trang-obs1.ps1 -PinFile): chi dung DUNG phien do. Doc ban ghi ghim; khong co file -> khong dung gi ("khong co phien nao do
#   script mo nay mo"). Hoi `track status` roi chi goi `track stop` khi marker cua so VA /api/health deu mang dung instance + pid da ghim (+ cung so); lech
#   (server da khoi dong lai, marker cua phien khac) -> khong dung gi, nop ly do, giu file ghim. Khong quet thu muc, khong tu giet tien trinh nao.
#   Khong co -PinFile thi chay y nhu truoc.
param([Parameter(Mandatory=$true)][string]$Venv, [Parameter(Mandatory=$true)][string]$Project, [Parameter(Mandatory=$true)][string]$StateRoot,
      [string]$PinFile)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$exe = Join-Path $Venv 'Scripts\onecrew.exe'
if (-not (Test-Path -LiteralPath $exe)) { Write-Host "KHONG DAT: khong thay $exe" -ForegroundColor Red; exit 1 }
function Norm([string]$p) { if (-not $p) { return '' }; [IO.Path]::GetFullPath($p).TrimEnd('\').ToLowerInvariant() }
function Refuse([string]$t) { Write-Host ('KHONG DUNG GI: ' + $t) -ForegroundColor Yellow; exit 2 }
if ($PinFile) {
    if (-not (Test-Path -LiteralPath $PinFile)) { Refuse 'khong co phien nao do script mo nay mo (khong thay file ghim). Khong dung gi.' }
    try { $pin = Get-Content -Raw -Encoding UTF8 -LiteralPath $PinFile | ConvertFrom-Json } catch { Refuse "khong doc duoc file ghim $PinFile. Khong dung gi." }
    if ($pin.kind -ne 'obs1-viewer-pin' -or -not $pin.instance -or -not $pin.pid) { Refuse "file ghim $PinFile khong phai ban ghi ghim hop le. Khong dung gi." }
    try { $st = ((& $exe --project $Project --state-root $StateRoot track status) -join "`n") | ConvertFrom-Json } catch { Refuse 'khong doc duoc ket qua track status. Khong dung gi.' }
    $mk = $st.marker; $hl = $st.health
    if ((Norm $pin.state_root) -ne (Norm $StateRoot) -and (Norm $pin.state_root) -ne (Norm ([string]$st.state_root))) { Refuse "file ghim la cua so khac ($($pin.state_root)), khong phai $StateRoot. Khong dung gi." }
    if (-not $mk) {
        $alive = $null; try { $alive = Invoke-RestMethod -Uri ($pin.url + 'api/health') -TimeoutSec 3 } catch {}
        if ($alive -and $alive.instance -eq $pin.instance -and $alive.pid -eq $pin.pid) { Refuse "phien da ghim (instance $($pin.instance), pid $($pin.pid)) van tra loi nhung so nay khong con marker: khong co cach an toan de dung. Khong dung gi." }
        Remove-Item -LiteralPath $PinFile -Force
        Refuse "phien da ghim (instance $($pin.instance), pid $($pin.pid)) khong con: server da tu thoat hoac da dung, so nay khong co marker. Da xoa file ghim cu."
    }
    if ($mk.instance -ne $pin.instance -or $mk.pid -ne $pin.pid) {
        Refuse "marker cua so nay nay thuoc server khac (instance $($mk.instance), pid $($mk.pid)), khong phai phien da ghim (instance $($pin.instance), pid $($pin.pid)). Khong dung gi; giu file ghim."
    }
    if (-not $hl) {
        $null = & $exe --project $Project --state-root $StateRoot track stop      # marker khop ghim nhung server khong tra loi: chi don marker cu
        Remove-Item -LiteralPath $PinFile -Force
        Refuse "server da ghim (pid $($pin.pid)) khong con tra loi; da don marker cu va file ghim. Khong co tien trinh nao bi dung."
    }
    if ($hl.instance -ne $pin.instance -or $hl.pid -ne $pin.pid) {
        Refuse "cong $($pin.url) dang do server khac tra loi (instance $($hl.instance), pid $($hl.pid)), khong phai phien da ghim. Khong dung gi; giu file ghim."
    }
}
$out = & $exe --project $Project --state-root $StateRoot track stop
$code = $LASTEXITCODE
Write-Host ($out -join "`n")
if ($code -eq 0) {
    if ($PinFile) {
        $res = $null; try { $res = ($out -join "`n") | ConvertFrom-Json } catch {}
        if ($res -and $res.pid -eq $pin.pid -and $res.instance -eq $pin.instance) { Remove-Item -LiteralPath $PinFile -Force }
        else { Write-Host 'Canh bao: track stop dung mot server khong khop ghim (xem JSON tren); giu file ghim.' -ForegroundColor Yellow }
    }
    Write-Host 'DAT: da dung server trang theo doi (worker/task khong bi anh huong).' -ForegroundColor Green; exit 0
}
Write-Host 'Khong co server nao bi dung (xem "reason" o tren).' -ForegroundColor Yellow
exit $code
