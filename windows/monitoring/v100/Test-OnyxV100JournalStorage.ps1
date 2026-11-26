# Explicit same-user foreground storage admission. No existing ACL is changed.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidatePattern('^S-1-[0-9-]+$')][string]$ExpectedSid,
    [switch]$Initialize
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$Principal = [Security.Principal.WindowsPrincipal]::new($Identity)
if ($Identity.User.Value -cne $ExpectedSid -or
    $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Expected non-elevated supervising user required.'
}
$Local = [IO.Path]::GetFullPath([Environment]::GetFolderPath('LocalApplicationData'))
if ($Local -ine [IO.Path]::GetFullPath($env:LOCALAPPDATA)) { throw 'LocalAppData mismatch.' }
$Parent = Join-Path $Local 'OnyxCore-v100'
$Target = Join-Path $Parent 'Monitoring'
$Sids = @($ExpectedSid,'S-1-5-18','S-1-5-32-544')
$Inherit = [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [Security.AccessControl.InheritanceFlags]::ObjectInherit
function Assert-Plain([string]$Path) {
    $Part = $Path
    while ($true) {
        $Node = Get-Item -LiteralPath $Part -Force
        if ($Node.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Redirected path refused.' }
        if ($Part -eq [IO.Path]::GetPathRoot($Part)) { break }
        $Part = [IO.Path]::GetDirectoryName($Part)
    }
}
function Assert-Acl([string]$Path,[bool]$Directory) {
    Assert-Plain $Path
    $Node = Get-Item -LiteralPath $Path -Force
    if ([bool]$Node.PSIsContainer -ne $Directory) { throw 'Unexpected node type.' }
    $Acl = $Node.GetAccessControl(([Security.AccessControl.AccessControlSections]::Access -bor [Security.AccessControl.AccessControlSections]::Owner))
    if ($Directory -and -not $Acl.AreAccessRulesProtected) { throw 'Directory DACL not protected.' }
    if ($Acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -notin $Sids) { throw 'Unexpected owner.' }
    $Rules = @($Acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))
    $Seen = @()
    foreach ($Rule in $Rules) {
        if ($Rule.IdentityReference.Value -notin $Sids -or
            $Rule.FileSystemRights -ne [Security.AccessControl.FileSystemRights]::FullControl -or
            $Rule.AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow -or
            $Rule.PropagationFlags -ne [Security.AccessControl.PropagationFlags]::None) { throw 'Unexpected access rule.' }
        if ($Directory -and ($Rule.IsInherited -or $Rule.InheritanceFlags -ne $Inherit)) { throw 'Unexpected directory inheritance.' }
        if (-not $Directory -and $Rule.InheritanceFlags -ne [Security.AccessControl.InheritanceFlags]::None) { throw 'Unexpected file inheritance.' }
        $Seen += $Rule.IdentityReference.Value
    }
    if ($Rules.Count -ne 3 -or @($Seen | Select-Object -Unique).Count -ne 3) { throw 'Unexpected ACL inventory.' }
}
Assert-Acl $Parent $true
if ($Initialize) {
    if (Test-Path -LiteralPath $Target) { throw 'Monitoring target exists; initialization refused.' }
    if (@(Get-ChildItem -LiteralPath $Parent -Force -Filter '.Monitoring-stage-*').Count -ne 0) { throw 'Abandoned monitoring stage; inspect before retrying.' }
    $Stage = Join-Path $Parent ('.Monitoring-stage-' + [guid]::NewGuid().ToString('N'))
    if (Test-Path -LiteralPath $Stage) { throw 'Stage collision.' }
    $Dacl = [Security.AccessControl.DirectorySecurity]::new()
    $Dacl.SetAccessRuleProtection($true,$false)
    foreach ($Sid in $Sids) {
        $Dacl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
            [Security.Principal.SecurityIdentifier]::new($Sid),
            [Security.AccessControl.FileSystemRights]::FullControl,
            $Inherit,[Security.AccessControl.PropagationFlags]::None,
            [Security.AccessControl.AccessControlType]::Allow))
    }
    [void][IO.Directory]::CreateDirectory($Stage,$Dacl)
    Assert-Acl $Stage $true
    [IO.Directory]::Move($Stage,$Target)
}
Assert-Acl $Target $true
$Allowed = @('incident-history.sqlite3','incident-history.sqlite3-journal','incident-history.sqlite3-wal','incident-history.sqlite3-shm')
foreach ($Item in @(Get-ChildItem -LiteralPath $Target -Force)) {
    if ($Item.Name -cnotin $Allowed) { throw 'Unexpected monitoring directory inventory.' }
    Assert-Acl $Item.FullName $false
}
Write-Output 'ONYX_V100_STORAGE_OK'
