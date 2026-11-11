#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build and start the Linux USB stack, optionally replacing its native services."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

HERE = Path(__file__).resolve().parent.parent
UNITS = ('blackmagic-recorder-webrtc.service', 'blackmagic-recorder.service',
         'blackmagic-recorder-gateway.service')


def native_state():
    running, enabled = [], []
    if Path('/run/systemd/system').is_dir():
        for unit in UNITS:
            for action, result in (('is-active', running), ('is-enabled', enabled)):
                check = subprocess.run(['systemctl', action, '--quiet', unit],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if check.returncode == 0:
                    result.append(unit)
    return running, enabled


def restore_native(compose, privilege, running, enabled):
    stopped = subprocess.run(compose + ['down'], check=False)
    if stopped.returncode:
        raise RuntimeError('Container cleanup failed; native services remain disabled to avoid competing for USB. '
                           'Stop the Compose stack before restoring the native services.')
    failures = []
    for action, units in (('enable', enabled), ('start', running)):
        if units:
            result = subprocess.run(privilege + ['systemctl', action] + units, check=False)
            if result.returncode:
                failures.append(action)
    if failures:
        raise RuntimeError('Native service restoration failed: systemctl ' + ', '.join(failures))


def launch(compose, running, enabled, replace_native=False):
    native = [unit for unit in UNITS if unit in running or unit in enabled]
    if native and not replace_native:
        raise ValueError('Native recorder services are active or enabled. Use --replace-native to migrate them.')
    # Build failure must leave the currently running recorder untouched.
    subprocess.run(compose + ['build', '--pull', 'capture'], check=True)
    privilege = [] if os.geteuid() == 0 else ['sudo']
    if native and privilege:
        subprocess.run(privilege + ['-v'], check=True)
    changed = False
    try:
        if native:
            changed = True
            subprocess.run(privilege + ['systemctl', 'disable', '--now'] + native, check=True)
        subprocess.run(compose + ['up', '--detach', '--no-build', '--wait', '--wait-timeout', '120'], check=True)
    except BaseException:
        if changed:
            print('Container start failed; restoring the previous native services.', file=sys.stderr)
            restore_native(compose, privilege, running, enabled)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replace-native', action='store_true',
                        help='Disable/stop native recorder services after the image builds; restore them if startup fails')
    args = parser.parse_args()
    try:
        if platform.system() != 'Linux' or platform.machine() != 'x86_64':
            raise ValueError('Run this on the physical x86_64 Linux recorder host')
        if not Path('/dev/bus/usb').is_dir():
            raise ValueError('/dev/bus/usb is unavailable; run this in the physical rack host terminal')
        compose = ['docker', 'compose', '--project-directory', str(HERE), '-f', str(HERE / 'compose.yaml')]
        resolved = subprocess.run(compose + ['config', '--format', 'json'],
                                  capture_output=True, text=True, check=True)
        config = json.loads(resolved.stdout)
        advertised = config['services']['gateway']['environment']['MTX_WEBRTCADDITIONALHOSTS']
        address = ipaddress.ip_address(advertised)
        if address.version != 4 or address.is_multicast or address.is_unspecified or address.is_loopback:
            raise ValueError('Set RACK_IP in stream-service/.env to the rack LAN IPv4 address')
        uid, gid = config['services']['capture']['user'].split(':')
        if int(uid) <= 0 or int(gid) < 0:
            raise ValueError('Set RECORDER_UID/RECORDER_GID to the regular host account that owns the USB nodes')
        subprocess.run(['docker', 'info'], stdout=subprocess.DEVNULL, check=True)
        running, enabled = native_state()
        launch(compose, running, enabled, args.replace_native)
        print(f'WebRTC: http://{address}:18889/usb')
        print(f'Capture status: http://{address}:18890/api/status')
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
