# ONYX CORE v1.0.0 M2-S5A-R3 - Windows OS Temp DACL-only fixture ONLY.
# Never call this against a real user installation or a production path.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateSet('Harden','Audit')][string]$Mode,
    [Parameter(Mandatory = $true)][string]$FixtureRoot,
    [Parameter(Mandatory = $true)][string]$ContentPath,
    [Parameter(Mandatory = $true)][switch]$ApproveTempFixture
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (-not $ApproveTempFixture) { throw 'Explicit Temp ACL fixture approval is required. STOP.' }
if (-not [Environment]::OSVersion.Platform.Equals([PlatformID]::Win32NT)) {
    throw 'Native Windows host required. STOP.'
}
$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$Principal = New-Object Security.Principal.WindowsPrincipal($Identity)
if ($Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Non-elevated Windows user required. STOP.'
}
$Temp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
$Root = [IO.Path]::GetFullPath($FixtureRoot).TrimEnd('\')
$Path = [IO.Path]::GetFullPath($ContentPath).TrimEnd('\')
if (-not [IO.Path]::IsPathRooted($FixtureRoot) -or -not [IO.Path]::IsPathRooted($ContentPath) -or
    [IO.Path]::GetDirectoryName($Root) -ine $Temp -or
    [IO.Path]::GetFileName($Root) -cnotmatch '^OnyxV100-S5A-ACL-[a-f0-9]{32}$' -or
    [IO.Path]::GetDirectoryName($Path) -ine $Root) {
    throw 'Path outside one direct OS Temp fixture refused. STOP.'
}
$Name = [IO.Path]::GetFileName($Path)
if ($Mode -ceq 'Harden') {
    if ($Name -cnotmatch '^\.OnyxCore-v100-staging-[a-zA-Z0-9_-]{8,70}$') {
        throw 'Only the temporary installer STAGING folder may be hardened. STOP.'
    }
} else {
    if ($Name -cnotmatch '^OnyxCore-v100-Inactive-S5A[a-f0-9]{32}$') {
        throw 'Only the published S5A Temp fixture may be audited. STOP.'
    }
}
foreach ($Dir in @($Temp,$Root,$Path)) {
    $Item = Get-Item -LiteralPath $Dir -Force -ErrorAction Stop
    if (-not $Item.PSIsContainer -or ($Item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Missing, redirected, or non-directory fixture component. STOP.'
    }
}
$MarkerFile = Join-Path $Root '.s5a-fixture.marker'
if (-not (Test-Path -LiteralPath $MarkerFile -PathType Leaf) -or
    [IO.File]::ReadAllText($MarkerFile, [Text.Encoding]::ASCII) -cne
        'ONYX-V100-S5A-NATIVE-ACL-FIXTURE') {
    throw 'Unique Temp fixture marker missing. STOP.'
}
$Children = @(Get-ChildItem -LiteralPath $Root -Force -ErrorAction Stop)
if ($Children.Count -ne 2 -or
    @(Compare-Object @('.s5a-fixture.marker', $Name) @($Children | ForEach-Object { $_.Name })).Count -ne 0) {
    throw 'Unexpected Temp fixture root contents. STOP.'
}
$Nodes = @(Get-Item -LiteralPath $Path -Force)
$Nodes += @(Get-ChildItem -LiteralPath $Path -Recurse -Force -ErrorAction Stop)
if ($Nodes.Count -lt 17 -or $Nodes.Count -gt 80) {
    throw 'Unexpected installed fixture inventory. STOP.'
}
foreach ($Node in $Nodes) {
    if ($Node.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw 'Redirected fixture node refused. STOP.'
    }
}
$Sid = $Identity.User.Value
$Allow = @($Sid, 'S-1-5-18', 'S-1-5-32-544')
# The previous two-step icacls hardening removed inherited access BEFORE
# granting replacement access. On SQUALL it locked the installer out.
# Apply a fresh DACL-only descriptor per node using .NET SetAccessControl.
# Files/children first, root last; each node is re-audited after the root.
function Assert-SafeAcl([string]$NodePath) {
    $Acl = Get-Acl -LiteralPath $NodePath -ErrorAction Stop
    if (-not $Acl.AreAccessRulesProtected) {
        throw "Inheritance still enabled on fixture node: $NodePath. STOP."
    }
    $Rules = @($Acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))
    if ($Rules.Count -ne 3) {
        throw "Expected 3 explicit ACEs, found $($Rules.Count): $NodePath. STOP."
    }
    $Found = @()
    foreach ($Rule in $Rules) {
        $RuleSid = $Rule.IdentityReference.Value
        if ($Rule.IsInherited -or
            $Rule.AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow -or
            $RuleSid -notin $Allow -or
            (($Rule.FileSystemRights -band [Security.AccessControl.FileSystemRights]::FullControl) -ne
                [Security.AccessControl.FileSystemRights]::FullControl)) {
            throw "Unexpected ACE or insufficient rights on fixture node: $NodePath. STOP."
        }
        $Found += $RuleSid
    }
    if (@(Compare-Object -ReferenceObject $Allow -DifferenceObject $Found).Count -ne 0) {
        throw "Wrong identities on fixture node: $NodePath. STOP."
    }
}
function Set-SafeAcl([string]$NodePath, [bool]$IsDirectory) {
    # IMPORTANT: Never round-trip Get-Acl through Set-Acl. That can carry
    # owner/group/SACL metadata and trigger SeSecurityPrivilege on some trees.
    # This fresh descriptor has ONLY the replacement DACL; owner and audit
    # settings are neither read nor modified by this operation.
    if ($IsDirectory) {
        $Acl = [Security.AccessControl.DirectorySecurity]::new()
        $Inheritance = [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
            [Security.AccessControl.InheritanceFlags]::ObjectInherit
    } else {
        $Acl = [Security.AccessControl.FileSecurity]::new()
        $Inheritance = [Security.AccessControl.InheritanceFlags]::None
    }
    $Acl.SetAccessRuleProtection($true,$false)
    foreach ($AllowedSid in $Allow) {
        $Rule = [Security.AccessControl.FileSystemAccessRule]::new(
            [Security.Principal.SecurityIdentifier]::new($AllowedSid),
            [Security.AccessControl.FileSystemRights]::FullControl,
            $Inheritance,
            [Security.AccessControl.PropagationFlags]::None,
            [Security.AccessControl.AccessControlType]::Allow
        )
        $Acl.AddAccessRule($Rule)
    }
    # .NET persists only the modified DACL on the matching filesystem object.
    # Do not request security-audit privilege and do not alter the SACL.
    if ($IsDirectory) {
        [IO.Directory]::SetAccessControl($NodePath,$Acl)
    } else {
        [IO.File]::SetAccessControl($NodePath,$Acl)
    }
}
if ($Mode -ceq 'Harden') {
    # Every node's complete DACL is built before changing that node.
    # Sorting deepest-first guarantees the installation root changes last.
    $Order = @($Nodes | Sort-Object @{ Expression = { $_.FullName.Length }; Descending = $true })
    foreach ($Node in $Order) {
        try {
            Set-SafeAcl $Node.FullName ([bool]$Node.PSIsContainer)
            Assert-SafeAcl $Node.FullName
        } catch {
            throw "Safe DACL application failed on fixture node $($Node.FullName): $($_.Exception.Message)"
        }
    }
}
foreach ($Node in $Nodes) {
    Assert-SafeAcl $Node.FullName
}
# Explicitly verify the current user can still traverse/read the entire tree
# after the parent DACL has been published. Never read credentials here.
$Recheck = @(Get-ChildItem -LiteralPath $Path -Recurse -Force -ErrorAction Stop)
if ($Recheck.Count -ne ($Nodes.Count - 1)) {
    throw 'Unable to enumerate all fixture nodes after hardening. STOP.'
}
if ($Mode -ceq 'Harden') {
    Write-Output 'PASS: Native Temp fixture DACL restricted and audited.'
} else {
    Write-Output 'PASS: Published Temp fixture DACL verified read-only.'
}
