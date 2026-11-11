# SPDX-License-Identifier: GPL-2.0-only
"""Daemon-free Compose validation and tests of recovery and migration behavior."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent.parent


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, HERE / 'docker' / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


health = load('container_health', 'healthcheck.py')
start = load('container_start', 'start.py')


class ContainerTests(unittest.TestCase):
    def test_compose_resolves_without_a_daemon_and_preserves_usb_hotplug(self):
        if not shutil.which('docker'):
            self.skipTest('Docker CLI is required for client-only Compose validation')
        env = dict(os.environ, RACK_IP='192.0.2.8', RECORDER_UID='1000', RECORDER_GID='1000')
        result = subprocess.run(['docker', 'compose', '-f', str(HERE / 'compose.yaml'),
                                 'config', '--format', 'json'], cwd=HERE, env=env,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        services = json.loads(result.stdout)['services']
        self.assertEqual(set(services), {'capture', 'gateway', 'publisher'})
        for service in services.values():
            self.assertEqual(service['network_mode'], 'host')
            self.assertEqual(service['user'], '1000:1000')
            self.assertTrue(service['read_only'])
            self.assertFalse(service.get('privileged', False))
            self.assertEqual(service['cap_drop'], ['ALL'])
        usb = [v for v in services['capture']['volumes'] if v['target'] == '/dev/bus/usb']
        self.assertEqual(len(usb), 1)
        self.assertEqual(usb[0]['source'], '/dev/bus/usb')
        self.assertFalse(usb[0]['bind']['create_host_path'])
        self.assertIn('c 189:* rw', services['capture']['device_cgroup_rules'])
        for name in ('gateway', 'publisher'):
            self.assertFalse(any(v['target'] == '/dev/bus/usb' for v in services[name]['volumes']))
        self.assertEqual(services['capture']['environment']['BLACKMAGIC_WEBRTC_URL'],
                         'http://192.0.2.8:18889/usb')
        self.assertEqual(services['gateway']['environment']['MTX_WEBRTCADDITIONALHOSTS'], '192.0.2.8')

    def test_publisher_health_requires_fresh_capture_and_both_live_tracks(self):
        get = mock.Mock(side_effect=[{'ready': True},
            {'online': True, 'tracks2': [{'codec': 'H264'}, {'codec': 'Opus'}]}])
        health.check('publisher', get)
        get = mock.Mock(side_effect=[{'ready': True}, {'online': True, 'tracks': ['H264']}])
        with self.assertRaisesRegex(ValueError, 'H264 and Opus'):
            health.check('publisher', get)
        get = mock.Mock(return_value={'ready': False, 'error': 'No video from recorder'})
        with self.assertRaisesRegex(ValueError, 'No video from recorder'):
            health.check('publisher', get)
        self.assertEqual(get.call_count, 1)

    def test_image_build_failure_leaves_native_services_running(self):
        compose = ['docker', 'compose']
        failure = subprocess.CalledProcessError(1, 'build')
        with mock.patch.object(start.subprocess, 'run', side_effect=failure) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                start.launch(compose, list(start.UNITS), list(start.UNITS), True)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0], compose + ['build', '--pull', 'capture'])

    def test_failed_start_restores_only_previously_enabled_and_running_units(self):
        calls = []

        def run(argv, **_kwargs):
            calls.append(argv)
            if 'up' in argv:
                raise subprocess.CalledProcessError(1, argv)
            return subprocess.CompletedProcess(argv, 0)

        running, enabled = list(start.UNITS[:2]), list(start.UNITS[1:])
        with mock.patch.object(start.subprocess, 'run', side_effect=run), \
                mock.patch.object(start.os, 'geteuid', return_value=0):
            with self.assertRaises(subprocess.CalledProcessError):
                start.launch(['docker', 'compose'], running, enabled, True)
        self.assertEqual(calls[0], ['docker', 'compose', 'build', '--pull', 'capture'])
        self.assertEqual(calls[1], ['systemctl', 'disable', '--now'] + list(start.UNITS))
        self.assertEqual(calls[-3:], [['docker', 'compose', 'down'],
                                    ['systemctl', 'enable'] + enabled,
                                    ['systemctl', 'start'] + running])

    def test_native_services_require_explicit_migration_flag(self):
        with mock.patch.object(start.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, '--replace-native'):
                start.launch(['docker', 'compose'], [start.UNITS[0]], [], False)
            run.assert_not_called()

    def test_failed_container_cleanup_does_not_start_a_competing_native_capture(self):
        with mock.patch.object(start.subprocess, 'run', return_value=subprocess.CompletedProcess('down', 1)) as run:
            with self.assertRaisesRegex(RuntimeError, 'native services remain disabled'):
                start.restore_native(['docker', 'compose'], [], list(start.UNITS), list(start.UNITS))
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0], ['docker', 'compose', 'down'])

    def test_successful_migration_builds_before_releasing_recorder(self):
        with mock.patch.object(start.subprocess, 'run') as run, \
                mock.patch.object(start.os, 'geteuid', return_value=0):
            start.launch(['docker', 'compose'], list(start.UNITS), list(start.UNITS), True)
        calls = [call.args[0] for call in run.call_args_list]
        self.assertEqual(len(calls), 3)
        self.assertIn('build', calls[0])
        self.assertEqual(calls[1], ['systemctl', 'disable', '--now'] + list(start.UNITS))
        self.assertIn('--wait', calls[2])


if __name__ == '__main__':
    unittest.main(verbosity=2)
