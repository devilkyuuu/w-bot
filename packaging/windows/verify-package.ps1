param(
    [Parameter(Mandatory = $true)][string]$PackageRoot
)

$ErrorActionPreference = 'Stop'
$ResolvedRoot = (Resolve-Path -LiteralPath $PackageRoot).Path
$ManifestPath = Join-Path $PSScriptRoot 'package-manifest.json'
$Manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json

foreach ($Relative in $Manifest.required_files) {
    $Required = Join-Path $ResolvedRoot $Relative
    if (-not (Test-Path -LiteralPath $Required -PathType Leaf)) {
        throw "Unsafe package: required file is missing: $Relative"
    }
}

$Forbidden = @{}
foreach ($Name in $Manifest.forbidden_names) {
    $Forbidden[$Name.ToLowerInvariant()] = $true
}
Get-ChildItem -LiteralPath $ResolvedRoot -Recurse -Force | ForEach-Object {
    if ($Forbidden.ContainsKey($_.Name.ToLowerInvariant())) {
        throw "Unsafe package: user state or credentials are present."
    }
}

foreach ($RuntimeName in @('data', 'logs', 'temp')) {
    $RuntimePath = Join-Path $ResolvedRoot $RuntimeName
    if (Test-Path -LiteralPath $RuntimePath -PathType Container) {
        $RuntimeContent = Get-ChildItem -LiteralPath $RuntimePath -Force
        if ($null -ne $RuntimeContent) {
            throw "Unsafe package: runtime data is present."
        }
    }
}

$TextExtensions = @('.txt', '.cmd', '.ps1', '.json', '.md', '.yml', '.yaml', '.toml', '.ini', '.cfg')
$TextFiles = Get-ChildItem -LiteralPath $ResolvedRoot -Recurse -File | Where-Object {
    $TextExtensions -contains $_.Extension.ToLowerInvariant()
}
foreach ($TextFile in $TextFiles) {
    if (Select-String -LiteralPath $TextFile.FullName -Pattern $Manifest.token_pattern -Quiet) {
        throw "Unsafe package: a token-shaped value is present."
    }
}

foreach ($Check in $Manifest.smoke_checks) {
    $Executable = Join-Path $ResolvedRoot $Check.path
    & $Executable @($Check.arguments) | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Package smoke check failed: $($Check.path)"
    }
}

Write-Output 'Portable package verified.'
