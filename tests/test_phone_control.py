import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET

from scripts import flightgear, phone_control as phone


def config():
    return phone.validate(flightgear.read(flightgear.ROOT / 'config/inputs/phone-landing.toml'))


class InputTests(unittest.TestCase):
    def setUp(self):
        self.now = 100
        self.state = phone.State(config(), lambda: self.now)
        self.state.ready = self.state.connected = True
        self.session = 'a' * 32

    def send(self, controls=None, challenge=None, session=None):
        return self.state.exchange(dict(session=session or self.session, challenge=challenge, controls=controls))

    def controls(self, **changes):
        return dict(dict(roll=.5, pitch=-.2, rudder=0, brake=0, throttle=None), **changes)

    def activate(self, **changes):
        first = self.send()
        return self.send(self.controls(**changes), first['challenge'])

    def test_profile_selects_valid_mapping(self):
        resolved = flightgear.resolve('karlsruhe-747-landing')
        self.assertEqual(resolved['input_config']['layout'], 'landing')
        self.assertLess(resolved['input_config']['controls']['pitch']['scale'], 0)
        self.assertIsNone(flightgear.resolve('amsterdam-explore')['input_config'])
        self.assertFalse(any('--telnet' in arg for arg in resolved['command']))

    def test_requires_handshake_and_expires_without_pausing(self):
        self.send(self.controls())
        self.assertFalse(self.state.fresh())
        self.activate()
        self.assertTrue(self.state.fresh())
        self.now += 1.1
        self.assertFalse(self.state.fresh())

    def test_delayed_or_replayed_frames_are_rejected(self):
        challenge = self.send()['challenge']
        self.now += .6
        self.assertTrue(self.send(self.controls(), challenge)['resync'])
        self.assertFalse(self.state.fresh())
        challenge = self.send()['challenge']
        self.send(self.controls(), challenge)
        revision = self.state.revision
        self.assertTrue(self.send(self.controls(roll=-1), challenge)['resync'])
        self.assertEqual(self.state.revision, revision)
        self.assertEqual(self.state.values['roll'], .5)

    def test_equal_votes_neutral_input_and_independent_challenges(self):
        a = self.activate(roll=1, throttle=.8)
        b = self.send(session='b'*32)
        b = self.send(self.controls(roll=-1, throttle=.2, brake=1), b['challenge'], 'b'*32)
        for _ in range(5):
            a = self.send(self.controls(roll=1), a['challenge'])
        self.assertEqual(self.state.values['roll'], 0)
        self.assertEqual(self.state.values['throttle'], .5)
        self.assertEqual(self.state.values['brake'], .5)
        self.assertEqual(a['count'], 2)
        b = self.send(self.controls(roll=0), b['challenge'], 'b'*32)
        self.assertEqual(self.state.values['roll'], .5)
        self.assertEqual(b['personal_throttle'], .2)

    def test_expiry_removes_only_inactive_phone_and_rejoin_reseeds_throttle(self):
        a = self.activate(roll=1, throttle=.8)
        b = self.send(session='b'*32)
        b = self.send(self.controls(roll=-1, throttle=.2), b['challenge'], 'b'*32)
        for _ in range(3):
            self.now += .4
            a = self.send(self.controls(roll=1), a['challenge'])
        self.assertEqual(self.state.values['roll'], 1)
        self.assertEqual(a['count'], 1)
        self.assertNotIn('b'*32, self.state.sessions)
        b = self.send(self.controls(roll=-1, throttle=.2), b['challenge'], 'b'*32)
        self.assertTrue(b['resync'])
        self.assertEqual(b['personal_throttle'], .8)

    def test_release_brakes_preserves_other_participants_vote(self):
        self.activate(brake=1)
        b = self.send(session='b'*32)
        self.state.exchange(dict(session='b'*32, challenge=b['challenge'],
                                 controls=self.controls(brake=1), release_brakes=True))
        self.assertEqual(self.state.values['brake'], .5)

    def test_new_participant_uses_group_throttle_and_readback_does_not_change_votes(self):
        self.state.throttle = .4
        a = self.activate()
        self.assertEqual(a['personal_throttle'], .4)
        self.send(self.controls(throttle=.8), a['challenge'])
        self.state.throttle = .5
        b = self.send(session='b'*32)
        self.assertEqual(b['personal_throttle'], .8)
        self.assertEqual(self.state.values['throttle'], .8)

    def test_reset_invalidates_old_challenge_and_throttle(self):
        response = self.activate(throttle=.8)
        self.state.invalidate()
        result = self.send(self.controls(throttle=.8), response['challenge'])
        self.assertTrue(result['resync'])
        self.assertFalse(self.state.fresh())
        self.assertIsNone(self.state.values['throttle'])

    def test_throttle_event_survives_until_adapter_consumes_it(self):
        response = self.activate(throttle=.7)
        self.send(self.controls(), response['challenge'])
        self.assertEqual(self.state.values['throttle'], .7)

    def test_reset_invalidates_every_participant(self):
        a = self.activate(throttle=.8)
        b = self.send(session='b'*32)
        b = self.send(self.controls(throttle=.2), b['challenge'], 'b'*32)
        self.state.invalidate()
        self.state.throttle = .45
        for session, response in ((self.session, a), ('b'*32, b)):
            result = self.send(self.controls(throttle=1), response['challenge'], session)
            self.assertTrue(result['resync'])
            self.assertEqual(result['personal_throttle'], .45)
        self.assertFalse(self.state.fresh())

    def test_abandoned_handshake_and_pending_release_expire(self):
        a = self.send()
        self.state.exchange(dict(session=self.session, challenge=a['challenge'],
                                 controls=self.controls(), release_brakes=True))
        self.send(session='b'*32)
        self.now += 1.1
        self.assertEqual(self.state.status()['count'], 0)
        self.assertEqual(self.state.sessions, {})
        self.assertEqual(self.state.brake_release, 0)

    def test_invalid_frames_cannot_change_controls(self):
        for invalid in (self.controls(roll=float('nan')), self.controls(brake=2),
                        self.controls(throttle=True), {'roll': 0}):
            challenge = self.send()['challenge']
            with self.assertRaises(ValueError):
                self.send(invalid, challenge)
            self.assertFalse(self.state.fresh())

    def test_invalid_mappings_rejected(self):
        for field, value in [('layout', 'unknown'), ('expiry_s', float('nan')), ('port', True)]:
            c = config()
            c[field] = value
            with self.assertRaises(ValueError):
                phone.validate(c)
        c = config()
        c['controls']['roll']['paths'] = ['/sim/freeze/master']
        with self.assertRaises(ValueError):
            phone.validate(c)

    def test_watchdog_is_independent_and_does_not_pause_or_change_trim(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'watchdog.xml'
            phone.watchdog_xml(config(), path)
            script = ET.parse(path).findtext('./nasal/committee_phone/script')
        self.assertIn("setlistener('/sim/signals/frame', tick)", script)
        self.assertIn('systime() - received', script)
        self.assertIn("frame-generation", script)
        self.assertIn("'connected', 0", script)
        self.assertNotIn('/sim/freeze', script)
        self.assertNotIn('elevator-trim', script)


class HTTPTests(unittest.TestCase):
    def test_real_http_join_status_input_and_access_control(self):
        state = phone.State(config())
        state.connected = state.ready = True
        try:
            server = phone.make_server(state, 'test-key', 0)
        except PermissionError:
            self.skipTest('Environment forbids listening sockets')
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=2)
        try:
            def request(method, path, data=None, headers=None):
                connection.request(method, path, body=json.dumps(data) if data else None, headers=headers or {})
                response = connection.getresponse()
                return response.status, response.read()
            self.assertEqual(request('GET', '/')[0], 403)
            code, body = request('GET', '/?key=test-key')
            self.assertEqual(code, 200)
            self.assertIn(b'Hold to brake', body)
            self.assertNotIn(b'id="reset"', body)
            status = json.loads(request('GET', '/status?key=test-key')[1])
            self.assertTrue(status['simulator'])
            self.assertEqual(state.sessions, {})
            message = dict(session='a'*32, challenge=None, controls=None)
            challenge = json.loads(request('POST', '/input?key=test-key', message)[1])['challenge']
            message.update(challenge=challenge, controls=dict(roll=1,pitch=0,rudder=0,brake=1,throttle=.5))
            self.assertEqual(request('POST', '/input?key=test-key', message)[0], 200)
            self.assertTrue(state.fresh())
            self.assertEqual(request('POST', '/input?key=test-key', message, {'Origin': 'http://elsewhere'})[0], 403)
            self.assertEqual(request('POST', '/reset?key=test-key', message)[0], 403)
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join()


class InMemoryHTTPTests(unittest.TestCase):
    def test_handler_routes_without_listening_socket(self):
        import io
        state = phone.State(config())
        state.ready = state.connected = True
        state.join_url = 'http://192.168.8.212:8080/?key=secret'
        state.qr_svg = b'<svg/>'
        handler = phone.handler_for(state, 'secret')

        class Connection:
            def __init__(self, request):
                self.input = io.BytesIO(request)
                self.output = bytearray()
            def makefile(self, *args):
                return self.input
            def sendall(self, data):
                self.output.extend(data)
            def settimeout(self, value):
                pass

        def request(method, path, payload=None):
            body = json.dumps(payload).encode() if payload else b''
            raw = (f'{method} {path} HTTP/1.0\r\nHost: localhost\r\nContent-Length: {len(body)}\r\n\r\n').encode() + body
            conn = Connection(raw)
            handler(conn, ('127.0.0.1', 1), None)
            headers, body = bytes(conn.output).split(b'\r\n\r\n', 1)
            return headers.split(b' ')[1], body

        self.assertEqual(request('GET', '/')[0], b'403')
        self.assertIn(b'Hold to brake', request('GET', '/?key=secret')[1])
        self.assertTrue(json.loads(request('GET', '/status?key=secret')[1])['ready'])
        self.assertEqual(state.sessions, {})
        self.assertEqual(request('GET', '/qr.svg')[0], b'403')
        self.assertEqual(request('GET', '/qr.svg?key=secret')[1], b'<svg/>')
        self.assertEqual(json.loads(request('GET', '/join?key=secret')[1])['url'], state.join_url)
        payload = dict(session='a'*32, controls=None, challenge=None)
        first = json.loads(request('POST', '/input?key=secret', payload)[1])
        payload.update(challenge=first['challenge'], controls=dict(roll=.2,pitch=-.1,rudder=0,brake=1,throttle=.7))
        self.assertTrue(json.loads(request('POST', '/input?key=secret', payload)[1])['active'])
        self.assertEqual(request('POST', '/reset?key=secret', payload)[0], b'403')
        payload['controls']['roll'] = 2
        payload['challenge'] = state.sessions['a'*32]['challenge']
        self.assertEqual(request('POST', '/input?key=secret', payload)[0], b'400')


class BridgeTests(unittest.TestCase):
    def test_adapter_maps_frames_confirms_throttle_and_releases_expired_input(self):
        from unittest.mock import Mock
        clock = [100.0]
        state = phone.State(config(), lambda: clock[0])
        state.ready = state.connected = True
        state.generation = 1
        commands = []
        actual_throttle = [0.45]

        class FakeClient:
            sock = Mock()
            def __init__(self, *args, **kwargs):
                pass
            def get(self, path):
                if path == phone.PREFIX + 'generation':
                    return 1
                if path == state.config['ready_property']:
                    return 1
                return actual_throttle[0]
            def command(self, command):
                commands.append(command)
            def close(self):
                pass

        first = state.exchange(dict(session='a'*32))
        state.exchange(dict(session='a'*32, challenge=first['challenge'],
                            controls=dict(roll=.4,pitch=.3,rudder=-.2,brake=1,throttle=.8)))
        class Stop:
            count = 0
            def is_set(self):
                return self.count >= 3
            def wait(self, delay):
                self.count += 1
                if self.count == 1:
                    # Readback acknowledges throttle on next bridge iteration.
                    actual_throttle[0] = .8
                if self.count == 2:
                    clock[0] += 2
        with patch('scripts.flightgear_test.Client', FakeClient):
            phone.bridge(state, 9999, Stop())
        self.assertIn('set ' + phone.PREFIX + 'roll 0.4', commands)
        self.assertIn('set ' + phone.PREFIX + 'throttle 0.8', commands)
        self.assertEqual(commands.count('set ' + phone.PREFIX + 'throttle 0.8'), 2)
        self.assertIn('set ' + phone.PREFIX + 'alive 0', commands)
        self.assertEqual(state.throttle, .8)
        self.assertFalse(state.fresh())
        self.assertFalse(any('/sim/freeze' in c or 'trim' in c for c in commands))

    def test_reset_generation_rejects_pending_frame(self):
        from unittest.mock import Mock
        state = phone.State(config())
        state.ready = state.connected = True
        state.generation = 1
        first = state.exchange(dict(session='a'*32))
        state.exchange(dict(session='a'*32, challenge=first['challenge'],
                            controls=dict(roll=1,pitch=1,rudder=1,brake=1,throttle=1)))
        client = Mock()
        client.get.side_effect = [2, 1, .45]
        stop = Mock()
        stop.is_set.side_effect = [False, True]
        with patch('scripts.flightgear_test.Client', return_value=client):
            phone.bridge(state, 9999, stop)
        commands = [call.args[0] for call in client.command.call_args_list]
        self.assertIn('set ' + phone.PREFIX + 'frame-generation 2', commands)
        self.assertIn('set ' + phone.PREFIX + 'alive 0', commands)
        self.assertFalse(any('roll 1' in c or 'throttle 1' in c for c in commands))
        self.assertEqual(state.sessions, {})


class JoinTests(unittest.TestCase):
    def test_active_lan_is_preferred_over_loopback_and_vpn(self):
        interfaces = '''lo0: flags=8049<UP,LOOPBACK,RUNNING> mtu 16384
    inet 127.0.0.1 netmask 0xff000000
en0: flags=8863<UP,BROADCAST,RUNNING> mtu 1500
    inet 192.168.8.212 netmask 0xffffff00
    status: active
utun4: flags=8051<UP,POINTOPOINT,RUNNING> mtu 1420
    inet 10.5.0.2 --> 10.5.0.2 netmask 0xffff0000
en1: flags=8863<UP,BROADCAST,RUNNING> mtu 1500
    inet 192.168.9.1 netmask 0xffffff00
    status: inactive
'''
        self.assertEqual(phone.lan_addresses(interfaces), ['192.168.8.212'])
        with patch.object(phone.shutil, 'which', return_value='/sbin/ifconfig'), \
                patch.object(phone.subprocess, 'run') as run:
            run.return_value.stdout = interfaces
            self.assertEqual(phone.discover_addresses(), ['192.168.8.212'])

    def test_qr_receives_exact_join_url_via_stdin(self):
        url = 'http://192.168.8.212:8080/?key=example-secret'
        with patch.object(phone.shutil, 'which', return_value='/bin/qrencode'), \
                patch.object(phone.subprocess, 'run') as run:
            run.return_value.stdout = b'<svg/>'
            self.assertEqual(phone.qr_code(url), b'<svg/>')
            self.assertEqual(run.call_args.kwargs['input'], url.encode())
            self.assertEqual(run.call_args.args[0], ['/bin/qrencode', '-t', 'SVG', '-m', '4', '-o', '-'])

    def test_missing_qr_dependency_keeps_url_join_available(self):
        with patch.object(phone.shutil, 'which', return_value=None):
            self.assertIsNone(phone.qr_code('http://example.test'))


class BrakeReleaseTests(unittest.TestCase):
    def test_release_survives_frames_but_not_reset_or_replayed_request(self):
        state = phone.State(config())
        state.ready = True
        first = state.exchange(dict(session='a'*32))
        request = dict(session='a'*32, challenge=first['challenge'], release_brakes=True,
                       controls=dict(roll=0,pitch=0,rudder=0,brake=1,throttle=None))
        result = state.exchange(request)
        self.assertEqual(state.brake_release, 1)
        self.assertEqual(state.values['brake'], 0)
        state.exchange(dict(session='a'*32, challenge=result['challenge'],
                            controls=dict(roll=0,pitch=0,rudder=0,brake=0,throttle=None)))
        self.assertEqual(state.brake_release, 1)
        state.exchange(request)
        self.assertEqual(state.release_counter, 1)
        state.invalidate()
        self.assertEqual(state.brake_release, 0)

    def test_watchdog_has_explicit_parking_and_autobrake_release(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'watchdog.xml'
            phone.watchdog_xml(config(), path)
            script = ET.parse(path).findtext('./nasal/committee_phone/script')
        self.assertIn('/controls/gear/brake-parking', script)
        self.assertIn('/autopilot/autobrake/step', script)
        self.assertIn("brake-release-ack", script)
        self.assertIn('setprop(path, 0)', script)
        self.assertLess(script.index('var release_id'), script.index('value * mapping[axis].scale'))
        self.assertNotIn('RELEASE_PATHS', script)

    def test_release_is_cleared_only_after_simulator_acknowledgement(self):
        from unittest.mock import Mock
        state = phone.State(config())
        state.ready = state.connected = True
        state.generation = 1
        first = state.exchange(dict(session='a'*32))
        state.exchange(dict(session='a'*32, challenge=first['challenge'], release_brakes=True,
                            controls=dict(roll=0,pitch=0,rudder=0,brake=0,throttle=None)))
        client = Mock()
        def get(path):
            if path == phone.PREFIX + 'brake-release-ack':
                return stop.count
            return .45 if path.endswith('/throttle') else 1
        client.get.side_effect = get
        class Stop:
            count = 0
            def is_set(self):
                return self.count >= 2
            def wait(self, _):
                self.count += 1
        stop = Stop()
        with patch('scripts.flightgear_test.Client', return_value=client):
            phone.bridge(state, 9999, stop)
        commands = [call.args[0] for call in client.command.call_args_list]
        self.assertIn('set ' + phone.PREFIX + 'brake-release 1', commands)
        self.assertIn('set ' + phone.PREFIX + 'brake-release 0', commands)
        self.assertEqual(state.brake_release, 0)
