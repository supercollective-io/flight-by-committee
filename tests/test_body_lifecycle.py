"""Exercise the parent camera lifecycle with a real, synthetic worker process."""
import http.client
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from scripts import body_control, flightgear


class LifecycleTests(unittest.TestCase):
    def test_camera_process_streams_status_and_is_stopped_with_context(self):
        # No camera, provider or simulator: only the real pipe/server boundary.
        worker = '''
import json, time
print(json.dumps({'kind': 'ready'}), flush=True)
while True:
    print(json.dumps({'kind': 'frame', 'captured': time.monotonic(),
                      'inputs': [{'roll': 0.5, 'pitch': None}]}), flush=True)
    time.sleep(0.02)
'''
        processes = []
        popen = subprocess.Popen

        def launch(command, **kwargs):
            self.assertIn('scripts.body_camera', command)
            process = popen([sys.executable, '-c', worker], **kwargs)
            processes.append(process)
            return process

        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / 'pose.task'
            model.touch()
            config = flightgear.resolve('karlsruhe-747-landing', overrides={
                'input_mode': 'body', 'pose_model': str(model),
            })['input_config']
            config['port'] = 0
            with patch.object(body_control.subprocess, 'Popen', side_effect=launch), \
                    patch.object(body_control.phone, 'bridge'):
                with body_control.running(config, 0) as state:
                    with state.lock:
                        state.ready = state.connected = True
                    deadline = time.monotonic() + 3
                    while time.monotonic() < deadline:
                        with state.lock:
                            if state.fresh():
                                break
                        time.sleep(0.01)
                    with state.lock:
                        self.assertTrue(state.fresh())
                        status = state.status()
                    self.assertEqual(status['count'], 1)
                    self.assertEqual(status['collective']['roll'], .5)
                    self.assertIsNone(status['collective']['throttle'])
                    from urllib.parse import urlsplit
                    url = urlsplit(state.projection_url)
                    connection = http.client.HTTPConnection(url.hostname, url.port, timeout=2)
                    try:
                        connection.request('GET', '/status?' + url.query)
                        response = connection.getresponse()
                        self.assertEqual(response.status, 200)
                        self.assertEqual(json.loads(response.read())['mode'], 'body')
                    finally:
                        connection.close()
                self.assertIsNotNone(processes[0].poll())
                self.assertTrue(processes[0].stdout.closed)
                self.assertFalse(state.fresh())

    def test_missing_model_does_not_start_camera(self):
        with tempfile.TemporaryDirectory() as directory:
            config = flightgear.resolve('karlsruhe-747-landing', overrides={
                'input_mode': 'body', 'pose_model': str(Path(directory) / 'absent.task'),
            })['input_config']
            with patch.object(body_control.subprocess, 'Popen') as spawn:
                with self.assertRaisesRegex(ValueError, 'Pose model missing'):
                    with body_control.running(config, 0):
                        self.fail('Missing model started camera mode')
                spawn.assert_not_called()
