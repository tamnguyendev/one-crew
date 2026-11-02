# don-dep.ps1 - ket thuc bai thu: xoa CA thu muc lab (venv, ban sao project, so thu, env voi registry thu). Khong dung den registry that,
# project that, venv that. Chay: powershell -ExecutionPolicy Bypass -File "D:\OneCrewRuns\v24\pkg\thu-tay-dev5\don-dep.ps1" [-Lab <lab>]
param([string]$Lab = 'D:\OneCrewRuns\v24 thu tay dev5')
$ErrorActionPreference = 'Stop'
$pkg = 'D:\OneCrewRuns\v24\pkg\onecrew-2.4.0.dev5-beta'
$labFull = [System.IO.Path]::GetFullPath($Lab).TrimEnd('\')
if (($labFull + '\').StartsWith($pkg + '\', [StringComparison]::OrdinalIgnoreCase)) { Write-Host "KHONG DAT: lab nam trong goi" -ForegroundColor Red; exit 2 }
if (-not (Test-Path -LiteralPath "$labFull\env\LocalAppData")) { Write-Host "KHONG DAT: $labFull khong phai lab cua chuan-bi.ps1 (thieu env\LocalAppData); khong xoa" -ForegroundColor Red; exit 2 }
$real = if ($env:ONECREW_LAB_REAL_LOCALAPPDATA) { $env:ONECREW_LAB_REAL_LOCALAPPDATA } else { $env:LOCALAPPDATA }
$registryThat = Join-Path $real 'OneCrew\hook-projects.json'
$truoc = if (Test-Path -LiteralPath $registryThat) { (Get-FileHash -LiteralPath $registryThat -Algorithm SHA256).Hash } else { 'absent' }
Remove-Item -LiteralPath $labFull -Recurse -Force
$sau = if (Test-Path -LiteralPath $registryThat) { (Get-FileHash -LiteralPath $registryThat -Algorithm SHA256).Hash } else { 'absent' }
if ($sau -ne $truoc) { Write-Host "KHONG DAT: registry that doi trong luc don dep" -ForegroundColor Red; exit 1 }
Write-Host "DAT: da xoa $labFull; registry that $registryThat khong doi ($truoc)."
