#!/bin/bash
# Run on YOUR computer (WSL / Linux / macOS). Finds the LubanCat on the LAN, copies board/ and runs bringup.
#   ./deploy.sh [board-ip] [user]      default user: cat (password: temppwd)
set -e
cd "$(dirname "$0")"
USER_=${2:-cat}
SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=5 -o ControlMaster=auto -o ControlPath=/tmp/ks-%r@%h -o ControlPersist=300"
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY

banner() { exec 3<>"/dev/tcp/$1/22" 2>/dev/null && read -t 1 -r b <&3 && exec 3<&- && echo "$b"; } 2>/dev/null

discover() {
  # Candidate /24 subnets: Windows adapters (via ipconfig.exe under WSL) plus our own.
  subs=$( { ipconfig.exe 2>/dev/null | tr -d '\r' | grep -E "IPv4|默认网关|Default Gateway" | grep -oE '([0-9]{1,3}\.){3}[0-9]{1,3}'; hostname -I 2>/dev/null | tr ' ' '\n'; } | grep -vE '^(127|198\.18|172\.(1[6-9]|2[0-9]|3[01])\.)' | sed -E 's/\.[0-9]+$//' | sort -u)
  for s in $subs; do
    echo "   扫描 $s.0/24 ..." >&2
    for i in $(seq 1 254); do ( b=$(banner "$s.$i"); case "$b" in *Ubuntu*|*Debian*) echo "$s.$i";; esac ) & done
    wait
  done | head -1
}

HOST=$1
case "$HOST" in ""|lubancat*) echo "== 1/3 在局域网里找板子"; HOST=$(discover); [ -n "$HOST" ] || { echo "没找到。请在板子屏幕上/路由器里看板子的 IP，然后运行: ./deploy.sh <IP>"; exit 1; };; esac
echo "   板子 IP: $HOST"
echo "== 2/3 拷贝程序（只需输一次密码 temppwd）"
ssh $SSH_OPTS "$USER_@$HOST" "mkdir -p ~/keyscreen"
scp $SSH_OPTS -r board "$USER_@$HOST:~/keyscreen/"
echo "== 3/3 板上自检"
ssh $SSH_OPTS -t "$USER_@$HOST" "cd ~/keyscreen/board && sed -i 's/\r\$//' *.sh *.py && sudo sh bringup.sh && sudo systemctl restart keyscreen && sleep 3 && systemctl is-active keyscreen && curl -s localhost:8765/api/state | head -c 120; echo"
echo "完成。电脑上运行: python3 desktop/panel.py --board http://$HOST:8765  然后打开 http://127.0.0.1:43125"
