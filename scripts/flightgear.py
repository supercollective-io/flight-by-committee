#!/usr/bin/env python3
"""Launch named FlightGear profiles. Run with uv run fly."""
import argparse
from contextlib import contextmanager
import datetime as dt
import json
import math
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import tomllib
import threading
import uuid

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import build_livery

ROOT = Path(__file__).resolve().parents[1]
NAME = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9_-]*\Z')


def keys(data, allowed, required, source):
    if not isinstance(data, dict):
        raise ValueError(f'{source}: expected a table')
    unknown, missing = set(data) - set(allowed), set(required) - set(data)
    if unknown or missing:
        raise ValueError(f'{source}: unknown keys {sorted(unknown)}; missing keys {sorted(missing)}')


def name(value):
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise ValueError(f'Invalid name: {value!r}')
    return value


def read(path):
    with path.open('rb') as stream:
        return tomllib.load(stream)


def number(value, low, high, label):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{label}: expected a finite number from {low} to {high}')
    return value


def boolean(value, label):
    if type(value) is not bool:
        raise ValueError(f'{label}: expected true or false')
    return value


def path_value(value, base):
    if not isinstance(value, str) or not value:
        raise ValueError('Installation paths must be non-empty strings')
    path = Path(value).expanduser()
    return str(path if path.is_absolute() else (base / path).resolve())


def installation(which, root=ROOT, binary=None, fg_root=None):
    local = root / 'config/installations.local.toml'
    source = local if local.exists() else root / 'config/installations.example.toml'
    entries = read(source)
    if which not in entries:
        raise ValueError(f'Unknown installation {which!r} in {source}')
    data = entries[which]
    keys(data, ('binary', 'fg_root', 'aircraft_dirs', 'scenery'), ('binary', 'fg_root'), source)
    data = data.copy()
    if binary:
        data['binary'] = str(Path(binary).expanduser().resolve())
    if fg_root:
        data['fg_root'] = str(Path(fg_root).expanduser().resolve())
        data['aircraft_dirs'] = [str(Path(data['fg_root']) / 'Aircraft')]
    for field in ('binary', 'fg_root', 'scenery'):
        if field in data:
            data[field] = path_value(data[field], source.parent)
    dirs = data.get('aircraft_dirs', [str(Path(data['fg_root']) / 'Aircraft')])
    if not isinstance(dirs, list):
        raise ValueError('aircraft_dirs must be an array of paths')
    data['aircraft_dirs'] = [path_value(p, source.parent) for p in dirs]
    return data


def resolve(profile_name, *, root=None, overrides=None):
    """Resolve and validate configuration without touching simulator state."""
    root = ROOT if root is None else root
    overrides = overrides or {}
    profile = read(root / 'profiles' / f'{name(profile_name)}.toml')
    keys(profile, ('description', 'warning', 'installation', 'location', 'rendering', 'aircraft', 'flight', 'properties', 'initialisation', 'livery', 'input'),
         ('description', 'installation', 'location', 'rendering', 'aircraft'), profile_name)
    for field in ('description', 'warning'):
        if field in profile and not isinstance(profile[field], str):
            raise ValueError(f'{field} must be a string')
    for field in ('installation', 'location', 'rendering', 'aircraft'):
        profile[field] = name(overrides.get(field) or profile[field])
    input_config = None
    if 'input' in profile:
        from scripts import phone_control
        input_name = name(profile['input'])
        input_config = phone_control.validate(read(root / 'config/inputs' / f'{input_name}.toml'))
    if 'livery' in profile:
        build_livery.livery_directory(root, profile['aircraft'], profile['livery'])
    install = installation(profile['installation'], root, overrides.get('binary'), overrides.get('fg_root'))
    location = read(root / 'config/locations' / f"{profile['location']}.toml")
    keys(location, ('airport', 'latitude_deg', 'longitude_deg', 'heading_deg', 'on_ground'),
         ('heading_deg', 'on_ground'), profile['location'])
    has_coords = 'latitude_deg' in location or 'longitude_deg' in location
    if ('airport' in location) == has_coords:
        raise ValueError('Location must specify either airport or both coordinates')
    flight = profile.get('flight', {})
    keys(flight, ('altitude_m', 'speed_m_s', 'wind_m_s', 'time_of_day', 'frozen', 'engine_running', 'glideslope_deg'), (), 'flight')
    flight = flight.copy()
    if overrides.get('altitude_m') is not None:
        flight['altitude_m'] = overrides['altitude_m']
    preset = root / 'config/rendering' / f"{profile['rendering']}.fgfsrc"
    # Flatten the native one-option-per-line file for an exact, portable run record.
    options = [line.strip() for line in preset.read_text().splitlines()
               if line.strip() and not line.lstrip().startswith('#')]
    managed = ('--config', '--fg-', '--aircraft', '--airport', '--lat', '--lon', '--heading',
               '--altitude', '--in-air', '--on-ground', '--units-', '--vc', '--enable-freeze',
               '--disable-freeze', '--glideslope', '--prop:/sim/presets/')
    for option in options:
        if not option.startswith('--') or option.startswith(managed):
            raise ValueError(f'{preset}: invalid or profile-managed option {option!r}')
    aircraft_dirs = list(install['aircraft_dirs'])
    livery_overlay = None
    if 'livery' in profile:
        livery_overlay = str((root / 'test-results/liveries' / uuid.uuid4().hex).resolve())
        aircraft_dirs.insert(0, livery_overlay)
    command = [install['binary'], '--launcher=false', '--ignore-autosave', '--no-default-config',
               '--disable-sentry', '--units-meters', f"--fg-root={install['fg_root']}",
               f"--fg-aircraft={os.pathsep.join(aircraft_dirs)}", f"--aircraft={profile['aircraft']}"]
    if 'scenery' in install:
        command.append(f"--terrasync-dir={install['scenery']}")
    command.extend(options)
    if 'livery' in profile:
        livery = profile['livery']
        livery_dir = build_livery.livery_directory(root, profile['aircraft'], livery).resolve()
        command.extend([f'--allow-nasal-read={livery_dir}',
                        f'--prop:/sim/model/livery/name={livery}',
                        f'--prop:/sim/model/livery/file={livery}',
                        f'--prop:/sim/model/livery/texture=Liveries/{livery}.png'])
    if 'initialisation' in profile:
        if profile['initialisation'] == '747-400-approach' and profile['aircraft'] != '747-400':
            raise ValueError('747-400-approach initialisation requires the 747-400 aircraft')
        state_file = root / 'config/aircraft' / f"{name(profile['initialisation'])}.xml"
        if not state_file.is_file():
            raise ValueError(f'Aircraft initialisation missing: {state_file}')
        command.append(f'--config={state_file}')
    if 'airport' in location:
        command.append(f"--airport={name(location['airport'])}")
    else:
        for key, flag, low, high in [('latitude_deg', 'lat', -90, 90), ('longitude_deg', 'lon', -180, 180)]:
            command.append(f'--{flag}={number(location.get(key), low, high, key)}')
    command.append(f"--heading={number(location['heading_deg'], 0, 360, 'heading_deg')}")
    ground = boolean(location['on_ground'], 'on_ground')
    command.append('--on-ground' if ground else '--in-air')
    if not ground and 'altitude_m' not in flight:
        raise ValueError('Airborne profiles require flight.altitude_m')
    if 'altitude_m' in flight:
        if ground:
            raise ValueError('altitude_m requires an airborne location')
        command.append(f"--altitude={number(flight['altitude_m'], -500, 100000, 'altitude_m')}")
    if 'speed_m_s' in flight:
        speed = number(flight['speed_m_s'], 0, 1000, 'speed_m_s')
        command.append(f'--vc={speed / (1852 / 3600):.8g}')  # --vc always uses knots.
    if 'glideslope_deg' in flight:
        if ground:
            raise ValueError('glideslope_deg requires an airborne location')
        command.append(f"--glideslope={number(flight['glideslope_deg'], -15, 15, 'glideslope_deg')}")
    if 'wind_m_s' in flight:
        wind = number(flight['wind_m_s'], 0, 150, 'wind_m_s')
        # Explicit fixed wind replaces preset weather, including METAR wind.
        command = [arg for arg in command if not arg.startswith(('--metar=', '--wind='))
                   and arg not in ('--enable-real-weather-fetch', '--disable-real-weather-fetch')]
        command.extend(['--disable-real-weather-fetch', f'--wind=0@{wind / (1852 / 3600):.8g}'])
    if 'time_of_day' in flight:
        tod = flight['time_of_day']
        if tod not in ('real', 'dawn', 'morning', 'noon', 'afternoon', 'dusk', 'evening', 'midnight'):
            raise ValueError('Invalid time_of_day')
        command = [arg for arg in command if not arg.startswith('--timeofday=')]
        command.append(f'--timeofday={tod}')
    if 'frozen' in flight:
        command.append('--enable-freeze' if boolean(flight['frozen'], 'frozen') else '--disable-freeze')
    if 'engine_running' in flight:
        command.append('--prop:/sim/presets/running=' + str(boolean(flight['engine_running'], 'engine_running')).lower())
    profile['flight'] = flight
    # Aircraft-specific initial state, kept separate from rendering presets.
    properties = profile.get('properties', {})
    if not isinstance(properties, dict):
        raise ValueError('properties must be a table')
    for path, value in properties.items():
        if not re.fullmatch(r'/(?:[a-zA-Z0-9_-]+(?:\[\d+\])?/)*[a-zA-Z0-9_-]+(?:\[\d+\])?', path):
            raise ValueError(f'Invalid property path: {path!r}')
        if path.startswith(('/sim/presets/', '/sim/freeze/')):
            raise ValueError(f'Use flight settings for {path}')
        if type(value) is bool:
            value = str(value).lower()
        elif type(value) in (int, float) and math.isfinite(value):
            value = str(value)
        else:
            raise ValueError(f'{path}: initial properties require finite numbers or booleans')
        command.append(f'--prop:{path}={value}')
    return {'profile_name': profile_name, 'profile': profile, 'installation': install,
            'location': location, 'command': command, 'livery_overlay': livery_overlay,
            'input_config': input_config}


def validate_assets(resolved):
    install = resolved['installation']
    binary = Path(install['binary'])
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise ValueError(f'FlightGear executable missing or not executable: {binary}')
    if not (Path(install['fg_root']) / 'defaults.xml').is_file():
        raise ValueError(f"FlightGear base data missing: {install['fg_root']}")
    aircraft = resolved['profile']['aircraft']
    if not any(next(Path(p).rglob(f'{aircraft}-set.xml'), None) for p in install['aircraft_dirs']):
        raise ValueError(f'Aircraft {aircraft!r} not found in configured aircraft_dirs')


def stop(process):
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


@contextmanager
def simulator(command, state, log, *, echo=False):
    """Own one simulator and its activation helper, including interrupt cleanup."""
    state.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.pop('FG_LAUNCHER', None)
    env['FG_HOME'] = str(state.resolve())
    process = activation = None
    relay = None
    previous = signal.getsignal(signal.SIGTERM)
    def terminate(signum, frame):
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, terminate)
    try:
        process = subprocess.Popen(command, env=env,
                                   stdout=subprocess.PIPE if echo else log,
                                   stderr=subprocess.STDOUT)
        if echo:
            def forward_output():
                # Keep the full log while surfacing diagnostics immediately, even
                # if FlightGear subsequently blocks on a graphical error dialog.
                for raw in iter(process.stdout.readline, b''):
                    line = raw.decode('utf-8', errors='replace')
                    log.write(line)
                    log.flush()
                    # WARN/ALRT include routine scenery, weather and renderer
                    # notices. Keep those in the log; surface explicit errors.
                    if re.search(r'\[(?:ERR|ERROR|FATAL)\]|^(?:fatal|error|startup failed|unknown command-line option|incompatible processor)\b', line.strip(), re.I):
                        print('FlightGear: ' + line.rstrip('\r\n'), file=sys.stderr, flush=True)
            relay = threading.Thread(target=forward_output, daemon=True)
            relay.start()
        if sys.platform == 'darwin':
            try:
                activation = subprocess.Popen(['/usr/bin/osascript', '-l', 'JavaScript', '-e', '''
ObjC.import('AppKit');
function run(argv) {
  var pid = Number(argv[0]);
  for (var attempt = 0; attempt < 40; attempt++) {
    var app = $.NSRunningApplication.runningApplicationWithProcessIdentifier(pid);
    if (app && !app.isNil()) {
      if (app.isTerminated) return;
      if (app.activateWithOptions(3)) return;
    }
    delay(0.25);
  }
  console.log('Automatic activation did not succeed; click FlightGear in the Dock.');
}''', str(process.pid)], stdout=log, stderr=subprocess.STDOUT)
            except OSError as exc:
                print(f'Could not activate FlightGear: {exc}; click its Dock icon.', file=sys.stderr)
        yield process
    finally:
        stop(process)
        if relay:
            relay.join(timeout=3)
            if not relay.is_alive():
                process.stdout.close()
        stop(activation)
        signal.signal(signal.SIGTERM, previous)


def run(resolved, root=None):
    root = ROOT if root is None else root
    validate_assets(resolved)
    build_livery.prepare(resolved, root=root)
    install = resolved['installation']
    if 'scenery' in install:
        Path(install['scenery']).mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    directory = root / 'test-results' / resolved['profile_name'] / stamp
    directory.mkdir(parents=True, exist_ok=False)
    # Per-run homes also prevent simultaneous flights sharing mutable state.
    state = directory / 'state' / resolved['profile']['installation']
    command = list(resolved['command'])
    input_config = resolved.get('input_config')
    if input_config:
        import socket
        from scripts import phone_control
        if input_config['port'] == 8080:
            raise ValueError('Phone HTTP port 8080 conflicts with FlightGear HTTP; use a separate port such as 8081.')
        try:
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                control_port = probe.getsockname()[1]
        except OSError as exc:
            raise ValueError(f'Cannot allocate the local FlightGear control socket (127.0.0.1): {exc}') from exc
        watchdog = directory / 'phone-watchdog.xml'
        phone_control.watchdog_xml(input_config, watchdog)
        # Keep Phi/property inspection separate from the phone/overlay server.
        # A localhost listener can steal traffic from a wildcard bind on macOS.
        command.extend(['--httpd=127.0.0.1:8080', f'--telnet=socket,bi,100,127.0.0.1,{control_port},tcp',
                        f'--config={watchdog.resolve()}'])
    record = dict(resolved, command=command, fg_home=str(state), started_at=stamp)
    (directory / 'launch.json').write_text(json.dumps(record, indent=2) + '\n')
    print(f"Starting {resolved['profile_name']}. Log: {directory / 'simulator.log'}", flush=True)
    if input_config:
        print('FlightGear web interface (this computer only): http://127.0.0.1:8080/', flush=True)
    if resolved.get('projection'):
        print('Projection: select an external view → View / Add Clone View; then return the main view to Captain.', flush=True)
    with (directory / 'simulator.log').open('w') as log:
        from contextlib import ExitStack
        with ExitStack() as stack:
            if input_config:
                phone_state = stack.enter_context(phone_control.running(input_config, control_port))
                if resolved.get('projection'):
                    from scripts.projection import open_projection
                    open_projection(phone_state.projection_url)
            process = stack.enter_context(simulator(command, state, log, echo=True))
            status = process.wait()
    if status != 0:
        print(f'FlightGear exited with {"signal " + str(-status) if status < 0 else "status " + str(status)}. '
              f'Log: {directory / "simulator.log"}', file=sys.stderr, flush=True)
        diagnostic_lines = (directory / 'simulator.log').read_text().strip().splitlines()
        if diagnostic_lines:
            print('Last FlightGear log lines:\n' + '\n'.join(diagnostic_lines[-20:]), file=sys.stderr, flush=True)
        else:
            print('FlightGear emitted no console diagnostics. Check its error popup; '
                  'this build can report startup errors only in a dialog.', file=sys.stderr, flush=True)
    return status if status >= 0 else 128 - status


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action')
    sub.add_parser('list', help='List saved profiles')
    launch = sub.add_parser('run', help='Run a saved profile')
    launch.add_argument('profile')
    for field in ('installation', 'location', 'rendering', 'aircraft', 'binary', 'fg-root'):
        launch.add_argument('--' + field)
    launch.add_argument('--altitude-m', type=float)
    launch.add_argument('--projection', action='store_true', help='Open OBS and the overlay preview; show extra-view setup guidance')
    launch.add_argument('--dry-run', action='store_true', help='Print resolved configuration without launching or checking installed assets')
    args = parser.parse_args(argv)
    try:
        if args.action in (None, 'list'):
            profiles = sorted((ROOT / 'profiles').glob('*.toml'))
            for index, path in enumerate(profiles, 1):
                profile = read(path)
                print(f"{index}. {path.stem}: {profile['description']}" + (' [experimental]' if profile.get('warning') else ''))
            if args.action == 'list':
                return 0
            if not sys.stdin.isatty():
                parser.error('Specify run PROFILE when not using an interactive terminal')
            choice = int(input('Choose a profile number: '))
            if not 1 <= choice <= len(profiles):
                raise ValueError('Profile number out of range')
            args = launch.parse_args([profiles[choice - 1].stem])
        resolved = resolve(args.profile, overrides=vars(args))
        if args.projection:
            resolved['projection'] = True
        if resolved['profile'].get('warning'):
            print(resolved['profile']['warning'], file=sys.stderr)
        if args.dry_run:
            print(json.dumps(resolved, indent=2))
            print('\nCommand: ' + shlex.join(resolved['command']))
            return 0
        return run(resolved)
    except (OSError, ValueError, EOFError) as exc:
        parser.error(str(exc))
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    sys.exit(main())
