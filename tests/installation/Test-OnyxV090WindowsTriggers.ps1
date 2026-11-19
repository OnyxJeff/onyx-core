# ONYX CORE v0.9.0 RC2: isolated Windows PowerShell 5.1 trigger-contract regression.
# Extracts only pure validation functions from development source. No real tasks read/written.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$RepositoryRoot
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1) {
    throw 'Windows PowerShell 5.1 required.'
}
$source = Join-Path $RepositoryRoot 'tools\installation\windows\Invoke-OnyxV090Rehearsal.ps1'
if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
    throw 'Development controller missing. STOP.'
}
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $source, [ref]$tokens, [ref]$errors
)
if (@($errors | Where-Object { $null -ne $_ }).Count -ne 0) {
    throw 'Controller syntax invalid. STOP.'
}
foreach ($name in @('Get-ActualTaskTriggers', 'Assert-ExpectedCandidateTask')) {
    $functions = @($ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }, $true))
    if ($functions.Count -ne 1) {
        throw "Expected one function in source: $name"
    }
    . ([ScriptBlock]::Create($functions[0].Extent.Text))
}

# Intercept the only OS-facing call in the extracted task-validator function.
# Do NOT dot-source the controller or execute any of its phase handlers.
$script:ExpectedName = 'SYNTHETIC RC2 TASK'
$script:MockTask = $null
function Get-ScheduledTask {
    [CmdletBinding()]
    param([string]$TaskName)
    if ($TaskName -cne $script:ExpectedName) {
        throw 'Unexpected task request. STOP.'
    }
    return $script:MockTask
}
$User = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$exe = 'C:\Windows\System32\wscript.exe'
$scriptPath = 'C:\RC2-SYNTHETIC\Launch-OnyxTelemetry.vbs'
$script:MockTask = [pscustomobject]@{
    Actions = @([pscustomobject]@{
        Execute = $exe
        Arguments = ('"{0}"' -f $scriptPath)
        WorkingDirectory = 'C:\RC2-SYNTHETIC'
    })
    Principal = [pscustomobject]@{
        LogonType = 'Interactive'
        RunLevel = 'Limited'
    }
    State = 'Ready'
    Triggers = $null
}

function Expect-Pass([string]$Label) {
    $null = Assert-ExpectedCandidateTask $script:ExpectedName $scriptPath $exe
    Write-Host "PASS: $Label"
}
function Expect-Refusal([string]$Label) {
    $refused = $false
    try {
        $null = Assert-ExpectedCandidateTask $script:ExpectedName $scriptPath $exe
    } catch {
        $refused = $true
    }
    if (-not $refused) {
        throw "Unsafe candidate definition accepted: $Label"
    }
    Write-Host "PASS: refused $Label"
}

$script:MockTask.Triggers = $null
Expect-Pass 'null trigger property means zero triggers'

$script:MockTask.Triggers = @()
Expect-Pass 'empty trigger array means zero triggers'

$script:MockTask.Triggers = @($null)
Expect-Pass 'null placeholder is not a trigger'

$logon = [pscustomobject]@{
    CimClass = [pscustomobject]@{CimClassName = 'MSFT_TaskLogonTrigger'}
    UserId = $User
}
$script:MockTask.Triggers = @($logon)
Expect-Pass 'one approved interactive logon trigger'

$script:MockTask.Triggers = @($logon, $logon)
Expect-Refusal 'two logon triggers'

$script:MockTask.Triggers = @([pscustomobject]@{
    CimClass = [pscustomobject]@{CimClassName = 'MSFT_TaskDailyTrigger'}
    UserId = $User
})
Expect-Refusal 'unexpected trigger class'

$script:MockTask.Triggers = @([pscustomobject]@{
    CimClass = [pscustomobject]@{CimClassName = 'MSFT_TaskLogonTrigger'}
    UserId = 'UNEXPECTED\OTHER'
})
Expect-Refusal 'wrong trigger identity'

$script:MockTask.Triggers = $null
$script:MockTask.Principal.RunLevel = 'Highest'
Expect-Refusal 'privileged principal'
$script:MockTask.Principal.RunLevel = 'Limited'

$script:MockTask.Actions[0].Execute = 'C:\Windows\System32\cmd.exe'
Expect-Refusal 'wrong action executable'
$script:MockTask.Actions[0].Execute = $exe

Write-Host '=== RC2-M4 NATIVE TRIGGER REGRESSIONS PASSED ==='
Write-Host 'No real Scheduled Tasks, services, credentials or journals modified.'
