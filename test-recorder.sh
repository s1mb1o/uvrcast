#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# Linux port maintenance: Alexander Shmelev (s1mb1o), 2026-11-10.
set -u
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
INPUT=${1:-composite}
STANDARD=${2:-pal}
RELOAD_FX2=0
TEST_PATTERN=off
FULLRES=0
for option in "${@:3}"; do
    case "$option" in
        reload) RELOAD_FX2=1 ;;
        blue) TEST_PATTERN=blue ;;
        full) FULLRES=1 ;;
        *) echo 'Optional arguments must be reload, blue, and/or full.' >&2; exit 2 ;;
    esac
done
case "$INPUT" in
    composite|s-video|component) ;;
    *) echo 'Input must be composite, s-video, or component.' >&2; exit 2 ;;
esac
case "$STANDARD" in
    pal) if [[ $FULLRES -eq 1 ]]; then SIZE=720x576; else SIZE=352x288; fi ;;
    ntsc) if [[ $FULLRES -eq 1 ]]; then SIZE=720x480; else SIZE=320x240; fi ;;
    *) echo 'Standard must be pal or ntsc (second argument).' >&2; exit 2 ;;
esac
# The Mac app's default full-resolution session is 720x576/720x480 at
# 2,000,000 bps; use it when "full" is requested so the command stream
# matches the shipped application exactly.
if [[ $FULLRES -eq 1 ]]; then BITRATE=2000000; else BITRATE=1500000; fi
if [[ ! -d /dev/bus/usb ]]; then
    echo 'USB device nodes are unavailable. Run this script in a normal host terminal.' >&2
    exit 1
fi
mkdir -p "$ROOT/tests"
TEST_DIR=$(mktemp -d "$ROOT/tests/capture-XXXXXXXX")
make_results_readable() {
    if [[ $EUID -eq 0 && -n ${SUDO_UID:-} && -n ${SUDO_GID:-} ]]; then
        chown -- "$SUDO_UID:$SUDO_GID" "$TEST_DIR"
        for output in "$TEST_DIR/capture.log" "$TEST_DIR/capture.qbox" \
            "$TEST_DIR/capture.h264" "$TEST_DIR/capture.aac" "$TEST_DIR/capture.mp4" \
            "$TEST_DIR/capture-media.json" "$TEST_DIR/capture-remux.log" \
            "$TEST_DIR/capture-probe.json"; do
            if [[ -f "$output" ]]; then chown -- "$SUDO_UID:$SUDO_GID" "$output"; fi
        done
    fi
}
trap make_results_readable EXIT
cd "$ROOT" || exit 1
echo "Testing $INPUT input, $STANDARD, requested output $SIZE at $BITRATE bps for up to 15 seconds."
if [[ $TEST_PATTERN == blue ]]; then
    echo 'Using the decoder internal blue screen; external CVBS picture is overridden.'
fi
CRUSHER_DIAGNOSTICS=1 CRUSHER_RELOAD_FX2="$RELOAD_FX2" CRUSHER_TEST_PATTERN="$TEST_PATTERN" \
    timeout --signal=INT --kill-after=5s 15s "$ROOT/build/bin/crusher264" \
    -d -m capture -i "$INPUT" -t "$STANDARD" -s "$SIZE" -b "$BITRATE" \
    -a 128000 -c 2 -f qbox -o "$TEST_DIR/capture.qbox" \
    > "$TEST_DIR/capture.log" 2>&1
STATUS=$?
cat "$TEST_DIR/capture.log"
echo "Capture exit status: $STATUS (124 means the 15-second limit was reached)."
echo "Results: $TEST_DIR"
if [[ -s "$TEST_DIR/capture.qbox" ]]; then
    wc -c "$TEST_DIR/capture.qbox"
    if command -v ffmpeg >/dev/null && command -v python3 >/dev/null; then
        if ! python3 "$ROOT/convert-capture.py" "$TEST_DIR/capture.qbox"; then
            echo 'Capture data was saved, but MP4 conversion failed.' >&2
            exit 1
        fi
    else
        echo 'Data received. Run convert-capture.py with ffmpeg installed to create MP4.'
    fi
else
    echo 'No capture data received.' >&2
    exit 1
fi
