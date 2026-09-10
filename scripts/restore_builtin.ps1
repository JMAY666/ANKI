param(
    [Parameter(Mandatory)][string]$BackupPath,
    [switch]$RestoreUserData
)
$ErrorActionPreference = 'Stop'
$backup = (Resolve-Path -LiteralPath $BackupPath).Path
$record = Get-Content -LiteralPath (Join-Path $backup 'installation.json') -Raw | ConvertFrom-Json
$install = [IO.Path]::GetFullPath($record.installed)
$previous = [IO.Path]::GetFullPath($record.previous)
$data = [IO.Path]::GetFullPath($record.data)
if (Get-Process -Name Anki -ErrorAction SilentlyContinue) { throw 'Close Anki before recovery' }
if ((Split-Path -Parent $previous) -ne (Split-Path -Parent $install) -or -not (Test-Path -LiteralPath (Join-Path $previous 'Anki.exe'))) { throw 'Invalid original installation path' }
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$retained = [IO.Path]::GetFullPath($install + '.before-restore-' + $stamp)
$staged = [IO.Path]::GetFullPath($install + '.restore-staged-' + $stamp)
if ((Split-Path -Parent $retained) -ne (Split-Path -Parent $install) -or (Split-Path -Parent $staged) -ne (Split-Path -Parent $install) -or (Test-Path -LiteralPath $retained) -or (Test-Path -LiteralPath $staged)) { throw 'Invalid recovery destination' }
Copy-Item -LiteralPath $previous -Destination $staged -Recurse
if ((Get-FileHash -LiteralPath (Join-Path $previous 'Anki.exe')).Hash -ne (Get-FileHash -LiteralPath (Join-Path $staged 'Anki.exe')).Hash) { throw 'Original application copy failed' }
Move-Item -LiteralPath $install -Destination $retained
try { Move-Item -LiteralPath $staged -Destination $install }
catch { if (-not (Test-Path -LiteralPath $install)) { Move-Item -LiteralPath $retained -Destination $install }; throw }
if ($RestoreUserData) {
    if ($data -eq [IO.Path]::GetPathRoot($data) -or -not (Test-Path -LiteralPath (Join-Path $backup 'Anki2/prefs21.db'))) { throw 'Invalid user data backup' }
    $retainedData = [IO.Path]::GetFullPath($data + '.before-restore-' + $stamp)
    $stagedData = [IO.Path]::GetFullPath($data + '.restore-staged-' + $stamp)
    if ((Split-Path -Parent $retainedData) -ne (Split-Path -Parent $data) -or (Split-Path -Parent $stagedData) -ne (Split-Path -Parent $data) -or (Test-Path -LiteralPath $retainedData) -or (Test-Path -LiteralPath $stagedData)) { throw 'Invalid user data recovery destination' }
    Copy-Item -LiteralPath (Join-Path $backup 'Anki2') -Destination $stagedData -Recurse
    Move-Item -LiteralPath $data -Destination $retainedData
    try { Move-Item -LiteralPath $stagedData -Destination $data }
    catch { Move-Item -LiteralPath $retainedData -Destination $data; throw }
} else {
    foreach ($name in $record.disabled) {
        $addonTarget = Join-Path $data ('addons21/' + $name)
        if (-not (Test-Path -LiteralPath $addonTarget)) {
            $addonBackup = Join-Path $backup ('retired-installed-addons/' + $name)
            if (-not (Test-Path -LiteralPath $addonBackup)) {
                $addonBackup = Join-Path $backup ('Anki2/addons21/' + $name)
            }
            if (Test-Path -LiteralPath $addonBackup) {
                Copy-Item -LiteralPath $addonBackup -Destination $addonTarget -Recurse
            }
        }
        $meta = Join-Path $backup ('disabled-addon-metadata/' + $name + '.json')
        if (Test-Path -LiteralPath $meta) {
            Copy-Item -LiteralPath $meta -Destination (Join-Path $data ('addons21/' + $name + '/meta.json')) -Force
        }
    }
}
Write-Output "Original program restored. Integrated program preserved at $retained"
