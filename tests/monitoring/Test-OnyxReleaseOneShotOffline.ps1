# ONYX CORE v0.7.0 M5 B2: PowerShell source audit and pure summary tests.
# NEVER dot-source or invoke either release script's top-level statements.
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..') -ErrorAction Stop).Path
$ExpectedBranch = & git -C $Root branch --show-current
if ($LASTEXITCODE -ne 0 -or $ExpectedBranch -ne 'feature/v0.7.0-monitoring' -or
    (Split-Path -Leaf $Root) -ne 'onyx-core-v070') {
    throw 'Release offline tests require isolated v0.7.0 development.'
}

function Assert-OnyxRelease {
    param([bool]$OK, [string]$Reason)
    if (-not $OK) { throw ('FAIL: ' + $Reason) }
}

$Runner = Join-Path $Root 'windows\monitoring\Invoke-OnyxReleaseCycle.ps1'
$Collector = Join-Path $Root 'windows\networking\Collect-OnyxReleaseEvidence.ps1'
$Bodies = @{}
foreach ($Path in @($Runner, $Collector)) {
    $Tokens = $null
    $Errors = $null
    $AST = [System.Management.Automation.Language.Parser]::ParseFile(
        $Path, [ref]$Tokens, [ref]$Errors
    )
    Assert-OnyxRelease (@($Errors).Count -eq 0) "PowerShell parse failed: $Path"
    $Names = @($AST.FindAll({param($Node)
        $Node -is [System.Management.Automation.Language.CommandAst]
    }, $true) | ForEach-Object {$_.GetCommandName()} | Where-Object {$null -ne $_})
    $Forbidden = @(
        'Restart-Service', 'Stop-Service', 'Start-Service', 'Set-Service',
        'Disable-NetAdapter', 'Enable-NetAdapter', 'Set-NetIPAddress',
        'New-NetIPAddress', 'Remove-NetIPAddress', 'Set-NetRoute',
        'New-NetRoute', 'Remove-NetRoute', 'netsh', 'schtasks',
        'Register-ScheduledTask', 'Unregister-ScheduledTask'
    )
    foreach ($Command in $Forbidden) {
        Assert-OnyxRelease ($Command -notin $Names) "Forbidden network repair/scheduling: $Command"
    }
    $Bodies[$Path] = $AST
}
Write-Host 'PASS: Release PowerShell syntax and no-repair/no-scheduling guards.'

$RunnerText = [IO.File]::ReadAllText($Runner)
$CollectorText = [IO.File]::ReadAllText($Collector)
Assert-OnyxRelease ($RunnerText.Contains('ONYX_CORE_V070_RELEASE_LIVE')) 'Missing release runner gate'
Assert-OnyxRelease ($CollectorText.Contains('AuthorizedReleaseRunner')) 'Missing release collector gate'
Assert-OnyxRelease ($CollectorText.Contains('monitoring.release.example.json')) 'Release config missing'
Assert-OnyxRelease ($CollectorText.Contains('StrictHostKeyChecking=yes')) 'SSH host key checking absent'
Assert-OnyxRelease ($CollectorText.Contains('BatchMode=yes')) 'SSH batch mode absent'
Assert-OnyxRelease ($CollectorText.Contains('if ($null -eq $HistoryError)')) 'Corrupt history preservation guard missing'
Assert-OnyxRelease (-not $CollectorText.Contains('OnyxCore-v070-Development')) 'Development history leaked into release collector'
Write-Host 'PASS: Explicit release invocation and history-isolation guards.'

# Extract the pure summary converter without invoking the wrapper or collector.
$SummaryFunctions = @($Bodies[$Runner].FindAll({param($Node)
    $Node -is [System.Management.Automation.Language.FunctionDefinitionAst]
}, $true) | Where-Object {$_.Name -eq 'ConvertTo-OnyxCycleSummary'})
Assert-OnyxRelease ($SummaryFunctions.Count -eq 1) 'Missing unique release summary function'
. ([scriptblock]::Create($SummaryFunctions[0].Extent.Text))

$Now = [DateTimeOffset]::UtcNow
$History = Join-Path $env:TEMP 'onyx-release-test-history.json'
$Report = [PSCustomObject]@{
    mode = 'ReadOnlyPersistentHistory'
    repair_action = 'None'
    history_path = $History
    observation_count = 1
    history_error = $null
    windows_error = $null
    pi_error = $null
    observation = [PSCustomObject]@{
        windows = [PSCustomObject]@{classification='WindowsPathReady'}
        pi = [PSCustomObject]@{classification='PiInternetVerified'}
        windows_upstream_ok = $true
    }
    decision = [PSCustomObject]@{
        decision = 'Healthy'
        consecutive_suspected = 0
        reason = 'offline only'
        repair_action = 'None'
    }
}
$Summary = ConvertTo-OnyxCycleSummary -Report $Report `
    -StartedAt $Now -FinishedAt $Now.AddSeconds(2) -ExpectedHistoryPath $History
Assert-OnyxRelease ($Summary.source -eq 'LiveRestrictedDiagnostic' -and
    $Summary.repair_action -eq 'None' -and $Summary.connectivity_decision -eq 'Healthy') `
    'Release healthy evidence summary mismatch'

$BadReport = $Report.PSObject.Copy()
$BadReport.repair_action = 'ResetIcs'
$Refused = $false
try { $null = ConvertTo-OnyxCycleSummary -Report $BadReport `
        -StartedAt $Now -FinishedAt $Now.AddSeconds(2) -ExpectedHistoryPath $History }
catch { $Refused = $true }
Assert-OnyxRelease $Refused 'Repair request must be refused'
Write-Host 'PASS: Offline release summary and repair refusal.'
Write-Host 'PASS: No diagnostic probe, state mutation, repair or schedule executed.'
