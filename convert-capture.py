#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Linux port maintenance: Alexander Shmelev (s1mb1o), 2026-11-10.
"""Demux this recorder's version-0 QBOX capture and copy its streams into MP4.

QBOX fields follow sample/qbox.[ch]. H.264 NAL units
have four-byte big-endian lengths; AAC configuration is AudioSpecificConfig.
Constant capture timestamps are verified before a constant-rate remux.
The source capture is never modified and existing outputs are not replaced.
"""
import argparse
from collections import Counter
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys

HEADER = struct.Struct('>I4sIHHII')
SAMPLE_RATES = [96000, 88200, 64000, 48000, 44100, 32000, 24000,
                22050, 16000, 12000, 11025, 8000, 7350]
TIMEBASE = 90000


def packets(source):
    offset = 0
    while True:
        header = source.read(HEADER.size)
        if not header:
            return
        if len(header) != HEADER.size:
            raise ValueError(f'Truncated QBOX header at byte {offset}')
        size, magic, version_flags, kind, stream_id, flags, cts = HEADER.unpack(header)
        if magic != b'qbox' or not HEADER.size <= size <= 16 * 1024 * 1024:
            raise ValueError(f'Invalid QBOX header at byte {offset}')
        if version_flags >> 24:
            raise ValueError('Only the recorder version-0 QBOX header is supported')
        payload = source.read(size - HEADER.size)
        if len(payload) != size - HEADER.size:
            raise ValueError(f'Truncated QBOX payload at byte {offset}')
        yield kind, stream_id, flags, cts, payload
        offset += size


def h264_nals(payload):
    offset = 0
    while offset + 4 <= len(payload):
        size = struct.unpack_from('>I', payload, offset)[0]
        if not size or offset + 4 + size > len(payload):
            raise ValueError('Invalid H.264 NAL length')
        nal = payload[offset + 4:offset + 4 + size]
        if nal[0] & 0x80:
            raise ValueError('Invalid H.264 forbidden_zero_bit')
        yield nal
        offset += size + 4
    # Encoder access units may include up to three zero alignment bytes.
    if any(payload[offset:]):
        raise ValueError('Invalid nonzero H.264 alignment bytes')


def aac_config(payload):
    if len(payload) != 2:
        raise ValueError('Only the recorder two-byte AAC configuration is supported')
    bits = int.from_bytes(payload, 'big')
    object_type = bits >> 11
    rate_index = (bits >> 7) & 15
    channels = (bits >> 3) & 15
    if object_type != 2 or rate_index >= len(SAMPLE_RATES) or not 1 <= channels <= 7 or bits & 7:
        raise ValueError('Unsupported AAC configuration (expected AAC-LC, 1024-sample frames)')
    return rate_index, channels


def adts_header(size, config):
    rate_index, channels = config
    size += 7
    if size > 8191:
        raise ValueError('AAC packet exceeds the ADTS length limit')
    return bytes([0xff, 0xf1, 0x40 | (rate_index << 2) | (channels >> 2),
                  ((channels & 3) << 6) | (size >> 11), (size >> 3) & 255,
                  ((size & 7) << 5) | 0x1f, 0xfc])


def convert(source_path, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    base = output_dir / source_path.stem
    paths = {key: Path(str(base) + suffix) for key, suffix in {
        'video': '.h264', 'audio': '.aac', 'mp4': '.mp4',
        'report': '-media.json', 'log': '-remux.log', 'probe': '-probe.json',
    }.items()}
    if any(path.exists() for path in paths.values()):
        raise ValueError('Converted output already exists; select a new --output-dir')
    if source_path.resolve() in (p.resolve() for p in paths.values()):
        raise ValueError('Output would replace the source')

    counts = Counter()
    nal_types = Counter()
    timestamps = {1: [], 2: []}
    stream_ids = {}
    config = None
    with source_path.open('rb') as source, paths['video'].open('xb') as video, paths['audio'].open('xb') as audio:
        for kind, stream_id, flags, cts, payload in packets(source):
            if kind not in (1, 2):
                raise ValueError(f'Unsupported QBOX stream type {kind}')
            if kind in stream_ids and stream_ids[kind] != stream_id:
                raise ValueError('Multiple streams of the same type are unsupported')
            stream_ids[kind] = stream_id
            counts[kind] += 1
            if not flags & 1:
                if not flags & 2:
                    raise ValueError('Capture sample has no timestamp')
                timestamps[kind].append(cts)
            if kind == 2:
                for nal in h264_nals(payload):
                    nal_types[nal[0] & 31] += 1
                    video.write(b'\x00\x00\x00\x01' + nal)
            elif flags & 1:
                new_config = aac_config(payload)
                if config is not None and new_config != config:
                    raise ValueError('AAC configuration changed during capture')
                config = new_config
            else:
                if config is None:
                    raise ValueError('AAC sample arrived before its configuration')
                audio.write(adts_header(len(payload), config) + payload)

    video_cts, audio_cts = timestamps[2], timestamps[1]
    if len(video_cts) < 2 or not config or not audio_cts:
        raise ValueError('Capture must contain video, AAC configuration and audio samples')
    video_steps = {b - a for a, b in zip(video_cts, video_cts[1:])}
    if len(video_steps) != 1 or min(video_steps) <= 0:
        raise ValueError('Nonuniform video timestamps cannot be remuxed as constant rate')
    video_step = video_steps.pop()
    frame_rate = Fraction(TIMEBASE, video_step)
    rate = SAMPLE_RATES[config[0]]
    if any(abs(Fraction(b - a) - Fraction(TIMEBASE * 1024, rate)) > 1
           for a, b in zip(audio_cts, audio_cts[1:])):
        raise ValueError('Discontinuous AAC timestamps; remux aborted')
    if not nal_types[7] or not nal_types[8] or not nal_types[5]:
        raise ValueError('Capture has no complete H.264 parameter sets / keyframe')

    digest = hashlib.sha256()
    with source_path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    report = {
        'source': str(source_path.resolve()), 'source_bytes': source_path.stat().st_size,
        'source_sha256': digest.hexdigest(),
        'qbox_packets': sum(counts.values()), 'timebase': TIMEBASE,
        'video': {'codec': 'h264', 'samples': len(video_cts),
                  'frame_rate': str(frame_rate), 'nal_types': dict(nal_types),
                  'first_cts': video_cts[0], 'last_cts': video_cts[-1],
                  'duration_seconds': float(Fraction(len(video_cts) * video_step, TIMEBASE))},
        'audio': {'codec': 'aac-lc', 'samples': len(audio_cts), 'sample_rate': rate,
                  'channels': 8 if config[1] == 7 else config[1],
                  'first_cts': audio_cts[0], 'last_cts': audio_cts[-1],
                  'duration_seconds': float(Fraction(len(audio_cts) * 1024, rate))},
    }
    paths['report'].write_text(json.dumps(report, indent=2) + '\n')
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise ValueError('Elementary streams saved, but ffmpeg is required to create MP4')
    start = min(video_cts[0], audio_cts[0])
    # The firmware SPS can advertise NTSC timing during PAL capture. Set its
    # timing header and MP4 packet timestamps from the actual QBOX clock.
    video_filter = (f'h264_metadata=tick_rate={frame_rate * 2}:fixed_frame_rate_flag=1,'
                    f'setts=ts=N*{video_step}+{video_cts[0] - start}')
    command = [ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'warning', '-n',
               '-fflags', '+genpts', '-itsoffset', str((video_cts[0] - start) / TIMEBASE),
               '-r', str(frame_rate), '-f', 'h264', '-i', str(paths['video']),
               '-itsoffset', str((audio_cts[0] - start) / TIMEBASE),
               '-f', 'aac', '-i', str(paths['audio']),
               '-map', '0:v:0', '-map', '1:a:0', '-c', 'copy',
               '-bsf:v', video_filter, '-video_track_timescale', str(TIMEBASE),
               '-bsf:a', 'aac_adtstoasc', '-movflags', '+faststart', str(paths['mp4'])]
    with paths['log'].open('x') as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise ValueError(f'ffmpeg failed; see {paths["log"]}')
    ffprobe = shutil.which('ffprobe')
    if ffprobe:
        result = subprocess.run([ffprobe, '-v', 'error', '-count_frames', '-show_streams',
                                 '-show_format', '-of', 'json', str(paths['mp4'])],
                                capture_output=True, text=True, check=True)
        if result.stderr.strip():
            raise ValueError(f'Media probe reported decoding errors: {result.stderr.strip()}')
        paths['probe'].write_text(result.stdout)
        probe = json.loads(result.stdout)
        for stream in probe['streams']:
            if stream['codec_type'] == 'video':
                expected = len(video_cts)
                report['encoded_video'] = {key: stream[key] for key in
                    ['width', 'height', 'sample_aspect_ratio', 'display_aspect_ratio',
                     'r_frame_rate', 'nb_read_frames'] if key in stream}
            elif stream['codec_type'] == 'audio':
                expected = len(audio_cts)
            else:
                continue
            if int(stream.get('nb_read_frames', -1)) != expected:
                raise ValueError('Decoded sample count does not match the QBOX sample count')
        report['container_duration_seconds'] = float(probe['format']['duration'])
        paths['report'].write_text(json.dumps(report, indent=2) + '\n')
    print(f'MP4: {paths["mp4"]}')
    print(f'{len(video_cts)} video samples at {frame_rate} fps; AAC {rate} Hz, '
          f'{report["audio"]["channels"]} channels.')
    if 'encoded_video' in report:
        video = report['encoded_video']
        print(f'Actual encoded size: {video["width"]}x{video["height"]}.')
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    try:
        convert(args.capture, args.output_dir or args.capture.parent)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f'Conversion failed: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
