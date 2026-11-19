# ONYX CORE v0.9.0 RC2: inactive Windows installer staging ACL.
# Invoked only by the approved elevated system installer, before atomic rename.
# Deliberately binds runtime read/execute to the current installer identity:
# subsequent Scheduled Tasks must use this same user with RunLevel Limited.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$StagingRoot
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Elevated local administrator required. STOP.'
}
$root = [IO.Path]::GetFullPath($StagingRoot).TrimEnd('\')
$parent = [IO.Path]::GetDirectoryName($root)
$leaf = [IO.Path]::GetFileName($root)
if ($parent -ine 'C:\Program Files\OnyxCore' -or
    $leaf -cnotmatch '^\.onyx-v090-inactive-[A-Za-z0-9_-]+$') {
    throw 'Unexpected inactive staging path. STOP.'
}
$item = Get-Item -LiteralPath $root -Force -ErrorAction Stop
if (-not $item.PSIsContainer -or
    ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    throw 'Staging root must be a real directory. STOP.'
}
$sid = $identity.User.Value
if ($sid -notmatch '^S-1-5-21-(?:[0-9]+-){3}[0-9]+$') {
    throw 'Expected a regular Windows user SID. STOP.'
}
$icacls = Join-Path $env:WINDIR 'System32\icacls.exe'
if (-not (Test-Path -LiteralPath $icacls -PathType Leaf)) {
    throw 'Windows ACL tool missing. STOP.'
}
# Do not grant Modify/FullControl, and do not broaden BUILTIN\Users access.
$grant = '*' + $sid + ':(OI)(CI)RX'
& $icacls $root /grant:r $grant | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw 'Windows ACL read/execute grant failed. STOP.'
}

$rx = [Security.AccessControl.FileSystemRights]::ReadAndExecute
$writeRights = [Security.AccessControl.FileSystemRights]::WriteData -bor
    [Security.AccessControl.FileSystemRights]::AppendData -bor
    [Security.AccessControl.FileSystemRights]::WriteExtendedAttributes -bor
    [Security.AccessControl.FileSystemRights]::WriteAttributes -bor
    [Security.AccessControl.FileSystemRights]::Delete -bor
    [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor
    [Security.AccessControl.FileSystemRights]::ChangePermissions -bor
    [Security.AccessControl.FileSystemRights]::TakeOwnership
$broadSids = @('S-1-1-0', 'S-1-5-11', 'S-1-5-32-545', 'S-1-5-32-546')
$items = @(Get-Item -LiteralPath $root -Force) +
    @(Get-ChildItem -LiteralPath $root -Recurse -Force -ErrorAction Stop)
if ($items.Count -lt 3) {
    throw 'Incomplete staging tree. STOP.'
}
foreach ($entry in $items) {
    if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw 'Redirected staging member forbidden. STOP.'
    }
    $acl = Get-Acl -LiteralPath $entry.FullName -ErrorAction Stop
    $allowed = $false
    foreach ($ace in $acl.Access) {
        $aceSid = $ace.IdentityReference.Translate(
            [Security.Principal.SecurityIdentifier]).Value
        if ($ace.AccessControlType -eq 'Allow' -and
            $aceSid -in $broadSids -and
            ($ace.FileSystemRights -band $writeRights)) {
            throw 'Broad writable staging ACL forbidden. STOP.'
        }
        if ($aceSid -eq $sid) {
            if ($ace.AccessControlType -eq 'Deny' -and
                ($ace.FileSystemRights -band $rx)) {
                throw 'Runtime user denied read/execute. STOP.'
            }
            if ($ace.AccessControlType -eq 'Allow') {
                if ($ace.FileSystemRights -band $writeRights) {
                    throw 'Runtime user has writable staging ACL. STOP.'
                }
                if (($ace.FileSystemRights -band $rx) -eq $rx) {
                    $allowed = $true
                }
            }
        }
    }
    if (-not $allowed) {
        throw 'Runtime user read/execute ACL not propagated. STOP.'
    }
}
Write-Output 'ONYX_ACL_VERIFIED'
