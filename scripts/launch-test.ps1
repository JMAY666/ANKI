param([string]$RunName = 'manual')
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$base = [IO.Path]::GetFullPath((Join-Path $root "runtime/$RunName"))
if (-not $base.StartsWith((Join-Path $root 'runtime') + [IO.Path]::DirectorySeparatorChar)) { throw 'Invalid run name' }
if (-not (Test-Path (Join-Path $base 'prefs21.db'))) { throw 'Run scripts/prepare.py with this run name first' }
$env:ANKI_SINGLE_INSTANCE_KEY = "synapsepro-test-$RunName"
$env:PYTHONUTF8 = '1'
& "$root/.venv/Scripts/python.exe" -c 'import aqt; aqt.run()' -b $base -p SynapsePro-Test -l zh_CN
