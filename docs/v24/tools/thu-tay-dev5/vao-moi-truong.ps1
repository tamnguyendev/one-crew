# vao-moi-truong.ps1 - DOT-SOURCE trong cua so PowerShell se go cac lenh thu (khong chay bang `powershell -File`: tien trinh con ket thuc thi cua so
# cua ban khong nhan duoc gi):
#   . "D:\OneCrewRuns\v24\pkg\thu-tay-dev5\vao-moi-truong.ps1" [-Lab "D:\OneCrewRuns\v24 thu tay dev5"]
# Chi vao lab ma chuan-bi.ps1 da tao (co dau <lab>\.lab-thu-dev5.json va muc tuong ung trong labs.json canh script); thu muc khac bi tu choi va
# KHONG bien thanh lab. Doi bien cua CUA SO nay: LOCALAPPDATA, APPDATA, TEMP, TMP -> <lab>\env (khong doi bien cap User/Machine; khong dung den
# CLAUDECODE, CLAUDE_CODE_CHILD_SESSION hay bien nao khac: dau hieu phien AI va guard owner cua OneCrew giu nguyen). Dat: $py $pkg $lab $venv $proj
# $state $exe $registryThu $registryThat $labOk. Khong `exit` (khong dong cua so cua ban): that bai -> in KHONG DAT, $labOk = $false, cac bien bi xoa.
param([string]$Lab = 'D:\OneCrewRuns\v24 thu tay dev5')
$labOk = $false
$py  = 'C:\Users\NUC\AppData\Local\Programs\Python\Python313\python.exe'
$pkg = 'D:\OneCrewRuns\v24\pkg\onecrew-2.4.0.dev5-beta'
$labsFile = Join-Path $PSScriptRoot 'labs.json'
function Script:Lab-Refuse([string]$t) { Write-Host ('KHONG DAT: ' + $t) -ForegroundColor Red; Write-Host 'Khong vao moi truong thu; khong go lenh thu trong cua so nay.' }
function Script:Lab-Record([string]$path) {
    # the marker inside the lab AND the entry in labs.json must agree on the absolute path and the nonce; made only by chuan-bi.ps1
    $marker = Join-Path $path '.lab-thu-dev5.json'
    if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) { return $null }
    try { $m = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json } catch { return $null }
    if (-not $m.lab -or -not $m.nonce -or $m.created_by -ne 'chuan-bi.ps1') { return $null }
    if ($m.lab.TrimEnd('\').ToLowerInvariant() -ne $path.ToLowerInvariant()) { return $null }
    if (-not (Test-Path -LiteralPath $labsFile -PathType Leaf)) { return $null }
    try { $all = @(Get-Content -LiteralPath $labsFile -Raw | ConvertFrom-Json) } catch { return $null }
    $hit = @($all | Where-Object { $_.lab -and $_.lab.TrimEnd('\').ToLowerInvariant() -eq $path.ToLowerInvariant() -and $_.nonce -eq $m.nonce })
    if ($hit.Count -ne 1) { return $null }
    return $m
}
function Script:Lab-NoLinks([string]$path) {
    # no reparse point (junction/symlink) on the lab or any ancestor: the path must be the folder itself
    $cur = $path
    while ($cur -and $cur -ne [System.IO.Path]::GetPathRoot($cur)) {
        if (Test-Path -LiteralPath $cur) {
            $item = Get-Item -LiteralPath $cur -Force
            if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { return $false }
        }
        $cur = Split-Path -Parent $cur
    }
    return $true
}
$lab = [System.IO.Path]::GetFullPath($Lab).TrimEnd('\')
$venv = "$lab\venv"; $proj = "$lab\project"; $state = "$lab\so"; $exe = "$venv\Scripts\onecrew.exe"
if (-not $env:ONECREW_LAB_REAL_LOCALAPPDATA) { $env:ONECREW_LAB_REAL_LOCALAPPDATA = $env:LOCALAPPDATA }   # registry that, chi de doi chieu (doc)
$registryThat = Join-Path $env:ONECREW_LAB_REAL_LOCALAPPDATA 'OneCrew\hook-projects.json'
$registryThu = "$lab\env\LocalAppData\OneCrew\hook-projects.json"
$why = $null
if (($lab + '\').StartsWith($pkg + '\', [StringComparison]::OrdinalIgnoreCase)) { $why = "lab nam trong goi: $lab" }
elseif (-not (Test-Path -LiteralPath $lab -PathType Container)) { $why = "lab chua co: $lab (chay chuan-bi.ps1 truoc)" }
elseif (-not (Lab-NoLinks $lab)) { $why = "duong dan lab di qua link/junction: $lab" }
elseif (-not (Lab-Record $lab)) { $why = "$lab khong phai lab do chuan-bi.ps1 tao (thieu .lab-thu-dev5.json hop le hoac muc trong labs.json)" }
elseif (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { $why = "lab thieu $exe" }
elseif (-not (Test-Path -LiteralPath "$proj\.onecrew\config.json" -PathType Leaf)) { $why = "lab thieu $proj\.onecrew\config.json" }
elseif (-not (Test-Path -LiteralPath "$state\ledger.sqlite3" -PathType Leaf)) { $why = "lab thieu $state\ledger.sqlite3" }
elseif (-not (Test-Path -LiteralPath $registryThu -PathType Leaf)) { $why = "lab thieu registry thu $registryThu" }
if ($why) {
    Lab-Refuse $why
    Remove-Variable -Name exe, proj, state, venv, lab, registryThu -ErrorAction SilentlyContinue
} else {
    $env:LOCALAPPDATA = "$lab\env\LocalAppData"; $env:APPDATA = "$lab\env\AppData"; $env:TEMP = "$lab\env\Temp"; $env:TMP = "$lab\env\Temp"
    foreach ($d in @($env:APPDATA, $env:TEMP)) { if (-not (Test-Path -LiteralPath $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null } }
    $ver = (& $exe --version 2>&1)
    if ($LASTEXITCODE -ne 0 -or "$ver" -notmatch '2\.4\.0\.dev5') {
        Lab-Refuse "onecrew cua lab khong chay: $ver"
        Remove-Variable -Name exe, proj, state, venv, lab, registryThu -ErrorAction SilentlyContinue
    } else {
        $labOk = $true
        Write-Host "DAT: dang o moi truong thu (cua so nay): lab=$lab, $ver"
        Write-Host "   LOCALAPPDATA=$env:LOCALAPPDATA"
        Write-Host "   exe=$exe"
        Write-Host "   project=$proj  state=$state"
        Write-Host "   registry thu=$registryThu"
        Write-Host "   registry that (chi doc, doi chieu)=$registryThat"
    }
}
