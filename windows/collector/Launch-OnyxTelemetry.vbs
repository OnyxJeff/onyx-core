Option Explicit
Dim shell, fso, scriptPath, command, result
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptPath = fso.BuildPath(fso.GetParentFolderName(WScript.ScriptFullName), "Send-OnyxTelemetry.ps1")
command = "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File """ & scriptPath & """ -UseSavedToken -IntervalSeconds 30 -Count 0"
result = shell.Run(command, 0, True)
WScript.Quit result
