#!/usr/bin/env python3
"""Terminal-driven FlightGear aircraft and landing validation."""
import argparse
from contextlib import ExitStack
import datetime as dt
import json
import math
from pathlib import Path
import platform
import re
import select
import socket
import sys
import time

# Also support direct script execution under uv.
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import flightgear
from scripts import landing

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

    def snapshot(self, properties=None):
        return {name: self.get(path) * factor
                for name, (path, factor) in (properties or PROPERTIES).items()}


def differences(before, after, tolerances):
    result = {}
    for name, tolerance in tolerances.items():
        delta = after[name] - before[name]
        if name in ('heading_deg', 'longitude_deg'):
            delta = (delta + 180) % 360 - 180
        if abs(delta) > tolerance:
            result[name] = delta
    return result


def connect_ready(port, process, timeout, properties=None):
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
                if properties is None:
                    client.snapshot()
                else:
                    snapshot = client.snapshot(properties)
                    if snapshot.get('approach_ready', 1) != 1:
                        raise ValueError('Aircraft approach initialisation is still pending')
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
        self.resolved = report.get('resolved')
        self.is_747 = bool(self.resolved and self.resolved['profile']['aircraft'] == '747-400')
        self.properties = dict(PROPERTIES)
        self.tolerances = dict(TOLERANCES)
        if self.is_747:
            self.properties.pop('engine_running')
            self.tolerances.pop('engine_running')
            for index in range(4):
                self.properties[f'engine_{index}_running'] = (f'/engines/engine[{index}]/running', 1)
                self.properties[f'throttle_{index}'] = (f'/controls/engines/engine[{index}]/throttle', 1)
                self.tolerances[f'engine_{index}_running'] = 0
                self.tolerances[f'throttle_{index}'] = 0.01
                self.properties[f'hydraulic_{index}_mpa'] = (f'/systems/hydraulic/pressure[{index}]', 0.006894757)
            for index in range(5):
                self.properties[f'gear_{index}_position'] = (f'/gear/gear[{index}]/position-norm', 1)
                self.tolerances[f'gear_{index}_position'] = 0.01
            self.properties.update({
                'approach_ready': ('/sim/committee/approach-ready', 1),
                'flaps': ('/controls/flight/flaps', 1),
                'flaps_actual': ('/surface-positions/flap-pos-norm', 1),
                'gear_down': ('/controls/gear/gear-down', 1),
                'mass_kg': ('/fdm/jsbsim/inertia/weight-lbs', 0.45359237),
                'vertical_speed_m_s': ('/velocities/vertical-speed-fps', 0.3048),
            })
            self.tolerances.update(flaps=0.01, flaps_actual=0.01, gear_down=0, mass_kg=10, vertical_speed_m_s=1)

    def connect(self):
        if self.is_747:
            return connect_ready(self.args.port, self.process, self.args.timeout, self.properties)
        return connect_ready(self.args.port, self.process, self.args.timeout)

    def snapshot(self):
        return self.client.snapshot(self.properties) if self.is_747 else self.client.snapshot()

    def capture_views(self):
        self.reset()
        paths = []
        for label, view in (('cockpit', 0), ('aircraft', 1)):
            directory = (self.args.output / label).resolve()
            directory.mkdir()
            self.client.command(f'set /sim/paths/screenshot-dir {directory}')
            self.client.set('/sim/current-view/view-number', view)
            if view == 1:
                self.client.set('/sim/current-view/goal-heading-offset-deg', 135)
                self.client.set('/sim/current-view/heading-offset-deg', 135)
            time.sleep(2)
            self.client.command('run screen-capture')
            time.sleep(1)
            paths.extend(str(p) for p in directory.glob('*.png'))
        self.report['screenshots'] = paths
        self.client.set('/sim/current-view/view-number', 0)

    def review_landing(self):
        """Let an operator fly; record evidence without claiming an automatic landing."""
        self.reset()
        telemetry = dict(self.properties,
                         vertical_speed_m_s=('/velocities/vertical-speed-fps', 0.3048),
                         groundspeed_m_s=('/velocities/groundspeed-kt', 1852 / 3600),
                         main_gear_wow=('/gear/gear[1]/wow', 1),
                         wings_broken=('/controls/failures/wings/broken', 1))
        previous = self.client.snapshot(telemetry)
        touchdown = None
        print('Fly the approach in FlightGear. After stopping, type pass NOTES or fail NOTES here.')
        print('The flight continues until you submit a result; Ctrl+C aborts and pauses.')
        self.client.set_paused(False)
        started = time.monotonic()
        with (self.args.output / 'landing.jsonl').open('w') as stream:
            while True:
                state = self.client.snapshot(telemetry)
                stream.write(json.dumps(dict(state, elapsed_s=time.monotonic() - started)) + '\n')
                stream.flush()
                if touchdown is None and not previous['main_gear_wow'] and state['main_gear_wow']:
                    touchdown = dict(state)
                    # Ground contact can zero vertical speed; retain the last airborne value.
                    touchdown['vertical_speed_m_s'] = previous['vertical_speed_m_s']
                previous = state
                if select.select([sys.stdin], [], [], 0.5)[0]:
                    answer = input().strip()
                    status, _, notes = answer.partition(' ')
                    if status in ('pass', 'fail') and notes.strip():
                        break
                    print('Enter pass NOTES or fail NOTES after the landing.')
        self.client.set_paused(True)
        result = landing.assess(touchdown, state)
        self.report['landing_review'] = dict(result, operator_status=status, notes=notes,
                                             touchdown=touchdown, final=state)
        self.record('operator landing', result['passed'] and status == 'pass', **{'assessment': result})

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
        self.client = self.connect()
        self.client.set_paused(True)
        return self.snapshot(), time.monotonic() - start

    def run(self):
        self.client = self.connect()
        c = self.client
        c.set_paused(True)
        baseline = self.snapshot()
        self.report['baseline'] = baseline
        flight = self.resolved['profile']['flight'] if self.resolved else {'altitude_m': 1000, 'speed_m_s': 46.3}
        plausible = (abs(baseline['altitude_m'] - flight['altitude_m']) < 10
                     and abs(baseline['airspeed_m_s'] - flight['speed_m_s']) < 3
                     and abs(baseline['roll_deg']) < 5)
        self.record('airborne starting state', plausible, state=baseline)
        if not plausible:
            raise RuntimeError('Starting state differs from the requested airborne preset')
        if self.is_747:
            expected_vertical_speed = flight['speed_m_s'] * math.sin(math.radians(flight['glideslope_deg']))
            self.record('approach descent rate', abs(baseline['vertical_speed_m_s'] - expected_vertical_speed) <= 1,
                        vertical_speed_m_s=baseline['vertical_speed_m_s'], expected_m_s=expected_vertical_speed)
            location = self.resolved['location']
            position_error = landing.distance_m(location['latitude_deg'], location['longitude_deg'],
                                                baseline['latitude_deg'], baseline['longitude_deg'])
            heading_error = (baseline['heading_deg'] - location['heading_deg'] + 180) % 360 - 180
            # The WS3 bootstrap includes a physics update before pausing. Allow
            # at most 100 m from the requested start, but retain tighter reset
            # comparisons against the measured baseline below.
            self.record('approach position and heading', position_error <= 100 and abs(heading_error) <= 2,
                        position_error_m=position_error, heading_error_deg=heading_error)
            self.record('landing configuration', baseline['flaps'] == 1
                        and abs(baseline['flaps_actual'] - 1) < 0.01 and baseline['gear_down'] == 1
                        and all(abs(baseline[f'gear_{i}_position'] - 1) < 0.01 for i in range(5)),
                        state=baseline)
        time.sleep(2)
        paused = self.snapshot()
        limits = {k: 0.001 for k in ('altitude_m', 'roll_deg', 'pitch_deg', 'latitude_deg', 'longitude_deg')}
        drift = differences(baseline, paused, limits)
        self.record('pause holds aircraft state', not drift, differences=drift)
        c.set_paused(False)
        time.sleep(3)
        c.set_paused(True)
        resumed = self.snapshot()
        moved = abs(resumed['longitude_deg'] - paused['longitude_deg']) + abs(resumed['latitude_deg'] - paused['latitude_deg']) > 0.00001
        self.record('resume moves aircraft', moved, state=resumed)
        if self.is_747:
            for index in range(4):
                self.record(f'engine {index + 1} runs after resume', resumed[f'engine_{index}_running'] == 1)
                self.record(f'engine {index + 1} throttle retained',
                            abs(resumed[f'throttle_{index}'] - baseline[f'throttle_{index}']) < 0.01)
                self.record(f'hydraulic system {index + 1} pressurised', resumed[f'hydraulic_{index}_mpa'] > 6.9)
        else:
            self.record('engine runs after resume', resumed['engine_running'] == 1)

        neutral_response = {'roll_deg': 0, 'pitch_deg': 0}
        if self.is_747:
            before, _ = self.reset()
            self.client.set_paused(False)
            time.sleep(self.args.pulse_seconds)
            self.client.set_paused(True)
            after = self.snapshot()
            neutral_response = {k: (after[k] - before[k] + 180) % 360 - 180 for k in neutral_response}
            self.report['neutral_flight'] = dict(before=before, after=after, response_deg=neutral_response)

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
                    after = self.snapshot()
                finally:
                    c.set_paused(True)
                    c.set(path, 0)
                delta = after[attitude] - before[attitude]
                delta = (delta + 180) % 360 - 180
                responses.append(delta - neutral_response[attitude])
                self.record(f'{axis} {value:+g} retained', abs(after[axis] - value) < 0.01,
                            before=before, after=after, response_deg=delta,
                            response_relative_to_neutral_deg=delta - neutral_response[attitude])
            self.record(f'{axis} produces opposite responses', responses[0] * responses[1] < 0
                        and min(map(abs, responses)) > 0.2, responses_deg=responses,
                        neutral_response_deg=neutral_response[attitude])

        for index in range(3):
            c = self.client
            c.set('/controls/flight/aileron', 0.1)
            c.set_paused(False)
            time.sleep(2)
            state, duration = self.reset()
            drift = differences(baseline, state, self.tolerances)
            self.record(f'reset {index + 1}', not drift, duration_s=duration,
                        state=state, differences=drift)

        if getattr(self.args, 'capture_views', False):
            self.capture_views()
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
        if getattr(self.args, 'landing_review', False):
            self.review_landing()

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
    parser.add_argument('--profile', default='feasibility', choices=('feasibility', 'karlsruhe-747-landing'))
    parser.add_argument('--binary', help='Override the selected installation executable')
    parser.add_argument('--fg-root', type=Path, help='Override the selected installation base data')
    parser.add_argument('--port', type=int, default=55401)
    parser.add_argument('--timeout', type=float, default=180)
    parser.add_argument('--pulse-seconds', type=float, help='Control pulse duration (default: 4 s for 747-400, 2 s for C172P)')
    parser.add_argument('--output', type=Path, default=Path('test-results') / dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    parser.add_argument('--non-interactive', action='store_true', help='Skip visual review; never report a full feasibility pass')
    parser.add_argument('--landing-review', action='store_true', help='After visual review, record an operator landing and rollout at EDSB')
    parser.add_argument('--capture-views', action='store_true', help='Save simulator cockpit and external screenshots; does not mark visual review passed')
    parser.add_argument('--dry-run', action='store_true', help='Print launch arguments without starting FlightGear')
    args = parser.parse_args(argv)
    if args.pulse_seconds is None:
        args.pulse_seconds = 4 if args.profile == 'karlsruhe-747-landing' else 2
    if args.landing_review and (args.non_interactive or args.profile != 'karlsruhe-747-landing'):
        parser.error('--landing-review requires the interactive karlsruhe-747-landing profile')
    if (not 1 <= args.port <= 65535 or not 0 < args.pulse_seconds <= 5
            or not math.isfinite(args.timeout) or args.timeout <= 0):
        parser.error('Require port 1–65535, pulse duration >0 and <=5 s, and timeout >0')
    try:
        resolved = flightgear.resolve(args.profile, overrides=vars(args))
        # The experiment has fixed assumptions even if the saved profile is edited.
        profile, location = resolved['profile'], resolved['location']
        if args.profile == 'feasibility' and (profile['installation'] != 'stable' or profile['aircraft'] != 'c172p'
                or profile['rendering'] != 'standard'
                or location != {'airport': 'KSFO', 'heading_deg': 280, 'on_ground': False}
                or profile['flight'] != {'altitude_m': 1000, 'speed_m_s': 46.3,
                                        'time_of_day': 'noon', 'frozen': True, 'engine_running': True}):
            raise ValueError('The feasibility experiment requires its fixed stable C172P scenario')
        if args.profile == 'karlsruhe-747-landing' and (
                profile['aircraft'] != '747-400' or location['on_ground']
                or not {'latitude_deg', 'longitude_deg'} <= location.keys()
                or profile.get('initialisation') != '747-400-approach'
                or profile['flight'].get('glideslope_deg', 0) >= 0
                or not profile['flight'].get('frozen')
                or not profile['flight'].get('engine_running')
                or 'speed_m_s' not in profile['flight']):
            raise ValueError('The landing experiment requires a paused, airborne 747-400 with running engines and a specified speed')
        command = resolved['command'] + ['--roll=0', '--pitch=0', '--disable-ai-traffic',
                   f'--telnet=socket,bi,100,127.0.0.1,{args.port},tcp']
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if args.dry_run:
        print(json.dumps(command, indent=2))
        return 0
    try:
        flightgear.validate_assets(resolved)
        flightgear.build_livery.prepare(resolved)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    # Refuse to attach to or alter an existing simulator.
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1', args.port)) == 0:
            parser.error(f'Port {args.port} already in use; choose another --port')
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'started_at': dt.datetime.now(dt.timezone.utc).isoformat(),
              'host': platform.platform(), 'command': command, 'resolved': resolved, 'checks': [],
              'visual_inspection': {'status': 'not_performed'}, 'status': 'error'}
    if args.profile == 'karlsruhe-747-landing':
        report['landing_review'] = {'status': 'not_performed'}
    process = experiment = None
    resources = ExitStack()
    try:
        log = resources.enter_context((args.output / 'simulator.log').open('w'))
        process = resources.enter_context(flightgear.simulator(command, args.output / 'state' / profile['installation'], log))
        print(f'FlightGear PID {process.pid}; log: {args.output / "simulator.log"}', flush=True)
        experiment = Experiment(args, process, report)
        experiment.run()
        failed = any(not check['passed'] for check in report['checks'])
        visual = report['visual_inspection']['status']
        report['status'] = 'fail' if failed or visual == 'fail' else ('pass' if visual == 'pass' else 'automated_pass_visual_pending')
        if args.profile == 'karlsruhe-747-landing' and report['status'] == 'pass' and not args.landing_review:
            report['status'] = 'automated_pass_landing_pending'
    except (OSError, ValueError, RuntimeError, KeyboardInterrupt, EOFError) as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
        print(report['error'], file=sys.stderr)
    finally:
        if experiment:
            experiment.close()
        resources.close()
        (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        print(f"Report: {(args.output / 'report.json').resolve()} ({report['status']})")
    return 0 if report['status'] in ('pass', 'automated_pass_visual_pending', 'automated_pass_landing_pending') else 1


if __name__ == '__main__':
    sys.exit(main())
