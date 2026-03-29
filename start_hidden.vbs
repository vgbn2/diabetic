Set WshShell = CreateObject("WScript.Shell")

' 0 = Hidden Window
' True = Wait for script to finish (keep the VBS process alive until runner finishes)
WshShell.Run "cmd /c run_live.bat", 0, True
