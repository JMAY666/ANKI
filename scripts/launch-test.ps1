param([string]$RunName = 'manual', [string]$PythonPath = '', [string]$AudioDirectory = '')
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$base = [IO.Path]::GetFullPath((Join-Path $root "runtime/$RunName"))
if (-not $base.StartsWith((Join-Path $root 'runtime') + [IO.Path]::DirectorySeparatorChar)) { throw 'Invalid run name' }
if (-not (Test-Path (Join-Path $base 'prefs21.db'))) { throw 'Run scripts/prepare.py with this run name first' }
$env:ANKI_SINGLE_INSTANCE_KEY = "synapsepro-test-$RunName"
$env:PYTHONUTF8 = '1'
if (-not $PythonPath) { $PythonPath = Join-Path $root '.venv/Scripts/python.exe' }
if (-not $AudioDirectory) { $AudioDirectory = Join-Path $root 'out/extracted/mpv' }
$launchPath = $env:PATH
try {
    if (Test-Path -LiteralPath (Join-Path $AudioDirectory 'mpv.exe')) {
        $env:PATH = [IO.Path]::GetFullPath($AudioDirectory) + [IO.Path]::PathSeparator + $launchPath
    }
    & $PythonPath -c 'import aqt; aqt.run()' -b $base -p SynapsePro-Test -l zh_CN
} finally {
    $env:PATH = $launchPath
}
