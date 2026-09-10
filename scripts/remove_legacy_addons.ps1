param(
    [Parameter(Mandatory)][string]$DataPath,
    [Parameter(Mandatory)][string]$BackupPath
)
$ErrorActionPreference = 'Stop'
$data = (Resolve-Path -LiteralPath $DataPath).Path
$backup = (Resolve-Path -LiteralPath $BackupPath).Path
if (-not (Test-Path -LiteralPath (Join-Path $backup 'installation.json'))) { throw 'Complete and verify installation before removing old add-ons' }
$addons = [IO.Path]::GetFullPath((Join-Path $data 'addons21'))
$archive = [IO.Path]::GetFullPath((Join-Path $backup 'retired-installed-addons'))
New-Item -ItemType Directory -Path $archive -Force | Out-Null
foreach ($name in @('236979321', '759844606')) {
    $source = [IO.Path]::GetFullPath((Join-Path $addons $name))
    $destination = [IO.Path]::GetFullPath((Join-Path $archive $name))
    if (-not $source.StartsWith($addons + '\') -or -not $destination.StartsWith($archive + '\')) { throw 'Invalid legacy add-on paths' }
    if (-not (Test-Path -LiteralPath $source)) { continue }
    if (Test-Path -LiteralPath $destination) { throw 'Recovery copy already exists; refusing to overwrite it' }
    Copy-Item -LiteralPath $source -Destination $destination -Recurse
    foreach ($file in Get-ChildItem -LiteralPath $source -File -Recurse) {
        $relative = [IO.Path]::GetRelativePath($source, $file.FullName)
        if ((Get-FileHash -LiteralPath $file.FullName).Hash -ne (Get-FileHash -LiteralPath (Join-Path $destination $relative)).Hash) { throw "Legacy backup mismatch: $name/$relative" }
    }
    Remove-Item -LiteralPath $source -Recurse -Force
    Write-Output "Removed active add-on $name; verified recovery copy preserved"
}
