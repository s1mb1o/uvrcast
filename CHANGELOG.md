# Changes from upstream

Base: piratfm/crusher264 commit
`19dd075e658dc1f78934e8f703d8fb14f6746e35`.

## 2026-11-11 — uvrcast streaming service

- Add shared HTTP MPEG-TS capture and WebRTC publishing with H.264 copy and Opus audio.
- Add media readiness checks, capture watchdog recovery, viewer queue limits,
  keyframe joining, and publisher retries.
- Add a Dockerfile and Compose stack with USB re-enumeration support and a
  launcher that can migrate the existing native services.
- Preserve the original crusher264 author credits and source licenses.
- Verify native browser playback at 25 fps with 720x288 coded PAL video.

## 2026-11-09 to 2026-11-10

- Build the userspace driver and capture utility on x86_64 Ubuntu using GCC
  and libusb compatibility sources, without system library installation.
- Detach an active kernel driver on the uninitialized capture interface and
  improve USB failure reporting.
- Add explicit PAL/NTSC selection, bounded capture tests and readable result
  ownership after sudo runs.
- Correct the product-configuration selector source pointer in the firmware
  loader and capture boot configuration.
- Correct capture host-register read byte order and preserve clock-control
  flags while following the vendor application's initialization sequence.
- Flush the FX2 loader's final buffered Intel HEX record; reject short writes.
  Add an optional once-only reload for devices already running RAM firmware.
- Treat idle capture-event timeouts as polling, clearing stale output blocks.
  Continue to reject other USB failures and incomplete transfers.
- Add read-only diagnostic snapshots, decoded ADC status, and an optional
  documented internal-blue-picture test.
- Add offline USB-mock regression tests and a QBOX-to-MP4 converter.
- Validate one external PAL recording and one internal-picture recording.

Successful captures do not establish which individual change resolved the
earlier stalls. Actual PAL output remains 720x288 in the tested full profile.
No proprietary firmware, application, private logs or recorded media are part
of the publication.
