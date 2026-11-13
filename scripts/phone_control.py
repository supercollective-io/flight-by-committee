"""Profile-selected, local-network phone controls (standard library only)."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import ipaddress
import socket
import threading
from urllib.parse import parse_qs, urlsplit
from xml.etree import ElementTree as ET

from scripts.controls import AXES, State
PREFIX = '/sim/committee/phone/'
PATH = re.compile(r'/controls/(?:[a-zA-Z0-9_-]+(?:\[\d+\])?/)*[a-zA-Z0-9_-]+(?:\[\d+\])?\Z')


def validate(config):
    from scripts.flightgear import keys, number
    keys(config, ('layout', 'port', 'expiry_s', 'ready_property', 'controls', 'brake_release_paths', 'body'),
         ('layout', 'port', 'expiry_s', 'ready_property', 'controls'), 'input')
    if 'body' in config:
        keys(config['body'], ('model', 'camera', 'max_poses', 'camera_elevation_deg', 'preview'),
             ('model',), 'body input')
        if not isinstance(config['body']['model'], str) or not config['body']['model'].strip():
            raise ValueError('Body model must be a non-empty path')
    if config['layout'] != 'landing':
        raise ValueError('Unknown phone layout')
    if type(config['port']) is not int:
        raise ValueError('Phone port must be an integer')
    number(config['port'], 1024, 65535, 'phone port')
    number(config['expiry_s'], 0.3, 3, 'input expiry')
    if not re.fullmatch(r'/[a-zA-Z0-9_/-]+', config['ready_property']):
        raise ValueError('Invalid input readiness property')
    keys(config['controls'], AXES, AXES, 'input controls')
    used = set()
    for axis, mapping in config['controls'].items():
        keys(mapping, ('paths', 'scale'), ('paths', 'scale'), axis)
        number(mapping['scale'], -1, 1, axis + ' scale')
        if mapping['scale'] == 0 or (axis in ('brake', 'throttle') and mapping['scale'] != 1):
            raise ValueError('Invalid control scale')
        paths = mapping['paths']
        if not isinstance(paths, list) or not paths:
            raise ValueError('Control paths must be a non-empty array')
        for path in paths:
            if not isinstance(path, str) or not PATH.fullmatch(path) or path in used:
                raise ValueError('Invalid or duplicate control path')
            used.add(path)
    releases = config.get('brake_release_paths', [])
    if not isinstance(releases, list) or any(not isinstance(p, str) or not (PATH.fullmatch(p) or p == '/autopilot/autobrake/step') for p in releases):
        raise ValueError('Invalid brake release paths')
    return config


def watchdog_xml(config, destination):
    """Nasal applies complete staged frames and releases controls independently."""
    mappings = json.dumps(config['controls'])
    ready = json.dumps(config['ready_property'])
    script = '''
var base = '/sim/committee/phone/';
var mapping = MAPPINGS;
var momentary = MOMENTARY;
var generation = getprop(base ~ 'generation');
if (generation == nil) generation = 0;
setprop(base ~ 'generation', generation + 1);
setprop(base ~ 'sequence', 0);
setprop(base ~ 'connected', 0);
setprop(base ~ 'brake-release-ack', 0);
var last = 0;
var received = systime();
var active = 0;
var release = func {
  foreach (var axis; momentary) {
    foreach (var path; mapping[axis].paths) setprop(path, 0);
  }
  setprop(base ~ 'connected', 0);
  if (active) print('Phone disconnected: momentary controls released; throttle retained.');
  active = 0;
};
var tick = func {
  var sequence = getprop(base ~ 'sequence');
  if (getprop(base ~ 'frame-generation') != generation + 1) {
    if (active) release();
  } elsif (sequence != last and getprop(READY) == 1) {
    last = sequence;
    received = systime();
    if (!getprop(base ~ 'alive')) {
      if (active) release();
      return;
    }
    var release_id = getprop(base ~ 'brake-release');
    if (release_id != nil and release_id > 0 and release_id != getprop(base ~ 'brake-release-ack')) {
      foreach (var path; RELEASE_PATHS) setprop(path, 0);
      setprop(base ~ 'brake-release-ack', release_id);
    }
    foreach (var axis; momentary) {
      var value = getprop(base ~ axis);
      foreach (var path; mapping[axis].paths) setprop(path, value * mapping[axis].scale);
    }
    var throttle = getprop(base ~ 'throttle');
    if (THROTTLE_ENABLED and throttle != nil and throttle >= 0) {
      foreach (var path; mapping.throttle.paths) setprop(path, throttle);
    }
    setprop(base ~ 'connected', 1);
    if (!active) print('Phone connected: aircraft controls active.');
    active = 1;
  } else {
    if (active and (systime() - received >= EXPIRY or getprop(READY) != 1)) release();
  }
};
setlistener('/sim/signals/frame', tick);
'''.replace('MAPPINGS', mappings).replace('MOMENTARY', json.dumps(config.get('owned_axes', ['roll', 'pitch', 'rudder', 'brake']))).replace('THROTTLE_ENABLED', '0' if 'body' in config else '1').replace('READY', ready).replace('EXPIRY', str(config['expiry_s'])).replace('RELEASE_PATHS', json.dumps(config.get('brake_release_paths', [])))
    root = ET.Element('PropertyList')
    sim = ET.SubElement(root, 'sim')
    node = ET.SubElement(ET.SubElement(sim, 'committee'), 'phone')
    ET.SubElement(node, 'generation', {'type': 'int', 'preserve': 'y'}).text = '0'
    nasal = ET.SubElement(ET.SubElement(root, 'nasal'), 'committee_phone')
    ET.SubElement(nasal, 'script').text = script
    ET.ElementTree(root).write(destination, encoding='utf-8', xml_declaration=True)


def lan_addresses(output):
    """Prefer active physical interfaces, never a VPN's default route."""
    addresses = []
    for block in re.split(r'(?m)(?=^[^\s:]+: flags=)', output):
        interface = block.split(':', 1)[0]
        if not re.fullmatch(r'(?:en|eth|wlan|wlp|wlx)[a-zA-Z0-9]*', interface):
            continue
        if 'status: inactive' in block or 'UP' not in block.split('\n', 1)[0]:
            continue
        for address in re.findall(r'\binet (\d+\.\d+\.\d+\.\d+)', block):
            ip = ipaddress.ip_address(address)
            if not ip.is_loopback and not ip.is_link_local:
                addresses.append(address)
    return sorted(set(addresses))


def discover_addresses():
    executable = shutil.which('ifconfig')
    if not executable and Path('/sbin/ifconfig').is_file():
        executable = '/sbin/ifconfig'
    if executable:
        try:
            result = subprocess.run([executable], capture_output=True, text=True, timeout=3, check=True)
            addresses = lan_addresses(result.stdout)
            if addresses:
                return addresses
        except (OSError, subprocess.SubprocessError):
            pass
    addresses = set()
    try:
        addresses.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(('192.0.2.1', 9))
            addresses.add(probe.getsockname()[0])
    except OSError:
        pass
    return sorted(a for a in addresses if not ipaddress.ip_address(a).is_loopback)


def qr_code(url, kind='SVG'):
    executable = shutil.which('qrencode')
    if not executable:
        return None
    try:
        return subprocess.run([executable, '-t', kind, '-m', '4', '-o', '-'],
                              input=url.encode(), capture_output=True, timeout=3, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return None



def bridge(state, port, stop):
    from scripts.flightgear_test import Client
    client = None
    sequence = 0
    last_status = None
    try:
        while not stop.is_set():
            try:
                if client is None:
                    client = Client(port, timeout=0.5)
                    client.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                generation = client.get(PREFIX + 'generation')
                ready = client.get(state.config['ready_property']) == 1
                throttle = client.get(state.config['controls']['throttle']['paths'][0])
                with state.lock:
                    if generation != state.generation or ready != state.ready:
                        state.invalidate()
                    state.generation, state.ready, state.connected = generation, ready, True
                    state.throttle = throttle
                    fresh = state.fresh()
                    values = state.values.copy()
                    brake_release = state.brake_release
                    deadline = getattr(state, 'frame_deadline', state.clock() + state.config['expiry_s'])
                if fresh:
                    if brake_release and client.get(PREFIX + 'brake-release-ack') == brake_release:
                        with state.lock:
                            if state.brake_release == brake_release:
                                state.brake_release = 0
                        brake_release = 0
                    client.command(f'set {PREFIX}brake-release {brake_release}')
                    for axis, value in values.items():
                        client.command(f'set {PREFIX}{axis} {-1 if value is None else value}')
                    client.command(f'set {PREFIX}frame-generation {generation}')
                    with state.lock:
                        fresh = state.fresh() and state.clock() < deadline and state.generation == generation
                    client.command(f'set {PREFIX}alive {1 if fresh else 0}')
                    sequence += 1
                    client.command(f'set {PREFIX}sequence {sequence}')
                    with state.lock:
                        state.applied = {k: v if fresh else 0 for k, v in values.items() if k != 'throttle'}
                else:
                    client.command(f'set {PREFIX}frame-generation {generation}')
                    client.command(f'set {PREFIX}alive 0')
                    sequence += 1
                    client.command(f'set {PREFIX}sequence {sequence}')
                    with state.lock:
                        state.applied = dict.fromkeys(state.applied, 0)
            except (OSError, ValueError, RuntimeError):
                if client:
                    client.close()
                client = None
                with state.lock:
                    state.connected = state.ready = False
                    state.invalidate()
            with state.lock:
                status = ('FlightGear unavailable' if not state.connected else
                          'Waiting for approach readiness' if not state.ready else
                          f'{len(state.participants())} participants — aircraft control active' if state.fresh() else
                          'No fresh input — flight continues')
            if status != last_status:
                print(status, flush=True)
                last_status = status
            stop.wait(0.1 if client else 0.5)
    finally:
        if client:
            client.close()


def handler_for(state, secret):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, code, data, mime='application/json'):
            body = data if isinstance(data, bytes) else json.dumps(data).encode()
            self.send_response(code)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def authorised(self):
            query = parse_qs(urlsplit(self.path).query)
            return secrets.compare_digest(query.get('key', [''])[0], secret)

        def do_GET(self):
            if not self.authorised():
                return self.reply(403, {'error': 'This link is missing a key or belongs to an earlier flight. Use the complete URL printed by the current launcher.'})
            path = urlsplit(self.path).path
            if path == '/':
                return self.reply(200, (Path(__file__).parent / 'phone/index.html').read_bytes(), 'text/html; charset=utf-8')
            if path == '/projection':
                return self.reply(200, (Path(__file__).parent / 'phone/projection.html').read_bytes(), 'text/html; charset=utf-8')
            if path == '/join':
                return self.reply(200, dict(url=state.join_url, qr=state.qr_svg is not None))
            if path == '/qr.svg' and state.qr_svg is not None:
                return self.reply(200, state.qr_svg, 'image/svg+xml')
            if path == '/status':
                with state.lock:
                    return self.reply(200, state.status())
            self.reply(404, {})

        def do_POST(self):
            if not self.authorised() or urlsplit(self.path).path not in ('/input', '/leave'):
                return self.reply(403, {})
            # No cross-origin browser access; all assets and input share one origin.
            if self.headers.get('Origin') not in (None, 'http://' + self.headers.get('Host', '')):
                return self.reply(403, {})
            try:
                length = int(self.headers.get('Content-Length', 0))
                if not 0 < length <= 2048:
                    raise ValueError('Invalid request size')
                self.connection.settimeout(1)
                data = json.loads(self.rfile.read(length))
                with state.lock:
                    if urlsplit(self.path).path == '/leave':
                        if not isinstance(data, dict) or set(data) != {'session'} or not isinstance(data['session'], str):
                            raise ValueError('Invalid departure')
                        state.sessions.pop(data['session'], None)
                        result = state.status()
                    else:
                        result = state.exchange(data)
                self.reply(200, result)
            except (ValueError, OSError):
                self.reply(400, {'error': 'Invalid control frame'})

    return Handler


def make_server(state, secret, port):
    try:
        server = ThreadingHTTPServer(('0.0.0.0', port), handler_for(state, secret))
    except OSError as exc:
        raise ValueError(f'Cannot start phone/overlay HTTP server on port {port}: {exc}') from exc
    server.daemon_threads = True
    return server


@contextmanager
def running(config, simulator_port):
    state = State(config)
    secret = secrets.token_urlsafe(24)
    server = make_server(state, secret, config['port'])
    stop = threading.Event()
    threads = [threading.Thread(target=server.serve_forever, daemon=True),
               threading.Thread(target=bridge, args=(state, simulator_port, stop), daemon=True)]
    addresses = discover_addresses()
    urls = [f'http://{address}:{server.server_port}/?key={secret}' for address in addresses]
    if urls:
        state.join_url = urls[0]
        state.qr_svg = qr_code(state.join_url)
        print(f'Phone: scan this QR code on the same Wi-Fi, or open:\n  {state.join_url}', flush=True)
        terminal_qr = qr_code(state.join_url, 'ANSIUTF8')
        if terminal_qr:
            print(terminal_qr.decode(), flush=True)
        else:
            print('QR unavailable. Install qrencode (macOS: brew install qrencode), then relaunch.', flush=True)
        for url in urls[1:]:
            print(f'Alternative LAN address: {url}', flush=True)
    else:
        print('No LAN address detected. Connect the computer to Wi-Fi and relaunch.', flush=True)
    print(f'Computer only — status and QR code:\n  http://127.0.0.1:{server.server_port}/?key={secret}&monitor=1', flush=True)
    state.projection_url = f'http://127.0.0.1:{server.server_port}/projection?key={secret}'
    print(f'OBS browser overlay (this computer only):\n  {state.projection_url}', flush=True)
    print('Pause/reset remain in FlightGear.', flush=True)
    for thread in threads:
        thread.start()
    try:
        yield state
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        for thread in threads:
            thread.join(timeout=3)
