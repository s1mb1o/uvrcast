#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Stream recorder QBOX into MPEG-TS, preserving its 90 kHz timestamps.

The existing, validated capture converter owns QBOX/H.264/AAC parsing.
Only transport headers and access-unit delimiters are added; media is not encoded.
"""
from collections import defaultdict
from pathlib import Path
import runpy
import struct

WORKSPACE = Path(__file__).resolve().parent.parent
_capture = runpy.run_path(str(WORKSPACE / 'convert-capture.py'))
packets = _capture['packets']
h264_nals = _capture['h264_nals']
aac_config = _capture['aac_config']
adts_header = _capture['adts_header']
START = b'\x00\x00\x00\x01'
VIDEO_PID, AUDIO_PID, PMT_PID = 256, 257, 4096


def crc32_mpeg(data):
    value = 0xffffffff
    for byte in data:
        value ^= byte << 24
        for _ in range(8):
            value = ((value << 1) ^ (0x04c11db7 if value & 0x80000000 else 0)) & 0xffffffff
    return value


def pts_bytes(value):
    value &= (1 << 33) - 1
    return bytes([0x21 | ((value >> 29) & 14), (value >> 22) & 255,
                  1 | ((value >> 14) & 254), (value >> 7) & 255,
                  1 | ((value << 1) & 254)])


def dimensions(sps):
    """Read coded dimensions from the recorder's baseline/main-profile SPS."""
    data = sps[1:].replace(b'\x00\x00\x03', b'\x00\x00')
    bit = 0

    def read(count=1):
        nonlocal bit
        if bit + count > len(data) * 8:
            raise ValueError('Truncated SPS')
        result = 0
        for _ in range(count):
            result = (result << 1) | ((data[bit // 8] >> (7 - bit % 8)) & 1)
            bit += 1
        return result

    def ue():
        count = 0
        while not read():
            count += 1
            if count > 31:
                raise ValueError('Invalid SPS integer')
        return (1 << count) - 1 + read(count)

    profile = read(8)
    if profile not in (66, 77, 88):
        raise ValueError('Only baseline/main SPS dimensions are supported')
    read(16)
    ue()  # sequence parameter set ID
    ue()  # log2_max_frame_num_minus4
    order = ue()
    if order == 0:
        ue()
    elif order == 1:
        read()
        ue()
        ue()
        for _ in range(ue()):
            ue()
    elif order != 2:
        raise ValueError('Invalid SPS picture order')
    ue()
    read()
    width, height = (ue() + 1) * 16, (ue() + 1) * 16
    frame_only = read()
    if not frame_only:
        read()
    read()
    crop = [ue() for _ in range(4)] if read() else [0, 0, 0, 0]
    return width - 2 * (crop[0] + crop[1]), (2 - frame_only) * (height - 2 * (crop[2] + crop[3]))


class Muxer:
    def __init__(self):
        self.cc = defaultdict(int)
        self.clock = {}
        self.tables_at = None
        self.config = None
        self.sps = self.pps = None
        self.width = self.height = None
        self.video_samples = self.audio_samples = 0

    def _timestamp(self, kind, value):
        if kind not in self.clock:
            self.clock[kind] = (value, value)
        else:
            previous, absolute = self.clock[kind]
            delta = (value - previous) & 0xffffffff
            if delta > 0x80000000:
                raise ValueError('Recorder timestamps went backwards')
            self.clock[kind] = value, absolute + delta
        return self.clock[kind][1]

    def _header(self, pid, start, adaptation=False):
        cc = self.cc[pid]
        self.cc[pid] = (cc + 1) & 15
        return bytes([0x47, ((pid >> 8) & 31) | (0x40 if start else 0),
                      pid & 255, (0x30 if adaptation else 0x10) | cc])

    def _section(self, pid, section):
        section += crc32_mpeg(section).to_bytes(4, 'big')
        payload = b'\x00' + section
        return self._header(pid, True) + payload + b'\xff' * (184 - len(payload))

    def _tables(self):
        pat = bytes.fromhex('00 b0 0d 00 01 c1 00 00 00 01 f0 00')
        pmt = bytes.fromhex('02 b0 17 00 01 c1 00 00 e1 00 f0 00 '
                            '1b e1 00 f0 00 0f e1 01 f0 00')
        return self._section(0, pat) + self._section(PMT_PID, pmt)

    def _pes(self, pid, stream_id, payload, timestamp, keyframe=False):
        length = len(payload) + 8
        if pid == VIDEO_PID:
            length = 0  # Unbounded video PES; next PUSI delimits it.
        elif length > 65535:
            raise ValueError('Audio PES is too large')
        pes = b'\x00\x00\x01' + bytes([stream_id]) + struct.pack('>H', length)
        pes += b'\x84\x80\x05' + pts_bytes(timestamp) + payload
        result = bytearray()
        first = True
        while pes:
            fields = b''
            if first and pid == VIDEO_PID:
                base = timestamp & ((1 << 33) - 1)
                pcr = struct.pack('>I', base >> 1) + bytes([((base & 1) << 7) | 0x7e, 0])
                fields = bytes([0x10 | (0x40 if keyframe else 0)]) + pcr
            capacity = 184 - (1 + len(fields) if fields else 0)
            chunk, pes = pes[:capacity], pes[capacity:]
            padding = 184 - len(chunk)
            if padding:
                size = padding - 1
                if size and not fields:
                    fields = b'\x00'
                adaptation = bytes([size]) + fields + b'\xff' * (size - len(fields))
                result += self._header(pid, first, True) + adaptation + chunk
            else:
                result += self._header(pid, first) + chunk
            first = False
        return bytes(result)

    def process(self, packet):
        kind, _stream_id, flags, cts, payload = packet
        if kind not in (1, 2):
            raise ValueError(f'Unsupported QBOX stream type: {kind}')
        keyframe = False
        if kind == 2:
            nals = list(h264_nals(payload))
            for nal in nals:
                if nal[0] & 31 == 7:
                    self.sps = nal
                    self.width, self.height = dimensions(nal)
                elif nal[0] & 31 == 8:
                    self.pps = nal
                elif nal[0] & 31 == 5:
                    keyframe = True
            if flags & 1:
                return b''
            if not self.sps or not self.pps:
                raise ValueError('Video arrived before SPS/PPS')
            payload = START + b'\x09\xf0'  # Access-unit delimiter for TS readers.
            if keyframe:
                payload += START + self.sps + START + self.pps
            payload += b''.join(START + nal for nal in nals if nal[0] & 31 not in (7, 8, 9))
            self.video_samples += 1
        elif flags & 1:
            new_config = aac_config(payload)
            if self.config is not None and new_config != self.config:
                raise ValueError('AAC configuration changed')
            self.config = new_config
            return b''
        else:
            if self.config is None:
                raise ValueError('Audio arrived before AAC configuration')
            payload = adts_header(len(payload), self.config) + payload
            self.audio_samples += 1
        if not flags & 2:
            raise ValueError('Media packet has no QBOX timestamp')
        timestamp = self._timestamp(kind, cts)
        output = b''
        if self.tables_at is None or keyframe or timestamp - self.tables_at >= 9000:
            output = self._tables()
            self.tables_at = timestamp
        return output + self._pes(VIDEO_PID if kind == 2 else AUDIO_PID,
                                  0xe0 if kind == 2 else 0xc0, payload, timestamp, keyframe)


def remux_command(ffmpeg='ffmpeg', standard='pal', output='pipe:1'):
    tick_rate = '50' if standard == 'pal' else '60000/1001'
    return [ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'warning',
            '-probesize', '32768', '-analyzeduration', '100000', '-fpsprobesize', '0',
            '-f', 'mpegts', '-i', 'pipe:0', '-map', '0:v:0', '-map', '0:a:0',
            '-c', 'copy', '-bsf:v', f'h264_metadata=tick_rate={tick_rate}:fixed_frame_rate_flag=1',
            '-max_interleave_delta', '50000', '-muxdelay', '0', '-muxpreload', '0',
            '-flush_packets', '1', '-mpegts_flags', '+resend_headers+initial_discontinuity',
            '-metadata', 'service_name=Blackmagic USB Recorder',
            '-metadata', 'service_provider=STB rack', '-f', 'mpegts', output]
