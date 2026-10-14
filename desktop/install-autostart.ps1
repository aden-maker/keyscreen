# Installs the plug-and-play watcher into the current user's Startup folder and starts it now.
$dst = Join-Path ([Environment]::GetFolderPath('Startup')) 'KeyScreen.vbs'
Copy-Item -Force (Join-Path $PSScriptRoot 'KeyScreen.vbs') $dst
Start-Process wscript.exe -ArgumentList "`"$dst`""
Write-Host "installed: $dst"
