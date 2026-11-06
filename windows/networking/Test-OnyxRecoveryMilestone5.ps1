# ONYX CORE v0.6.0 Milestone 5 -- OFFLINE failure injection (Windows PowerShell 5.1).
# Never invokes live collector, Pi, ICS, production, scheduled tasks, or network.
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Dev = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Prod = 'D:\github_repos\onyx-core'
$Collector = Join-Path $PSScriptRoot 'Collect-OnyxRecoveryEvidence.ps1'
$EngineScenarios = Join-Path $PSScriptRoot 'Test-OnyxRecoveryMilestone5.py'

function Assert-OnyxM5 {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw ('FAIL: ' + $Message) }
}

Write-Host "`n=== Milestone 5: read-only repository guards ==="
Assert-OnyxM5 ((Split-Path -Leaf $Dev) -eq 'onyx-core-v060') 'Wrong development worktree name'
$Branch = & git -C $Dev branch --show-current
Assert-OnyxM5 (($LASTEXITCODE -eq 0) -and ($Branch -eq 'feature/v0.6.0-reliability')) 'Wrong development branch'
& git -C $Dev merge-base --is-ancestor '049bd72' HEAD
Assert-OnyxM5 ($LASTEXITCODE -eq 0) 'Milestone 4 must be an ancestor of development HEAD'
Assert-OnyxM5 (Test-Path -LiteralPath $Collector -PathType Leaf) 'Collector missing'
Assert-OnyxM5 (Test-Path -LiteralPath $EngineScenarios -PathType Leaf) 'Scenario file missing'
if (Test-Path -LiteralPath $Prod -PathType Container) {
    $ProdBranch = & git -C $Prod branch --show-current
    $ProdHead = & git -C $Prod rev-parse --short=7 HEAD
    Assert-OnyxM5 (($LASTEXITCODE -eq 0) -and $ProdBranch -eq 'main' -and $ProdHead -eq '6d1e599') 'Production HEAD/branch unexpectedly changed'
}
else { throw 'Production repository not found at the expected path; cannot verify isolation.' }
Write-Host 'PASS: Worktree and production HEAD guarded'

Write-Host "`n=== Actual collector function checks (no top-level execution) ==="
$Tokens = $null
$ParseErrors = $null
$Ast = [System.Management.Automation.Language.Parser]::ParseFile($Collector, [ref]$Tokens, [ref]$ParseErrors)
Assert-OnyxM5 (@($ParseErrors).Count -eq 0) 'Collector PowerShell syntax invalid'
$BlockedCommands = @(
    'Restart-Service', 'Stop-Service', 'Start-Service', 'Set-Service',
    'Set-NetIPAddress', 'New-NetIPAddress', 'Remove-NetIPAddress',
    'Set-NetIPInterface', 'Disable-NetAdapter', 'Enable-NetAdapter',
    'New-NetRoute', 'Remove-NetRoute', 'Set-NetRoute',
    'Register-ScheduledTask', 'Unregister-ScheduledTask',
    'netsh', 'netsh.exe', 'sc', 'sc.exe', 'schtasks', 'schtasks.exe'
)
$InvokedCommands = @($Ast.FindAll({param($Node)
    $Node -is [System.Management.Automation.Language.CommandAst]
}, $true) | ForEach-Object { $_.GetCommandName() } | Where-Object { $null -ne $_ })
foreach ($Blocked in $BlockedCommands) {
    Assert-OnyxM5 ($Blocked -notin $InvokedCommands) ("Collector invokes prohibited command: " + $Blocked)
}
$FunctionNames = @('Invoke-OnyxBoundedSsh', 'Read-OnyxHistory', 'Write-OnyxHistory')
foreach ($Name in $FunctionNames) {
    $Matches = @($Ast.FindAll({param($Node)
        $Node -is [System.Management.Automation.Language.FunctionDefinitionAst]
    }, $true) | Where-Object { $_.Name -eq $Name })
    Assert-OnyxM5 ($Matches.Count -eq 1) ("Expected exactly one function " + $Name)
    # Dot-source the FUNCTION DEFINITION ONLY. Never execute collector top-level code.
    $Definition = [scriptblock]::Create($Matches[0].Extent.Text)
    . $Definition
}
Write-Host 'PASS: Collector parsed; helper functions loaded without running probes'
Write-Host 'PASS: No known ICS/service/scheduled-task repair commands in collector AST'

# The helpers depend only on these fixed bounds normally set by the collector top-level.
$script:MaxHistoryAgeSeconds = 300
$script:MaxHistoryBytes = 262144
$script:MaxObservations = 12
$ScratchRoot = Join-Path $env:TEMP ('onyxcore-m5-offline-' + [guid]::NewGuid().ToString('N'))
$OriginalMode = [Environment]::GetEnvironmentVariable('ONYX_M5_SSH_MODE', 'Process')
try {
    $null = New-Item -ItemType Directory -Path $ScratchRoot -Force
    $HistoryPath = Join-Path $ScratchRoot 'observations.json'
    $T1 = [DateTimeOffset]::UtcNow.AddSeconds(-25).ToString('o')
    $T2 = [DateTimeOffset]::UtcNow.AddSeconds(-10).ToString('o')
    $Obs1 = @{
        timestamp_utc = $T1
        windows = @{ classification = 'WindowsPathReady' }
        pi = @{ classification = 'PiInternetVerified'; gateway_reachable = $true }
        windows_upstream_ok = $true
        external_tcp_failed_targets = @()
    }
    $Obs2 = @{
        timestamp_utc = $T2
        windows = @{ classification = 'WindowsPathReady' }
        pi = @{ classification = 'ExternalTcpUnverified'; gateway_reachable = $true }
        windows_upstream_ok = $true
        external_tcp_failed_targets = @('1.1.1.1:443', '9.9.9.9:443')
    }

    Write-Host "`n=== Real bounded history helper tests (temporary files only) ==="
    $Missing = Read-OnyxHistory -Path $HistoryPath -Now ([DateTimeOffset]::UtcNow)
    Assert-OnyxM5 (($null -eq $Missing.error) -and @($Missing.observations).Count -eq 0) 'Missing history should start empty'
    Write-OnyxHistory -Path $HistoryPath -Observations @($Obs1)
    Write-OnyxHistory -Path $HistoryPath -Observations @($Obs1, $Obs2)
    $Loaded = Read-OnyxHistory -Path $HistoryPath -Now ([DateTimeOffset]::UtcNow)
    Assert-OnyxM5 (($null -eq $Loaded.error) -and @($Loaded.observations).Count -eq 2) 'Atomic replacement lost observations'
    Write-Host 'PASS: Initial file creation and atomic replacement'

    $Stale = $Obs1.Clone()
    $Stale.timestamp_utc = [DateTimeOffset]::UtcNow.AddSeconds(-600).ToString('o')
    Write-OnyxHistory -Path $HistoryPath -Observations @($Stale, $Obs2)
    $Loaded = Read-OnyxHistory -Path $HistoryPath -Now ([DateTimeOffset]::UtcNow)
    Assert-OnyxM5 (($null -eq $Loaded.error) -and @($Loaded.observations).Count -eq 1) 'Stale observation not pruned'
    Write-Host 'PASS: Five-minute retention boundary'

    [IO.File]::WriteAllText($HistoryPath, '{invalid JSON')
    $Loaded = Read-OnyxHistory -Path $HistoryPath -Now ([DateTimeOffset]::UtcNow)
    Assert-OnyxM5 (($null -ne $Loaded.error) -and @($Loaded.observations).Count -eq 0) 'Corrupt history did not fail closed'
    Write-Host 'PASS: Corrupt JSON fails closed'

    [IO.File]::WriteAllText($HistoryPath, (('X' * ($script:MaxHistoryBytes + 1))))
    $Loaded = Read-OnyxHistory -Path $HistoryPath -Now ([DateTimeOffset]::UtcNow)
    Assert-OnyxM5 (($null -ne $Loaded.error) -and @($Loaded.observations).Count -eq 0) 'Oversize history not rejected'
    Write-Host 'PASS: Storage size upper bound'

    $TooMany = @()
    for ($I = 13; $I -ge 1; $I--) {
        $Obs = $Obs1.Clone()
        $Obs.timestamp_utc = [DateTimeOffset]::UtcNow.AddSeconds(-$I).ToString('o')
        $TooMany += $Obs
    }
    Write-OnyxHistory -Path $HistoryPath -Observations $TooMany
    $Loaded = Read-OnyxHistory -Path $HistoryPath -Now ([DateTimeOffset]::UtcNow)
    Assert-OnyxM5 (($null -ne $Loaded.error) -and @($Loaded.observations).Count -eq 0) '13 observations not rejected'
    Write-Host 'PASS: Observation-count upper bound'

    Write-OnyxHistory -Path $HistoryPath -Observations @($Obs2)
    $Loaded = Read-OnyxHistory -Path $HistoryPath -Now ([DateTimeOffset]::UtcNow)
    Assert-OnyxM5 (($null -eq $Loaded.error) -and @($Loaded.observations).Count -eq 1) 'History not recoverable after corrupt/oversize input'
    $Residue = @(Get-ChildItem -LiteralPath $ScratchRoot -File | Where-Object {
        $_.Name -like '.onyx-v060-*'
    })
    Assert-OnyxM5 ($Residue.Count -eq 0) 'History left behind a temporary/backup file'
    Write-Host 'PASS: History recovery and temporary-file cleanup'

    Write-Host "`n=== SSH subprocess failure injection (LOCAL mock executable) ==="
    # Compile temporary, harmless test process: no sockets, no authentication, no Pi.
    $MockExe = Join-Path $ScratchRoot 'mock-ssh.exe'
    $MockSource = @'
using System;
using System.Threading;
class MockSsh {
    static int Main(string[] args) {
        string joined = String.Join(" ", args);
        string[] required = {
            "-T", "-n", "-i", "IdentitiesOnly=yes", "BatchMode=yes",
            "PreferredAuthentications=publickey", "PasswordAuthentication=no",
            "KbdInteractiveAuthentication=no", "NumberOfPasswordPrompts=0",
            "StrictHostKeyChecking=yes", "ConnectTimeout=8", "ConnectionAttempts=1",
            "ServerAliveInterval=5", "ServerAliveCountMax=1",
            "test@mock.invalid", "onyxcore-monitor"
        };
        foreach (string flag in required) {
            if (!joined.Contains(flag)) {
                Console.Error.WriteLine("missing flag: " + flag);
                return 11;
            }
        }
        string mode = Environment.GetEnvironmentVariable("ONYX_M5_SSH_MODE") ?? "good";
        if (mode == "failure") {
            Console.Error.WriteLine("mock authentication failure");
            return 42;
        }
        if (mode == "sleep") {
            Thread.Sleep(10000);
            return 0;
        }
        if (mode == "large") {
            Console.Write(new String('X', 70000));
            return 0;
        }
        if (mode == "invalid_json") {
            Console.Write("{invalid json");
            return 0;
        }
        Console.Write("{\"classification\":\"PiInternetVerified\",\"repair_action\":\"None\"}");
        return 0;
    }
}
'@
    $null = Add-Type -TypeDefinition $MockSource -Language CSharp `
        -OutputAssembly $MockExe -OutputType ConsoleApplication -ErrorAction Stop
    Assert-OnyxM5 (Test-Path -LiteralPath $MockExe -PathType Leaf) 'Failed to build mock executable'
    $MockKey = Join-Path $ScratchRoot 'mock key with spaces'
    [IO.File]::WriteAllText($MockKey, 'not a real private key')

    [Environment]::SetEnvironmentVariable('ONYX_M5_SSH_MODE', 'good', 'Process')
    $Output = Invoke-OnyxBoundedSsh -Executable $MockExe -KeyPath $MockKey `
        -Remote 'test@mock.invalid' -TimeoutSeconds 5
    $Parsed = $Output | ConvertFrom-Json -ErrorAction Stop
    Assert-OnyxM5 (($Parsed.classification -eq 'PiInternetVerified') -and
        ($Parsed.repair_action -eq 'None')) 'Mock SSH good path or noninteractive flags failed'
    Write-Host 'PASS: Dedicated-key-only, noninteractive SSH invocation flags'

    [Environment]::SetEnvironmentVariable('ONYX_M5_SSH_MODE', 'failure', 'Process')
    $Failed = $false
    try { $null = Invoke-OnyxBoundedSsh -Executable $MockExe -KeyPath $MockKey -Remote 'test@mock.invalid' -TimeoutSeconds 5 }
    catch { $Failed = $_.Exception.Message -like '*exit 42*' }
    Assert-OnyxM5 $Failed 'Nonzero SSH exit was not surfaced'
    Write-Host 'PASS: SSH authorization/command failure is non-success'

    [Environment]::SetEnvironmentVariable('ONYX_M5_SSH_MODE', 'sleep', 'Process')
    $Failed = $false
    try { $null = Invoke-OnyxBoundedSsh -Executable $MockExe -KeyPath $MockKey -Remote 'test@mock.invalid' -TimeoutSeconds 1 }
    catch { $Failed = $_.Exception.Message -like '*wall-clock limit*' }
    Assert-OnyxM5 $Failed 'SSH hung beyond bounded deadline'
    Write-Host 'PASS: SSH/remote diagnostic wall-clock timeout enforced'

    [Environment]::SetEnvironmentVariable('ONYX_M5_SSH_MODE', 'large', 'Process')
    $Failed = $false
    try { $null = Invoke-OnyxBoundedSsh -Executable $MockExe -KeyPath $MockKey -Remote 'test@mock.invalid' -TimeoutSeconds 5 }
    catch { $Failed = $_.Exception.Message -like '*too much output*' }
    Assert-OnyxM5 $Failed 'Oversize SSH output was accepted'
    Write-Host 'PASS: Remote diagnostic stdout size limit'

    [Environment]::SetEnvironmentVariable('ONYX_M5_SSH_MODE', 'invalid_json', 'Process')
    $Output = Invoke-OnyxBoundedSsh -Executable $MockExe -KeyPath $MockKey -Remote 'test@mock.invalid' -TimeoutSeconds 5
    $Failed = $false
    try { $null = $Output | ConvertFrom-Json -ErrorAction Stop }
    catch { $Failed = $true }
    Assert-OnyxM5 $Failed 'Invalid JSON did not fail parsing'
    Write-Host 'PASS: Malformed remote payload cannot be parsed as evidence'

    Write-Host "`n=== Python decision policy matrix (offline fixtures) ==="
    & python $EngineScenarios
    Assert-OnyxM5 ($LASTEXITCODE -eq 0) 'Python decision scenarios failed'

    Write-Host "`nPASS: Milestone 5 offline failure-injection suite complete. No repair actions."
}
finally {
    [Environment]::SetEnvironmentVariable('ONYX_M5_SSH_MODE', $OriginalMode, 'Process')
    Remove-Item -LiteralPath $ScratchRoot -Recurse -Force -ErrorAction SilentlyContinue
}
