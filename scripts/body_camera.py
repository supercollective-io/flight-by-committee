"""Local camera worker that turns detected bodies into flight-control inputs."""

import argparse
from dataclasses import dataclass
import json
import math
import sys
import threading
import time
from typing import Any


MAX_FRAME_AGE_S = 0.5
CAPTURE_STALL_S = 3.0


@dataclass(frozen=True)
class CapturedFrame:
    image: Any
    captured: float


class LatestFrame:
    """A single replaceable frame slot; camera reads never build a queue."""

    def __init__(self):
        self._condition = threading.Condition()
        self._frame: CapturedFrame | None = None
        self._stopped = False
        self._error: str | None = None
        self._read_started: float | None = None

    def read_started(self, captured: float) -> None:
        with self._condition:
            self._read_started = captured

    def read_stalled(self, now: float, timeout: float = CAPTURE_STALL_S) -> bool:
        with self._condition:
            return self._read_started is not None and now - self._read_started > timeout

    def publish(self, image: Any, captured: float) -> None:
        with self._condition:
            self._frame = CapturedFrame(image, captured)
            self._read_started = None
            self._condition.notify_all()

    def stop(self, error: str | None = None) -> None:
        with self._condition:
            self._stopped = True
            self._error = error
            self._condition.notify_all()

    def take(self, timeout: float = 0.1) -> CapturedFrame | None:
        with self._condition:
            if self._frame is None and not self._stopped:
                self._condition.wait(timeout)
            frame, self._frame = self._frame, None
            return frame

    @property
    def stopped(self) -> bool:
        with self._condition:
            return self._stopped

    @property
    def error(self) -> str | None:
        with self._condition:
            return self._error


def is_fresh(frame: CapturedFrame, now: float, max_age_s: float = MAX_FRAME_AGE_S) -> bool:
    return 0 <= now - frame.captured <= max_age_s


def _capture_loop(capture: Any, frames: LatestFrame, stop: threading.Event) -> None:
    try:
        while not stop.is_set():
            captured = time.monotonic()
            frames.read_started(captured)
            ok, image = capture.read()
            if stop.is_set():
                return
            if not ok or image is None:
                frames.stop('Camera stopped returning frames')
                return
            frames.publish(image, captured)
    except Exception as exc:  # Capture errors must reach the worker's stderr path.
        frames.stop(f'Camera capture failed: {exc}')


def _number(value: Any, label: str, allow_none: bool = False) -> float | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'Pose mapper returned an invalid {label}')
    return float(value)


def _pose_input(image_landmarks: Any, world_landmarks: Any, elevation: float) -> dict[str, float | None] | None:
    from scripts.body_pose import map_pose

    mapped = map_pose(image_landmarks, world_landmarks, camera_elevation_deg=elevation)
    if mapped is None:
        return None
    roll, pitch = mapped['roll'], mapped['pitch']
    return {
        'roll': _number(roll, 'roll'),
        'pitch': _number(pitch, 'pitch', allow_none=True),
    }


def _emit(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, allow_nan=False, separators=(',', ':')) + '\n')
    sys.stdout.flush()


def _draw_preview(cv2: Any, image: Any, result: Any, inputs: list[dict[str, float | None]]) -> None:
    display = image.copy()
    height, width = display.shape[:2]
    # Draw the standard BlazePose skeleton without importing drawing helpers.
    connections = (
        (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
        (11, 23), (12, 24), (23, 24), (23, 25), (25, 27),
        (27, 29), (29, 31), (24, 26), (26, 28), (28, 30), (30, 32),
    )
    poses = getattr(result, 'pose_landmarks', ()) or ()
    for landmarks in poses:
        points = [(int(point.x * width), int(point.y * height)) for point in landmarks]
        for first, second in connections:
            if max(first, second) < len(points):
                cv2.line(display, points[first], points[second], (0, 220, 255), 2)
        for point in points:
            cv2.circle(display, point, 3, (40, 230, 80), -1)
    for index, pose in enumerate(inputs):
        pitch = '—' if pose['pitch'] is None else f"{pose['pitch']:+.2f}"
        cv2.putText(display, f"{index + 1}: roll {pose['roll']:+.2f}  pitch {pitch}",
                    (12, 28 + index * 25), cv2.FONT_HERSHEY_SIMPLEX, 0.65,
                    (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(display, f'Bodies: {len(inputs)}', (12, height - 16),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.imshow('Flight by Committee body camera', display)


def _make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True)
    parser.add_argument('--camera', type=int, default=0)
    parser.add_argument('--max-poses', type=int, default=12)
    parser.add_argument('--camera-elevation-deg', type=float, default=0.0)
    parser.add_argument('--preview', action='store_true')
    return parser


def _validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if not args.model.strip():
        parser.error('--model must be a non-empty path')
    if not 0 <= args.camera <= 100:
        parser.error('--camera must be between 0 and 100')
    if not 1 <= args.max_poses <= 100:
        parser.error('--max-poses must be between 1 and 100')
    if not math.isfinite(args.camera_elevation_deg) or not 0 <= args.camera_elevation_deg <= 75:
        parser.error('--camera-elevation-deg must be between 0 and 75')


def run(args: argparse.Namespace) -> int:
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError('Camera support is missing; install the optional body dependencies') from exc
    try:
        import mediapipe as mp
    except ImportError as exc:
        raise RuntimeError('Pose support is missing; install the optional body dependencies') from exc

    capture = None
    landmarker = None
    capture_stop = threading.Event()
    capture_thread = None
    preview_open = False
    try:
        try:
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision
        except (ImportError, AttributeError) as exc:
            raise RuntimeError('Installed MediaPipe does not provide the Tasks vision API') from exc

        try:
            base_options = mp_python.BaseOptions(model_asset_path=args.model)
            options = vision.PoseLandmarkerOptions(
                base_options=base_options,
                running_mode=vision.RunningMode.VIDEO,
                num_poses=args.max_poses,
            )
            landmarker = vision.PoseLandmarker.create_from_options(options)
        except Exception as exc:
            raise RuntimeError(f'Could not load pose model: {exc}') from exc

        capture = cv2.VideoCapture(args.camera)
        if not capture.isOpened():
            raise RuntimeError(f'Could not open camera device {args.camera}')
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        capture.set(cv2.CAP_PROP_FPS, 30)
        frames = LatestFrame()
        capture_thread = threading.Thread(target=_capture_loop,
                                          args=(capture, frames, capture_stop), daemon=True,
                                          name='body-camera-capture')
        capture_thread.start()

        last_timestamp_ms = -1
        ready = False
        while True:
            frame = frames.take()
            if frame is None:
                if frames.stopped:
                    raise RuntimeError(frames.error or 'Camera capture stopped')
                if ready and frames.read_stalled(time.monotonic()):
                    raise RuntimeError('Camera capture stalled for more than 3 seconds')
                continue
            if not is_fresh(frame, time.monotonic()):
                continue

            # The first successful camera read plus a loaded model is readiness.
            if not ready:
                _emit({'kind': 'ready'})
                ready = True

            timestamp_ms = max(int(frame.captured * 1000), last_timestamp_ms + 1)
            last_timestamp_ms = timestamp_ms
            rgb = cv2.cvtColor(frame.image, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result = landmarker.detect_for_video(mp_image, timestamp_ms)

            if not is_fresh(frame, time.monotonic()):
                if args.preview and cv2.waitKey(1) & 0xFF == ord('q'):
                    return 0
                continue
            image_poses = getattr(result, 'pose_landmarks', ()) or ()
            world_poses = getattr(result, 'pose_world_landmarks', ()) or ()
            inputs = []
            for image_pose, world_pose in zip(image_poses, world_poses):
                pose = _pose_input(image_pose, world_pose, args.camera_elevation_deg)
                if pose is not None:
                    inputs.append(pose)
            _emit({'kind': 'frame', 'captured': frame.captured, 'inputs': inputs})

            if args.preview:
                _draw_preview(cv2, frame.image, result, inputs)
                preview_open = True
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    return 0
    finally:
        capture_stop.set()
        if capture_thread is not None:
            capture_thread.join(timeout=0.5)
        if capture is not None:
            capture.release()
        if landmarker is not None:
            landmarker.close()
        if preview_open:
            cv2.destroyAllWindows()


def main(argv: list[str] | None = None) -> int:
    parser = _make_parser()
    args = parser.parse_args(argv)
    _validate_args(args, parser)
    try:
        return run(args)
    except Exception as exc:
        print(f'body-camera: {exc}', file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
