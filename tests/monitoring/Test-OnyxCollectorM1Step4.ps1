# Offline verification only. Never runs the collector's top-level logic or probes the Pi.
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Collector = Join-Path $Root 'windows\networking\Collect-OnyxRecoveryEvidence.ps1'
$DevBranch = & git -C $Root branch --show-current
if ($LASTEXITCODE -ne 0 -or $DevBranch -ne 'feature/v0.7.0-monitoring' -or
    (Split-Path -Leaf $Root) -ne 'onyx-core-v070') {
    throw 'Offline tests must run inside isolated v0.7.0 development worktree.'
}

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw ('FAIL: ' + $Message) }
}

Write-Host "`n=== Parse collector without executing it ==="
$Tokens = $null
$ParseErrors = $null
$Ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $Collector, [ref]$Tokens, [ref]$ParseErrors
)
Assert-True (@($ParseErrors).Count -eq 0) 'Collector has PowerShell syntax errors'

# This scan is a defense-in-depth check, not a substitute for functional verification.
$Prohibited = @(
    'Restart-Service', 'Stop-Service', 'Start-Service', 'Set-Service',
    'Set-NetIPAddress', 'New-NetIPAddress', 'Remove-NetIPAddress',
    'Set-NetIPInterface', 'Disable-NetAdapter', 'Enable-NetAdapter',
    'New-NetRoute', 'Remove-NetRoute', 'Set-NetRoute',
    'Register-ScheduledTask', 'Unregister-ScheduledTask',
    'netsh', 'netsh.exe', 'sc', 'sc.exe', 'schtasks', 'schtasks.exe'
)
$Commands = @($Ast.FindAll({ param($Node)
    $Node -is [System.Management.Automation.Language.CommandAst]
}, $true) | ForEach-Object { $_.GetCommandName() } | Where-Object { $null -ne $_ })
foreach ($Name in $Prohibited) {
    Assert-True ($Name -notin $Commands) ("Forbidden network/task command present: " + $Name)
}
Write-Host 'PASS: Syntax and forbidden command audit'

# Extract only function definitions: never dot-source or run collector top-level.
$Functions = @('Read-OnyxHistory', 'Write-OnyxHistory', 'Invoke-OnyxBoundedSsh')
foreach ($Name in $Functions) {
    $Matches = @($Ast.FindAll({ param($Node)
        $Node -is [System.Management.Automation.Language.FunctionDefinitionAst]
    }, $true) | Where-Object { $_.Name -eq $Name })
    Assert-True ($Matches.Count -eq 1) ("Expected one function " + $Name)
    . ([scriptblock]::Create($Matches[0].Extent.Text))
}
Write-Host 'PASS: Extracted history/SSH functions only'

$script:MaxHistoryAgeSeconds = 300
$script:MaxHistoryBytes = 262144
$script:MaxObservations = 12

$Scratch = Join-Path $env:TEMP ('onyx-v070-m1-step4-' + [guid]::NewGuid().ToString('N'))
try {
    $null = New-Item -ItemType Directory -Path $Scratch -ErrorAction Stop
    $History = Join-Path $Scratch 'recovery-observations.json'
    $When = [DateTimeOffset]::UtcNow.AddSeconds(-10).ToString('o')
    $Obs = @{
        timestamp_utc = $When
        windows = @{ classification = 'WindowsPathReady' }
        pi = @{ classification = 'PiInternetVerified'; gateway_reachable = $true }
        windows_upstream_ok = $true
        external_tcp_failed_targets = @()
    }

    Write-Host "`n=== Bounded offline history tests ==="
    $Missing = Read-OnyxHistory -Path $History -Now ([DateTimeOffset]::UtcNow)
    Assert-True (@($Missing.observations).Count -eq 0) 'Missing history should be empty'
    Write-OnyxHistory -Path $History -Observations @($Obs)
    $Read = Read-OnyxHistory -Path $History -Now ([DateTimeOffset]::UtcNow)
    Assert-True ($null -eq $Read.error -and @($Read.observations).Count -eq 1) 'History roundtrip failed'

    [IO.File]::WriteAllText($History, '{corrupt')
    $Corrupt = Read-OnyxHistory -Path $History -Now ([DateTimeOffset]::UtcNow)
    Assert-True ($null -ne $Corrupt.error -and @($Corrupt.observations).Count -eq 0) 'Corrupt history not rejected'

    [IO.File]::WriteAllText($History, ('X' * ($script:MaxHistoryBytes + 1)))
    $Large = Read-OnyxHistory -Path $History -Now ([DateTimeOffset]::UtcNow)
    Assert-True ($null -ne $Large.error -and @($Large.observations).Count -eq 0) 'Oversized history not rejected'
    Write-OnyxHistory -Path $History -Observations @($Obs)
    $Recovered = Read-OnyxHistory -Path $History -Now ([DateTimeOffset]::UtcNow)
    Assert-True ($null -eq $Recovered.error -and @($Recovered.observations).Count -eq 1) 'History did not recover'
    Write-Host 'PASS: Missing, valid, corrupted, oversized and recovered history'

    Write-Host "`n=== Noninteractive SSH subprocess mock (no network) ==="
    $MockExe = Join-Path $Scratch 'mock-ssh.exe'
    $MockSource = @'
using System;
using System.Threading;
class OnyxM1Mock {
    static int Main(string[] args) {
        var joined = String.Join(" ", args);
        string[] required = {
            "-T", "-n", "-i", "IdentitiesOnly=yes", "BatchMode=yes",
            "PreferredAuthentications=publickey", "PasswordAuthentication=no",
            "KbdInteractiveAuthentication=no", "NumberOfPasswordPrompts=0",
            "StrictHostKeyChecking=yes", "ConnectTimeout=8", "ConnectionAttempts=1",
            "ServerAliveInterval=5", "ServerAliveCountMax=1",
            "mock@invalid.test", "onyxcore-monitor"
        };
        foreach (string requirement in required) {
            if (!joined.Contains(requirement)) return 11;
        }
        var mode = Environment.GetEnvironmentVariable("ONYX_M1_MOCK_MODE") ?? "success";
        if (mode == "fail") return 42;
        if (mode == "sleep") { Thread.Sleep(5000); return 0; }
        Console.Write("{\"classification\":\"PiInternetVerified\",\"repair_action\":\"None\"}");
        return 0;
    }
}
'@
    $null = Add-Type -TypeDefinition $MockSource -Language CSharp `
        -OutputAssembly $MockExe -OutputType ConsoleApplication -ErrorAction Stop
    Assert-True (Test-Path -LiteralPath $MockExe -PathType Leaf) 'Could not compile offline SSH mock'
    $DummyKey = Join-Path $Scratch 'mock key with spaces'
    [IO.File]::WriteAllText($DummyKey, 'dummy')
    $OldMockMode = [Environment]::GetEnvironmentVariable('ONYX_M1_MOCK_MODE', 'Process')
    try {
        [Environment]::SetEnvironmentVariable('ONYX_M1_MOCK_MODE', 'success', 'Process')
        $Output = Invoke-OnyxBoundedSsh -Executable $MockExe -KeyPath $DummyKey `
            -Remote 'mock@invalid.test' -TimeoutSeconds 3
        $Parsed = $Output | ConvertFrom-Json -ErrorAction Stop
        Assert-True ($Parsed.repair_action -eq 'None') 'SSH mock output failed'

        [Environment]::SetEnvironmentVariable('ONYX_M1_MOCK_MODE', 'fail', 'Process')
        $Failed = $false
        try {
            $null = Invoke-OnyxBoundedSsh -Executable $MockExe -KeyPath $DummyKey `
                -Remote 'mock@invalid.test' -TimeoutSeconds 3
        }
        catch { $Failed = $_.Exception.Message -like '*exit 42*' }
        Assert-True $Failed 'SSH failure was not surfaced'

        [Environment]::SetEnvironmentVariable('ONYX_M1_MOCK_MODE', 'sleep', 'Process')
        $TimedOut = $false
        try {
            $null = Invoke-OnyxBoundedSsh -Executable $MockExe -KeyPath $DummyKey `
                -Remote 'mock@invalid.test' -TimeoutSeconds 1
        }
        catch { $TimedOut = $_.Exception.Message -like '*wall-clock limit*' }
        Assert-True $TimedOut 'SSH process timeout not enforced'
        Write-Host 'PASS: Restricted mock SSH, failures and wall-clock timeout'
    }
    finally {
        [Environment]::SetEnvironmentVariable('ONYX_M1_MOCK_MODE', $OldMockMode, 'Process')
    }
}
finally {
    if (Test-Path -LiteralPath $Scratch) {
        Remove-Item -LiteralPath $Scratch -Recurse -Force -ErrorAction SilentlyContinue
    }
}
Write-Host "`nPASS: M1 Step 4 offline collector checks completed; no live probes or network changes."
