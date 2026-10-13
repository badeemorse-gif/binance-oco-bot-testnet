' OCOBot GUI launcher (G1.16 / G-LAUNCH-01) - opens the interface with no console window.
' Runs: pythonw -m ocobot.ui.app  from the project root (this file's folder).
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
projectRoot = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = projectRoot
sh.Run "pythonw -m ocobot.ui.app", 0, False
