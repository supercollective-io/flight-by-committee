import unittest
from scripts.runtime_origin import runtime_origin


class RuntimeOriginTests(unittest.TestCase):
    def test_explicit_override(self):
        self.assertEqual(runtime_origin({'FLIGHT_PUBLIC_ORIGIN': 'https://override.example/', 'COOLIFY_URL': 'invalid'}), 'https://override.example')

    def test_canonical_aliases(self):
        for value in ('https://flight.example,https://www.flight.example', 'https://www.flight.example/, https://flight.example/'):
            self.assertEqual(runtime_origin({'COOLIFY_URL': value}), 'https://flight.example')
        self.assertEqual(runtime_origin({'COOLIFY_URL': 'https://www.flight.example'}), 'https://www.flight.example')
        self.assertEqual(runtime_origin({'COOLIFY_URL': 'http://127.0.0.1:8080'}), 'http://127.0.0.1:8080')

    def test_rejects_invalid_or_missing_configuration(self):
        cases = [{}, {'FLIGHT_PUBLIC_ORIGIN': ''}, {'FLIGHT_PUBLIC_ORIGIN': '$COOLIFY_URL'}]
        cases += [{'COOLIFY_URL': value} for value in ('', 'https://a.example,https://b.example', 'https://a.example,http://a.example', 'https://user:secret@a.example', 'https://a.example/path', 'https://a.example?x=1', 'https://a.example,', 'ftp://a.example')]
        for env in cases:
            with self.subTest(env=env), self.assertRaises(ValueError):
                runtime_origin(env)
