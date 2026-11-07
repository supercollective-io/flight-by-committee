#!/usr/bin/env python3
"""Install the pinned official Nightly 747-400 package into ignored local assets."""
import hashlib
import io
from pathlib import Path
import sys
import tempfile
import urllib.request
import zipfile

URL = 'https://fgaddon.b-cdn.net/Aircraft-trunk/747-400.zip'
SHA256 = 'e6cd96ca081891988db2e1bd8480b54850a6fb184cc339cfabdee7c09d7c6e2f'
DESTINATION = Path(__file__).resolve().parents[1] / 'test-results/assets/nightly'


def install(destination=DESTINATION):
    target = destination / '747-400'
    if target.exists():
        raise ValueError(f'{target} already exists; existing aircraft are never overwritten')
    with urllib.request.urlopen(URL, timeout=60) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise ValueError('Aircraft archive differs from the validated revision; review the upstream update before changing the checksum')
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination) as temporary:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for member in archive.namelist():
                parts = Path(member).parts
                if not parts or parts[0] != '747-400' or '..' in parts:
                    raise ValueError(f'Unexpected archive member: {member}')
            archive.extractall(temporary)
        aircraft = Path(temporary) / '747-400'
        if not (aircraft / '747-400-set.xml').is_file():
            raise ValueError('Archive has no 747-400 aircraft definition')
        aircraft.rename(target)
    print(f'Installed {target}\nSHA-256: {SHA256}')
    print('Add ../test-results/assets/nightly to nightly.aircraft_dirs in config/installations.local.toml if using a local configuration.')


if __name__ == '__main__':
    try:
        install()
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
