# ONYX CORE v0.7.0 Milestone 1: offline cycle-wrapper tests.
# Extracts a pure function from the AST; never runs the script's top level.
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-Onyx {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw ('FAIL: ' + $Message) }
}
function Expect-OnyxReject {
    param([scriptblock]$Action, [string]$Label)
    $Rejected = $false
    try { $null = & $Action }
    catch { $Rejected = $true }
    Assert-Onyx $Rejected ("Expected rejection: " + $Label)
}

$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..') -ErrorAction Stop).Path
$Runner = Join-Path $Root 'windows\monitoring\Invoke-OnyxMonitoringCycle.ps1'
Assert-Onyx (Test-Path -LiteralPath $Runner -PathType Leaf) 'Cycle runner missing'

$Branch = & git -C $Root branch --show-current
Assert-Onyx ($LASTEXITCODE -eq 0 -and $Branch -eq 'feature/v0.7.0-monitoring' -and
    (Split-Path -Leaf $Root) -eq 'onyx-core-v070') 'Wrong development worktree'

Write-Host "`n=== Parse cycle runner without invoking probes ==="
$Tokens = $null
$Errors = $null
$Ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $Runner, [ref]$Tokens, [ref]$Errors
)
Assert-Onyx (@($Errors).Count -eq 0) 'PowerShell parser rejected cycle runner'

$Commands = @($Ast.FindAll({ param($Node)
    $Node -is [System.Management.Automation.Language.CommandAst]
}, $true) | ForEach-Object { $_.GetCommandName() } | Where-Object { $null -ne $_ })
$Forbidden = @(
    'Restart-Service', 'Stop-Service', 'Start-Service', 'Set-Service',
    'Disable-NetAdapter', 'Enable-NetAdapter', 'Set-NetIPAddress', 'New-NetIPAddress',
    'Remove-NetIPAddress', 'Set-NetRoute', 'New-NetRoute', 'Remove-NetRoute',
    'netsh', 'netsh.exe', 'schtasks', 'schtasks.exe',
    'Register-ScheduledTask', 'Unregister-ScheduledTask',
    'Start-Process', 'Invoke-WebRequest'
)
foreach ($Name in $Forbidden) {
    Assert-Onyx ($Name -notin $Commands) ("Forbidden command: " + $Name)
}
$Source = [IO.File]::ReadAllText($Runner)
Assert-Onyx ($Source.Contains('if (-not $LiveReadOnly)')) 'Missing explicit live opt-in'
Assert-Onyx ($Source.Contains('& $Collector -LiveReadOnly')) 'Collector invocation missing read-only switch'
Assert-Onyx ($Source.Contains('OnyxCore-v070-Development')) 'Development history path not enforced'
Assert-Onyx ($Source.Contains('792526af8b8f3b66b7f8d05f4f289bf297f82593')) 'Checkpoint lineage guard missing'
Write-Host 'PASS: Syntax and static no-repair/no-task guard'

$Functions = @($Ast.FindAll({ param($Node)
    $Node -is [System.Management.Automation.Language.FunctionDefinitionAst]
}, $true) | Where-Object { $_.Name -eq 'ConvertTo-OnyxCycleSummary' })
Assert-Onyx ($Functions.Count -eq 1) 'Exactly one normalization function required'
. ([scriptblock]::Create($Functions[0].Extent.Text))

$Path = 'C:\Users\test\AppData\Local\OnyxCore-v070-Development\Monitoring\recovery-observations.json'
$Start = [DateTimeOffset]::UtcNow.AddSeconds(-3)
$End = [DateTimeOffset]::UtcNow

function New-HealthyReport {
    return [PSCustomObject]@{
        mode = 'ReadOnlyPersistentHistory'
        repair_action = 'None'
        history_path = $Path
        history_error = $null
        windows_error = $null
        pi_error = $null
        observation_count = 1
        observation = [PSCustomObject]@{
            windows = [PSCustomObject]@{ classification = 'WindowsPathReady' }
            pi = [PSCustomObject]@{ classification = 'PiInternetVerified' }
            windows_upstream_ok = $true
        }
        decision = [PSCustomObject]@{
            decision = 'Healthy'
            reason = 'Both diagnostics agree'
            repair_action = 'None'
            consecutive_suspected = 0
        }
    }
}

Write-Host "`n=== Offline summary contract ==="
$Healthy = New-HealthyReport
$Summary = ConvertTo-OnyxCycleSummary -Report $Healthy -StartedAt $Start `
    -FinishedAt $End -ExpectedHistoryPath $Path
Assert-Onyx ($Summary.cycle_status -eq 'Complete' -and
    $Summary.connectivity_decision -eq 'Healthy' -and
    $Summary.repair_action -eq 'None' -and
    $Summary.observation_count -eq 1 -and
    $Summary.duration_ms -ge 0) 'Healthy summary invalid'
$Json = $Summary | ConvertTo-Json -Depth 5 | ConvertFrom-Json
Assert-Onyx ($Json.schema_version -eq 1 -and $Json.repair_action -eq 'None') 'Summary JSON invalid'
Write-Host 'PASS: Healthy normalization and JSON roundtrip'

$Partial = New-HealthyReport
$Partial.pi_error = 'mock timeout'
$Partial.decision.decision = 'Investigate'
$Partial.decision.reason = 'incomplete'
$PartSummary = ConvertTo-OnyxCycleSummary -Report $Partial -StartedAt $Start `
    -FinishedAt $End -ExpectedHistoryPath $Path
Assert-Onyx ($PartSummary.cycle_status -eq 'EvidenceIncomplete' -and
    $PartSummary.pi_error_present -and
    $PartSummary.connectivity_decision -eq 'Investigate' -and
    $PartSummary.repair_action -eq 'None') 'Incomplete evidence normalized incorrectly'
Write-Host 'PASS: SSH timeout modeled as incomplete evidence, never healthy'

$Suspect = New-HealthyReport
$Suspect.decision.decision = 'PossibleIcsFailure'
$Suspect.decision.consecutive_suspected = 3
$Suspect.observation.pi.classification = 'ExternalTcpUnverified'
$Suspect.observation_count = 3
$SuspSummary = ConvertTo-OnyxCycleSummary -Report $Suspect -StartedAt $Start `
    -FinishedAt $End -ExpectedHistoryPath $Path
Assert-Onyx ($SuspSummary.connectivity_decision -eq 'PossibleIcsFailure' -and
    $SuspSummary.repair_action -eq 'None') 'Suspected failure summary invalid'
Write-Host 'PASS: Suspected ICS failure never requests repair'

$WrongRepair = New-HealthyReport
$WrongRepair.repair_action = 'RestartIcs'
Expect-OnyxReject { ConvertTo-OnyxCycleSummary -Report $WrongRepair `
    -StartedAt $Start -FinishedAt $End -ExpectedHistoryPath $Path } 'repair action'

$WrongPath = New-HealthyReport
$WrongPath.history_path = 'C:\Users\test\AppData\Local\OnyxCore\Monitoring\recovery-observations.json'
Expect-OnyxReject { ConvertTo-OnyxCycleSummary -Report $WrongPath `
    -StartedAt $Start -FinishedAt $End -ExpectedHistoryPath $Path } 'production history path'

$Contradiction = New-HealthyReport
$Contradiction.pi_error = 'mock failure'
Expect-OnyxReject { ConvertTo-OnyxCycleSummary -Report $Contradiction `
    -StartedAt $Start -FinishedAt $End -ExpectedHistoryPath $Path } 'healthy with Pi failure'

$Unknown = New-HealthyReport
$Unknown.decision.decision = 'Other'
Expect-OnyxReject { ConvertTo-OnyxCycleSummary -Report $Unknown `
    -StartedAt $Start -FinishedAt $End -ExpectedHistoryPath $Path } 'unknown decision'

$BadCount = New-HealthyReport
$BadCount.observation_count = 13
Expect-OnyxReject { ConvertTo-OnyxCycleSummary -Report $BadCount `
    -StartedAt $Start -FinishedAt $End -ExpectedHistoryPath $Path } 'invalid count'

$NoUpstream = New-HealthyReport
$NoUpstream.observation.windows_upstream_ok = $false
Expect-OnyxReject { ConvertTo-OnyxCycleSummary -Report $NoUpstream `
    -StartedAt $Start -FinishedAt $End -ExpectedHistoryPath $Path } 'healthy with Windows upstream failure'

Write-Host 'PASS: Invalid/contradictory evidence rejected'
Write-Host "`nPASS: One-shot wrapper offline tests. No probes, scheduled tasks or network changes."
