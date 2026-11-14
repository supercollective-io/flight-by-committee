from pathlib import Path
import tempfile
import shutil
from unittest.mock import patch
import unittest
import xml.etree.ElementTree as ET

from scripts import crash_stress, flightgear, build_livery


class CrashStressTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.aircraft = Path(self.tmp.name) / 'installed/747-400'
        (self.aircraft / 'Sounds').mkdir(parents=True)
        model = ET.Element('fdm_config')
        ground = ET.SubElement(model, 'ground_reactions')
        for name in crash_stress.CONTACTS:
            ET.SubElement(ground, 'contact', name=name)
        ET.ElementTree(model).write(self.aircraft / '747-400.xml')
        (self.aircraft / '747-400-set.xml').write_text('<PropertyList><nasal><existing/></nasal></PropertyList>')
        (self.aircraft / 'Sounds/747-sound.xml').write_text('<PropertyList><fx><existing/></fx></PropertyList>')

    def test_installs_bundled_code_and_every_referenced_sound(self):
        crash_stress.install(self.aircraft)
        definition = ET.parse(self.aircraft / '747-400-set.xml')
        self.assertIsNotNone(definition.find('./nasal/existing'))
        files = definition.findall('./nasal/committee_crash/file')
        self.assertEqual(len(files), 2)
        sounds = ET.parse(self.aircraft / 'Sounds/747-sound.xml')
        self.assertIsNotNone(sounds.find('./fx/existing'))
        paths = [f.text for f in files] + [p.text for p in sounds.findall('./fx/*/path')]
        self.assertEqual(len(paths), 8)
        for path in paths:
            self.assertTrue((self.aircraft / path.removeprefix('Aircraft/747-400/')).is_file(), path)
        self.assertEqual((self.aircraft / 'CommitteeCrash/crash-and-stress.nas').read_bytes(),
                         (crash_stress.ROOT / 'assets/crash-stress/crash-and-stress.nas').read_bytes())

    def test_rejects_changed_contact_mapping_before_writing(self):
        model = self.aircraft / '747-400.xml'
        model.write_text(model.read_text().replace('NOSE_GROUND', 'CHANGED'))
        with self.assertRaisesRegex(ValueError, 'contact layout'):
            crash_stress.install(self.aircraft)
        self.assertFalse((self.aircraft / 'CommitteeCrash').exists())

    def test_existing_and_future_747_profiles_get_overlay(self):
        for name in ('karlsruhe-747-crash-trial', 'karlsruhe-747-landing'):
            self.assertIsNotNone(flightgear.resolve(name)['livery_overlay'])
        root = self.aircraft / 'repo'
        for directory in ('config', 'profiles'):
            shutil.copytree(flightgear.ROOT / directory, root / directory)
        profile = root / 'profiles/new-ground-747.toml'
        profile.write_text('description = "New plain 747"\ninstallation = "nightly"\n'
                           'aircraft = "747-400"\nlocation = "schiphol-ground"\n'
                           'rendering = "ws3-hdr"\n')
        result = flightgear.resolve('new-ground-747', root=root)
        self.assertIsNotNone(result['livery_overlay'])
        self.assertNotIn('livery', result['profile'])
        self.assertNotIn('initialisation', result['profile'])
        self.assertIn(result['livery_overlay'], next(c for c in result['command'] if c.startswith('--fg-aircraft=')))
        self.assertIsNone(flightgear.resolve('new-ground-747', root=root,
                                           overrides={'aircraft': 'ufo'})['livery_overlay'])

    def test_plain_747_overlay_installs_damage_without_changing_source(self):
        original = (self.aircraft / '747-400-set.xml').read_bytes()
        overlay = Path(self.tmp.name) / 'overlay'
        resolved = {'profile': {'aircraft': '747-400'},
                    'installation': {'aircraft_dirs': [str(self.aircraft)]},
                    'livery_overlay': str(overlay)}
        with patch.object(build_livery, 'build') as build:
            build_livery.prepare(resolved)
            build.assert_not_called()
        installed = overlay / '747-400'
        self.assertTrue((installed / 'CommitteeCrash/adapter.nas').is_file())
        self.assertIsNotNone(ET.parse(installed / '747-400-set.xml').find('./nasal/committee_crash'))
        self.assertEqual((self.aircraft / '747-400-set.xml').read_bytes(), original)
        self.assertFalse((self.aircraft / 'CommitteeCrash').exists())
