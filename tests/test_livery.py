from pathlib import Path
import shutil
import struct
import tempfile
import unittest
from unittest.mock import patch

from scripts import build_livery as livery
from scripts import flightgear


class LiveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.assets = self.root / 'assets/liveries/747-400'
        shutil.copytree(livery.ROOT / 'assets/liveries/747-400', self.assets)
        # Match a fresh checkout: generated livery textures are not tracked.
        for output in self.assets.glob("*.png"):
            output.unlink()
        self.aircraft = self.root / 'installed/747-400'
        self.destination = self.aircraft / 'Models/Liveries'
        self.destination.mkdir(parents=True)
        (self.aircraft / '747-400-set.xml').write_text('<PropertyList/>')
        (self.aircraft / 'Models/BOE.png').write_bytes(b'original texture')
        (self.aircraft / 'Models/model.ac').write_text('texture \"BOE.png\"')
        self.resolved = {'profile': {'aircraft': '747-400', 'livery': 'supercollective'},
                         'installation': {'aircraft_dirs': [str(self.root / 'installed')]},
                         'livery_overlay': str(self.root / 'test-results/overlay')}
        self.overlay = Path(self.resolved['livery_overlay'])
        self.overlay_aircraft = self.overlay / '747-400'

    def test_build_is_reproducible_and_links_follow_rebuilds(self):
        livery.prepare(self.resolved, root=self.root)
        output = self.assets / 'supercollective.png'
        first = output.read_bytes()
        self.assertEqual(struct.unpack('>II', first[16:24]), (8192, 2048))
        modified = output.stat().st_mtime_ns
        livery.prepare(self.resolved, root=self.root)
        self.assertEqual(output.stat().st_mtime_ns, modified)
        for extension in ('png', 'xml'):
            link = self.overlay_aircraft / 'Models/Liveries' / f'supercollective.{extension}'
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.resolve(), self.assets / link.name)
        svg = self.assets / 'supercollective.svg'
        svg.write_text(svg.read_text().replace('#ff512b', '#00aaee'))
        livery.prepare(self.resolved, root=self.root)
        self.assertNotEqual(first, output.read_bytes())
        self.assertEqual((self.overlay_aircraft / 'Models/BOE.png').read_bytes(), output.read_bytes())

    def test_overlay_preserves_installed_aircraft_and_uses_local_model_files(self):
        conflict = self.destination / 'supercollective.xml'
        conflict.write_text('user-owned')
        livery.prepare(self.resolved, root=self.root)
        self.assertEqual(conflict.read_text(), 'user-owned')
        self.assertEqual((self.aircraft / 'Models/BOE.png').read_bytes(), b'original texture')
        copied_model = self.overlay_aircraft / 'Models/model.ac'
        self.assertFalse(copied_model.is_symlink())
        self.assertEqual(copied_model.read_text(), 'texture "BOE.png"')
        self.assertEqual((self.overlay_aircraft / 'Models/BOE.png').resolve(),
                         self.assets / 'supercollective.png')

    def test_unmanaged_overlay_is_not_overwritten(self):
        self.overlay.mkdir(parents=True)
        sentinel = self.overlay / 'user-owned'
        sentinel.write_text('preserve')
        with patch.object(livery, 'build') as build:
            with self.assertRaisesRegex(ValueError, 'unmanaged'):
                livery.prepare(self.resolved, root=self.root)
            build.assert_not_called()
        self.assertEqual(sentinel.read_text(), 'preserve')

    def test_bad_inputs_fail_before_installing(self):
        for aircraft, name in [('c172p', 'supercollective'), ('747-400', '../escape'), ('747-400', True)]:
            with self.subTest(aircraft=aircraft, name=name), self.assertRaises(ValueError):
                livery.livery_directory(self.root, aircraft, name)
        svg = self.assets / 'supercollective.svg'
        svg.write_text('<svg viewBox="0 0 1 1"/>')
        with self.assertRaisesRegex(ValueError, 'viewBox'):
            livery.prepare(self.resolved, root=self.root)
        self.assertEqual(list(self.destination.iterdir()), [])
        self.assertFalse(self.overlay.exists())

    def test_missing_definition_and_artwork_are_clear_errors(self):
        source = self.assets / 'supercollective.svg'
        source.unlink()
        with self.assertRaisesRegex(ValueError, 'asset missing'):
            livery.prepare(self.resolved, root=self.root)
        (self.assets / 'supercollective.xml').unlink()
        with self.assertRaisesRegex(ValueError, 'definition missing'):
            livery.prepare(self.resolved, root=self.root)

    def test_profile_resolution_selects_livery_without_installing(self):
        with patch.object(livery, 'prepare') as prepare:
            resolved = flightgear.resolve('karlsruhe-747-landing')
            prepare.assert_not_called()
        search = next(arg for arg in resolved['command'] if arg.startswith('--fg-aircraft='))
        self.assertTrue(search.startswith('--fg-aircraft=' + resolved['livery_overlay'] + ':'))
        self.assertFalse(Path(resolved['livery_overlay']).exists())
        for property, value in [('name', 'supercollective'), ('file', 'supercollective'),
                                ('texture', 'Liveries/supercollective.png')]:
            self.assertIn(f'--prop:/sim/model/livery/{property}={value}', resolved['command'])
        self.assertIn(f'--allow-nasal-read={livery.ROOT / "assets/liveries/747-400"}', resolved['command'])

    def test_profiles_without_livery_need_no_assets(self):
        self.resolved['profile'].pop('livery')
        shutil.rmtree(self.assets)
        livery.prepare(self.resolved, root=self.root)
        self.assertEqual(list(self.destination.iterdir()), [])
        self.assertFalse(self.overlay.exists())
