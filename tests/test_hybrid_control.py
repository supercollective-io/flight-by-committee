"""Hybrid weighting, independent recovery, launch and real transport boundaries."""
import asyncio
import io
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

from aiohttp.test_utils import TestClient, TestServer
from scripts import body_control, flightgear, hybrid_control, phone_control, relay_bridge
from scripts.relay import Relay
from scripts.hybrid_feedback import validate_feedback

VALUES = dict(roll=-1, pitch=-1, rudder=.5, brake=.3, throttle=.7)
BRIDGE = 'b' * 32
PARTICIPANT = 'p' * 32
ORIGIN = 'https://flight.example.test'


class HybridTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.
        self.config = flightgear.resolve('karlsruhe-747-hybrid')['input_config']
        self.state = hybrid_control.HybridState(self.config, lambda: self.now)
        self.state.connected = self.state.ready = True
        self.state.generation = 1
        self.state.throttle = .45
        self.state.sync()
        self.now += .1

    def phone(self, session, values=None):
        handshake = self.state.exchange(dict(session=session))
        return self.state.exchange(dict(session=session, challenge=handshake['challenge'],
                                        controls=values or VALUES))

    def camera(self, votes):
        self.state.sync()
        self.state.camera.available = True
        return self.state.camera.accept(dict(kind='frame', captured=self.now, inputs=votes))

    def test_people_weighting_and_auxiliary_axes(self):
        self.phone('a'*32)
        self.phone('b'*32)
        self.camera([dict(roll=1, pitch=1)] * 8)
        result = self.state.status()
        self.assertAlmostEqual(result['collective']['roll'], .6)
        self.assertEqual(result['sources'], dict(phone=2, camera=8))
        self.assertEqual(result['count'], 10)
        for axis in ('rudder', 'brake', 'throttle'):
            self.assertEqual(result['collective'][axis], VALUES[axis])
            self.assertEqual(result['axis_counts'][axis], 2)
        self.state.camera.invalidate()
        self.assertEqual(self.state.values['roll'], -1)
        self.now += .1
        self.camera([dict(roll=1, pitch=1)] * 8)
        self.state.sessions.clear()
        self.assertEqual(self.state.values['roll'], 1)
        self.assertIsNone(self.state.values['throttle'])
        self.now += .1
        self.camera([])
        self.assertFalse(self.state.fresh())
        self.assertEqual(self.state.values['roll'], 0)

    def test_missing_axis_centred_votes_and_observer(self):
        self.state.exchange(dict(session='observer'*4))
        self.phone('a'*32)
        self.phone('b'*32, VALUES | dict(roll=0, pitch=0))
        self.camera([dict(roll=1, pitch=None)] * 8)
        status = self.state.status()
        self.assertEqual(status['axis_counts']['pitch'], 2)
        self.assertEqual(status['collective']['pitch'], -.5)
        self.assertAlmostEqual(status['collective']['roll'], .7)
        self.assertEqual(status['count'], 10)

    def test_independent_expiry_and_camera_eof(self):
        self.phone('a'*32)
        self.camera([dict(roll=1, pitch=1)])
        self.now += .51
        self.assertEqual(self.state.values['roll'], -1)
        self.camera([dict(roll=1, pitch=1)])
        self.now += .49
        self.assertEqual(self.state.values['roll'], 1)
        started, finished = threading.Event(), threading.Event()
        self.phone('b'*32)
        with redirect_stderr(io.StringIO()):
            body_control.read_camera(io.StringIO(''), self.state.camera, started, finished)
        self.assertEqual(self.state.values['roll'], -1)
        self.assertFalse(self.state.status()['camera_available'])
        self.assertEqual(self.state.status()['sources']['phone'], 1)

    def test_reset_discards_both_sources_and_old_challenges(self):
        result = self.phone('a'*32)
        captured = self.now
        self.camera([dict(roll=1, pitch=1)])
        self.now += .1
        self.state.invalidate()
        self.state.ready = False
        self.state.sync()
        self.assertFalse(self.state.fresh())
        self.state.ready = True
        self.state.sync()
        self.assertFalse(self.state.camera.accept(dict(kind='frame', captured=captured,
                                                      inputs=[dict(roll=1, pitch=1)])))
        result = self.state.exchange(dict(session='a'*32, challenge=result['challenge'], controls=VALUES))
        self.assertTrue(result['resync'])
        self.assertEqual(result['count'], 0)
        self.now += .1
        self.camera([dict(roll=1, pitch=1)])
        self.assertTrue(self.state.fresh())

    def test_phone_exchange_returns_combined_command_and_personal_throttle(self):
        self.camera([dict(roll=1, pitch=1)] * 8)
        reply = self.phone('a'*32)
        self.assertEqual(reply['personal_throttle'], .7)
        self.assertAlmostEqual(reply['collective']['roll'], 7/9)
        self.assertEqual(reply['sources'], dict(phone=1, camera=8))

    def test_watchdog_and_mode_overrides(self):
        self.assertEqual(self.config['mode'], 'hybrid')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'watchdog.xml'
            phone_control.watchdog_xml(self.config, path)
            xml = path.read_text()
        self.assertIn('if (1 and throttle != nil', xml)
        self.assertIn('["roll", "pitch", "rudder", "brake"]', xml)
        body = flightgear.resolve('karlsruhe-747-hybrid', overrides={'input_mode': 'body'})['input_config']
        self.assertFalse(body['throttle_enabled'])
        phone = flightgear.resolve('karlsruhe-747-hybrid', overrides={'input_mode': 'phone'})['input_config']
        self.assertNotIn('body', phone)
        self.assertEqual(phone['mode'], 'phone')

    def test_camera_expiry_during_property_staging_does_not_commit_old_mix(self):
        self.phone('a'*32)
        self.camera([dict(roll=1, pitch=1)] * 8)
        stop = threading.Event()
        client = Mock()
        client.get.side_effect = lambda path: .45 if path.endswith('/throttle') else 1
        def command(text):
            self.now += .1
            if text.startswith('set ' + phone_control.PREFIX + 'sequence '):
                stop.set()
        client.command.side_effect = command
        with patch('scripts.flightgear_test.Client', return_value=client):
            phone_control.bridge(self.state, 0, stop)
        commands = [call.args[0] for call in client.command.call_args_list]
        self.assertIn('set ' + phone_control.PREFIX + 'alive 0', commands)
        self.assertNotIn('set ' + phone_control.PREFIX + 'alive 1', commands)

    def test_local_runtime_has_one_writer_and_phone_survives_camera_exit(self):
        worker = "import json,time; print(json.dumps({'kind':'ready'}),flush=True); time.sleep(30)"
        popen = subprocess.Popen
        processes = []
        def launch(command, **kwargs):
            process = popen([sys.executable, '-c', worker], **kwargs)
            processes.append(process)
            return process
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / 'pose.task'
            model.touch()
            config = self.config | {'port': 0, 'body': self.config['body'] | {'model': str(model)}}
            with patch.dict('os.environ', {'FLIGHT_RELAY_URL': ''}), \
                    patch.object(body_control.subprocess, 'Popen', side_effect=launch), \
                    patch.object(phone_control, 'bridge') as writer, \
                    patch.object(phone_control, 'discover_addresses', return_value=[]), patch('builtins.print'):
                with hybrid_control.running(config, 0) as state:
                    state.connected = state.ready = True
                    url = urlsplit(state.projection_url)
                    connection = HTTPConnection(url.hostname, url.port, timeout=2)
                    def request(path, data):
                        connection.request('POST', path + '?' + url.query, json.dumps(data))
                        response = connection.getresponse()
                        self.assertEqual(response.status, 200)
                        return json.loads(response.read())
                    handshake = request('/input', dict(session='s'*32))
                    reply = request('/input', dict(session='s'*32, challenge=handshake['challenge'], controls=VALUES))
                    self.assertEqual(reply['sources']['phone'], 1)
                    processes[0].terminate()
                    processes[0].wait(timeout=2)
                    deadline = time.monotonic() + 2
                    while state.camera.available and time.monotonic() < deadline:
                        time.sleep(.01)
                    with state.lock:
                        self.assertEqual(state.values['roll'], -1)
                    request('/leave', dict(session='s'*32))
                    self.assertFalse(state.fresh())
                    connection.close()
                    writer.assert_called_once()
                self.assertIsNotNone(processes[0].poll())


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.
        self.relay = Relay(PARTICIPANT, BRIDGE, ORIGIN, clock=lambda: self.now)
        self.relay.bridge = object()
        self.state = hybrid_control.HybridState({'expiry_s': 1.}, lambda: self.now, hosted=True)
        self.state.ready = self.state.connected = True
        self.state.generation = 1
        self.state.throttle = .45
        self.state.sync()
        self.now += .01
        self.state.camera.available = True
        self.state.camera.accept(dict(kind='frame', captured=self.now, inputs=[dict(roll=1, pitch=None)] * 8))

    def poll(self, feedback=None, generation=1):
        return self.relay.poll(dict(generation=generation, ready=True, throttle=.45,
                                   nonce='n'*32, feedback=feedback or self.state.feedback()))

    def test_feedback_is_display_only_and_expires_without_phone_only_fallback(self):
        frame = self.poll()
        self.state.phone.accept(frame, 'n'*32, self.now)
        self.now += .1
        frame = self.poll()
        self.assertEqual(frame['count'], 0)
        self.assertEqual(frame['controls']['roll'], 0)
        self.assertEqual(self.relay.status()['count'], 8)
        self.assertEqual(self.relay.status()['collective']['roll'], 1)
        self.now += .31
        self.assertTrue(self.relay.status()['feedback_pending'])
        self.assertFalse(self.relay.status()['active'])

    def test_old_epoch_cannot_restore_feedback_after_reset(self):
        frame = self.poll()
        self.state.phone.accept(frame, 'n'*32, self.now)
        self.now += .1
        old = self.state.feedback()
        self.poll(old)
        self.poll(old, generation=2)
        self.assertTrue(self.relay.status()['feedback_pending'])
        self.assertEqual(self.relay.status()['count'], 0)

    def test_malformed_feedback_is_rejected(self):
        good = self.state.feedback()
        for invalid in (good | {'valid_for': float('nan')}, good | {'valid_for': 10},
                        good | {'count': True}, good | {'sequence': -1},
                        good | {'sources': {'phone': 0, 'camera': 9}},
                        good | {'collective': VALUES | {'roll': 2}},
                        good | {'camera_available': 1}, good | {'command': 'reset'}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_feedback(invalid)

    def test_expired_phone_brake_release_cannot_be_applied_by_active_camera(self):
        frame = dict(kind='aggregate', epoch='e'*32, generation=1, sequence=1,
                     nonce='n'*32, active=True, controls=VALUES, brake_release=1,
                     count=1, inputs=[dict(roll=-1, pitch=-1)])
        self.state.phone.accept(frame, 'n'*32, self.now)
        self.assertEqual(self.state.brake_release, 1)
        self.now += .51
        self.state.camera.accept(dict(kind='frame', captured=self.now, inputs=[dict(roll=1, pitch=1)]))
        self.assertTrue(self.state.fresh())
        self.assertEqual(self.state.brake_release, 0)
        self.assertEqual(self.state.values['brake'], 0)

    def test_hosted_hybrid_local_server_stays_read_only(self):
        config = flightgear.resolve('karlsruhe-747-hybrid')['input_config'] | {'port': 0}
        state = hybrid_control.HybridState(config, hosted=True)
        async def unused(*args):
            pass
        with patch.dict('os.environ', {'FLIGHT_RELAY_URL': ORIGIN, 'FLIGHT_BRIDGE_KEY': BRIDGE}), \
                patch.object(phone_control, 'bridge') as writer, \
                patch.object(relay_bridge, 'connect', side_effect=unused), patch('builtins.print'):
            with relay_bridge.running(config, 0, state=state):
                url = urlsplit(state.projection_url)
                connection = HTTPConnection(url.hostname, url.port, timeout=2)
                for path in ('/input', '/leave'):
                    connection.request('POST', path+'?'+url.query, '{}')
                    response = connection.getresponse()
                    response.read()
                    self.assertEqual(response.status, 403)
                connection.close()
                writer.assert_called_once()


class HostedHybridTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_relay_combines_locally_and_returns_final_display(self):
        relay = Relay(PARTICIPANT, BRIDGE, ORIGIN)
        async with TestClient(TestServer(relay.app())) as client:
            state = hybrid_control.HybridState({'expiry_s': 1.}, hosted=True)
            state.ready = state.connected = True
            state.generation = 1
            state.throttle = .45
            state.sync()
            state.camera.available = True
            stop = threading.Event()
            task = asyncio.create_task(relay_bridge.connection_loop(
                state.phone, str(client.server.make_url('/ws/bridge')), BRIDGE, stop, state.feedback))
            async def wait_for(predicate):
                for _ in range(80):
                    state.camera.accept(dict(kind='frame', captured=time.monotonic(),
                                             inputs=[dict(roll=1, pitch=None)] * 8))
                    if predicate():
                        return
                    await asyncio.sleep(.025)
                self.fail('Hybrid transport did not reach expected state')
            try:
                await wait_for(lambda: relay.state.ready)
                ws = await client.ws_connect('/ws/participant?key='+PARTICIPANT, headers={'Origin': ORIGIN})
                async def send(previous=None):
                    await ws.send_json(dict(kind='input', epoch=(previous or {}).get('epoch'),
                                            challenge=(previous or {}).get('challenge'),
                                            controls=VALUES if previous else None, release_brakes=False))
                    return await ws.receive_json()
                reply = await send()
                reply = await send(reply)
                await wait_for(lambda: state.phone.fresh() and relay.status().get('count') == 9)
                validate_feedback(state.feedback())
                local, remote = state.status(), relay.status()
                self.assertAlmostEqual(local['collective']['roll'], 7/9)
                self.assertAlmostEqual(remote['collective']['roll'], 7/9)
                self.assertEqual(remote['collective']['pitch'], -1)
                self.assertEqual(relay.state.values['roll'], -1)  # Feedback never re-enters voting.
                reply = await send(reply)
                self.assertEqual(reply['sources'], dict(camera=8, phone=1))
                self.assertAlmostEqual(reply['collective']['roll'], 7/9)
                self.assertEqual(reply['personal_throttle'], .7)
                await ws.close()
                await wait_for(lambda: not state.phone.fresh())
                self.assertEqual(state.values['roll'], 1)
                await relay.bridge.close()
                await asyncio.sleep(.05)
                self.assertEqual(state.values['roll'], 1)  # Relay loss leaves camera intact.
                state.invalidate()
                state.generation = 2
                state.sync()
                self.assertFalse(state.fresh())
            finally:
                stop.set()
                await asyncio.wait_for(task, 3)


if __name__ == '__main__':
    unittest.main()
