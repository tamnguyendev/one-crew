# thu-goi.ps1 - owner test of a OneCrew 2.3 milestone package, run FROM THE PACKAGE
# (source: docs/v23/tools/thu_goi.ps1; build_milestone.py ships it as <package>\verify\thu-goi.ps1).
#
#   powershell -ExecutionPolicy Bypass -File "<package>\verify\thu-goi.ps1" [-Package <package folder>] [-Work <new folder>] [-Python <python.exe>]
#
# Steps: 1 read <package>\manifest.json (version, code commit, wheel name + sha256), check the wheel hash and that the manifest, the wheel and
#          the two tools match the package's SHA256SUMS;
#        2 run verify\verify_milestone.py -> <work>\verify\verify-report.json;
#        3 run verify\first_task_drill.py -> <work>\task dau tien\first-task-drill-log.json (the first task of the package README: fake claude,
#          temporary ledger). The real ledger, hook-projects.json, PATH and provider settings are never touched.
# It prints "DAT: ..." and exits 0 ONLY when, in THIS run, both tools exited 0 and each wrote a report that
#   - did not exist before the tool started and was written by it (start time and last write not before the tool started, not in the future),
#   - names this package and the manifest's version and code commit (the verifier report also the wheel name and sha256),
#   - says result pass with every required step passed, counted from the steps (the drill's required steps are those whose kind is not 'info');
# and the wheel still has the manifest hash afterwards. Anything else prints "KHONG DAT: ..." and exits non-zero:
# 1 = it ran or checked and failed, 2 = it refused to start (bad argument, missing file, work folder not empty).
# A work folder that already holds anything is refused up front: an old report is never read as the result of a new run.
# ASCII only (Vietnamese without diacritics). Windows PowerShell 5.1.
param(
    [string]$Package = '',
    [string]$Work = '',
    [string]$Python = 'C:\Users\NUC\AppData\Local\Programs\Python\Python313\python.exe'
)

function Stop-Refuse([string]$Text) {
    Write-Host ('KHONG DAT: ' + $Text) -ForegroundColor Red
    Write-Host 'Chua chay gi. Ma thoat: 2'
    exit 2
}

function Stop-Fail([string]$Text) {
    Write-Host ('KHONG DAT: ' + $Text) -ForegroundColor Red
    Write-Host 'Ma thoat: 1'
    exit 1
}

function Get-WholeSecond([datetime]$When) {
    return $When.AddTicks(-1 * ($When.Ticks % [TimeSpan]::TicksPerSecond))
}

function ConvertTo-ReportTime($Value) {
    if ($Value -is [datetime]) { return $Value }
    $parsed = [datetime]::MinValue
    $format = "yyyy-MM-dd'T'HH:mm:ss"
    if ([datetime]::TryParseExact([string]$Value, $format, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::None, [ref]$parsed)) { return $parsed }
    return $null
}

function Test-SamePath([string]$Left, [string]$Right) {
    if (-not $Left -or -not $Right) { return $false }
    return [string]::Equals($Left.Replace('/', '\').TrimEnd('\'), $Right.Replace('/', '\').TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase)
}

# The path exactly as the tools write it into their reports (Python's Path.resolve()), passed back as ASCII JSON so no console code page can alter it.
function Get-ResolvedPath([string]$Path) {
    $global:LASTEXITCODE = $null
    $text = & $Python -I -c 'import json, pathlib, sys; print(json.dumps(dict(p=str(pathlib.Path(sys.argv[1]).resolve()))))' $Path
    if ($LASTEXITCODE -ne 0) { throw ('python khong tinh duoc duong dan, ma thoat ' + $LASTEXITCODE) }
    return [string](($text | Out-String | ConvertFrom-Json).p)
}

# Does a report's path name this folder? The tools write Python's resolved path (links followed, short names expanded). The plain spelling is compared
# first; only when it differs is Python asked, so a legitimate report is not refused for its spelling and another folder is never accepted.
function Test-ReportedPath([string]$Reported, [string]$Expected) {
    if (Test-SamePath $Reported $Expected) { return $true }
    try { return (Test-SamePath $Reported (Get-ResolvedPath $Expected)) } catch { return $false }
}

function Get-Sha256Hex([string]$Path) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $stream = [System.IO.File]::OpenRead($Path)
    try { $bytes = $sha.ComputeHash($stream) }
    finally { $stream.Dispose(); $sha.Dispose() }
    return ([System.BitConverter]::ToString($bytes) -replace '-', '').ToLower()
}

# Runs one tool of the package. Its report must not exist yet. The start is taken to the whole second, because the reports carry whole seconds.
function Invoke-Tool([string]$Tool, [string[]]$ToolArgs, [string]$Report) {
    $run = @{ Exit = $null; Since = $null; Error = '' }
    if (Test-Path -LiteralPath $Report) { $run.Error = 'bao cao da co truoc khi chay: ' + $Report; return $run }
    $run.Since = Get-WholeSecond (Get-Date)
    try {
        $global:LASTEXITCODE = $null
        & $Python -I $Tool @ToolArgs | Out-Host
        $run.Exit = $LASTEXITCODE
    }
    catch { $run.Error = 'khong chay duoc: ' + $_.Exception.Message }
    return $run
}

# What every report must show: it exists, is JSON of the right kind, names this package and the manifest's version and commit, and was started
# and written by this run. Returns the parsed report (or $null) and appends one reason for each check that failed.
function Read-Report([string]$Path, [datetime]$Since, [string]$Kind, [string]$PackageDir, [string]$Version, [string]$Commit, $Reasons) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { $Reasons.Add('khong co bao cao cua lan chay nay: ' + $Path); return $null }
    try { $rep = [System.IO.File]::ReadAllText($Path, (New-Object System.Text.UTF8Encoding $false)) | ConvertFrom-Json }
    catch { $Reasons.Add('khong doc duoc bao cao ' + $Path + ': ' + $_.Exception.Message); return $null }
    if ($null -eq $rep) { $Reasons.Add('bao cao rong: ' + $Path); return $null }
    if ($rep.kind -cne $Kind) { $Reasons.Add('bao cao khong phai loai ' + $Kind + ' (kind = ' + [string]$rep.kind + ')') }
    if (-not (Test-ReportedPath ([string]$rep.package) $PackageDir)) { $Reasons.Add('bao cao ghi goi khac: ' + [string]$rep.package + ' (can ' + $PackageDir + ')') }
    $started = ConvertTo-ReportTime $rep.started
    if ($null -eq $started) { $Reasons.Add('bao cao khong co gio bat dau doc duoc (started = ' + [string]$rep.started + ')') }
    elseif ($started -lt $Since) { $Reasons.Add('bao cao bat dau luc ' + $started.ToString('s') + ', truoc khi lan chay nay bat dau (' + $Since.ToString('s') + '): bao cao cu') }
    elseif ($started -gt (Get-Date).AddMinutes(2)) { $Reasons.Add('bao cao bat dau luc ' + $started.ToString('s') + ', o tuong lai') }
    $written = (Get-Item -LiteralPath $Path).LastWriteTime
    if ($written -lt $Since) { $Reasons.Add('file bao cao duoc ghi luc ' + $written.ToString('s') + ', truoc khi lan chay nay bat dau (' + $Since.ToString('s') + '): bao cao cu') }
    if ($rep.manifest.version -cne $Version) { $Reasons.Add('bao cao ghi phien ban ' + [string]$rep.manifest.version + ' (manifest: ' + $Version + ')') }
    if ($rep.manifest.code_commit -cne $Commit) { $Reasons.Add('bao cao ghi commit ' + [string]$rep.manifest.code_commit + ' (manifest: ' + $Commit + ')') }
    return $rep
}

$problems = New-Object 'System.Collections.Generic.List[string]'
$workDir = ''
try {
    # ---- arguments, package, manifest (nothing is written yet)
    if (-not $Package) {
        if (-not $PSScriptRoot) { Stop-Refuse 'khong biet goi nam o dau: dung -Package <thu muc goi>.' }
        $Package = Split-Path -Parent $PSScriptRoot
    }
    if (-not (Test-Path -LiteralPath $Package -PathType Container)) { Stop-Refuse ('khong thay thu muc goi: ' + $Package) }
    $pkg = (Resolve-Path -LiteralPath $Package).ProviderPath.TrimEnd('\')
    $manifestPath = Join-Path $pkg 'manifest.json'
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { Stop-Refuse ('khong thay manifest.json trong ' + $pkg + ' (dung -Package <thu muc goi>).') }
    try { $manifest = [System.IO.File]::ReadAllText($manifestPath, (New-Object System.Text.UTF8Encoding $false)) | ConvertFrom-Json }
    catch { Stop-Refuse ('khong doc duoc manifest.json: ' + $_.Exception.Message) }
    $version = [string]$manifest.version
    $commit = [string]$manifest.code_commit
    $wheelName = [string]$manifest.wheel.name
    $wheelSha = ([string]$manifest.wheel.sha256).ToLower()
    if ($version -notmatch '^[0-9A-Za-z][0-9A-Za-z._+-]*$') { Stop-Refuse 'manifest.json: version thieu hoac khong hop le.' }
    if ($commit -cnotmatch '^[0-9a-f]{40}$') { Stop-Refuse 'manifest.json: code_commit thieu hoac khong phai 40 ky tu hex.' }
    if (-not $wheelName -or $wheelName -match '[\\/]') { Stop-Refuse 'manifest.json: wheel.name thieu hoac khong hop le.' }
    if ($wheelSha -cnotmatch '^[0-9a-f]{64}$') { Stop-Refuse 'manifest.json: wheel.sha256 thieu hoac khong phai 64 ky tu hex.' }
    $verifyTool = Join-Path $pkg 'verify\verify_milestone.py'
    $drillTool = Join-Path $pkg 'verify\first_task_drill.py'
    foreach ($tool in @($verifyTool, $drillTool)) {
        if (-not (Test-Path -LiteralPath $tool -PathType Leaf)) { Stop-Refuse ('goi thieu file: ' + $tool) }
    }
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { Stop-Refuse ('khong thay Python: ' + $Python + ' (dung -Python <python.exe>).') }

    # ---- work folder: new, or empty. It is never reused, so no old report can be read as this run's.
    if ($Work) { $workDir = $Work }
    else { $workDir = 'D:\OneCrewRuns\v23 thu cua anh ' + $version + ' ' + (Get-Date).ToString('yyyyMMdd-HHmmss', [Globalization.CultureInfo]::InvariantCulture) }
    if (-not [System.IO.Path]::IsPathRooted($workDir)) { $workDir = Join-Path (Get-Location).ProviderPath $workDir }
    $workDir = [System.IO.Path]::GetFullPath($workDir).TrimEnd('\')
    if (($workDir + '\').StartsWith($pkg + '\', [StringComparison]::OrdinalIgnoreCase)) { Stop-Refuse ('thu muc ket qua nam trong goi, se lam doi goi: ' + $workDir) }
    if (Test-Path -LiteralPath $workDir) {
        if (-not (Test-Path -LiteralPath $workDir -PathType Container)) { Stop-Refuse ('thu muc ket qua la mot file: ' + $workDir) }
        $existing = @(Get-ChildItem -LiteralPath $workDir -Force -ErrorAction Stop)
        if ($existing.Count -gt 0) {
            Stop-Refuse ('thu muc ket qua da co ' + $existing.Count + ' muc, khong dung lai: ' + $workDir + '. Bao cao cu khong bao gio duoc doc nhu ket qua lan chay nay; bo -Work de co thu muc moi, hoac chon thu muc trong.')
        }
    }

    Write-Host ('thu-goi: goi OneCrew ' + $version + ' (code ' + $commit.Substring(0, 12) + ')')
    Write-Host ('   goi            : ' + $pkg)
    Write-Host ('   python         : ' + $Python)
    Write-Host ('   thu muc ket qua: ' + $workDir)

    # ---- 1. the wheel: the one the manifest names, with the manifest hash, and the only onecrew-*.whl (the package README picks its wheel with that pattern)
    $wheelPath = Join-Path $pkg ('wheel\' + $wheelName)
    if (-not (Test-Path -LiteralPath $wheelPath -PathType Leaf)) { Stop-Fail ('khong thay wheel cua manifest: ' + $wheelPath) }
    $hash = Get-Sha256Hex $wheelPath
    Write-Host ('1. wheel sha256 = ' + $hash)
    if ($hash -ne $wheelSha) { Stop-Fail ('hash wheel khac manifest (manifest: ' + $wheelSha + ')') }
    $wheels = @(Get-ChildItem -LiteralPath (Join-Path $pkg 'wheel') -Filter 'onecrew-*.whl' -File -ErrorAction Stop)
    if ($wheels.Count -ne 1 -or $wheels[0].Name -cne $wheelName) { Stop-Fail ('thu muc wheel\ co ' + $wheels.Count + ' file onecrew-*.whl, can dung 1 file la ' + $wheelName) }
    # what this run depends on is what the package lists in SHA256SUMS, unchanged: the manifest, the wheel and the two tools about to run
    $sumsPath = Join-Path $pkg 'SHA256SUMS'
    if (-not (Test-Path -LiteralPath $sumsPath -PathType Leaf)) { Stop-Fail ('goi khong co SHA256SUMS: ' + $sumsPath) }
    $listed = @{}
    foreach ($line in [System.IO.File]::ReadAllLines($sumsPath, (New-Object System.Text.UTF8Encoding $false))) {
        $gap = $line.IndexOf('  ')
        if ($gap -gt 0) { $listed[$line.Substring($gap + 2).Trim()] = $line.Substring(0, $gap).Trim().ToLower() }
    }
    foreach ($relative in @('manifest.json', ('wheel/' + $wheelName), 'verify/verify_milestone.py', 'verify/first_task_drill.py')) {
        $onDisk = Join-Path $pkg ($relative -replace '/', '\')
        if (-not $listed.ContainsKey($relative)) { Stop-Fail ('SHA256SUMS khong liet ke ' + $relative) }
        if ($listed[$relative] -ne (Get-Sha256Hex $onDisk)) { Stop-Fail ('file khac SHA256SUMS: ' + $relative) }
    }
    Write-Host '   manifest, wheel va hai cong cu cua goi khop SHA256SUMS.'
    try { New-Item -ItemType Directory -Force -Path $workDir -ErrorAction Stop | Out-Null }
    catch { Stop-Refuse ('khong tao duoc thu muc ket qua ' + $workDir + ': ' + $_.Exception.Message) }

    # ---- 2. the package verifier
    Write-Host '2. Bo kiem cua goi (khoang 3-6 phut)...'
    $verifyDir = Join-Path $workDir 'verify'
    $verifyReport = Join-Path $verifyDir 'verify-report.json'
    $verifyRun = Invoke-Tool $verifyTool @($pkg, $verifyDir) $verifyReport
    $verifyReasons = New-Object 'System.Collections.Generic.List[string]'
    $verifyCount = '?'
    if ($verifyRun.Error) { $verifyReasons.Add($verifyRun.Error) }
    else {
        if ($verifyRun.Exit -ne 0) { $verifyReasons.Add('bo kiem thoat voi ma ' + [string]$verifyRun.Exit + ' (can 0)') }
        $v = Read-Report $verifyReport $verifyRun.Since 'v23-milestone-verify-report' $pkg $version $commit $verifyReasons
        if ($null -ne $v) {
            if ($v.manifest.wheel.name -cne $wheelName) { $verifyReasons.Add('bao cao ghi wheel ' + [string]$v.manifest.wheel.name + ' (manifest: ' + $wheelName + ')') }
            if (([string]$v.manifest.wheel.sha256).ToLower() -ne $wheelSha) { $verifyReasons.Add('bao cao ghi sha256 wheel ' + [string]$v.manifest.wheel.sha256 + ' (manifest: ' + $wheelSha + ')') }
            $vSteps = @()
            if ($null -ne $v.steps) { $vSteps = @($v.steps) }
            $vPassed = @($vSteps | Where-Object { $_.result -ceq 'pass' }).Count
            $vExpected = 0
            try { $vExpected = [int]$v.expected_steps } catch { $vExpected = 0 }
            $verifyCount = [string]$vPassed + '/' + [string]$vExpected
            if ($vSteps.Count -eq 0) { $verifyReasons.Add('bao cao khong co buoc nao') }
            elseif ($vSteps.Count -ne $vExpected) { $verifyReasons.Add('bao cao co ' + $vSteps.Count + ' buoc, can ' + $vExpected) }
            if ($vPassed -ne $vSteps.Count) { $verifyReasons.Add('co ' + ($vSteps.Count - $vPassed) + ' buoc khong dat trong bao cao') }
            if ($v.result -cne 'pass') { $verifyReasons.Add('bao cao ghi result = ' + [string]$v.result) }
        }
    }
    if ($verifyReasons.Count -eq 0) { Write-Host ('   ket qua: pass, buoc dat ' + $verifyCount) }
    else {
        Write-Host '   ket qua: KHONG DAT (bao cao khong duoc chap nhan):'
        foreach ($reason in $verifyReasons) { Write-Host ('   - ' + $reason); $problems.Add('bo kiem: ' + $reason) }
    }

    # ---- 3. the first task from the package README
    Write-Host '3. Task dau tien tu README cua goi (claude gia, so tam rieng; khoang 2-4 phut)...'
    $drillDir = Join-Path $workDir 'task dau tien'
    $drillReport = Join-Path $drillDir 'first-task-drill-log.json'
    $drillRun = Invoke-Tool $drillTool @($pkg, $drillDir, '--owner-step', 'auto') $drillReport
    $drillReasons = New-Object 'System.Collections.Generic.List[string]'
    $drillCount = '?'
    $ownerMode = '(khong doc duoc)'
    if ($drillRun.Error) { $drillReasons.Add($drillRun.Error) }
    else {
        if ($drillRun.Exit -ne 0) { $drillReasons.Add('task dau tien thoat voi ma ' + [string]$drillRun.Exit + ' (can 0)') }
        $d = Read-Report $drillReport $drillRun.Since 'first-task-drill-log' $pkg $version $commit $drillReasons
        if ($null -ne $d) {
            if (-not (Test-ReportedPath ([string]$d.work) $drillDir)) { $drillReasons.Add('bao cao ghi thu muc lam viec khac: ' + [string]$d.work + ' (can ' + $drillDir + ')') }
            if ($d.onecrew_version -cne $version) { $drillReasons.Add('bao cao cai onecrew ' + [string]$d.onecrew_version + ' (manifest: ' + $version + ')') }
            if ($d.package_unchanged -ne $true) { $drillReasons.Add('bao cao khong xac nhan goi nguyen ven (package_unchanged = ' + [string]$d.package_unchanged + ')') }
            $ownerMode = [string]$d.owner_step_mode
            if ($ownerMode -cne 'real' -and $ownerMode -cne 'fixture') { $drillReasons.Add('buoc duyet plan khong ro (owner_step_mode = ' + $ownerMode + ')') }
            $dSteps = @()
            if ($null -ne $d.steps) { $dSteps = @($d.steps) }
            $dRequired = @($dSteps | Where-Object { $_.kind -cne 'info' })
            $dPassed = @($dRequired | Where-Object { $_.result -ceq 'pass' }).Count
            $drillCount = [string]$dPassed + '/' + [string]$dRequired.Count
            if ($dRequired.Count -eq 0) { $drillReasons.Add('bao cao khong co buoc bat buoc nao') }
            if ($dPassed -ne $dRequired.Count) { $drillReasons.Add('co ' + ($dRequired.Count - $dPassed) + ' buoc bat buoc khong dat trong bao cao') }
            if ($d.result -cne 'pass') { $drillReasons.Add('bao cao ghi result = ' + [string]$d.result) }
        }
    }
    if ($drillReasons.Count -eq 0) {
        Write-Host ('   ket qua: pass, buoc bat buoc dat ' + $drillCount + ', buoc duyet plan: ' + $ownerMode)
        if ($ownerMode -ceq 'fixture') { Write-Host '   (fixture = buoc duyet plan duoc thay trong phien AI, khong phai ban chu chay that)' }
    }
    else {
        Write-Host ('   ket qua: KHONG DAT (bao cao khong duoc chap nhan), buoc duyet plan: ' + $ownerMode)
        foreach ($reason in $drillReasons) { Write-Host ('   - ' + $reason); $problems.Add('task dau tien: ' + $reason) }
    }

    # ---- 4. the wheel is still the verified one
    $after = Get-Sha256Hex $wheelPath
    if ($after -ne $wheelSha) { Write-Host ('4. wheel sau khi chay: KHAC manifest (' + $after + ')'); $problems.Add('wheel doi trong luc chay') }
    else { Write-Host '4. wheel sau khi chay: van dung hash cua manifest.' }

    # ---- the result: DAT only when nothing above recorded a problem
    if ($problems.Count -eq 0) {
        Write-Host ('DAT: goi ' + $version + ' qua bo kiem ' + $verifyCount + ' buoc va task dau tien tu goi ' + $drillCount + ' buoc bat buoc (buoc duyet plan: ' + $ownerMode + '). Day khong phai nghiem thu.') -ForegroundColor Green
        Write-Host ('Thu muc ket qua: ' + $workDir)
        exit 0
    }
    Write-Host ('KHONG DAT: ' + $problems.Count + ' van de (cac dong "- " o tren); bao cao nam trong thu muc ket qua.') -ForegroundColor Red
    Write-Host ('Thu muc ket qua: ' + $workDir)
    Write-Host 'Ma thoat: 1'
    exit 1
}
catch {
    Write-Host ('KHONG DAT: loi khong du kien: ' + $_.Exception.Message) -ForegroundColor Red
    if ($workDir) { Write-Host ('Thu muc ket qua: ' + $workDir) }
    Write-Host 'Ma thoat: 1'
    exit 1
}
