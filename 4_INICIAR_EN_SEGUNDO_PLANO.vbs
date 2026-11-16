Set WshShell = CreateObject("WScript.Shell")
currentDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
coreDir = currentDir & "\core"
botScript = coreDir & "\bot.py"
cmdToRun = "powershell -WindowStyle Hidden -Command ""Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine = 'pythonw.exe """ & botScript & """'; CurrentDirectory = '""" & coreDir & """'}"""
WshShell.Run cmdToRun, 0, False
Set WshShell = Nothing