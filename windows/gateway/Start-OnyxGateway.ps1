# ONYX CORE v0.5.0 localhost read-only gateway launcher.
# Run under the SAME Windows account as the production collector (DPAPI is user-scoped).
[CmdletBinding()]
param(
    [string]$Receiver = 'svr-onyxcore.local',
    [ValidateRange(1024,65535)][int]$Port = 18766
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$folder = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonFile = Join-Path $folder 'OnyxGateway.py'
$htmlFile = Join-Path $folder 'gateway-dashboard.html'
$tokenFile = Join-Path $env:LOCALAPPDATA 'OnyxCore\collector-token.dpapi'
foreach ($file in @($pythonFile, $htmlFile, $tokenFile)) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Required gateway file is missing: $file" }
}
# Resolve installed Python 3 executable. Windows Store aliases may not be valid installs.
$python = Get-Command python.exe -ErrorAction SilentlyContinue
$pythonPrefix = ''
if ($python) {
    $version = & $python.Source --version 2>&1
} else {
    $python = Get-Command py.exe -ErrorAction SilentlyContinue
    if (-not $python) { throw 'Python 3 not found. Check with: py -3 --version' }
    $pythonPrefix = '-3 '
    $version = & $python.Source -3 --version 2>&1
}
if ($LASTEXITCODE -ne 0 -or ([string]$version) -notmatch '^Python 3\.') {
    throw 'Python 3 is required (check Python installation and app execution aliases).'
}
$secure = Get-Content -LiteralPath $tokenFile -Raw | ConvertTo-SecureString
$secret = [System.Net.NetworkCredential]::new('', $secure).Password
if ($secret.Length -lt 32) { throw 'Saved collector token invalid.' }
$proc = New-Object System.Diagnostics.Process
$proc.StartInfo = New-Object System.Diagnostics.ProcessStartInfo
$proc.StartInfo.FileName = $python.Source
$proc.StartInfo.Arguments = ($pythonPrefix + ('-u "{0}" --dashboard "{1}" --receiver "{2}" --port {3}' -f $pythonFile, $htmlFile, $Receiver, $Port))
$proc.StartInfo.UseShellExecute = $false
$proc.StartInfo.RedirectStandardInput = $true
$proc.StartInfo.CreateNoWindow = $false
try {
    if (-not $proc.Start()) { throw 'Unable to launch gateway.' }
    $proc.StandardInput.WriteLine($secret)
    $proc.StandardInput.Close()
    $secret = $null
    $secure = $null
    Write-Host ('Gateway launched. Use http://127.0.0.1:{0}/dashboard' -f $Port)
    Write-Host 'Close the child Python process to stop gateway. This window waits for process exit.'
    $proc.WaitForExit()
    if ($proc.ExitCode -ne 0) { throw "Gateway process exited with code $($proc.ExitCode)" }
}
finally {
    $secret = $null
    $secure = $null
    $proc.Dispose()
}
