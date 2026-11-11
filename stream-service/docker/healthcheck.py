#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check media freshness and MediaMTX readiness using loopback HTTP only."""
import argparse
import json
import sys
import urllib.request


def fetch(url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=2) as response:
        return json.loads(response.read(65536))


def check(role, get=fetch):
    if role in ('capture', 'publisher'):
        status = get('http://127.0.0.1:18890/health')
        if not status.get('ready'):
            raise ValueError(status.get('error') or 'Waiting for recorder media')
    if role == 'gateway':
        get('http://127.0.0.1:19997/v3/paths/list')
    elif role == 'publisher':
        path = get('http://127.0.0.1:19997/v3/paths/get/usb')
        tracks = {track['codec'] for track in path.get('tracks2', [])} or set(path.get('tracks', []))
        if not path.get('online', path.get('ready')) or not {'H264', 'Opus'} <= tracks:
            raise ValueError('WebRTC publisher is waiting for H264 and Opus tracks')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('role', choices=('capture', 'gateway', 'publisher'))
    args = parser.parse_args()
    try:
        check(args.role)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'{args.role}: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
