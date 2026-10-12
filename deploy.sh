#!/bin/sh
# Run on YOUR computer (Linux/macOS/Windows Git Bash). Copies board/ to the LubanCat over the LAN and runs bringup.
#   ./deploy.sh [board-ip-or-hostname] [user]      defaults: lubancat.local  cat   (password: temppwd)
set -e
cd "$(dirname "$0")"
HOST=${1:-lubancat.local}; USER=${2:-cat}
echo "== 1/3 找板子 $HOST"; ping -c1 -W2 "$HOST" >/dev/null 2>&1 || { echo "ping 不通。在路由器后台或电脑的 arp -a 里找板子的 IP，然后: ./deploy.sh <IP>"; exit 1; }
echo "== 2/3 拷贝程序（输密码 temppwd）"; ssh "$USER@$HOST" "mkdir -p ~/keyscreen" && scp -r board "$USER@$HOST:~/keyscreen/"
echo "== 3/3 板上自检"; ssh -t "$USER@$HOST" "cd ~/keyscreen/board && sudo sh bringup.sh && sudo systemctl restart keyscreen && sleep 3 && systemctl is-active keyscreen && curl -s localhost:8765/api/state | head -c 120; echo"
echo "完成。电脑上运行: python3 desktop/panel.py --board http://$HOST:8765  然后打开 http://127.0.0.1:43125"
