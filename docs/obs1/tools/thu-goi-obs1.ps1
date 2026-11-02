# thu-goi-obs1.ps1 - owner check of an OBS-1 trial package, run FROM THE PACKAGE (shipped as <package>\verify\thu-goi-obs1.ps1).
#   powershell -ExecutionPolicy Bypass -File "<package>\verify\thu-goi-obs1.ps1" [-Package <folder>] [-Work <new folder>] [-Python <python.exe>]
# Steps: 1 read manifest.json, check the wheel hash and that manifest/wheel/verifier match SHA256SUMS;
#        2 run verify\verify_obs1.py -> <work>\verify-report.json (V1..V12; the page in a headless browser when one is on the machine).
# Prints "DAT: ..." and exits 0 ONLY when the verifier exited 0 in THIS run and wrote a report (new, by this run) that names this package, its version
# and code commit with result "pass". Everything else prints "KHONG DAT: ..." and exits non-zero. The real ledger, hook-projects.json, PATH and
# provider settings are never touched (the verifier redirects LOCALAPPDATA/APPDATA/TEMP into <work>).
param([string]$Package = '', [string]$Work = '', [string]$Python = 'C:\Users\NUC\AppData\Local\Programs\Python\Python313\python.exe')
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
function Fail([string]$t) { Write-Host ('KHONG DAT: ' + $t) -ForegroundColor Red; exit 1 }
if (-not $Package) { $Package = Split-Path -Parent $PSScriptRoot }
$pkg = [System.IO.Path]::GetFullPath($Package).TrimEnd('\')
if (-not (Test-Path -LiteralPath "$pkg\manifest.json")) { Fail "khong thay manifest.json trong $pkg" }
if (-not (Test-Path -LiteralPath $Python)) { Fail "khong thay python: $Python" }
$man = Get-Content -LiteralPath "$pkg\manifest.json" -Raw | ConvertFrom-Json
if (-not $Work) { $Work = "D:\OneCrewRuns\obs1 thu $($man.version) $(Get-Date -Format yyyyMMdd-HHmmss)" }
if (Test-Path -LiteralPath $Work) { if (@(Get-ChildItem -LiteralPath $Work -Force).Count -gt 0) { Fail "thu muc ket qua da co file: $Work" } }
New-Item -ItemType Directory -Path $Work -Force | Out-Null
$wheel = "$pkg\wheel\$($man.wheel.name)"
$sha = (Get-FileHash -LiteralPath $wheel -Algorithm SHA256).Hash.ToLower()
if ($sha -ne $man.wheel.sha256.ToLower()) { Fail "SHA256 wheel $sha khac manifest $($man.wheel.sha256)" }
$sums = @{}
foreach ($line in Get-Content -LiteralPath "$pkg\SHA256SUMS") { $parts = $line -split '  ', 2; if ($parts.Count -eq 2) { $sums[$parts[1]] = $parts[0].ToLower() } }
foreach ($rel in @('manifest.json', "wheel/$($man.wheel.name)", 'verify/verify_obs1.py', 'verify/scenario_obs1.py', 'verify/onecrew_fake_claude_v24.py')) {
    $h = (Get-FileHash -LiteralPath ("$pkg\" + $rel.Replace('/', '\')) -Algorithm SHA256).Hash.ToLower()
    if (-not $sums.ContainsKey($rel) -or $sums[$rel] -ne $h) { Fail "SHA256SUMS khong khop: $rel" }
}
Write-Host "== goi $pkg ($($man.version), code $($man.code_commit.Substring(0,7)), wheel sha256 dung)"
$started = Get-Date
& $Python -I "$pkg\verify\verify_obs1.py" $pkg $Work
$code = $LASTEXITCODE
$report = "$Work\verify-report.json"
if (-not (Test-Path -LiteralPath $report)) { Fail "verifier khong ghi $report (exit $code)" }
$item = Get-Item -LiteralPath $report
if ($item.LastWriteTime -lt $started.AddSeconds(-2) -or $item.LastWriteTime -gt (Get-Date).AddMinutes(1)) { Fail "bao cao khong phai cua lan chay nay" }
$r = Get-Content -LiteralPath $report -Raw | ConvertFrom-Json
if ($r.package -ne $pkg) { Fail "bao cao cua goi khac: $($r.package)" }
if ($r.manifest.version -ne $man.version -or $r.manifest.code_commit -ne $man.code_commit) { Fail "bao cao khong dung version/commit" }
$passed = @($r.steps | Where-Object { $_.result -eq 'pass' }).Count
if ($code -ne 0 -or $r.result -ne 'pass') { Fail "verifier exit $code, result $($r.result) ($passed/$($r.steps.Count)); xem $report" }
Write-Host ("DAT: goi OBS-1 $($man.version) ($($man.code_commit.Substring(0,7))) kiem $passed/$($r.steps.Count) buoc; do tre ghi->trang " + $r.measures.latency_write_to_overview_seconds + " s; bao cao $report; anh trang web trong $Work\evidence") -ForegroundColor Green
exit 0
