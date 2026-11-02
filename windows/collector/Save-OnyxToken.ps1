# Run interactively as the SAME Windows user who will run the collector.
# DPAPI CurrentUser protects token at rest. Never put this file under Git.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$dir = Join-Path $env:LOCALAPPDATA 'OnyxCore'
$file = Join-Path $dir 'collector-token.dpapi'
New-Item -ItemType Directory -Path $dir -Force | Out-Null
if (Test-Path -LiteralPath $file) {
    throw "Token file exists: $file. Delete manually only when intentionally rotating credentials."
}
$secret = Read-Host 'Paste permanent Pi receiver token (not echoed)' -AsSecureString
$plain = [System.Net.NetworkCredential]::new('', $secret).Password
try {
    if ($plain.Length -lt 32) { throw 'Token must be at least 32 characters' }
    $secret | ConvertFrom-SecureString | Set-Content -LiteralPath $file -Encoding ASCII -NoNewline
    Write-Host "DPAPI-protected token saved to $file for current user $env:USERNAME"
} finally {
    $plain = $null
    Remove-Variable secret,plain -ErrorAction SilentlyContinue
}
