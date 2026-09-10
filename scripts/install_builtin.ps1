param(
    [Parameter(Mandatory)][string]$ImagePath,
    [Parameter(Mandatory)][string]$InstallPath,
    [Parameter(Mandatory)][string]$BackupPath,
    [string]$DataPath = (Join-Path $env:APPDATA 'Anki2')
)
$ErrorActionPreference = 'Stop'
$image = (Resolve-Path -LiteralPath $ImagePath).Path
$install = (Resolve-Path -LiteralPath $InstallPath).Path
$backup = (Resolve-Path -LiteralPath $BackupPath).Path
$data = (Resolve-Path -LiteralPath $DataPath).Path
if (-not (Test-Path -LiteralPath (Join-Path $image 'INTEGRATED-BUILD.json'))) { throw 'Not an integrated application image' }
if (-not (Test-Path -LiteralPath (Join-Path $backup 'sha256-manifest.json'))) { throw 'A verified full backup is required' }
if (-not (Test-Path -LiteralPath (Join-Path $install 'Anki.exe'))) { throw 'Not the current Anki installation' }
if (Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'Anki.exe' -and $_.ExecutablePath -eq (Join-Path $install 'Anki.exe') }) { throw 'Close the installed Anki before replacement' }
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$previous = [IO.Path]::GetFullPath($install + '.pre-builtin-' + $stamp)
$staged = [IO.Path]::GetFullPath($install + '.staged-' + $stamp)
$parent = Split-Path -Parent $install
if ((Split-Path -Parent $previous) -ne $parent -or (Split-Path -Parent $staged) -ne $parent -or $install -eq [IO.Path]::GetPathRoot($install)) { throw 'Invalid replacement paths' }
if ((Test-Path -LiteralPath $previous) -or (Test-Path -LiteralPath $staged)) { throw 'Replacement destination already exists' }
Copy-Item -LiteralPath $image -Destination $staged -Recurse
# Check the staged application bytes before touching the installed version.
foreach ($file in Get-ChildItem -LiteralPath $image -File -Recurse) {
    $relative = [IO.Path]::GetRelativePath($image, $file.FullName)
    if ((Get-FileHash -LiteralPath $file.FullName).Hash -ne (Get-FileHash -LiteralPath (Join-Path $staged $relative)).Hash) { throw "Staging mismatch: $relative" }
}
Move-Item -LiteralPath $install -Destination $previous
try {
    Move-Item -LiteralPath $staged -Destination $install
} catch {
    Move-Item -LiteralPath $previous -Destination $install
    throw
}
$disabled = @()
$metaBackup = Join-Path $backup 'disabled-addon-metadata'
New-Item -ItemType Directory -Path $metaBackup -Force | Out-Null
foreach ($folder in Get-ChildItem -LiteralPath (Join-Path $data 'addons21') -Directory) {
    $replaced = $folder.Name -in @('236979321', 'SynapsePro1', '759844606')
    $manifestPath = Join-Path $folder.FullName 'manifest.json'
    if (-not $replaced -and (Test-Path -LiteralPath $manifestPath)) {
        $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        $replaced = $manifest.package -in @('236979321', 'SynapsePro1', '759844606')
    }
    if (-not $replaced) { continue }
    $metaPath = Join-Path $folder.FullName 'meta.json'
    $meta = @{}
    if (Test-Path -LiteralPath $metaPath) {
        Copy-Item -LiteralPath $metaPath -Destination (Join-Path $metaBackup ($folder.Name + '.json'))
        $meta = Get-Content -LiteralPath $metaPath -Raw | ConvertFrom-Json -AsHashtable
    }
    $meta['disabled'] = $true
    $temporary = $metaPath + '.builtin-tmp'
    $meta | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $temporary -Encoding utf8NoBOM
    Move-Item -LiteralPath $temporary -Destination $metaPath -Force
    $disabled += $folder.Name
}
$record = @{ installed = $install; previous = $previous; backup = $backup; data = $data; disabled = $disabled; timestamp = $stamp }
$record | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $backup 'installation.json') -Encoding utf8NoBOM
$record | ConvertTo-Json -Depth 5
