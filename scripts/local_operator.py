"""Loopback-only operator app; one child process owns each flight."""
import asyncio
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import signal
import sys
import threading
import webbrowser

from aiohttp import web
from scripts import flightgear as fg

STATIC = Path(__file__).with_name('operator')
STATE = web.AppKey('operator', object)


def toml_document(data):
    """Serialise the profile schema, not arbitrary TOML."""
    lines = []
    def table(value, prefix=()):
        for key, item in value.items():
            if not isinstance(item, dict):
                if not isinstance(item, (str, bool, int, float)):
                    raise ValueError(f'Unsupported profile value: {key}')
                lines.append(f'{json.dumps(key)} = {json.dumps(item, ensure_ascii=False, allow_nan=False)}')
        for key, item in value.items():
            if isinstance(item, dict):
                path = (*prefix, key)
                lines.extend(['', '[' + '.'.join(json.dumps(part) for part in path) + ']'])
                table(item, path)
    table(data)
    return '\n'.join(lines) + '\n'


def revision(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data))
    temporary.replace(path)


class Operator:
    def __init__(self, root):
        self.root = Path(root)
        self.token = secrets.token_urlsafe(32)
        self.lock = asyncio.Lock()
        self.process = None
        self.waiter = None
        self.run_dir = None
        self.current = {'phase': 'idle', 'message': 'No flight launched yet.'}
        self.host = None

    def catalogue(self):
        profiles = []
        for path in sorted((self.root / 'profiles').glob('*.toml')) + sorted((self.root / 'profiles/local').glob('*.toml')):
            try:
                data = fg.read(path)
                profiles.append({'name': path.stem, 'description': data['description'],
                                 'custom': path.parent.name == 'local'})
            except (OSError, ValueError, KeyError):
                profiles.append({'name': path.stem, 'description': 'Invalid profile — inspect the TOML file.',
                                 'custom': path.parent.name == 'local'})
        config = self.root / 'config'
        installation_file = config / 'installations.local.toml'
        if not installation_file.exists():
            installation_file = config / 'installations.example.toml'
        return {'profiles': profiles, 'options': {
            'installation': list(fg.read(installation_file)),
            'rendering': sorted(p.stem for p in (config / 'rendering').glob('*.fgfsrc')),
            'location': {p.stem: fg.read(p) for p in sorted((config / 'locations').glob('*.toml'))},
            'input': sorted(p.stem for p in (config / 'inputs').glob('*.toml')),
            'initialisation': sorted(p.stem for p in (config / 'aircraft').glob('*.xml')),
        }}

    def detail(self, name):
        path = fg.profile_path(name, self.root)
        data = fg.read(path)
        resolved = fg.resolve(name, root=self.root)
        return {'name': name, 'profile': data, 'location': resolved['location'],
                'custom': path.parent.name == 'local', 'revision': revision(path),
                'effective': self.effective(resolved)}

    @staticmethod
    def effective(resolved):
        # These are requested settings, not a claim about live simulator values.
        return {'location': resolved['location'], 'flight': resolved['profile']['flight'],
                'input': resolved['input_config'], 'installation': resolved['installation'],
                'command': resolved['command']}

    def resolve_draft(self, payload):
        fg.keys(payload, ('name', 'profile', 'revision'), ('name', 'profile'), 'request')
        return fg.resolve(payload['name'], root=self.root, profile_data=payload['profile'])

    def save(self, payload):
        resolved = self.resolve_draft(payload)
        name = resolved['profile_name']
        if (self.root / 'profiles' / f'{name}.toml').exists():
            raise ValueError('This is a shipped profile. Choose a new name to save a local copy.')
        directory = self.root / 'profiles/local'
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f'{name}.toml'
        contents = toml_document(payload['profile'])
        if path.exists():
            if payload.get('revision') != revision(path):
                raise web.HTTPConflict(text='Profile changed or name already exists. Reload it or choose another name.')
            temporary = directory / f'.{name}-{secrets.token_hex(8)}.tmp'
            try:
                temporary.write_text(contents)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        else:
            if payload.get('revision'):
                raise web.HTTPConflict(text='Profile was removed. Reload before saving.')
            with path.open('x') as stream:
                stream.write(contents)
        return self.detail(name)

    def status(self):
        result = dict(self.current)
        if self.process is not None and self.process.returncode is None and self.run_dir:
            try:
                result.update(json.loads((self.run_dir / 'status.json').read_text()))
            except (OSError, ValueError):
                pass
            if self.current['phase'] == 'stopping':
                result.update(phase='stopping', message='Stopping FlightGear and its controls…')
        result['active'] = self.process is not None and self.process.returncode is None
        return result

    async def launch(self, payload):
        async with self.lock:
            if self.process is not None and self.process.returncode is None:
                raise web.HTTPConflict(text='A flight is already active. Stop it before launching another.')
            if self.waiter:
                await self.waiter
            resolved = self.resolve_draft(payload)
            fg.validate_assets(resolved)
            directory = self.root / 'test-results/operator' / secrets.token_hex(12)
            directory.mkdir(parents=True, mode=0o700)
            self.run_dir = directory
            self.current = {'phase': 'starting', 'name': payload['name'],
                            'description': payload['profile']['description'],
                            'message': 'Preparing aircraft and controls…',
                            'log': str(directory / 'worker.log'),
                            'settings': self.effective(resolved)}
            # A snapshot isolates the active flight from later edits or saves.
            snapshot = directory / 'profile.json'
            snapshot.write_text(json.dumps({'name': payload['name'], 'profile': payload['profile'], 'resolved': resolved}))
            with (directory / 'worker.log').open('wb') as log:
                try:
                    self.process = await asyncio.create_subprocess_exec(
                        sys.executable, '-m', 'scripts.local_operator', '--worker', str(directory),
                        cwd=self.root, stdout=log, stderr=log, start_new_session=True)
                except OSError:
                    self.current.update(phase='failed', message='Could not start the flight process. Check the local log.')
                    raise
            self.waiter = asyncio.create_task(self.watch(self.process))
            return self.status()

    async def watch(self, process):
        code = await process.wait()
        stopped = self.current['phase'] == 'stopping'
        self.current.update(phase='stopped' if stopped or code == 0 else 'failed', exit_code=code,
                            message='Flight stopped. Choose settings and launch again.' if stopped or code == 0
                            else 'Flight exited unexpectedly. Inspect the local log, correct the problem and relaunch.')

    async def stop(self):
        async with self.lock:
            process = self.process
            if process and process.returncode is None:
                self.current.update(phase='stopping')
                # Signal the worker first so its context managers release inputs.
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(asyncio.shield(self.waiter), timeout=15)
                except asyncio.TimeoutError:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    await self.waiter
            return self.status()


@web.middleware
async def guard(request, handler):
    state = request.app[STATE]
    if request.host != state.host or request.headers.get('Origin') not in (None, f'http://{state.host}'):
        raise web.HTTPForbidden(text='Use the local operator URL printed in the terminal.')
    if request.path.startswith('/api/'):
        if not hmac.compare_digest(request.headers.get('Authorization', '').encode(), ('Bearer ' + state.token).encode()):
            raise web.HTTPUnauthorized(text='Open the operator URL printed in the terminal to reconnect.')
    try:
        response = await handler(request)
    except (ValueError, OSError, TypeError, KeyError) as exc:
        # API configuration errors are local; never return worker/provider output.
        response = web.json_response({'error': str(exc)}, status=400)
    response.headers.update({'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
                             'X-Content-Type-Options': 'nosniff',
                             'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"})
    return response


def create_app(root=fg.ROOT):
    state = Operator(root)
    app = web.Application(middlewares=[guard], client_max_size=65536)
    app[STATE] = state

    async def catalogue(request):
        return web.json_response(state.catalogue())
    async def detail(request):
        return web.json_response(state.detail(request.match_info['name']))
    async def save(request):
        async with state.lock:
            return web.json_response(state.save(await request.json()))
    async def check(request):
        resolved = state.resolve_draft(await request.json())
        try:
            fg.validate_assets(resolved)
            ready, message = True, 'Installed assets found. Launch to check simulator and scenery readiness.'
        except ValueError as exc:
            ready, message = False, str(exc)
        return web.json_response({'ready': ready, 'message': message, 'effective': state.effective(resolved)})
    async def launch(request):
        return web.json_response(await state.launch(await request.json()))
    async def stop(request):
        return web.json_response(await state.stop())
    async def status(request):
        return web.json_response(state.status())
    async def asset(request):
        filename = request.match_info.get('file', 'index.html')
        if filename not in ('index.html', 'app.js', 'style.css'):
            raise web.HTTPNotFound()
        return web.FileResponse(STATIC / filename)
    async def cleanup(app):
        await state.stop()
    app.on_cleanup.append(cleanup)
    app.router.add_get('/api/profiles', catalogue)
    app.router.add_get('/api/profiles/{name}', detail)
    app.router.add_post('/api/profiles', save)
    app.router.add_post('/api/check', check)
    app.router.add_post('/api/launch', launch)
    app.router.add_post('/api/stop', stop)
    app.router.add_get('/api/status', status)
    app.router.add_get('/', asset)
    app.router.add_get('/{file}', asset)
    return app


def worker(directory):
    """Keep signals and FlightGear ownership in a dedicated main thread."""
    os.umask(0o077)
    directory = Path(directory)
    payload = json.loads((directory / 'profile.json').read_text())
    resolved = payload['resolved']
    stop = threading.Event()
    reporter = None
    def started(state, run_dir):
        nonlocal reporter
        def report():
            while not stop.is_set():
                data = {'phase': 'running', 'message': 'FlightGear process running. Check the simulator window for readiness.',
                        'simulator_log': str(run_dir / 'simulator.log'), 'links': {}}
                if state is not None:
                    with state.lock:
                        ready, connected = state.ready, state.connected
                        join = getattr(state, 'join_url', '')
                    data['phase'] = 'ready' if ready and connected else 'loading'
                    data['message'] = 'Aircraft reports ready. Pause and reset in FlightGear.' if ready and connected else 'Waiting for simulator connection and aircraft readiness…'
                    projection = getattr(state, 'projection_url', '')
                    if projection:
                        data['links']['Projection'] = projection
                        data['links']['Monitor and QR code'] = projection.replace('/projection?', '/?') + '&monitor=1'
                    if join:
                        data['links']['Participant controls'] = join
                atomic_json(directory / 'status.json', data)
                stop.wait(0.5)
        reporter = threading.Thread(target=report, daemon=True)
        reporter.start()
    def terminate(signum, frame):
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, terminate)
    try:
        return fg.run(resolved, on_started=started)
    finally:
        stop.set()
        if reporter:
            reporter.join(timeout=2)


def serve(*, root=fg.ROOT, port=0, open_browser=True):
    fg.number(port, 0, 65535, 'operator port')
    app = create_app(root)
    async def run():
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        try:
            site = web.TCPSite(runner, '127.0.0.1', port)
            await site.start()
            actual_port = runner.addresses[0][1]
            app[STATE].host = f'127.0.0.1:{actual_port}'
            url = f'http://{app[STATE].host}/#{app[STATE].token}'
            print(f'Local flight operator: {url}\nKeep this terminal open. Ctrl+C stops the app and its flight.', flush=True)
            if open_browser:
                webbrowser.open(url)
            done = asyncio.Event()
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, done.set)
            try:
                await done.wait()
            finally:
                for sig in (signal.SIGINT, signal.SIGTERM):
                    loop.remove_signal_handler(sig)
        finally:
            await runner.cleanup()
    asyncio.run(run())
    return 0


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--worker':
        sys.exit(worker(sys.argv[2]))
    sys.exit(serve())
