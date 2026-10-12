#!/bin/sh
# Configure LubanCat 1H OTG port as a USB boot keyboard (/dev/hidg0) via configfs. Run as root.
set -e
G=/sys/kernel/config/usb_gadget/keyscreen
modprobe libcomposite 2>/dev/null || true
mountpoint -q /sys/kernel/config || mount -t configfs none /sys/kernel/config
[ -d "$G" ] && { echo "gadget exists"; exit 0; }
mkdir -p "$G" && cd "$G"
echo 0x1d6b > idVendor; echo 0x0104 > idProduct; echo 0x0100 > bcdDevice; echo 0x0200 > bcdUSB
mkdir -p strings/0x409
echo "KS0001" > strings/0x409/serialnumber; echo "KeyScreen" > strings/0x409/manufacturer; echo "KeyScreen Touch Keyboard" > strings/0x409/product
mkdir -p configs/c.1/strings/0x409; echo "HID" > configs/c.1/strings/0x409/configuration; echo 100 > configs/c.1/MaxPower
mkdir -p functions/hid.usb0
echo 1 > functions/hid.usb0/protocol; echo 1 > functions/hid.usb0/subclass; echo 8 > functions/hid.usb0/report_length
printf '\x05\x01\x09\x06\xa1\x01\x05\x07\x19\xe0\x29\xe7\x15\x00\x25\x01\x75\x01\x95\x08\x81\x02\x95\x01\x75\x08\x81\x03\x95\x05\x75\x01\x05\x08\x19\x01\x29\x05\x91\x02\x95\x01\x75\x03\x91\x03\x95\x06\x75\x08\x15\x00\x25\x65\x05\x07\x19\x00\x29\x65\x81\x00\xc0' > functions/hid.usb0/report_desc
ln -s functions/hid.usb0 configs/c.1/
UDC=$(ls /sys/class/udc | head -n1)
[ -n "$UDC" ] || { echo "no UDC: set OTG to peripheral (dr_mode=peripheral) in device tree overlay"; exit 1; }
echo "$UDC" > UDC
chmod 666 /dev/hidg0
echo "ok: /dev/hidg0 on $UDC"
