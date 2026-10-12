#!/bin/sh
# One-shot LubanCat 1H bring-up (Ubuntu 22.04 or the Debian 10 vendor image). Run as root on the board; re-runnable.
set -e
cd "$(dirname "$0")"
pass() { echo "[PASS] $1"; }; fail() { echo "[FAIL] $1"; }
export PYGAME_HIDE_SUPPORT_PROMPT=1
deps_ok() { python3 -c "import pygame,evdev,aiohttp,PIL,sys; sys.exit(pygame.version.vernum[0] < 2)" 2>/dev/null; }
if ! deps_ok && timeout 5 getent hosts deb.debian.org >/dev/null 2>&1; then
  timeout 120 apt-get update -qq >/dev/null 2>&1 || true
  timeout 300 apt-get install -y -qq python3-evdev python3-pil python3-pygame python3-aiohttp evtest >/dev/null 2>&1 || true
fi
if ! deps_ok && ls wheels/*.whl >/dev/null 2>&1; then
  # pip on Debian 10 is too old for manylinux2014 tags; these wheels have no entry points, so unzipping is enough.
  SITE=$(python3 -c "import sys; print('/usr/local/lib/python%d.%d/dist-packages' % sys.version_info[:2])"); mkdir -p "$SITE"
  for w in wheels/*.whl; do python3 -m zipfile -e "$w" "$SITE"; done
fi
deps_ok && pass "packages (pygame $(python3 -c 'import pygame; print(pygame.version.ver)' 2>/dev/null))" || fail "packages: need pygame>=2, evdev, aiohttp, pillow (no internet? run board/fetch_wheels.py on the PC first)"
for s in /sys/class/drm/card*-HDMI-A-*/status; do [ "$(cat "$s")" = connected ] && pass "HDMI connected ($s)" || fail "HDMI not connected ($s)"; done
# Leftover FluxBoard services on this board grab the touchscreen, the UDC, the HDMI output and port 8765.
for u in fluxboard-upload fluxboard-touch-hid fluxboard-hid fluxboard-display fluxboard-display-watch fluxboard-display-retry.timer fluxboard-usb-gadget fluxboard-usb-net; do
  systemctl list-unit-files "$u*" 2>/dev/null | grep -q "^$u" && { systemctl disable --now "$u" >/dev/null 2>&1 || true; echo "       disabled $u"; }
done
python3 -c "import evdev,sys; d=[evdev.InputDevice(p) for p in evdev.list_devices()]; t=[x.name for x in d if evdev.ecodes.ABS_MT_POSITION_X in dict(x.capabilities().get(3,[]))]; print('[PASS] touch:',t) if t else print('[FAIL] no multitouch device; check USB cable to monitor touch port')"
sh ./hid_gadget.sh && [ -c /dev/hidg0 ] && pass "HID gadget /dev/hidg0" || fail "HID gadget"
if [ -e /var/run/lightdm/root/:0 ] || pgrep -x Xorg >/dev/null; then
  VIDEO="Environment=SDL_VIDEODRIVER=x11
Environment=DISPLAY=:0
Environment=XAUTHORITY=/var/run/lightdm/root/:0
ExecStartPre=-/bin/sh -c 'for i in 1 2 3 4 5 6 7 8 9 10; do [ -e /tmp/.X11-unix/X0 ] && exit 0; sleep 1; done'"
else
  VIDEO="Environment=SDL_VIDEODRIVER=kmsdrm"
fi
cat > /etc/systemd/system/keyscreen.service <<EOF
[Unit]
Description=KeyScreen touch keyboard
After=lightdm.service rockchip.service
[Service]
ExecStartPre=/bin/sh $(pwd)/hid_gadget.sh
ExecStart=/usr/bin/python3 $(pwd)/keyscreen.py
Environment=PYTHONUNBUFFERED=1 PYGAME_HIDE_SUPPORT_PROMPT=1
$VIDEO
Restart=always
RestartSec=2
TimeoutStopSec=5
[Install]
WantedBy=graphical.target
EOF
systemctl daemon-reload && systemctl enable keyscreen >/dev/null 2>&1 && pass "systemd service enabled (systemctl start keyscreen)"
