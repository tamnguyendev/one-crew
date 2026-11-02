# roi-lab.ps1 - DOT-SOURCE de cua so nay ROI moi truong thu: tra LOCALAPPDATA, APPDATA, TEMP, TMP ve gia tri that ma chuan-bi/vao-moi-truong da nho,
# xoa $exe $proj $state $lab $venv, $labOk = $false. Sau do co the chay don-dep.ps1 ngay trong cua so nay. Khong xoa gi tren dia.
#   . "D:\OneCrewRuns\v24\pkg\thu-tay-dev5\roi-lab.ps1"
if (-not $env:ONECREW_LAB_REAL_LOCALAPPDATA) {
    Write-Host 'cua so nay chua vao moi truong thu (khong co gi de tra lai).'
} else {
    $env:LOCALAPPDATA = $env:ONECREW_LAB_REAL_LOCALAPPDATA; $env:APPDATA = $env:ONECREW_LAB_REAL_APPDATA
    $env:TEMP = $env:ONECREW_LAB_REAL_TEMP; $env:TMP = $env:ONECREW_LAB_REAL_TMP
    Remove-Item Env:ONECREW_LAB_REAL_LOCALAPPDATA, Env:ONECREW_LAB_REAL_APPDATA, Env:ONECREW_LAB_REAL_TEMP, Env:ONECREW_LAB_REAL_TMP -ErrorAction SilentlyContinue
    Remove-Variable -Name exe, proj, state, lab, venv, registryThu, registryThat -ErrorAction SilentlyContinue
    $labOk = $false
    Write-Host "DAT: da roi moi truong thu. LOCALAPPDATA=$env:LOCALAPPDATA (that). Co the chay don-dep.ps1 trong cua so nay."
}
