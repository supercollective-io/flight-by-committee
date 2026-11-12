import os
import subprocess
import sys
import unittest
from scripts.relay import configuration


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.env = dict(FLIGHT_PARTICIPANT_KEY='p' * 32, FLIGHT_BRIDGE_KEY='b' * 32,
                        COOLIFY_URL='https://www.flight.example,https://flight.example')

    def test_valid_configuration(self):
        self.assertEqual(configuration(self.env), ('p' * 32, 'b' * 32, 'https://flight.example', 8080))

    def test_missing_and_invalid_keys(self):
        for name in ('FLIGHT_PARTICIPANT_KEY', 'FLIGHT_BRIDGE_KEY'):
            for value in ('', 'short', 'bad value' * 8):
                with self.subTest(name=name, value=value), self.assertRaisesRegex(ValueError, name):
                    configuration({**self.env, name: value})
            env = self.env.copy()
            del env[name]
            with self.assertRaisesRegex(ValueError, name):
                configuration(env)

    def test_duplicate_keys_and_invalid_ports(self):
        with self.assertRaisesRegex(ValueError, 'must be different'):
            configuration({**self.env, 'FLIGHT_BRIDGE_KEY': self.env['FLIGHT_PARTICIPANT_KEY']})
        for port in ('oops', '0', '65536'):
            with self.assertRaisesRegex(ValueError, 'PORT'):
                configuration({**self.env, 'PORT': port})

    def test_startup_error_is_actionable_without_traceback_or_secret(self):
        env = {**os.environ, **self.env}
        del env['FLIGHT_PARTICIPANT_KEY']
        result = subprocess.run([sys.executable, '-m', 'scripts.relay'], env=env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertIn('Flight configuration error: Set FLIGHT_PARTICIPANT_KEY', result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        self.assertNotIn(self.env['FLIGHT_BRIDGE_KEY'], result.stderr)
