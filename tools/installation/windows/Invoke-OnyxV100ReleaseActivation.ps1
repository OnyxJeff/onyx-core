# Internal native executor for the authenticated S6 clean release plan.
# No existing task replacement, credential rotation, history deletion or repairs.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidateSet('prepare','activate','rollback')][string]$Operation,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ApprovedPlan,
    [Parameter(Mandatory=$true)][string]$PlanBase64,
    [switch]$ApproveNativeOperation
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
function Require([bool]$Condition,[string]$Message) {
    if (-not $Condition) { throw $Message }
}
Require ($ApproveNativeOperation.IsPresent) 'Separate native approval required.'
Require ($PSVersionTable.PSVersion.Major -eq 5 -and $PSVersionTable.PSVersion.Minor -eq 1) 'PowerShell 5.1 required.'
$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$Principal = [Security.Principal.WindowsPrincipal]::new($Identity)
Require (-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) 'Run non-elevated.'
Require ([Environment]::UserInteractive) 'Interactive user required.'
$Sid = $Identity.User.Value
$Local = [Environment]::GetFolderPath('LocalApplicationData')
Require ($Local -ieq $env:LOCALAPPDATA) 'LocalAppData differs.'
$Root = Join-Path $Local 'OnyxCore-v100-Inactive-Release100'
$State = Join-Path $Local 'OnyxCore-v100'
$Credential = Join-Path $State 'collector-token.dpapi'
$Intent = Join-Path $State 'activation-intent.json'
$Owned = Join-Path $State 'activation-owned.json'
$Plan = [Text.Encoding]::ASCII.GetString([Convert]::FromBase64String($PlanBase64)) | ConvertFrom-Json
Require ($Plan.schema_version -eq 1 -and $Plan.plan_sha256 -ceq $ApprovedPlan -and
    $Plan.activation.root -ieq $Root -and $Plan.activation.credential_path -ieq $Credential) 'Activation plan differs.'
$Actions = @($Plan.activation.tasks)
$Names = @('ONYX CORE v1.0.0 - Local Gateway','ONYX CORE v1.0.0 - Telemetry Collector')
Require ($Actions.Count -eq 2 -and $Actions[0].task_name -ceq $Names[0] -and $Actions[1].task_name -ceq $Names[1]) 'Task scope differs.'
$Marker = 'ONYX CORE v1.0.0 clean release plan ' + $ApprovedPlan
$AllowedSids = @($Sid,'S-1-5-18','S-1-5-32-544')

function Assert-Plain([string]$Path) {
    $Node = Get-Item -LiteralPath $Path -Force
    Require (-not ($Node.Attributes -band [IO.FileAttributes]::ReparsePoint)) 'Redirected path refused.'
    while ($null -ne $Node -and $null -ne $Node.PSObject.Properties['Parent']) {
        $Node = $Node.Parent
        if ($null -ne $Node) {
            Require (-not ($Node.Attributes -band [IO.FileAttributes]::ReparsePoint)) 'Redirected ancestor refused.'
        }
    }
}
function Assert-Dacl([string]$Path,[bool]$Protected) {
    Assert-Plain $Path
    $Acl = Get-Acl -LiteralPath $Path
    Require ($Acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -eq $Sid) 'State owner differs.'
    if ($Protected) { Require $Acl.AreAccessRulesProtected 'State DACL inheritance differs.' }
    $Rules = @($Acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))
    Require ($Rules.Count -gt 0) 'Missing state DACL.'
    foreach ($Rule in $Rules) {
        Require ($Rule.IdentityReference.Value -in $AllowedSids -and
            $Rule.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow) 'Unexpected state DACL.'
    }
    Require (@($Rules | Where-Object {$_.IdentityReference.Value -eq $Sid -and
        ($_.FileSystemRights -band [Security.AccessControl.FileSystemRights]::FullControl) -eq
            [Security.AccessControl.FileSystemRights]::FullControl}).Count -ge 1) 'User control missing.'
}
function Write-New([string]$Path,[string]$Text) {
    $Bytes = [Text.Encoding]::ASCII.GetBytes($Text)
    $Stream = [IO.File]::Open($Path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try { $Stream.Write($Bytes,0,$Bytes.Length); $Stream.Flush($true) }
    finally { $Stream.Dispose() }
}
function TextHash([string]$Text) {
    $Hash = [Security.Cryptography.SHA256]::Create()
    try { [BitConverter]::ToString($Hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text))).Replace('-','') }
    finally { $Hash.Dispose() }
}
function Onyx-Tasks {
    @(Get-ScheduledTask | Where-Object {$_.TaskName -like 'ONYX CORE*'})
}
function Runtime-Processes {
    @(Get-CimInstance Win32_Process | Where-Object {
        $_.Name -in @('pythonw.exe','python.exe','wscript.exe','powershell.exe') -and
        $_.CommandLine -and $_.CommandLine -match '(?i)OnyxGateway_v100\.py|Launch-OnyxTelemetry\.vbs|Send-OnyxTelemetry-v100\.ps1'
    })
}
function Assert-NoTasks {
    Require (@(Onyx-Tasks).Count -eq 0) 'Existing ONYX task requires migration; no changes.'
    Require (@(Runtime-Processes).Count -eq 0) 'Existing ONYX runtime process requires review.'
}
function Assert-State {
    Assert-Dacl $State $true
    Assert-Dacl $Credential $false
    $Item = Get-Item -LiteralPath $Credential
    Require (-not $Item.PSIsContainer -and $Item.Length -ge 32 -and $Item.Length -le 4096) 'Credential metadata differs.'
}
function Assert-Task($Expected,[string]$ExpectedHash) {
    $Task = Get-ScheduledTask -TaskName $Expected.task_name -TaskPath '\'
    $User = [string]$Task.Principal.UserId
    if ($User -notmatch '^S-1-') { $User = ([Security.Principal.NTAccount]::new($User)).Translate([Security.Principal.SecurityIdentifier]).Value }
    Require ($User -eq $Sid -and $Task.Principal.RunLevel -eq 'Limited' -and $Task.Principal.LogonType -eq 'Interactive') 'Task principal differs.'
    Require (@($Task.Actions).Count -eq 1 -and @($Task.Triggers).Count -eq 1 -and
        $Task.Actions[0].Execute -ieq $Expected.execute -and $Task.Actions[0].Arguments -ceq $Expected.arguments -and
        $Task.Actions[0].WorkingDirectory -ieq $Expected.working_directory -and $Task.Description -ceq $Marker) 'Task action or marker differs.'
    $Trigger = $Task.Triggers[0]
    Require ($Trigger.CimClass.CimClassName -eq 'MSFT_TaskLogonTrigger' -and $Trigger.Enabled) 'Task trigger differs.'
    $TriggerUser = [string]$Trigger.UserId
    if ($TriggerUser -notmatch '^S-1-') { $TriggerUser = ([Security.Principal.NTAccount]::new($TriggerUser)).Translate([Security.Principal.SecurityIdentifier]).Value }
    Require ($TriggerUser -eq $Sid -and $Task.Settings.Enabled -and $Task.Settings.ExecutionTimeLimit -eq 'PT0S' -and
        $Task.Settings.RestartCount -eq 3 -and $Task.Settings.RestartInterval -eq 'PT1M' -and
        $Task.Settings.StartWhenAvailable -and $Task.Settings.MultipleInstances -eq 'IgnoreNew') 'Task settings differ.'
    $Digest = TextHash ([string](Export-ScheduledTask -TaskName $Expected.task_name -TaskPath '\'))
    if ($ExpectedHash) { Require ($Digest -ceq $ExpectedHash) 'Task definition hash differs.' }
    $Digest
}
function Assert-LiveRuntime {
    $Processes = @(Runtime-Processes)
    $G = @($Processes | Where-Object {$_.Name -ieq 'pythonw.exe'})
    $W = @($Processes | Where-Object {$_.Name -ieq 'wscript.exe'})
    $C = @($Processes | Where-Object {$_.Name -ieq 'powershell.exe'})
    Require ($Processes.Count -eq 3 -and $G.Count -eq 1 -and $W.Count -eq 1 -and $C.Count -eq 1) 'Unexpected runtime process count.'
    Require ($G[0].CommandLine.IndexOf((Join-Path $Root 'windows\gateway\OnyxGateway_v100.py'),[StringComparison]::OrdinalIgnoreCase) -ge 0 -and
        $W[0].CommandLine.IndexOf((Join-Path $Root 'windows\collector\Launch-OnyxTelemetry.vbs'),[StringComparison]::OrdinalIgnoreCase) -ge 0 -and
        $C[0].CommandLine.IndexOf((Join-Path $Root 'windows\collector\Send-OnyxTelemetry-v100.ps1'),[StringComparison]::OrdinalIgnoreCase) -ge 0 -and
        $C[0].CommandLine -match '(?i)-RequireLauncher' -and $C[0].ParentProcessId -eq $W[0].ProcessId) 'Runtime supervision differs.'
    $Listeners = @(Get-NetTCPConnection -State Listen | Where-Object {$_.LocalPort -eq $Plan.gateway_port})
    Require ($Listeners.Count -eq 1 -and $Listeners[0].LocalAddress -eq '127.0.0.1' -and
        $Listeners[0].OwningProcess -eq $G[0].ProcessId) 'Gateway listener differs.'
}
function Read-Api([string]$Route) {
    $Request = [Net.HttpWebRequest]::Create('http://127.0.0.1:'+[string]$Plan.gateway_port+$Route)
    $Request.Proxy = $null; $Request.Timeout = 5000; $Request.ReadWriteTimeout = 5000; $Request.AllowAutoRedirect = $false
    $Response = $Request.GetResponse()
    try {
        $Reader = [IO.StreamReader]::new($Response.GetResponseStream())
        try { $Reader.ReadToEnd() | ConvertFrom-Json } finally { $Reader.Dispose() }
    } finally { $Response.Dispose() }
}

# Native path and executable identities are independently checked by the Python dispatcher.
Assert-Plain $Root
foreach ($Action in $Actions) {
    Require ($Action.working_directory -ieq $Root) 'Task working directory differs.'
    Assert-Plain $Action.execute
}
Require ($Actions[1].execute -ieq (Join-Path $env:SystemRoot 'System32\wscript.exe')) 'WScript identity differs.'
Require ([IO.Path]::GetFileName($Actions[0].execute) -ieq 'pythonw.exe') 'Pythonw identity differs.'
$Lock = $null
try {
    # Same-user mutex serializes supported executor invocations; abandoned lock fails closed.
    $Mutex = [Threading.Mutex]::new($false,'Local\OnyxCore-v100-CleanReleaseActivation')
    try { $Lock = $Mutex.WaitOne(0) } catch { throw 'Abandoned activation lock; review required.' }
    Require ($Lock) 'Another activation operation is running.'
    if ($Operation -eq 'prepare') {
        Require (-not [Console]::IsInputRedirected) 'Interactive credential entry required.'
        Assert-NoTasks
        Require (-not (Test-Path -LiteralPath $State)) 'Existing credential/state requires migration.'
        Require (@(Get-ChildItem -LiteralPath $Local -Force | Where-Object {
            $_.Name -like '.OnyxCore-v100-release-prepare-*'}).Count -eq 0) 'Previous preparation stage requires review.'
        $Secret = Read-Host 'Paste the same Pi receiver token (not echoed)' -AsSecureString
        $Again = Read-Host 'Confirm receiver token (not echoed)' -AsSecureString
        $Plain = [Net.NetworkCredential]::new('',$Secret).Password
        $Confirm = [Net.NetworkCredential]::new('',$Again).Password
        try {
            Require ($Plain -ceq $Confirm -and $Plain -cmatch '^[A-Za-z0-9_-]{32,128}$') 'Matching URL-safe token required.'
            $Encrypted = ConvertFrom-SecureString -SecureString $Secret
            $Stage = Join-Path $Local ('.OnyxCore-v100-release-prepare-'+[guid]::NewGuid().ToString('N'))
            $Security = [Security.AccessControl.DirectorySecurity]::new()
            $Security.SetOwner($Identity.User); $Security.SetAccessRuleProtection($true,$false)
            foreach ($Account in $AllowedSids) {
                $Rule = [Security.AccessControl.FileSystemAccessRule]::new(
                    [Security.Principal.SecurityIdentifier]::new($Account),
                    [Security.AccessControl.FileSystemRights]::FullControl,
                    [Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit',
                    [Security.AccessControl.PropagationFlags]::None,
                    [Security.AccessControl.AccessControlType]::Allow)
                $Security.AddAccessRule($Rule)
            }
            Require (-not (Test-Path -LiteralPath $Stage)) 'Preparation collision.'
            [IO.Directory]::CreateDirectory($Stage,$Security) | Out-Null
            Assert-Dacl $Stage $true
            $StageCredential = Join-Path $Stage 'collector-token.dpapi'
            Write-New $StageCredential $Encrypted
            Assert-Dacl $StageCredential $false
            [IO.Directory]::Move($Stage,$State)
            Assert-State
            Write-Host 'WINDOWS_STATE_AND_CREDENTIAL_PREPARED=True'
        } finally { $Plain=$null; $Confirm=$null; $Secret=$null; $Again=$null; $Encrypted=$null }
        return
    }
    Assert-State
    if ($Operation -eq 'activate') {
        Assert-NoTasks
        Require (@(Get-ChildItem -LiteralPath $State -Force).Count -eq 1) 'Existing history/intent requires migration or review.'
        Require (@(Get-NetTCPConnection -State Listen | Where-Object {$_.LocalPort -eq $Plan.gateway_port}).Count -eq 0) 'Gateway port occupied.'
        Require ((Get-NetAdapter -Name $Plan.network_adapter).Status -eq 'Up' -and
            (Get-NetAdapter -Name $Plan.usb_adapter).Status -eq 'Up') 'Required adapter unavailable.'
        Write-New $Intent (@{schema_version=1;plan_sha256=$ApprovedPlan;sid=$Sid;kind='windows-clean-activation-intent'} | ConvertTo-Json -Compress)
        Assert-Dacl $Intent $false
        $Scheduler = New-Object -ComObject 'Schedule.Service'
        $Scheduler.Connect()
        $Folder = $Scheduler.GetFolder('\')
        $Hashes = @{}
        foreach ($Expected in $Actions) {
            $Definition = $Scheduler.NewTask(0)
            $Definition.RegistrationInfo.Description = $Marker
            $Definition.Principal.UserId = $Sid
            $Definition.Principal.LogonType = 3 # TASK_LOGON_INTERACTIVE_TOKEN
            $Definition.Principal.RunLevel = 0 # TASK_RUNLEVEL_LUA
            $Settings = $Definition.Settings
            $Settings.Enabled = $true; $Settings.ExecutionTimeLimit = 'PT0S'
            $Settings.RestartCount = 3; $Settings.RestartInterval = 'PT1M'
            $Settings.StartWhenAvailable = $true; $Settings.MultipleInstances = 2 # IgnoreNew
            $Settings.DisallowStartIfOnBatteries = $false; $Settings.StopIfGoingOnBatteries = $false
            $Trigger = $Definition.Triggers.Create(9); $Trigger.UserId = $Sid; $Trigger.Enabled = $true
            $Action = $Definition.Actions.Create(0)
            $Action.Path = $Expected.execute; $Action.Arguments = $Expected.arguments; $Action.WorkingDirectory = $Expected.working_directory
            # TASK_CREATE (2), deliberately NOT TASK_CREATE_OR_UPDATE (6).
            $null = $Folder.RegisterTaskDefinition($Expected.task_name,$Definition,2,$Sid,$null,3,$null)
            $Hashes[$Expected.task_name] = Assert-Task $Expected ''
        }
        Write-New $Owned (@{schema_version=1;plan_sha256=$ApprovedPlan;sid=$Sid;hashes=$Hashes} | ConvertTo-Json -Compress)
        Assert-Dacl $Owned $false
        $Started = [datetimeoffset]::UtcNow
        foreach ($Expected in $Actions) {
            $null = Assert-Task $Expected $Hashes[$Expected.task_name]
            Start-ScheduledTask -TaskName $Expected.task_name -TaskPath '\'
        }
        $Deadline = $Started.AddSeconds(150); $Healthy = $false
        while ([datetimeoffset]::UtcNow -lt $Deadline) {
            $H = $null; $S = $null
            try { $H = Read-Api '/api/v1/health'; $S = (Read-Api '/api/v1/latest').sample } catch { }
            if ($null -ne $H -and $null -ne $S -and $H.status -ceq 'healthy' -and $S.source -ceq $Plan.source -and
                [datetimeoffset]::Parse($S.timestamp_utc) -ge $Started.AddSeconds(-1) -and
                (-not $Plan.cpu_temperature_enabled -or $null -ne $S.metrics.cpu_temp_c)) { $Healthy=$true; break }
            Start-Sleep -Seconds 5
        }
        Require ($Healthy) 'Fresh telemetry not established; preserve intent and registered definitions for review.'
        foreach ($Expected in $Actions) {
            $null = Assert-Task $Expected $Hashes[$Expected.task_name]
            Require ((Get-ScheduledTask -TaskName $Expected.task_name -TaskPath '\').State -eq 'Running') 'Runtime task not running.'
        }
        Assert-LiveRuntime
        Write-Host 'WINDOWS_ACTIVATED=True'
        return
    }
    # Rollback is explicit, checks both saved definitions before stopping either,
    # and retains runtime/state/credential and evidence files.
    Assert-Dacl $Intent $false; Assert-Dacl $Owned $false
    $I = Get-Content -LiteralPath $Intent -Raw | ConvertFrom-Json
    $O = Get-Content -LiteralPath $Owned -Raw | ConvertFrom-Json
    Require ($I.schema_version -eq 1 -and $O.schema_version -eq 1 -and $I.kind -ceq 'windows-clean-activation-intent' -and
        $I.sid -eq $Sid -and $O.sid -eq $Sid -and $I.plan_sha256 -ceq $ApprovedPlan -and $O.plan_sha256 -ceq $ApprovedPlan) 'Activation evidence differs.'
    Require (@(Onyx-Tasks).Count -eq 2 -and @($O.hashes.PSObject.Properties).Count -eq 2) 'Task or receipt inventory differs.'
    foreach ($Expected in $Actions) {
        $Digest = $O.hashes.PSObject.Properties[$Expected.task_name].Value
        Require ($Digest -cmatch '^[A-F0-9]{64}$') 'Missing task identity.'
        $null = Assert-Task $Expected $Digest
    }
    foreach ($Expected in @($Actions[1],$Actions[0])) {
        $null = Assert-Task $Expected $O.hashes.PSObject.Properties[$Expected.task_name].Value
        if ((Get-ScheduledTask -TaskName $Expected.task_name -TaskPath '\').State -eq 'Running') {
            Stop-ScheduledTask -TaskName $Expected.task_name -TaskPath '\'
        }
    }
    $Deadline = [datetimeoffset]::UtcNow.AddSeconds(60)
    while (@(Runtime-Processes).Count -gt 0 -and [datetimeoffset]::UtcNow -lt $Deadline) { Start-Sleep -Seconds 2 }
    Require (@(Runtime-Processes).Count -eq 0) 'Runtime process remains; no task removal.'
    foreach ($Expected in $Actions) {
        $null = Assert-Task $Expected $O.hashes.PSObject.Properties[$Expected.task_name].Value
        Require ((Get-ScheduledTask -TaskName $Expected.task_name -TaskPath '\').State -eq 'Ready') 'Task not stopped.'
    }
    foreach ($Expected in $Actions) {
        $null = Assert-Task $Expected $O.hashes.PSObject.Properties[$Expected.task_name].Value
        Unregister-ScheduledTask -TaskName $Expected.task_name -TaskPath '\' -Confirm:$false
    }
    Require (@(Onyx-Tasks).Count -eq 0 -and @(Runtime-Processes).Count -eq 0) 'Rollback incomplete; review required.'
    Write-Host 'WINDOWS_ROLLED_BACK_RUNTIME_AND_STATE_RETAINED=True'
} catch {
    # No secret values or native exception text are echoed. Partial state stays for review.
    Write-Error 'Native clean-release operation refused or incomplete. Preserve evidence; no automatic cleanup.'
    exit 2
} finally {
    if ($Lock) { $Mutex.ReleaseMutex() }
    if ($null -ne (Get-Variable Mutex -ErrorAction SilentlyContinue)) { $Mutex.Dispose() }
}
