# ONYX CORE v0.9.0 inactive source installer. Windows PowerShell 5.1.
# PREVIEW by default. No tasks/services, credential, DB or networking changes.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Archive,
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{40}$')][string]$ExpectedCommit,
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-fA-F0-9]{64}$')][string]$ExpectedSHA256,
    [ValidatePattern('^0\.9\.0([-\.][A-Za-z0-9.-]+)?$')][string]$Version = '0.9.0',
    [switch]$System,
    [switch]$Apply,
    [switch]$ApproveInactiveSystemPreparation
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1) {
    throw 'Windows PowerShell 5.1 required.'
}
$Python = 'C:\Python313\python.exe'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw 'Python 3.13 prerequisite not found at approved runtime location.'
}
$Installer = Join-Path $PSScriptRoot '..\common\onyx_install.py'
if (-not (Test-Path -LiteralPath $Installer -PathType Leaf)) {
    throw 'Versioned installer code missing.'
}
if ($System) {
    $Target = 'C:\Program Files\OnyxCore\v0.9.0'
    if ($Apply -and -not $ApproveInactiveSystemPreparation) {
        throw 'Explicit -ApproveInactiveSystemPreparation required.'
    }
    $Arguments = @('-I', '-B', $Installer,
                   '--archive', $Archive, '--target', $Target,
                   '--platform', 'windows', '--expected-commit', $ExpectedCommit,
                   '--expected-version', $Version, '--expected-sha256', $ExpectedSHA256,
                   '--system')
    if ($ApproveInactiveSystemPreparation) {
        $Arguments += '--approve-inactive-system-preparation'
    }
}
else {
    if ($ApproveInactiveSystemPreparation) {
        throw 'System approval switch is invalid for sandbox installs.'
    }
    $Target = Join-Path $env:TEMP ('OnyxV090-' + [guid]::NewGuid().ToString('N'))
    $Arguments = @('-I', '-B', $Installer,
                   '--archive', $Archive, '--target', $Target,
                   '--platform', 'windows', '--expected-commit', $ExpectedCommit,
                   '--expected-version', $Version, '--expected-sha256', $ExpectedSHA256)
}
if ($Apply) { $Arguments += '--apply' }
& $Python @Arguments
if ($LASTEXITCODE -ne 0) { throw 'ONYX CORE inactive preparation refused.' }
