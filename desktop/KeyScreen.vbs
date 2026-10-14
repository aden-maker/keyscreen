' Copy to shell:startup (install-autostart.ps1 does it). Starts the hidden KeyScreen watcher in WSL at logon:
' whenever the board is plugged in, the Agnes bridge, chat, weather and desktop panel come up by themselves.
CreateObject("WScript.Shell").Run "wsl.exe -d Ubuntu -- bash /home/lenovo/keyscreen/work/keyscreen/demo.sh watch", 0, False
