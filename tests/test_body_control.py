"""Dependency-free tests for local body input and its FlightGear boundary."""

from contextlib import redirect_stderr, redirect_stdout
from http.client import HTTPConnection
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from xml.etree import ElementTree as ET

from scripts import body_control, flightgear, phone_control as phone


def phone_config():
    return phone.validate(flightgear.read(flightgear.ROOT / 'config/inputs/phone-landing.toml'))


class BodyStateTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.state = body_control.BodyState(phone_config(), lambda: self.now)
        self.state.ready = True

    def frame(self, captured, inputs):
        return {'kind': 'frame', 'captured': captured, 'inputs': inputs}

    def test_axes_are_equal_weighted_and_missing_axes_do_not_vote(self):
        self.now = 100.1
        accepted = self.state.accept(self.frame(100.1, [
            {'roll': 1, 'pitch': None},
            {'roll': 0, 'pitch': 1},
            {'roll': -1, 'pitch': 1},
        ]))
        self.assertTrue(accepted)
        self.assertEqual(self.state.command, {'roll': 0, 'pitch': 1})
        self.assertEqual(self.state.values['roll'], 0)
        self.assertEqual(self.state.values['pitch'], 1)
        status = self.state.status()
        self.assertEqual(status['count'], 3)
        self.assertEqual(status['contributions'], [
            {'roll': 1, 'pitch': None},
            {'roll': 0, 'pitch': 1},
            {'roll': -1, 'pitch': 1},
        ])
        self.assertFalse(any('id' in key or 'name' in key for item in status['contributions'] for key in item))

    def test_empty_input_withdraws_commands_immediately_even_during_smoothing(self):
        self.now = 100.1
        self.assertTrue(self.state.accept(self.frame(100.1, [{'roll': 1, 'pitch': -1}])))
        self.now = 100.11
        self.assertTrue(self.state.accept(self.frame(100.11, [])))
        self.assertEqual(self.state.command, {'roll': 0, 'pitch': 0})
        self.assertFalse(self.state.fresh())
        self.assertEqual(self.state.values, dict(roll=0, pitch=0, rudder=0, brake=0, throttle=None))

    def test_an_axis_with_no_votes_is_released_without_waiting_for_smoothing(self):
        self.now = 100.1
        self.assertTrue(self.state.accept(self.frame(100.1, [{'roll': 1, 'pitch': 1}])))
        self.now = 100.11
        self.assertTrue(self.state.accept(self.frame(100.11, [{'roll': None, 'pitch': -1}])))
        self.assertEqual(self.state.command['roll'], 0)
        self.assertLess(self.state.command['pitch'], 1)

    def test_stale_before_acceptance_and_future_capture_are_rejected(self):
        self.now = 100.6
        self.assertFalse(self.state.accept(self.frame(100.1, [{'roll': 1, 'pitch': 0}])))
        self.assertFalse(self.state.fresh())
        self.assertFalse(self.state.accept(self.frame(100.7, [{'roll': 1, 'pitch': 0}])))

    def test_accepted_input_expires_after_inference_and_values_release(self):
        self.now = 100.1
        self.assertTrue(self.state.accept(self.frame(100.1, [{'roll': .7, 'pitch': -.2}])))
        self.now = 100.6001
        self.assertFalse(self.state.fresh())
        self.assertEqual(self.state.values['roll'], 0)
        self.assertEqual(self.state.values['pitch'], 0)

    def test_duplicate_timestamps_and_pre_reset_capture_are_rejected(self):
        self.now = 100.1
        sample = self.frame(100.1, [{'roll': .5, 'pitch': .2}])
        self.assertTrue(self.state.accept(sample))
        self.assertFalse(self.state.accept(sample))
        self.now = 100.2
        self.state.invalidate()
        self.state.ready = True
        self.now = 100.3
        self.assertFalse(self.state.accept(sample))
        self.assertFalse(self.state.fresh())
        new_sample = self.frame(100.3, [{'roll': -.3, 'pitch': .4}])
        self.assertTrue(self.state.accept(new_sample))
        self.assertTrue(self.state.fresh())

    def test_frames_before_camera_ready_are_rejected(self):
        self.state.ready = False
        self.now = 100.1
        self.assertFalse(self.state.accept(self.frame(100.1, [{'roll': 1, 'pitch': 0}])))
        self.assertFalse(self.state.fresh())

    def test_malformed_frames_and_non_finite_or_out_of_range_axes_raise(self):
        malformed = [
            {},
            {'kind': 'frame', 'captured': True, 'inputs': []},
            self.frame(float('nan'), []),
            self.frame(100.1, [{'roll': None, 'pitch': None}]),
            self.frame(100.1, [{'roll': 1.1, 'pitch': 0}]),
            self.frame(100.1, [{'roll': True, 'pitch': 0}]),
            self.frame(100.1, [{'roll': 0, 'pitch': 0, 'rudder': 0}]),
            self.frame(100.1, [{'roll': 0}]),
        ]
        for frame in malformed:
            with self.subTest(frame=frame), self.assertRaises(ValueError):
                self.state.accept(frame)
        self.assertFalse(self.state.fresh())


class BodyBoundaryTests(unittest.TestCase):
    def test_body_profile_selects_saved_defaults_and_cli_can_override_them(self):
        profile = flightgear.resolve('karlsruhe-747-body')
        settings = profile['input_config']['body']
        self.assertEqual(settings, dict(
            model=str((flightgear.ROOT / 'assets/models/pose_landmarker_lite.task').resolve()),
            camera=0, max_poses=12, camera_elevation_deg=0, preview=True))
        self.assertEqual(profile['input_config']['owned_axes'], ['roll', 'pitch'])
        changed = flightgear.resolve('karlsruhe-747-body', overrides={
            'camera': 2, 'camera_elevation_deg': 0, 'camera_preview': False})
        self.assertEqual(changed['input_config']['body']['camera'], 2)
        self.assertFalse(changed['input_config']['body']['preview'])
        phone_profile = flightgear.resolve('karlsruhe-747-body', overrides={'input_mode': 'phone'})
        self.assertNotIn('body', phone_profile['input_config'])
        self.assertNotIn('owned_axes', phone_profile['input_config'])

    def test_body_profile_cli_uses_profile_instead_of_implicit_phone_default(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
            self.assertEqual(flightgear.main(['run', 'karlsruhe-747-body', '--no-camera-preview', '--dry-run']), 0)
        document = json.loads(stdout.getvalue().split('\n\nCommand:')[0])
        self.assertIn('body', document['input_config'])
        self.assertFalse(document['input_config']['body']['preview'])

    def test_observer_rejects_post_without_creating_input(self):
        now = [100.0]
        state = body_control.BodyState(phone_config(), lambda: now[0])
        state.ready = True
        now[0] = 100.1
        self.assertTrue(state.accept({'kind': 'frame', 'captured': 100.1,
                                      'inputs': [{'roll': .5, 'pitch': None}]}))
        server = phone.ThreadingHTTPServer(('127.0.0.1', 0), body_control.observer_handler(state, 'secret'))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = HTTPConnection('127.0.0.1', server.server_port, timeout=2)
            connection.request('POST', '/input?key=secret', body='{}', headers={'Content-Type': 'application/json'})
            response = connection.getresponse()
            response.read()
            self.assertEqual(response.status, 403)
            self.assertEqual(state.sessions, {})
            connection.request('GET', '/status?key=secret')
            response = connection.getresponse()
            status = json.loads(response.read())
            self.assertEqual(response.status, 200)
            self.assertEqual(status['mode'], 'body')
            self.assertEqual(status['count'], 1)
            self.assertEqual(status['contributions'], [{'roll': .5, 'pitch': None}])
            self.assertEqual(state.sessions, {})
        finally:
            if 'connection' in locals():
                connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_body_watchdog_owns_only_pitch_and_roll(self):
        resolved = flightgear.resolve('karlsruhe-747-landing', overrides={
            'input_mode': 'body', 'pose_model': '/tmp/pose.task',
        })
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'watchdog.xml'
            phone.watchdog_xml(resolved['input_config'], destination)
            tree = ET.parse(destination)
        script = tree.findtext('./nasal/committee_phone/script')
        self.assertIn('var momentary = ["roll", "pitch"]', script)
        self.assertIn('if (0 and throttle != nil and throttle >= 0)', script)
        self.assertIn('foreach (var path; []) setprop(path, 0);', script)
        self.assertNotIn('foreach (var path; mapping.brake.paths)', script)

    def test_phone_default_remains_phone_and_body_cli_options_resolve(self):
        default = flightgear.resolve('karlsruhe-747-landing')
        self.assertNotIn('body', default['input_config'])
        stdout = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
            result = flightgear.main([
                'run', 'karlsruhe-747-landing', '--input-mode', 'body',
                '--pose-model', '/tmp/pose.task', '--camera', '2',
                '--max-poses', '4', '--camera-elevation-deg', '12',
                '--camera-preview', '--dry-run',
            ])
        self.assertEqual(result, 0)
        printed = stdout.getvalue()
        document = json.loads(printed[:printed.index('\n\nCommand:')])
        self.assertEqual(document['input_config']['body'], {
            'model': str(Path('/tmp/pose.task').resolve()), 'camera': 2, 'max_poses': 4,
            'camera_elevation_deg': 12.0, 'preview': True,
        })
        self.assertEqual(document['input_config']['owned_axes'], ['roll', 'pitch'])

    def test_invalid_body_option_combinations_and_profiles_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'require --input-mode body'):
            flightgear.resolve('karlsruhe-747-landing', overrides={'camera': 1})
        with self.assertRaisesRegex(ValueError, 'require --pose-model'):
            flightgear.resolve('karlsruhe-747-landing', overrides={'input_mode': 'body'})
        with self.assertRaisesRegex(ValueError, 'require a profile'):
            flightgear.resolve('amsterdam-explore', overrides={
                'input_mode': 'body', 'pose_model': '/tmp/pose.task',
            })
        with self.assertRaisesRegex(ValueError, 'device index'):
            flightgear.resolve('karlsruhe-747-landing', overrides={
                'input_mode': 'body', 'pose_model': '/tmp/pose.task', 'camera': -1,
            })
        with self.assertRaisesRegex(ValueError, 'camera elevation'):
            flightgear.resolve('karlsruhe-747-landing', overrides={
                'input_mode': 'body', 'pose_model': '/tmp/pose.task', 'camera_elevation_deg': 80,
            })

    def test_reader_eof_and_startup_error_invalidate_and_wake_waiters(self):
        state = body_control.BodyState(phone_config())
        state.ready = True
        state.inputs = [{'roll': 1, 'pitch': 1}]
        state.command = {'roll': 1, 'pitch': 1}
        started, finished = threading.Event(), threading.Event()
        with redirect_stderr(io.StringIO()):
            body_control.read_camera(io.StringIO(''), state, started, finished)
        self.assertTrue(started.is_set())
        self.assertTrue(finished.is_set())
        self.assertEqual(state.inputs, [])
        self.assertEqual(state.command, {'roll': 0, 'pitch': 0})

        failed_state = body_control.BodyState(phone_config())
        failed_started, failed_finished = threading.Event(), threading.Event()
        with redirect_stderr(io.StringIO()):
            body_control.read_camera(io.StringIO('{bad json}\n'), failed_state, failed_started, failed_finished)
        self.assertTrue(failed_started.is_set())
        self.assertTrue(failed_finished.is_set())
        self.assertFalse(failed_state.fresh())


if __name__ == '__main__':
    unittest.main()
