# vao-moi-truong.ps1 - dot-source trong MOT cua so PowerShell de vao moi truong thu cach ly cua OneCrew 2.4.0.dev5:
#   . "D:\OneCrewRuns\v24\pkg\thu-tay-dev5\vao-moi-truong.ps1" [-Lab "D:\OneCrewRuns\v24 thu tay dev5"]
# Chi doi bien cua CUA SO nay (process): LOCALAPPDATA, APPDATA, TEMP, TMP tro vao <lab>\env, nen `onecrew init` va moi lenh thu ghi registry hook,
# cache, file tam vao <lab>, khong vao registry/that cua tai khoan. Khong doi bien cap User/Machine. Mo cua so moi thi dot-source lai.
# Dat san: $py $pkg $lab $venv $proj $state $exe $registryThu $registryThat (chi doc). Khong ghi gi.
param([string]$Lab = 'D:\OneCrewRuns\v24 thu tay dev5')
$script:ok = $true
$py  = 'C:\Users\NUC\AppData\Local\Programs\Python\Python313\python.exe'
$pkg = 'D:\OneCrewRuns\v24\pkg\onecrew-2.4.0.dev5-beta'
$lab = [System.IO.Path]::GetFullPath($Lab).TrimEnd('\')
if (($lab + '\').StartsWith($pkg + '\', [StringComparison]::OrdinalIgnoreCase)) { Write-Host "KHONG DAT: lab nam trong goi: $lab" -ForegroundColor Red; $script:ok = $false }
$venv = "$lab\venv"; $proj = "$lab\project"; $state = "$lab\so"; $exe = "$venv\Scripts\onecrew.exe"
if (-not $env:ONECREW_LAB_REAL_LOCALAPPDATA) { $env:ONECREW_LAB_REAL_LOCALAPPDATA = $env:LOCALAPPDATA }   # ghi nho registry that de DOI CHIEU (chi doc)
$registryThat = Join-Path $env:ONECREW_LAB_REAL_LOCALAPPDATA 'OneCrew\hook-projects.json'
$env:LOCALAPPDATA = "$lab\env\LocalAppData"; $env:APPDATA = "$lab\env\AppData"; $env:TEMP = "$lab\env\Temp"; $env:TMP = "$lab\env\Temp"
foreach ($d in @($env:LOCALAPPDATA, $env:APPDATA, $env:TEMP)) { if (-not (Test-Path -LiteralPath $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null } }
$registryThu = "$env:LOCALAPPDATA\OneCrew\hook-projects.json"
Remove-Item Env:CLAUDECODE, Env:CLAUDE_CODE_CHILD_SESSION, Env:PYTHONPATH -ErrorAction SilentlyContinue
Write-Host "moi truong thu (cua so nay): lab=$lab"
Write-Host "   LOCALAPPDATA=$env:LOCALAPPDATA"
Write-Host "   registry thu = $registryThu"
Write-Host "   registry that (chi doc, doi chieu) = $registryThat"
Write-Host "   exe = $exe" -NoNewline
if (Test-Path -LiteralPath $exe) { Write-Host ("  (" + (& $exe --version 2>&1) + ")") } else { Write-Host '  (chua cai: chay chuan-bi.ps1)' }
