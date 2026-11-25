<#
.SYNOPSIS
  URL9692 M2: try the fixed tracking addresses with the trial runtime: 9692 (real ledger), 9693 (development ledger), 9694 (coordinator's ledger).
.DESCRIPTION
  Default = dry run: shows what would be written and started, writes nothing, starts nothing.
  -ApDung (owner's own terminal only; refused inside an AI session):
    1. writes tracking.json {"port": 9693} into the development ledger and {"port": 9694} into the coordinator's ledger
       (a tracking.json that is already there with another content is only replaced after you answer y);
    2. runs `track open --no-browser` of the trial runtime for the three ledgers (the real ledger has no tracking.json: 9692);
    3. prints the three URLs and asks /api/health of each (no proxy).
  -QuayVe -ApDung: stops the three servers (`track stop` of each ledger) and removes the two tracking.json files this script writes
  (a file with another content is only removed after you answer y). -QuayVe alone is the dry run of that.
  Then open the three URLs in the browser, wait 35 minutes, open them again: each page must still be there.
  Exit 0 = every step passed; 1 = a step failed; 2 = -ApDung inside an AI session.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\owner\thu-url9692.ps1
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\owner\thu-url9692.ps1 -ApDung
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\owner\thu-url9692.ps1 -QuayVe -ApDung
#>
param(
    [switch]$ApDung,
    [switch]$QuayVe,
    [string]$OneCrew = 'D:\OneCrewRuns\url9692\runtime-thu\Scripts\onecrew.exe',
    [string]$Project = 'D:\TamNT\Workspace\11.OneCrew\onecrew',
    [string]$RealState = 'D:\TamNT\Workspace\11.OneCrew\state-v2-real',
    [string]$DevState = 'D:\OneCrewRuns\onecrew-development\state',
    [string]$CoordState = 'D:\OneCrewRuns\dieu-phoi-state'
)
$ErrorActionPreference = 'Continue'
if ($ApDung -and ($env:CLAUDE_CODE_CHILD_SESSION -or $env:CLAUDECODE)) { Write-Host 'KHONG DAT: -ApDung dang o trong phien AI; mo terminal rieng cua ban roi chay lai.' -ForegroundColor Red; exit 2 }
$savedEncoding = [Console]::OutputEncoding       # OneCrew writes UTF-8: read it as UTF-8 while it runs, give the console its own code page back after
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }
$OutputEncoding = [Text.Encoding]::UTF8
$savedIo = $env:PYTHONIOENCODING
$env:PYTHONIOENCODING = 'utf-8'
$noBom = New-Object System.Text.UTF8Encoding $false

$ledgers = @(
    [pscustomobject]@{ Name = 'so that'; State = $RealState; Port = 9692; File = $false },
    [pscustomobject]@{ Name = 'so phat trien'; State = $DevState; Port = 9693; File = $true },
    [pscustomobject]@{ Name = 'so rieng dieu phoi'; State = $CoordState; Port = 9694; File = $true }
)
$mode = if ($ApDung) { 'CHAY THAT' } else { 'CHAY THU (khong ghi gi, khong mo gi)' }
Write-Host ('URL9692 M2 - ' + $mode + $(if ($QuayVe) { ' - QUAY VE' } else { '' }))
$failed = $false

function Read-PortFile([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) { return $null }
    try { return [IO.File]::ReadAllText($path, [Text.Encoding]::UTF8).Trim() } catch { return '(khong doc duoc)' }
}

function Get-Listener([int]$port) {
    $rows = @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)
    if ($rows.Count -eq 0) { return 'trong' }
    $names = foreach ($row in $rows) { $p = Get-Process -Id $row.OwningProcess -ErrorAction SilentlyContinue; '{0} pid {1}' -f $(if ($p) { $p.ProcessName } else { '?' }), $row.OwningProcess }
    return 'dang nghe: ' + (($names | Select-Object -Unique) -join ', ')
}

function Invoke-Track([string]$state, [string[]]$verb) {
    $out = (& $OneCrew --project $Project --state-root $state track @verb 2>$null | ForEach-Object { "$_" }) -join "`n"     # stdout only: the CLI prints its JSON (errors too) there
    $code = $LASTEXITCODE
    $value = $null
    try { $value = $out | ConvertFrom-Json } catch { $value = $null }
    return [pscustomobject]@{ Code = $code; Text = $out; Value = $value }
}

function Get-Health([string]$url) {
    try {
        $request = [Net.HttpWebRequest]::Create($url + 'api/health')
        $request.Proxy = $null
        $request.Timeout = 10000
        $response = $request.GetResponse()
        try { $reader = New-Object IO.StreamReader($response.GetResponseStream(), [Text.Encoding]::UTF8); return ($reader.ReadToEnd() | ConvertFrom-Json) }
        finally { $response.Close() }
    } catch { return $null }
}

if (-not (Test-Path -LiteralPath $OneCrew)) { Write-Host ('KHONG DAT: khong tim thay runtime thu ' + $OneCrew) -ForegroundColor Red; $failed = $true }
if (-not (Test-Path -LiteralPath $Project)) { Write-Host ('KHONG DAT: khong tim thay du an ' + $Project) -ForegroundColor Red; $failed = $true }
foreach ($l in $ledgers) {
    if (-not (Test-Path -LiteralPath $l.State)) { Write-Host ('KHONG DAT: khong tim thay ' + $l.Name + ' ' + $l.State) -ForegroundColor Red; $failed = $true }
}
if ($failed) { [Console]::OutputEncoding = $savedEncoding; $env:PYTHONIOENCODING = $savedIo; exit 1 }
if (-not $QuayVe -and (Test-Path -LiteralPath (Join-Path $RealState 'tracking.json'))) {
    Write-Host ('LUU Y: so that co tracking.json (' + (Read-PortFile (Join-Path $RealState 'tracking.json')) + '): cong cua no khong phai 9692; script nay khong dong vao tep do.') -ForegroundColor Yellow
}

try {
    if ($QuayVe) {
        foreach ($l in $ledgers) {
            if (-not $ApDung) { Write-Host ('[thu] se chay: track stop cho ' + $l.Name + ' (' + $l.State + ')'); continue }
            $r = Invoke-Track $l.State @('stop')
            $stopped = $r.Value -and $r.Value.stopped
            Write-Host ($l.Name + ': track stop -> ' + $(if ($stopped) { 'da dung ' + $r.Value.url } else { 'khong dung gi (' + $(if ($r.Value) { $r.Value.reason } else { $r.Text }) + ')' }))
        }
        foreach ($l in ($ledgers | Where-Object { $_.File })) {
            $path = Join-Path $l.State 'tracking.json'
            $now = Read-PortFile $path
            if ($null -eq $now) { Write-Host ($l.Name + ': khong co tracking.json, khong go gi.'); continue }
            $ours = ($now -replace '\s', '') -eq ('{"port":' + $l.Port + '}')
            if (-not $ApDung) { Write-Host ('[thu] se go ' + $path + ' (dang la ' + $now + $(if ($ours) { '' } else { '; KHAC ban script ghi: se hoi truoc' }) + ')'); continue }
            if (-not $ours) {
                $answer = Read-Host ($path + ' dang la ' + $now + ' (khac ban script ghi). Van go? y/n')
                if ($answer -ne 'y') { Write-Host ($l.Name + ': giu nguyen tracking.json.'); continue }
            }
            Remove-Item -LiteralPath $path -Force
            Write-Host ($l.Name + ': da go ' + $path)
        }
        foreach ($l in $ledgers) { Write-Host ('cong ' + $l.Port + ': ' + (Get-Listener $l.Port)) }
        Write-Host $(if ($ApDung) { 'XONG quay ve.' } else { 'Chay thu quay ve xong: khong ghi gi, khong dung gi.' })
        exit 0
    }

    foreach ($l in ($ledgers | Where-Object { $_.File })) {
        $path = Join-Path $l.State 'tracking.json'
        $want = '{"port": ' + $l.Port + '}'
        $now = Read-PortFile $path
        if ($null -ne $now -and ($now -replace '\s', '') -eq ($want -replace '\s', '')) { Write-Host ($l.Name + ': tracking.json da co ' + $want + ', giu nguyen.'); continue }
        if (-not $ApDung) {
            Write-Host ('[thu] se ghi ' + $path + ' = ' + $want + $(if ($null -ne $now) { ' (dang la ' + $now + ': se hoi truoc khi ghi de)' } else { '' })); continue
        }
        if ($null -ne $now) {
            $answer = Read-Host ($path + ' dang la ' + $now + '. Ghi de thanh ' + $want + '? y/n')
            if ($answer -ne 'y') { Write-Host ($l.Name + ': giu nguyen tracking.json; cong cua so nay se theo tep do.') -ForegroundColor Yellow; continue }
        }
        [IO.File]::WriteAllText($path, $want, $noBom)
        Write-Host ($l.Name + ': da ghi ' + $path + ' = ' + $want)
    }

    foreach ($l in $ledgers) { Write-Host ('cong ' + $l.Port + ' truoc khi mo: ' + (Get-Listener $l.Port)) }
    if (-not $ApDung) {
        foreach ($l in $ledgers) { Write-Host ('[thu] se chay: ' + $OneCrew + ' --project ' + $Project + ' --state-root ' + $l.State + ' track open --no-browser  (mong doi http://127.0.0.1:' + $l.Port + '/)') }
        Write-Host 'Chay thu xong: khong ghi gi, khong mo server nao. Chay lai voi -ApDung trong terminal cua ban.'
        exit 0
    }

    $urls = @()
    foreach ($l in $ledgers) {
        $r = Invoke-Track $l.State @('open', '--no-browser')
        $url = if ($r.Value) { $r.Value.url } else { $null }
        $want = 'http://127.0.0.1:' + $l.Port + '/'
        if ($r.Code -eq 0 -and $url -eq $want) {
            Write-Host ($l.Name + ': ' + $url + $(if ($r.Value.reused) { ' (dung lai server dang chay)' } else { ' (server moi)' })) -ForegroundColor Green
        } else {
            Write-Host ($l.Name + ': KHONG DAT (exit ' + $r.Code + '): ' + $(if ($r.Value -and $r.Value.error) { $r.Value.error } else { $r.Text })) -ForegroundColor Red
            $failed = $true
        }
        $urls += [pscustomobject]@{ Ledger = $l; Url = $want }
    }
    Write-Host ''
    Write-Host 'Hoi /api/health tung dia chi:'
    foreach ($u in $urls) {
        $h = Get-Health $u.Url
        if ($h -and $h.ok) {
            Write-Host ('  ' + $u.Url + '  ok, ' + $h.server + ', phien ban ' + $h.version + ', pid ' + $h.pid + ', so ' + $h.state_root) -ForegroundColor Green
        } else {
            Write-Host ('  ' + $u.Url + '  KHONG tra loi /api/health') -ForegroundColor Red
            $failed = $true
        }
    }
    Write-Host ''
    if ($failed) { Write-Host 'KHONG DAT: xem dong do o tren.' -ForegroundColor Red; exit 1 }
    Write-Host 'DAT: ba dia chi tren dang mo. Mo ca ba trong trinh duyet, 35 phut sau mo lai: trang van con la dat.' -ForegroundColor Green
    exit 0
} finally {
    [Console]::OutputEncoding = $savedEncoding
    $env:PYTHONIOENCODING = $savedIo
}
