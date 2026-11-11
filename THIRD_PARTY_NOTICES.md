# Third-party notices

## crusher264

Original author: tipok / piratfm. Source: https://github.com/piratfm/crusher264
at commit `19dd075e658dc1f78934e8f703d8fb14f6746e35`.
License: GNU General Public License version 2. The original COPYING.GPL is
preserved; LICENSE is an identical copy for repository discovery. Retain the
original copyright, license and warranty notices. The upstream commit is
recorded for provenance; this independent repository does not import the
original Git history.

## libusb-compat-0.1

Source: https://github.com/libusb/libusb-compat-0.1
at commit `4831748a1439aec81e9cbb9984b1b0289c1c7051`.
The included implementation headers/source state LGPL-2.1-or-later; the
package's LICENSE also describes the alternative BSD license for usb.h.
Keep the full original files under vendor/libusb-compat, including COPYING,
LICENSE and their per-file copyright/license notices.

## libusb-1.0 header

Source: https://github.com/libusb/libusb/tree/v1.0.25
at `libusb/libusb.h`, included as vendor/libusb-compat/libusb.h.
License: LGPL-2.1-or-later, as stated in the header. Runtime linking uses the
system libusb-1.0 shared library; that runtime is not bundled here.

## FFmpeg

FFmpeg/FFprobe are optional external executables for conversion and media
validation. This repository does not bundle FFmpeg binaries or source.

## Firmware and application

No redistribution permission for the vendor firmware/application was
established for this publication. Neither firmware payloads nor the Mac app
are included or relicensed. A local import helper accepts user-supplied files.
