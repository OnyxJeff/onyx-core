# ONYX CORE local-only DPAPI credential loader for the scheduled Python gateway.
# Never log or print this output; Python consumes it from a private pipe.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$path = Join-Path $env:LOCALAPPDATA 'OnyxCore\collector-token.dpapi'
if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { exit 2 }
try {
    $secure = Get-Content -LiteralPath $path -Raw | ConvertTo-SecureString
    $plain = [System.Net.NetworkCredential]::new('', $secure).Password
    if ($plain.Length -lt 32 -or $plain.Length -gt 2048 -or $plain.Contains("`n") -or $plain.Contains("`r")) { exit 3 }
    # Avoid formatting or writing the credential to files, logs, or stderr.
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
    [Console]::Out.WriteLine($plain)
} catch {
    exit 4
} finally {
    $plain = $null
    $secure = $null
}
