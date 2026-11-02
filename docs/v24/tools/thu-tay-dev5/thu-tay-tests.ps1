# thu-tay-tests.ps1 -Scripts <folder with chuan-bi/vao-moi-truong/don-dep> -Work <new test root> - the three Codex findings on the dev5 lab scripts.
# Every case runs REAL PowerShell child processes and the real filesystem under <Work> (disposable); the only fakes: a fake AI marker value and
# fake "lab-like" folders. Expected: red on the old scripts (c17e465), green on the current ones. Writes <Work>\results.json; exit 0 when all pass.
param([Parameter(Mandatory=$true)][string]$Scripts, [Parameter(Mandatory=$true)][string]$Work, [string]$PackageDir = 'D:\OneCrewRuns\v24\pkg\onecrew-2.4.0.dev5-beta')
$ErrorActionPreference = 'Continue'
$Work = [System.IO.Path]::GetFullPath($Work).TrimEnd('\')
if (Test-Path -LiteralPath $Work) { Write-Host "work exists: $Work"; exit 3 }
New-Item -ItemType Directory -Path $Work -Force | Out-Null
$ps = 'powershell'
$results = [ordered]@{}
function Case([string]$name, [scriptblock]$body) {
    try { $r = & $body } catch { $r = [ordered]@{ ok = $false; error = "$($_.Exception.Message)" } }
    $results[$name] = $r
    Write-Host ("{0,-44} {1}" -f $name, $(if ($r.ok) { 'pass' } else { 'FAIL' }))
}
function Child([string]$cmd, [hashtable]$extraEnv = @{}) {
    # a fresh PowerShell with the REAL user environment (never this test's variables), optional extra variables; returns stdout lines + exit code
    $old = @{}
    foreach ($k in $extraEnv.Keys) { $old[$k] = [Environment]::GetEnvironmentVariable($k); [Environment]::SetEnvironmentVariable($k, $extraEnv[$k]) }
    try { $out = & $ps -NoProfile -ExecutionPolicy Bypass -Command $cmd 2>&1 | ForEach-Object { "$_" }; $code = $LASTEXITCODE }
    finally { foreach ($k in $extraEnv.Keys) { [Environment]::SetEnvironmentVariable($k, $old[$k]) } }
    return @{ out = $out; code = $code }
}
$chuanBi = Join-Path $Scripts 'chuan-bi.ps1'; $vao = Join-Path $Scripts 'vao-moi-truong.ps1'; $donDep = Join-Path $Scripts 'don-dep.ps1'
function DonDep([string]$p) {
    # don-dep as the guide runs it: its own PowerShell process, so its exit code is the process exit code
    $out = & $ps -NoProfile -ExecutionPolicy Bypass -File $donDep -Lab $p 2>&1 | ForEach-Object { "$_" }
    return @{ out = $out; code = $LASTEXITCODE }
}
$realReg = Join-Path $env:LOCALAPPDATA 'OneCrew\hook-projects.json'
$regBefore = if (Test-Path $realReg) { (Get-FileHash $realReg -Algorithm SHA256).Hash } else { 'absent' }

# ---- P1: don-dep must refuse what chuan-bi did not make ---------------------------------------------------------------------------
Case 'p1_refuses_lab_like_folder_not_made_by_chuan_bi' {
    $fake = "$Work\unrelated-folder"; New-Item -ItemType Directory -Path "$fake\env\LocalAppData", "$fake\venv", "$fake\so" -Force | Out-Null
    Set-Content "$fake\keep.txt" 'must survive'
    $r = DonDep $fake
    [ordered]@{ ok = ($r.code -ne 0 -and (Test-Path "$fake\keep.txt")); exit = $r.code; keep_survived = (Test-Path "$fake\keep.txt"); tail = ($r.out | Select-Object -Last 1) }
}
Case 'p1_refuses_shallow_and_package_paths' {
    $a = DonDep 'D:\OneCrewRuns'
    $b = DonDep (Join-Path $PackageDir 'not-a-lab')
    $c = DonDep (Split-Path -Parent $PackageDir)
    [ordered]@{ ok = ($a.code -ne 0 -and $b.code -ne 0 -and $c.code -ne 0 -and (Test-Path (Join-Path $PackageDir 'manifest.json'))); exits = @($a.code, $b.code, $c.code); tails = @(($a.out | Select-Object -Last 1), ($b.out | Select-Object -Last 1), ($c.out | Select-Object -Last 1)) }
}
Case 'p1_refuses_fabricated_marker_without_ledger_entry' {
    $fake = "$Work\forged-lab"; New-Item -ItemType Directory -Path "$fake\env\LocalAppData", "$fake\venv", "$fake\so" -Force | Out-Null
    Set-Content "$fake\keep.txt" 'must survive'
    (@{ created_by = 'chuan-bi.ps1'; lab = $fake; nonce = 'deadbeef'; created_at = '2026-11-02' } | ConvertTo-Json) | Set-Content "$fake\.lab-thu-dev5.json"
    $r = DonDep $fake
    [ordered]@{ ok = ($r.code -ne 0 -and (Test-Path "$fake\keep.txt")); exit = $r.code; tail = ($r.out | Select-Object -Last 1) }
}
# a real lab (the scripts' own way), used by the next cases
$lab = "$Work\lab real"
Case 'p2_dot_source_chuan_bi_leaves_the_window_in_the_lab' {
    $r = Child ". '$chuanBi' -Lab '$lab'; Write-Output ('EXE_DEFINED=' + [bool](Get-Variable exe -ErrorAction SilentlyContinue)); Write-Output ('LABOK=' + `$labOk); Write-Output ('ENV_IN_LAB=' + (`$env:LOCALAPPDATA -like '$lab*')); Write-Output ('EXE_EXISTS=' + (Test-Path `$exe)); Write-Output ('REG_THU=' + (Test-Path '$lab\env\LocalAppData\OneCrew\hook-projects.json'))"
    $o = $r.out -join "`n"
    [ordered]@{ ok = ($o -match 'EXE_DEFINED=True' -and $o -match 'LABOK=True' -and $o -match 'ENV_IN_LAB=True' -and $o -match 'EXE_EXISTS=True' -and $o -match 'REG_THU=True' -and $o -match '(?m)^DAT: moi truong thu san sang'); markers = @($o -split "`n" | Where-Object { $_ -match '^(EXE_|LABOK|ENV_|REG_|KHONG DAT|DAT)' }) }
}
Case 'p2_new_window_dot_source_vao_then_harmless_report' {
    $r = Child ". '$vao' -Lab '$lab'; Write-Output ('LABOK=' + `$labOk); Write-Output ('ENV_IN_LAB=' + (`$env:LOCALAPPDATA -like '$lab*')); & `$exe --project `$proj --state-root `$state support report --text 'thu' --key t1 --json | Out-Null; Write-Output ('REPORT_EXIT=' + `$LASTEXITCODE); Write-Output ('LEDGER_IN_LAB=' + (Test-Path '$lab\so\ledger.sqlite3'))"
    $o = $r.out -join "`n"
    [ordered]@{ ok = ($o -match 'LABOK=True' -and $o -match 'ENV_IN_LAB=True' -and $o -match 'REPORT_EXIT=0' -and $o -match 'LEDGER_IN_LAB=True'); lines = @($o -split "`n" | Where-Object { $_ -match '^(LABOK|ENV_|REPORT|LEDGER)' }) }
}
Case 'p2_vao_refuses_a_folder_that_is_not_a_lab' {
    $fake = "$Work\not-a-lab"; New-Item -ItemType Directory -Path "$fake\env\LocalAppData" -Force | Out-Null
    $r = Child ". '$vao' -Lab '$fake'; Write-Output ('LABOK=' + `$labOk); Write-Output ('EXE_DEFINED=' + [bool](Get-Variable exe -ErrorAction SilentlyContinue)); Write-Output ('ENV_REAL=' + (`$env:LOCALAPPDATA -eq '$env:LOCALAPPDATA'))"
    $o = $r.out -join "`n"
    [ordered]@{ ok = ($o -match 'LABOK=False' -and $o -match 'EXE_DEFINED=False' -and $o -match 'ENV_REAL=True' -and $o -match 'KHONG DAT'); lines = @($o -split "`n" | Where-Object { $_ -match '^(LABOK|EXE_|ENV_|KHONG)' }) }
}
Case 'p2_ai_markers_kept_and_owner_verb_refused' {
    $r = Child ". '$vao' -Lab '$lab'; Write-Output ('MARKER_AFTER=' + `$env:CLAUDE_CODE_CHILD_SESSION); `$o = & `$exe --project `$proj --state-root `$state support confirm FB-00000000000000000000000000000000 2>&1; Write-Output ('CONFIRM_EXIT=' + `$LASTEXITCODE); Write-Output ('CONFIRM_MSG=' + ((`$o | Out-String) -replace '\s+', ' ').Substring(0, [Math]::Min(160, ((`$o | Out-String) -replace '\s+', ' ').Length)))" @{ CLAUDE_CODE_CHILD_SESSION = 'fixture-marker'; CLAUDECODE = '1' }
    $o = $r.out -join "`n"
    $msg = ($o -split "`n" | Where-Object { $_ -like 'CONFIRM_MSG=*' } | Select-Object -First 1)
    [ordered]@{ ok = ($o -match 'MARKER_AFTER=fixture-marker' -and $o -match 'CONFIRM_EXIT=[1-9]' -and $msg -match '(?i)AI|session|owner'); lines = @($o -split "`n" | Where-Object { $_ -match '^(MARKER|CONFIRM)' }) }
}
Case 'p1_refuses_the_real_lab_through_a_junction' {
    $junction = "$Work\junction-to-lab"
    cmd /c mklink /J "$junction" "$lab" | Out-Null
    $r = DonDep $junction
    [ordered]@{ ok = ($r.code -ne 0 -and (Test-Path "$lab\.lab-thu-dev5.json")); exit = $r.code; tail = ($r.out | Select-Object -Last 1) }
}
Case 'p1_refuses_from_a_window_whose_env_points_into_the_lab' {
    $r = Child ". '$vao' -Lab '$lab'; & '$ps' -NoProfile -ExecutionPolicy Bypass -File '$donDep' -Lab '$lab'; exit `$LASTEXITCODE"
    [ordered]@{ ok = ($r.code -ne 0 -and (Test-Path "$lab\.lab-thu-dev5.json")); exit = $r.code; tail = ($r.out | Select-Object -Last 1) }
}
Case 'p1_cleans_the_real_lab_and_verifies_it_is_gone' {
    $r = DonDep $lab
    $again = DonDep $lab
    [ordered]@{ ok = ($r.code -eq 0 -and -not (Test-Path $lab) -and $again.code -ne 0 -and (($r.out | Select-Object -Last 1) -like 'DAT:*')); exit = $r.code; tail = ($r.out | Select-Object -Last 1); again_exit = $again.code }
}
$regAfter = if (Test-Path $realReg) { (Get-FileHash $realReg -Algorithm SHA256).Hash } else { 'absent' }
$results['real_registry_unchanged_during_tests'] = [ordered]@{ ok = ($regAfter -eq $regBefore); before = $regBefore; after = $regAfter }
Write-Host ("{0,-44} {1}" -f 'real_registry_unchanged_during_tests', $(if ($regAfter -eq $regBefore) { 'pass' } else { 'FAIL' }))
$passed = @($results.Values | Where-Object { $_.ok }).Count
$summary = [ordered]@{ scripts = $Scripts; work = $Work; passed = "$passed/$($results.Count)"; cases = $results }
($summary | ConvertTo-Json -Depth 6) | Set-Content -LiteralPath "$Work\results.json" -Encoding utf8
Write-Host "RESULT $passed/$($results.Count) scripts=$Scripts"
exit $(if ($passed -eq $results.Count) { 0 } else { 1 })
