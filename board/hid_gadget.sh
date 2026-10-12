#!/bin/sh
# Configure LubanCat 1H OTG port as a USB boot keyboard (/dev/hidg0) via configfs. Run as root.
# Ubuntu image: creates its own 'keyscreen' gadget. Debian vendor image: the kernel only allows the vendor
# 'rockchip' gadget (mkdir of a second gadget oopses), so HID is added to it as an extra function. Never rmdir.
set -e
CFS=/sys/kernel/config
DESC=05010906a101050719e029e71500250175019508810295017508810395057501050819012905910295017503910395067508150025650507190029658100c0  # boot keyboard
modprobe libcomposite 2>/dev/null || true
mountpoint -q $CFS || mount -t configfs none $CFS
UDC=$(ls /sys/class/udc | head -n1)
[ -n "$UDC" ] || { echo "no UDC: set OTG to peripheral (dr_mode=peripheral) in device tree overlay"; exit 1; }
if [ -x /etc/init.d/rockchip.sh ]; then
  for i in $(seq 1 20); do [ -d $CFS/usb_gadget/rockchip/configs ] && break; sleep 1; done
fi
G=$(ls -d $CFS/usb_gadget/* 2>/dev/null | head -n1)
[ -n "$G" ] || G=$CFS/usb_gadget/keyscreen
F=$G/functions/hid.usb0
linked() { ls -l "$G"/configs/*/ 2>/dev/null | grep -q 'hid.usb0$'; }
desc_ok() { [ "$(od -An -tx1 -v "$F/report_desc" 2>/dev/null | tr -d ' \n')" = "$DESC" ]; }
if [ -c /dev/hidg0 ] && [ -n "$(cat "$G/UDC" 2>/dev/null)" ] && linked && desc_ok; then
  chmod 666 /dev/hidg0; echo "ok: /dev/hidg0 already on $(cat "$G/UDC") ($(basename "$G"))"; exit 0
fi
if [ ! -d "$G" ]; then
  mkdir -p "$G"
  echo 0x1d6b > $G/idVendor; echo 0x0104 > $G/idProduct; echo 0x0100 > $G/bcdDevice; echo 0x0200 > $G/bcdUSB
  mkdir -p $G/configs/c.1/strings/0x409; echo "HID" > $G/configs/c.1/strings/0x409/configuration; echo 100 > $G/configs/c.1/MaxPower
fi
C=$(ls -d "$G"/configs/*/ | head -n1); C=${C%/}
# The vendor usb-hotplug rule rebinds ~1 s after any unbind, so everything up to the bind runs without sleeping.
[ -z "$(cat "$G/UDC")" ] || echo "" > "$G/UDC"
for l in "$C"/*; do [ -L "$l" ] && [ "$(basename "$(readlink "$l")")" = hid.usb0 ] && rm "$l"; done  # f_hid attrs are EBUSY while linked
mkdir -p $G/strings/0x409 $F
echo "KS0001" > $G/strings/0x409/serialnumber; echo "KeyScreen" > $G/strings/0x409/manufacturer; echo "KeyScreen Touch Keyboard" > $G/strings/0x409/product
echo 1 > $F/protocol; echo 1 > $F/subclass; echo 8 > $F/report_length
python3 -c "import sys; sys.stdout.buffer.write(bytes.fromhex('$DESC'))" > $F/report_desc  # dash printf has no \x escapes
n=1; while [ -e $C/f$n ]; do n=$((n + 1)); done
ln -s $F $C/f$n
echo "$UDC" > $G/UDC 2>/dev/null || [ "$(cat $G/UDC)" = "$UDC" ]
sleep 1
desc_ok || { echo "report_desc not applied"; exit 1; }
chmod 666 /dev/hidg0
echo "ok: /dev/hidg0 on $UDC ($(basename "$G"))"
