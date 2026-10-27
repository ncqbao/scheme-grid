[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$sgTests=Join-Path $PSScriptRoot ('t'+[guid]::NewGuid().ToString('N').Substring(0,8))
New-Item -ItemType Directory -Path $sgTests|Out-Null
$sgEncoding=New-Object Text.UTF8Encoding($false)
$sgChecks=@()
function Check-SG([string]$Name,[bool]$Condition){if(-not$Condition){throw ('FAILED: '+$Name)};$script:sgChecks += [ordered]@{name=$Name;passed=$true}}
function Write-SG([string]$Path,[string]$Text){[IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($Path))|Out-Null;[IO.File]::WriteAllText($Path,$Text,$sgEncoding)}
function Json-SG([string]$Path,$Value){Write-SG $Path ($Value|ConvertTo-Json -Depth 12)}
$sgCsc=Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$sgHelperSource=Join-Path $sgTests 'Helper.cs'
Write-SG $sgHelperSource @'
using System.Reflection;
[assembly:AssemblyFileVersion("26.1.0.6327")]
public class Helper { public static int Main(string[] args) { if(args.Length>0 && args[0]=="fail") return 17; return 0; } }
'@
$sgHelper=Join-Path $sgTests 'Helper.exe'
& $sgCsc /nologo /target:exe "/out:$sgHelper" $sgHelperSource
if($LASTEXITCODE -ne 0){throw 'Fixture helper compilation failed.'}
$sgPayload=Join-Path $sgTests 'payload'
Write-SG (Join-Path $sgPayload 'core\native-runtime.json') '{"mode":"prepare","runDirectory":"placeholder"}'
Write-SG (Join-Path $sgPayload 'installer\native-runtime.template.json') '{"mode":"prepare","runDirectory":__DATA_DIR_JSON__,"installation":__INSTALL_DIR_JSON__}'
foreach($sgCommand in @('Arrange','Restore')){
    Write-SG (Join-Path $sgPayload ('host\'+$sgCommand+'.py.template')) ("# SchemeGridNative managed shim v2`n# command: "+$sgCommand+"`ninstallation = __INSTALL_DIR_JSON__`n")
}
New-Item -ItemType Directory -Path (Join-Path $sgPayload 'runtime') -Force|Out-Null
Copy-Item -LiteralPath $sgHelper -Destination (Join-Path $sgPayload 'runtime\Helper.exe')
$sgCommands=@(@{command='Arrange';fileName='Scheme Grid - Arrange Selection in Place.py';source='host/Arrange.py.template';template=$true},@{command='Restore';fileName='Scheme Grid - Restore Last Arrangement.py';source='host/Restore.py.template';template=$true})
$sgLegacyName='Scheme Grid - Snap Scheme.py'
$sgContract=[ordered]@{schema=1;runtimeConfigFile='core/native-runtime.json';runtimeTemplateFile='installer/native-runtime.template.json';commands=$sgCommands;retireLegacy=@(@{command='Arrange';fileName=$sgLegacyName});selfChecks=@(@{executable='runtime/Helper.exe';arguments=@();timeoutSeconds=5});pythonInstallers=@()}
Json-SG (Join-Path $sgPayload 'install-contract.json') $sgContract
$sgSetup1=Join-Path $sgTests 'Setup1.exe';$sgSetup2=Join-Path $sgTests 'Setup2.exe';$sgProduction=Join-Path $sgTests 'Production.exe'
& (Join-Path $PSScriptRoot 'Build-Setup.ps1') -PayloadDirectory $sgPayload -OutputFile $sgSetup1 -Version '0.5.0-test.1' -Fixture|Out-Null
& (Join-Path $PSScriptRoot 'Build-Setup.ps1') -PayloadDirectory $sgPayload -OutputFile $sgSetup2 -Version '0.5.0-test.2' -Fixture|Out-Null
& (Join-Path $PSScriptRoot 'Build-Setup.ps1') -PayloadDirectory $sgPayload -OutputFile $sgProduction -Version '0.5.0-test.1'|Out-Null
function Invoke-SG([string]$Exe,[string[]]$Arguments){
    $sgReport=Join-Path $sgTests ('report-'+[guid]::NewGuid().ToString('N')+'.json')
    $sgArgs=@($Arguments)+@('--report',$sgReport)
    $sgQuoted=@($sgArgs|ForEach-Object {'"'+$_.Replace('"','\"')+'"'})
    $sgProcess=Start-Process -FilePath $Exe -ArgumentList $sgQuoted -WindowStyle Hidden -PassThru -Wait
    if(-not(Test-Path -LiteralPath $sgReport)){throw 'Fixture installer did not write its report.'}
    $sgValue=Get-Content -LiteralPath $sgReport -Raw|ConvertFrom-Json
    return [pscustomobject]@{ExitCode=$sgProcess.ExitCode;Result=$sgValue}
}
function Fixture-SG([string]$Name,[bool]$Vendors=$true){
    $sgRoot=Join-Path $sgTests $Name;Json-SG (Join-Path $sgRoot 'fixture.json') @{kind='schemegrid-native-installer-fixture'}
    New-Item -ItemType Directory -Path (Join-Path $sgRoot 'profile\AppData\Local') -Force|Out-Null
    if($Vendors){foreach($sgArch in @('ChemDrawApplications','ChemDrawApplications_x64')){
        $sgApp=Join-Path $sgRoot ('profile\AppData\Local\Programs\RevvitySignalsSoftware\'+$sgArch)
        New-Item -ItemType Directory -Path (Join-Path $sgApp 'ChemDraw\Scripts') -Force|Out-Null
        Copy-Item -LiteralPath $sgHelper -Destination (Join-Path $sgApp 'ChemDraw.exe')
        foreach($sgCommand in $sgCommands){Write-SG (Join-Path $sgApp ('ChemDraw\Scripts\'+$sgCommand.fileName)) ("# SchemeGridNativePreview managed shim v1`n# command: "+$sgCommand.command+"`n# original fixture`n")}
    }}
    return $sgRoot
}
function Snapshot-SG([string]$Root){$sgData=@{};foreach($sgFile in Get-ChildItem -LiteralPath (Join-Path $Root 'profile\AppData\Local\Programs\RevvitySignalsSoftware') -File -Recurse){$sgData[$sgFile.FullName.Substring($Root.Length)]=(Get-FileHash -LiteralPath $sgFile.FullName).Hash};return ($sgData|ConvertTo-Json -Compress)}
function LegacySnap-SG([string]$Root){
    $sgEntry=Join-Path $Root 'profile\AppData\Local\Programs\SchemeGrid\SchemeGrid-ChemScript.py'
    $sgEntryLiteral=ConvertTo-Json -InputObject $sgEntry -Compress
    $sgText=@(
        '# -*- coding: utf-8 -*-',
        '# Scheme Grid managed ChemScript menu entry',
        '# File > ChemScripts > Scheme Grid - Snap Scheme',
        '# Clear all selections first; output opens as a separate drawing.',
        'import os',
        'import runpy',
        ('_scheme_grid_entry = '+$sgEntryLiteral),
        'if not os.path.isfile(_scheme_grid_entry):',
        "    raise RuntimeError('Scheme Grid installation is missing. Reinstall the Scheme Grid ChemScript command.')",
        "runpy.run_path(_scheme_grid_entry, run_name='__main__')"
    ) -join "`n"
    foreach($sgArch in @('ChemDrawApplications','ChemDrawApplications_x64')){
        $sgPath=Join-Path $Root ('profile\AppData\Local\Programs\RevvitySignalsSoftware\'+$sgArch+'\ChemDraw\Scripts\'+$sgLegacyName)
        Write-SG $sgPath $sgText
        $sgPath
    }
}

$sgValue=Invoke-SG $sgSetup1 @('--validate-only');Check-SG 'Embedded payload validation succeeds without installation' ($sgValue.ExitCode -eq 0 -and $sgValue.Result.ok)
$sgNoVendor=Fixture-SG 'no-vendor' $false
$sgValue=Invoke-SG $sgSetup1 @('--fixture-root',$sgNoVendor,'--install');Check-SG 'Missing ChemDraw refuses and creates no vendor folders' ($sgValue.ExitCode -ne 0 -and -not(Test-Path -LiteralPath (Join-Path $sgNoVendor 'profile\AppData\Local\Programs\RevvitySignalsSoftware')))
$sgRoot=Fixture-SG 'f s'
$sgBefore=Snapshot-SG $sgRoot
$sgValue=Invoke-SG $sgProduction @('--fixture-root',$sgRoot,'--install');Check-SG 'Production build refuses fixture overrides' ($sgValue.ExitCode -ne 0 -and (Snapshot-SG $sgRoot) -ceq $sgBefore)
$sgValue=Invoke-SG $sgSetup1 @('--install');Check-SG 'Fixture build refuses real profile installation' ($sgValue.ExitCode -ne 0)
$sgValue=Invoke-SG $sgSetup1 @('--fixture-root',$sgRoot,'--install');Check-SG 'Both ChemDraw architectures install from private fixture payload' ($sgValue.ExitCode -eq 0 -and $sgValue.Result.ok -and $sgValue.Result.pythonHost.systemProvisioningExecuted -eq $false)
Check-SG 'Absent legacy Snap command permits installation without creating it' ($sgValue.ExitCode -eq 0 -and @(Get-ChildItem -LiteralPath (Join-Path $sgRoot 'profile\AppData\Local\Programs\RevvitySignalsSoftware') -File -Recurse -Filter $sgLegacyName).Count -eq 0)
$sgInstalled=$sgValue.Result.destination
$sgRuntime=Get-Content -LiteralPath (Join-Path $sgInstalled 'core\native-runtime.json') -Raw|ConvertFrom-Json
Check-SG 'Only installed runtime is activated; source remains prepare' ($sgRuntime.mode -ceq 'apply-selected' -and ((Get-Content -LiteralPath (Join-Path $sgPayload 'core\native-runtime.json') -Raw|ConvertFrom-Json).mode -ceq 'prepare'))
Check-SG 'No reboot requested' (-not$sgValue.Result.rebootRequired)
$sgIndexPath=Join-Path $sgRoot 'profile\AppData\Local\SchemeGrid\Native\command-registration.json'
$sgFirstIndex=(Get-FileHash -LiteralPath $sgIndexPath).Hash
$sgValue=Invoke-SG $sgSetup1 @('--fixture-root',$sgRoot,'--install');Check-SG 'Same build is idempotent and keeps original backup chain' ($sgValue.ExitCode -eq 0 -and (Get-FileHash -LiteralPath $sgIndexPath).Hash -ceq $sgFirstIndex)
$sgVolatileLog=Join-Path $sgInstalled 'runtime\chromium\debug.log';Write-SG $sgVolatileLog 'generated browser diagnostics'
$sgValue=Invoke-SG $sgSetup1 @('--fixture-root',$sgRoot,'--install');Check-SG 'Exact generated browser debug log is allowed and preserved' ($sgValue.ExitCode -eq 0 -and (Get-Content -LiteralPath $sgVolatileLog -Raw) -ceq 'generated browser diagnostics')
$sgUnknown=Join-Path $sgInstalled 'runtime\chromium\another.log';Write-SG $sgUnknown 'unexpected extra file';$sgBeforeUnknown=Snapshot-SG $sgRoot
$sgValue=Invoke-SG $sgSetup1 @('--fixture-root',$sgRoot,'--install');Check-SG 'Any other extra runtime file refuses without removing it or changing commands' ($sgValue.ExitCode -ne 0 -and (Test-Path -LiteralPath $sgUnknown) -and (Snapshot-SG $sgRoot) -ceq $sgBeforeUnknown)
Remove-Item -LiteralPath $sgUnknown
$sgSnapshot1=Snapshot-SG $sgRoot
$sgValue=Invoke-SG $sgSetup2 @('--fixture-root',$sgRoot,'--install');Check-SG 'New version is installed beside retained previous version' ($sgValue.ExitCode -eq 0 -and (Test-Path -LiteralPath $sgInstalled) -and $sgValue.Result.destination -cne $sgInstalled)
$sgValue=Invoke-SG $sgSetup2 @('--fixture-root',$sgRoot,'--uninstall');Check-SG 'Uninstall upgrade restores previous commands and index' ($sgValue.ExitCode -eq 0 -and (Snapshot-SG $sgRoot) -ceq $sgSnapshot1 -and (Get-FileHash -LiteralPath $sgIndexPath).Hash -ceq $sgFirstIndex)
$sgValue=Invoke-SG $sgSetup1 @('--fixture-root',$sgRoot,'--uninstall');Check-SG 'Uninstall restores original preview shims exactly and retains user-safe payload' ($sgValue.ExitCode -eq 0 -and (Snapshot-SG $sgRoot) -ceq $sgBefore -and (Test-Path -LiteralPath $sgInstalled) -and -not(Test-Path -LiteralPath $sgIndexPath))

$sgRollback=Fixture-SG 'rollback';$sgBefore=Snapshot-SG $sgRollback
$sgValue=Invoke-SG $sgSetup1 @('--fixture-root',$sgRollback,'--install','--fail-after','3')
Check-SG 'Injected mid-registration failure restores every original script' ($sgValue.ExitCode -ne 0 -and (Snapshot-SG $sgRollback) -ceq $sgBefore -and $sgValue.Result.message.Contains('restored and verified'))
$sgFailedRuntime=Get-Content -LiteralPath (Join-Path $sgRollback 'profile\AppData\Local\Programs\SchemeGridNative\0.5.0-test.1\core\native-runtime.json') -Raw|ConvertFrom-Json
Check-SG 'Failed installed copy is returned to prepare mode' ($sgFailedRuntime.mode -ceq 'prepare')
$sgValue=Invoke-SG $sgSetup1 @('--fixture-root',$sgRollback,'--install');Check-SG 'Verified failed version can be safely retried' ($sgValue.ExitCode -eq 0 -and $sgValue.Result.ok)

# Retire only the exact historical separate-copy launcher, never a same-name edit.
$sgLegacyRoot=Fixture-SG 'legacy f s';$sgLegacyPaths=@(LegacySnap-SG $sgLegacyRoot)
$sgLegacyCRLF=([IO.File]::ReadAllText($sgLegacyPaths[1])).Replace("`n","`r`n")+"`r`n"
[IO.File]::WriteAllText($sgLegacyPaths[1],$sgLegacyCRLF,(New-Object Text.UTF8Encoding($true)))
$sgLegacyBefore=Snapshot-SG $sgLegacyRoot;$sgLegacyHashes=@{}
foreach($sgPath in $sgLegacyPaths){$sgLegacyHashes[$sgPath]=(Get-FileHash -LiteralPath $sgPath).Hash.ToLowerInvariant()}
$sgValue=Invoke-SG $sgSetup1 @('--fixture-root',$sgLegacyRoot,'--install')
$sgLegacyIndexPath=Join-Path $sgLegacyRoot 'profile\AppData\Local\SchemeGrid\Native\command-registration.json'
$sgRetired=@((Get-Content -LiteralPath $sgLegacyIndexPath -Raw|ConvertFrom-Json).files|Where-Object retired)
$sgLegacyBackupsMatch=$sgRetired.Count -eq 2
foreach($sgRetiredFile in $sgRetired){$sgLegacyBackupsMatch=$sgLegacyBackupsMatch -and (Test-Path -LiteralPath $sgRetiredFile.backupPath) -and ((Get-FileHash -LiteralPath $sgRetiredFile.backupPath).Hash.ToLowerInvariant() -ceq $sgLegacyHashes[$sgRetiredFile.path]) -and ($sgRetiredFile.backupSHA256 -ceq $sgLegacyHashes[$sgRetiredFile.path])}
Check-SG 'Exact historical Snap launchers retire in both architectures with verified backups' ($sgValue.ExitCode -eq 0 -and $sgValue.Result.ok -and $sgLegacyBackupsMatch -and @($sgLegacyPaths|Where-Object {Test-Path -LiteralPath $_}).Count -eq 0)
$sgLegacyIndexHash=(Get-FileHash -LiteralPath $sgLegacyIndexPath).Hash
$sgValue=Invoke-SG $sgSetup1 @('--fixture-root',$sgLegacyRoot,'--install')
Check-SG 'Retired legacy Snap state remains idempotent with its original backup chain' ($sgValue.ExitCode -eq 0 -and (Get-FileHash -LiteralPath $sgLegacyIndexPath).Hash -ceq $sgLegacyIndexHash)
$sgValue=Invoke-SG $sgSetup1 @('--fixture-root',$sgLegacyRoot,'--uninstall')
Check-SG 'Uninstall restores exact legacy Snap bytes including original newline and BOM variants' ($sgValue.ExitCode -eq 0 -and (Snapshot-SG $sgLegacyRoot) -ceq $sgLegacyBefore -and -not(Test-Path -LiteralPath $sgLegacyIndexPath))

foreach($sgFailureCount in @(3,6)){
    $sgLegacyRollback=Fixture-SG ('legacy-rollback-'+$sgFailureCount);$sgLegacyRollbackPaths=@(LegacySnap-SG $sgLegacyRollback);$sgBefore=Snapshot-SG $sgLegacyRollback
    $sgValue=Invoke-SG $sgSetup1 @('--fixture-root',$sgLegacyRollback,'--install','--fail-after',([string]$sgFailureCount))
    Check-SG ('Injected failure after '+($sgFailureCount/3)+' legacy retirements restores both command folders exactly') ($sgValue.ExitCode -ne 0 -and (Snapshot-SG $sgLegacyRollback) -ceq $sgBefore -and $sgValue.Result.message.Contains('restored and verified') -and -not(Test-Path -LiteralPath (Join-Path $sgLegacyRollback 'profile\AppData\Local\SchemeGrid\Native\command-registration.json')))
}

$sgLegacyEdited=Fixture-SG 'legacy-edited';$sgLegacyEditedPaths=@(LegacySnap-SG $sgLegacyEdited)
Write-SG $sgLegacyEditedPaths[1] (([IO.File]::ReadAllText($sgLegacyEditedPaths[1]))+"`n# hand-edited same-header launcher")
$sgBefore=Snapshot-SG $sgLegacyEdited;$sgValue=Invoke-SG $sgSetup1 @('--fixture-root',$sgLegacyEdited,'--install')
Check-SG 'Edited Snap launcher with original headers refuses before either command folder changes' ($sgValue.ExitCode -ne 0 -and (Snapshot-SG $sgLegacyEdited) -ceq $sgBefore)

$sgLegacyForeign=Fixture-SG 'legacy-foreign';$sgLegacyForeignPaths=@(LegacySnap-SG $sgLegacyForeign)
Write-SG $sgLegacyForeignPaths[1] '# unrelated laboratory command with the same filename'
$sgBefore=Snapshot-SG $sgLegacyForeign;$sgValue=Invoke-SG $sgSetup1 @('--fixture-root',$sgLegacyForeign,'--install')
Check-SG 'Foreign Snap filename refuses before either command folder changes' ($sgValue.ExitCode -ne 0 -and (Snapshot-SG $sgLegacyForeign) -ceq $sgBefore)

$sgLegacyWrongPath=Fixture-SG 'legacy-wrong-path';$sgLegacyWrongPaths=@(LegacySnap-SG $sgLegacyWrongPath)
Write-SG $sgLegacyWrongPaths[1] (([IO.File]::ReadAllText($sgLegacyWrongPaths[1])).Replace('SchemeGrid-ChemScript.py','Other-ChemScript.py'))
$sgBefore=Snapshot-SG $sgLegacyWrongPath;$sgValue=Invoke-SG $sgSetup1 @('--fixture-root',$sgLegacyWrongPath,'--install')
Check-SG 'Same-header Snap launcher pointing to another runtime refuses without command writes' ($sgValue.ExitCode -ne 0 -and (Snapshot-SG $sgLegacyWrongPath) -ceq $sgBefore)

$sgLegacyForgedHeader=Fixture-SG 'legacy-forged-native-header';$sgLegacyForgedPaths=@(LegacySnap-SG $sgLegacyForgedHeader)
Write-SG $sgLegacyForgedPaths[1] "# SchemeGridNativePreview managed shim v1`n# command: Arrange`n# not the historical Snap launcher`n"
$sgBefore=Snapshot-SG $sgLegacyForgedHeader;$sgValue=Invoke-SG $sgSetup1 @('--fixture-root',$sgLegacyForgedHeader,'--install')
Check-SG 'Snap filename cannot use generic native-preview headers to claim ownership' ($sgValue.ExitCode -ne 0 -and (Snapshot-SG $sgLegacyForgedHeader) -ceq $sgBefore)

$sgContract.retireLegacy[0].command='Restore';Json-SG (Join-Path $sgPayload 'install-contract.json') $sgContract
$sgWrongLegacyCommand=Join-Path $sgTests 'WrongLegacyCommand.exe'; & (Join-Path $PSScriptRoot 'Build-Setup.ps1') -PayloadDirectory $sgPayload -OutputFile $sgWrongLegacyCommand -Version '0.5.0-test.4' -Fixture|Out-Null
$sgLegacyCommandRoot=Fixture-SG 'legacy-wrong-command';$sgLegacyCommandPaths=@(LegacySnap-SG $sgLegacyCommandRoot);$sgBefore=Snapshot-SG $sgLegacyCommandRoot
$sgValue=Invoke-SG $sgWrongLegacyCommand @('--fixture-root',$sgLegacyCommandRoot,'--install')
Check-SG 'Exact Snap launcher is refused when retirement is assigned to Restore' ($sgValue.ExitCode -ne 0 -and (Snapshot-SG $sgLegacyCommandRoot) -ceq $sgBefore)
$sgContract.retireLegacy[0].command='Arrange';Json-SG (Join-Path $sgPayload 'install-contract.json') $sgContract

$sgForeign=Fixture-SG 'foreign';$sgForeignFile=Join-Path $sgForeign ('profile\AppData\Local\Programs\RevvitySignalsSoftware\ChemDrawApplications_x64\ChemDraw\Scripts\'+$sgCommands[0].fileName)
Write-SG $sgForeignFile '# laboratory script, not managed by Scheme Grid';$sgBefore=Snapshot-SG $sgForeign
$sgValue=Invoke-SG $sgSetup1 @('--fixture-root',$sgForeign,'--install');Check-SG 'Unmarked existing script refuses before either vendor folder changes' ($sgValue.ExitCode -ne 0 -and (Snapshot-SG $sgForeign) -ceq $sgBefore)
Check-SG 'Preparation failure cleans only its owned temporary stage' (@(Get-ChildItem -LiteralPath (Join-Path $sgForeign 'profile\AppData\Local\Programs\SchemeGridNative') -Directory -Filter '.stage-*' -ErrorAction SilentlyContinue).Count -eq 0)

$sgTamper=Fixture-SG 'tamper';$sgValue=Invoke-SG $sgSetup1 @('--fixture-root',$sgTamper,'--install');$sgBefore=Snapshot-SG $sgTamper
Write-SG (Join-Path $sgValue.Result.destination 'host\Arrange.py.template') 'changed runtime source'
$sgValue=Invoke-SG $sgSetup1 @('--fixture-root',$sgTamper,'--install');Check-SG 'Changed immutable version is refused without command writes' ($sgValue.ExitCode -ne 0 -and (Snapshot-SG $sgTamper) -ceq $sgBefore)
$sgTamperedScript=Join-Path $sgTamper ('profile\AppData\Local\Programs\RevvitySignalsSoftware\ChemDrawApplications\ChemDraw\Scripts\'+$sgCommands[0].fileName)
Write-SG $sgTamperedScript '# hand edited after installation';$sgBefore=Snapshot-SG $sgTamper
$sgValue=Invoke-SG $sgSetup1 @('--fixture-root',$sgTamper,'--uninstall');Check-SG 'Uninstall refuses changed scripts and preserves all files' ($sgValue.ExitCode -ne 0 -and (Snapshot-SG $sgTamper) -ceq $sgBefore)

$sgContract.selfChecks[0].arguments=@('fail');Json-SG (Join-Path $sgPayload 'install-contract.json') $sgContract
$sgBadRuntime=Join-Path $sgTests 'BadRuntime.exe'; & (Join-Path $PSScriptRoot 'Build-Setup.ps1') -PayloadDirectory $sgPayload -OutputFile $sgBadRuntime -Version '0.5.0-test.3' -Fixture|Out-Null
$sgFailed=Fixture-SG 'failed-runtime';$sgBefore=Snapshot-SG $sgFailed
$sgValue=Invoke-SG $sgBadRuntime @('--fixture-root',$sgFailed,'--install');Check-SG 'Bundled runtime failure prevents all native command writes' ($sgValue.ExitCode -ne 0 -and (Snapshot-SG $sgFailed) -ceq $sgBefore)
$sgContract.selfChecks[0].arguments=@();Json-SG (Join-Path $sgPayload 'install-contract.json') $sgContract

# Exercise malicious embedded resources, without invoking any install path.
$sgBuild=Get-ChildItem -LiteralPath $PSScriptRoot -Directory -Filter 'build-*'|Sort-Object LastWriteTime -Descending|Select-Object -First 1
$sgManifest=Get-Content -LiteralPath (Join-Path $sgBuild.FullName 'payload-manifest.json') -Raw|ConvertFrom-Json
$sgUnsafeManifest=Join-Path $sgTests 'unsafe-manifest.json';$sgManifest.files[0].path='../escape.txt';Json-SG $sgUnsafeManifest $sgManifest
$sgUnsafeSetup=Join-Path $sgTests 'Unsafe.exe'
& $sgCsc /nologo /target:winexe /platform:anycpu "/out:$sgUnsafeSetup" "/win32manifest:$(Join-Path $PSScriptRoot 'Setup.exe.manifest')" /reference:System.dll /reference:System.Core.dll /reference:System.Drawing.dll /reference:System.Windows.Forms.dll /reference:System.IO.Compression.dll /reference:System.IO.Compression.FileSystem.dll /reference:System.Web.Extensions.dll "/resource:$(Join-Path $sgBuild.FullName 'payload.zip'),payload.zip" "/resource:$sgUnsafeManifest,payload-manifest.json" (Join-Path $PSScriptRoot 'Setup.cs')
if($LASTEXITCODE -ne 0){throw 'Unsafe-resource fixture compilation failed.'}
$sgValue=Invoke-SG $sgUnsafeSetup @('--validate-only');Check-SG 'Traversal in manifest is rejected before any extraction' ($sgValue.ExitCode -ne 0 -and -not(Test-Path -LiteralPath (Join-Path $sgTests 'escape.txt')))
$sgCorruptManifest=Get-Content -LiteralPath (Join-Path $sgBuild.FullName 'payload-manifest.json') -Raw|ConvertFrom-Json;$sgCorruptManifest.files[0].sha256=('0'*64);$sgCorruptPath=Join-Path $sgTests 'corrupt-manifest.json';Json-SG $sgCorruptPath $sgCorruptManifest
$sgCorruptSetup=Join-Path $sgTests 'Corrupt.exe'
& $sgCsc /nologo /target:winexe /platform:anycpu "/out:$sgCorruptSetup" "/win32manifest:$(Join-Path $PSScriptRoot 'Setup.exe.manifest')" /reference:System.dll /reference:System.Core.dll /reference:System.Drawing.dll /reference:System.Windows.Forms.dll /reference:System.IO.Compression.dll /reference:System.IO.Compression.FileSystem.dll /reference:System.Web.Extensions.dll "/resource:$(Join-Path $sgBuild.FullName 'payload.zip'),payload.zip" "/resource:$sgCorruptPath,payload-manifest.json" (Join-Path $PSScriptRoot 'Setup.cs')
if($LASTEXITCODE -ne 0){throw 'Corrupt-resource fixture compilation failed.'}
$sgValue=Invoke-SG $sgCorruptSetup @('--validate-only');Check-SG 'Embedded file checksum mismatch is rejected' ($sgValue.ExitCode -ne 0)

$sgReport=[ordered]@{ok=$true;checks=$sgChecks.Count;testRoot=$sgTests;liveChemDrawAccessed=$false;systemPythonProvisioned=$false;checksPassed=$sgChecks}
Json-SG (Join-Path $PSScriptRoot 'fixture-test-report.json') $sgReport
$sgReport|ConvertTo-Json -Depth 6
