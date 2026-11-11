# Credits

## Original driver

**tipok / piratfm** is the original author of crusher264: the reverse-engineered
MG1264/MG3500 USB driver, codec control protocol, firmware-loading path, analog
capture support and original sample utilities.

- Source and commit history: https://github.com/piratfm/crusher264
- Original project page: https://tipok.org.ua/node/13
- Original Google Code project: https://code.google.com/archive/p/crusher264/
- Base commit: `19dd075e658dc1f78934e8f703d8fb14f6746e35`

All original source headers and COPYING.GPL are retained. Other upstream
contributors are acknowledged, including DHPollack, credited in an upstream
ARM build-fix commit. The upstream Git history remains available at the link
above. This independent repository starts from an imported source snapshot
and does not include or recreate those original commits. The initial import
must not be interpreted as authorship of the original driver.

## Linux compatibility work, November 2026

**Alexander Shmelev (s1mb1o)** maintains the Linux port and performed physical
recorder tests. This work adds a local build, USB access/error fixes, firmware
upload corrections, PAL/NTSC selection, diagnostic tooling, regression checks
and QBOX-to-MP4 conversion. It builds on the original driver rather than
claiming the original implementation as new work.

Modified upstream files carry dated change notices. See CHANGELOG.md and
docs/PROVENANCE.json for the base revision and scope.

The 2026-11-11 streaming service adds shared HTTP MPEG-TS capture, WebRTC
publishing through MediaMTX, Docker deployment, and capture recovery checks.
It copies the recorder's hardware H.264 output and relies on the original
driver for USB and encoder communication.

## Dependencies

The libusb and libusb-compat authors are credited in their retained source
headers and THIRD_PARTY_NOTICES.md. FFmpeg is an external runtime tool used for
remuxing and validation; no FFmpeg source or binaries are bundled.

Blackmagic Design is the device/application vendor. This community project is
not affiliated with or endorsed by Blackmagic Design. Vendor application and
firmware payloads are not included.
