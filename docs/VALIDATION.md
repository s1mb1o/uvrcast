# Validation record

Hardware tests were performed on 2026-11-10 by Alexander Shmelev with an
original analog Blackmagic USB Video Recorder on Ubuntu 22.04 x86_64, kernel
6.8.0-138-generic. The firmware resources came from vendor application 1.0.1.

External composite PAL capture, requested 720x576 at 2 Mbps:

- Raw QBOX: 989,307 bytes; every box ends on a valid boundary, including EOF.
- 317 H.264 picture samples, continuous 3600/90000-second timestamps (25 fps).
- 593 AAC-LC stereo samples, continuous 1920/90000-second timestamps, 48 kHz.
- About 12.7 seconds of media within the 15-second initialization/capture limit.
- Actual encoded size: 720x288, sample aspect ratio 1:2, display aspect 5:4.
- The extracted picture visibly contained the external television source.
- FFprobe sample counts matched; a full FFmpeg `-xerror` decode passed with
  no errors. The audio was mostly quiet; program audibility was not verified.

Internal decoder picture test:

- Raw QBOX: 178,227 bytes.
- 340 decoded H.264 pictures at 25 fps, encoded size 720x288.
- 636 AAC samples, stereo 48 kHz; full decode passed without errors.

Original SPS timing reported 30000/1001 fps while QBOX timestamps showed 25
fps. MP4 conversion uses the QBOX clock and corrects the copied timing header;
it does not re-encode pictures or sound. Earlier tests had zero data despite
input lock. These results establish successful capture examples, not sustained
reliability, full-height capture or support for other devices/standards.

Personal recordings, source screenshots, USB topology and raw host logs are
not included in this public source package.

## Offline checks

After `python3 build.py`, run `python3 tests/run-offline.py`.
Five checks use mocked USB calls and synthetic temporary fixtures, without
opening a real device or requiring vendor firmware. The optional real-image
loader check needs locally supplied MG1264 firmware and prodcfg17.bin:

```sh
python3 tests/run-offline.py \
  --real-firmware firmware/cap.qmmapp.seve1-eb-16mb.bin \
  --product-config '/path/to/Blackmagic Video Recorder.app/Contents/Resources/prodcfg17.bin'
```

Synthetic fixtures are only for these USB mocks and must never be used as
device firmware. The real-image check is explicitly skipped by default.
