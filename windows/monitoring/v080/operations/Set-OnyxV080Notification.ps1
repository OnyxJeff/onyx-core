# Local-user development configuration ONLY. No task created; no webhook sent.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('ntfy','discord','json')]
    [string]$Provider,
    [switch]$Replace
)
$ErrorActionPreference = 'Stop'
$Base = Join-Path $env:LOCALAPPDATA 'OnyxCore-v080-Development\NotificationConfig'
$Target = Join-Path $Base 'destination.dpapi'
$Metadata = Join-Path $Base 'provider.txt'
if (-not $Replace -and ((Test-Path -LiteralPath $Target) -or (Test-Path -LiteralPath $Metadata))) {
    throw 'Existing notification configuration: explicitly use -Replace to change it.'
}
# The webhook URL may contain a credential in its path; never print it.
$Secret = Read-Host 'Webhook URL (input hidden)' -AsSecureString
if ($Secret.Length -lt 8) { throw 'Webhook URL too short.' }
if ($Provider -eq 'discord' -and $Secret.Length -lt 20) { throw 'Discord destination too short.' }
New-Item -ItemType Directory -Path $Base -Force | Out-Null
# ConvertFrom-SecureString without a supplied key uses Windows DPAPI,
# protecting the value for the currently logged-on account on this PC.
$Sealed = ConvertFrom-SecureString -SecureString $Secret
[IO.File]::WriteAllText($Target, $Sealed + "`n", [Text.Encoding]::ASCII)
[IO.File]::WriteAllText($Metadata, $Provider + "`n", [Text.Encoding]::ASCII)
Write-Host 'Notification destination stored under current-user DPAPI.'
Write-Host 'No alerts sent and no tasks installed.'
