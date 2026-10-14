#!/usr/bin/env bash
# One-click demo: MHS device bridge + AGH workbench + desktop panel (the "software" for the show).
#   BOARD=http://169.254.220.2:8765 ./demo.sh        # stop: ./demo.sh stop
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$HERE/../.." && pwd)"
BOARD="${BOARD:-http://169.254.220.2:8765}"; HUB="${HUB:-ws://127.0.0.1:4180}"
export HOME="${HOME:-/home/lenovo}" AGNES_HUB_ORIGIN="${AGNES_HUB_ORIGIN:-http://127.0.0.1:4180}"
export PYTHONPATH="$ROOT/agnes-harness/packages/mhs/python/src${PYTHONPATH:+:$PYTHONPATH}"
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY
LOG=/tmp/keyscreen-demo; mkdir -p "$LOG"

if [[ "${1:-}" == "stop" ]]; then
  pkill -f "demo.sh watch"; pkill -f "board/mhs_device.py" ; pkill -f "desktop/panel.py" ; pkill -f "agnes.mjs serve"; echo stopped; exit 0
fi
# Plug-and-play: started at Windows logon (Startup\KeyScreen.vbs); brings everything up whenever the board appears.
if [[ "${1:-}" == "watch" ]]; then
  exec >>"$LOG/watch.log" 2>&1
  exec 9>"$LOG/watch.lock"; flock -n 9 || { echo "$(date '+%F %T') watcher already running"; exit 0; }
  while true; do
    if curl -s -m 2 "$BOARD/api/state" >/dev/null && ! pgrep -f "desktop/panel.py" >/dev/null; then
      echo "$(date '+%F %T') board up -> starting"; "$0" start
    fi
    sleep 5
  done
fi
curl -s -m 3 "$BOARD/api/state" >/dev/null || { echo "板子不可达：$BOARD（检查网线/地址）"; exit 1; }
# The board has no RTC battery/NTP on a direct cable: copy the PC clock so the bar and schedule are right.
H="${BOARD#http://}"; H="${H%%:*}"
ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=3 "cat@$H" \
  "echo ${KS_PASS:-temppwd} | sudo -S -p '' date -s @$(date +%s) >/dev/null" 2>/dev/null || echo "（板子时钟同步失败，可忽略）"
# AgnesHub lives inside the AGH daemon; any CLI call starts the daemon after a WSL restart.
curl -s -m 2 http://127.0.0.1:4180/ >/dev/null || (cd "$ROOT/agnes-harness" && "$ROOT/scripts/agh.sh" package status >/dev/null 2>&1)
pgrep -f "agnes.mjs serve" >/dev/null || { (cd "$HERE" && nohup setsid "$ROOT/scripts/agh.sh" serve --home "$ROOT/.agh" --profile local-dev --cwd "$HERE" --port 43117 >"$LOG/agh.log" 2>&1 </dev/null &) ; }
# panel.py also supervises the keyscreen-01 MHS bridge, the on-screen chat, foreground-app hints and the weather line.
pgrep -f "desktop/panel.py" >/dev/null || { nohup setsid python3 -u "$HERE/desktop/panel.py" --board "$BOARD" --hub "$HUB" >"$LOG/panel.log" 2>&1 </dev/null & }
sleep 4
curl -s -m 3 http://127.0.0.1:4180/ >/dev/null && echo "AgnesHub      http://127.0.0.1:4180/   (设备 keyscreen-01)" || echo "AgnesHub 未监听 4180：先 scripts/agh.sh package status 看 @agnes/mhs 是否 enabled"
echo "演示软件      http://127.0.0.1:43125/  <- 打开这个"
echo "AGH 工作台    http://127.0.0.1:43117/"
echo "板端客户端    $BOARD/ui/"
echo "日志 $LOG/   停止 ./demo.sh stop"
