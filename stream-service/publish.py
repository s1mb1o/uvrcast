#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Copy H.264 to MediaMTX; encode only the AAC audio into WebRTC-compatible Opus."""
import argparse
import json
import logging
from pathlib import Path
import shutil
import signal
import subprocess
import threading
import time
import urllib.request

from server import Config

LOG = logging.getLogger('blackmagic-publisher')


def source_url(config):
    host = '127.0.0.1' if config.host == '0.0.0.0' else config.host
    return f'http://{host}:{config.port}'


def command(config):
    return ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'warning',
            '-rw_timeout', '5000000', '-probesize', '131072',
            '-analyzeduration', '500000', '-fpsprobesize', '0',
            '-f', 'mpegts', '-i', source_url(config) + '/0.ts',
            '-map', '0:v:0', '-map', '0:a:0', '-c:v', 'copy',
            '-c:a', 'libopus', '-application', 'lowdelay', '-frame_duration', '20',
            '-b:a', '64000', '-ar', '48000', '-ac', '2',
            '-max_interleave_delta', '50000', '-flush_packets', '1',
            '-f', 'rtsp', '-rtsp_transport', 'tcp', '-pkt_size', '1200', '-muxdelay', '0',
            config.rtsp_publish_url]


def read_status(config):
    with urllib.request.urlopen(source_url(config) + '/api/status', timeout=2) as response:
        return json.loads(response.read(65536))


def wait_until_ready(config, stop, fetch=None):
    fetch = read_status if fetch is None else fetch
    waiting_logged = False
    while not stop.is_set():
        try:
            status = fetch(config)
            if status.get('ready'):
                return True
        except (OSError, ValueError):
            pass
        if not waiting_logged:
            LOG.info('Waiting for recorder video; publisher remains idle')
            waiting_logged = True
        if stop.wait(2):
            break
    return False


def run(config, stop):
    failures, child = 0, None
    try:
        while wait_until_ready(config, stop):
            started = time.monotonic()
            child = subprocess.Popen(command(config))
            while not stop.is_set():
                try:
                    code = child.wait(timeout=0.5)
                    break
                except subprocess.TimeoutExpired:
                    continue
            if stop.is_set():
                break
            failures = 1 if time.monotonic() - started >= 60 else failures + 1
            delay = min(30, 2 ** min(failures, 5))
            LOG.warning('Publisher exited (%s); retrying in %s seconds', code, delay)
            if stop.wait(delay):
                break
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--print-command', action='store_true')
    args = parser.parse_args()
    config = Config.load(args.config)
    argv = command(config)
    if args.print_command:
        import shlex
        print(shlex.join(argv))
    else:
        ffmpeg = shutil.which(argv[0])
        if not ffmpeg:
            parser.error('ffmpeg is required')
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
        stop = threading.Event()
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        run(config, stop)


if __name__ == '__main__':
    main()
