# ONYX CORE v1.0.0 M2-S2C: restricted ACL on a fresh user-scope STAGING tree.
# Called only after explicit install approval; never operates on an existing installation.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$StagingPath)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Local = [Environment]::GetFolderPath('LocalApplicationData')
if ([string]::IsNullOrWhiteSpace($Local)) { throw 'LocalAppData unavailable. STOP.' }
$Root = [IO.Path]::GetFullPath($Local).TrimEnd('\')
$Path = [IO.Path]::GetFullPath($StagingPath).TrimEnd('\')
$Parent = [IO.Path]::GetDirectoryName($Path)
$Name = [IO.Path]::GetFileName($Path)
if ($Parent -ine $Root -or $Name -cnotmatch '^\.OnyxCore-v100-staging-[a-zA-Z0-9_-]{8,70}$') {
    throw 'ACL helper only accepts a fresh staging directory directly beneath LocalAppData. STOP.'
}
if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw 'Staging directory missing. STOP.' }
$ParentItem = Get-Item -LiteralPath $Root -Force
if ($ParentItem.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Redirected LocalAppData refused. STOP.' }
$Nodes = @(Get-Item -LiteralPath $Path -Force)
$Nodes += @(Get-ChildItem -LiteralPath $Path -Recurse -Force -ErrorAction Stop)
foreach ($Node in $Nodes) {
    if ($Node.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Redirected staging content refused. STOP.' }
}
$Sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$Allow = @($Sid, 'S-1-5-18', 'S-1-5-32-544')
# Remove inherited ACEs on all staged files; keep only the current user, SYSTEM and Administrators.
& icacls.exe $Path /inheritance:r /T | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Staging ACL inheritance removal failed. STOP.' }
& icacls.exe $Path /grant:r "*${Sid}:(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' /T | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Staging ACL grant failed. STOP.' }
# Audit the complete resulting tree, including the receipt, before it can be published.
foreach ($Node in $Nodes) {
    $Acl = Get-Acl -LiteralPath $Node.FullName -ErrorAction Stop
    $Rules = $Acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])
    foreach ($Rule in $Rules) {
        if ($Rule.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and
            $Rule.IdentityReference.Value -notin $Allow) {
            throw 'Unexpected allowed principal on staged installation. STOP.'
        }
    }
}
# Restrict the install root's inheritance from its parent as well.
if (-not (Get-Acl -LiteralPath $Path).AreAccessRulesProtected) {
    throw 'Staging root ACL is still inherited. STOP.'
}
Write-Output 'PASS: User-scoped staging DACL restricted and audited.'
