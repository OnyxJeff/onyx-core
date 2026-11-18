# ONYX CORE v0.9.0: supervised rehearsal, optional separately approved boot promotion.
# PREVIEW by default. Live phases require an independent, explicit operator approval.
# No Pi access, DB access, Git writes, or protected v0.8.0 changes.
[CmdletBinding()]
param(
    [ValidateSet('Preview','PreviewBoot','Escrow','Quiesce','StartCandidate','PromoteBoot','StopCandidate','RestoreLegacy')]
    [string]$Phase='Preview',
    [string]$ExpectedCommit='',
    [switch]$ApproveLiveWindowsChanges,
    [switch]$ConfirmCandidatePiActive,
    [switch]$ConfirmLegacyPiRestored,
    [switch]$ConfirmPiBootReady
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
if ($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1) { throw 'PowerShell 5.1 required.' }
if ($Phase -in @('Preview','PreviewBoot')) {
    if ($ApproveLiveWindowsChanges -or $ConfirmCandidatePiActive -or $ConfirmLegacyPiRestored -or $ConfirmPiBootReady) { throw 'Approval switches are invalid in Preview.' }
    if ($Phase -eq 'PreviewBoot' -and $ExpectedCommit -notmatch '^[a-f0-9]{40}$') { throw 'Frozen candidate SHA required for boot audit. STOP.' }
} else {
    if (-not $ApproveLiveWindowsChanges) { throw 'A separately approved live Windows operation is required. STOP.' }
    if ($ExpectedCommit -notmatch '^[a-f0-9]{40}$') { throw 'Frozen candidate commit required. STOP.' }
}
if ($ConfirmCandidatePiActive -and $Phase -ne 'StartCandidate') { throw 'Pi candidate confirmation valid only for StartCandidate.' }
if ($ConfirmPiBootReady -and $Phase -ne 'PromoteBoot') { throw 'Pi durable boot confirmation only valid for PromoteBoot.' }
if ($Phase -eq 'PromoteBoot' -and -not $ConfirmPiBootReady) { throw 'Pi must have passed its durable startup promotion before Windows. STOP.' }
if ($ConfirmLegacyPiRestored -and $Phase -ne 'RestoreLegacy') { throw 'Legacy Pi confirmation valid only for RestoreLegacy.' }
if ($Phase -eq 'StartCandidate' -and -not $ConfirmCandidatePiActive) { throw 'Candidate Pi must be verified active separately. STOP.' }
if ($Phase -eq 'RestoreLegacy' -and -not $ConfirmLegacyPiRestored) { throw 'Legacy Pi must be restored before starting Windows legacy tasks. STOP.' }

$Production='D:\github_repos\onyx-core'
$ProductionHead='06ec81582791fc797f74ad294195d68b2023cb66'
$Candidate='C:\Program Files\OnyxCore\v0.9.0'
$Escrow=Join-Path $env:LOCALAPPDATA 'OnyxCore-v090-Cutover-Escrow'
$StatePath=Join-Path $Escrow 'state.json'
$LegacyCollector='ONYX CORE - Telemetry Collector'
$LegacyGateway='ONYX CORE - Local Gateway'
$NewCollector='ONYX CORE v0.9 - Telemetry Collector (Candidate)'
$NewGateway='ONYX CORE v0.9 - Local Gateway (Candidate)'
$LegacyCollectorScript=Join-Path $Production 'windows\collector\Send-OnyxTelemetry.ps1'
$LegacyLauncherScript=Join-Path $Production 'windows\collector\Launch-OnyxTelemetry.vbs'
$LegacyGatewayScript=Join-Path $Production 'windows\gateway\OnyxGateway.py'
$NewCollectorScript=Join-Path $Candidate 'windows\collector\Send-OnyxTelemetry.ps1'
$NewLauncherScript=Join-Path $Candidate 'windows\collector\Launch-OnyxTelemetry.vbs'
$NewGatewayScript=Join-Path $Candidate 'windows\gateway\OnyxGateway.py'
$Python='C:\Python313\python.exe'
$Pythonw='C:\Python313\pythonw.exe'
$Wscript=Join-Path $env:WINDIR 'System32\wscript.exe'
$User=[Security.Principal.WindowsIdentity]::GetCurrent().Name
$LegacyNames=@($LegacyCollector,$LegacyGateway)
$NewNames=@($NewCollector,$NewGateway)

function Assert-OriginalSource {
    $head=& git -C $Production rev-parse HEAD
    if ($LASTEXITCODE -ne 0 -or $head -cne $ProductionHead) { throw 'Original production Git commit changed. STOP.' }
    foreach ($path in @($LegacyCollectorScript,$LegacyLauncherScript,$LegacyGatewayScript)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw 'Legacy startup file missing. STOP.' }
    }
}
function Get-TaskStrict([string]$Name,[string]$Needle) {
    $t=Get-ScheduledTask -TaskName $Name -ErrorAction Stop
    if ($null -eq $t -or @($t.Actions).Count -ne 1) { throw 'Task missing or has multiple actions. STOP.' }
    $a=$t.Actions[0]
    $command=([string]$a.Execute)+' '+([string]$a.Arguments)+' '+([string]$a.WorkingDirectory)
    if ($command.IndexOf($Needle,[StringComparison]::OrdinalIgnoreCase) -lt 0) { throw 'Task reference mismatch. STOP.' }
    if ([string]$t.Principal.LogonType -ne 'Interactive' -or [string]$t.Principal.RunLevel -ne 'Limited') { throw 'Task principal changed. STOP.' }
    return $t
}
function Get-MatchingProcesses([string]$Root,[int[]]$AllowedOrphanCollectorPIDs=@()) {
    $scripts=@(
        @{role='launcher'; name='wscript.exe'; path=(Join-Path $Root 'windows\collector\Launch-OnyxTelemetry.vbs')},
        @{role='collector'; name='powershell.exe'; path=(Join-Path $Root 'windows\collector\Send-OnyxTelemetry.ps1')},
        @{role='gateway'; name='pythonw.exe'; path=(Join-Path $Root 'windows\gateway\OnyxGateway.py')}
    )
    $all=@(Get-CimInstance Win32_Process -ErrorAction Stop)
    $matched=@()
    foreach ($p in $all) {
        $cmd=[string]$p.CommandLine
        if (-not $cmd) { continue }
        foreach ($s in $scripts) {
            if ($cmd.IndexOf([string]$s.path,[StringComparison]::OrdinalIgnoreCase) -ge 0) {
                if ([string]$p.Name -ine [string]$s.name) { throw 'Unexpected executable runs ONYX script. STOP.' }
                $matched+= [pscustomobject]@{Role=$s.role; Id=[int]$p.ProcessId; Parent=[int]$p.ParentProcessId; Name=[string]$p.Name}
            }
        }
    }
    $launchers=@($matched | Where-Object { $_.Role -eq 'launcher' })
    foreach ($child in @($matched | Where-Object { $_.Role -eq 'collector' })) {
        if (@($launchers | Where-Object { $_.Id -eq $child.Parent }).Count -ne 1 -and
            $child.Id -notin $AllowedOrphanCollectorPIDs) {
            throw 'Detached collector without verified ONYX launcher. STOP.'
        }
    }
    foreach ($r in @('collector','gateway','launcher')) {
        if (@($matched | Where-Object { $_.Role -eq $r }).Count -gt 1) { throw 'Multiple matching processes found. STOP.' }
    }
    return @($matched)
}
function Assert-Port([string]$Root,[bool]$MustBeFree) {
    $list=@(Get-NetTCPConnection -LocalPort 18766 -State Listen -ErrorAction SilentlyContinue)
    if ($MustBeFree) {
        if ($list.Count -ne 0) { throw 'Gateway port 18766 remains occupied. STOP.' }
        return
    }
    if ($list.Count -ne 1 -or [string]$list[0].LocalAddress -ne '127.0.0.1') { throw 'Unexpected gateway listener count/address. STOP.' }
    $gateways=@(Get-MatchingProcesses $Root | Where-Object { $_.Role -eq 'gateway' })
    if ($gateways.Count -ne 1 -or $gateways[0].Id -ne $list[0].OwningProcess) { throw 'Gateway listener process identity mismatch. STOP.' }
}
function Assert-CandidateInstall {
    $planner=Join-Path $Candidate 'tools\installation\common\onyx_runtime_plan.py'
    foreach ($file in @($planner,$NewCollectorScript,$NewLauncherScript,$NewGatewayScript,$Python,$Pythonw,$Wscript)) {
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw 'Versioned candidate component missing. STOP.' }
    }
    $lines=@(& $Python -I -B $planner --installed-root $Candidate --platform windows --expected-commit $ExpectedCommit 2>&1)
    if ($LASTEXITCODE -ne 0 -or $lines.Count -ne 1) { throw 'Candidate installed hashes/receipt invalid. STOP.' }
    $doc=$lines[0] | ConvertFrom-Json
    if ($doc.operation -ne 'READ_ONLY_ACTIVATION_PLAN' -or $doc.activated -ne $false -or $doc.audit.source_commit -cne $ExpectedCommit) {
        throw 'Candidate runtime provenance mismatch. STOP.'
    }
}
function Assert-EscrowPrivate {
    if (-not (Test-Path -LiteralPath $Escrow -PathType Container)) { throw 'Private rollback escrow missing. STOP.' }
    $acl=Get-Acl -LiteralPath $Escrow
    foreach ($ace in $acl.Access) {
        if ($ace.AccessControlType -eq 'Allow') {
            $sid=[string]$ace.IdentityReference
            if ($sid -match '(^|\\)(Everyone|Users|Authenticated Users|Guests)$') { throw 'Escrow permissions too broad. STOP.' }
        }
    }
}
function Get-State {
    Assert-EscrowPrivate
    if (-not (Test-Path -LiteralPath $StatePath -PathType Leaf)) { throw 'Escrow state missing. STOP.' }
    $d=Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
    if ($d.schema -ne 1 -or $d.commit -cne $ExpectedCommit -or $d.production -cne $ProductionHead) { throw 'Escrow identity mismatch. STOP.' }
    if (@($d.tasks).Count -ne 2) { throw 'Escrow must contain exactly two original tasks. STOP.' }
    foreach ($row in @($d.tasks)) {
        if ($row.name -notin $LegacyNames -or $row.file -notin @('legacy-collector.xml','legacy-gateway.xml')) { throw 'Unexpected escrow item. STOP.' }
        $file=Join-Path $Escrow $row.file
        if (-not (Test-Path -LiteralPath $file -PathType Leaf) -or
            (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ine $row.sha256) { throw 'Original task XML escrow integrity failure. STOP.' }
    }
    return $d
}
function Set-State($doc,[string]$Next) {
    $doc.phase=$Next
    $text=$doc | ConvertTo-Json -Depth 8
    $temporary=$StatePath+'.tmp'
    if (Test-Path -LiteralPath $temporary) { throw 'Escrow temporary file exists. STOP.' }
    [IO.File]::WriteAllText($temporary,$text,(New-Object Text.UTF8Encoding($false)))
    if (Test-Path -LiteralPath $StatePath) {
        [IO.File]::Replace($temporary,$StatePath,($StatePath+'.previous'))
    } else {
        [IO.File]::Move($temporary,$StatePath)
    }
}
function Assert-NoOtherCandidate {
    foreach ($name in $NewNames) {
        if ($null -ne (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue)) { throw 'Candidate task already registered. STOP.' }
    }
}
function Assert-ExpectedCandidateTask([string]$Name,[string]$Script,[string]$Executable) {
    $task=Get-ScheduledTask -TaskName $Name -ErrorAction Stop
    if ($null -eq $task -or @($task.Actions).Count -ne 1) { throw 'Candidate task missing/multiple actions. STOP.' }
    $action=$task.Actions[0]
    $line=([string]$action.Execute)+' '+([string]$action.Arguments)
    if ($line.IndexOf($Script,[StringComparison]::OrdinalIgnoreCase) -lt 0 -or
        [string]$action.Execute -ine $Executable -or
        [string]$task.Principal.LogonType -ne 'Interactive' -or
        [string]$task.Principal.RunLevel -ne 'Limited') { throw 'Candidate action/principal changed. STOP.' }
    $triggers=@($task.Triggers)
    if ($triggers.Count -gt 1) { throw 'Unexpected candidate trigger count. STOP.' }
    if ($triggers.Count -eq 1) {
        if ([string]$triggers[0].CimClass.CimClassName -ne 'MSFT_TaskLogonTrigger') {
            throw 'Unexpected candidate trigger type. STOP.'
        }
        $userId=[string]$triggers[0].UserId
        $sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
        if ($userId -ine $User -and $userId -ine $sid) {
            throw 'Unexpected candidate trigger principal. STOP.'
        }
    }
    return $task
}
function Stop-ExactProcesses([string]$Root,[object[]]$BeforeStop) {
    $allowed=@($BeforeStop | Where-Object { $_.Role -eq 'collector' } | ForEach-Object { [int]$_.Id })
    # Stop scheduled tasks first. Only verified, freshly enumerated processes are terminated.
    for ($attempt=0; $attempt -lt 6; $attempt++) {
        $matches=@(Get-MatchingProcesses $Root $allowed)
        if ($matches.Count -eq 0) { return }
        if ($attempt -lt 2) { Start-Sleep -Seconds 2; continue }
        foreach ($p in $matches) {
            # Re-check identity to avoid using cached PIDs after process turnover.
            $fresh=@(Get-MatchingProcesses $Root $allowed | Where-Object { $_.Id -eq $p.Id -and $_.Role -eq $p.Role })
            if ($fresh.Count -ne 1 -or $fresh[0].Parent -ne $p.Parent) { throw 'Process changed before stop. STOP.' }
            Stop-Process -Id $p.Id -ErrorAction Stop
        }
        Start-Sleep -Seconds 1
    }
    if (@(Get-MatchingProcesses $Root $allowed).Count -ne 0) { throw 'ONYX processes still running. STOP.' }
}

Assert-OriginalSource
if ($Phase -eq 'Preview') {
    $null=Get-TaskStrict $LegacyCollector $LegacyLauncherScript
    $null=Get-TaskStrict $LegacyGateway $LegacyGatewayScript
    $legacy=@(Get-MatchingProcesses $Production)
    $candidate=@(Get-MatchingProcesses $Candidate)
    # Preview must validate topology, not merely print raw counts. It is still read-only.
    foreach ($role in @('launcher','collector','gateway')) {
        if (@($legacy | Where-Object { $_.Role -eq $role }).Count -ne 1) {
            throw ('Legacy ' + $role + ' process is missing or duplicated. STOP.')
        }
    }
    if ($legacy.Count -ne 3 -or $candidate.Count -ne 0) {
        throw 'Unexpected legacy or candidate runtime processes. STOP.'
    }
    # Recheck the live listener owner against the verified production gateway PID.
    Assert-Port $Production $false
    $ports=@(Get-NetTCPConnection -LocalPort 18766 -State Listen -ErrorAction Stop)
    [pscustomobject]@{phase='PREVIEW_ONLY';legacy_count=$legacy.Count;candidate_count=$candidate.Count;port_18766_owners=@($ports | ForEach-Object { $_.OwningProcess });escrow_exists=(Test-Path -LiteralPath $StatePath);topology_verified=$true;writes=$false} | ConvertTo-Json -Compress
    return
}
if ($Phase -eq 'PreviewBoot') {
    # Read-only post-boot attestation. A successful pre-reboot preview is NOT
    # equivalent to having exercised Windows startup and logon triggers.
    Assert-CandidateInstall
    $journal=Get-State
    if ($journal.phase -ne 'candidate-boot-configured') { throw 'Candidate not promoted to boot startup. STOP.' }
    foreach ($name in $LegacyNames) {
        $task=Get-ScheduledTask -TaskName $name -ErrorAction Stop
        if ([string]$task.State -ne 'Disabled') { throw 'Legacy autostart re-enabled. STOP.' }
    }
    foreach ($pair in @(
        @{Name=$NewCollector;Script=$NewLauncherScript;Exe=$Wscript},
        @{Name=$NewGateway;Script=$NewGatewayScript;Exe=$Pythonw}
    )) {
        $task=Assert-ExpectedCandidateTask $pair.Name $pair.Script $pair.Exe
        if (@($task.Triggers).Count -ne 1 -or [string]$task.State -eq 'Disabled') {
            throw 'Candidate startup trigger not enabled. STOP.'
        }
    }
    if (@(Get-MatchingProcesses $Production).Count -ne 0) { throw 'Legacy ONYX process exists. STOP.' }
    $running=@(Get-MatchingProcesses $Candidate)
    foreach ($role in @('launcher','collector','gateway')) {
        if (@($running | Where-Object { $_.Role -eq $role }).Count -ne 1) {
            throw ('Candidate '+$role+' process not uniquely running. STOP.')
        }
    }
    Assert-Port $Candidate $false
    $boot=([datetime](Get-CimInstance Win32_OperatingSystem -ErrorAction Stop).LastBootUpTime).ToUniversalTime()
    $promoted=([datetime]$journal.promoted_utc).ToUniversalTime()
    $rebooted=($boot -gt $promoted)
    [pscustomobject]@{phase='POST_BOOT_READ_ONLY_AUDIT';candidate_running=$true;candidate_startup_configured=$true;legacy_excluded=$true;reboot_observed=$rebooted;writes=$false} | ConvertTo-Json -Compress
    return
}
# LIVE phases are only intended after frozen package verification, native review,
# and the operator's separate explicit authorization for this specific phase.
Assert-CandidateInstall
$null=Get-TaskStrict $LegacyCollector $LegacyLauncherScript
    $null=Get-TaskStrict $LegacyGateway $LegacyGatewayScript
if ($Phase -eq 'Escrow') {
    Assert-NoOtherCandidate
    if (Test-Path -LiteralPath $Escrow) { throw 'Rollback escrow already exists; no overwrite. STOP.' }
    $null=New-Item -Path $Escrow -ItemType Directory -ErrorAction Stop
    $acl=New-Object System.Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true,$false)
    foreach ($id in @($User,'NT AUTHORITY\SYSTEM','BUILTIN\Administrators')) {
        $rule=New-Object -TypeName System.Security.AccessControl.FileSystemAccessRule -ArgumentList @($id,'FullControl','ContainerInherit,ObjectInherit','None','Allow')
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $Escrow -AclObject $acl
    Assert-EscrowPrivate
    $items=@()
    foreach ($name in $LegacyNames) {
        $file=if ($name -eq $LegacyCollector) { 'legacy-collector.xml' } else { 'legacy-gateway.xml' }
        $xml=Export-ScheduledTask -TaskName $name -ErrorAction Stop
        [IO.File]::WriteAllText((Join-Path $Escrow $file),$xml,(New-Object Text.UTF8Encoding($false)))
        $items+=@{name=$name;file=$file;sha256=(Get-FileHash -LiteralPath (Join-Path $Escrow $file) -Algorithm SHA256).Hash}
    }
    $record=[pscustomobject]@{schema=1;phase='escrowed';commit=$ExpectedCommit;production=$ProductionHead;tasks=$items}
    Set-State $record 'escrowed'
    Write-Host 'PASS: original task XML privately escrowed. Tasks untouched. DO NOT SHARE XML.'
    return
}
$record=Get-State
if ($Phase -eq 'Quiesce') {
    if ($record.phase -ne 'escrowed') { throw 'Wrong phase for Quiesce. STOP.' }
    Assert-NoOtherCandidate
    Assert-Port $Production $false
    foreach ($row in @($record.tasks)) {
        $actual=Export-ScheduledTask -TaskName $row.name -ErrorAction Stop
        $actualBytes=[Text.Encoding]::UTF8.GetBytes($actual)
        $sha=[Security.Cryptography.SHA256]::Create()
        try { $hex=([BitConverter]::ToString($sha.ComputeHash($actualBytes))).Replace('-','') } finally { $sha.Dispose() }
        if ($hex -ine $row.sha256) { throw 'Original task XML changed since escrow. STOP.' }
    }
    $snapshot=@(Get-MatchingProcesses $Production)
    Set-State $record 'quiescing'
    foreach ($name in $LegacyNames) { Disable-ScheduledTask -TaskName $name -ErrorAction Stop | Out-Null }
    foreach ($name in $LegacyNames) { Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue }
    Stop-ExactProcesses $Production $snapshot
    Assert-Port $Production $true
    Set-State $record 'legacy-quiesced'
    Write-Host 'PASS: original tasks disabled; original ONYX processes exited; 18766 free.'
    return
}
if ($Phase -eq 'StartCandidate') {
    if ($record.phase -ne 'legacy-quiesced') { throw 'Wrong phase for StartCandidate. STOP.' }
    foreach ($name in $LegacyNames) {
        $t=Get-ScheduledTask -TaskName $name -ErrorAction Stop
        if ([string]$t.State -ne 'Disabled') { throw 'Legacy task not disabled. STOP.' }
    }
    if (@(Get-MatchingProcesses $Production).Count -gt 0) { throw 'Legacy process found. STOP.' }
    Assert-Port $Production $true
    Assert-NoOtherCandidate
    if (-not (Test-Path -LiteralPath (Join-Path $env:LOCALAPPDATA 'OnyxCore\collector-token.dpapi') -PathType Leaf)) { throw 'Saved DPAPI token missing. STOP.' }
    $dashboard=Join-Path $Candidate 'windows\gateway\gateway-dashboard.html'
    $principal=New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited
    # NO logon triggers: rehearsal tasks cannot auto-start at the next logon/reboot.
    $settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([timespan]::Zero)
    $ca=New-ScheduledTaskAction -Execute $Wscript -Argument ('"{0}"' -f $NewLauncherScript) -WorkingDirectory (Split-Path $NewLauncherScript)
    $ga=New-ScheduledTaskAction -Execute $Pythonw -Argument ('-I -B "{0}" --dashboard "{1}" --receiver svr-onyxcore.local --port 18766 --load-dpapi' -f $NewGatewayScript,$dashboard) -WorkingDirectory (Split-Path $NewGatewayScript)
    $c=New-ScheduledTask -Action $ca -Principal $principal -Settings $settings
    $g=New-ScheduledTask -Action $ga -Principal $principal -Settings $settings
    Register-ScheduledTask -TaskName $NewCollector -InputObject $c -ErrorAction Stop | Out-Null
    Register-ScheduledTask -TaskName $NewGateway -InputObject $g -ErrorAction Stop | Out-Null
    # Mark before the first start; if activation fails, the operator has a rollback route.
    Set-State $record 'candidate-registration-created'
    Start-ScheduledTask -TaskName $NewGateway -ErrorAction Stop
    Start-ScheduledTask -TaskName $NewCollector -ErrorAction Stop
    $ok=$false
    for ($i=0; $i -lt 12; $i++) {
        Start-Sleep -Seconds 2
        try {
            $new=@(Get-MatchingProcesses $Candidate)
            Assert-Port $Candidate $false
            if (@($new | Where-Object { $_.Role -eq 'collector' }).Count -eq 1) { $ok=$true; break }
        } catch { }
    }
    if (-not $ok) { throw 'Candidate startup not verified. Leave legacy disabled; invoke approved rollback. STOP.' }
    Set-State $record 'candidate-running-rehearsal'
    Write-Host 'PASS: one candidate gateway on 127.0.0.1:18766 and one collector process.'
    Write-Host 'REHEARSAL ONLY: candidate tasks have NO logon triggers; reboot durability NOT validated.'
    return
}
if ($Phase -eq 'PromoteBoot') {
    if ($record.phase -ne 'candidate-running-rehearsal') { throw 'Boot promotion requires verified rehearsal. STOP.' }
    foreach ($name in $LegacyNames) {
        $legacy=Get-ScheduledTask -TaskName $name -ErrorAction Stop
        if ([string]$legacy.State -ne 'Disabled') { throw 'Legacy startup not disabled. STOP.' }
    }
    if (@(Get-MatchingProcesses $Production).Count -ne 0) { throw 'Legacy process still present. STOP.' }
    $current=@(Get-MatchingProcesses $Candidate)
    foreach ($role in @('launcher','collector','gateway')) {
        if (@($current | Where-Object { $_.Role -eq $role }).Count -ne 1) {
            throw ('Candidate '+$role+' not uniquely running. STOP.')
        }
    }
    Assert-Port $Candidate $false
    foreach ($pair in @(
        @{Name=$NewCollector;Script=$NewLauncherScript;Exe=$Wscript},
        @{Name=$NewGateway;Script=$NewGatewayScript;Exe=$Pythonw}
    )) {
        $task=Assert-ExpectedCandidateTask $pair.Name $pair.Script $pair.Exe
        if (@($task.Triggers).Count -ne 0 -or [string]$task.State -eq 'Disabled') {
            throw 'Candidate task not manual-only and enabled. STOP.'
        }
    }
    # Intent is escrowed before changing either trigger. A partial promotion
    # can be quiesced by StopCandidate, leaving legacy autostart disabled.
    Set-State $record 'boot-promoting'
    $trigger=New-ScheduledTaskTrigger -AtLogOn -User $User
    foreach ($name in $NewNames) {
        Set-ScheduledTask -TaskName $name -Trigger $trigger -ErrorAction Stop | Out-Null
    }
    foreach ($pair in @(
        @{Name=$NewCollector;Script=$NewLauncherScript;Exe=$Wscript},
        @{Name=$NewGateway;Script=$NewGatewayScript;Exe=$Pythonw}
    )) {
        $task=Assert-ExpectedCandidateTask $pair.Name $pair.Script $pair.Exe
        if (@($task.Triggers).Count -ne 1 -or [string]$task.State -eq 'Disabled') {
            throw 'Candidate logon startup was not fully registered. STOP.'
        }
    }
    if (@(Get-MatchingProcesses $Production).Count -ne 0) { throw 'Legacy restarted during promotion. STOP.' }
    Assert-Port $Candidate $false
    $record | Add-Member -NotePropertyName promoted_utc -NotePropertyValue ((Get-Date).ToUniversalTime().ToString('o')) -Force
    Set-State $record 'candidate-boot-configured'
    Write-Host 'PASS: candidate logon triggers configured; original tasks remain disabled.'
    Write-Host 'PENDING: native reboot/logon plus authenticated telemetry/overlay and rollback acceptance.'
    return
}
if ($Phase -eq 'StopCandidate') {
    if ($record.phase -notin @('legacy-quiesced','candidate-registration-created','candidate-running-rehearsal','boot-promoting','candidate-boot-configured')) { throw 'Unexpected rollback phase. STOP.' }
     $snapshot=@(Get-MatchingProcesses $Candidate)
    foreach ($name in $NewNames) {
        $task=Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if ($null -ne $task) {
            $source=if ($name -eq $NewCollector) { $NewLauncherScript } else { $NewGatewayScript }
            $exe=if ($name -eq $NewCollector) { $Wscript } else { $Pythonw }
            $null=Assert-ExpectedCandidateTask $name $source $exe
            Disable-ScheduledTask -TaskName $name -ErrorAction Stop | Out-Null
            Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        }
    }
    Stop-ExactProcesses $Candidate $snapshot
    Assert-Port $Candidate $true
    # Keep candidate task definitions for evidence; disabled and NO logon triggers.
    # Pi should now be rolled back BEFORE re-enabling the original collector.
    # Candidate tasks retain their triggers if promoted, but remain DISABLED.
    # Never re-enable them during rollback; legacy owns the next logon.
    Set-State $record 'candidate-quiesced'
    Write-Host 'PASS: Windows candidate stopped; 18766 free. Restore Pi legacy next.'
    return
}
if ($Phase -eq 'RestoreLegacy') {
    if ($record.phase -notin @('candidate-quiesced','quiescing')) { throw 'StopCandidate is required before restoring legacy tasks. STOP.' }
    if (@(Get-MatchingProcesses $Candidate).Count -gt 0) { throw 'Candidate process remains. STOP.' }
    Assert-Port $Candidate $true
    $oldProcesses=@(Get-MatchingProcesses $Production)
    if ($oldProcesses.Count -gt 0) {
        if ($record.phase -ne 'quiescing' -or
            @($oldProcesses | Where-Object { $_.Role -eq 'gateway' }).Count -ne 1 -or
            @($oldProcesses | Where-Object { $_.Role -eq 'collector' }).Count -ne 1) {
            throw 'Partially running legacy processes; manual intervention required. STOP.'
        }
        Assert-Port $Production $false
    } else {
        Assert-Port $Production $true
    }
    foreach ($name in $LegacyNames) { Enable-ScheduledTask -TaskName $name -ErrorAction Stop | Out-Null }
    if ($oldProcesses.Count -eq 0) {
        Start-ScheduledTask -TaskName $LegacyGateway -ErrorAction Stop
        Start-ScheduledTask -TaskName $LegacyCollector -ErrorAction Stop
    }
    $ok=$false
    for ($i=0; $i -lt 12; $i++) {
        Start-Sleep -Seconds 2
        try {
            $live=@(Get-MatchingProcesses $Production)
            Assert-Port $Production $false
            if (@($live | Where-Object { $_.Role -eq 'collector' }).Count -eq 1) { $ok=$true; break }
        } catch { }
    }
    if (-not $ok) { throw 'Legacy restart not verified. Preserve escrow and inspect immediately. STOP.' }
    Set-State $record 'rolled-back'
    Write-Host 'PASS: original task definitions retained, original runtime restarted, 18766 restored.'
    return
}
throw 'Unknown phase. STOP.'
