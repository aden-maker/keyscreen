@echo off
rem Windows 版：在本机 cmd 里运行。把 board\ 拷到鲁班猫并执行自检。用法: deploy.bat [板子IP或主机名] [用户名]
rem 默认 lubancat.local / cat，密码 temppwd。需要 Windows 自带的 OpenSSH（Win10 1809+ 已内置）。
setlocal
cd /d "%~dp0"
set HOST=%1
if "%HOST%"=="" set HOST=lubancat.local
set USR=%2
if "%USR%"=="" set USR=cat
echo == 1/3 找板子 %HOST%
ping -n 1 -w 2000 %HOST% >nul 2>&1 || (echo ping 不通。运行 arp -a 找板子的 IP，然后: deploy.bat ^<IP^> & exit /b 1)
echo == 2/3 拷贝程序（提示输密码时输入 temppwd）
ssh %USR%@%HOST% "mkdir -p ~/keyscreen" || exit /b 1
scp -r board %USR%@%HOST%:~/keyscreen/ || exit /b 1
echo == 3/3 板上自检
ssh -t %USR%@%HOST% "cd ~/keyscreen/board && sed -i 's/\r$//' *.sh *.py && sudo sh bringup.sh && sudo systemctl restart keyscreen && sleep 3 && systemctl is-active keyscreen && curl -s localhost:8765/api/state | head -c 120; echo"
echo.
echo 完成。电脑上运行: python desktop\panel.py --board http://%HOST%:8765  然后打开 http://127.0.0.1:43125
endlocal
