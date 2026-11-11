#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""One USB capture shared by the STB-rack HTTP-TS relay and WebRTC publisher."""
import argparse
from dataclasses import dataclass, fields
from datetime import datetime, timezone
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import queue
import shutil
import signal
import socket
import subprocess
import threading
import time
import xml.etree.ElementTree as ET

from qbox_ts import AUDIO_PID, Muxer, VIDEO_PID, WORKSPACE, packets, remux_command

LOG = logging.getLogger('blackmagic-stream')


@dataclass
class Config:
    workspace: str = str(WORKSPACE)
    host: str = '127.0.0.1'
    port: int = 18890
    input: str = 'composite'
    standard: str = 'pal'
    width: int = 720
    height: int = 576
    bitrate: int = 2000000
    audio_bitrate: int = 128000
    device_number: int = 0
    reload_fx2: bool = False
    stall_timeout: float = 20
    queue_packets: int = 1024
    max_clients: int = 12
    viewer_max_delay: float = 0.5
    auto_reload_after: int = 2
    webrtc_url: str = 'http://127.0.0.1:18889/usb'
    rtsp_publish_url: str = 'rtsp://127.0.0.1:18554/usb'

    @classmethod
    def load(cls, path=None):
        value = json.loads(Path(path).read_text()) if path else {}
        extra = set(value) - {f.name for f in fields(cls)}
        if extra:
            raise ValueError(f'Unknown configuration keys: {sorted(extra)}')
        config = cls(**value)
        if os.environ.get('BLACKMAGIC_WEBRTC_URL'):
            config.webrtc_url = os.environ['BLACKMAGIC_WEBRTC_URL']
        if config.input not in ('composite', 's-video', 'component'):
            raise ValueError('Invalid capture input')
        if config.standard not in ('pal', 'ntsc'):
            raise ValueError('Invalid capture standard')
        if not 1 <= config.port <= 65535 or not 8 <= config.queue_packets <= 4096:
            raise ValueError('Invalid HTTP port or client queue size')
        if not 1 <= config.max_clients <= 64 or not 5 <= config.stall_timeout <= 120:
            raise ValueError('Invalid client limit or capture timeout')
        if not 0.05 <= config.viewer_max_delay <= 5 or not 0 <= config.auto_reload_after <= 20:
            raise ValueError('Invalid viewer delay or firmware recovery threshold')
        if not 16 <= config.width <= 720 or not 16 <= config.height <= 576:
            raise ValueError('Invalid requested dimensions')
        if not 64000 <= config.bitrate <= 20000000 or not 8000 <= config.audio_bitrate <= 320000:
            raise ValueError('Invalid media bitrate')
        if type(config.reload_fx2) is not bool or not 0 <= config.device_number < 32:
            raise ValueError('Invalid firmware reload or device number')
        config.workspace = str(Path(config.workspace).resolve())
        return config

    def capture_command(self):
        return ['stdbuf', '-o0', str(Path(self.workspace) / 'build/bin/crusher264'),
                '-m', 'capture', '-i', self.input, '-t', self.standard,
                '-n', str(self.device_number), '-s', f'{self.width}x{self.height}',
                '-b', str(self.bitrate), '-a', str(self.audio_bitrate), '-c', '2',
                '-f', 'qbox', '-o', '-']


class Hub:
    def __init__(self, config):
        self.config = config
        self.lock = threading.Lock()
        self.clients = []
        self.tables = {}
        self.state = {'running': False, 'phase': 'idle', 'video_samples': 0, 'audio_samples': 0,
                      'output_bytes': 0, 'restarts': 0, 'error': None,
                      'last_error_at': None, 'fx2_reload_attempts': 0,
                      'viewer_drops': 0, 'viewer_drop_reasons': {},
                      'last_video': 0, 'last_output': 0, 'width': None, 'height': None}

    def status(self):
        with self.lock:
            status = dict(self.state)
            status['viewer_drop_reasons'] = dict(self.state['viewer_drop_reasons'])
            status['clients'] = len(self.clients)
        now = time.monotonic()
        last_video, last_output = status.pop('last_video'), status.pop('last_output')
        status['video_age_seconds'] = round(now - last_video, 3) if last_video else None
        status['output_age_seconds'] = round(now - last_output, 3) if last_output else None
        status['ready'] = bool(status['running'] and status['video_age_seconds'] is not None
                               and status['video_age_seconds'] < 3
                               and status['output_age_seconds'] is not None
                               and status['output_age_seconds'] < 3)
        status['standard'] = self.config.standard
        status['webrtc_url'] = self.config.webrtc_url
        status['queue_capacity_packets'] = max(1024, self.config.queue_packets)
        return status

    def subscribe(self):
        with self.lock:
            if len(self.clients) >= self.config.max_clients:
                raise ValueError('Viewer limit reached')
            # A hardware access unit can be 128 KiB. The original 48 KiB
            # queue misclassified a single valid keyframe burst as a slow viewer.
            client = {'queue': queue.Queue(max(1024, self.config.queue_packets)),
                      'active': False, 'audio_ready': False, 'reason': None}
            self.clients.append(client)
            return client

    @staticmethod
    def _finish(client):
        while True:
            try:
                client['queue'].get_nowait()
            except queue.Empty:
                break
        client['queue'].put_nowait(None)

    def unsubscribe(self, client):
        with self.lock:
            if client in self.clients:
                self.clients.remove(client)

    def _drop_locked(self, client, reason):
        client['reason'] = reason
        self._finish(client)
        if client in self.clients:
            self.clients.remove(client)
        if reason in ('queue_full', 'queue_age'):
            self.state['viewer_drops'] += 1
            reasons = self.state['viewer_drop_reasons']
            reasons[reason] = reasons.get(reason, 0) + 1
            LOG.warning('Disconnecting viewer: %s', reason)

    def drop(self, client, reason):
        with self.lock:
            self._drop_locked(client, reason)

    def reset(self):
        with self.lock:
            for client in self.clients[:]:
                self._drop_locked(client, 'capture_reset')
            self.tables.clear()
            self.state.update(running=False, phase='idle', video_samples=0, audio_samples=0,
                              last_video=0, last_output=0, width=None, height=None)

    def publish(self, packet):
        if len(packet) != 188 or packet[0] != 0x47:
            raise ValueError('Invalid MPEG-TS output packet')
        pid = ((packet[1] & 31) << 8) | packet[2]
        random_access = (pid == VIDEO_PID and packet[1] & 0x40
                         and packet[3] & 0x20 and packet[4] > 0 and packet[5] & 0x40)
        with self.lock:
            self.state['output_bytes'] += 188
            self.state['last_output'] = time.monotonic()
            if self.state['video_samples'] and self.state['phase'] in ('starting', 'streaming'):
                self.state.update(phase='streaming', error=None)
            if pid in (0, 17, 4096):
                self.tables[pid] = packet
            for client in self.clients[:]:
                if not client['active']:
                    if not random_access or not all(p in self.tables for p in (0, 4096)):
                        continue
                    for table in self.tables.values():
                        client['queue'].put_nowait((time.monotonic(), table))
                    client['active'] = True
                if pid == AUDIO_PID and not client['audio_ready']:
                    # Joining at a video keyframe may land in the middle of an
                    # audio PES. Wait for its next payload-unit start indicator.
                    if not packet[1] & 0x40:
                        continue
                    client['audio_ready'] = True
                try:
                    client['queue'].put_nowait((time.monotonic(), packet))
                except queue.Full:
                    # Dropping arbitrary H.264 packets would corrupt reference frames.
                    self._drop_locked(client, 'queue_full')


def relay_client(hub, client, write):
    """Send available packets immediately, batching syscalls without waiting."""
    while True:
        try:
            item = client['queue'].get(timeout=4)
        except queue.Empty:
            with hub.lock:
                if client not in hub.clients:
                    return
            continue
        if item is None:
            return
        queued_at, packet = item
        if time.monotonic() - queued_at > hub.config.viewer_max_delay:
            hub.drop(client, 'queue_age')
            return
        batch = bytearray(packet)
        finished = False
        for _ in range(31):
            try:
                item = client['queue'].get_nowait()
            except queue.Empty:
                break
            if item is None:
                finished = True
                break
            batch.extend(item[1])
        write(bytes(batch))
        if finished:
            return


class Capture:
    def __init__(self, config, hub, replay=None):
        self.config, self.hub, self.replay = config, hub, replay
        self.stop_event = threading.Event()
        self.processes = []
        self.process_lock = threading.Lock()
        self.started = 0
        self.empty_failures = 0
        self.session_video_samples = 0
        self.restart_requested = threading.Event()
        self.failure_reason = None
        self.thread = threading.Thread(target=self.run, daemon=True)

    def source_environment(self):
        env = dict(os.environ)
        env.pop('CRUSHER_DIAGNOSTICS', None)
        env['CRUSHER_TEST_PATTERN'] = 'off'
        recovery = self.config.auto_reload_after > 0 and self.empty_failures >= self.config.auto_reload_after
        env['CRUSHER_RELOAD_FX2'] = '1' if self.config.reload_fx2 or recovery else '0'
        return env

    @staticmethod
    def retry_delay(failures):
        return min(30, 2 ** min(5, max(1, failures)))

    def kill_children(self):
        with self.process_lock:
            children = self.processes[:]
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=4)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()

    def watchdog(self):
        while not self.stop_event.wait(1):
            self.check_stall()

    def check_stall(self):
        with self.hub.lock:
            if not self.hub.state['running'] or self.restart_requested.is_set():
                return
            last = self.hub.state['last_video'] or self.started
            samples = self.hub.state['video_samples']
        if last and time.monotonic() - last > self.config.stall_timeout:
            stage = 'stopped producing video' if samples else 'produced no video after startup'
            self.failure_reason = f'Recorder {stage} for {self.config.stall_timeout:g} seconds'
            self.restart_requested.set()
            with self.hub.lock:
                self.hub.state.update(phase='recovering', error=self.failure_reason,
                                      last_error_at=datetime.now(timezone.utc).isoformat())
            LOG.error('%s; restarting capture', self.failure_reason)
            self.kill_children()

    def read_output(self, process):
        pending = bytearray()
        while chunk := process.stdout.read(188 * 32):
            pending.extend(chunk)
            while len(pending) >= 188:
                self.hub.publish(bytes(pending[:188]))
                del pending[:188]
        if pending:
            LOG.error('Remuxer ended with an incomplete TS packet')

    def run_once(self):
        self.hub.reset()
        self.started = time.monotonic()
        self.session_video_samples = 0
        self.restart_requested.clear()
        self.failure_reason = None
        with self.hub.lock:
            # Keep the preceding error visible during the next empty attempt.
            self.hub.state.update(running=True, phase='starting')
        remux = subprocess.Popen(remux_command(standard=self.config.standard),
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)
        with self.process_lock:
            self.processes = [remux]
        reader = threading.Thread(target=self.read_output, args=(remux,), daemon=True)
        reader.start()
        source = None
        child = None
        try:
            if self.replay:
                source = open(self.replay, 'rb')
            else:
                env = self.source_environment()
                if env['CRUSHER_RELOAD_FX2'] == '1':
                    LOG.warning('Reloading FX2 RAM firmware after %d empty attempts', self.empty_failures)
                    with self.hub.lock:
                        self.hub.state['fx2_reload_attempts'] += 1
                child = subprocess.Popen(self.config.capture_command(), stdout=subprocess.PIPE,
                                         cwd=Path(self.config.workspace), env=env)
                with self.process_lock:
                    self.processes.append(child)
                source = child.stdout
            mux = Muxer()
            started, first_cts = time.monotonic(), None
            previous_video = 0
            for packet in packets(source):
                if self.stop_event.is_set():
                    break
                if self.replay and not packet[2] & 1:
                    first_cts = packet[3] if first_cts is None else first_cts
                    delay = started + (packet[3] - first_cts) / 90000 - time.monotonic()
                    if delay > 0 and self.stop_event.wait(delay):
                        break
                data = memoryview(mux.process(packet))
                self.session_video_samples = mux.video_samples
                with self.hub.lock:
                    self.hub.state.update(video_samples=mux.video_samples, audio_samples=mux.audio_samples,
                                          width=mux.width, height=mux.height)
                    if mux.video_samples != previous_video:
                        self.hub.state['last_video'] = time.monotonic()
                        previous_video = mux.video_samples
                while data:
                    written = remux.stdin.write(data)
                    if not written:
                        raise BrokenPipeError('Remuxer input closed')
                    data = data[written:]
            if self.failure_reason:
                raise RuntimeError(self.failure_reason)
            if not self.stop_event.is_set() and not mux.video_samples:
                code = child.poll() if child is not None else None
                raise RuntimeError(f'Recorder source ended without video (exit={code})')
            remux.stdin.close()
            if remux.wait(timeout=4):
                raise RuntimeError('FFmpeg remuxer failed')
            reader.join(timeout=2)
            if not self.stop_event.is_set():
                raise RuntimeError('Capture source ended')
        finally:
            self.kill_children()
            if source:
                source.close()
            reader.join(timeout=2)
            for stream in (remux.stdin, remux.stdout):
                if stream:
                    stream.close()
            self.hub.reset()
            self.started = 0

    def run(self):
        threading.Thread(target=self.watchdog, daemon=True).start()
        while not self.stop_event.is_set():
            try:
                self.run_once()
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                if not self.stop_event.is_set():
                    message = self.failure_reason or str(exc)
                    LOG.error('%s', message)
                    self.empty_failures = 0 if self.session_video_samples else self.empty_failures + 1
                    with self.hub.lock:
                        self.hub.state.update(error=message, phase='retrying',
                                              last_error_at=datetime.now(timezone.utc).isoformat())
                        self.hub.state['restarts'] += 1
            if self.stop_event.wait(self.retry_delay(self.empty_failures)):
                break

    def stop(self):
        self.stop_event.set()
        self.kill_children()
        self.thread.join(timeout=6)


def handler_class(config, hub):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def send_body(self, code, body, content_type='application/json'):
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split('?', 1)[0]
            status = hub.status()
            if path in ('/health', '/api/status'):
                self.send_body(200 if path == '/api/status' or status['ready'] else 503,
                               json.dumps(status).encode())
            elif path == '/get_status':
                root = ET.Element('status')
                venc = ET.SubElement(ET.SubElement(root, 'vi', id='0'), 'venc', id='0')
                values = {'ts_url0': '/0.ts', 'width': status['width'] or '',
                          'height': status['height'] or '',
                          'framerate': '25' if config.standard == 'pal' else '29.97'}
                for key, value in values.items():
                    ET.SubElement(venc, key).text = str(value)
                self.send_body(200, ET.tostring(root), 'application/xml')
            elif path in ('/0.ts', '/1.ts', '/stream.ts'):
                if not status['ready']:
                    self.send_body(503, b'{"error":"Waiting for capture"}')
                    return
                try:
                    client = hub.subscribe()
                except ValueError as exc:
                    self.send_body(503, json.dumps({'error': str(exc)}).encode())
                    return
                self.close_connection = True
                try:
                    self.connection.settimeout(5)
                    self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    self.send_response(200)
                    self.send_header('Content-Type', 'video/mp2t')
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('X-Accel-Buffering', 'no')
                    self.send_header('Transfer-Encoding', 'chunked')
                    self.send_header('Connection', 'close')
                    self.end_headers()

                    def write_chunk(data):
                        self.wfile.write(f'{len(data):x}\r\n'.encode() + data + b'\r\n')

                    relay_client(hub, client, write_chunk)
                    self.wfile.write(b'0\r\n\r\n')
                except (OSError, TimeoutError):
                    hub.drop(client, 'client_closed')
                finally:
                    hub.unsubscribe(client)
            elif path == '/':
                url = html.escape(config.webrtc_url, quote=True)
                body = ('<!doctype html><meta charset="utf-8"><title>USB Recorder</title>'
                        '<style>body{margin:0;background:#111;color:#eee;font:16px sans-serif}'
                        'iframe{width:100vw;height:calc(100vh - 3rem);border:0}p{margin:1rem}</style>'
                        f'<iframe src="{url}" allow="autoplay; fullscreen" allowfullscreen></iframe>'
                        '<p>Blackmagic USB Recorder · live view</p>').encode()
                self.send_body(200, body, 'text/html; charset=utf-8')
            else:
                self.send_body(404, b'{"error":"Not found"}')

        def log_message(self, fmt, *args):
            LOG.info('%s %s', self.client_address[0], fmt % args)

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--replay', type=Path, help='Paced saved QBOX source for testing; never opens USB')
    parser.add_argument('--check', action='store_true', help='Validate dependencies without opening sockets or USB')
    args = parser.parse_args()
    config = Config.load(args.config)
    missing = [program for program in ('ffmpeg', 'stdbuf') if not shutil.which(program)]
    if not args.replay and not (Path(config.workspace) / 'build/bin/crusher264').is_file():
        missing.append('build/bin/crusher264')
    if missing:
        parser.error('Missing dependencies: ' + ', '.join(missing))
    if args.check:
        print('Configuration and capture/remux dependencies are valid.')
        return
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    hub = Hub(config)
    capture = Capture(config, hub, args.replay)
    server = ThreadingHTTPServer((config.host, config.port), handler_class(config, hub))
    server.daemon_threads = True

    def stop(_signum, _frame):
        capture.stop_event.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    capture.thread.start()
    LOG.info('HTTP-TS recorder listening on %s:%s', config.host, config.port)
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        capture.stop()
        server.server_close()


if __name__ == '__main__':
    main()
