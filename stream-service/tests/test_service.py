# SPDX-License-Identifier: GPL-2.0-only
"""Transport and service checks; no USB access, listeners, or host configuration."""
import io
import http.client
import json
import os
from pathlib import Path
import queue
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
from qbox_ts import Muxer, WORKSPACE, crc32_mpeg, h264_nals, packets, pts_bytes, remux_command
from server import Capture, Config, Hub, handler_class, relay_client
from install import render
from publish import command as publisher_command, run as run_publisher, wait_until_ready

FIXTURE = Path(os.environ.get('UVRCAST_TEST_FIXTURE', str(WORKSPACE / 'tests/capture-OWdSCyCp/capture.qbox')))
requires_fixture = unittest.skipUnless(FIXTURE.is_file(), 'Set UVRCAST_TEST_FIXTURE to an optional local QBOX recording')


class TransportTests(unittest.TestCase):
    @requires_fixture
    def test_real_capture_headers_timestamps_and_continuity(self):
        mux = Muxer()
        data = bytearray()
        with FIXTURE.open('rb') as source:
            for packet in packets(source):
                data.extend(mux.process(packet))
        self.assertEqual((mux.video_samples, mux.audio_samples), (317, 593))
        self.assertEqual((mux.width, mux.height), (720, 288))
        self.assertEqual(len(data) % 188, 0)
        expected = {}
        sections = set()
        for offset in range(0, len(data), 188):
            packet = data[offset:offset + 188]
            self.assertEqual(packet[0], 0x47)
            pid = ((packet[1] & 31) << 8) | packet[2]
            cc = packet[3] & 15
            if pid in expected:
                self.assertEqual(cc, expected[pid])
            expected[pid] = (cc + 1) & 15
            if pid in (0, 4096):
                start = 5 + packet[4]
                length = ((packet[start + 1] & 15) << 8) | packet[start + 2]
                self.assertEqual(crc32_mpeg(packet[start:start + 3 + length]), 0)
                sections.add(pid)
        self.assertEqual(sections, {0, 4096})
        self.assertEqual(pts_bytes((1 << 33) + 3600), pts_bytes(3600))

    def test_fragmented_or_invalid_capture_is_rejected(self):
        with self.assertRaises(ValueError):
            list(packets(io.BytesIO(b'bad')))
        with self.assertRaises(ValueError):
            list(packets(io.BytesIO(b'\x00' * 24)))

    def test_timestamp_wrap_and_backwards_jump(self):
        mux = Muxer()
        self.assertEqual(mux._timestamp(2, 0xfffffff0), 0xfffffff0)
        self.assertEqual(mux._timestamp(2, 20), 0x100000014)
        with self.assertRaises(ValueError):
            mux._timestamp(2, 10)

    @requires_fixture
    def test_full_ts_decodes_and_video_pixels_match_source(self):
        mux = Muxer()
        data = bytearray()
        with FIXTURE.open('rb') as source:
            for packet in packets(source):
                data.extend(mux.process(packet))
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'stream.ts'
            result = subprocess.run(remux_command(output=str(target)), input=data,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertEqual(result.stderr, b'')
            result = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-show_streams',
                                     '-of', 'json', str(target)], capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, '')
            streams = json.loads(result.stdout)['streams']
            video = next(s for s in streams if s['codec_type'] == 'video')
            audio = next(s for s in streams if s['codec_type'] == 'audio')
            self.assertEqual((video['codec_name'], video['r_frame_rate'], video['nb_read_frames']),
                             ('h264', '25/1', '317'))
            self.assertEqual((audio['codec_name'], audio['sample_rate'], audio['channels'], audio['nb_read_frames']),
                             ('aac', '48000', 2, '593'))
            ts = target.read_bytes()
            random_access_packets = 0
            for offset in range(0, len(ts), 188):
                packet = ts[offset:offset + 188]
                pid = ((packet[1] & 31) << 8) | packet[2]
                if (pid == 256 and packet[1] & 0x40 and packet[3] & 0x20
                        and packet[4] > 0 and packet[5] & 0x40):
                    random_access_packets += 1
            self.assertEqual(random_access_packets, 13)

            def video_hashes(path):
                result = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-map', '0:v:0',
                                         '-vsync', '0', '-f', 'framemd5', '-'],
                                        capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, '')
                return [line.rsplit(',', 1)[1].strip() for line in result.stdout.splitlines()
                        if line and not line.startswith('#')]

            original = FIXTURE.with_suffix('.h264')
            if original.is_file():
                self.assertEqual(video_hashes(target), video_hashes(original))

            opus = Path(directory) / 'webrtc-codecs.mkv'
            result = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(target), '-c:v', 'copy',
                '-c:a', 'libopus', '-application', 'lowdelay', '-frame_duration', '20',
                '-ar', '48000', '-ac', '2', str(opus)], capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            probe = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(opus)],
                                   capture_output=True, text=True, check=True, timeout=20)
            names = {s['codec_name'] for s in json.loads(probe.stdout)['streams']}
            self.assertEqual(names, {'h264', 'opus'})


class ServiceTests(unittest.TestCase):
    def test_container_can_override_advertised_viewer_url(self):
        with mock.patch.dict('os.environ', {'BLACKMAGIC_WEBRTC_URL': 'http://192.0.2.8:18889/usb'}):
            self.assertEqual(Config.load().webrtc_url, 'http://192.0.2.8:18889/usb')

    @requires_fixture
    def test_real_capture_process_pipeline_without_usb_or_network(self):
        with tempfile.TemporaryDirectory() as directory:
            replay = Path(directory) / 'short.qbox'
            with FIXTURE.open('rb') as source, replay.open('wb') as target:
                for kind, sid, flags, cts, payload in packets(source):
                    if not flags & 1 and cts >= 90000:
                        continue
                    target.write(struct.pack('>I4sIHHII', len(payload) + 24, b'qbox', 1,
                                             kind, sid, flags, cts) + payload)
            hub = Hub(Config())
            emitted = io.BytesIO()
            publish = hub.publish

            def record(packet):
                emitted.write(packet)
                publish(packet)

            hub.publish = record
            capture = Capture(Config(), hub, replay)
            with self.assertRaisesRegex(RuntimeError, 'Capture source ended'):
                capture.run_once()
            self.assertEqual(capture.session_video_samples, 25)
            self.assertTrue(all(child.poll() is not None for child in capture.processes))
            ts = Path(directory) / 'stream.ts'
            ts.write_bytes(emitted.getvalue())
            probe = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-show_streams',
                                     '-of', 'json', str(ts)], capture_output=True, text=True, timeout=10)
            self.assertEqual(probe.returncode, 0, probe.stderr)
            self.assertEqual(probe.stderr, '')
            video = next(s for s in json.loads(probe.stdout)['streams'] if s['codec_type'] == 'video')
            self.assertEqual(video['nb_read_frames'], '25')

    def test_empty_real_process_is_terminated_by_watchdog_with_root_error(self):
        config = Config(stall_timeout=0.1)
        config.capture_command = lambda: [sys.executable, '-u', '-c', 'import time; time.sleep(20)']
        capture = Capture(config, Hub(config))
        watchdog = threading.Thread(target=capture.watchdog, daemon=True)
        watchdog.start()
        try:
            with self.assertRaisesRegex(RuntimeError, 'Recorder produced no video'):
                capture.run_once()
            self.assertTrue(all(child.poll() is not None for child in capture.processes))
        finally:
            capture.stop_event.set()
            watchdog.join(timeout=2)

    @requires_fixture
    def test_subscriber_waits_for_keyframe_and_slow_subscriber_is_closed(self):
        hub = Hub(Config(queue_packets=8))
        client = hub.subscribe()
        mux = Muxer()
        with FIXTURE.open('rb') as source:
            first_video = None
            for packet in packets(source):
                data = mux.process(packet)
                for offset in range(0, len(data), 188):
                    ts = data[offset:offset + 188]
                    hub.publish(ts)
                    if client['active']:
                        first_video = ts
                        break
                if first_video:
                    break
        self.assertTrue(client['active'])
        first = client['queue'].get_nowait()[1]
        self.assertEqual(((first[1] & 31) << 8) | first[2], 0)  # PAT before keyframe.
        for _ in range(client['queue'].maxsize + 12):
            hub.publish(first_video)
        self.assertNotIn(client, hub.clients)
        self.assertIsNone(client['queue'].get_nowait())
        self.assertFalse(hub.status()['ready'])

    @requires_fixture
    def test_a_valid_large_keyframe_burst_does_not_disconnect_a_viewer(self):
        mux = Muxer()
        with FIXTURE.open('rb') as source:
            for packet in packets(source):
                mux.process(packet)
                if packet[0] == 2 and not packet[2] & 1:
                    picture = packet
                    break
        kind, sid, flags, cts, payload = picture
        payload = b''.join(len(nal).to_bytes(4, 'big') + nal for nal in h264_nals(payload))
        filler = b'\x0c' + b'\xff' * 100000 + b'\x80'
        payload += len(filler).to_bytes(4, 'big') + filler
        burst = mux.process((kind, sid, flags, cts + 3600, payload))
        self.assertGreater(len(burst), 256 * 188)
        hub = Hub(Config(queue_packets=256))  # Existing deployed configuration.
        client = hub.subscribe()
        for offset in range(0, len(burst), 188):
            hub.publish(burst[offset:offset + 188])
        self.assertIn(client, hub.clients)
        self.assertEqual(hub.status()['viewer_drops'], 0)

    @requires_fixture
    def test_join_skips_partial_audio_pes(self):
        hub = Hub(Config())
        client = hub.subscribe()
        mux = Muxer()
        with FIXTURE.open('rb') as source:
            for packet in packets(source):
                data = mux.process(packet)
                for offset in range(0, len(data), 188):
                    hub.publish(data[offset:offset + 188])
                    if client['active']:
                        break
                if client['active']:
                    break
        while not client['queue'].empty():
            client['queue'].get_nowait()
        continuation = b'\x47\x01\x01\x10' + b'\xff' * 184
        start = b'\x47\x41\x01\x11' + b'\xff' * 184
        hub.publish(continuation)
        self.assertTrue(client['queue'].empty())
        hub.publish(start)
        self.assertEqual(client['queue'].get_nowait()[1], start)

    def test_queued_media_older_than_latency_limit_is_disconnected(self):
        hub = Hub(Config(viewer_max_delay=0.1))
        client = hub.subscribe()
        client['queue'].put((time.monotonic() - 1, b'\x47' + b'\x00' * 187))
        written = []
        relay_client(hub, client, written.append)
        self.assertEqual(written, [])
        self.assertEqual(client['reason'], 'queue_age')
        self.assertEqual(hub.status()['viewer_drop_reasons'], {'queue_age': 1})

    def test_http_chunks_decode_and_available_packets_are_batched(self):
        config, body = Config(), io.BytesIO()
        hub = Hub(config)
        hub.state.update(running=True, video_samples=1, last_video=time.monotonic(),
                         last_output=time.monotonic())
        client = hub.subscribe()
        packet = b'\x47' + b'\x00' * 187
        for _ in range(65):
            client['queue'].put((time.monotonic(), packet))
        client['queue'].put(None)
        hub.subscribe = lambda: client
        handler = object.__new__(handler_class(config, hub))
        handler.path, handler.wfile = '/0.ts', body
        handler.connection = mock.Mock()
        headers = []
        handler.send_response = lambda code: self.assertEqual(code, 200)
        handler.send_header = lambda key, value: headers.append((key, value))
        handler.end_headers = lambda: None
        handler.do_GET()
        self.assertIn(('Transfer-Encoding', 'chunked'), headers)

        class Socket:
            def makefile(self, *_args):
                header = b'HTTP/1.1 200 OK\r\n' + b''.join(f'{k}: {v}\r\n'.encode() for k, v in headers) + b'\r\n'
                return io.BytesIO(header + body.getvalue())

        response = http.client.HTTPResponse(Socket())
        response.begin()
        self.assertEqual(response.read(), packet * 65)
        # Two full batches and one remaining packet, followed by the terminator.
        self.assertEqual(body.getvalue().count(b'1780\r\n'), 2)

    def test_empty_capture_recovery_reloads_fx2_and_can_be_disabled(self):
        capture = Capture(Config(), Hub(Config()))
        self.assertEqual(capture.source_environment()['CRUSHER_RELOAD_FX2'], '0')
        capture.empty_failures = 2
        self.assertEqual(capture.source_environment()['CRUSHER_RELOAD_FX2'], '1')
        capture.config.auto_reload_after = 0
        self.assertEqual(capture.source_environment()['CRUSHER_RELOAD_FX2'], '0')
        self.assertEqual([capture.retry_delay(n) for n in range(1, 7)], [2, 4, 8, 16, 30, 30])

    def test_watchdog_reports_recorder_failure_once_and_retains_error(self):
        config, hub = Config(), Hub(Config())
        capture = Capture(config, hub)
        capture.started = time.monotonic() - 25
        capture.kill_children = mock.Mock()
        hub.state.update(running=True, phase='starting')
        capture.check_stall()
        capture.check_stall()
        capture.kill_children.assert_called_once()
        self.assertIn('Recorder produced no video', hub.status()['error'])
        hub.reset()
        self.assertIn('Recorder produced no video', hub.status()['error'])

    def test_publisher_waits_through_unhealthy_source(self):
        stop = mock.Mock()
        stop.is_set.return_value = False
        stop.wait.return_value = False
        fetch = mock.Mock(side_effect=[{'ready': False}, {'ready': False}, {'ready': True}])
        self.assertTrue(wait_until_ready(Config(), stop, fetch))
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(stop.wait.call_count, 2)

    def test_publisher_retries_clean_ffmpeg_exit_without_systemd_restart(self):
        stop = mock.Mock()
        stop.is_set.return_value = False
        stop.wait.side_effect = [False, True]
        child = mock.Mock()
        child.wait.return_value = 0
        child.poll.return_value = 0
        with mock.patch('publish.read_status', return_value={'ready': True}), \
                mock.patch('publish.subprocess.Popen', return_value=child) as process:
            run_publisher(Config(), stop)
        self.assertEqual(process.call_count, 2)
        self.assertEqual([call.args[0] for call in stop.wait.call_args_list], [2, 4])

    def test_reset_releases_waiting_readers(self):
        hub = Hub(Config())
        client = hub.subscribe()
        hub.reset()
        self.assertIsNone(client['queue'].get_nowait())
        self.assertEqual(hub.status()['clients'], 0)

    def test_get_status_matches_existing_rack_recorder_schema(self):
        hub = Hub(Config())
        hub.state.update(width=720, height=288)
        handler = object.__new__(handler_class(Config(), hub))
        handler.path = '/get_status'
        captured = []
        handler.send_body = lambda *args: captured.append(args)
        handler.do_GET()
        from xml.etree import ElementTree as ET
        root = ET.fromstring(captured[0][1])
        vi = next(root.iter('vi'))
        venc = next(vi.iter('venc'))
        self.assertEqual((vi.get('id'), venc.get('id'), venc.findtext('ts_url0')), ('0', '0', '/0.ts'))
        self.assertEqual(venc.findtext('height'), '288')

    def test_unready_stream_returns_503_and_does_not_open_capture(self):
        hub = Hub(Config())
        handler = object.__new__(handler_class(Config(), hub))
        handler.path = '/0.ts'
        captured = []
        handler.send_body = lambda *args: captured.append(args)
        handler.do_GET()
        self.assertEqual(captured[0][0], 503)
        self.assertEqual(hub.status()['clients'], 0)

    def test_installation_and_publisher_keep_video_copy_and_usb_user_access(self):
        from types import SimpleNamespace
        with mock.patch('install.pwd.getpwnam', return_value=SimpleNamespace(pw_uid=1000, pw_gid=1000)), \
                mock.patch('install.grp.getgrgid', return_value=SimpleNamespace(gr_name='recorder')):
            files = render('ashmelev', '192.0.2.8')
        units = [value for name, value in files.items() if name.endswith('.service')]
        self.assertEqual(len(units), 3)
        for unit in units:
            self.assertIn('User=ashmelev', unit)
            self.assertIn('NoNewPrivileges=yes', unit)
        self.assertIn('PrivateDevices=no', files['/etc/systemd/system/blackmagic-recorder.service'])
        self.assertIn('Restart=always', files['/etc/systemd/system/blackmagic-recorder-webrtc.service'])
        self.assertIn('OWNER="ashmelev"', files['/etc/udev/rules.d/99-blackmagic-recorder.rules'])
        gateway = files['/etc/blackmagic-recorder/mediamtx.yml']
        self.assertIn('rtspAddress: 127.0.0.1:18554', gateway)
        self.assertIn('webrtcAdditionalHosts: ["192.0.2.8"]', gateway)
        argv = publisher_command(Config())
        self.assertEqual(argv[argv.index('-c:v') + 1], 'copy')
        self.assertEqual(argv[argv.index('-c:a') + 1], 'libopus')
        self.assertNotIn('libx264', argv)


if __name__ == '__main__':
    unittest.main(verbosity=2)
