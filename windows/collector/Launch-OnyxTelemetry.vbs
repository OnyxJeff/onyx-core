Option Explicit
Dim shell, command, result
Set shell = CreateObject("WScript.Shell")
command = "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File ""D:\github_repos\onyx-core\windows\collector\Send-OnyxTelemetry.ps1"" -UseSavedToken -IntervalSeconds 30 -Count 0"
result = shell.Run(command, 0, True)
WScript.Quit result
