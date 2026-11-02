# chuan-bi.ps1 - bai 2 cua huong dan thu OneCrew 2.4.0.dev5: moi truong cach ly, venv thu, ban sao project doc lap, `onecrew init`, `doctor`,
# roi KIEM: registry hook duoc tao trong <lab>\env, registry that khong doi. Chay trong terminal cua ban (khong trong phien AI):
#   powershell -ExecutionPolicy Bypass -File "D:\OneCrewRuns\v24\pkg\thu-tay-dev5\chuan-bi.ps1" [-Lab <thu muc moi>] [-Source <repo Git cua ban>]
# Khong co -Source: tao mot project mau (Git, 1 file) de thu. Co -Source: `git clone --no-hardlinks` tu do, bo remote, xoa .onecrew va
# .claude\settings.local.json neu chung duoc commit (ban sao khong dung lai config/hook cua ban goc). Dung ngay khi mot buoc that bai (ma thoat 1);
# tu choi khi <lab> da co (ma thoat 2). In "DAT:" chi khi moi kiem deu dung.
param([string]$Lab = 'D:\OneCrewRuns\v24 thu tay dev5', [string]$Source = '')
$ErrorActionPreference = 'Stop'
function Fail([string]$t) { Write-Host ('KHONG DAT: ' + $t) -ForegroundColor Red; exit 1 }
function Refuse([string]$t) { Write-Host ('KHONG DAT: ' + $t + ' (chua chay gi)') -ForegroundColor Red; exit 2 }
function Hash([string]$p) { if (Test-Path -LiteralPath $p) { (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash } else { 'absent' } }
$labFull = [System.IO.Path]::GetFullPath($Lab).TrimEnd('\')
if (Test-Path -LiteralPath $labFull) { Refuse ("lab da co: $labFull (chon ten moi hoac don-dep.ps1 truoc)") }
if ($Source -and -not (Test-Path -LiteralPath (Join-Path $Source '.git'))) { Refuse ("-Source khong phai repo Git: $Source") }
. (Join-Path $PSScriptRoot 'vao-moi-truong.ps1') -Lab $labFull
if (-not $script:ok) { exit 2 }
$wheel = "$pkg\wheel\onecrew-2.4.0.dev5-py3-none-any.whl"
$sha = '6ed8ab8a8568d271d4fd7d4b89f7bbb5ed98c8b387898f109c2f9b73ae409655'
$registryThatTruoc = Hash $registryThat
Write-Host "== 1. wheel"; if ((Hash $wheel).ToLower() -ne $sha) { Fail "SHA256 wheel khac $sha" }; Write-Host "   sha256 dung"
Write-Host "== 2. venv thu + cai wheel"
& $py -m venv $venv; if ($LASTEXITCODE -ne 0) { Fail 'python -m venv' }
& "$venv\Scripts\python.exe" -I -m pip install --no-index --no-build-isolation --disable-pip-version-check -q $wheel; if ($LASTEXITCODE -ne 0) { Fail 'pip install wheel' }
$ver = (& $exe --version 2>&1); if ($LASTEXITCODE -ne 0 -or "$ver" -notmatch '2\.4\.0\.dev5') { Fail "onecrew --version: $ver" }; Write-Host "   $ver"
Write-Host "== 3. ban sao project doc lap"
if ($Source) {
    git clone -q --no-hardlinks $Source $proj; if ($LASTEXITCODE -ne 0) { Fail 'git clone' }
    git -C $proj remote remove origin 2>$null
    foreach ($f in @("$proj\.onecrew", "$proj\.claude\settings.local.json")) { if (Test-Path -LiteralPath $f) { Remove-Item -LiteralPath $f -Recurse -Force; Write-Host "   bo $f (cua ban goc)" } }
    Write-Host "   clone tu $Source, khong remote"
} else {
    New-Item -ItemType Directory -Path $proj -Force | Out-Null
    Set-Content -LiteralPath "$proj\a.txt" -Value 'one' -Encoding ascii
    git -C $proj init -q; git -C $proj -c user.name=thu -c user.email=thu@example.invalid add a.txt; git -C $proj -c user.name=thu -c user.email=thu@example.invalid commit -q -m 'mau'
    if ($LASTEXITCODE -ne 0) { Fail 'git init project mau' }
    Write-Host "   project mau: $proj (a.txt, 1 commit)"
}
Write-Host "== 4. onecrew init + doctor (ghi vao ban sao va $state)"
& $exe init --project $proj --state-root $state --yes; if ($LASTEXITCODE -ne 0) { Fail 'onecrew init' }
& $exe --project $proj --state-root $state doctor; if ($LASTEXITCODE -ne 0) { Fail 'onecrew doctor' }
Write-Host "== 5. kiem cach ly"
if (-not (Test-Path -LiteralPath $registryThu)) { Fail "registry thu khong duoc tao: $registryThu" }
$reg = Get-Content -LiteralPath $registryThu -Raw
if ($reg -notlike ('*' + ($proj -replace '\\', '\\') + '*') -and $reg.ToLower() -notlike ('*' + ($proj.ToLower() -replace '\\', '\\\\') + '*')) { Fail "registry thu khong co muc cua $proj" }
if (-not (Test-Path -LiteralPath "$proj\.onecrew\config.json")) { Fail 'ban sao khong co .onecrew\config.json' }
$hook = Get-Content -LiteralPath "$proj\.claude\settings.local.json" -Raw
if ($hook -notlike ('*' + ($exe -replace '\\', '\\\\') + '*') -and $hook -notlike ('*' + ($exe -replace '\\', '\\') + '*') -and $hook -notlike "*$exe*") { Fail 'hook cua ban sao khong tro vao exe thu' }
$registryThatSau = Hash $registryThat
if ($registryThatSau -ne $registryThatTruoc) { Fail "registry THAT doi: $registryThat ($registryThatTruoc -> $registryThatSau)" }
Write-Host "   registry thu: $registryThu (co muc cua ban sao)"
Write-Host "   registry that: $registryThat khong doi ($registryThatTruoc)"
Write-Host "   hook ban sao: $proj\.claude\settings.local.json -> $exe"
Write-Host ''
Write-Host "DAT: moi truong thu san sang tai $lab ($ver). Cua so nay dang o trong moi truong thu; cua so moi: dot-source vao-moi-truong.ps1 -Lab `"$lab`"."
exit 0
