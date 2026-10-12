#!/bin/sh
# One-shot LubanCat 1H bring-up (Ubuntu 22.04 image). Run as root on the board; re-runnable.
set -e
cd "$(dirname "$0")"
pass() { echo "[PASS] $1"; }; fail() { echo "[FAIL] $1"; }
apt-get update -qq && apt-get install -y -qq python3-pygame python3-evdev python3-aiohttp python3-pil evtest >/dev/null && pass "packages"
for s in /sys/class/drm/card*-HDMI-A-*/status; do [ "$(cat "$s")" = connected ] && pass "HDMI connected ($s)" || fail "HDMI not connected ($s)"; done
python3 -c "import evdev,sys; d=[evdev.InputDevice(p) for p in evdev.list_devices()]; t=[x.name for x in d if evdev.ecodes.ABS_MT_POSITION_X in dict(x.capabilities().get(3,[]))]; print('[PASS] touch:',t) if t else print('[FAIL] no multitouch device; check USB cable to monitor touch port')"
sh ./hid_gadget.sh && [ -c /dev/hidg0 ] && pass "HID gadget /dev/hidg0" || fail "HID gadget"
cat > /etc/systemd/system/keyscreen.service <<EOF
[Unit]
Description=KeyScreen touch keyboard
After=graphical.target
[Service]
ExecStartPre=/bin/sh $(pwd)/hid_gadget.sh
ExecStart=/usr/bin/python3 $(pwd)/keyscreen.py
Environment=SDL_VIDEODRIVER=kmsdrm
Restart=always
RestartSec=2
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload && systemctl enable keyscreen >/dev/null && pass "systemd service enabled (systemctl start keyscreen)"
