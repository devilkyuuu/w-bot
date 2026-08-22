param(
    [Parameter(Mandatory = $true)][string]$BotDist,
    [Parameter(Mandatory = $true)][string]$TelegramApi,
    [Parameter(Mandatory = $true)][string]$FfmpegRoot,
    [Parameter(Mandatory = $true)][string]$Output
)

$ErrorActionPreference = 'Stop'

function Require-File([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label was not found."
    }
}

if (-not (Test-Path -LiteralPath $BotDist -PathType Container)) {
    throw 'The PyInstaller distribution was not found.'
}
Require-File (Join-Path $BotDist 'w-bot.exe') 'w-bot.exe'
Require-File $TelegramApi 'telegram-bot-api.exe'
if (-not (Test-Path -LiteralPath $FfmpegRoot -PathType Container)) {
    throw 'The FFmpeg directory was not found.'
}

$Ffmpeg = Get-ChildItem -LiteralPath $FfmpegRoot -Recurse -File -Filter 'ffmpeg.exe' |
    Select-Object -First 1
$Ffprobe = Get-ChildItem -LiteralPath $FfmpegRoot -Recurse -File -Filter 'ffprobe.exe' |
    Select-Object -First 1
if ($null -eq $Ffmpeg -or $null -eq $Ffprobe) {
    throw 'The FFmpeg executables were not found.'
}

if (Test-Path -LiteralPath $Output) {
    $Existing = Get-ChildItem -LiteralPath $Output -Force
    if ($null -ne $Existing) {
        throw 'The package output directory must be empty.'
    }
} else {
    New-Item -ItemType Directory -Path $Output | Out-Null
}

$PackageRoot = Join-Path $Output 'W-Bot'
$Directories = @(
    $PackageRoot,
    (Join-Path $PackageRoot 'app'),
    (Join-Path $PackageRoot 'telegram-api'),
    (Join-Path $PackageRoot 'tools'),
    (Join-Path $PackageRoot 'scripts'),
    (Join-Path $PackageRoot 'licenses'),
    (Join-Path $PackageRoot 'licenses\telegram-bot-api'),
    (Join-Path $PackageRoot 'licenses\ffmpeg')
)
foreach ($Directory in $Directories) {
    New-Item -ItemType Directory -Path $Directory | Out-Null
}

Get-ChildItem -LiteralPath $BotDist -Force | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $PackageRoot 'app') -Recurse
}
Copy-Item -LiteralPath $TelegramApi -Destination (
    Join-Path $PackageRoot 'telegram-api\telegram-bot-api.exe'
)
Copy-Item -LiteralPath $Ffmpeg.FullName -Destination (Join-Path $PackageRoot 'tools\ffmpeg.exe')
Copy-Item -LiteralPath $Ffprobe.FullName -Destination (Join-Path $PackageRoot 'tools\ffprobe.exe')

$FfmpegBin = $Ffmpeg.Directory.FullName
Get-ChildItem -LiteralPath $FfmpegBin -File -Filter '*.dll' | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $PackageRoot 'tools')
}
$FfmpegLicenses = Get-ChildItem -LiteralPath $FfmpegRoot -Recurse -File | Where-Object {
    $_.Name -like 'LICENSE*' -or $_.Name -like 'COPYING*'
}
if ($null -eq $FfmpegLicenses) {
    throw 'The FFmpeg license files were not found.'
}
foreach ($License in $FfmpegLicenses) {
    Copy-Item -LiteralPath $License.FullName -Destination (
        Join-Path $PackageRoot ('licenses\ffmpeg\' + $License.Name)
    )
}

$ControlFiles = @(
    'Setup Bot.cmd',
    'Start Bot.cmd',
    'Stop Bot.cmd',
    'Bot Status.cmd',
    'Show Bot Logs.cmd',
    'Create Desktop Shortcuts.cmd',
    'README-WINDOWS.txt',
    'THIRD-PARTY-NOTICES.txt'
)
foreach ($ControlFile in $ControlFiles) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $ControlFile) -Destination $PackageRoot
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'scripts\create-shortcuts.ps1') -Destination (
    Join-Path $PackageRoot 'scripts\create-shortcuts.ps1'
)
Copy-Item -LiteralPath (
    Join-Path $PSScriptRoot 'licenses\telegram-bot-api-LICENSE.txt'
) -Destination (Join-Path $PackageRoot 'licenses\telegram-bot-api\LICENSE_1_0.txt')

Write-Output $PackageRoot
