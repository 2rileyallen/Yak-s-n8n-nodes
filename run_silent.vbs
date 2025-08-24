' This script runs a command passed to it without opening a visible window.
Set WshShell = CreateObject("WScript.Shell")

' Check if an argument was provided
If WScript.Arguments.Count > 0 Then
    ' The entire command (e.g., "cmd /c my_script.bat") is the first argument
    commandToRun = WScript.Arguments(0)
    
    ' The "Run" method can handle a full command string correctly.
    ' The '0' hides the window, and 'False' tells the script not to wait for the command to finish.
    WshShell.Run commandToRun, 0, False
End If