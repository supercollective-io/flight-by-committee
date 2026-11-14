"""Install the standard crash-and-stress effects into a private 747 aircraft overlay."""
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
CONTACTS = ['NOSE', 'LEFT_WING', 'LEFT_BODY', 'RIGHT_BODY', 'RIGHT_WING',
            'NOSE_GROUND', 'LEFT_GROUND', 'RIGHT_GROUND', 'NOSE_TIP',
            'LEFT_WING_TIP', 'RIGHT_WING_TIP', 'TAIL_TIP']


def install(aircraft, *, root=ROOT):
    # Fail closed if another aircraft revision changes the contact mapping.
    contacts = ET.parse(aircraft / '747-400.xml').findall('./ground_reactions/contact')
    if [c.get('name') for c in contacts] != CONTACTS:
        raise ValueError('Crash trial requires the pinned 747-400 contact layout')
    assets = root / 'assets/crash-stress'
    target = aircraft / 'CommitteeCrash'
    shutil.copytree(assets, target)
    shutil.copyfile(root / 'config/aircraft/747-crash-stress.nas', target / 'adapter.nas')
    definition = aircraft / '747-400-set.xml'
    tree = ET.parse(definition)
    nasal = tree.find('nasal')
    if nasal is None:
        nasal = ET.SubElement(tree.getroot(), 'nasal')
    module = ET.SubElement(nasal, 'committee_crash')
    for filename in ('crash-and-stress.nas', 'adapter.nas'):
        ET.SubElement(module, 'file').text = f'Aircraft/747-400/CommitteeCrash/{filename}'
    tree.write(definition, encoding='utf-8', xml_declaration=True)
    sound_path = aircraft / 'Sounds/747-sound.xml'
    sounds = ET.parse(sound_path)
    fx = sounds.find('fx')
    if fx is None:
        raise ValueError('747 sound configuration has no fx section')
    for name, prop, loop in [('crash', 'crash', False), ('water-crash', 'water-crash', False),
                             ('explode', 'explode', False), ('wings-detach', 'detach', False),
                             ('crack', 'crack', False), ('creaking', 'creaking', True)]:
        sound = ET.SubElement(fx, 'committee-' + name)
        ET.SubElement(sound, 'name').text = 'committee-' + name
        ET.SubElement(sound, 'path').text = f'Aircraft/747-400/CommitteeCrash/aircraft-{name}.wav'
        ET.SubElement(sound, 'mode').text = 'looped' if loop else 'once'
        ET.SubElement(ET.SubElement(sound, 'condition'), 'property').text = f'damage/sounds/{prop}-on'
        volume = ET.SubElement(sound, 'volume')
        ET.SubElement(volume, 'factor').text = '1'
        if name in ('crack', 'creaking'):
            ET.SubElement(volume, 'property').text = f'damage/sounds/{prop}-volume'
    sounds.write(sound_path, encoding='utf-8', xml_declaration=True)
