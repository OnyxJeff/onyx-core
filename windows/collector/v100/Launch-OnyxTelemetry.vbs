Option Explicit
' v1.0.0 scheduled collector: fixed executable, adjacent collector, no token input.
Dim shell, fso, ps, scriptPath, command, arg, i, result
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
ps = fso.BuildPath(fso.GetSpecialFolder(1), "WindowsPowerShell\v1.0\powershell.exe")
scriptPath = fso.BuildPath(fso.GetParentFolderName(WScript.ScriptFullName), "Send-OnyxTelemetry-v100.ps1")
If Not fso.FileExists(ps) Or Not fso.FileExists(scriptPath) Then WScript.Quit 2
If WScript.Arguments.Count = 0 Or WScript.Arguments.Count > 32 Then WScript.Quit 2
command = QuoteArg(ps) & " -NoProfile -NonInteractive -ExecutionPolicy Bypass -File " & QuoteArg(scriptPath) & " -RequireLauncher"
For i = 0 To WScript.Arguments.Count - 1
    arg = WScript.Arguments.Item(i)
    command = command & " " & QuoteArg(arg)
Next
If Len(command) > 1800 Then WScript.Quit 2
result = shell.Run(command, 0, True)
WScript.Quit result

Function QuoteArg(value)
    Dim j, code
    If Len(value) = 0 Or Len(value) > 512 Then WScript.Quit 2
    ' WScript.Shell.Run expands environment variables; refuse expansion and
    ' ambiguous native quoting, including trailing backslashes and controls.
    If InStr(value, Chr(34)) Or InStr(value, "%") Or Right(value, 1) = "\" Then WScript.Quit 2
    For j = 1 To Len(value)
        code = AscW(Mid(value, j, 1))
        If code < 32 Or code = 127 Then WScript.Quit 2
    Next
    QuoteArg = Chr(34) & value & Chr(34)
End Function
