#!/usr/bin/env bash
# Run explicitly on the physical host only if recorder udev ownership is missing.
set -euo pipefail
if [[ $# -ne 2 || ! $1 =~ ^[1-9][0-9]*$ || ! $2 =~ ^(0|[1-9][0-9]*)$ ]]; then
  echo 'Usage: sudo bash docker/usb-access.sh RECORDER_UID RECORDER_GID' >&2
  exit 2
fi
if [[ $EUID -ne 0 ]]; then
  echo 'Run this host udev setup with sudo.' >&2
  exit 1
fi
rules=/etc/udev/rules.d/99-blackmagic-recorder-docker.rules
if [[ -e $rules ]]; then
  cp --preserve=mode "$rules" "$rules.bak.$(date +%Y%m%d%H%M%S)"
fi
cat > "$rules" <<EOF
SUBSYSTEM=="usb", ATTR{idVendor}=="04b4", ATTR{idProduct}=="8613", OWNER="$1", GROUP="$2", MODE="0600"
SUBSYSTEM=="usb", ATTR{idVendor}=="04b4", ATTR{idProduct}=="bd1c", OWNER="$1", GROUP="$2", MODE="0600"
EOF
chmod 0644 "$rules"
udevadm control --reload-rules
udevadm trigger --action=add --subsystem-match=usb --attr-match=idVendor=04b4 --attr-match=idProduct=8613
udevadm trigger --action=add --subsystem-match=usb --attr-match=idVendor=04b4 --attr-match=idProduct=bd1c
udevadm settle
echo "Recorder USB nodes will belong to UID $1, GID $2."
