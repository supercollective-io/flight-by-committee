"""Outbound relay connection with independent freshness and fixed control frames."""
import asyncio
from contextlib import contextmanager
import math
import json
import os
import secrets
import threading
import time
from urllib.parse import urlsplit

import aiohttp
from scripts import phone_control as phone
from scripts.controls import bounded_controls, generation_valid



class RemoteState(phone.State):
    """Adapt validated aggregates to the same local simulator/watchdog writer."""
    def __init__(self, config, clock=time.monotonic):
        super().__init__(config, clock)
        self.frame = None
        self.received = -math.inf
        self.epoch = None
        self.sequence = 0
        self.release_token = None
        self.relay_connected = False
        self.override = False

    def invalidate(self):
        super().invalidate()
        self.frame = None
        self.received = -math.inf
        self.epoch = None
        self.sequence = 0

    def fresh(self):
        return (self.ready and not self.override and self.relay_connected and self.frame is not None
                and self.frame['active'] and self.clock() - self.received < .5)

    @property
    def frame_deadline(self):
        return self.received + .5

    def participants(self):
        return self.frame['inputs'] if self.fresh() else []

    @property
    def values(self):
        return self.frame['controls'].copy() if self.fresh() else dict(roll=0, pitch=0, rudder=0, brake=0, throttle=None)

    def status(self):
        fresh = self.fresh()
        return dict(simulator=self.connected, ready=self.ready, relay=self.relay_connected and self.clock() - self.received < .5,
                    local_operator=True, override=self.override,
                    active=bool(fresh), count=self.frame['count'] if fresh else 0,
                    throttle=self.throttle, accepted=self.applied, collective=self.values,
                    inputs=self.participants())

    def accept(self, frame, nonce, sent):
        if not isinstance(frame, dict) or set(frame) != {'kind', 'epoch', 'generation', 'sequence', 'nonce', 'active', 'controls', 'brake_release', 'count', 'inputs'}:
            raise ValueError('Invalid aggregate shape')
        bounded_controls(frame['controls'])
        if (frame['kind'] != 'aggregate' or frame['nonce'] != nonce or self.clock() - sent >= .5
                or not generation_valid(frame['generation']) or frame['generation'] != self.generation
                or type(frame['active']) is not bool):
            raise ValueError('Stale aggregate')
        if not isinstance(frame['epoch'], str) or len(frame['epoch']) != 32:
            raise ValueError('Invalid epoch')
        if type(frame['sequence']) is not int or frame['sequence'] <= 0 or (frame['epoch'] == self.epoch and frame['sequence'] <= self.sequence):
            raise ValueError('Replayed aggregate')
        if type(frame['brake_release']) is not int or not 0 <= frame['brake_release'] < 2**31:
            raise ValueError('Invalid release')
        if type(frame['count']) is not int or not 0 <= frame['count'] <= 400 or not isinstance(frame['inputs'], list) or len(frame['inputs']) != frame['count']:
            raise ValueError('Invalid participant count')
        if any(not isinstance(v, dict) or set(v) != {'roll', 'pitch'} or any(type(x) not in (int, float) or not math.isfinite(x) or not -1 <= x <= 1 for x in v.values()) for v in frame['inputs']):
            raise ValueError('Invalid participant display')
        if frame['active'] != (frame['count'] > 0):
            raise ValueError('Inconsistent participant count')
        self.epoch, self.sequence = frame['epoch'], frame['sequence']
        self.frame, self.received = frame, self.clock()
        token = (self.epoch, frame['brake_release'])
        if frame['brake_release'] and token != self.release_token:
            self.release_counter += 1
            self.brake_release = self.release_counter
            self.release_token = token
        self.relay_connected = True


async def connect(state, url, key, stop):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.netloc or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
        raise ValueError('FLIGHT_RELAY_URL must be an HTTPS origin')
    endpoint = url.rstrip('/') + '/ws/bridge'
    await connection_loop(state, endpoint, key, stop)


async def connection_loop(state, endpoint, key, stop):
    last_status = None
    timeout = aiohttp.ClientTimeout(total=3, sock_connect=2)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        while not stop.is_set():
            try:
                async with session.ws_connect(endpoint, headers={'Authorization': 'Bearer ' + key}, heartbeat=10, max_msg_size=65536) as ws:
                    with state.lock:
                        state.invalidate()  # Never resume a previous aggregate on reconnect.
                    while not stop.is_set():
                        with state.lock:
                            generation, ready, override = state.generation, state.ready, state.override
                            throttle = state.throttle
                        if not generation_valid(generation):
                            await asyncio.sleep(.1)
                            continue
                        nonce = secrets.token_hex(16)
                        sent = state.clock()
                        await ws.send_json(dict(generation=int(generation), ready=ready, override=override, throttle=throttle, nonce=nonce))
                        frame = await asyncio.wait_for(ws.receive_json(), .5)
                        with state.lock:
                            state.accept(frame, nonce, sent)
                        await asyncio.sleep(.1)
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError, TypeError, RuntimeError):
                with state.lock:
                    state.relay_connected = False
                    state.invalidate()
                await asyncio.sleep(.3)
            with state.lock:
                status = 'Relay connected' if state.relay_connected else 'Relay unavailable — momentary controls released; throttle retained; flight continues'
            if status != last_status:
                print(status, flush=True)
                last_status = status


@contextmanager
def running(config, simulator_port):
    """Hosted mode owns the simulator writer; local routes are read-only observers."""
    url, key = os.environ['FLIGHT_RELAY_URL'], os.environ['FLIGHT_BRIDGE_KEY']
    if len(key) < 24:
        raise ValueError('FLIGHT_BRIDGE_KEY must have at least 24 characters')
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.netloc or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
        raise ValueError('FLIGHT_RELAY_URL must be an HTTPS origin')
    state = RemoteState(config)
    secret = secrets.token_urlsafe(24)
    # This local server exposes status/projection, never a second active input route.
    handler = phone.handler_for(state, secret)
    class Observer(handler):
        def do_POST(self):
            if (not self.authorised() or urlsplit(self.path).path != '/override'
                    or self.headers.get('Origin') != 'http://' + self.headers.get('Host', '')):
                return self.reply(403, {})
            try:
                length = int(self.headers.get('Content-Length', 0))
                if not 0 < length <= 100:
                    raise ValueError('Invalid request size')
                self.connection.settimeout(1)
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict) or set(data) != {'enabled'} or type(data['enabled']) is not bool:
                    raise ValueError('Invalid override')
                with state.lock:
                    state.override = data['enabled']
                    state.invalidate()
                print('Operator intervention: ' + ('local control enabled' if data['enabled'] else 'crowd control enabled; fresh input required'), flush=True)
                self.reply(200, {'override': data['enabled']})
            except (ValueError, OSError):
                self.reply(400, {})
    server = phone.ThreadingHTTPServer(('127.0.0.1', config['port']), Observer)
    server.daemon_threads = True
    stop = threading.Event()
    threads = [threading.Thread(target=server.serve_forever, daemon=True),
               threading.Thread(target=phone.bridge, args=(state, simulator_port, stop), daemon=True),
               threading.Thread(target=lambda: asyncio.run(connect(state, url, key, stop)), daemon=True)]
    state.projection_url = f'http://127.0.0.1:{server.server_port}/projection?key={secret}'
    print(f'Hosted controls: {url}\nLocal projection: {state.projection_url}\n'
          f'Local operator monitor: http://127.0.0.1:{server.server_port}/?key={secret}&monitor=1\n'
          'The relay participant link must include the participant key. Local HTTP controls are disabled in hosted mode.\n'
          'Use the local operator monitor to take manual control. Loss never pauses flight.', flush=True)
    for thread in threads:
        thread.start()
    try:
        yield state
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        for thread in threads:
            thread.join(timeout=4)
