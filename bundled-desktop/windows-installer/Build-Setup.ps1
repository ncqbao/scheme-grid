[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PayloadDirectory, [Parameter(Mandatory=$true)][string]$OutputFile, [string]$EntryPoint='SchemeGrid.exe', [string]$Version='0.4.0')
$ErrorActionPreference='Stop'
$taskPayload=(Resolve-Path -LiteralPath $PayloadDirectory).Path.TrimEnd('\')
$taskOutput=[IO.Path]::GetFullPath($OutputFile)
$taskBuild=Join-Path $PSScriptRoot ('build-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $taskBuild | Out-Null
$taskFiles=@()
foreach($taskFile in (Get-ChildItem -LiteralPath $taskPayload -File -Recurse -Force)) {
    if($taskFile.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Linked files are not supported in the Windows installer.'}
    $taskRelative=$taskFile.FullName.Substring($taskPayload.Length+1).Replace('\','/')
    $taskFiles += [ordered]@{path=$taskRelative;sha256=(Get-FileHash -LiteralPath $taskFile.FullName -Algorithm SHA256).Hash.ToLowerInvariant();size=$taskFile.Length}
}
$taskManifest=[ordered]@{kind='schemegrid-desktop';version=$Version;entrypoint=$EntryPoint;files=$taskFiles}
$taskEncoding=New-Object Text.UTF8Encoding($false)
$taskManifestPath=Join-Path $taskBuild 'payload-manifest.json'
[IO.File]::WriteAllText($taskManifestPath,($taskManifest|ConvertTo-Json -Depth 5),$taskEncoding)
Add-Type -AssemblyName System.IO.Compression.FileSystem
$taskZip=Join-Path $taskBuild 'payload.zip'
[IO.Compression.ZipFile]::CreateFromDirectory($taskPayload,$taskZip,[IO.Compression.CompressionLevel]::Optimal,$false)
$taskCsc=Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if(-not(Test-Path -LiteralPath $taskCsc)){throw 'The Windows .NET Framework compiler was not found.'}
New-Item -ItemType Directory -Path (Split-Path -Parent $taskOutput) -Force | Out-Null
& $taskCsc /nologo /target:winexe /platform:anycpu /optimize+ "/out:$taskOutput" /reference:System.dll /reference:System.Core.dll /reference:System.Drawing.dll /reference:System.Windows.Forms.dll /reference:System.IO.Compression.dll /reference:System.IO.Compression.FileSystem.dll /reference:System.Web.Extensions.dll "/resource:$taskZip,payload.zip" "/resource:$taskManifestPath,payload-manifest.json" (Join-Path $PSScriptRoot 'Setup.cs')
if($LASTEXITCODE -ne 0){throw 'The installer compiler failed.'}
Write-Output ('Built '+$taskOutput)
