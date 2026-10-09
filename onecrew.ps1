$onecrewPython = $env:ONECREW_PYTHON
if (-not $onecrewPython) {
    $onecrewLocalPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $onecrewLocalPython) {
        $onecrewPython = $onecrewLocalPython
    } else {
        $onecrewPythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
        if ($onecrewPythonCommand) { $onecrewPython = $onecrewPythonCommand.Source }
    }
}
if (-not $onecrewPython) {
    Write-Error 'Python 3.10+ required. Set ONECREW_PYTHON to its executable path.'
    exit 2
}
& $onecrewPython -X utf8 (Join-Path $PSScriptRoot 'onecrew_cli.py') @args
exit $LASTEXITCODE
