#!/bin/bash
# Run on YOUR computer (WSL / Linux / macOS). Finds the LubanCat on the LAN, copies board/ and runs bringup.
#   ./deploy.sh [board-ip] [user]      default user: cat (password: temppwd)
set -e
cd "$(dirname "$0")"
USER_=${2:-cat}
SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=5 -o ControlMaster=auto -o ControlPath=/tmp/ks-%r@%h -o ControlPersist=300"
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY

# timeout: hosts that silently drop SYNs would otherwise hold the scan (and our stdout) for minutes.
banner() { timeout 2 bash -c 'exec 3<>"/dev/tcp/$0/22" && read -t 1 -r b <&3 && echo "$b"' "$1" 2>/dev/null; }

discover() {
  # Candidate /24 subnets: Windows adapters (via ipconfig.exe under WSL) plus our own.
  # Direct cable (169.254 link-local, Windows ICS 192.168.137) first so a big campus/office LAN can't win the race.
  for h in 192.168.137.2; do case "$(banner $h)" in *Ubuntu*|*Debian*) echo "$h"; return;; esac; done
  subs=$( { ipconfig.exe 2>/dev/null | tr -d '\r' | grep -aE "IPv4|默认网关|Default Gateway" | grep -aoE '([0-9]{1,3}\.){3}[0-9]{1,3}'; hostname -I 2>/dev/null | tr ' ' '\n'; } | grep -vE '^(127|198\.18|172\.(1[6-9]|2[0-9]|3[01])\.)' | sed -E 's/\.[0-9]+$//' | sort -u | awk '/^169\.254|^192\.168\.137/{print; next} {rest=rest $0 "\n"} END{printf "%s", rest}')
  for s in $subs; do
    echo "   扫描 $s.0/24 ..." >&2
    h=$(for i in $(seq 1 254); do ( case "$(banner "$s.$i")" in *Ubuntu*|*Debian*) echo "$s.$i";; esac ) & done; wait)
    [ -n "$h" ] && { echo "$h" | head -1; return; }
  done
}

HOST=$1
case "$HOST" in ""|lubancat*) echo "== 1/3 在局域网里找板子"; HOST=$(discover); [ -n "$HOST" ] || { echo "没找到。请在板子屏幕上/路由器里看板子的 IP，然后运行: ./deploy.sh <IP>"; exit 1; };; esac
echo "   板子 IP: $HOST"
echo "== 2/3 拷贝程序（只需输一次密码 temppwd）"
# Boards without internet (Debian 10 vendor image) install pygame/aiohttp from these wheels.
[ -n "$(ls board/wheels/*.whl 2>/dev/null)" ] || python3 board/fetch_wheels.py || echo "   (wheels 下载失败，板子需自行联网 apt 安装)"
ssh $SSH_OPTS "$USER_@$HOST" "mkdir -p ~/keyscreen"
scp $SSH_OPTS -r board desktop/web "$USER_@$HOST:~/keyscreen/"
echo "== 3/3 板上自检"
# KS_PASS=temppwd ./deploy.sh  -> sudo without a tty prompt
SUDO="sudo"; [ -n "$KS_PASS" ] && SUDO="echo '$KS_PASS' | sudo -S -p ''"
ssh $SSH_OPTS -t "$USER_@$HOST" "cd ~/keyscreen/board && sed -i 's/\r\$//' *.sh *.py && $SUDO sh bringup.sh && $SUDO systemctl restart keyscreen && sleep 5 && systemctl is-active keyscreen && curl -s localhost:8765/api/state | head -c 120; echo"
ssh $SSH_OPTS -O exit "$USER_@$HOST" 2>/dev/null || true
echo "完成。浏览器打开客户端: http://$HOST:8765/ui/"
echo "（需要按前台应用自动切换 Profile 时再运行: python3 desktop/panel.py --board http://$HOST:8765）"
