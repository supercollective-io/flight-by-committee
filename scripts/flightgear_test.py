#!/usr/bin/env python3
"""Terminal-driven FlightGear feasibility test; Python standard library only."""
import argparse
from contextlib import ExitStack
import datetime as dt
import json
import math
from pathlib import Path
import platform
import re
import socket
import sys
import time

# Also support direct script execution under uv.
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import flightgear

PROPERTIES = {
    'altitude_m': ('/position/altitude-ft', 0.3048),
    'airspeed_m_s': ('/velocities/airspeed-kt', 0.514444),
    'latitude_deg': ('/position/latitude-deg', 1),
    'longitude_deg': ('/position/longitude-deg', 1),
    'heading_deg': ('/orientation/heading-deg', 1),
    'roll_deg': ('/orientation/roll-deg', 1),
    'pitch_deg': ('/orientation/pitch-deg', 1),
    'aileron': ('/controls/flight/aileron', 1),
    'elevator': ('/controls/flight/elevator', 1),
    'engine_running': ('/engines/active-engine/running', 1),
}
TOLERANCES = {'altitude_m': 10, 'airspeed_m_s': 2, 'latitude_deg': 0.0001,
              'longitude_deg': 0.0001, 'heading_deg': 2, 'roll_deg': 2,
              'pitch_deg': 2, 'aileron': 0.01, 'elevator': 0.01,
              'engine_running': 0}
PAUSE = '/sim/freeze/master'


class Client:
    """Serial request/reply client using prompt framing, never timed reads."""
    def __init__(self, port, timeout=5):
        self.sock = socket.create_connection(('127.0.0.1', port), timeout)
        self.sock.settimeout(timeout)
        self.buffer = b''
        try:
            # FlightGear sends no greeting: request prompt mode explicitly.
            self.command('prompt')
        except BaseException:
            self.close()
            raise

    def close(self):
        self.sock.close()

    def _response(self):
        deadline = time.monotonic() + self.sock.gettimeout()
        while True:
            match = re.search(rb'(?:^|[\r\n])/> ', self.buffer)
            if match:
                result = self.buffer[:match.start()].decode('utf-8')
                self.buffer = self.buffer[match.end():]
                if any(marker in result for marker in ('-ERR', '*failed*', 'Error:')):
                    raise RuntimeError(result.strip())
                return result
            if time.monotonic() >= deadline or len(self.buffer) > 65536:
                raise TimeoutError('Missing FlightGear command prompt')
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError('FlightGear closed the command connection')
            self.buffer += chunk

    def command(self, command):
        self.sock.sendall((command + '\r\n').encode())
        try:
            return self._response()
        except TimeoutError as exc:
            raise TimeoutError(f'No complete reply to {command!r}; received {self.buffer[:200]!r}') from exc

    def get(self, path):
        reply = self.command('get ' + path)
        match = re.search(r"= '(.*)' \([^)]+\)", reply)
        if not match or not match[1]:
            raise ValueError(f'Missing or untyped property {path}: {reply!r}')
        value = {'true': '1', 'false': '0'}.get(match[1], match[1])
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f'Non-finite property {path}: {value}')
        return number

    def set(self, path, value):
        self.command(f'set {path} {value}')
        actual = self.get(path)
        expected = {'true': 1, 'false': 0}.get(str(value), value)
        if abs(actual - float(expected)) > 0.001:
            raise RuntimeError(f'Control ownership/read-back failure: {path}={actual}')

    def set_paused(self, paused):
        # Freeze time first, and release it last, so no physics step can slip
        # between the two property updates. --enable-freeze sets both flags.
        if paused:
            self.set('/sim/freeze/clock', 'true')
            self.set(PAUSE, 'true')
        else:
            self.set(PAUSE, 'false')
            self.set('/sim/freeze/clock', 'false')

    def snapshot(self):
        return {name: self.get(path) * factor
                for name, (path, factor) in PROPERTIES.items()}


def differences(before, after, tolerances):
    result = {}
    for name, tolerance in tolerances.items():
        delta = after[name] - before[name]
        if name in ('heading_deg', 'longitude_deg'):
            delta = (delta + 180) % 360 - 180
        if abs(delta) > tolerance:
            result[name] = delta
    return result


def connect_ready(port, process, timeout):
    deadline = time.monotonic() + timeout
    last = None
    next_update = 0.0
    print(f'Waiting for FlightGear on port {port} (up to {timeout:g} s)…', flush=True)
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f'FlightGear exited with status {process.returncode}; see simulator.log')
        client = None
        try:
            client = Client(port)
            if (client.get('/sim/signals/fdm-initialized') == 1
                    and client.get('/sim/sceneryloaded') == 1):
                client.snapshot()
                print('FlightGear command connection and telemetry ready.', flush=True)
                return client
            last = 'Flight dynamics or scenery not initialised yet'
        except (OSError, ValueError, RuntimeError) as exc:
            last = exc
        if client:
            client.close()
        if time.monotonic() >= next_update:
            print(f'Still waiting: {last}', flush=True)
            next_update = time.monotonic() + 10
        time.sleep(0.5)
    raise TimeoutError(f'FlightGear not ready within {timeout} s: {last}')


class Experiment:
    def __init__(self, args, process, report):
        self.args, self.process, self.report = args, process, report
        self.client = None

    def record(self, name, passed, **details):
        self.report['checks'].append(dict(name=name, passed=bool(passed), **details))
        print(f"{'PASS' if passed else 'FAIL'}: {name}", flush=True)

    def reset(self):
        start = time.monotonic()
        try:
            self.client.command('run reset')
        except (ConnectionError, TimeoutError):
            pass  # Reset may close the connection before acknowledging.
        self.client.close()
        self.client = None
        time.sleep(2)
        self.client = connect_ready(self.args.port, self.process, self.args.timeout)
        self.client.set_paused(True)
        return self.client.snapshot(), time.monotonic() - start

    def run(self):
        self.client = connect_ready(self.args.port, self.process, self.args.timeout)
        c = self.client
        c.set_paused(True)
        baseline = c.snapshot()
        self.report['baseline'] = baseline
        plausible = (abs(baseline['altitude_m'] - 1000) < 10
                     and abs(baseline['airspeed_m_s'] - 46.3) < 3
                     and abs(baseline['roll_deg']) < 5)
        self.record('airborne starting state', plausible, state=baseline)
        if not plausible:
            raise RuntimeError('Starting state differs from the requested airborne preset')
        time.sleep(2)
        paused = c.snapshot()
        limits = {k: 0.001 for k in ('altitude_m', 'roll_deg', 'pitch_deg', 'latitude_deg', 'longitude_deg')}
        drift = differences(baseline, paused, limits)
        self.record('pause holds aircraft state', not drift, differences=drift)
        c.set_paused(False)
        time.sleep(3)
        c.set_paused(True)
        resumed = c.snapshot()
        moved = abs(resumed['longitude_deg'] - paused['longitude_deg']) + abs(resumed['latitude_deg'] - paused['latitude_deg']) > 0.00001
        self.record('resume moves aircraft', moved, state=resumed)
        self.record('engine runs after resume', resumed['engine_running'] == 1)

        for axis, attitude in [('aileron', 'roll_deg'), ('elevator', 'pitch_deg')]:
            responses = []
            for value in (0.1, -0.1):
                before, _ = self.reset()
                c = self.client
                path = '/controls/flight/' + axis
                c.set(path, value)
                try:
                    c.set_paused(False)
                    time.sleep(self.args.pulse_seconds)
                    c.set_paused(True)
                    after = c.snapshot()
                finally:
                    c.set_paused(True)
                    c.set(path, 0)
                delta = after[attitude] - before[attitude]
                delta = (delta + 180) % 360 - 180
                responses.append(delta)
                self.record(f'{axis} {value:+g} retained', abs(after[axis] - value) < 0.01,
                            before=before, after=after, response_deg=delta)
            self.record(f'{axis} produces opposite responses', responses[0] * responses[1] < 0
                        and min(map(abs, responses)) > 0.2, responses_deg=responses)

        for index in range(3):
            c = self.client
            c.set('/controls/flight/aileron', 0.1)
            c.set_paused(False)
            time.sleep(2)
            state, duration = self.reset()
            drift = differences(baseline, state, TOLERANCES)
            self.record(f'reset {index + 1}', not drift, duration_s=duration,
                        state=state, differences=drift)

        # Inspect repeated short flights, avoiding a ten-minute uncontrolled dive.
        self.report['visual_inspection'] = {'status': 'not_performed'}
        if not self.args.non_interactive:
            self.reset()
            print('Inspect the FlightGear window at the intended display resolution.')
            print('Press Enter after each 20 s flight to repeat; type pass/fail and notes to finish.')
            while True:
                self.client.set_paused(False)
                time.sleep(20)
                self.client.set_paused(True)
                answer = input('Visual result [Enter/pass notes/fail notes]: ').strip()
                if answer.split(' ', 1)[0] in ('pass', 'fail'):
                    status, _, notes = answer.partition(' ')
                    self.report['visual_inspection'] = {'status': status, 'notes': notes}
                    break
                self.reset()

    def close(self):
        if self.client:
            try:
                self.client.set_paused(True)
                for axis in ('aileron', 'elevator'):
                    self.client.set('/controls/flight/' + axis, 0)
            except (OSError, ValueError, RuntimeError):
                pass
            self.client.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', help='Override the stable installation executable')
    parser.add_argument('--fg-root', type=Path, help='Override the stable installation base data')
    parser.add_argument('--port', type=int, default=55401)
    parser.add_argument('--timeout', type=float, default=180)
    parser.add_argument('--pulse-seconds', type=float, default=2)
    parser.add_argument('--output', type=Path, default=Path('test-results') / dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    parser.add_argument('--non-interactive', action='store_true', help='Skip visual review; never report a full feasibility pass')
    parser.add_argument('--dry-run', action='store_true', help='Print launch arguments without starting FlightGear')
    args = parser.parse_args(argv)
    if (not 1 <= args.port <= 65535 or not 0 < args.pulse_seconds <= 5
            or not math.isfinite(args.timeout) or args.timeout <= 0):
        parser.error('Require port 1–65535, pulse duration >0 and <=5 s, and timeout >0')
    try:
        resolved = flightgear.resolve('feasibility', overrides=vars(args))
        # The experiment has fixed assumptions even if the saved profile is edited.
        profile, location = resolved['profile'], resolved['location']
        if (profile['installation'] != 'stable' or profile['aircraft'] != 'c172p'
                or profile['rendering'] != 'standard'
                or location != {'airport': 'KSFO', 'heading_deg': 280, 'on_ground': False}
                or profile['flight'] != {'altitude_m': 1000, 'speed_m_s': 46.3,
                                        'time_of_day': 'noon', 'frozen': True, 'engine_running': True}):
            raise ValueError('The feasibility experiment requires its fixed stable C172P scenario')
        command = resolved['command'] + ['--roll=0', '--pitch=0', '--disable-ai-traffic',
                   f'--telnet=socket,bi,100,127.0.0.1,{args.port},tcp']
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if args.dry_run:
        print(json.dumps(command, indent=2))
        return 0
    try:
        flightgear.validate_assets(resolved)
    except ValueError as exc:
        parser.error(str(exc))
    # Refuse to attach to or alter an existing simulator.
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1', args.port)) == 0:
            parser.error(f'Port {args.port} already in use; choose another --port')
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'started_at': dt.datetime.now(dt.timezone.utc).isoformat(),
              'host': platform.platform(), 'command': command, 'resolved': resolved, 'checks': [],
              'visual_inspection': {'status': 'not_performed'}, 'status': 'error'}
    process = experiment = None
    resources = ExitStack()
    try:
        log = resources.enter_context((args.output / 'simulator.log').open('w'))
        process = resources.enter_context(flightgear.simulator(command, args.output / 'state/stable', log))
        print(f'FlightGear PID {process.pid}; log: {args.output / "simulator.log"}', flush=True)
        experiment = Experiment(args, process, report)
        experiment.run()
        failed = any(not check['passed'] for check in report['checks'])
        visual = report['visual_inspection']['status']
        report['status'] = 'fail' if failed or visual == 'fail' else ('pass' if visual == 'pass' else 'automated_pass_visual_pending')
    except (OSError, ValueError, RuntimeError, KeyboardInterrupt, EOFError) as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
        print(report['error'], file=sys.stderr)
    finally:
        if experiment:
            experiment.close()
        resources.close()
        (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        print(f"Report: {(args.output / 'report.json').resolve()} ({report['status']})")
    return 0 if report['status'] in ('pass', 'automated_pass_visual_pending') else 1


if __name__ == '__main__':
    sys.exit(main())
