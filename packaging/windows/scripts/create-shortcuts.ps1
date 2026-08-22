param(
    [Parameter(Mandatory = $true)]
    [string]$PackageRoot
)

$ErrorActionPreference = 'Stop'
$ResolvedRoot = (Resolve-Path -LiteralPath $PackageRoot).Path
$Desktop = [Environment]::GetFolderPath('Desktop')
$ShortcutFiles = [ordered]@{
    'Start W Bot.lnk' = 'Start Bot.cmd'
    'Stop W Bot.lnk' = 'Stop Bot.cmd'
    'W Bot Status.lnk' = 'Bot Status.cmd'
    'W Bot Logs.lnk' = 'Show Bot Logs.cmd'
}

$WshShell = New-Object -ComObject WScript.Shell
foreach ($Entry in $ShortcutFiles.GetEnumerator()) {
    $ShortcutPath = Join-Path -Path $Desktop -ChildPath $Entry.Key
    $Target = Join-Path -Path $ResolvedRoot -ChildPath $Entry.Value
    $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = $Target
    $Shortcut.WorkingDirectory = $ResolvedRoot
    $Shortcut.IconLocation = Join-Path -Path $ResolvedRoot -ChildPath 'app\w-bot.exe'
    $Shortcut.Save()
}
