[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$TrackRoot,
    [string]$ModsDirectory = (Join-Path $env:LOCALAPPDATA 'BeamNG\BeamNG.drive\current\mods\repo'),
    [string]$Python = 'python'
)
$ErrorActionPreference = 'Stop'
$trackPath = (Resolve-Path -LiteralPath $TrackRoot).Path
$modsPath = (Resolve-Path -LiteralPath $ModsDirectory).Path
$pythonPath = (Get-Command $Python -ErrorAction Stop).Source
$conversionRoot = Join-Path $trackPath '_beamng_conversion'
$script = Join-Path $conversionRoot 'tools\install_fixed_mod.py'
if (-not (Test-Path -LiteralPath $script)) { throw 'Run Build.ps1 first.' }
& $pythonPath -X utf8 -B $script $modsPath
if ($LASTEXITCODE -ne 0) { throw 'Installation failed. Review the error above.' }
Write-Host 'Verified archive installed. Start BeamNG manually when ready.'
