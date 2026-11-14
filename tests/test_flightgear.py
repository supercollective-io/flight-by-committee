import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts import flightgear as fg
from scripts import flightgear_test as harness


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        for directory in ('profiles', 'config'):
            shutil.copytree(fg.ROOT / directory, self.root / directory)
        (self.root / 'config/installations.local.toml').unlink(missing_ok=True)

    def resolve(self, profile='amsterdam-explore', **overrides):
        return fg.resolve(profile, root=self.root, overrides=overrides)

    def test_all_profiles_resolve_without_assets(self):
        for path in (self.root / 'profiles').glob('*.toml'):
            result = self.resolve(path.stem)
            self.assertIn('--no-default-config', result['command'])
            self.assertIn('--enable-sound', result['command'])
            self.assertIn('--prop:/sim/sound/switch=true', result['command'])
        self.assertFalse((self.root / 'test-results').exists())

    def test_amsterdam_retains_scenery_and_airborne_workaround(self):
        command = self.resolve()['command']
        for arg in ('--lat=52.3086', '--lon=4.7639', '--altitude=600', '--in-air',
                    '--prop:/scenery/use-vpb=true', '--prop:/sim/rendering/osm-buildings=true',
                    '--prop:/sim/rendering/scenery-path-suffix[1]/enabled=false', '--aircraft=ufo'):
            self.assertIn(arg, command)
        self.assertNotIn('--on-ground', command)
        self.assertEqual(sum(a.startswith('--timeofday=') for a in command), 1)

    def test_amsterdam_flight_is_paused_calm_and_explicitly_unvalidated(self):
        resolved = self.resolve('amsterdam-flight')
        command = resolved['command']
        for option in ('--aircraft=c172p', '--altitude=1000', '--enable-freeze',
                       '--prop:/sim/presets/running=true', '--wind=0@0',
                       '--disable-real-weather-fetch', '--in-air'):
            self.assertIn(option, command)
        self.assertFalse(any(arg.startswith('--metar=') for arg in command))
        self.assertIn('Experimental', resolved['profile']['warning'])

    def test_takeoff_phone_controls_wait_for_ground_start_not_approach(self):
        resolved = self.resolve('karlsruhe-747-takeoff')
        config = resolved['input_config']
        self.assertEqual(resolved['profile']['input'], 'phone-takeoff')
        self.assertEqual(config['mode'], 'phone')
        self.assertEqual(config['ready_property'], '/sim/signals/fdm-initialized')
        self.assertIn('/controls/gear/brake-parking', config['brake_release_paths'])
        self.assertEqual(len(config['controls']['throttle']['paths']), 4)
        self.assertIn('--on-ground', resolved['command'])
        self.assertNotIn('initialisation', resolved['profile'])

    def test_overrides_replace_instead_of_duplicate(self):
        result = self.resolve(aircraft='c172p', installation='stable', altitude_m=1200)
        self.assertEqual([a for a in result['command'] if a.startswith('--aircraft=')], ['--aircraft=c172p'])
        self.assertEqual([a for a in result['command'] if a.startswith('--altitude=')], ['--altitude=1200'])
        self.assertEqual(result['profile']['installation'], 'stable')

    def test_invalid_values_rejected(self):
        for overrides in ({'aircraft': '../escape'}, {'altitude_m': float('nan')}, {'location': 'schiphol-ground'}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.resolve(**overrides)
        path = self.root / 'profiles/amsterdam-explore.toml'
        path.write_text(path.read_text().replace('altitude_m', 'altitdue_m'))
        with self.assertRaisesRegex(ValueError, 'unknown keys'):
            self.resolve()

    def test_ambiguous_location_rejected(self):
        path = self.root / 'config/locations/schiphol-airborne.toml'
        path.write_text(path.read_text() + '\nairport = "EHAM"\n')
        with self.assertRaisesRegex(ValueError, 'either airport'):
            self.resolve()

    def test_rendering_cannot_override_aircraft_or_include_hidden_config(self):
        path = self.root / 'config/rendering/ws3-hdr.fgfsrc'
        for option in ('--aircraft=other', '--config=/tmp/hidden'):
            path.write_text(option)
            with self.assertRaisesRegex(ValueError, 'profile-managed'):
                self.resolve()

    def test_installation_paths_relative_to_config_file(self):
        (self.root / 'config/installations.local.toml').write_text(
            '[nightly]\nbinary="app with spaces"\nfg_root="data"\naircraft_dirs=["planes"]\n')
        resolved = self.resolve()
        self.assertEqual(resolved['command'][0], str(self.root / 'config/app with spaces'))
        self.assertEqual(resolved['installation']['aircraft_dirs'], [str(self.root / 'config/planes')])

    def test_asset_validation_and_separate_aircraft_installation(self):
        binary = self.root / 'fake-fg'
        binary.write_text('#!/bin/sh\nexit 0\n')
        binary.chmod(0o755)
        data = self.root / 'data'
        data.mkdir()
        (data / 'defaults.xml').touch()
        result = self.resolve(binary=str(binary), fg_root=str(data))
        with self.assertRaisesRegex(ValueError, 'Aircraft'):
            fg.validate_assets(result)
        plane = data / 'Aircraft/ufo/ufo-set.xml'
        plane.parent.mkdir(parents=True)
        plane.touch()
        fg.validate_assets(result)

    def test_cli_dry_run(self):
        with patch.object(fg, 'ROOT', self.root), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(fg.main(['run', 'schiphol-inspect', '--dry-run']), 0)
            self.assertIn('--on-ground', out.getvalue())

    def test_default_launch_opens_operator_without_terminal_input(self):
        with patch.object(fg, 'ROOT', self.root), patch('scripts.local_operator.serve', return_value=0) as serve:
            self.assertEqual(fg.main([]), 0)
            serve.assert_called_once_with(root=self.root, port=0, open_browser=True)
            serve.reset_mock()
            self.assertEqual(fg.main(['operator', '--no-browser', '--port', '8765']), 0)
            serve.assert_called_once_with(root=self.root, port=8765, open_browser=False)

    def test_feasibility_rejects_edited_scenario(self):
        resolved = self.resolve('feasibility')
        resolved['profile']['aircraft'] = 'ufo'
        with patch.object(fg, 'resolve', return_value=resolved), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                harness.main(['--dry-run'])
            self.assertEqual(error.exception.code, 2)

    def test_run_records_command_log_and_isolated_state(self):
        resolved = self.resolve('schiphol-inspect')
        resolved['command'] = [sys.executable, '-c', 'import os; print(os.environ["FG_HOME"])']
        resolved['installation'].pop('scenery', None)
        with patch.object(fg, 'validate_assets'), patch.object(fg.sys, 'platform', 'linux'), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(fg.run(resolved, self.root), 0)
        record_path = next((self.root / 'test-results').rglob('launch.json'))
        record = json.loads(record_path.read_text())
        self.assertEqual(record['command'], resolved['command'])
        self.assertTrue(record['fg_home'].endswith('state/nightly'))
        self.assertIn(record['fg_home'], record_path.with_name('simulator.log').read_text())


class LifecycleTests(unittest.TestCase):
    def test_interrupt_cleans_up_owned_simulator_and_activation(self):
        process, activation = Mock(pid=123), Mock()
        process.poll.return_value = activation.poll.return_value = None
        with tempfile.TemporaryDirectory() as directory, patch.object(fg.sys, 'platform', 'darwin'), \
                patch.object(fg.subprocess, 'Popen', side_effect=[process, activation]) as popen, \
                patch.dict(os.environ, {'FG_LAUNCHER': 'old'}):
            previous = signal.getsignal(signal.SIGTERM)
            with self.assertRaises(KeyboardInterrupt):
                with fg.simulator(['fake'], Path(directory) / 'state', None):
                    raise KeyboardInterrupt
            process.terminate.assert_called_once()
            activation.terminate.assert_called_once()
            self.assertIs(signal.getsignal(signal.SIGTERM), previous)
            self.assertNotIn('FG_LAUNCHER', popen.call_args_list[0].kwargs['env'])
            self.assertEqual(popen.call_args_list[1].args[0][-1], '123')

    def test_unresponsive_process_is_killed(self):
        process = Mock()
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired('fake', 10), 0]
        fg.stop(process)
        process.kill.assert_called_once()

class LandingProfileTests(unittest.TestCase):
    def test_nightly_approach_has_four_throttles_and_metric_fuel(self):
        resolved = fg.resolve('karlsruhe-747-landing')
        self.assertIn('--glideslope=-3.0', resolved['command'])
        self.assertEqual(resolved['profile']['installation'], 'nightly')
        self.assertEqual(resolved['profile']['aircraft'], '747-400')
        self.assertIn('--compositor=Compositor/HDR/hdr', resolved['command'])
        self.assertIn('--prop:/scenery/use-vpb=true', resolved['command'])
        props = resolved['profile']['properties']
        self.assertEqual(sum(v for p, v in props.items() if p.endswith('/level-kg')), 20000)
        self.assertEqual(sum(p.endswith('/throttle') for p in props), 4)
        self.assertIn('--prop:/controls/flight/flaps=1.0', resolved['command'])
        self.assertNotIn('--metar=', ' '.join(resolved['command']))

    def test_invalid_initial_properties_are_rejected(self):
        for suffix in ('"/bad path" = 1', '"/controls/test" = nan',
                       '"/controls/test" = "unexpected"', '"/sim/freeze/master" = false'):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                shutil.copytree(fg.ROOT / 'profiles', root / 'profiles')
                shutil.copytree(fg.ROOT / 'config', root / 'config')
                p = root / 'profiles/feasibility.toml'
                p.write_text(p.read_text() + '\n[properties]\n' + suffix + '\n')
                with self.assertRaises(ValueError):
                    fg.resolve('feasibility', root=root)

class AircraftInstallerTests(unittest.TestCase):
    def test_rejects_changed_archive_and_preserves_existing_aircraft(self):
        from scripts import install_747
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            with patch.object(install_747.urllib.request, 'urlopen', return_value=io.BytesIO(b'changed')):
                with self.assertRaisesRegex(ValueError, 'differs'):
                    install_747.install(destination)
            self.assertFalse((destination / '747-400').exists())
            (destination / '747-400').mkdir()
            with patch.object(install_747.urllib.request, 'urlopen') as download:
                with self.assertRaisesRegex(ValueError, 'already exists'):
                    install_747.install(destination)
                download.assert_not_called()

class ProjectionLaunchRegressionTests(unittest.TestCase):
    def test_projection_does_not_pass_removed_nightly_option(self):
        with patch.object(fg, 'run', return_value=0) as run, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(fg.main(['run', 'karlsruhe-747-landing', '--projection']), 0)
        resolved = run.call_args.args[0]
        self.assertTrue(resolved['projection'])
        self.assertNotIn('--enable-composite-viewer', resolved['command'])

    def test_simulator_diagnostics_reach_terminal_and_log(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(fg.sys, 'platform', 'linux'):
            output = io.StringIO()
            path = Path(directory) / 'simulator.log'
            with path.open('w') as log, contextlib.redirect_stderr(output):
                with fg.simulator([sys.executable, '-c',
                                   'import sys; print("startup failed", file=sys.stderr); sys.exit(2)'],
                                  Path(directory) / 'state', log, echo=True) as process:
                    self.assertEqual(process.wait(timeout=5), 2)
            self.assertIn('FlightGear: startup failed', output.getvalue())
            self.assertIn('startup failed', path.read_text())

    def test_silent_failure_is_reported_with_popup_guidance(self):
        resolved = fg.resolve('schiphol-inspect')
        resolved['command'] = [sys.executable, '-c', 'import sys; sys.exit(2)']
        resolved['installation'].pop('scenery', None)
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(fg, 'validate_assets'), patch.object(fg.build_livery, 'prepare'), \
                patch.object(fg.sys, 'platform', 'linux'), \
                contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()) as output:
            self.assertEqual(fg.run(resolved, Path(directory)), 2)
        self.assertIn('FlightGear exited with status 2', output.getvalue())
        self.assertIn('no console diagnostics', output.getvalue())
        self.assertIn('error popup', output.getvalue())

    def test_phone_launch_keeps_flightgear_http_on_a_separate_port(self):
        from scripts import phone_control
        from unittest.mock import MagicMock
        resolved = fg.resolve('karlsruhe-747-landing')
        resolved['installation'].pop('scenery', None)
        process = Mock()
        process.wait.return_value = 0
        simulator_context = MagicMock()
        simulator_context.__enter__.return_value = process
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(fg, 'validate_assets'), patch.object(fg.build_livery, 'prepare'), \
                patch.object(phone_control, 'running', return_value=MagicMock()), \
                patch('socket.socket') as socket_factory, \
                patch.object(fg, 'simulator', return_value=simulator_context) as simulator, \
                contextlib.redirect_stdout(io.StringIO()):
            socket_factory.return_value.__enter__.return_value.getsockname.return_value = ('127.0.0.1', 12345)
            self.assertEqual(fg.run(resolved, Path(directory)), 0)
        command = simulator.call_args.args[0]
        self.assertIn('--httpd=127.0.0.1:8080', command)
        self.assertNotIn('--disable-httpd', command)
        self.assertEqual(resolved['input_config']['port'], 8081)
        self.assertTrue(any(arg.startswith('--telnet=') for arg in command))

    def test_routine_simulator_output_stays_in_log(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(fg.sys, 'platform', 'linux'):
            output = io.StringIO()
            path = Path(directory) / 'simulator.log'
            with path.open('w') as log, contextlib.redirect_stderr(output):
                with fg.simulator([sys.executable, '-c',
                                   'print("[WARN]: weather notice"); print("[ALRT]: particles disabled"); print("[ERROR]: genuine fault")'],
                                  Path(directory) / 'state', log, echo=True) as process:
                    self.assertEqual(process.wait(timeout=5), 0)
            self.assertNotIn('weather notice', output.getvalue())
            self.assertNotIn('particles disabled', output.getvalue())
            self.assertIn('genuine fault', output.getvalue())
            self.assertIn('weather notice', path.read_text())
            self.assertIn('particles disabled', path.read_text())
