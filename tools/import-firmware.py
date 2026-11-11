#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Linux port maintenance: Alexander Shmelev (s1mb1o), 2026-11-10.
"""Copy user-supplied vendor app resources locally; no downloads or execution."""
import argparse
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def check_hex(data):
    eof = False
    for line in data.decode('ascii').splitlines():
        line = line.strip()
        if not line:
            continue
        if eof or not line.startswith(':'):
            raise ValueError('Invalid Intel HEX record order')
        record = bytes.fromhex(line[1:])
        if len(record) < 5 or len(record) != record[0] + 5 or sum(record) & 255:
            raise ValueError('Invalid Intel HEX length/checksum')
        eof = record[3] == 1
    if not eof:
        raise ValueError('Intel HEX has no EOF record')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('app', type=Path)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'firmware')
    args = parser.parse_args()
    resources = args.app / 'Contents/Resources'
    pairs = [('VideoRecorder.hex', 'VideoRecorder.hex'),
             ('qmmapp.seve1-eb-16mb.bin', 'cap.qmmapp.seve1-eb-16mb.bin')]
    try:
        planned = []
        for original, installed in pairs:
            data = (resources / original).read_bytes()
            if original.endswith('.hex'):
                check_hex(data)
            elif not data.startswith(b'MBY0'):
                raise ValueError('MG1264 resource does not have an MBY0 signature')
            target = args.output_dir / installed
            if target.exists() and target.read_bytes() != data:
                raise ValueError(f'Refusing to replace different file: {target}')
            planned.append((target, data))
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for target, data in planned:
            if not target.exists():
                with target.open('xb') as output:
                    output.write(data)
            print(f'{target.name}: {len(data)} bytes, SHA-256 {hashlib.sha256(data).hexdigest()}')
        return 0
    except (OSError, ValueError) as exc:
        print(f'Firmware import failed: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
