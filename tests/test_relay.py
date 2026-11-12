import asyncio
import json
import time
import threading
import unittest

import aiohttp
from aiohttp.test_utils import TestClient, TestServer
from scripts.relay import Relay
from scripts.relay_bridge import RemoteState, connection_loop
from scripts.flightgear import read, ROOT

PARTICIPANT = 'p' * 32
BRIDGE = 'b' * 32
ORIGIN = 'https://flight.supercollective.io'
VALUES = dict(roll=.5, pitch=-.5, rudder=0, brake=0, throttle=.45)


class FrameTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.
        self.state = RemoteState({'expiry_s': 1.}, lambda: self.now)
        self.state.ready = self.state.connected = True
        self.state.generation = 1.
        self.frame = dict(kind='aggregate', epoch='e'*32, generation=1, sequence=1,
                          nonce='n'*32, active=True, controls=VALUES.copy(),
                          brake_release=1, count=1, inputs=[dict(roll=.5, pitch=-.5)])

    def accept(self, frame=None, sent=100.):
        self.state.accept(frame or self.frame, 'n'*32, sent)

    def test_fixed_schema_ranges_and_stale_rejection(self):
        for field, value in [('nonce', 'old'), ('generation', 0), ('sequence', -1),
                             ('active', 1), ('count', True), ('inputs', [{}]),
                             ('controls', VALUES | {'path': '/sim/freeze/master'}),
                             ('controls', VALUES | {'roll': float('nan')}),
                             ('controls', VALUES | {'brake': -1})]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.accept(self.frame | {field: value})
        with self.assertRaises(ValueError):
            self.accept(self.frame | {'command': 'reset'})
        with self.assertRaises(ValueError):
            self.accept(sent=99.4)
        self.accept()
        with self.assertRaises(ValueError):
            self.accept()

    def test_bridge_expiry_retains_throttle_and_requires_new_frame(self):
        self.accept()
        self.assertTrue(self.state.fresh())
        self.now += .5
        self.assertFalse(self.state.fresh())
        self.assertEqual(self.state.values, dict(roll=0, pitch=0, rudder=0, brake=0, throttle=None))
        self.assertFalse(self.state.status()['active'])
        self.state.invalidate()
        self.assertIsNone(self.state.frame)

    def test_release_is_not_reasserted_after_ack_or_reused_across_epochs(self):
        self.accept()
        self.assertEqual(self.state.brake_release, 1)
        self.state.brake_release = 0  # local simulator acknowledgement
        self.accept(self.frame | {'sequence': 2})
        self.assertEqual(self.state.brake_release, 0)
        self.accept(self.frame | {'epoch': 'f'*32})
        self.assertEqual(self.state.brake_release, 2)


class RelayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.relay = Relay(PARTICIPANT, BRIDGE, ORIGIN)
        self.server = TestServer(self.relay.app())
        self.client = TestClient(self.server)
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def bridge(self):
        return await self.client.ws_connect('/ws/bridge', headers={'Authorization': 'Bearer ' + BRIDGE})

    async def participant(self, **kwargs):
        return await self.client.ws_connect('/ws/participant?key=' + PARTICIPANT, headers={'Origin': ORIGIN}, **kwargs)

    async def poll(self, ws, generation=1, ready=True):
        await ws.send_json(dict(generation=generation, ready=ready, throttle=.45, nonce='n'*32))
        return await ws.receive_json()

    async def send(self, ws, response=None, controls=VALUES):
        await ws.send_json(dict(kind='input', epoch=(response or {}).get('epoch'), challenge=(response or {}).get('challenge'), controls=controls if response else None, release_brakes=False))
        return await ws.receive_json()

    async def test_authentication_origin_and_credential_separation(self):
        for role, key, headers in [('participant', BRIDGE, {'Origin': ORIGIN}), ('participant', PARTICIPANT, {'Origin': 'https://evil.test'}), ('participant', PARTICIPANT, {}), ('bridge', PARTICIPANT, {'Authorization': 'Bearer ' + PARTICIPANT})]:
            with self.subTest(role=role, headers=headers), self.assertRaises(aiohttp.WSServerHandshakeError) as error:
                await self.client.ws_connect('/ws/' + role + '?key=' + key, headers=headers)
            self.assertEqual(error.exception.status, 403)
        response = await self.client.get('/healthz')
        self.assertEqual(response.status, 200)
        self.assertEqual((await self.client.get('/?key=' + PARTICIPANT)).status, 200)
        self.assertEqual((await self.client.get('/?key=' + BRIDGE)).status, 403)

    async def test_public_homepage_keeps_performance_private(self):
        for path in ('/', '/?utm_source=programme'):
            response = await self.client.get(path)
            self.assertEqual(response.status, 200)
            body = await response.text()
            self.assertIn('https://github.com/supercollective-io/flight-by-committee', body)
            self.assertIn('invitation link', body)
            for private in (PARTICIPANT, BRIDGE, '/relay.js', 'id="controls"'):
                self.assertNotIn(private, body)
        for path in ('/', '/status', '/join', '/projection', '/relay.js'):
            for query in ('?key=', '?key=invalid', '?key=' + BRIDGE):
                self.assertEqual((await self.client.get(path + query)).status, 403)
            if path != '/':
                self.assertEqual((await self.client.get(path)).status, 403)
        invitation = await self.client.get('/?key=' + PARTICIPANT)
        self.assertEqual(invitation.status, 200)
        self.assertIn('id="controls"', await invitation.text())
        self.assertEqual(invitation.headers['Cache-Control'], 'no-store')
        self.assertEqual(invitation.headers['Referrer-Policy'], 'no-referrer')
        self.assertFalse(self.relay.sockets)
        self.assertFalse(self.relay.state.sessions)

    async def test_observer_handshake_and_centred_denominator(self):
        bridge = await self.bridge()
        await self.poll(bridge)
        observer = await self.participant()
        await observer.send_json({'kind': 'status'})
        self.assertEqual((await observer.receive_json())['count'], 0)
        self.assertEqual(len(self.relay.state.sessions), 0)
        a, b = await self.participant(), await self.participant()
        ha, hb = await self.send(a), await self.send(b)
        self.assertEqual(self.relay.state.status()['count'], 0)
        await self.send(a, ha)
        result = await self.send(b, hb, VALUES | {'roll': 0, 'pitch': 0})
        self.assertEqual(result['count'], 2)
        self.assertEqual(result['collective']['roll'], .25)
        await b.send_json({'kind':'status'})
        self.assertEqual((await b.receive_json())['count'], 1)
        await b.close()
        await asyncio.sleep(.01)
        self.assertEqual(self.relay.state.status()['count'], 1)

    async def test_generation_and_bridge_reconnect_never_replay(self):
        bridge = await self.bridge()
        first = await self.poll(bridge)
        phone = await self.participant()
        h = await self.send(phone)
        active = await self.send(phone, h)
        self.assertEqual(active['count'], 1)
        reset = await self.poll(bridge, generation=2)
        self.assertNotEqual(reset['epoch'], first['epoch'])
        self.assertFalse(reset['active'])
        stale = await self.send(phone, active)
        self.assertTrue(stale['resync'])
        self.assertEqual(stale['count'], 0)
        await bridge.close()
        await asyncio.sleep(.01)
        self.assertFalse(self.relay.status()['ready'])
        bridge = await self.bridge()
        reconnect = await self.poll(bridge, generation=2)
        self.assertFalse(reconnect['active'])
        self.assertNotEqual(reconnect['epoch'], reset['epoch'])

    async def test_readiness_change_clears_votes_and_requires_fresh_handshake(self):
        bridge = await self.bridge()
        initial = await self.poll(bridge)
        phone = await self.participant()
        active = await self.send(phone, await self.send(phone))
        self.assertEqual(active['count'], 1)
        not_ready = await self.poll(bridge, ready=False)
        self.assertFalse(not_ready['active'])
        self.assertFalse(self.relay.status()['ready'])
        ready = await self.poll(bridge, ready=True)
        self.assertNotEqual(initial['epoch'], ready['epoch'])
        self.assertFalse(ready['active'])
        stale = await self.send(phone, active)
        self.assertTrue(stale['resync'])
        self.assertEqual(stale['count'], 0)
        handshake = await self.send(phone, stale)
        self.assertEqual(handshake['count'], 1)

    async def test_bridge_telemetry_has_exact_current_schema(self):
        bridge = await self.bridge()
        await bridge.send_json(dict(generation=1, ready=True, override=False,
                                    throttle=.45, nonce='n'*32))
        message = await bridge.receive()
        self.assertEqual(message.type, aiohttp.WSMsgType.CLOSE)
        self.assertEqual(message.data, 1008)

    async def test_rate_limit_and_invalid_frames_close_socket(self):
        for data in [{'kind': 'command', 'path': '/sim/freeze/master'}, []]:
            ws = await self.participant()
            await ws.send_json(data)
            message = await ws.receive()
            self.assertEqual(message.type, aiohttp.WSMsgType.CLOSE)
            self.assertEqual(message.data, 1008)
        ws = await self.participant()
        for _ in range(8):
            await ws.send_json({'kind': 'status'})
        while True:
            message = await ws.receive()
            if message.type == aiohttp.WSMsgType.CLOSE:
                break
        self.assertEqual(message.data, 1008)

    async def test_bridge_independent_expiry_and_recovery_over_real_websocket(self):
        state = RemoteState({'expiry_s': 1.})
        state.ready = state.connected = True
        state.generation = 1.
        state.throttle = .45
        stop = __import__('threading').Event()
        task = asyncio.create_task(connection_loop(state, str(self.server.make_url('/ws/bridge')), BRIDGE, stop))
        try:
            phone = await self.participant()
            for _ in range(15):
                await asyncio.sleep(.1)
                if self.relay.state.ready:
                    break
            result = await self.send(phone)
            result = await self.send(phone, result)
            for _ in range(15):
                await asyncio.sleep(.1)
                if state.fresh():
                    break
            self.assertTrue(state.fresh())
            # A relay restart destroys its connection and old participant input.
            await self.relay.bridge.close()
            await asyncio.sleep(.6)
            self.assertFalse(state.fresh())
            self.assertEqual(state.values['roll'], 0)
            self.assertIsNone(state.values['throttle'])
            for _ in range(15):
                await asyncio.sleep(.1)
                if self.relay.state.ready:
                    break
            self.assertEqual(self.relay.state.status()['count'], 0)
        finally:
            stop.set()
            await asyncio.wait_for(task, 3)

class LocalWriterTests(unittest.TestCase):
    def test_expired_aggregate_is_not_committed_after_slow_property_staging(self):
        from unittest.mock import Mock, patch
        from scripts import phone_control
        now = [100.]
        config = read(ROOT / 'config/inputs/phone-landing.toml')
        state = RemoteState(config, lambda: now[0])
        state.ready = state.connected = True
        state.generation = 1.
        state.throttle = .45
        frame = dict(kind='aggregate', epoch='e'*32, generation=1, sequence=1,
                     nonce='n'*32, active=True, controls=VALUES, brake_release=0,
                     count=1, inputs=[dict(roll=.5,pitch=-.5)])
        state.accept(frame, 'n'*32, 100.)
        stop = threading.Event()
        client = Mock()
        client.get.side_effect = lambda path: .45 if path.endswith('/throttle') else 1.
        def command(text):
            now[0] += .15
            if text.startswith('set ' + phone_control.PREFIX + 'sequence '):
                stop.set()
        client.command.side_effect = command
        with patch('scripts.flightgear_test.Client', return_value=client):
            phone_control.bridge(state, 9999, stop)
        commands = [call.args[0] for call in client.command.call_args_list]
        self.assertIn('set ' + phone_control.PREFIX + 'alive 0', commands)
        self.assertNotIn('set ' + phone_control.PREFIX + 'alive 1', commands)

class ObserverServerTests(unittest.TestCase):
    def test_hosted_local_monitor_rejects_every_write_even_with_its_key(self):
        import http.client
        from urllib.parse import urlsplit
        from unittest.mock import patch
        from scripts import relay_bridge
        config = read(ROOT / 'config/inputs/phone-landing.toml') | {'port': 0}
        async def unused(*args):
            pass
        with patch.dict('os.environ', {'FLIGHT_RELAY_URL': ORIGIN, 'FLIGHT_BRIDGE_KEY': BRIDGE}), \
                patch('scripts.phone_control.bridge'), patch('scripts.relay_bridge.connect', side_effect=unused), \
                patch('builtins.print'):
            with relay_bridge.running(config, 9999) as state:
                url = urlsplit(state.projection_url)
                key = url.query
                connection = http.client.HTTPConnection(url.hostname, url.port)
                origin = f'http://{url.netloc}'
                def post(path, data, headers=None):
                    connection.request('POST', path, json.dumps(data), headers or {})
                    response = connection.getresponse()
                    result = response.status, json.loads(response.read())
                    return result
                for path, data in (('/input', {}), ('/leave', {'session':'s'}),
                                   ('/override', {'enabled':True})):
                    self.assertEqual(post(path + '?' + key, data, {'Origin':origin})[0], 403)
                connection.request('GET', '/status?' + key)
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                status = json.loads(response.read())
                self.assertNotIn('override', status)
                self.assertNotIn('local_operator', status)
                self.assertFalse(hasattr(state, 'override'))
                self.assertFalse(hasattr(state, 'local_operator'))
                connection.close()


if __name__ == '__main__':
    unittest.main()
