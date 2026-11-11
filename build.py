#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Linux port maintenance: Alexander Shmelev (s1mb1o), 2026-11-10.
"""Build the userspace driver locally using GCC and the system libusb-1.0 runtime."""
from pathlib import Path
import subprocess
import platform
import sys

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'build'
SRC = ROOT
USB = ROOT / 'vendor/libusb-compat'

def main():
    if platform.machine() != 'x86_64' or sys.byteorder != 'little':
        raise SystemExit('This configuration targets little-endian x86_64 Linux.')
    OUT.mkdir(exist_ok=True)
    (OUT / 'lib').mkdir(exist_ok=True)
    (OUT / 'bin').mkdir(exist_ok=True)
    (OUT / 'config.h').write_text('''/* Local x86_64 Linux build configuration. */
#define HAVE_LITTLEENDIAN 1
#define HAVE_BIGENDIAN 0
#define ARCH_X86 1
#define ARCH_X86_64 1
#define HAVE_BSWAP 1
#define ASM_OPTIMISATIONS 1
#define DBG 1
#define TEST_MEMBLOCK_SIZE 1
#define GCC_PACK __attribute__((packed))
#define API_EXPORTED __attribute__((visibility("default")))
#define ENABLE_LOGGING 1
''')
    commands = []
    def run(args):
        commands.append(args)
        print('Building:', args[-1], flush=True)
        subprocess.run(args, check=True)
    base = ['gcc', '-std=gnu99', '-fgnu89-inline', '-O2', '-g', '-Wall', '-fPIC',
            '-I'+str(OUT), '-I'+str(USB), '-I'+str(USB/'libusb')]
    run(base + ['-shared', '-Wl,-z,defs', '-Wl,-soname,libusb-0.1.so.4', str(USB/'libusb/core.c'),
                '-Wl,-l:libusb-1.0.so.0', '-o', str(OUT/'lib/libusb-0.1.so.4')])
    common = base + ['-DHAVE_CONFIG_H', '-I'+str(SRC/'include'), '-include', 'stdlib.h', '-include', 'unistd.h']
    driver = ['logging.c', 'crusher-fx2.c', 'crusher.c', 'crusher-i2c.c', 'mg1264-loader.c',
              'mg1264-cmd.c', 'mg1264-io.c', 'mg1264-codec.c', 'mg1264-mware.c', 'mg1264-cli.c']
    run(common + ['-DDATADIR="'+str(ROOT)+'"', '-shared', '-Wl,-z,defs',
                  '-Wl,-soname,libcrusher264.so.0', '-Wl,-rpath,$ORIGIN'] +
        [str(SRC/'src'/f) for f in driver] + ['-L'+str(OUT/'lib'), '-Wl,-l:libusb-0.1.so.4',
         '-lm', '-o', str(OUT/'lib/libcrusher264.so.0')])
    samples = ['crusherenc.c', 'logging.c', 'qbox.c', 'wav.c', 'adts.c', 'imgConverter.c']
    run(common + [str(SRC/'sample'/f) for f in samples] + ['-L'+str(OUT/'lib'),
        '-Wl,-l:libcrusher264.so.0', '-Wl,-l:libusb-0.1.so.4', '-Wl,-rpath,$ORIGIN/../lib',
        '-lm', '-o', str(OUT/'bin/crusher264')])
    import json
    (OUT/'commands.json').write_text(json.dumps(commands, indent=2)+'\n')

if __name__ == '__main__':
    main()
