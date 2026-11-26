# ONYX CORE v1.0.0 M2-S5C - DACL-only Windows inactive installer helper.
# This is a NEW helper. Do not invoke the legacy Set-OnyxV100UserInstallAcl.ps1.
# Fixture scope may be used under an approved OS Temp fixture; User scope is
# reserved for a separately authorized future persistent inactive installation.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidateSet('Harden','Audit')][string]$Mode,
    [Parameter(Mandatory=$true)][ValidateSet('Temp','User')][string]$Scope,
    [Parameter(Mandatory=$true)][string]$Root,
    [Parameter(Mandatory=$true)][string]$ContentPath,
    [switch]$ApproveTempFixture,
    [switch]$ApproveInactiveUser,
    [switch]$ApproveUserDacl
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'Native Windows is required. STOP.'
}
$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$Principal = New-Object Security.Principal.WindowsPrincipal($Identity)
if ($Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Non-elevated Windows user required. STOP.'
}
if (-not [IO.Path]::IsPathRooted($Root) -or -not [IO.Path]::IsPathRooted($ContentPath)) {
    throw 'Absolute paths required. STOP.'
}
$RootPath = [IO.Path]::GetFullPath($Root).TrimEnd('\')
$NodePath = [IO.Path]::GetFullPath($ContentPath).TrimEnd('\')
if ([IO.Path]::GetDirectoryName($NodePath) -ine $RootPath) {
    throw 'Only a direct child of the approved root is allowed. STOP.'
}
$Name = [IO.Path]::GetFileName($NodePath)
if ($Mode -ceq 'Harden') {
    if ($Name -cnotmatch '^\.OnyxCore-v100-staging-[a-zA-Z0-9_-]{8,70}$') {
        throw 'Only fresh inactive staging may be hardened. STOP.'
    }
} elseif ($Scope -ceq 'Temp') {
    if ($Name -cnotmatch '^OnyxCore-v100-Inactive-S5A[a-f0-9]{32}$') {
        throw 'Only a published S5A fixture may be audited. STOP.'
    }
} else {
    if ($Name -cnotmatch '^OnyxCore-v100-Inactive-[a-zA-Z0-9_-]{8,48}$') {
        throw 'Only a versioned inactive user directory may be audited. STOP.'
    }
}
if ($Scope -ceq 'Temp') {
    if (-not $ApproveTempFixture -or $ApproveInactiveUser -or $ApproveUserDacl) {
        throw 'Only Temp fixture approval is permitted. STOP.'
    }
    $Temp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
    if ([IO.Path]::GetDirectoryName($RootPath) -ine $Temp -or
        [IO.Path]::GetFileName($RootPath) -cnotmatch '^OnyxV100-S5A-ACL-[a-f0-9]{32}$') {
        throw 'Temp fixture is not a direct, versioned OS Temp child. STOP.'
    }
    $Marker = Join-Path $RootPath '.s5a-fixture.marker'
    if (-not (Test-Path -LiteralPath $Marker -PathType Leaf) -or
        [IO.File]::ReadAllText($Marker,[Text.Encoding]::ASCII) -cne 'ONYX-V100-S5A-NATIVE-ACL-FIXTURE') {
        throw 'Temp fixture marker invalid. STOP.'
    }
    $Children = @(Get-ChildItem -LiteralPath $RootPath -Force -ErrorAction Stop)
    if ($Children.Count -ne 2 -or
        @(Compare-Object @('.s5a-fixture.marker', $Name) @($Children | ForEach-Object {$_.Name})).Count -ne 0) {
        throw 'Unexpected Temp fixture root contents. STOP.'
    }
} else {
    if (-not ($ApproveInactiveUser -and $ApproveUserDacl) -or $ApproveTempFixture) {
        throw 'Two separate inactive user installation approvals required. STOP.'
    }
    $NativeRoot = [IO.Path]::GetFullPath(
        [Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)).TrimEnd('\')
    $EnvironmentRoot = [IO.Path]::GetFullPath($env:LOCALAPPDATA).TrimEnd('\')
    if ($RootPath -ine $NativeRoot -or $RootPath -ine $EnvironmentRoot) {
        throw 'User-scope root must equal native LocalAppData. STOP.'
    }
}
# Refuse reparse points at every existing ancestor and every installed node.
foreach ($Dir in @($RootPath, $NodePath)) {
    $Part = $Dir
    while ($true) {
        $Item = Get-Item -LiteralPath $Part -Force -ErrorAction Stop
        if ($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "Redirected filesystem component refused: $Part. STOP."
        }
        if ($Part -eq [IO.Path]::GetPathRoot($Part)) { break }
        $Part = [IO.Path]::GetDirectoryName($Part)
    }
}
$Content = Get-Item -LiteralPath $NodePath -Force -ErrorAction Stop
if (-not $Content.PSIsContainer) { throw 'Installation node is not a directory. STOP.' }
$Nodes = @($Content)
$Nodes += @(Get-ChildItem -LiteralPath $NodePath -Recurse -Force -ErrorAction Stop)
if ($Nodes.Count -lt 17 -or $Nodes.Count -gt 80) {
    throw 'Unexpected 17-file installed runtime tree. STOP.'
}
foreach ($Node in $Nodes) {
    if ($Node.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw 'Redirected child node refused. STOP.'
    }
}
$AllowedSids = @($Identity.User.Value, 'S-1-5-18', 'S-1-5-32-544')
function Assert-OnlyApprovedDacl([string]$Path) {
    $Acl = Get-Acl -LiteralPath $Path -ErrorAction Stop
    if (-not $Acl.AreAccessRulesProtected) {
        throw "Inherited DACL on protected node: $Path. STOP."
    }
    $Rules = @($Acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]))
    if ($Rules.Count -ne 3) {
        throw "Unexpected ACE count: $Path. STOP."
    }
    $Seen = @()
    foreach ($Rule in $Rules) {
        $Sid = $Rule.IdentityReference.Value
        if ($Rule.IsInherited -or $Sid -notin $AllowedSids -or
            $Rule.AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow -or
            (($Rule.FileSystemRights -band [Security.AccessControl.FileSystemRights]::FullControl) -ne
                [Security.AccessControl.FileSystemRights]::FullControl)) {
            throw "Unexpected access rule: $Path. STOP."
        }
        $Seen += $Sid
    }
    if (@(Compare-Object $AllowedSids $Seen).Count -ne 0) {
        throw "Approved identities mismatch: $Path. STOP."
    }
}
function Write-CompleteDacl([string]$Path, [bool]$Directory) {
    # Fresh DACL-only security descriptors; do not roundtrip Get-Acl/Set-Acl.
    if ($Directory) {
        $Acl = [Security.AccessControl.DirectorySecurity]::new()
        $Inheritance = [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
            [Security.AccessControl.InheritanceFlags]::ObjectInherit
    } else {
        $Acl = [Security.AccessControl.FileSecurity]::new()
        $Inheritance = [Security.AccessControl.InheritanceFlags]::None
    }
    $Acl.SetAccessRuleProtection($true, $false)
    foreach ($Sid in $AllowedSids) {
        $Rule = [Security.AccessControl.FileSystemAccessRule]::new(
            [Security.Principal.SecurityIdentifier]::new($Sid),
            [Security.AccessControl.FileSystemRights]::FullControl,
            $Inheritance,
            [Security.AccessControl.PropagationFlags]::None,
            [Security.AccessControl.AccessControlType]::Allow)
        $Acl.AddAccessRule($Rule)
    }
    if ($Directory) {
        [IO.Directory]::SetAccessControl($Path, $Acl)
    } else {
        [IO.File]::SetAccessControl($Path, $Acl)
    }
}
if ($Mode -ceq 'Harden') {
    foreach ($Node in @($Nodes | Sort-Object @{Expression={$_.FullName.Length};Descending=$true})) {
        try {
            Write-CompleteDacl $Node.FullName ([bool]$Node.PSIsContainer)
            Assert-OnlyApprovedDacl $Node.FullName
        } catch {
            throw "Safe DACL write failed: $($Node.FullName): $($_.Exception.Message)"
        }
    }
}
foreach ($Node in $Nodes) { Assert-OnlyApprovedDacl $Node.FullName }
$Again = @(Get-ChildItem -LiteralPath $NodePath -Recurse -Force -ErrorAction Stop)
if ($Again.Count -ne ($Nodes.Count - 1)) {
    throw 'Post-hardening tree traversal failed. STOP.'
}
Write-Output 'PASS: DACL-only runtime hardening/audit verified.'
