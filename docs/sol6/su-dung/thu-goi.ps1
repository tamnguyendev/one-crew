# thu-goi.ps1 - thu goi OneCrew Sol6.4 tren mot venv moi trong mot thu muc moi: kiem SHA256 wheel, cai wheel, chay smoke 38 dieu kien.
#   powershell -ExecutionPolicy Bypass -File thu-goi.ps1 -Goi <thu muc goi da giai nen> -Python <python.exe> -Thu <thu muc MOI>
# Khong dung toi runtime, hook, so hay so dang ky that: moi thu nam trong -Thu. Smoke la fixture cuc bo, khong goi model, khong phai nghiem thu.
# Thoat 0 + "DAT" khi dat; 1 + "KHONG DAT: <ly do>" khi khong.
param([Parameter(Mandatory=$true)][string]$Goi, [Parameter(Mandatory=$true)][string]$Python, [Parameter(Mandatory=$true)][string]$Thu,
      [string]$WheelSha = '4f25c3991dc503aaa61ab31573fa99e948670b66e591e0e2bf68dbecd024a64f')
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
function Fail([string]$t) { Write-Host ('KHONG DAT: ' + $t) -ForegroundColor Red; exit 1 }
if (Test-Path -LiteralPath $Thu) { Fail "$Thu da ton tai: chon mot thu muc MOI" }
$wheel = Get-ChildItem -LiteralPath (Join-Path $Goi 'wheel') -Filter '*.whl' | Select-Object -First 1
if (-not $wheel) { Fail "khong thay wheel trong $Goi\wheel" }
$actual = (Get-FileHash -LiteralPath $wheel.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $WheelSha) { Fail "SHA256 wheel la $actual, can la $WheelSha" }
Write-Host "SHA256 wheel dung: $actual"
New-Item -ItemType Directory -Path (Join-Path $Thu 'wheel') | Out-Null
$Thu = (Resolve-Path -LiteralPath $Thu).ProviderPath
Copy-Item -LiteralPath $wheel.FullName -Destination (Join-Path $Thu 'wheel')
Copy-Item -LiteralPath (Join-Path $Goi 'tools\smoke_wheel.py') -Destination $Thu
$ErrorActionPreference = 'Continue'
& $Python -m venv (Join-Path $Thu 'venv')
if ($LASTEXITCODE -ne 0) { Fail 'khong tao duoc venv' }
$py = Join-Path $Thu 'venv\Scripts\python.exe'
& $py -m pip install -q --no-index --no-deps --disable-pip-version-check (Join-Path $Thu ('wheel\' + $wheel.Name))
if ($LASTEXITCODE -ne 0) { Fail 'khong cai duoc wheel' }
foreach ($name in 'PYTHONPATH', 'PYTHONHOME', 'CLAUDE_CODE_CHILD_SESSION', 'CLAUDECODE', 'ONECREW_ACTOR') { Remove-Item "Env:$name" -ErrorAction SilentlyContinue }
foreach ($pair in @(@('LOCALAPPDATA', 'may\local'), @('APPDATA', 'may\roaming'), @('TEMP', 'tmp'), @('TMP', 'tmp'))) {
    $p = Join-Path $Thu $pair[1]
    New-Item -ItemType Directory -Force -Path $p | Out-Null
    [Environment]::SetEnvironmentVariable($pair[0], $p, 'Process')
}
Push-Location -LiteralPath $Thu
& $py -I -B -X utf8 (Join-Path $Thu 'smoke_wheel.py') 2>&1 | Out-File (Join-Path $Thu 'smoke.log') -Encoding utf8
$code = $LASTEXITCODE
Pop-Location
if ($code -ne 0) { Fail "smoke thoat ma $code, xem $Thu\smoke.log" }
$result = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $Thu 'smoke-result.json') | ConvertFrom-Json
Write-Host ("DAT: onecrew {0}, {1} dieu kien smoke, thu muc thu {2}" -f $result.version, @($result.checks).Count, $Thu) -ForegroundColor Green
exit 0
