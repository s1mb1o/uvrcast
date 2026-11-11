#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Launch the pinned, locally installed MediaMTX binary without a shell."""
import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    args = parser.parse_args()
    binary = Path(__file__).resolve().parent / 'bin/mediamtx'
    if not binary.is_file():
        parser.error('MediaMTX is not installed; run install.py on the rack host')
    os.execv(str(binary), [str(binary), str(args.config)])


if __name__ == '__main__':
    main()
