#!/bin/sh
# No-hardware demo: board simulator (window, mouse = finger) + desktop panel + MHS device on the dev hub.
# Usage: ./sim.sh [--headless]    then open http://127.0.0.1:43125 and http://127.0.0.1:4191
cd "$(dirname "$0")"
MHS=../../agnes-harness/packages/mhs
export PATH="$HOME/.local/bin:/home/ubuntu/.nvm/versions/node/v24.21.0/bin:$PATH" KEYSCREEN_HOME="${KEYSCREEN_HOME:-$PWD/board/data}"
trap 'kill 0' EXIT INT TERM
python3 board/keyscreen.py --sim "$@" &
python3 desktop/panel.py --no-watch &
[ -z "$HUB" ] && (cd "$MHS" && pnpm dev-hub) &
sleep 4
(cd "$MHS/python" && uv run python "$OLDPWD/board/mhs_device.py" "${HUB:-ws://127.0.0.1:4191}") &
wait
