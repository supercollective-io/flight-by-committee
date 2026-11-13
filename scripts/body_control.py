"""Local camera input, with no identities, recordings or participant calibration."""
from contextlib import contextmanager
import json
import math
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time

from scripts import phone_control as phone


MAX_AGE = 0.5


class BodyState(phone.State):
    """One fresh camera sample; each visible pose votes once on readable axes."""
    def __init__(self, config, clock=time.monotonic):
        super().__init__(config, clock)
        self.inputs = []
        self.received = -math.inf
        self.invalidated = clock()
        self.command = dict(roll=0.0, pitch=0.0)

    def invalidate(self):
        super().invalidate()
        self.inputs = []
        self.received = -math.inf
        self.invalidated = self.clock()
        self.command = dict(roll=0.0, pitch=0.0)

    @property
    def frame_deadline(self):
        return self.received + MAX_AGE

    def fresh(self):
        return self.ready and bool(self.inputs) and self.clock() < self.frame_deadline

    def participants(self):
        return self.inputs if self.fresh() else []

    @property
    def values(self):
        axes = self.command if self.fresh() else dict(roll=0.0, pitch=0.0)
        return dict(**axes, rudder=0, brake=0, throttle=None)

    def accept(self, frame):
        if not isinstance(frame, dict) or set(frame) != {'kind', 'captured', 'inputs'} or frame['kind'] != 'frame':
            raise ValueError('Invalid camera frame')
        captured, inputs = frame['captured'], frame['inputs']
        if type(captured) not in (int, float) or not math.isfinite(captured):
            raise ValueError('Invalid camera timestamp')
        if not isinstance(inputs, list) or len(inputs) > 100:
            raise ValueError('Invalid camera contributions')
        for vote in inputs:
            if not isinstance(vote, dict) or set(vote) != {'roll', 'pitch'}:
                raise ValueError('Invalid camera contribution')
            if all(value is None for value in vote.values()):
                raise ValueError('Empty camera contribution')
            for value in vote.values():
                if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or not -1 <= value <= 1):
                    raise ValueError('Invalid camera axis')
        now = self.clock()
        if (not self.ready or captured <= max(self.received, self.invalidated)
                or not 0 <= now - captured < MAX_AGE):
            return False
        # Smooth the group, not remembered people. Empty axes release immediately.
        dt = captured - self.received
        alpha = 1.0 if dt >= MAX_AGE else 1 - math.exp(-dt / 0.15)
        for axis in self.command:
            votes = [v[axis] for v in inputs if v[axis] is not None]
            target = sum(votes) / len(votes) if votes else 0.0
            self.command[axis] = self.command[axis] + alpha * (target - self.command[axis]) if votes else 0.0
        self.inputs = [dict(v) for v in inputs]
        self.received = captured
        return True

    def status(self):
        participants = self.participants()
        result = dict(simulator=self.connected, ready=self.ready, active=bool(participants),
                      count=len(participants), throttle=self.throttle, accepted=self.applied,
                      collective=self.values, mode='body')
        # Existing dot display requires numbers. Missing axes remain explicit in
        # contributions; zero here is only a display placeholder, never a vote.
        result['contributions'] = participants
        result['inputs'] = [{axis: v[axis] if v[axis] is not None else 0 for axis in ('roll', 'pitch')}
                            for v in participants]
        return result


def read_camera(stream, state, started, finished):
    try:
        while True:
            line = stream.readline(65537)
            if not line:
                break
            if len(line) > 65536:
                raise ValueError('Oversized camera frame')
            frame = json.loads(line)
            if frame == {'kind': 'ready'} and not started.is_set():
                started.set()
                continue
            if not started.is_set():
                raise ValueError('Camera did not initialise')
            with state.lock:
                state.accept(frame)
    except (ValueError, OSError):
        print('Camera data unavailable — pitch and roll released.', file=sys.stderr, flush=True)
    finally:
        with state.lock:
            state.invalidate()
        finished.set()
        started.set()  # Wake startup waiter on failure too.


def observer_handler(state, secret):
    class Observer(phone.handler_for(state, secret)):
        def do_POST(self):
            self.reply(403, {})
    return Observer


@contextmanager
def running(config, simulator_port):
    settings = config['body']
    model = Path(settings['model']).expanduser()
    if not model.is_file():
        raise ValueError('Pose model missing. Download it as described in docs/body-controls.md and pass --pose-model PATH.')
    command = [sys.executable, '-m', 'scripts.body_camera', '--model', str(model.resolve()),
               '--camera', str(settings['camera']), '--max-poses', str(settings['max_poses']),
               '--camera-elevation-deg', str(settings['camera_elevation_deg'])]
    if settings['preview']:
        command.append('--preview')
    state = BodyState(config)
    started, finished, stop = threading.Event(), threading.Event(), threading.Event()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, text=True, bufsize=1)
    reader = threading.Thread(target=read_camera, args=(process.stdout, state, started, finished), daemon=True)
    server = None
    threads = []
    reader.start()
    try:
        if not started.wait(30) or finished.is_set() or process.poll() is not None:
            raise ValueError('Camera could not start. Check camera permissions, device index, body dependencies and pose model; see docs/body-controls.md.')
        secret = secrets.token_urlsafe(24)
        server = phone.ThreadingHTTPServer(('127.0.0.1', config['port']), observer_handler(state, secret))
        server.daemon_threads = True
        state.projection_url = f'http://127.0.0.1:{server.server_port}/projection?key={secret}'
        threads = [threading.Thread(target=server.serve_forever, daemon=True),
                   threading.Thread(target=phone.bridge, args=(state, simulator_port, stop), daemon=True)]
        for thread in threads:
            thread.start()
        print('Body controls: spread wings to contribute; bent elbows are welcome. Lower arms to rest.\n'
              'Lean forwards for nose down, backwards for nose up. No participant calibration.\n'
              'Only pitch and roll are camera-controlled. Manage throttle, rudder and brakes in FlightGear.\n'
              f'Local projection: {state.projection_url}', flush=True)
        yield state
    finally:
        stop.set()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        reader.join(timeout=3)
        process.stdout.close()
        if server is not None:
            if threads:
                server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=3)
