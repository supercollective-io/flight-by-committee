"""Mocked runtime coverage for the local camera worker."""

import sys
import threading
import time
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts import body_camera


def pose_lists(withdrawn=False):
    image = [SimpleNamespace(x=0.0, y=0.0, z=0.0, visibility=0.0, presence=0.0)
             for _ in range(33)]
    world = [SimpleNamespace(x=0.0, y=0.0, z=0.0) for _ in range(33)]
    points = {
        11: (0.25, 0.0, 0.0), 12: (-0.25, 0.0, 0.0),
        13: (0.8, 0.0, 0.0), 14: (-0.8, 0.0, 0.0),
        23: (0.2, 1.0, 0.0), 24: (-0.2, 1.0, 0.0),
    }
    for index, (x, y, z) in points.items():
        image[index] = SimpleNamespace(x=0.5, y=0.5, z=0.0,
                                       visibility=0.1 if withdrawn and index == 13 else 1.0,
                                       presence=1.0)
        world[index] = SimpleNamespace(x=x, y=y, z=z)
    return image, world


class FakeCapture:
    def __init__(self):
        self.successful_reads = 0
        self.released = False

    def isOpened(self):
        return True

    def set(self, *_args):
        return True

    def read(self):
        if self.successful_reads == 0:
            self.successful_reads += 1
            return True, object()
        return False, None

    def release(self):
        self.released = True


class FakeLandmarker:
    def __init__(self, result, delay=0):
        self.result = result
        self.delay = delay
        self.closed = False
        self.timestamps = []

    def detect_for_video(self, _image, timestamp_ms):
        self.timestamps.append(timestamp_ms)
        if self.delay:
            time.sleep(self.delay)
        return self.result

    def close(self):
        self.closed = True


class BodyCameraRuntimeTests(unittest.TestCase):
    def run_worker(self, result, delay=0):
        capture = FakeCapture()
        landmarker = FakeLandmarker(result, delay)
        cv2 = types.ModuleType('cv2')
        cv2.VideoCapture = lambda _device: capture
        cv2.CAP_PROP_FRAME_WIDTH = 1
        cv2.CAP_PROP_FRAME_HEIGHT = 2
        cv2.CAP_PROP_FPS = 3
        cv2.COLOR_BGR2RGB = 4
        cv2.cvtColor = lambda image, _mode: image

        mediapipe = types.ModuleType('mediapipe')
        mediapipe.ImageFormat = SimpleNamespace(SRGB='srgb')
        mediapipe.Image = lambda **kwargs: SimpleNamespace(**kwargs)
        tasks = types.ModuleType('mediapipe.tasks')
        python = types.ModuleType('mediapipe.tasks.python')
        python.BaseOptions = lambda **kwargs: SimpleNamespace(**kwargs)
        vision = types.ModuleType('mediapipe.tasks.python.vision')
        vision.RunningMode = SimpleNamespace(VIDEO='video')
        vision.PoseLandmarkerOptions = lambda **kwargs: SimpleNamespace(**kwargs)
        vision.PoseLandmarker = SimpleNamespace(
            create_from_options=lambda _options: landmarker)
        tasks.python = python
        python.vision = vision
        mediapipe.tasks = tasks
        modules = {
            'cv2': cv2,
            'mediapipe': mediapipe,
            'mediapipe.tasks': tasks,
            'mediapipe.tasks.python': python,
            'mediapipe.tasks.python.vision': vision,
        }
        args = body_camera._make_parser().parse_args(['--model', 'local.task'])
        messages = []

        def emit(message):
            if message['kind'] == 'ready':
                self.assertEqual(capture.successful_reads, 1)
            messages.append(message)

        with patch.dict(sys.modules, modules), patch.object(body_camera, '_emit', side_effect=emit):
            with self.assertRaisesRegex(RuntimeError, 'Camera stopped returning frames'):
                body_camera.run(args)
        self.assertTrue(capture.released)
        self.assertTrue(landmarker.closed)
        return messages, landmarker

    def test_ready_and_media_pipe_pose_are_emitted_after_first_camera_frame(self):
        image, world = pose_lists()
        result = SimpleNamespace(pose_landmarks=[image], pose_world_landmarks=[world])
        messages, landmarker = self.run_worker(result)
        self.assertEqual([message['kind'] for message in messages], ['ready', 'frame'])
        self.assertEqual(messages[1]['inputs'], [{'roll': 0.0, 'pitch': 0.0}])
        self.assertEqual(len(landmarker.timestamps), 1)

    def test_withdrawn_media_pipe_pose_emits_empty_inputs(self):
        image, world = pose_lists(withdrawn=True)
        result = SimpleNamespace(pose_landmarks=[image], pose_world_landmarks=[world])
        messages, _landmarker = self.run_worker(result)
        self.assertEqual(messages[1]['inputs'], [])

    def test_stale_inference_result_is_dropped_and_resources_are_cleaned(self):
        image, world = pose_lists()
        result = SimpleNamespace(pose_landmarks=[image], pose_world_landmarks=[world])
        messages, _landmarker = self.run_worker(result, delay=0.52)
        self.assertEqual(messages, [{'kind': 'ready'}])


if __name__ == '__main__':
    unittest.main()
