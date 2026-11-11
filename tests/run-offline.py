#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Linux port maintenance: Alexander Shmelev (s1mb1o), 2026-11-10.
"""Compile/run USB-mock regressions using synthetic temporary fixtures."""
import argparse
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def run_case(name, args):
    out = ROOT / 'build/tests'
    out.mkdir(exist_ok=True)
    binary = out / name
    command = ['gcc', '-std=gnu99', '-fgnu89-inline', '-O2', '-g', '-Wall',
               '-DHAVE_CONFIG_H', '-include', 'stdlib.h', '-include', 'unistd.h',
               '-I' + str(ROOT / 'build'), '-I' + str(ROOT / 'include'),
               '-I' + str(ROOT / 'src'), '-I' + str(ROOT / 'vendor/libusb-compat'),
               '-I' + str(ROOT / 'vendor/libusb-compat/libusb'),
               str(ROOT / 'tests' / (name + '.c')), '-L' + str(ROOT / 'build/lib'),
               '-Wl,-l:libcrusher264.so.0', '-Wl,-l:libusb-0.1.so.4',
               '-Wl,-rpath,$ORIGIN/../lib', '-o', str(binary)]
    with (out / (name + '.log')).open('w') as log:
        subprocess.run(command, cwd=ROOT, check=True, stdout=log, stderr=subprocess.STDOUT)
        result = subprocess.run([str(binary), *map(str, args)], cwd=ROOT,
                                stdout=log, stderr=subprocess.STDOUT)
    print(f'{name}: {"PASS" if result.returncode == 0 else "FAIL"}', flush=True)
    if result.returncode:
        raise SystemExit(f'See {out / (name + ".log")}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--real-firmware', type=Path)
    parser.add_argument('--product-config', type=Path)
    args = parser.parse_args()
    if bool(args.real_firmware) != bool(args.product_config):
        parser.error('Supply both --real-firmware and --product-config')
    if not (ROOT / 'build/lib/libcrusher264.so.0').is_file():
        parser.error('Run python3 build.py first')
    with tempfile.TemporaryDirectory(prefix='crusher264-mock-') as directory:
        work = Path(directory)
        (work / 'firmware').mkdir()
        memory, mask = bytearray(65536), bytearray(65536)
        records = []
        # Arbitrary synthetic bytes exercise a noncontiguous final short block.
        # These are USB-mock fixtures, never firmware for a physical device.
        for address, data in [(0x1000, bytes(range(16))), (0x14c4, bytes(range(12)))]:
            body = bytes([len(data), address >> 8, address & 255, 0]) + data
            records.append(':' + (body + bytes([-sum(body) & 255])).hex().upper())
            memory[address:address + len(data)] = data
            mask[address:address + len(data)] = bytes([1]) * len(data)
        records.append(':00000001FF')
        hex_path = work / 'firmware/VideoRecorder.hex'
        hex_path.write_text('\n'.join(records) + '\n')
        image, coverage = work / 'memory.bin', work / 'mask.bin'
        image.write_bytes(memory)
        coverage.write_bytes(mask)
        fake_mg = work / 'unused-mg-file'
        fake_mg.write_text('Synthetic placeholder; the mock loader never reads it.\n')
        run_case('capture-transport', [])
        run_case('decoder-pattern', [])
        run_case('bridge-clock', [fake_mg])
        run_case('fx2-loader', [hex_path, image, coverage])
        run_case('fx2-reload', [work])
        if args.real_firmware:
            run_case('firmware-loader', [args.real_firmware.resolve(), args.product_config.resolve()])
        else:
            print('firmware-loader: SKIP (optional vendor resources not supplied)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
