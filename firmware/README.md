# Local firmware, not distributed

Provide your own vendor application/firmware. This repository includes no
Blackmagic firmware payloads or application binaries and does not grant a
license to redistribute them.

The analog USB recorder needs:

| Vendor app resource | Local driver filename |
| --- | --- |
| `VideoRecorder.hex` | `firmware/VideoRecorder.hex` |
| `qmmapp.seve1-eb-16mb.bin` | `firmware/cap.qmmapp.seve1-eb-16mb.bin` |

From a copy of Blackmagic Video Recorder.app you are entitled to use:

```sh
python3 tools/import-firmware.py '/path/to/Blackmagic Video Recorder.app'
```

The helper checks Intel HEX records and the MBY0 container signature, then
copies these files without changing their contents or executing the app.
Existing different files are not overwritten. The `cap.` prefix is only a
filename alias required by the original driver. All local payloads are ignored
by Git. No `bigbird.bin` is needed for the tested analog device.

Tested application version: 1.0.1. Other versions are unverified.

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| VideoRecorder.hex | 33,216 | `3623a23bf60efd7605ca5a3e3089a37e50240c360c681880baf6fd18950d0a24` |
| cap.qmmapp.seve1-eb-16mb.bin | 421,460 | `eb65ee4fa7810e18bcd2002e5317eddcd9b9bb2e0ade665721149a40da92f1ba` |

`prodcfg17.bin` is only needed for an optional offline real-image regression
test; the normal driver uses its existing built-in product configuration.
