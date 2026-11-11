# uvrcast

Linux capture and WebRTC streaming for the original USB Video Recorder, with
a userspace driver, MPEG-TS output, and Docker Compose deployment.

An independent community continuation of the original **crusher264**
userspace driver by **tipok / piratfm**, with experimental Linux compatibility
updates. The original author implemented the
MG1264/MG3500 protocol, capture support, firmware loader and sample programs.
This project maintains that work; it is not an official Blackmagic driver.

- Original source: [piratfm/crusher264](https://github.com/piratfm/crusher264)
- Original project: [tipok.org.ua/node/13](https://tipok.org.ua/node/13)
- Linux port maintenance and capture validation: [Alexander Shmelev (s1mb1o)](https://github.com/s1mb1o)
- [Credits](CREDITS.md), [license](LICENSE), [changes](CHANGELOG.md)

## Supported hardware and current result

The tested device is the original analog **Blackmagic USB 2.0 Video Recorder**
with an MG1264 encoder. This is not an Intensity Shuttle, UltraStudio,
DeckLink or H.264 Pro Recorder driver. It does not create a V4L2 `/dev/video*`
device.

Tested on Ubuntu 22.04, x86_64, kernel 6.8.0-138-generic. A composite PAL
recording produced 317 H.264 pictures at 25 fps and 593 AAC-LC stereo samples
at 48 kHz; the complete converted recording decoded without errors. An
internal decoder test-picture capture also decoded successfully. Browser
WebRTC playback was verified on 2026-11-11 with a visible test pattern, H.264
video and Opus audio tracks, advancing capture counters at 25 fps, and a
healthy HTTP endpoint. Audible program sound and end-to-end latency were not
measured.

**Actual encoded PAL resolution is 720x288**, even when the requested profile
is 720x576. The inherited capture path uses field coding/vertical decimation.
Full-height capture, NTSC hardware capture, other operating systems and long
or repeated recordings are not verified. Earlier initialization attempts
stalled; the exact cause of that intermittent behavior is not established.
The presence of decoded audio does not establish useful program sound in the
mostly quiet test source. See [validation details](docs/VALIDATION.md).

## Build

On Ubuntu 22.04:

```sh
sudo apt install build-essential python3 libusb-1.0-0 ffmpeg
python3 build.py
./build/bin/crusher264 --help
python3 tests/run-offline.py
```

The build currently targets little-endian x86_64 Linux. It uses bundled
libusb compatibility sources and the system libusb-1.0 runtime. Build output
stays under `build/`; nothing is installed into system library directories.
The old Autotools files remain for provenance; `build.py` is the tested route.

## Supply firmware locally

Firmware and the vendor Mac application are **not included**. From a copy of
Blackmagic Video Recorder.app that you are entitled to use:

```sh
python3 tools/import-firmware.py '/path/to/Blackmagic Video Recorder.app'
```

This copies two resource files to the ignored `firmware/` directory. It does
not execute the application or download anything. See
[firmware instructions](firmware/README.md) for filenames and tested hashes.

## Capture

Connect composite/CVBS video to the green video connector. Analog audio uses
the separate audio inputs. Activate the source before recording.

```sh
sudo bash ./test-recorder.sh composite pal full reload
```

The test has a 15-second overall limit, including initialization. Exit status
124 from `timeout` is expected when that limit ends the capture. Results go to
a new ignored directory under `tests/capture-*/`. Nonempty captures are
converted automatically to MP4 if FFmpeg is available; actual encoded
dimensions are reported. Newly created result files are returned to the
invoking sudo user's ownership.

Input options: `composite`, `s-video`, `component`. Standard: `pal` or `ntsc`.
Optional flags, in any order after those two arguments:

- `full`: request 720x576 PAL or 720x480 NTSC at 2 Mbps. This is a requested
  profile, not a guarantee of encoded dimensions.
- `reload`: replace the FX2 RAM firmware once and reopen after enumeration.
  It does not program EEPROM.
- `blue`: force the ADV7180's internal blue picture for diagnostics. A normal
  run clears forced-picture mode; unplugging power also clears volatile state.

The default smaller request is 352x288 PAL or 320x240 NTSC at 1.5 Mbps.
Unprivileged capture requires USB device permissions; otherwise use the sudo
command above. The driver detaches `usbtest` if it owns interface 0 of the
uninitialized capture device.

To convert an existing, not-yet-converted raw recording:

```sh
python3 convert-capture.py /path/to/capture.qbox
```

The converter preserves the QBOX file, extracts H.264/AAC, creates MP4 without
re-encoding picture/audio data, and checks sample counts using FFprobe. It
uses capture timestamps to correct timing metadata. It supports this recorder's
version-0, constant-rate H.264/AAC-LC QBOX format. Existing output files are not
replaced; use `--output-dir DIRECTORY` for another copy.

## Live streaming and Docker

The streaming service captures the recorder once and shares H.264 video over
WebRTC and HTTP MPEG-TS. Only AAC audio is converted to Opus for WebRTC.
It includes media health checks, bounded viewer queues, capture watchdog
recovery, and an optional migration from the native systemd installation.

After supplying firmware locally as described above, on the physical x86_64
Linux recorder host with Docker Engine and Compose:

```sh
cd stream-service
cp -n .env.example .env
# Edit .env: set RACK_IP to the host's LAN address and match its USB owner's UID/GID.
python3 docker/start.py
```

If the native recorder services are already installed, use
`python3 docker/start.py --replace-native` to migrate them after the image
build completes. The launcher restores their previous state if container
startup fails and the new stack can be stopped.

Open `http://RACK_IP:18889/usb/` for WebRTC. HTTP MPEG-TS is available at
`http://RACK_IP:18890/0.ts`, capture status at `/api/status`, and media health
at `/health`. The stream's actual coded PAL dimensions remain 720x288.
Intermittent capture initialization stalls remain under investigation; a
successful session does not establish repeatability.

See the [streaming guide](stream-service/README.md) for native installation,
ports, recovery settings, STB-rack compatibility, logs, and Docker smoke tests.
Firmware, recordings, runtime state, and downloaded gateway binaries are not
part of this repository. The Docker image is built locally after firmware import.

Run the portable streaming checks without USB:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s stream-service/tests -v
```

Six additional recording integration checks run when `UVRCAST_TEST_FIXTURE`
points to the known local QBOX fixture; that recording is not distributed.
Image building and live USB capture from Docker have not been verified in
this restricted session. Native browser streaming has been verified.

## License and attribution

The driver and this port are distributed under **GNU GPL version 2**, retaining
the original [COPYING.GPL](COPYING.GPL). New port scripts/tests use GPL-2.0-only.
Vendored libusb files retain their own LGPL/BSD notices and license texts; see
[third-party notices](THIRD_PARTY_NOTICES.md). Firmware is outside this source
license and is supplied separately by the user.

This project is published as an independent repository. Its upstream source,
base revision, author credits and original notices remain documented. See
[publication instructions](docs/PUBLISHING.md).
