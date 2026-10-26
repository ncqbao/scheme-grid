[CmdletBinding()]
param(
    [string]$DownloadDirectory,
    [string]$OutputDirectory,
    [switch]$ValidateOnly
)
$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'Build the Windows installer on Windows.'
}
$taskRepository = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$taskBase = Join-Path $taskRepository 'bundled-desktop'
if (-not $DownloadDirectory) { $DownloadDirectory = Join-Path $taskBase 'downloads' }
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $taskRepository 'dist' }
$taskDownloads = [IO.Path]::GetFullPath($DownloadDirectory)
$taskOutput = [IO.Path]::GetFullPath($OutputDirectory)
$taskAppNames = @('package.json','main.cjs','preload.cjs','index.html','desktop.css','renderer.js','worker.html','layout-runner.js','reaction-layout.js','scheme-grid.js')
$taskBridgeNames = @('native_bridge.py','preservation.py')
foreach ($taskName in $taskAppNames) {
    if (-not (Test-Path -LiteralPath (Join-Path $taskBase ('app\' + $taskName)) -PathType Leaf)) { throw ('Missing application source: ' + $taskName) }
}
foreach ($taskName in $taskBridgeNames) {
    if (-not (Test-Path -LiteralPath (Join-Path $taskBase ('windows-bridge\' + $taskName)) -PathType Leaf)) { throw ('Missing bridge source: ' + $taskName) }
}
$taskRuntimes = @(
    @{Name='electron-v45.0.0-win32-x64.zip';Url='https://github.com/electron/electron/releases/download/v45.0.0/electron-v45.0.0-win32-x64.zip';Hash='ae53887a23bb640369c93dbd38c408a2af5c0deb86f2fa76c6c244cb444b7f47'},
    @{Name='python-3.14.10-embed-amd64.zip';Url='https://www.python.org/ftp/python/3.14.10/python-3.14.10-embed-amd64.zip';Hash='90905e64a840557d8c1bc4f5b74db3d7ee85e3ffb217611cac1c7813acea4159'}
)
foreach ($taskRuntime in $taskRuntimes) {
    $taskArchive = Join-Path $taskDownloads $taskRuntime.Name
    if (-not (Test-Path -LiteralPath $taskArchive -PathType Leaf)) {
        if ($ValidateOnly) { throw ('Missing cached runtime: ' + $taskRuntime.Name + '. Run a normal build to download it.') }
        New-Item -ItemType Directory -Path $taskDownloads -Force | Out-Null
        Write-Host ('Downloading official runtime: ' + $taskRuntime.Name)
        Invoke-WebRequest -Uri $taskRuntime.Url -OutFile $taskArchive -UseBasicParsing
    }
    if ((Get-FileHash -LiteralPath $taskArchive -Algorithm SHA256).Hash -ne $taskRuntime.Hash) {
        throw ('Runtime checksum mismatch: ' + $taskRuntime.Name + '. Keep this file out of a release.')
    }
}
$taskCsc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $taskCsc -PathType Leaf)) { throw 'The .NET Framework compiler was not found.' }
if ($ValidateOnly) {
    Write-Host 'Source files, cached official runtime hashes and compiler path passed. No build files were written.'
    return
}
$taskStage = Join-Path $taskBase ('build\windows-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $taskStage -Force | Out-Null
Expand-Archive -LiteralPath (Join-Path $taskDownloads 'electron-v45.0.0-win32-x64.zip') -DestinationPath $taskStage
Rename-Item -LiteralPath (Join-Path $taskStage 'electron.exe') -NewName 'SchemeGrid.exe'
$taskAppDestination = Join-Path $taskStage 'resources\app'
$taskPythonDestination = Join-Path $taskStage 'resources\python'
$taskBridgeDestination = Join-Path $taskStage 'resources\windows-bridge'
New-Item -ItemType Directory -Path $taskAppDestination,$taskPythonDestination,$taskBridgeDestination -Force | Out-Null
foreach ($taskName in $taskAppNames) {
    Copy-Item -LiteralPath (Join-Path $taskBase ('app\' + $taskName)) -Destination (Join-Path $taskAppDestination $taskName)
}
foreach ($taskName in $taskBridgeNames) {
    Copy-Item -LiteralPath (Join-Path $taskBase ('windows-bridge\' + $taskName)) -Destination (Join-Path $taskBridgeDestination $taskName)
}
Expand-Archive -LiteralPath (Join-Path $taskDownloads 'python-3.14.10-embed-amd64.zip') -DestinationPath $taskPythonDestination
New-Item -ItemType Directory -Path $taskOutput -Force | Out-Null
& (Join-Path $taskBase 'windows-installer\Build-Setup.ps1') -PayloadDirectory $taskStage -OutputFile (Join-Path $taskOutput 'SchemeGrid-Windows-Setup.exe') -EntryPoint 'SchemeGrid.exe' -Version '0.4.0'
Write-Host 'Build complete. The installer was not installed or launched.'
