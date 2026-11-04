[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ClientData,
    [string]$Output
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).ProviderPath
$data = (Resolve-Path -LiteralPath $ClientData).ProviderPath
$installArtifacts = Join-Path $repo 'artifacts\install'
$templates = Join-Path $PSScriptRoot 'player_package'
$pythonInstaller = Join-Path $installArtifacts 'dependencies\python-3.12.10-amd64.exe'
$stormLib = Join-Path $PSScriptRoot 'vendor\StormLib.dll'
$previewSource = Join-Path $installArtifacts 'preview\Data\patch-Z.MPQ'

if (-not $Output) {
    $Output = Join-Path $repo 'artifacts\release\WoWSpotlight-Player.zip'
}
$outputPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Output)
if ([IO.Path]::GetExtension($outputPath) -ine '.zip') {
    throw 'The output path must end in .zip.'
}
$outputDirectory = [IO.Path]::GetDirectoryName($outputPath)
$launcher = (Get-Command py.exe -CommandType Application | Select-Object -First 1).Source

$rootFiles = @('Spotlight.cmd', 'Install Spotlight.ps1', 'README.md', 'StormLib-LICENSE.txt')
$modules = @(
    'arm_motion.py', 'client_poc.py', 'duet_assets.py', 'duet_runtime.py',
    'duet_select.py', 'preview_poc.py', 'runtime_poc.py', 'spotlight_bridge.py',
    'spotlight_comfy.py', 'spotlight_http.py', 'spotlight_ipc.py', 'spotlight_library.py',
    'spotlight_publish.py', 'spotlight_viewer.py', 'stormlib.py'
)
$required = @($pythonInstaller, $stormLib)
$required += $rootFiles | ForEach-Object { Join-Path $templates $_ }
$required += $modules | ForEach-Object { Join-Path $PSScriptRoot $_ }
foreach ($path in $required) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required package file is missing: $path"
    }
}
if ((Get-FileHash -LiteralPath $pythonInstaller).Hash -ne '67B5635E80EA51072B87941312D00EC8927C4DB9BA18938F7AD2D27B328B95FB') {
    throw "The Python installer does not match the official Python 3.12.10 x64 release: $pythonInstaller"
}

function Invoke-SpotlightPython([string[]]$ScriptArguments) {
    & $launcher -3.12 -B @ScriptArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Could not run $($ScriptArguments[0]). Python exited with code $LASTEXITCODE."
    }
}

$id = [guid]::NewGuid().ToString('N')
$stage = Join-Path $outputDirectory ".spotlight-stage-$id"
$stagedZip = Join-Path $outputDirectory ".spotlight-stage-$id.zip"
$package = Join-Path $stage 'package'
$clips = Join-Path $stage 'clips'
$app = Join-Path $package 'app'
$dependencies = Join-Path $package 'dependencies'
$creator = Join-Path $package 'payload\Creator'
$viewer = Join-Path $package 'payload\Viewer'
$preview = Join-Path $package 'payload\Preview'
$creatorData = Join-Path $creator 'Data\enUS'
$viewerData = Join-Path $viewer 'Data'
$previewData = Join-Path $preview 'Data'
$creatorAddOns = Join-Path $creator 'Interface\AddOns'
$viewerAddOns = Join-Path $viewer 'Interface\AddOns'
$vendor = Join-Path $app 'vendor'

New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
$stageCreated = $false
try {
    New-Item -ItemType Directory -Path $stage | Out-Null
    $stageCreated = $true
    New-Item -ItemType Directory -Path $vendor, $dependencies, $creatorData, $viewerData,
        $previewData, $creatorAddOns, $viewerAddOns -Force | Out-Null

    foreach ($name in $rootFiles) {
        Copy-Item -LiteralPath (Join-Path $templates $name) -Destination $package
    }
    foreach ($name in $modules) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination $app
    }
    Copy-Item -LiteralPath $stormLib -Destination $vendor
    Copy-Item -LiteralPath $pythonInstaller -Destination $dependencies
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'live_lab\SpotlightDanceLab') -Destination $creatorAddOns -Recurse
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'live_lab\SpotlightViewer') -Destination $viewerAddOns -Recurse
    Set-Content -LiteralPath (Join-Path $viewer 'SpotlightDuet.lab') -Value 'WoWSpotlight duet lab' -Encoding Ascii

    Invoke-SpotlightPython @((Join-Path $PSScriptRoot 'live_setup.py'),
        (Join-Path $creatorData 'patch-enUS-Z.MPQ'), '--client-data', $data)
    Invoke-SpotlightPython @((Join-Path $PSScriptRoot 'make_duet_clips.py'), $clips)
    $duet = @((Join-Path $PSScriptRoot 'duet_assets.py'),
        (Join-Path $clips 'left-arm.motion.json'), (Join-Path $clips 'right-arm.motion.json'))
    Invoke-SpotlightPython ($duet + @((Join-Path $viewerData 'patch-Z.MPQ'), '--client-data', $data))
    if (Test-Path -LiteralPath $previewSource -PathType Leaf) {
        Copy-Item -LiteralPath $previewSource -Destination $previewData
    } else {
        Invoke-SpotlightPython ($duet + @((Join-Path $previewData 'patch-Z.MPQ'), '--client-data', $data, '--preview'))
    }

    Compress-Archive -Path (Join-Path $package '*') -DestinationPath $stagedZip
    if ([IO.File]::Exists($outputPath)) {
        [IO.File]::Replace($stagedZip, $outputPath, [NullString]::Value)
    } else {
        [IO.File]::Move($stagedZip, $outputPath)
    }
    Write-Output $outputPath
} finally {
    if ($stageCreated -and (Test-Path -LiteralPath $stagedZip -PathType Leaf)) {
        Remove-Item -LiteralPath $stagedZip
    }
    if ($stageCreated -and (Test-Path -LiteralPath $stage -PathType Container)) {
        $stageItem = Get-Item -LiteralPath $stage
        if ($stageItem.Parent.FullName -ieq $outputDirectory -and
            $stageItem.Name -eq ".spotlight-stage-$id" -and
            -not ($stageItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            Remove-Item -LiteralPath $stageItem.FullName -Recurse -Force
        }
    }
}
