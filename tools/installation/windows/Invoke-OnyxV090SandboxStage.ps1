# ONYX CORE v0.9.0 M2 package sandbox, Windows PowerShell 5.1.
# Preview by default. -Stage writes ONLY under %TEMP%\OnyxV090-*.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Archive,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9A-Fa-f]{64}$')][string]$ExpectedSha256,
    [Parameter(Mandatory=$true)][string]$ExpectedCommit,
    [Parameter(Mandatory=$true)][string]$ExpectedVersion,
    [ValidatePattern('^OnyxV090-[A-Za-z0-9_-]{1,50}$')][string]$SandboxName = 'OnyxV090-WindowsSandbox',
    [switch]$Stage
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1) {
    throw 'Windows PowerShell 5.1 required.'
}
$Python = 'C:\Python313\python.exe'
$StageScript = Join-Path $PSScriptRoot '..\common\onyx_stage.py'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf) -or
    -not (Test-Path -LiteralPath $StageScript -PathType Leaf)) {
    throw 'Python 3.13 or developer staging module missing.'
}
$Destination = Join-Path ([IO.Path]::GetTempPath()) $SandboxName
$Args = @('-I', '-B', $StageScript, '--archive', $Archive,
          '--platform', 'windows', '--expected-sha256', $ExpectedSha256,
          '--expected-commit', $ExpectedCommit, '--expected-version', $ExpectedVersion,
          '--target', $Destination)
if ($Stage) { $Args += '--stage' }
& $Python @Args
if ($LASTEXITCODE -ne 0) { throw 'Verified sandbox staging refused or failed.' }
