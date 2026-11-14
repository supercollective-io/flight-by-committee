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
from scripts.hybrid_feedback import validate_feedback

HERE = Path(__file__).parent


class Relay:
    def __init__(self, participant_key, bridge_key, origin, clock=time.monotonic, operator_token=None):
        if any(not re.fullmatch(r'[A-Za-z0-9_-]{24,128}', key) for key in (participant_key, bridge_key)) or participant_key == bridge_key:
            raise ValueError('Use distinct participant and bridge keys of at least 24 characters')
        if not origin.startswith(('https://', 'http://127.0.0.1:')) or origin.endswith('/'):
            raise ValueError('Set the exact HTTPS public origin without a trailing slash')
        if operator_token is not None and (not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', operator_token) or operator_token in (participant_key, bridge_key)):
            raise ValueError('FLIGHT_OPERATOR_TOKEN must be a distinct URL-safe token of 32–128 characters')
        self.operator_token = operator_token
        self.keys = participant_key, bridge_key
        self.origin, self.clock = origin, clock
        self.state = State({'expiry_s': 1.0}, clock)
        self.epoch = secrets.token_hex(16)
        self.generation = None
        self.sequence = 0
        self.bridge = None
        self.last_bridge = -float('inf')
        self.sockets = set()
        self.hybrid = False
        self.feedback = None
        self.feedback_deadline = -float('inf')

    def reset(self):
        self.epoch = secrets.token_hex(16)
        self.state.invalidate()
        self.sequence = 0
        self.feedback = None
        self.feedback_deadline = -float('inf')

    def status(self):
        live = self.bridge is not None and self.clock() - self.last_bridge < .5
        if not live:
            self.state.connected = self.state.ready = False
            self.state.invalidate()
        result = dict(self.state.status(), relay=live, epoch=self.epoch)
        if self.hybrid:
            if live and self.state.ready and self.feedback and self.clock() < self.feedback_deadline:
                result.update(self.feedback)
                result['active'] = result['count'] > 0
            else:
                # Never label the phone-only mean as the combined aircraft command.
                result.update(mode='hybrid', count=0, active=False, inputs=[],
                              sources=dict(phone=0, camera=0), feedback_pending=True,
                              collective=dict(roll=0, pitch=0, rudder=0, brake=0, throttle=None))
        return result

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
        ws = web.WebSocketResponse(heartbeat=10, max_msg_size=65536 if role == 'bridge' else 4096)
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
        response = self.state.exchange({k: data[k] for k in ('challenge', 'controls', 'release_brakes')} | {'session': session})
        return response | self.status()

    def poll(self, data):
        if set(data) - {'feedback'} != {'generation', 'ready', 'throttle', 'nonce'}:
            raise ValueError('Invalid telemetry')
        if not generation_valid(data['generation']) or type(data['ready']) is not bool:
            raise ValueError('Invalid simulator generation/readiness')
        if data['throttle'] is None:
            raise ValueError('Simulator throttle must be numeric')
        bounded_controls(dict(roll=0, pitch=0, rudder=0, brake=0, throttle=data['throttle']))
        if not isinstance(data['nonce'], str) or len(data['nonce']) != 32:
            raise ValueError('Invalid nonce')
        feedback = data.get('feedback')
        if 'feedback' in data:
            validate_feedback(feedback)
        self.hybrid = 'feedback' in data
        ready = data['ready']
        if data['generation'] != self.generation or ready != self.state.ready or self.clock() - self.last_bridge >= .5:
            self.reset()
        self.generation = data['generation']
        self.state.generation = self.generation
        self.state.ready = ready
        self.state.connected = True
        self.state.throttle = data['throttle']
        # Feedback refers to the previous phone aggregate, never feeds into votes.
        # Subtract the whole poll interval as a conservative transit-age bound.
        if (feedback and ready and feedback['epoch'] == self.epoch
                and feedback['sequence'] == self.sequence):
            remaining = feedback['valid_for'] - (self.clock() - self.last_bridge)
            self.feedback = {k: v for k, v in feedback.items()
                             if k not in ('epoch', 'sequence', 'valid_for')}
            self.feedback_deadline = self.clock() + max(0, remaining)
        elif not self.hybrid:
            self.feedback = None
        self.last_bridge = self.clock()
        self.sequence += 1
        status = self.state.status()
        return dict(kind='aggregate', epoch=self.epoch, generation=self.generation,
                    sequence=self.sequence, nonce=data['nonce'], active=status['active'],
                    controls=status['collective'], brake_release=self.state.brake_release,
                    count=status['count'], inputs=status['inputs'],
                    **({'hybrid': True} if self.hybrid else {}))

    async def operator_sessions(self, request):
        token = request.headers.get('Authorization', '').removeprefix('Bearer ')
        if not request.headers.get('Authorization', '').startswith('Bearer ') or not self.operator_token or not hmac.compare_digest(token.encode(), self.operator_token.encode()):
            raise web.HTTPUnauthorized(headers={'Cache-Control': 'no-store'})
        if request.match_info.get('id') not in (None, 'current'):
            raise web.HTTPNotFound()
        state = self.status()
        resource = {'id': 'current', 'title': 'Flight',
                    'participantUrl': self.origin + '/?key=' + self.keys[0],
                    'status': 'aircraft-ready' if state['ready'] else
                              'simulator-loading' if state['relay'] else 'simulator-disconnected'}
        return web.json_response(resource if request.match_info.get('id') else [resource],
                                 headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'})

    async def page(self, request):
        if request.path in ('/operator', '/operator.js'):
            file = 'operator.html' if request.path == '/operator' else 'operator.js'
            return web.Response(text=(HERE / 'phone' / file).read_text(),
                                content_type='text/html' if file.endswith('.html') else 'text/javascript',
                                headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
                                         'X-Content-Type-Options': 'nosniff'})
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
        app.router.add_get('/api/operator/sessions', self.operator_sessions)
        app.router.add_get('/api/operator/sessions/{id}', self.operator_sessions)
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
        relay = Relay(participant, bridge, origin, operator_token=os.environ.get('FLIGHT_OPERATOR_TOKEN'))
    except ValueError as error:
        raise SystemExit(f'Flight configuration error: {error}') from None
    web.run_app(relay.app(), host='0.0.0.0', port=port, access_log=None)


if __name__ == '__main__':
    main()
