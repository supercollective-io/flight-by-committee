"""OBS composition behaviour without requiring a running OBS instance."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from scripts.projection import configure, SCENE, OVERLAY


class ProjectionTests(unittest.TestCase):
    def client(self):
        client = Mock()
        client.get_input_list.return_value = SimpleNamespace(inputs=[{'inputName': 'FlightGear'}, {'inputName': OVERLAY}])
        client.get_video_settings.return_value = SimpleNamespace(base_width=1920, base_height=1080)
        client.get_scene_list.return_value = SimpleNamespace(scenes=[{'sceneName': SCENE}])
        client.get_scene_item_list.return_value = SimpleNamespace(scene_items=[{'sourceName': 'FlightGear', 'sceneItemId': 1}, {'sourceName': OVERLAY, 'sceneItemId': 2}])
        return client

    def test_refresh_reuses_sources_without_duplicate_items(self):
        client = self.client()
        configure(client, 'http://127.0.0.1:8080/projection?key=new', 'FlightGear')
        client.create_input.assert_not_called()
        client.create_scene_item.assert_not_called()
        self.assertEqual(client.set_input_settings.call_args.args[1]['url'], 'http://127.0.0.1:8080/projection?key=new')
        client.set_scene_item_index.assert_called_once_with(SCENE, 2, 1)
        client.open_video_mix_projector.assert_not_called()

    def test_missing_capture_does_not_mutate_scene(self):
        client = self.client()
        with self.assertRaises(ValueError):
            configure(client, 'url', 'Missing')
        client.create_scene.assert_not_called()
        client.set_input_settings.assert_not_called()

    def test_projection_opens_obs_and_current_overlay_on_mac(self):
        from unittest.mock import patch
        from scripts.projection import open_projection
        with patch('scripts.projection.sys.platform', 'darwin'), \
                patch('scripts.projection.subprocess.run', return_value=SimpleNamespace(returncode=0)) as run, \
                patch('builtins.print'):
            open_projection('http://127.0.0.1:8080/projection?key=current')
        self.assertEqual(run.call_args_list[0].args[0], ['open', '-a', 'OBS'])
        self.assertEqual(run.call_args_list[1].args[0], ['open', 'http://127.0.0.1:8080/projection?key=current'])
