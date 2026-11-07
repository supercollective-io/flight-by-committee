"""Local live aircraft preview: uv run python -m scripts.preview_livery."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
from urllib.parse import parse_qs, unquote, urlsplit
import xml.etree.ElementTree as ET

from scripts import build_livery, flightgear

ROOT = flightgear.ROOT
MESHES = ('747-400_fuselage', '747-400_wings', '747-400_gear', 'GE_CF6-80C2B1F')


def aircraft_directory(resolved):
    aircraft = resolved['profile']['aircraft']
    if aircraft != '747-400':
        raise ValueError('The live preview currently supports the 747-400 only')
    for directory in resolved['installation']['aircraft_dirs']:
        match = next(iter(sorted(Path(directory).rglob(f'{aircraft}-set.xml'))), None)
        if match:
            return match.parent.resolve()
    raise ValueError('747-400 not installed; run uv run python scripts/install_747.py')


def convert_models(aircraft, cache):
    """Convert actual exterior meshes; retain AC3D UVs and XML engine offsets."""
    converter = shutil.which('assimp')
    if not converter:
        raise ValueError('Install the Assimp CLI first (macOS: brew install assimp)')
    cache.mkdir(parents=True, exist_ok=True)
    models = aircraft / 'Models'
    for stem in MESHES:
        source = models / f'{stem}.ac'
        digest = hashlib.sha256(source.read_bytes() + b'preview-gltf-v2').hexdigest()
        output = cache / f'{stem}.gltf'
        stamp = cache / f'{stem}.sha256'
        if not (output.is_file() and stamp.is_file() and stamp.read_text() == digest):
            result = subprocess.run([converter, 'export', str(source), str(output), '-fgltf2'],
                                    capture_output=True, text=True)
            if result.returncode:
                raise ValueError(f'Could not convert {source.name}: {result.stderr or result.stdout}')
            document = json.loads(output.read_text())
            # Assimp's AC3D exporter can omit diffuse colours from glTF PBR
            # materials. Restore them so rubber/glass do not become white.
            colours = {}
            for line in source.read_text().splitlines():
                match = re.match(r'MATERIAL "([^"]+)" rgb ([\d.eE+ -]+) amb .* trans ([\d.eE+-]+)', line)
                if match:
                    colours[match[1]] = [*map(float, match[2].split()), 1 - float(match[3])]
            skin_images = set()
            for index, image in enumerate(document.get('images', [])):
                original = image['uri']
                if Path(original).name == 'BOE.png':
                    skin_images.add(index)
                    image['uri'] = '/texture.png'
                else:
                    texture = (source.parent / original).resolve()
                    image['uri'] = '/aircraft/' + texture.relative_to(aircraft).as_posix()
            for material in document.get('materials', []):
                for original_name in sorted(colours, key=len, reverse=True):
                    if material.get('name', '').startswith(original_name):
                        material.setdefault('pbrMetallicRoughness', {})['baseColorFactor'] = colours[original_name]
                        if colours[original_name][3] < 1:
                            material['alphaMode'] = 'BLEND'
                        break
                texture = material.get('pbrMetallicRoughness', {}).get('baseColorTexture', {})
                if 'index' in texture:
                    image_index = document['textures'][texture['index']]['source']
                    material['extras'] = {'livery': image_index in skin_images}
            output.write_text(json.dumps(document))
            stamp.write_text(digest)
    parts = [{'name': stem, 'url': f'/model/{stem}.gltf', 'position': [0, 0, 0]}
             for stem in MESHES[:3]]
    wings = ET.parse(models / '747-400_wings.xml').getroot()
    for model in wings.findall('model'):
        if (model.findtext('path') or '').endswith('/GE_CF6-80C2B1F.xml'):
            offsets = model.find('offsets')
            # AC3D/glTF is Y-up; FlightGear XML is Z-up, positive Y to starboard.
            x, y, z = [float(offsets.findtext(f'{axis}-m', '0')) for axis in 'xyz']
            parts.append({'name': 'engine', 'url': '/model/GE_CF6-80C2B1F.gltf',
                          'position': [x, z, -y]})
    if sum(part['name'] == 'engine' for part in parts) != 4:
        raise ValueError('Expected four engine placements in the aircraft XML')
    return parts


class LiveLivery:
    def __init__(self, name, root=ROOT):
        self.name, self.root = name, root
        self.directory = build_livery.livery_directory(root, '747-400', name)
        self.lock = threading.Lock()
        self.state = {'name': name, 'revision': None, 'error': None, 'build_ms': None}
        self.signature = None
        self.texture = b''

    def refresh(self):
        watched = [self.directory / f'{self.name}.svg',
                   *sorted((self.directory / 'details').glob('*.png')),
                   *sorted((self.directory / 'fonts').glob('*.ttf'))]
        signature = []
        for path in watched:
            try:
                stat = path.stat()
                signature.append((str(path), stat.st_mtime_ns, stat.st_size))
            except OSError:
                signature.append((str(path), None, None))
        signature = tuple(signature)
        if signature == self.signature:
            return
        self.signature = signature
        start = time.monotonic()
        try:
            output = build_livery.build(self.name, root=self.root)
            texture = output.read_bytes()
            with self.lock:
                self.texture = texture
                self.state.update(revision=hashlib.sha256(texture).hexdigest(), error=None,
                                  build_ms=round((time.monotonic() - start) * 1000))
        except Exception as exc:
            # Keep the last good texture visible while the SVG is being edited.
            with self.lock:
                self.state['error'] = str(exc)

    def watch(self, stop):
        while not stop.wait(.5):
            self.refresh()


def safe_file(base, relative):
    path = (base / relative).resolve()
    if not path.is_relative_to(base.resolve()) or not path.is_file():
        return None
    return path


def design_catalogue(directory):
    """Discover complete editable liveries; optional metadata supplies display copy."""
    metadata = directory / 'designs.json'
    descriptions = {item['name']: item for item in json.loads(metadata.read_text())} if metadata.exists() else {}
    names = [path.stem for path in sorted(directory.glob('*.svg'))
             if path.with_suffix('.xml').is_file()]
    return [dict(name=name, label=descriptions.get(name, {}).get('label', name),
                 description=descriptions.get(name, {}).get('description', '')) for name in names]


def handler_for(live, aircraft, cache, parts, root=ROOT, designs=None, catalogue=None):
    designs = designs or {live.name: live}
    catalogue = catalogue or [{'name': live.name, 'label': live.name, 'description': ''}]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            url = urlsplit(self.path)
            path = unquote(url.path)
            name = parse_qs(url.query).get('livery', [live.name])[0]
            selected = designs.get(name)
            if path in ('/state', '/texture.png') and selected is None:
                return self.send_error(404, 'Unknown livery')
            if path == '/state':
                with selected.lock:
                    state = dict(selected.state, parts=parts, designs=catalogue)
                return self.send_bytes(json.dumps(state).encode(), 'application/json')
            if path == '/texture.png':
                with selected.lock:
                    texture = selected.texture
                return self.send_bytes(texture, 'image/png') if texture else self.send_error(503)
            routes = {'/model/': cache, '/aircraft/': aircraft,
                      '/vendor/': root / 'preview/node_modules/three',
                      '/source/': live.directory, '/': root / 'preview'}
            for prefix, base in routes.items():
                if path.startswith(prefix):
                    relative = path[len(prefix):] or 'index.html'
                    file = safe_file(base, relative)
                    if file:
                        kind = mimetypes.guess_type(file)[0] or 'application/octet-stream'
                        return self.send_bytes(file.read_bytes(), kind)
                    break
            self.send_error(404)

        def send_bytes(self, data, kind):
            self.send_response(200)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', default='karlsruhe-747-landing')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    try:
        if not 1 <= args.port <= 65535:
            raise ValueError('Port must be between 1 and 65535')
        if not (ROOT / 'preview/node_modules/three/build/three.module.js').is_file():
            raise ValueError('Install the preview dependency first: npm ci --prefix preview')
        resolved = flightgear.resolve(args.profile)
        name = resolved['profile'].get('livery')
        if not name:
            raise ValueError('Choose a profile with a livery setting')
        aircraft = aircraft_directory(resolved)
        cache_id = hashlib.sha256(str(aircraft).encode()).hexdigest()[:12]
        cache = ROOT / 'test-results/preview-models' / cache_id
        parts = convert_models(aircraft, cache)
        live = LiveLivery(name)
        catalogue = design_catalogue(live.directory)
        designs = {item['name']: LiveLivery(item['name']) for item in catalogue}
        designs[name] = live
        for design in designs.values():
            design.refresh()
        if live.state['error']:
            raise ValueError(live.state['error'])
        server = ThreadingHTTPServer(('127.0.0.1', args.port), handler_for(
            live, aircraft, cache, parts, designs=designs, catalogue=catalogue))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    stop = threading.Event()
    def watch_all():
        while not stop.wait(.5):
            for design in designs.values():
                if stop.is_set():
                    return
                design.refresh()
    worker = threading.Thread(target=watch_all, daemon=True)
    worker.start()
    print(f'Livery studio: http://127.0.0.1:{args.port}\nWatching {len(designs)} designs in {live.directory}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
        worker.join(timeout=5)


if __name__ == '__main__':
    main()
