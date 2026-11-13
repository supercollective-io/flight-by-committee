"""Tests for the camera worker's dependency-free frame handling."""

import builtins
import importlib
import sys
import threading
import types
import unittest
from unittest.mock import patch

from scripts import body_camera


class LatestFrameTests(unittest.TestCase):
    def test_publish_replaces_unconsumed_frame(self):
        frames = body_camera.LatestFrame()
        frames.publish('first', 1.0)
        frames.publish('latest', 2.0)
        frame = frames.take(timeout=0)
        self.assertEqual((frame.image, frame.captured), ('latest', 2.0))
        self.assertIsNone(frames.take(timeout=0))

    def test_frame_timestamp_freshness(self):
        frame = body_camera.CapturedFrame('image', 10.0)
        self.assertTrue(body_camera.is_fresh(frame, 10.5))
        self.assertFalse(body_camera.is_fresh(frame, 10.5001))
        self.assertFalse(body_camera.is_fresh(frame, 9.9))

    def test_capture_stamps_before_read_and_replaces_slot(self):
        frames = body_camera.LatestFrame()

        class Camera:
            def __init__(self):
                self.calls = 0

            def read(self):
                self.calls += 1
                return (True, self.calls) if self.calls < 3 else (False, None)

        times = iter((10.0, 11.0, 12.0))
        with patch.object(body_camera.time, 'monotonic', side_effect=lambda: next(times)):
            body_camera._capture_loop(Camera(), frames, threading.Event())
        frame = frames.take(timeout=0)
        self.assertEqual((frame.image, frame.captured), (2, 11.0))
        self.assertTrue(frames.stopped)
        self.assertIn('stopped', frames.error)


class ImportTests(unittest.TestCase):
    def test_module_import_does_not_load_optional_camera_libraries(self):
        imported = []
        original_import = builtins.__import__

        def record_import(name, *args, **kwargs):
            if name.split('.', 1)[0] in ('cv2', 'mediapipe'):
                imported.append(name)
            return original_import(name, *args, **kwargs)

        cached = sys.modules.pop('scripts.body_camera')
        try:
            # A fresh import proves module setup itself has no optional imports.
            with patch('builtins.__import__', side_effect=record_import):
                importlib.import_module('scripts.body_camera')
        finally:
            sys.modules['scripts.body_camera'] = cached
        self.assertEqual(imported, [])

    def test_missing_optional_dependency_has_actionable_error(self):
        args = body_camera._make_parser().parse_args(['--model', 'pose.task'])
        original_import = builtins.__import__

        def no_cv2(name, *args, **kwargs):
            if name == 'cv2':
                raise ImportError('not installed')
            return original_import(name, *args, **kwargs)

        with patch('builtins.__import__', side_effect=no_cv2):
            with self.assertRaisesRegex(RuntimeError, 'optional body dependencies'):
                body_camera.run(args)

    def test_withdrawn_pose_is_skipped(self):
        mapper = types.ModuleType('scripts.body_pose')
        mapper.map_pose = lambda *args, **kwargs: None
        with patch.dict(sys.modules, {'scripts.body_pose': mapper}):
            result = body_camera._pose_input([object()] * 33, [object()] * 33, 0)
        self.assertIsNone(result)

    def test_cli_limits_match_body_launcher(self):
        parser = body_camera._make_parser()
        args = parser.parse_args(['--model', 'pose.task', '--camera', '0',
                                  '--max-poses', '12', '--camera-elevation-deg', '75'])
        body_camera._validate_args(args, parser)
        args.camera_elevation_deg = 75.1
        with self.assertRaises(SystemExit):
            body_camera._validate_args(args, parser)


if __name__ == '__main__':
    unittest.main()
