# ONYX CORE M1-S6B Windows-native parser and read-only preview acceptance.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Dev,
    [Parameter(Mandatory=$true)][string]$PythonPath
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1) {
    throw 'Windows PowerShell 5.1 required.'
}
$Launcher = Join-Path $Dev 'tools\installation\windows\Invoke-OnyxV100WindowsRuntime.ps1'
$Collector = Join-Path $Dev 'windows\collector\Send-OnyxTelemetry-v100.ps1'
$Gateway = Join-Path $Dev 'windows\gateway\OnyxGateway_v100.py'
$Example = Join-Path $Dev 'docs\v1.0.0\examples\windows.config.example.json'

foreach ($File in @($Launcher, $Collector)) {
    $Tokens = $null
    $ParseErrors = $null
    $null = [System.Management.Automation.Language.Parser]::ParseFile(
        $File, [ref]$Tokens, [ref]$ParseErrors)
    if (@($ParseErrors).Count -ne 0) {
        $ParseErrors | ForEach-Object { Write-Error $_.Message }
        throw "PowerShell parser rejected: $File"
    }
}
Write-Host 'PASS: Versioned collector and runtime launcher parse in PowerShell 5.1.'

& $PythonPath -I -B -c "import ast,sys; ast.parse(open(sys.argv[1], encoding='utf-8').read())" $Gateway
if ($LASTEXITCODE -ne 0) {
    throw 'Versioned gateway failed Python AST parsing.'
}
Write-Host 'PASS: Versioned gateway Python AST parsed without writing bytecode.'

foreach ($Component in @('Collector', 'Gateway')) {
    $Raw = @(& powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass `
        -File $Launcher -ConfigPath $Example -InstalledRoot $Dev `
        -PythonPath $PythonPath -Component $Component 2>&1)
    if ($LASTEXITCODE -ne 0 -or $Raw.Count -ne 1) {
        throw "Read-only runtime preview failed: $Component"
    }
    $Plan = [string]$Raw[0] | ConvertFrom-Json -ErrorAction Stop
    if ($Plan.operation -cne 'WINDOWS_RUNTIME_PREVIEW' -or
        $Plan.component -cne $Component -or
        $Plan.activation_performed -ne $false -or
        $Plan.credential_contents_read -ne $false -or
        $Plan.task_or_service_changes -ne $false -or
        $Plan.installation_accepted -ne $false -or
        $Plan.receiver_port -ne 8765 -or $Plan.gateway_port -ne 18766) {
        throw "Unexpected runtime preview contract: $Component"
    }
    Write-Host "PASS: $Component preview validated; no activation."
}

# An expected child PowerShell refusal writes to native stderr. With
# ErrorActionPreference=Stop, Windows PowerShell 5.1 turns redirected native
# stderr into a terminating NativeCommandError before we can check the exit
# code. Scope Continue ONLY around this intentional negative test.
$PreviousErrorActionPreference = $ErrorActionPreference
$Refusal = @()
$RefusalExit = $null
try {
    $ErrorActionPreference = 'Continue'
    $Refusal = @(& powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass `
        -File $Launcher -ConfigPath $Example -InstalledRoot $Dev `
        -PythonPath $PythonPath -Component Collector -Run 2>&1)
    $RefusalExit = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $PreviousErrorActionPreference
}
if ($null -eq $RefusalExit -or $RefusalExit -eq 0) {
    throw 'One-sided runtime execution was not refused.'
}
$RefusalText = $Refusal | Out-String
if (-not $RefusalText.Contains('Execution requires explicit -Run and -ApproveExecution.')) {
    throw 'Runtime refused for an unexpected reason; approval guard not established.'
}
Write-Host 'PASS: One-sided execution approval refused with expected reason.'
Write-Host 'SUCCESS: M1-S6B native offline checks passed.'
