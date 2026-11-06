import importlib.util
from pathlib import Path
import socket
import threading
import unittest
from unittest.mock import patch
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location('flightgear_test', Path(__file__).parents[1] / 'scripts/flightgear_test.py')
fg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fg)


class ProtocolTests(unittest.TestCase):
    def client(self, reply):
        client = fg.Client.__new__(fg.Client)
        client.sock, server = socket.socketpair()
        client.sock.settimeout(0.1)
        client.buffer = b''
        self.addCleanup(client.close)
        self.addCleanup(server.close)
        def respond():
            server.recv(4096)
            for fragment in reply:
                server.sendall(fragment)
        thread = threading.Thread(target=respond, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 1)
        return client

    def test_connect_to_server_that_sends_no_greeting(self):
        left, right = socket.socketpair()
        right.settimeout(1)
        received = []
        self.addCleanup(right.close)
        def respond():
            try:
                received.append(right.recv(4096))
                right.sendall(b'/> ')
            except OSError:
                pass
        thread = threading.Thread(target=respond, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        with patch.object(fg.socket, 'create_connection', return_value=left):
            client = fg.Client(1234, timeout=0.2)
            self.addCleanup(client.close)
        thread.join(1)
        self.assertEqual(received, [b'prompt\r\n'])

    def test_fragmented_numeric_response(self):
        client = self.client([b"/orientation/roll-deg = '", b"-1.25' (double)\r\n/", b'> '])
        self.assertEqual(client.get('/orientation/roll-deg'), -1.25)

    def test_split_prompt_does_not_leave_a_space_for_next_reply(self):
        client = fg.Client.__new__(fg.Client)
        client.buffer = b''
        client.sock = unittest.mock.Mock()
        client.sock.gettimeout.return_value = 1
        client.sock.recv.side_effect = [b'/>', b' ', b'/> ']
        self.assertEqual(client._response(), '')
        self.assertEqual(client.buffer, b'')
        self.assertEqual(client._response(), '')

    def test_failed_command_rejected(self):
        client = self.client([b'*failed*\r\n/> '])
        with self.assertRaises(RuntimeError):
            client.command('run reset')

    def test_pause_and_resume_update_both_freeze_flags(self):
        client = fg.Client.__new__(fg.Client)
        client.set = unittest.mock.Mock()
        client.set_paused(True)
        self.assertEqual(client.set.call_args_list, [
            unittest.mock.call('/sim/freeze/clock', 'true'),
            unittest.mock.call(fg.PAUSE, 'true')])
        client.set.reset_mock()
        client.set_paused(False)
        self.assertEqual(client.set.call_args_list, [
            unittest.mock.call(fg.PAUSE, 'false'),
            unittest.mock.call('/sim/freeze/clock', 'false')])

    def test_missing_property_is_not_zero(self):
        client = self.client([b"/missing = '' (unknown)\r\n/> "])
        with self.assertRaises(ValueError):
            client.get('/missing')

    def test_non_finite_rejected(self):
        client = self.client([b"/value = 'nan' (double)\r\n/> "])
        with self.assertRaises(ValueError):
            client.get('/value')

    def test_server_error_rejected(self):
        client = self.client([b'-ERR unknown command\r\n/> '])
        with self.assertRaises(RuntimeError):
            client.command('invalid')

    def test_missing_prompt_times_out(self):
        client = self.client([b'incomplete'])
        with self.assertRaises(TimeoutError):
            client.command('get /value')

    def test_disconnect_detected(self):
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        client = fg.Client.__new__(fg.Client)
        client.sock, client.buffer = left, b''
        left.settimeout(0.1)
        right.close()
        with self.assertRaises(ConnectionError):
            client._response()


class FakeSimulator:
    def __init__(self):
        self.state = dict(altitude_m=1000, airspeed_m_s=46.3, latitude_deg=37,
                          longitude_deg=-122, heading_deg=280, roll_deg=0,
                          pitch_deg=0, aileron=0, elevator=0, engine_running=1)
        self.baseline = self.state.copy()
        self.paused = True
        self.reset_count = 0

    def get(self, path):
        if path == '/sim/signals/fdm-initialized':
            return 1
        return 1

    def snapshot(self):
        return self.state.copy()

    def set(self, path, value):
        if path == fg.PAUSE:
            self.paused = value == 'true'
        else:
            self.state[path.rsplit('/', 1)[-1]] = value

    def set_paused(self, paused):
        self.paused = paused

    def command(self, command):
        if command == 'run reset':
            self.state = self.baseline.copy()
            self.paused = True
            self.reset_count += 1
            raise ConnectionError('Reset closes socket')

    def close(self):
        pass

    def advance(self, seconds):
        if not self.paused:
            self.state['longitude_deg'] += seconds * 0.0001
            self.state['roll_deg'] += self.state['aileron'] * seconds * 10
            self.state['pitch_deg'] += self.state['elevator'] * seconds * 10


class ExperimentTests(unittest.TestCase):
    def test_full_sequence_reconnects_and_neutralises(self):
        sim = FakeSimulator()
        args = SimpleNamespace(port=1, timeout=1, pulse_seconds=2, non_interactive=True)
        report = {'checks': []}
        experiment = fg.Experiment(args, None, report)
        with patch.object(fg, 'connect_ready', return_value=sim), patch.object(fg.time, 'sleep', side_effect=sim.advance):
            experiment.run()
            experiment.close()
        self.assertTrue(all(c['passed'] for c in report['checks']))
        self.assertEqual(sim.reset_count, 7)
        self.assertTrue(sim.paused)
        self.assertEqual(sim.state['aileron'], 0)
        self.assertEqual(report['visual_inspection']['status'], 'not_performed')

    def test_unresponsive_aircraft_does_not_pass(self):
        sim = FakeSimulator()
        args = SimpleNamespace(port=1, timeout=1, pulse_seconds=2, non_interactive=True)
        report = {'checks': []}
        experiment = fg.Experiment(args, None, report)
        with patch.object(fg, 'connect_ready', return_value=sim), patch.object(fg.time, 'sleep'):
            experiment.run()
        failed = {c['name'] for c in report['checks'] if not c['passed']}
        self.assertIn('resume moves aircraft', failed)
        self.assertIn('aileron produces opposite responses', failed)
        self.assertIn('elevator produces opposite responses', failed)

    def test_reset_drift_fails(self):
        before = {'heading_deg': 359, 'altitude_m': 1000}
        after = {'heading_deg': 1, 'altitude_m': 1020}
        self.assertEqual(fg.differences(before, after, {'heading_deg': 3, 'altitude_m': 10}), {'altitude_m': 20})

    def test_readiness_waits_for_scenery_after_fdm(self):
        loading = unittest.mock.Mock()
        loading.get.side_effect = [1, 0]
        ready = unittest.mock.Mock()
        ready.get.side_effect = [1, 1]
        process = SimpleNamespace(poll=lambda: None)
        with patch.object(fg, 'Client', side_effect=[loading, ready]), patch.object(fg.time, 'sleep'):
            self.assertIs(fg.connect_ready(1, process, 1), ready)
        loading.close.assert_called_once()
        loading.snapshot.assert_not_called()
        ready.snapshot.assert_called_once()

    def test_early_process_exit(self):
        process = SimpleNamespace(poll=lambda: 7, returncode=7)
        with self.assertRaisesRegex(RuntimeError, 'status 7'):
            fg.connect_ready(1, process, 1)


if __name__ == '__main__':
    unittest.main()
