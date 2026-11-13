import unittest
from aiohttp.test_utils import TestClient, TestServer
from scripts.relay import Relay


class OperatorApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_shared_resource_and_auth_boundaries(self):
        relay = Relay('p' * 32, 'b' * 32, 'https://fly.supercollective.io', operator_token='o' * 32)
        async with TestClient(TestServer(relay.app())) as client:
            for headers in ({}, {'Authorization': 'Bearer ' + 'p' * 32}, {'Authorization': 'Bearer ' + 'b' * 32}, {'Authorization': 'o' * 32}, {'Authorization': 'Bearer ü'}):
                response = await client.get('/api/operator/sessions/current', headers=headers)
                self.assertEqual(response.status, 401)
            headers = {'Authorization': 'Bearer ' + 'o' * 32}
            collection = await client.get('/api/operator/sessions', headers=headers)
            resource = await client.get('/api/operator/sessions/current', headers=headers)
            value = await resource.json()
            self.assertEqual(await collection.json(), [value])
            self.assertEqual(value['participantUrl'], 'https://fly.supercollective.io/?key=' + 'p' * 32)
            self.assertEqual(value['status'], 'simulator-disconnected')
            self.assertEqual(resource.headers['Cache-Control'], 'no-store')
            self.assertNotIn('o' * 32, str(value))
            self.assertNotIn('b' * 32, str(value))
            self.assertEqual((await client.post('/api/operator/sessions', headers=headers)).status, 405)
            self.assertEqual((await client.get('/api/operator/sessions/missing', headers=headers)).status, 404)
            self.assertEqual((await client.get('/operator')).status, 200)
            script = await (await client.get('/operator.js')).text()
            self.assertIn('/api/operator/sessions/current', script)
            relay.bridge = object()
            relay.last_bridge = relay.clock()
            relay.state.ready = True
            ready = await (await client.get('/api/operator/sessions/current', headers=headers)).json()
            self.assertEqual(ready['status'], 'aircraft-ready')
            relay.state.ready = False
            loading = await (await client.get('/api/operator/sessions/current', headers=headers)).json()
            self.assertEqual(loading['status'], 'simulator-loading')

    async def test_optional_operator_api_and_distinct_token(self):
        relay = Relay('p' * 32, 'b' * 32, 'https://fly.supercollective.io')
        async with TestClient(TestServer(relay.app())) as client:
            self.assertEqual((await client.get('/api/operator/sessions')).status, 401)
        for token in ('short', 'p' * 32, 'b' * 32):
            with self.assertRaises(ValueError):
                Relay('p' * 32, 'b' * 32, 'https://fly.supercollective.io', operator_token=token)
