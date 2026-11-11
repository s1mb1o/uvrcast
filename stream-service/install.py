#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Prepare or install the recorder's three unprivileged systemd services.

--prepare only writes reviewable files under --output. --apply installs and
starts services and requires root on the physical rack host.
"""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import grp
import hashlib
import io
import ipaddress
import json
import os
from pathlib import Path
import platform
import pwd
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

from server import Config

HERE = Path(__file__).resolve().parent
VERSION = 'v1.21.3'
ARCHIVE_SHA256 = '0a2ea7eba96023631efa1bea7804823a9145b043b6646a8a05798d4ac24ed635'
ARCHIVE_URL = (f'https://github.com/bluenviron/mediamtx/releases/download/{VERSION}/'
               f'mediamtx_{VERSION}_linux_amd64.tar.gz')
UNITS = ['blackmagic-recorder.service', 'blackmagic-recorder-gateway.service',
         'blackmagic-recorder-webrtc.service']


def quote(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'


def render(user, host):
    account = pwd.getpwnam(user)
    if account.pw_uid == 0:
        raise ValueError('Run the services under a regular user, not root')
    address = ipaddress.ip_address(host)
    if address.version != 4 or address.is_multicast or address.is_unspecified or address.is_loopback:
        raise ValueError('--webrtc-host must be the rack host LAN IPv4 address')
    config = Config(host='0.0.0.0', webrtc_url=f'http://{address}:18889/usb')
    prefix = '/etc/blackmagic-recorder'
    group = grp.getgrgid(account.pw_gid).gr_name

    def unit(description, script, config_path, extra='', runtime='blackmagic-recorder', private='yes', restart='on-failure'):
        return (f'[Unit]\nDescription={description}\nWants=network-online.target\n'
                'After=network-online.target\nStartLimitIntervalSec=0\n' + extra +
                f'\n[Service]\nType=simple\nUser={user}\nGroup={group}\n'
                f'ExecStart=/usr/bin/python3 {quote(HERE / script)} --config {quote(config_path)}\n'
                f'WorkingDirectory={str(HERE).replace("%", "%%")}\nRestart={restart}\nRestartSec=3\n'
                'TimeoutStopSec=12\nKillMode=control-group\nUMask=0077\n'
                f'RuntimeDirectory={runtime}\nNoNewPrivileges=yes\nProtectSystem=strict\n'
                f'ProtectHome=read-only\nPrivateTmp=yes\nPrivateDevices={private}\n'
                'Environment=PYTHONDONTWRITEBYTECODE=1\n'
                '\n[Install]\nWantedBy=multi-user.target\n')

    gateway = f'''# MediaMTX {VERSION}; only the local publisher may publish.
logLevel: info
api: false
metrics: false
pprof: false
playback: false
moq: false
rtsp: true
rtspAddress: 127.0.0.1:18554
rtspTransports: [tcp]
rtmp: false
hls: false
srt: false
webrtc: true
webrtcAddress: :18889
webrtcLocalUDPAddress: :18189
webrtcLocalTCPAddress: :18189
webrtcAdditionalHosts: ["{address}"]
webrtcICEServers2: []
authMethod: internal
authInternalUsers:
  - user: any
    ips: [127.0.0.1, "::1"]
    permissions:
      - action: publish
        path: usb
  - user: any
    ips: []
    permissions:
      - action: read
        path: usb
paths:
  usb:
    source: publisher
    overridePublisher: false
'''
    return {
        f'{prefix}/stream.json': json.dumps(asdict(config), indent=2) + '\n',
        f'{prefix}/mediamtx.yml': gateway,
        '/etc/udev/rules.d/99-blackmagic-recorder.rules':
            f'SUBSYSTEM=="usb", ATTR{{idVendor}}=="04b4", ATTR{{idProduct}}=="8613", OWNER="{user}", MODE="0600"\n'
            f'SUBSYSTEM=="usb", ATTR{{idVendor}}=="04b4", ATTR{{idProduct}}=="bd1c", OWNER="{user}", MODE="0600"\n',
        '/etc/systemd/system/' + UNITS[0]: unit('Blackmagic USB recorder HTTP-TS service',
            'server.py', f'{prefix}/stream.json', private='no'),
        '/etc/systemd/system/' + UNITS[1]: unit('Blackmagic USB recorder WebRTC gateway',
            'gateway.py', f'{prefix}/mediamtx.yml', runtime='blackmagic-recorder-gateway'),
        '/etc/systemd/system/' + UNITS[2]: unit('Blackmagic USB recorder WebRTC publisher',
            'publish.py', f'{prefix}/stream.json', runtime='blackmagic-recorder-webrtc',
            restart='always',
            extra=('Requires=blackmagic-recorder.service blackmagic-recorder-gateway.service\n'
                   'After=blackmagic-recorder.service blackmagic-recorder-gateway.service\n')),
    }


def install_gateway():
    target = HERE / 'bin/mediamtx'
    manifest = HERE / 'bin/mediamtx-release.json'
    if target.exists():
        if not manifest.is_file():
            raise ValueError('Existing MediaMTX binary has no installation manifest')
        info = json.loads(manifest.read_text())
        if info.get('version') != VERSION or hashlib.sha256(target.read_bytes()).hexdigest() != info.get('binary_sha256'):
            raise ValueError('Existing MediaMTX binary differs from the pinned installation')
        return
    print(f'Downloading MediaMTX {VERSION} from its official release...', flush=True)
    with urllib.request.urlopen(ARCHIVE_URL, timeout=60) as response:
        archive = response.read(64 * 1024 * 1024 + 1)
    if len(archive) > 64 * 1024 * 1024 or hashlib.sha256(archive).hexdigest() != ARCHIVE_SHA256:
        raise ValueError('MediaMTX archive failed the pinned SHA-256 check')
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as package:
        member = package.getmember('mediamtx')
        if not member.isfile() or member.size > 128 * 1024 * 1024:
            raise ValueError('Unexpected MediaMTX executable member')
        data = package.extractfile(member).read()
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(data)
    target.chmod(0o755)
    manifest.write_text(json.dumps({'version': VERSION, 'archive_url': ARCHIVE_URL,
        'archive_sha256': ARCHIVE_SHA256, 'binary_sha256': hashlib.sha256(data).hexdigest()}, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare', action='store_true')
    mode.add_argument('--apply', action='store_true')
    parser.add_argument('--webrtc-host', required=True)
    parser.add_argument('--user', default=os.environ.get('SUDO_USER') or pwd.getpwuid(os.getuid()).pw_name)
    parser.add_argument('--output', type=Path, default=HERE / 'state/prepared')
    args = parser.parse_args()
    files = render(args.user, args.webrtc_host)
    if args.prepare:
        for name, content in files.items():
            path = args.output / name.lstrip('/')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        print(f'Prepared {len(files)} files under {args.output}; host settings were not changed.')
        return
    if os.geteuid() != 0:
        parser.error('--apply requires sudo in a normal terminal on the rack host')
    if platform.machine() != 'x86_64' or platform.system() != 'Linux':
        parser.error('This installation targets the x86_64 Linux recorder host')
    if not Path('/dev/bus/usb').is_dir():
        parser.error('USB device nodes are unavailable; run in the host terminal')
    for program in ['ffmpeg', 'ffprobe', 'stdbuf', 'systemctl', 'udevadm']:
        if not shutil.which(program):
            parser.error(f'Missing dependency: {program}')
    subprocess.run(['/usr/bin/python3', str(HERE / 'server.py'), '--check'], check=True)
    encoders = subprocess.run(['ffmpeg', '-hide_banner', '-encoders'], capture_output=True, text=True, check=True)
    if 'libopus' not in encoders.stdout:
        parser.error('This ffmpeg build needs the libopus encoder')
    install_gateway()
    backup = HERE / 'state/backups' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    for name, content in files.items():
        path = Path(name)
        # Preserve an existing capture configuration on subsequent installs.
        if path.exists() and name.endswith('/stream.json'):
            print(f'Keeping existing configuration: {path}')
            continue
        if path.exists() and path.read_text() != content:
            saved = backup / name.lstrip('/')
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, saved)
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        tmp_path.chmod(0o644)
        tmp_path.replace(path)
    subprocess.run(['udevadm', 'control', '--reload-rules'], check=True)
    for product in ('8613', 'bd1c'):
        subprocess.run(['udevadm', 'trigger', '--action=add', '--subsystem-match=usb',
                        '--attr-match=idVendor=04b4', f'--attr-match=idProduct={product}'], check=True)
    subprocess.run(['udevadm', 'settle', '--timeout=5'], check=True)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'enable', *UNITS], check=True)
    subprocess.run(['systemctl', 'restart', *UNITS], check=True)
    print(f'WebRTC viewer: http://{args.webrtc_host}:18889/usb')
    print(f'Rack recorder address: http://{args.webrtc_host}:18890 (input 1)')
    print('Live status: systemctl status ' + ' '.join(UNITS))


if __name__ == '__main__':
    main()
