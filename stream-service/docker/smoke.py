#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Decode an externally mounted QBOX fixture with the image's real media tools."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from qbox_ts import Muxer, packets, remux_command


def smoke(fixture, standard):
    mux = Muxer()
    with tempfile.TemporaryDirectory() as directory:
        transport = Path(directory) / 'capture.ts'
        remux = subprocess.Popen(remux_command(output=str(transport), standard=standard), stdin=subprocess.PIPE)
        try:
            with fixture.open('rb') as source:
                for packet in packets(source):
                    remux.stdin.write(mux.process(packet))
            remux.stdin.close()
            if remux.wait(timeout=30):
                raise RuntimeError('MPEG-TS remux failed')
        finally:
            if remux.poll() is None:
                remux.kill()
                remux.wait()
            remux.stdin.close()

        result = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-show_streams',
                                 '-of', 'json', str(transport)], capture_output=True, text=True,
                                timeout=30, check=True)
        if result.stderr:
            raise RuntimeError(result.stderr)
        streams = json.loads(result.stdout)['streams']
        video = next(s for s in streams if s['codec_type'] == 'video')
        audio = next(s for s in streams if s['codec_type'] == 'audio')
        if (int(video['nb_read_frames']) != mux.video_samples
                or int(audio['nb_read_frames']) != mux.audio_samples or not mux.video_samples):
            raise RuntimeError('Decoded frame counts do not match QBOX input')

        opus = Path(directory) / 'webrtc.mkv'
        converted = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(transport),
            '-map', '0:v:0', '-map', '0:a:0', '-c:v', 'copy', '-c:a', 'libopus',
            '-application', 'lowdelay', '-frame_duration', '20', '-ar', '48000', '-ac', '2', str(opus)],
            capture_output=True, text=True, timeout=30, check=True)
        if converted.stderr:
            raise RuntimeError(converted.stderr)
        probe = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(opus)],
                               capture_output=True, text=True, timeout=30, check=True)
        codecs = {s['codec_name'] for s in json.loads(probe.stdout)['streams']}
        if probe.stderr or codecs != {'h264', 'opus'}:
            raise RuntimeError('WebRTC codec conversion failed')
        return {'video_frames': mux.video_samples, 'audio_frames': mux.audio_samples,
                'width': mux.width, 'height': mux.height, 'webrtc_codecs': sorted(codecs)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fixture', type=Path)
    parser.add_argument('--standard', choices=('pal', 'ntsc'), default='pal')
    args = parser.parse_args()
    print(json.dumps(smoke(args.fixture, args.standard), indent=2))


if __name__ == '__main__':
    main()
