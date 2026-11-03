# mo-trang-obs1.ps1 - mo man hinh theo doi OBS-1 (CHI DOC) cua mot so OneCrew bang venv rieng; di qua `onecrew track open` (dinh danh server: marker + /api/health).
#   powershell -ExecutionPolicy Bypass -File "<goi>\verify\mo-trang-obs1.ps1" -Venv <thu muc venv da cai wheel OBS-1> -Project <thu muc project> -StateRoot <so> [-ProjectOnly] [-NoBrowser] [-PinFile <file>]
# -PinFile (tuy chon): ghi ban ghi "phien nay do toi mo" (url, pid, instance, version, so, project, pham vi, gio server tu ghi luc khoi dong, opened_at)
#   vao <file>. <file> phai nam NGOAI -Venv, -StateRoot va thu muc goi (script tu choi neu khong). dung-trang-obs1.ps1 -PinFile <cung file> dung DUNG
#   phien do (theo url + instance + pid, ke ca khi marker cua so da tro sang server khac). Khong co -PinFile thi chay y nhu truoc, khong ghi gi.
#   Truoc khi khoi dong bat cu gi: neu <file> dang giu mot phien CON SONG ma lan mo nay KHONG dung lai duoc (so khac; cung so nhung pham vi/project khac,
#   wheel khac, hoac marker cua so khong con tro toi phien do) thi script tu choi, khong mo server nao, khong ghi de ghim: dung phien do truoc bang
#   dung-trang-obs1.ps1 -PinFile <file>. "Con song" duoc hoi kien nhan: /api/health khong tra loi thi hoi lai voi thoi han dai hon; phien chi duoc coi
#   la da het khi tien trinh da ghim khong con chay (hoac PID do nay thuoc mot tien trinh moi hon). Tien trinh van chay ma khong tra loi: cung tu choi.
# Chi doc so (sqlite mode=ro); khong init project, khong doi hook, khong nang runtime cua project. Server chay tach roi, tu thoat sau 30 phut khong ai mo;
# dong trinh duyet hay dung server (dung-trang-obs1.ps1) khong dung worker hay task nao. Khong bao gio dung tien trinh la: `track open` chi dung lai server
# khi /api/health tra dung instance + version wheel + state-root + pham vi; sai thi mo server moi va bao ly do trong JSON.
param([Parameter(Mandatory=$true)][string]$Venv, [Parameter(Mandatory=$true)][string]$Project, [Parameter(Mandatory=$true)][string]$StateRoot,
      [switch]$ProjectOnly, [switch]$NoBrowser, [double]$Interval = 2, [string]$PinFile)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
function Fail([string]$t) { Write-Host ('KHONG DAT: ' + $t) -ForegroundColor Red; exit 1 }
function Norm([string]$p) { if (-not $p) { return '' }; [IO.Path]::GetFullPath($p).TrimEnd('\').ToLowerInvariant() }
function Inside([string]$child, [string]$parent) { $c = Norm $child; $p = Norm $parent; ($p -ne '') -and (($c -eq $p) -or $c.StartsWith($p + '\')) }
function Iso($v) { if ($v -is [datetime]) { return $v.ToUniversalTime().ToString('o') }; return [string]$v }
function Health([string]$url, [int]$seconds) { try { Invoke-RestMethod -Uri ($url + 'api/health') -TimeoutSec $seconds } catch { $null } }
function Utc($v) {
    if (-not $v) { return $null }
    if ($v -is [datetime]) { return $v.ToUniversalTime() }
    try { return ([DateTimeOffset]::Parse([string]$v, [Globalization.CultureInfo]::InvariantCulture)).UtcDateTime } catch { return $null }
}
function Same-Process($pin) {      # $true: the pinned pid runs and IS the pinned server (created no later than the start stamp it wrote); $false: gone; $null: cannot tell
    $p = Get-Process -Id ([int]$pin.pid) -ErrorAction SilentlyContinue
    if (-not $p) { return $false }
    $since = Utc $pin.server_started_at
    if (-not $since) { return $null }
    $created = $null
    try { $created = $p.StartTime.ToUniversalTime() } catch {}
    if (-not $created) { try { $created = (Get-CimInstance -Query ('SELECT CreationDate FROM Win32_Process WHERE ProcessId = ' + [int]$pin.pid)).CreationDate.ToUniversalTime() } catch {} }
    if (-not $created) { return $null }
    return ($created -le $since)
}
function Pin-State($pin) {         # 'live' | 'gone' | 'unknown': a slow /api/health is asked again (longer timeouts) while the pinned process still runs
    foreach ($t in 3, 6, 12) {
        $h = Health ([string]$pin.url) $t
        if ($h -and $h.instance -eq $pin.instance -and $h.pid -eq $pin.pid) { return 'live' }
        if ((Same-Process $pin) -eq $false) { return 'gone' }
        Start-Sleep -Milliseconds 300
    }
    return 'unknown'
}
$exe = Join-Path $Venv 'Scripts\onecrew.exe'
if (-not (Test-Path -LiteralPath $exe)) { Fail "khong thay $exe (venv chua cai wheel OBS-1)" }
if (-not (Test-Path -LiteralPath $Project)) { Fail "khong thay project $Project" }
if (-not (Test-Path -LiteralPath (Join-Path $StateRoot 'ledger.sqlite3'))) { Fail "khong thay so $StateRoot\ledger.sqlite3" }
if ($PinFile) {                    # the pin lives outside the venv, the state root and the package (in a checkout: the tools folder) of this script
    $pkg = Split-Path -Parent $PSScriptRoot
    if (-not (Test-Path -LiteralPath (Join-Path $pkg 'manifest.json'))) { $pkg = $PSScriptRoot }
    foreach ($place in @(@('venv', $Venv), @('so', $StateRoot), @('thu muc goi', $pkg))) {
        if (Inside $PinFile $place[1]) { Fail "file ghim $PinFile nam trong $($place[0]) ($($place[1])): dat no ra ngoai venv, so va thu muc goi. Khong mo gi." }
    }
}
$ver = (& $exe --version) -join ' '
Write-Host "== $ver | project $Project | so $StateRoot"
$here = ($ver -replace '^\s*onecrew\s+', '').Trim()
$old = $null
if ($PinFile -and (Test-Path -LiteralPath $PinFile)) {
    try { $old = Get-Content -Raw -Encoding UTF8 -LiteralPath $PinFile | ConvertFrom-Json } catch { Fail "file ghim $PinFile co san nhung khong doc duoc: khong biet con phien nao dang mo khong. Khong mo gi; xoa tay file do neu chac khong con phien." }
    if (-not $old -or $old.kind -ne 'obs1-viewer-pin' -or -not $old.url -or -not $old.instance -or -not $old.pid) { Fail "file ghim $PinFile co san nhung khong phai ban ghi ghim hop le. Khong mo gi; xoa tay file do neu chac khong con phien." }
    $state = Pin-State $old
    if ($state -eq 'gone') { $old = $null }                                  # the pinned session is over: its pin may be replaced
    elseif ($state -eq 'unknown') {
        Fail "file ghim $PinFile giu phien (instance $($old.instance), pid $($old.pid)) khong tra loi /api/health du da hoi lai lau hon, nhung tien trinh cua no van chay: khong ghi de ghim, khong mo them server. Doi roi chay lai, hoac dung phien do bang dung-trang-obs1.ps1 -PinFile $PinFile."
    }
    elseif ((Norm $old.state_root) -ne (Norm $StateRoot)) {
        Fail "file ghim $PinFile dang giu mot phien con song cua so khac ($($old.state_root), pid $($old.pid)): khong ghi de, khong mo them server. Dung phien do bang dung-trang-obs1.ps1 -PinFile truoc."
    }
    else {                         # a live session of THIS state root: this call must reuse exactly it, else refuse before anything starts
        $why = $null
        if ([string]$old.version -ne $here) { $why = "wheel khac (phien chay $($old.version), lan mo nay la $here)" }
        elseif ($ProjectOnly -and -not $old.project_scope) { $why = 'pham vi khac (phien theo doi moi project, lan mo nay -ProjectOnly)' }
        elseif ((-not $ProjectOnly) -and $old.project_scope) { $why = 'pham vi khac (phien chi theo doi mot project, lan mo nay moi project)' }
        elseif ($ProjectOnly -and ((Norm $old.project) -ne (Norm $Project))) { $why = "project khac (phien cua project $($old.project))" }
        else {
            $st = $null; try { $st = ((& $exe --project $Project --state-root $StateRoot track status) -join "`n") | ConvertFrom-Json } catch {}
            if (-not $st) { $why = 'khong doc duoc track status' }
            elseif (-not $st.marker -or $st.marker.instance -ne $old.instance -or $st.marker.pid -ne $old.pid) { $why = "marker cua so khong con tro toi phien nay (marker: instance $($st.marker.instance), pid $($st.marker.pid))" }
        }
        if ($why) {
            Fail "file ghim $PinFile dang giu phien con song cua so nay (instance $($old.instance), pid $($old.pid)) ma lan mo nay se khong dung lai: $why. Khong mo them server, khong ghi de ghim. Dung phien do truoc: dung-trang-obs1.ps1 -Venv <venv> -Project <project> -StateRoot <so> -PinFile $PinFile"
        }
    }
}
$a = @('--project', $Project, '--state-root', $StateRoot, 'track', 'open', '--interval', "$Interval")
if ($ProjectOnly) { $a += '--project-only' }
if ($NoBrowser) { $a += '--no-browser' }
$out = & $exe @a
$code = $LASTEXITCODE
Write-Host ($out -join "`n")
if ($code -ne 0) { Fail "track open thoat $code (xem JSON tren: 'refused' la ly do khong dung lai server cu)" }
$rec = ($out -join "`n") | ConvertFrom-Json
$how = if ($rec.reused) { 'dung lai server dang chay' } else { 'server moi' }
if ($PinFile) {
    if (-not $rec.instance -or -not $rec.pid) { Fail 'track open khong tra instance/pid: khong ghim duoc phien' }
    if ($old -and $old.instance -ne $rec.instance) {
        $note = ''
        if (-not $rec.reused) {        # the marker moved meanwhile and this call started a server: stop exactly that one, so no unpinned viewer stays behind
            $sa = @('--project', $Project, '--state-root', $StateRoot, 'track', 'stop', '--url', [string]$rec.url, '--instance', [string]$rec.instance, '--pid', [string]$rec.pid)
            if ($rec.started_at) { $sa += @('--started-at', (Iso $rec.started_at)) }
            $so = & $exe @sa
            $note = if ($LASTEXITCODE -eq 0) { " Server lan nay vua khoi dong (pid $($rec.pid)) da duoc dung lai." } else { " Server lan nay vua khoi dong (pid $($rec.pid)) KHONG dung duoc: " + ($so -join ' ') }
        }
        Fail "file ghim $PinFile van giu phien con song instance $($old.instance) (pid $($old.pid)), khac server cua lan mo nay (instance $($rec.instance)): khong ghi de ghim.$note Dung phien cu truoc."
    }
    $pin = [ordered]@{ kind = 'obs1-viewer-pin'; url = $rec.url; pid = [int]$rec.pid; instance = $rec.instance; version = $rec.version; state_root = $rec.state_root
        project = $Project; project_scope = $rec.project_id; venv = $Venv; server_started_at = (Iso $rec.started_at); reused = [bool]$rec.reused
        opened_at = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') }
    $pinDir = Split-Path -Parent ([IO.Path]::GetFullPath($PinFile)); New-Item -ItemType Directory -Force -Path $pinDir | Out-Null
    $tmp = $PinFile + '.' + [guid]::NewGuid().ToString('N').Substring(0, 8) + '.tmp'
    [IO.File]::WriteAllText($tmp, ($pin | ConvertTo-Json), (New-Object System.Text.UTF8Encoding $false))
    Move-Item -LiteralPath $tmp -Destination $PinFile -Force
    Write-Host "Da ghim phien (pid $($rec.pid), instance $($rec.instance)) vao $PinFile"
}
Write-Host ("DAT: trang theo doi (chi doc) o " + $rec.url + " (" + $how + ", wheel " + $rec.version + ", pid " + $rec.pid + "). Dung: dung-trang-obs1.ps1 cung tham so.") -ForegroundColor Green
exit 0
