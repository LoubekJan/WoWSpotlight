[CmdletBinding()]
param(
    [ValidateSet('Creator', 'Viewer', 'Preview')]
    [string]$Role,
    [string]$ClientDir,
    [string]$RelayTokenFile,
    [switch]$InstallOnly
)

$ErrorActionPreference = 'Stop'
$comfyUrl = 'http://192.168.0.248:8188'
$relayUrl = 'http://192.168.0.248:8765'

if (!$Role) {
    $Role = Read-Host 'Choose Creator (upload video), Viewer (watch shared dances), or Preview (offline comparison)'
}
if ($Role -notin 'Creator', 'Viewer', 'Preview') { throw 'Choose Creator, Viewer, or Preview.' }
if (!$ClientDir) { $ClientDir = Read-Host 'Paste the folder that contains WoW.exe' }
$client = (Resolve-Path -LiteralPath $ClientDir.Trim('"')).ProviderPath
$exe = Join-Path $client 'WoW.exe'
$data = Join-Path $client 'Data'
if ($client -eq 'C:\WoWModding\Client-Lab') { throw 'Select a separate copy of the base client.' }
if (!(Test-Path -LiteralPath $exe -PathType Leaf) -or
    !(Test-Path -LiteralPath (Join-Path $data 'enUS\patch-enUS-2.MPQ') -PathType Leaf)) {
    throw 'Select a separate WoW 3.3.5a enUS client folder with WoW.exe and its Data folder.'
}
if ((Get-FileHash -LiteralPath $exe).Hash -ne '28287cd94e6ab2d6e68865f49314b456d2750dcb5d0b8ecca12eeddf72b7bf80') {
    throw 'The selected WoW.exe does not match the verified build 12340.'
}
if (Get-Process -Name WoW -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exe }) {
    throw 'Close WoW from the selected folder before running Spotlight.cmd.'
}
if ($RelayTokenFile) {
    if ($Role -ne 'Creator') { throw 'A share token is only needed in Creator mode.' }
    $RelayTokenFile = (Resolve-Path -LiteralPath $RelayTokenFile).ProviderPath
}

$app = Join-Path $PSScriptRoot 'app'
if (!$InstallOnly -and $Role -ne 'Preview') {
    $pythonReady = $false
    $py = Get-Command py.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    $pyw = Get-Command pyw.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($py -and $pyw) {
        & $py.Source -3.12 -B -c 'import sys, tkinter; assert sys.maxsize > 2**32' 2>$null
        $pythonReady = $LASTEXITCODE -eq 0
    }
    if (!$pythonReady) {
        throw 'Install the bundled dependencies\python-3.12.10-amd64.exe with Python Launcher and Tcl/Tk, then run Spotlight.cmd again.'
    }
}

$payload = Join-Path (Join-Path $PSScriptRoot 'payload') $Role
$patch = if ($Role -eq 'Creator') { 'Data\enUS\patch-enUS-Z.MPQ' } else { 'Data\patch-Z.MPQ' }
if (!(Test-Path -LiteralPath (Join-Path $payload $patch) -PathType Leaf)) {
    throw "Extract the entire ZIP before running Spotlight.cmd. Missing payload\$Role\$patch."
}
if (($Role -ne 'Creator' -and (Test-Path -LiteralPath (Join-Path $client 'Interface\AddOns\SpotlightDanceLab\SpotlightDanceLab.toc'))) -or
    ($Role -ne 'Viewer' -and (Test-Path -LiteralPath (Join-Path $client 'SpotlightDuet.lab')))) {
    throw 'Use a separate clean client for each Spotlight mode.'
}

$installFiles = foreach ($source in Get-ChildItem -LiteralPath $payload -Recurse -File) {
    $target = Join-Path $client $source.FullName.Substring($payload.Length + 1)
    if (Test-Path -LiteralPath $target) {
        if (!(Test-Path -LiteralPath $target -PathType Leaf) -or
            (Get-FileHash -LiteralPath $target).Hash -ne (Get-FileHash -LiteralPath $source.FullName).Hash) {
            throw "An existing file differs from this package. Use a separate clean client. $target"
        }
    } else {
        @{ Source = $source.FullName; Target = $target }
    }
}
foreach ($file in $installFiles) {
    $parent = Split-Path -Parent $file.Target
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $staged = Join-Path $parent ([IO.Path]::GetRandomFileName())
    try {
        [IO.File]::Copy($file.Source, $staged, $false)
        [IO.File]::Move($staged, $file.Target)
    } finally {
        if (Test-Path -LiteralPath $staged) { Remove-Item -LiteralPath $staged }
    }
}
Write-Host "Spotlight $Role installed in $client"
if ($InstallOnly) { exit 0 }

switch ($Role) {
    'Creator' {
        $arguments = @('-3.12', '-B', ('"{0}"' -f (Join-Path $app 'spotlight_bridge.py')),
            '--launch', '--client-dir', ('"{0}"' -f $client), '--comfy-url', $comfyUrl)
        if ($RelayTokenFile) {
            $arguments += @('--relay-url', $relayUrl, '--relay-token-file', ('"{0}"' -f $RelayTokenFile))
        }
        Start-Process -FilePath $pyw.Source -ArgumentList $arguments -WindowStyle Hidden
    }
    'Viewer' {
        $game = Start-Process -FilePath $exe -WorkingDirectory $client -PassThru
        Write-Host 'Log in to WoW and stop at character selection.'
        [void](Read-Host 'Press Enter here at character selection')
        & $py.Source -3.12 -B (Join-Path $app 'spotlight_viewer.py') $game.Id --client-dir $client --relay-url $relayUrl
        exit $LASTEXITCODE
    }
    'Preview' {
        Start-Process -FilePath $exe -WorkingDirectory $client
    }
}
