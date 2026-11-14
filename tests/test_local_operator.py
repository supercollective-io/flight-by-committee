import asyncio
import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer
from scripts import flightgear as fg
from scripts.local_operator import STATE, create_app, toml_document


class OperatorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for directory in ('profiles', 'config', 'scripts'):
            shutil.copytree(fg.ROOT / directory, self.root / directory, ignore=shutil.ignore_patterns('local', '__pycache__'))
        (self.root / 'config/installations.local.toml').unlink(missing_ok=True)
        self.app = create_app(self.root)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        self.state = self.app[STATE]
        self.state.host = self.client.make_url('/').authority
        self.headers = {'Authorization': 'Bearer ' + self.state.token}
        self.payload = {'name': 'my-flight', 'profile': fg.read(self.root / 'profiles/amsterdam-explore.toml')}

    async def post(self, route, data=None):
        return await self.client.post('/api/' + route, json=self.payload if data is None else data, headers=self.headers)

    async def test_auth_origin_host_and_private_assets(self):
        for headers in ({}, {'Authorization':'Bearer ü'}, {'Authorization':'Bearer wrong'}):
            response = await self.client.get('/api/profiles', headers=headers)
            self.assertEqual(response.status, 401)
        for extra in ({'Origin':'https://elsewhere.example'}, {'Host':'evil.example'}):
            response = await self.client.get('/api/profiles', headers={**self.headers, **extra})
            self.assertEqual(response.status, 403)
        response = await self.client.get('/', headers={'Host':self.state.host})
        self.assertEqual(response.status, 200)
        self.assertIn("frame-ancestors 'none'", response.headers['Content-Security-Policy'])
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        for path in ('/.env', '/flightgear.py', '/config/installations.local.toml'):
            self.assertEqual((await self.client.get(path)).status, 404)

    async def test_catalogue_and_effective_settings(self):
        response = await self.client.get('/api/profiles', headers=self.headers)
        self.assertTrue((await response.json())['profiles'])
        response = await self.client.get('/api/profiles/amsterdam-explore', headers=self.headers)
        detail = await response.json()
        self.assertFalse(detail['custom'])
        self.assertEqual(detail['location']['latitude_deg'], 52.3086)
        self.assertIn('--altitude=600', detail['effective']['command'])

    async def test_save_inline_location_round_trip_and_conflicts(self):
        original = (self.root / 'profiles/amsterdam-explore.toml').read_bytes()
        self.payload['profile']['location'] = {'latitude_deg':40.2, 'longitude_deg':-3.5, 'heading_deg':150, 'on_ground':False}
        self.payload['profile']['description'] = 'A "quoted" description\nwith a second line'
        self.payload['profile']['properties'] = {'/controls/flight/flaps':0.2, '/controls/gear/gear-down':True}
        response = await self.post('profiles')
        self.assertEqual(response.status, 200, await response.text())
        saved = await response.json()
        self.assertTrue(saved['custom'])
        self.assertEqual(saved['profile'], self.payload['profile'])
        self.assertIn('--lat=40.2', fg.resolve('my-flight', root=self.root)['command'])
        self.assertEqual((await self.post('profiles')).status, 409)
        self.payload['revision'] = saved['revision']
        self.payload['profile']['flight']['altitude_m'] = 1500
        self.assertEqual((await self.post('profiles')).status, 200)
        self.assertEqual((await self.post('profiles')).status, 409)
        self.assertEqual((self.root / 'profiles/amsterdam-explore.toml').read_bytes(), original)
        self.payload['name'] = 'amsterdam-explore'
        self.assertEqual((await self.post('profiles')).status, 400)

    async def test_validation_rejects_bad_drafts_without_writes(self):
        cases = [None, [], {'name':'../escape','profile':self.payload['profile']}]
        for location in ({'latitude_deg':91,'longitude_deg':0,'heading_deg':0,'on_ground':False},
                         {'latitude_deg':0,'heading_deg':0,'on_ground':False},
                         {'airport':'EHAM','latitude_deg':0,'longitude_deg':0,'heading_deg':0,'on_ground':False}):
            profile = copy.deepcopy(self.payload['profile']); profile['location'] = location
            cases.append({'name':'invalid','profile':profile})
        for payload in cases:
            response = await self.client.post('/api/profiles', json=payload, headers=self.headers)
            self.assertEqual(response.status, 400, await response.text())
        self.assertFalse((self.root / 'profiles/local').exists())

    async def test_dry_check_and_failure_do_not_spawn(self):
        with patch('scripts.local_operator.fg.validate_assets', side_effect=ValueError('Missing test aircraft')):
            response = await self.post('check')
            self.assertFalse((await response.json())['ready'])
            self.assertEqual((await self.post('launch')).status, 400)
        self.assertIsNone(self.state.process)
        self.assertFalse((self.root / 'test-results').exists())

    def install_fake_simulator(self, *, exit_code=None):
        binary = self.root / 'fake-fg'
        body = f'import sys\nsys.exit({exit_code})\n' if exit_code is not None else f'import os, time\nfrom pathlib import Path\nPath({str(self.root / "fake-fg.pid")!r}).write_text(str(os.getpid()))\ntime.sleep(120)\n'
        binary.write_text(f'#!{sys.executable}\n' + body)
        binary.chmod(0o755)
        data = self.root / 'data'
        (data / 'Aircraft/ufo').mkdir(parents=True, exist_ok=True)
        (data / 'defaults.xml').touch()
        (data / 'Aircraft/ufo/ufo-set.xml').touch()
        (self.root / 'config/installations.local.toml').write_text(toml_document({'nightly':{'binary':str(binary),'fg_root':str(data)}}))

    async def wait_phase(self, *phases):
        # Process import/startup is not a five-second performance contract.
        deadline = asyncio.get_running_loop().time() + 30
        while asyncio.get_running_loop().time() < deadline:
            if self.state.status()['phase'] in phases:
                return self.state.status()
            await asyncio.sleep(.05)
        self.fail(f'Expected {phases}, got {self.state.status()}')

    async def test_real_worker_lifecycle_snapshot_stop_and_relaunch(self):
        self.install_fake_simulator()
        response = await self.post('launch')
        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual((await self.post('launch')).status, 409)
        await self.wait_phase('running')
        # UI draft changes cannot mutate the already-launched snapshot.
        self.payload['profile']['flight']['altitude_m'] = 1700
        snapshot = json.loads((self.state.run_dir / 'profile.json').read_text())
        self.assertEqual(snapshot['profile']['flight']['altitude_m'], 600)
        self.assertEqual((await self.post('profiles')).status, 200)
        first = self.state.process.pid
        for _ in range(100):
            if (self.root / 'fake-fg.pid').exists():
                break
            await asyncio.sleep(.01)
        simulator_pid = int((self.root / 'fake-fg.pid').read_text())
        response = await self.post('stop', {})
        self.assertEqual((await response.json())['phase'], 'stopped')
        with self.assertRaises(ProcessLookupError):
            os.kill(first, 0)
        with self.assertRaises(ProcessLookupError):
            os.kill(simulator_pid, 0)
        self.assertEqual((await self.post('launch')).status, 200)
        await self.wait_phase('running')
        self.assertNotEqual(self.state.process.pid, first)
        await self.client.close()
        self.assertIsNotNone(self.state.process.returncode)

    async def test_worker_failure_is_visible_and_allows_retry(self):
        self.install_fake_simulator(exit_code=7)
        self.assertEqual((await self.post('launch')).status, 200)
        status = await self.wait_phase('failed')
        self.assertEqual(status['exit_code'], 7)
        self.assertFalse(status['active'])
        self.assertEqual((await self.post('launch')).status, 200)
        await self.wait_phase('failed')


class ProfileIsolationTests(unittest.TestCase):
    def test_draft_resolution_does_not_mutate_input(self):
        profile = fg.read(fg.ROOT / 'profiles/amsterdam-explore.toml')
        before = copy.deepcopy(profile)
        fg.resolve('draft', profile_data=profile, overrides={'altitude_m':1200})
        self.assertEqual(profile, before)
