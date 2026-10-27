[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PayloadDirectory,[Parameter(Mandatory=$true)][string]$OutputFile,[string]$Version='0.5.0-native-preview.7',[switch]$Fixture,[string]$PythonHostSource)
$ErrorActionPreference='Stop'
$sgPayload=(Resolve-Path -LiteralPath $PayloadDirectory).Path.TrimEnd('\')
$sgOutput=[IO.Path]::GetFullPath($OutputFile)
$sgBuild=Join-Path $PSScriptRoot ('build-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $sgBuild | Out-Null
$sgFiles=@()
foreach($sgFile in (Get-ChildItem -LiteralPath $sgPayload -File -Recurse -Force)) {
    if($sgFile.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Linked files are not supported.'}
    $sgRelative=$sgFile.FullName.Substring($sgPayload.Length+1).Replace('\','/')
    $sgFiles += [ordered]@{path=$sgRelative;sha256=(Get-FileHash -LiteralPath $sgFile.FullName -Algorithm SHA256).Hash.ToLowerInvariant();size=$sgFile.Length}
}
foreach($sgDirectory in (Get-ChildItem -LiteralPath $sgPayload -Directory -Recurse -Force)){if($sgDirectory.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Linked directories are not supported.'}}
if(-not(Test-Path -LiteralPath (Join-Path $sgPayload 'install-contract.json') -PathType Leaf)){throw 'Payload needs install-contract.json.'}
$sgManifest=[ordered]@{kind='schemegrid-native';version=$Version;testOnly=[bool]$Fixture;files=$sgFiles}
$sgEncoding=New-Object Text.UTF8Encoding($false)
$sgManifestPath=Join-Path $sgBuild 'payload-manifest.json'
[IO.File]::WriteAllText($sgManifestPath,($sgManifest|ConvertTo-Json -Depth 8),$sgEncoding)
Add-Type -AssemblyName System.IO.Compression.FileSystem
$sgZip=Join-Path $sgBuild 'payload.zip'
[IO.Compression.ZipFile]::CreateFromDirectory($sgPayload,$sgZip,[IO.Compression.CompressionLevel]::Optimal,$false)
$sgCsc=Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if(-not(Test-Path -LiteralPath $sgCsc)){throw 'Windows .NET Framework compiler was not found.'}
New-Item -ItemType Directory -Path (Split-Path -Parent $sgOutput) -Force | Out-Null
$sgSources=@((Join-Path $PSScriptRoot 'Setup.cs'))
if($PythonHostSource){$sgSources+=(Resolve-Path -LiteralPath $PythonHostSource).Path}
$sgNotices=@()
if(Test-Path -LiteralPath (Join-Path $sgPayload 'INSTALLER-NOTICES.txt') -PathType Leaf){$sgNotices=@('/resource:'+(Join-Path $sgPayload 'INSTALLER-NOTICES.txt')+',installer-notices.txt')}
& $sgCsc /nologo /target:winexe /platform:anycpu /optimize+ "/out:$sgOutput" "/win32manifest:$(Join-Path $PSScriptRoot 'Setup.exe.manifest')" /reference:System.dll /reference:System.Core.dll /reference:System.Drawing.dll /reference:System.Windows.Forms.dll /reference:System.IO.Compression.dll /reference:System.IO.Compression.FileSystem.dll /reference:System.Web.Extensions.dll "/resource:$sgZip,payload.zip" "/resource:$sgManifestPath,payload-manifest.json" @sgNotices @sgSources
if($LASTEXITCODE -ne 0){throw 'Installer compiler failed.'}
[pscustomobject]@{Output=$sgOutput;Version=$Version;Fixture=[bool]$Fixture;Files=$sgFiles.Count;Bytes=(Get-Item -LiteralPath $sgOutput).Length;SHA256=(Get-FileHash -LiteralPath $sgOutput -Algorithm SHA256).Hash.ToLowerInvariant();BuildDirectory=$sgBuild}|ConvertTo-Json -Compress
