import json
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

from scripts import preview_livery as preview


class LivePreviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def test_watch_rebuilds_and_keeps_last_good_texture_after_invalid_save(self):
        directory = self.root / 'assets/liveries/747-400'
        shutil.copytree(preview.ROOT / 'assets/liveries/747-400', directory)
        live = preview.LiveLivery('supercollective', root=self.root)
        live.refresh()
        original, revision = live.texture, live.state['revision']
        self.assertIsNone(live.state['error'])
        with patch.object(preview.build_livery, 'build') as build:
            live.refresh()
            build.assert_not_called()
        svg = directory / 'supercollective.svg'
        valid = svg.read_text()
        svg.write_text('<svg broken')
        live.refresh()
        self.assertIsNotNone(live.state['error'])
        self.assertEqual(live.texture, original)
        self.assertEqual(live.state['revision'], revision)
        svg.write_text(valid.replace('#ff512b', '#5b63d0'))
        live.refresh()
        self.assertIsNone(live.state['error'])
        self.assertNotEqual(live.state['revision'], revision)
        self.assertNotEqual(live.texture, original)
        svg.unlink()
        live.refresh()
        self.assertIsNotNone(live.state['error'])

    def test_file_routes_cannot_escape_their_allowed_directory(self):
        public = self.root / 'public'
        public.mkdir()
        (public / 'image.png').write_bytes(b'PNG')
        private = self.root / 'private.txt'
        private.write_text('private')
        (public / 'link').symlink_to(private)
        self.assertEqual(preview.safe_file(public, 'image.png'), public / 'image.png')
        for path in ('../private.txt', str(private), 'link', 'missing'):
            self.assertIsNone(preview.safe_file(public, path))

    def test_design_selection_is_per_request_and_unknown_names_are_rejected(self):
        original = preview.LiveLivery('original', root=self.root)
        alternative = preview.LiveLivery('alternative', root=self.root)
        original.texture, alternative.texture = b'original PNG', b'alternative PNG'
        catalogue = [{'name': name, 'label': name} for name in ('original', 'alternative')]
        handler = preview.handler_for(original, self.root, self.root, [], root=self.root,
                                      designs={'original': original, 'alternative': alternative},
                                      catalogue=catalogue)
        server = preview.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            base = f'http://127.0.0.1:{server.server_port}'
            with urlopen(base + '/state?livery=alternative') as response:
                state = json.load(response)
            self.assertEqual(state['name'], 'alternative')
            self.assertEqual(state['designs'], catalogue)
            for query, expected in [('?livery=alternative', alternative.texture), ('', original.texture)]:
                with urlopen(base + '/texture.png' + query) as response:
                    self.assertEqual(response.read(), expected)
            for endpoint in ('state', 'texture.png'):
                with self.assertRaises(HTTPError) as error:
                    urlopen(base + '/' + endpoint + '?livery=../missing')
                self.assertEqual(error.exception.code, 404)
            self.assertEqual(original.state['name'], 'original')
        finally:
            server.shutdown()
            server.server_close()
            worker.join()

    def test_catalogue_requires_svg_and_xml_and_supports_optional_labels(self):
        for name in ('one.svg', 'one.xml', 'two.svg', 'two.xml', 'incomplete.svg'):
            (self.root / name).touch()
        (self.root / 'designs.json').write_text(json.dumps([
            {'name': 'one', 'label': 'First design', 'description': 'A description'}]))
        catalogue = preview.design_catalogue(self.root)
        self.assertEqual([item['name'] for item in catalogue], ['one', 'two'])
        self.assertEqual(catalogue[0]['label'], 'First design')
        self.assertEqual(catalogue[1]['label'], 'two')

    def test_conversion_preserves_uvs_and_reads_engine_placements(self):
        aircraft = self.root / '747-400'
        models = aircraft / 'Models'
        models.mkdir(parents=True)
        for stem in preview.MESHES:
            (models / f'{stem}.ac').write_text('AC3Db\nMATERIAL "rubber" rgb 0 0 0 amb 0 0 0 emis 0 0 0 spec 0 0 0 shi 0 trans 0\n')
        (models / '747-400_wings.xml').write_text('<PropertyList>' + ''.join(
            f'<model><path>Aircraft/747-400/Models/GE_CF6-80C2B1F.xml</path><offsets>'
            f'<x-m>{x}</x-m><y-m>{y}</y-m><z-m>-2</z-m></offsets></model>'
            for x, y in [(4, -21), (-2, -13), (-2, 13), (4, 21)]) + '</PropertyList>')
        def export(command, **_):
            Path(command[3]).write_text(json.dumps({
                'images': [{'uri': 'BOE.png'}, {'uri': 'other.png'}],
                'textures': [{'source': 0}, {'source': 1}],
                'materials': [{'name': 'paint', 'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}}},
                              {'name': 'rubber'}],
                'meshes': [{'primitives': [{'attributes': {'POSITION': 0, 'TEXCOORD_0': 1}}]}],
                'accessors': [{'min': [0, 0, 0]}, {'min': [.1, .2], 'max': [.8, .9]}],
            }))
            return type('Result', (), {'returncode': 0})()
        cache = self.root / 'converted'
        with patch.object(preview.shutil, 'which', return_value='/assimp'), patch.object(preview.subprocess, 'run', side_effect=export) as run:
            parts = preview.convert_models(aircraft, cache)
            self.assertEqual(run.call_count, 4)
            preview.convert_models(aircraft, cache)
            self.assertEqual(run.call_count, 4, 'Unchanged geometry should use the cache')
        self.assertEqual([p['position'] for p in parts if p['name'] == 'engine'],
                         [[4, -2, 21], [-2, -2, 13], [-2, -2, -13], [4, -2, -21]])
        converted = json.loads((cache / '747-400_fuselage.gltf').read_text())
        self.assertEqual(converted['images'][0]['uri'], '/texture.png')
        self.assertEqual(converted['images'][1]['uri'], '/aircraft/Models/other.png')
        self.assertTrue(converted['materials'][0]['extras']['livery'])
        self.assertEqual(converted['materials'][1]['pbrMetallicRoughness']['baseColorFactor'], [0, 0, 0, 1])
        self.assertEqual(converted['accessors'][1]['min'], [.1, .2])
        self.assertEqual(converted['meshes'][0]['primitives'][0]['attributes']['TEXCOORD_0'], 1)
