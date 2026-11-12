"""Single-process hosted controls; FlightGear is reachable only through its local bridge."""
import asyncio
import hmac
import json
import os
import re
from pathlib import Path
import secrets
import time

from aiohttp import web, WSMsgType
from scripts.runtime_origin import runtime_origin
from scripts.controls import State, bounded_controls, generation_valid

HERE = Path(__file__).parent


class Relay:
    def __init__(self, participant_key, bridge_key, origin, clock=time.monotonic):
        if any(not re.fullmatch(r'[A-Za-z0-9_-]{24,128}', key) for key in (participant_key, bridge_key)) or participant_key == bridge_key:
            raise ValueError('Use distinct participant and bridge keys of at least 24 characters')
        if not origin.startswith(('https://', 'http://127.0.0.1:')) or origin.endswith('/'):
            raise ValueError('Set the exact HTTPS public origin without a trailing slash')
        self.keys = participant_key, bridge_key
        self.origin, self.clock = origin, clock
        self.state = State({'expiry_s': 1.0}, clock)
        self.epoch = secrets.token_hex(16)
        self.generation = None
        self.sequence = 0
        self.bridge = None
        self.last_bridge = -float('inf')
        self.sockets = set()

    def reset(self):
        self.epoch = secrets.token_hex(16)
        self.state.invalidate()
        self.sequence = 0

    def status(self):
        live = self.bridge is not None and self.clock() - self.last_bridge < .5
        if not live:
            self.state.connected = self.state.ready = False
            self.state.invalidate()
        return dict(self.state.status(), relay=live, epoch=self.epoch)

    async def socket(self, request):
        role = request.match_info['role']
        if role not in ('participant', 'bridge'):
            raise web.HTTPNotFound()
        # Browsers require the exact configured origin. Native bridge uses Bearer auth.
        key = request.query.get('key', '') if role == 'participant' else request.headers.get('Authorization', '').removeprefix('Bearer ')
        if not hmac.compare_digest(key, self.keys[role == 'bridge']):
            raise web.HTTPForbidden()
        if role == 'participant' and request.headers.get('Origin') != self.origin:
            raise web.HTTPForbidden()
        if role == 'bridge' and request.headers.get('Origin') not in (None, self.origin):
            raise web.HTTPForbidden()
        if len(self.sockets) >= 400 or (role == 'bridge' and self.bridge is not None):
            raise web.HTTPServiceUnavailable()
        ws = web.WebSocketResponse(heartbeat=10, max_msg_size=4096)
        await ws.prepare(request)
        self.sockets.add(ws)
        session = secrets.token_hex(16)  # A connection owns exactly one vote.
        if role == 'bridge':
            self.bridge = ws
            self.reset()
            self.generation = None
        tokens, updated = 4., self.clock()
        try:
            async for message in ws:
                if message.type != WSMsgType.TEXT:
                    break
                now = self.clock()
                tokens = min(4., tokens + (now - updated) * 15)
                updated = now
                if tokens < 1:
                    await ws.close(code=1008, message=b'Rate limit')
                    break
                tokens -= 1
                try:
                    data = json.loads(message.data)
                    if not isinstance(data, dict):
                        raise ValueError('Expected object')
                    if role == 'participant':
                        result = self.participant(data, session)
                    else:
                        result = self.poll(data)
                    await ws.send_json(result)
                except (ValueError, TypeError, KeyError, OverflowError):
                    await ws.close(code=1008, message=b'Invalid frame')
                    break
        finally:
            self.sockets.discard(ws)
            self.state.sessions.pop(session, None)
            if self.bridge is ws:
                self.bridge = None
                self.reset()
                self.status()
        return ws

    def participant(self, data, session):
        self.status()
        if data.get('kind') == 'status' and set(data) == {'kind'}:
            self.state.sessions.pop(session, None)
            return self.status()  # Opening an observer never creates a participant.
        if set(data) != {'kind', 'epoch', 'challenge', 'controls', 'release_brakes'} or data['kind'] != 'input':
            raise ValueError('Invalid participant frame')
        if data['epoch'] != self.epoch:
            data = dict(data, challenge=None, controls=None, release_brakes=False)
        return dict(self.state.exchange({k: data[k] for k in ('challenge', 'controls', 'release_brakes')} | {'session': session}), epoch=self.epoch)

    def poll(self, data):
        if set(data) != {'generation', 'ready', 'throttle', 'nonce'}:
            raise ValueError('Invalid telemetry')
        if not generation_valid(data['generation']) or type(data['ready']) is not bool:
            raise ValueError('Invalid simulator generation/readiness')
        if data['throttle'] is None:
            raise ValueError('Simulator throttle must be numeric')
        bounded_controls(dict(roll=0, pitch=0, rudder=0, brake=0, throttle=data['throttle']))
        if not isinstance(data['nonce'], str) or len(data['nonce']) != 32:
            raise ValueError('Invalid nonce')
        ready = data['ready']
        if data['generation'] != self.generation or ready != self.state.ready or self.clock() - self.last_bridge >= .5:
            self.reset()
        self.generation = data['generation']
        self.state.generation = self.generation
        self.state.ready = ready
        self.state.connected = True
        self.state.throttle = data['throttle']
        self.last_bridge = self.clock()
        self.sequence += 1
        status = self.status()
        return dict(kind='aggregate', epoch=self.epoch, generation=self.generation,
                    sequence=self.sequence, nonce=data['nonce'], active=status['active'],
                    controls=status['collective'], brake_release=self.state.brake_release,
                    count=status['count'], inputs=status['inputs'])

    async def page(self, request):
        if request.path == '/healthz':
            return web.json_response({'ok': True})
        if request.path == '/' and 'key' not in request.query:
            return web.Response(text=(HERE / 'phone' / 'home.html').read_text(), content_type='text/html',
                                headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
                                         'X-Content-Type-Options': 'nosniff'})
        if not hmac.compare_digest(request.query.get('key', ''), self.keys[0]):
            raise web.HTTPForbidden()
        if request.path == '/status':
            return web.json_response(self.status(), headers={'Cache-Control': 'no-store'})
        if request.path == '/join':
            return web.json_response({'url': self.origin + '/?key=' + self.keys[0], 'qr': False})
        file = {'/': 'index.html', '/projection': 'projection.html', '/relay.js': 'relay.js'}.get(request.path)
        if file is None:
            raise web.HTTPNotFound()
        body = (HERE / 'phone' / file).read_text()
        if file == 'index.html':
            body = body.replace('<script>', '<script src="/relay.js?key=' + self.keys[0] + '"></script><script>', 1)
        return web.Response(text=body, content_type='text/javascript' if file.endswith('.js') else 'text/html', headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff'})

    def app(self):
        app = web.Application(client_max_size=4096)
        app.router.add_get('/ws/{role}', self.socket)
        app.router.add_get('/{path:.*}', self.page)
        async def close(app):
            await asyncio.gather(*(ws.close(code=1001) for ws in tuple(self.sockets)))
        app.on_shutdown.append(close)
        return app


def configuration(env):
    keys = []
    for name in ('FLIGHT_PARTICIPANT_KEY', 'FLIGHT_BRIDGE_KEY'):
        value = env.get(name, '')
        if not re.fullmatch(r'[A-Za-z0-9_-]{24,128}', value):
            raise ValueError(f'Set {name} to a persistent, independently generated URL-safe key of 24–128 characters in the runtime environment')
        keys.append(value)
    if keys[0] == keys[1]:
        raise ValueError('FLIGHT_PARTICIPANT_KEY and FLIGHT_BRIDGE_KEY must be different')
    try:
        port = int(env.get('PORT', '8080'))
        if not 1 <= port <= 65535:
            raise ValueError()
    except ValueError:
        raise ValueError('PORT must be an integer from 1 to 65535') from None
    return keys[0], keys[1], runtime_origin(env), port


def main():
    try:
        participant, bridge, origin, port = configuration(os.environ)
        relay = Relay(participant, bridge, origin)
    except ValueError as error:
        raise SystemExit(f'Flight configuration error: {error}') from None
    web.run_app(relay.app(), host='0.0.0.0', port=port, access_log=None)


if __name__ == '__main__':
    main()
