# uvrcast streaming service

This service captures the working USB recorder once and shares its video with
the STB-rack portal and browser viewers. It lives separately from the recorder
driver and does not modify the portal or assign a rack slot.

For the STB-rack **browser**, use **WebRTC** for the lower-delay path. The
hardware H.264 video is copied. AAC audio is converted to Opus because browser
WebRTC receivers support Opus rather than AAC. The existing STB-rack
`Watch STB` player can use the compatible HTTP MPEG-TS endpoint immediately;
that player retains its existing buffer settings. Native WebRTC inside
`Watch STB` requires a portal viewer change. The separate WebRTC viewer is
already provided by MediaMTX and can also be embedded with an iframe.

Direct RTP/UDP is a low-overhead alternative for a dedicated native receiver.
It is not a browser video URL. Actual end-to-end delay includes the recorder's
encoding delay and the viewer's buffering; no measured latency is claimed here.

## Docker on the physical rack host

The Compose stack runs capture, a MediaMTX **1.21.3** gateway, and an H.264-copy /
Opus publisher in three containers sharing one locally built image. It requires
Docker Engine with Compose on the **x86_64 Linux rack host**. The container uses
host networking for direct WebRTC ICE connectivity. Its unprivileged capture
user needs ownership of the USB nodes; this rack's native installation already
provides that through udev.

After importing firmware into the repository's `firmware/` directory, with
Docker daemon access on the physical recorder host:

```bash
cd ~/uvrcast/stream-service
cp -n .env.example .env
# Set RACK_IP to the real LAN address and RECORDER_UID / RECORDER_GID to the USB owner.
python3 docker/start.py --replace-native
```

Check `.env` first: `192.0.2.10` is a documentation example. `RACK_IP` is the LAN IPv4 address,
and `RECORDER_UID` / `RECORDER_GID` match the host account owning the recorder
(`id -u` / `id -g`). Docker daemon permission errors require running the command
from an account with Docker access, or using `sudo python3 docker/start.py
--replace-native` from this directory.

The launcher validates Compose, builds the image, then disables and stops the
three native recorder units before starting containers. It waits up to 120
seconds for media readiness. If startup fails, it removes this Compose stack
and restores the native units' previous enabled and running states. A failure
to remove containers is reported before attempting to restart native capture.
Without
`--replace-native`, it refuses to compete with enabled or running native units.
It does not change the STB-rack slot configuration. The existing native services
are not stopped by creating these files.

The Dockerfile compiles the current patched userspace driver and USB shim from
source, bundles the two extracted firmware files, and installs FFmpeg with Opus.
The build context excludes recordings, macOS installers, logs, local state, and
the host's installed gateway binary. Driver/shim source and licenses accompany
their compiled libraries in the image.

Only the capture container receives `/dev/bus/usb` and character-device access
for USB major 189. Binding the directory keeps newly enumerated FX2 device nodes
visible after firmware loading. All containers use a regular numeric UID, a
read-only root filesystem, dropped capabilities, and a writable temporary
directory. On a fresh host without recorder udev ownership, run this explicitly
with the same IDs as `.env` before starting:

```bash
sudo bash docker/usb-access.sh 1000 1000
```

This adds rules for only `04b4:8613` and `04b4:bd1c`. It is not needed when the
existing native udev rules already give the configured account access.

Container operation:

```bash
docker compose ps
docker compose logs --tail 100 -f capture publisher gateway
docker compose down
```

Capture health requires recent video and transport output. Publisher health
also requires the gateway's live H.264 and Opus tracks. The gateway control API
is bound to loopback **19997**, RTSP to loopback **18554**. LAN viewer endpoints
remain the ones listed below. `docker compose down` releases the recorder; its
native services stay disabled after a successful migration.

Edit `docker/stream.json` for capture settings and restart `capture` and
`publisher`. Edit `docker/mediamtx.yml` for gateway settings. To rebuild after
source changes, run `python3 docker/start.py` again. To return to the native
installation:

```bash
docker compose down
sudo systemctl enable --now blackmagic-recorder.service blackmagic-recorder-gateway.service blackmagic-recorder-webrtc.service
```

After building, an offline container smoke test can decode a mounted recording
and exercise H.264-copy / Opus conversion without opening USB or networking:

```bash
docker run --rm --network none --read-only --tmpfs /tmp:size=64m,mode=1777 \
  --mount "type=bind,src=$(realpath ../tests/capture-OWdSCyCp/capture.qbox),dst=/fixtures/capture.qbox,readonly" \
  uvrcast:local \
  python3 /opt/blackmagic-recorder/stream-service/docker/smoke.py /fixtures/capture.qbox
```

The expected fixture result is **317 video frames, 593 audio frames, 720×288**,
with WebRTC codec output `h264` and `opus`.

## Native installation on the physical rack host

Run after any manual recorder test has finished:

```bash
sudo python3 ~/uvrcast/stream-service/install.py \
  --apply --user ashmelev --webrtc-host 192.0.2.10
```

The installer checks the existing capture utility, FFmpeg, Python, `stdbuf`,
and FFmpeg's Opus encoder. It downloads the official MediaMTX **v1.21.3**
Linux amd64 release and verifies its pinned archive SHA-256 before extracting
the executable. The normal host needs Internet access for that first download.
No video encoder package, Docker image, or alternate recorder driver is installed.

It writes:

- `/etc/blackmagic-recorder/stream.json`: capture and HTTP service settings.
- `/etc/blackmagic-recorder/mediamtx.yml`: the dedicated WebRTC gateway.
- `/etc/udev/rules.d/99-blackmagic-recorder.rules`: recorder access for the selected user.
- Three `blackmagic-recorder*.service` units in `/etc/systemd/system/`.

The services run as the selected regular user. The installer enables them at
boot and starts them. Existing `stream.json` is retained on subsequent installs;
other replaced files are backed up under `state/backups/`. The gateway executable
and its provenance record are stored in `bin/`. To review the generated files
without changing host settings, use:

```bash
python3 ~/uvrcast/stream-service/install.py \
  --prepare --user ashmelev --webrtc-host 192.0.2.10
```

The prepared files are under `stream-service/state/prepared/etc/`.

## Watch

Open **<http://192.0.2.10:18889/usb>** for WebRTC video and audio. The gateway
uses port **18189/UDP**, with **18189/TCP** as an ICE fallback. The rack host's
LAN address is advertised in ICE candidates; no external STUN server is needed
for direct LAN access. HTTP signaling is on port **18889**. RTSP publishing
is restricted to loopback port **18554**, and publishing is allowed only from
loopback addresses. Only the `usb` stream is configured.

To use the current STB-rack recorder provider, set the intended slot's video
connection to:

| Setting | Value |
| --- | --- |
| Provider | Recorder |
| Recorder address | `http://192.0.2.10:18890` |
| Input | `1` — the recorder's single analog input |
| Password | None |

The service does not challenge for a username/password. The portal's normal
video relay and its existing player remain in use for this path. Do not select
other input numbers: this USB recorder has one active analog capture input.
No slot configuration was changed by implementing or preparing this service.

Endpoints:

| Endpoint | Purpose |
| --- | --- |
| `http://192.0.2.10:18889/usb` | WebRTC browser player |
| `http://192.0.2.10:18889/usb/whep` | WebRTC WHEP endpoint |
| `http://192.0.2.10:18890/0.ts` | Live H.264 + AAC MPEG-TS; portal input 1 main stream |
| `http://192.0.2.10:18890/1.ts` | Alias for the same stream |
| `http://192.0.2.10:18890/get_status` | Recorder-compatible XML, using coded dimensions |
| `http://192.0.2.10:18890/api/status` | Capture counters, clients, errors and freshness |
| `http://192.0.2.10:18890/health` | HTTP 200 while media is flowing; otherwise 503 |

These viewers are for the rack LAN. An HTTPS portal needs same-origin HTTPS
proxying of WebRTC signaling rather than an HTTP iframe; the UDP media port
must also be reachable by the viewer. No proxy or firewall settings are changed
by this installer.

## Operation

```bash
systemctl status blackmagic-recorder.service blackmagic-recorder-gateway.service blackmagic-recorder-webrtc.service
journalctl -u blackmagic-recorder.service -u blackmagic-recorder-webrtc.service -f
```

Edit `/etc/blackmagic-recorder/stream.json` to change input, PAL/NTSC, requested
size, bitrate, or the no-video timeout, then restart the capture and publisher:

```bash
sudo systemctl restart blackmagic-recorder.service blackmagic-recorder-webrtc.service
```

`reload_fx2` defaults to false. The driver loads firmware automatically on an
uninitialized recorder. After `auto_reload_after` consecutive attempts that
produce no video (default **2**), recovery forces a complete FX2 RAM firmware
reload. Set that threshold to `0` to disable escalation, or set `reload_fx2` to
true to reload on every start. Failed attempts back off up to 30 seconds. The
service explicitly selects the external picture, turning off the previous
internal-blue diagnostic.

One capture is shared across clients. Viewers start at a keyframe with fresh
program tables and H.264 parameter sets, skipping partial audio PES packets.
Viewer queues accommodate a full hardware keyframe burst (at least 1,024 TS
packets). Available packets are batched immediately over HTTP chunked transfer.
Slow clients are disconnected if their queue fills or its oldest packet exceeds
`viewer_max_delay` (default 0.5 seconds); drop reasons appear in `/api/status`.
A stalled capture is restarted, and viewer connections are closed across a
source reset so timestamps from separate capture sessions are not mixed.
The WebRTC publisher waits for a healthy source and retries a disconnected
FFmpeg process with backoff. Capture phase, the last failure, and FX2 reload
attempts are available in `/api/status`.

The tested recorder firmware actually encoded **720×288 at 25 fps** for the
requested 720×576 PAL session. This service reports those coded dimensions and
preserves the QBOX timestamps. It corrects the firmware's inconsistent SPS
timing header without re-encoding video. It does not scale to 576 lines.

To release the recorder for a manual test:

```bash
sudo systemctl stop blackmagic-recorder-webrtc.service blackmagic-recorder.service
```

Start both again afterwards. The gateway may remain running.

## Validation and limits

Run the offline checks without USB or listening sockets:

```bash
cd ~/uvrcast/stream-service
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
python3 server.py --check
```

The **27 checks** cover QBOX
rejection, MPEG-TS table CRCs and continuity, timestamp wraparound, large keyframe
joining, audio PES boundaries, queue age limits, HTTP chunk parsing, recorder
XML compatibility, firmware recovery, and publisher retries. They also exercise
the capture/remux subprocess pipeline and verify that the watchdog terminates
an empty source while preserving its recorder error. Docker checks validate
Compose without a daemon, media health decisions, migration ordering, and
restoration of native services after failed startup. Six integration checks
need the optional `capture-OWdSCyCp` recording, which is not published. Set
`UVRCAST_TEST_FIXTURE=/path/to/capture.qbox` to run them with that fixture;
otherwise they are explicitly skipped. The remaining checks use synthetic
data and do not need a recorder.
The complete fixture remuxes and decodes with **317 video frames and 593 AAC
frames** and no FFmpeg errors. Decoded video frame hashes match the original.
H.264-copy plus Opus-audio output also passes codec probing.

The three generated systemd units passed isolated unit verification. Earlier
native-runtime checks established a WebRTC session and displayed the STB menu.
The new recovery behavior has offline validation; its hardware effect remains
unverified. The Docker source layout also compiles the driver in an isolated
local directory, and the smoke helper decodes the fixture using host FFmpeg.
**The Docker image itself has not been built or run here:** this session cannot
access the Docker daemon or USB nodes. End-to-end latency has not been measured.
Use `--replay /path/to/capture.qbox` with `server.py` on the host to exercise the
service without opening the recorder; replay is paced by capture timestamps.

Protocol references: [MediaMTX WebRTC receiver](https://mediamtx.org/docs/read/webrtc),
[browser codec and connectivity support](https://mediamtx.org/docs/features/webrtc-specific-features),
[FFmpeg publishing](https://mediamtx.org/docs/publish/ffmpeg).
