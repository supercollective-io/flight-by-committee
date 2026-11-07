"""Render a repository SVG livery: uv run python -m scripts.build_livery."""
import argparse
import os
from pathlib import Path
import re
import shutil
import struct
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
# Supersample the fixed UV layout for readable lettering at close camera distances.
TEXTURE_SIZE = (8192, 2048)


def livery_directory(root, aircraft, name):
    if aircraft != '747-400':
        raise ValueError('Repository liveries currently support only the 747-400')
    if not isinstance(name, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]*', name):
        raise ValueError(f'Invalid livery name: {name!r}')
    return Path(root) / 'assets/liveries' / aircraft


def build(name='supercollective', *, root=ROOT, aircraft='747-400'):
    import resvg_py

    directory = livery_directory(root, aircraft, name)
    source = directory / f'{name}.svg'
    output = directory / f'{name}.png'
    font = directory / 'fonts/Montserrat.ttf'
    details = directory / 'details/airframe.png'
    for path in (source, font, details, directory / 'details/construction.png'):
        if not path.is_file():
            raise ValueError(f'Livery asset missing: {path}')
    if output.is_symlink():
        raise ValueError(f'Refusing to overwrite linked build output: {output}')
    try:
        svg = ET.parse(source).getroot()
    except ET.ParseError as exc:
        raise ValueError(f'Invalid livery SVG: {source}: {exc}') from exc
    if svg.get('viewBox') != '0 0 4096 1024':
        raise ValueError('Livery SVG must use viewBox="0 0 4096 1024"')
    data = resvg_py.svg_to_bytes(
        svg_path=str(source), resources_dir=str(directory),
        width=TEXTURE_SIZE[0], height=TEXTURE_SIZE[1], skip_system_fonts=True,
        font_files=[str(font)], font_family='Montserrat',
    )
    if data[:8] != b'\x89PNG\r\n\x1a\n' or struct.unpack('>II', data[16:24]) != TEXTURE_SIZE:
        raise ValueError('Renderer did not produce an 8192 × 2048 PNG')
    # Avoid changing the file when a rebuild produces identical artwork.
    if output.is_file() and output.read_bytes() == data:
        return output
    with tempfile.NamedTemporaryFile(dir=directory, suffix='.png', delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(data)
    try:
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return output


def prepare(resolved, *, root=ROOT):
    """Build a private aircraft overlay without modifying the installed aircraft."""
    profile = resolved['profile']
    if 'livery' not in profile:
        return
    name, aircraft = profile['livery'], profile['aircraft']
    directory = livery_directory(root, aircraft, name).resolve()
    definition = directory / f'{name}.xml'
    if not definition.is_file():
        raise ValueError(f'Livery definition missing: {definition}')
    try:
        tree = ET.parse(definition)
    except ET.ParseError as exc:
        raise ValueError(f'Invalid livery definition: {definition}') from exc
    if (tree.findtext('./sim/model/livery/name') != name or
            tree.findtext('./sim/model/livery/texture') != f'Liveries/{name}.png'):
        raise ValueError(f'Livery definition must name {name} and use Liveries/{name}.png')
    aircraft_set = next((match for parent in resolved['installation']['aircraft_dirs']
                         for match in sorted(Path(parent).rglob(f'{aircraft}-set.xml'))), None)
    if aircraft_set is None:
        raise ValueError(f'Aircraft {aircraft!r} not found in configured aircraft_dirs')
    source_aircraft = aircraft_set.parent.resolve()
    if not (source_aircraft / 'Models/BOE.png').is_file():
        raise ValueError(f'Aircraft has no expected 747 base texture: {source_aircraft}')
    overlay = Path(resolved['livery_overlay'])
    marker_text = str(source_aircraft) + '\n' + name + '\n'
    marker = overlay / '.committee-livery'
    if overlay.exists() and (not marker.is_file() or marker.read_text() != marker_text):
        raise ValueError(f'Refusing to replace an unmanaged livery overlay: {overlay}')
    build(name, root=root, aircraft=aircraft)
    if overlay.exists():
        return
    overlay.parent.mkdir(parents=True, exist_ok=True)

    def copy_asset(source, destination):
        # Keep model paths inside the overlay; heavy textures and sounds stay linked.
        if Path(source).suffix.lower() in ('.xml', '.ac'):
            shutil.copyfile(source, destination)
        else:
            Path(destination).symlink_to(Path(source).resolve())

    with tempfile.TemporaryDirectory(dir=overlay.parent) as temporary:
        staged = Path(temporary) / 'overlay'
        aircraft_copy = staged / aircraft
        shutil.copytree(source_aircraft, aircraft_copy, copy_function=copy_asset)
        # HDR ignores this legacy aircraft's material texture animation. Supply
        # the chosen livery as the AC3D base texture before the model is loaded.
        base_texture = aircraft_copy / 'Models/BOE.png'
        base_texture.unlink()
        base_texture.symlink_to(directory / f'{name}.png')
        for extension in ('png', 'xml'):
            target = aircraft_copy / 'Models/Liveries' / f'{name}.{extension}'
            target.unlink(missing_ok=True)
            target.symlink_to(directory / f'{name}.{extension}')
        (staged / '.committee-livery').write_text(marker_text)
        staged.rename(overlay)



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name', nargs='?', default='supercollective')
    args = parser.parse_args()
    try:
        print(build(args.name))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
