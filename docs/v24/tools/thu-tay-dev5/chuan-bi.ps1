# chuan-bi.ps1 - bai 2 cua huong dan thu OneCrew 2.4 (goi chua script nay, hoac goi dev5 da biet). DOT-SOURCE trong cua so PowerShell se go cac lenh thu:
#   . "D:\OneCrewRuns\v24\pkg\thu-tay-dev5\chuan-bi.ps1" [-Lab <thu muc moi>] [-Source <repo Git cua ban>]
# (khong chay bang `powershell -File`: tien trinh con ket thuc thi cua so cua ban khong o trong moi truong thu).
# Lam: tao <lab> moi, ghi dau so huu <lab>\.lab-thu-dev5.json + muc trong labs.json canh script (chi don-dep.ps1 xoa duoc lab co ca hai),
# doi LOCALAPPDATA/APPDATA/TEMP/TMP cua cua so nay -> <lab>\env, venv thu + wheel dev5 (kiem SHA256), ban sao project doc lap, `onecrew init`,
# `doctor`, roi KIEM: registry hook thu nam trong <lab>\env, registry that khong doi hash, hook ban sao tro exe thu; cuoi cung dot-source
# vao-moi-truong.ps1 de cua so nay o trong moi truong thu ($exe $proj $state ... va $labOk = $true).
# Khong -Source: tao project mau (Git, 1 file). Co -Source: `git clone --no-hardlinks`, bo remote, xoa .onecrew va .claude\settings.local.json neu
# chung duoc commit. Khong dung den CLAUDECODE / CLAUDE_CODE_CHILD_SESSION (guard owner cua OneCrew giu nguyen). Khong `exit`: that bai ->
# KHONG DAT, $labOk = $false, dung ngay (cac buoc sau khong chay).
param([string]$Lab = 'D:\OneCrewRuns\v24 thu tay dev5', [string]$Source = '')
$labOk = $false
$py  = 'C:\Users\NUC\AppData\Local\Programs\Python\Python313\python.exe'
$pkg = $null
foreach ($cand in @((Split-Path -Parent (Split-Path -Parent $PSScriptRoot)), 'D:\OneCrewRuns\v24\pkg\onecrew-2.4.0.dev5-beta')) {   # <package>\verify\thu-tay -> <package>; else the known package
    if ($cand -and (Test-Path -LiteralPath (Join-Path $cand 'manifest.json') -PathType Leaf) -and (Test-Path -LiteralPath (Join-Path $cand 'wheel') -PathType Container)) { $pkg = [System.IO.Path]::GetFullPath($cand).TrimEnd('\'); break }
}
if (-not $pkg) { Write-Host 'KHONG DAT: khong tim thay goi (manifest.json) canh script hay o duong dan da biet' -ForegroundColor Red }
$man = if ($pkg) { Get-Content -LiteralPath (Join-Path $pkg 'manifest.json') -Raw | ConvertFrom-Json } else { $null }
$labsFile = Join-Path $env:USERPROFILE '.onecrew-thu-tay\labs.json'       # ngoai goi, ngoai lab: bang chung thu hai cua don-dep.ps1
function Script:CB-Fail([string]$t) { Write-Host ('KHONG DAT: ' + $t) -ForegroundColor Red; Write-Host 'Dung tai day; khong go lenh thu trong cua so nay.' }
function Script:CB-Hash([string]$p) { if (Test-Path -LiteralPath $p) { (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash } else { 'absent' } }
$cbOk = $true
$lab = [System.IO.Path]::GetFullPath($Lab).TrimEnd('\')
$venv = "$lab\venv"; $proj = "$lab\project"; $state = "$lab\so"; $exe = "$venv\Scripts\onecrew.exe"
if (-not $env:ONECREW_LAB_REAL_LOCALAPPDATA) {   # gia tri that cua cua so nay, nho mot lan (doi chieu registry that; roi-lab.ps1 tra lai)
    $env:ONECREW_LAB_REAL_LOCALAPPDATA = $env:LOCALAPPDATA; $env:ONECREW_LAB_REAL_APPDATA = $env:APPDATA; $env:ONECREW_LAB_REAL_TEMP = $env:TEMP; $env:ONECREW_LAB_REAL_TMP = $env:TMP
}
$registryThat = Join-Path $env:ONECREW_LAB_REAL_LOCALAPPDATA 'OneCrew\hook-projects.json'
$registryThu = "$lab\env\LocalAppData\OneCrew\hook-projects.json"
$version = if ($man) { $man.version } else { '' }
$wheel = if ($man) { "$pkg\wheel\$($man.wheel.name)" } else { '' }
$sha = if ($man) { $man.wheel.sha256 } else { '' }
$oldEAP = $ErrorActionPreference; $ErrorActionPreference = 'Stop'
try {
    if (-not $pkg) { throw 'khong tim thay goi' }
    if (($lab + '\').StartsWith($pkg + '\', [StringComparison]::OrdinalIgnoreCase)) { throw "lab nam trong goi: $lab" }
    if ((($lab -split '\\') | Where-Object { $_ }).Count -lt 3) { throw "lab qua nong (can it nhat D:\<thu muc>\<lab>): $lab" }
    if (Test-Path -LiteralPath $lab) { throw "lab da co: $lab (chon -Lab ten moi, hoac don-dep.ps1 lab cu)" }
    if ($Source -and -not (Test-Path -LiteralPath (Join-Path $Source '.git'))) { throw "-Source khong phai repo Git: $Source" }
    $registryThatTruoc = CB-Hash $registryThat
    Write-Host "== 1. goi $pkg ($version)"; if ((CB-Hash $wheel).ToLower() -ne $sha.ToLower()) { throw "SHA256 wheel khac $sha" }; Write-Host "   wheel $($man.wheel.name) sha256 dung"
    Write-Host "== 2. lab moi + dau so huu"
    New-Item -ItemType Directory -Path "$lab\env\LocalAppData", "$lab\env\AppData", "$lab\env\Temp" -Force | Out-Null
    $nonce = [guid]::NewGuid().ToString('N')
    $marker = @{ created_by = 'chuan-bi.ps1'; lab = $lab; nonce = $nonce; created_at = (Get-Date).ToString('o'); package = $pkg; version = $version }
    ($marker | ConvertTo-Json) | Set-Content -LiteralPath "$lab\.lab-thu-dev5.json" -Encoding utf8
    $all = New-Object System.Collections.Generic.List[object]
    if (Test-Path -LiteralPath $labsFile) {
        try { $old = Get-Content -LiteralPath $labsFile -Raw | ConvertFrom-Json } catch { $old = $null }
        if ($old -ne $null -and $old.PSObject.Properties['value'] -and -not ($old -is [array])) { $old = $old.value }   # a wrapped list written by an older build
        foreach ($e in @($old)) { if ($e -and $e.lab -and $e.lab.ToLowerInvariant() -ne $lab.ToLowerInvariant()) { $all.Add([pscustomobject]@{ lab = $e.lab; nonce = $e.nonce; created_at = $e.created_at }) } }
    }
    $all.Add([pscustomobject]@{ lab = $lab; nonce = $nonce; created_at = $marker.created_at })
    New-Item -ItemType Directory -Path (Split-Path -Parent $labsFile) -Force | Out-Null
    (ConvertTo-Json -InputObject $all.ToArray() -Depth 3) | Set-Content -LiteralPath $labsFile -Encoding utf8
    Write-Host "   $lab\.lab-thu-dev5.json + muc trong $labsFile"
    Write-Host "== 3. bien moi truong cua cua so nay -> $lab\env"
    $env:LOCALAPPDATA = "$lab\env\LocalAppData"; $env:APPDATA = "$lab\env\AppData"; $env:TEMP = "$lab\env\Temp"; $env:TMP = "$lab\env\Temp"
    Write-Host "== 4. venv thu + cai wheel"
    & $py -m venv $venv; if ($LASTEXITCODE -ne 0) { throw 'python -m venv' }
    & "$venv\Scripts\python.exe" -I -m pip install --no-index --no-build-isolation --disable-pip-version-check -q $wheel; if ($LASTEXITCODE -ne 0) { throw 'pip install wheel' }
    $ver = (& $exe --version 2>&1); if ($LASTEXITCODE -ne 0 -or "$ver" -notmatch [regex]::Escape($version)) { throw "onecrew --version: $ver (can $version)" }; Write-Host "   $ver"
    Write-Host "== 5. ban sao project doc lap"
    if ($Source) {
        git clone -q --no-hardlinks $Source $proj; if ($LASTEXITCODE -ne 0) { throw 'git clone' }
        git -C $proj remote remove origin 2>$null
        foreach ($f in @("$proj\.onecrew", "$proj\.claude\settings.local.json")) { if (Test-Path -LiteralPath $f) { Remove-Item -LiteralPath $f -Recurse -Force; Write-Host "   bo $f (cua ban goc)" } }
        Write-Host "   clone tu $Source, khong remote"
    } else {
        New-Item -ItemType Directory -Path $proj -Force | Out-Null
        Set-Content -LiteralPath "$proj\a.txt" -Value 'one' -Encoding ascii
        git -C $proj init -q; git -C $proj -c user.name=thu -c user.email=thu@example.invalid add a.txt; git -C $proj -c user.name=thu -c user.email=thu@example.invalid commit -q -m 'mau'
        if ($LASTEXITCODE -ne 0) { throw 'git init project mau' }
        Write-Host "   project mau: $proj (a.txt, 1 commit)"
    }
    Write-Host "== 6. onecrew init + doctor (ghi vao ban sao va $state)"
    & $exe init --project $proj --state-root $state --yes; if ($LASTEXITCODE -ne 0) { throw 'onecrew init' }
    & $exe --project $proj --state-root $state doctor; if ($LASTEXITCODE -ne 0) { throw 'onecrew doctor' }
    Write-Host "== 7. kiem cach ly"
    if (-not (Test-Path -LiteralPath $registryThu)) { throw "registry thu khong duoc tao: $registryThu" }
    $reg = Get-Content -LiteralPath $registryThu -Raw
    $projJson = $proj.ToLowerInvariant().Replace('\', '\\')     # JSON doubles the backslashes
    if ($reg.ToLowerInvariant().IndexOf($projJson) -lt 0) { throw "registry thu khong co muc cua $proj" }
    if (-not (Test-Path -LiteralPath "$proj\.onecrew\config.json")) { throw 'ban sao khong co .onecrew\config.json' }
    $hook = Get-Content -LiteralPath "$proj\.claude\settings.local.json" -Raw
    if ($hook.IndexOf($exe.Replace('\', '\\')) -lt 0 -and $hook.IndexOf($exe) -lt 0) { throw 'hook cua ban sao khong tro vao exe thu' }
    $registryThatSau = CB-Hash $registryThat
    if ($registryThatSau -ne $registryThatTruoc) { throw "registry THAT doi: $registryThat ($registryThatTruoc -> $registryThatSau)" }
    Write-Host "   registry thu: $registryThu (co muc cua ban sao)"
    Write-Host "   registry that: $registryThat khong doi ($registryThatTruoc)"
    Write-Host "   hook ban sao: $proj\.claude\settings.local.json -> $exe"
} catch {
    $cbOk = $false
    CB-Fail "$($_.Exception.Message)"
} finally {
    $ErrorActionPreference = $oldEAP
}
if ($cbOk) {
    Write-Host "== 8. vao moi truong thu (kiem lai lab)"
    . (Join-Path $PSScriptRoot 'vao-moi-truong.ps1') -Lab $lab
    if ($labOk) { Write-Host "DAT: moi truong thu san sang tai $lab. Go cac lenh thu trong CUA SO NAY; cua so moi: dot-source vao-moi-truong.ps1 -Lab `"$lab`"." }
} else {
    Remove-Variable -Name exe, proj, state, venv, registryThu -ErrorAction SilentlyContinue
}
