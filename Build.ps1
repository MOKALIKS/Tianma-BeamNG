[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$TrackRoot,
    [Parameter(Mandatory = $true)][string]$GameRoot,
    [string]$Python = 'python',
    [switch]$InstallDependencies
)
$ErrorActionPreference = 'Stop'
$trackPath = (Resolve-Path -LiteralPath $TrackRoot).Path
$gamePath = (Resolve-Path -LiteralPath $GameRoot).Path
$pythonPath = (Get-Command $Python -ErrorAction Stop).Source
foreach ($relative in @('models.ini','st_stctk.kn5','ai\fast_lane.ai','ai\pit_lane.ai','ui\preview.png')) {
    if (-not (Test-Path -LiteralPath (Join-Path $trackPath $relative) -PathType Leaf)) {
        throw "Missing track input: $relative"
    }
}
foreach ($relative in @('content\levels\hirochi_raceway.zip','content\assets\materials\tree.zip','lua\common\mathlib.lua','gameplay\missionTypes\timeTrial\constructor.lua')) {
    if (-not (Test-Path -LiteralPath (Join-Path $gamePath $relative) -PathType Leaf)) {
        throw "Missing game input: $relative"
    }
}
$conversionRoot = Join-Path $trackPath '_beamng_conversion'
$toolsPath = Join-Path $conversionRoot 'tools'
$workPath = Join-Path $conversionRoot 'work'
New-Item -ItemType Directory -Force -Path $toolsPath,$workPath | Out-Null
# Existing project build scripts are refreshed from this checkout.
Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'tools') -File |
    Where-Object { $_.Extension -in '.py','.lua' } |
    Copy-Item -Destination $toolsPath -Force
$savedEnv = @{}
foreach ($key in @('BEAMNG_GAME_ROOT','PYTHONIOENCODING','PYTHONUTF8','PYTHONPYCACHEPREFIX','TEMP','TMP')) {
    $savedEnv[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
}
try {
    $env:BEAMNG_GAME_ROOT = $gamePath
    $env:PYTHONIOENCODING = 'utf-8'
    $env:PYTHONUTF8 = '1'
    $env:PYTHONPYCACHEPREFIX = Join-Path $workPath 'pycache'
    $env:TEMP = $workPath
    $env:TMP = $workPath
    if ($InstallDependencies) {
        & $pythonPath -B -m pip install --disable-pip-version-check --no-cache-dir --no-compile --upgrade --target (Join-Path $toolsPath 'lib') -r (Join-Path $PSScriptRoot 'requirements.txt')
        if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    }
    & $pythonPath -B (Join-Path $toolsPath 'convert_track.py') $trackPath
    if ($LASTEXITCODE -ne 0) { throw 'Conversion failed.' }
    & $pythonPath -B (Join-Path $toolsPath 'validate_conversion.py') $trackPath
    if ($LASTEXITCODE -ne 0) { throw 'Archive/geometry validation failed.' }
    foreach ($script in @('validate_visual_revision.py','validate_tone_revision.py')) {
        & $pythonPath -B (Join-Path $toolsPath $script)
        if ($LASTEXITCODE -ne 0) { throw "$script failed." }
    }
    & $pythonPath -B (Join-Path $toolsPath 'validate_v1.py') $gamePath
    if ($LASTEXITCODE -ne 0) { throw 'Native mission/navigation validation failed.' }
    Copy-Item -LiteralPath (Join-Path $workPath 'conversion_report.json') -Destination (Join-Path $conversionRoot 'output\conversion_report.json') -Force
    $archive = Join-Path $conversionRoot 'output\st_stctk_ac_port.zip'
    $checksum = Get-FileHash -LiteralPath $archive -Algorithm SHA256
    Set-Content -LiteralPath (Join-Path $conversionRoot 'output\SHA256.txt') -Encoding ascii -Value ($checksum.Hash.ToLowerInvariant() + '  st_stctk_ac_port.zip')
    Write-Host "Built and validated: $archive"
    Write-Host 'BeamNG was not launched. Install separately with Install-Mod.ps1.'
}
finally {
    foreach ($key in $savedEnv.Keys) {
        [Environment]::SetEnvironmentVariable($key, $savedEnv[$key], 'Process')
    }
}
