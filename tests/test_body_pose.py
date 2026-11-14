"""Geometry and withdrawal behaviour for the dependency-free pose mapper."""

import math
import unittest
from types import SimpleNamespace

from scripts.body_pose import map_pose


def landmarks(roll=0.0, pitch=0.0):
    """Build a frontal pose in camera axes, with angles expressed in radians."""
    left_shoulder = (0.25, 0.0, 0.0)
    right_shoulder = (-0.25, 0.0, 0.0)
    left_elbow = (0.8 * math.cos(roll), -0.8 * math.sin(roll), 0.0)
    right_elbow = (-0.8 * math.cos(roll), 0.8 * math.sin(roll), 0.0)
    # The torso vector from hips to shoulders leans towards the lens for a
    # negative pitch; camera-forward is negative z.
    height = math.cos(pitch)
    forward = math.sin(pitch)
    points = {
        "left_shoulder": left_shoulder,
        "right_shoulder": right_shoulder,
        "left_elbow": left_elbow,
        "right_elbow": right_elbow,
        "left_hip": (0.2, height, -forward),
        "right_hip": (-0.2, height, -forward),
    }
    # Shift shoulders forward or backward relative to hips to make a lean.
    return points


def confidence(points):
    return {name: {"x": xyz[0], "y": xyz[1], "z": xyz[2],
                   "visibility": 1.0, "presence": 1.0}
            for name, xyz in points.items()}


def rotate_x(points, angle):
    cosine, sine = math.cos(angle), math.sin(angle)
    return {name: (x, y * cosine - z * sine, y * sine + z * cosine)
            for name, (x, y, z) in points.items()}


def rotate_y(points, angle):
    cosine, sine = math.cos(angle), math.sin(angle)
    return {name: (x * cosine + z * sine, y, -x * sine + z * cosine)
            for name, (x, y, z) in points.items()}


def rotate_axis(points, axis, angle):
    cosine, sine = math.cos(angle), math.sin(angle)

    def cross(a, b):
        return (a[1] * b[2] - a[2] * b[1],
                a[2] * b[0] - a[0] * b[2],
                a[0] * b[1] - a[1] * b[0])

    def dot(a, b):
        return sum(a[i] * b[i] for i in range(3))

    return {name: tuple(vector[i] * cosine + cross(axis, vector)[i] * sine +
                        axis[i] * dot(axis, vector) * (1 - cosine)
                        for i in range(3))
            for name, vector in points.items()}


def mediapipe_lists(points):
    """Create list-shaped MediaPipe data, including its fixed landmark slots."""
    names = {"left_shoulder": 11, "right_shoulder": 12,
             "left_elbow": 13, "right_elbow": 14,
             "left_hip": 23, "right_hip": 24}
    image = [SimpleNamespace(x=0.0, y=0.0, z=0.0,
                             visibility=0.0, presence=0.0) for _ in range(33)]
    world = [SimpleNamespace(x=0.0, y=0.0, z=0.0) for _ in range(33)]
    for name, index in names.items():
        if name in points:
            xyz = points[name]
            image[index] = SimpleNamespace(x=0.0, y=0.0, z=0.0,
                                           visibility=1.0, presence=1.0)
            world[index] = SimpleNamespace(x=xyz[0], y=xyz[1], z=xyz[2])
    return image, world


class BodyPoseTests(unittest.TestCase):
    def mapped(self, points, **kwargs):
        return map_pose(confidence(points), points, **kwargs)

    def test_level_pose_is_neutral(self):
        self.assertEqual(self.mapped(landmarks()), {"roll": 0.0, "pitch": 0.0})

    def test_mediapipe_landmark_lists_are_supported(self):
        image, world = mediapipe_lists(landmarks())
        self.assertEqual(map_pose(image, world), {"roll": 0.0, "pitch": 0.0})

    def test_roll_signs_follow_anatomical_right_wing(self):
        right_down = self.mapped(landmarks(roll=math.radians(20)))
        left_down = self.mapped(landmarks(roll=math.radians(-20)))
        self.assertGreater(right_down["roll"], 0)
        self.assertLess(left_down["roll"], 0)
        self.assertAlmostEqual(right_down["roll"], -left_down["roll"])

    def test_pitch_signs_and_combined_pose(self):
        forward = self.mapped(landmarks(pitch=math.radians(-15)))
        backward = self.mapped(landmarks(pitch=math.radians(15)))
        combined = self.mapped(landmarks(math.radians(20), math.radians(-15)))
        self.assertLess(forward["pitch"], 0)
        self.assertGreater(backward["pitch"], 0)
        self.assertGreater(combined["roll"], 0)
        self.assertLess(combined["pitch"], 0)

    def test_yaw_and_camera_elevation_preserve_neutral_pose(self):
        yaw = math.radians(35)
        self.assertEqual(self.mapped(rotate_y(landmarks(), yaw)),
                         {"roll": 0.0, "pitch": 0.0})
        elevation = math.radians(20)
        elevated = rotate_x(landmarks(), elevation)
        self.assertEqual(self.mapped(elevated, camera_elevation_deg=20),
                         {"roll": 0.0, "pitch": 0.0})

    def test_yaw_and_elevation_preserve_combined_roll_and_pitch(self):
        expected = self.mapped(landmarks(math.radians(18), math.radians(-12)))
        elevation = math.radians(24)
        elevated = rotate_x(landmarks(math.radians(18), math.radians(-12)), elevation)
        gravity_up = (0.0, -math.cos(elevation), -math.sin(elevation))
        rotated = rotate_axis(elevated, gravity_up, math.radians(38))
        actual = self.mapped(rotated, camera_elevation_deg=24)
        self.assertAlmostEqual(actual["roll"], expected["roll"])
        self.assertAlmostEqual(actual["pitch"], expected["pitch"])

    def test_bent_elbows_are_accepted_without_wrist_extension(self):
        pose = landmarks()
        pose["left_elbow"] = (0.65, 0.0, -0.45)
        pose["right_elbow"] = (-0.65, 0.0, -0.45)
        self.assertIsNotNone(self.mapped(pose))

    def test_arms_down_or_one_collapsed_arm_withdraws_pose(self):
        pose = landmarks()
        pose["left_elbow"] = (0.25, 0.7, 0.0)
        pose["right_elbow"] = (-0.25, 0.7, 0.0)
        self.assertIsNone(self.mapped(pose))

    def test_symmetric_arm_drop_withdraws_but_opposite_bank_motion_is_kept(self):
        lowered = landmarks()
        lowered["left_elbow"] = (0.25 + 0.6 * math.cos(math.radians(30)),
                                 0.6 * math.sin(math.radians(30)), 0.0)
        lowered["right_elbow"] = (-0.25 - 0.6 * math.cos(math.radians(30)),
                                  0.6 * math.sin(math.radians(30)), 0.0)
        self.assertIsNone(self.mapped(lowered))

        banking = self.mapped(landmarks(roll=math.radians(20)))
        self.assertIsNotNone(banking)
        self.assertGreater(banking["roll"], 0)
        pose = landmarks()
        pose["right_elbow"] = (-0.25, 0.7, 0.0)
        self.assertIsNone(self.mapped(pose))

    def test_missing_hips_keep_roll_and_remove_pitch(self):
        pose = landmarks(roll=math.radians(15))
        del pose["left_hip"]
        del pose["right_hip"]
        result = self.mapped(pose)
        self.assertGreater(result["roll"], 0)
        self.assertIsNone(result["pitch"])

    def test_low_confidence_and_non_finite_world_points_are_rejected(self):
        pose = landmarks()
        image = confidence(pose)
        image["left_elbow"]["visibility"] = 0.1
        self.assertIsNone(map_pose(image, pose))
        pose = landmarks()
        pose["right_shoulder"] = (float("nan"), 0.0, 0.0)
        self.assertIsNone(self.mapped(pose))

    def test_dead_zone_and_saturation(self):
        small = self.mapped(landmarks(roll=math.radians(4), pitch=math.radians(-4)))
        large = self.mapped(landmarks(roll=math.radians(35), pitch=math.radians(-40)))
        self.assertEqual(small, {"roll": 0.0, "pitch": 0.0})
        self.assertEqual(large, {"roll": 1.0, "pitch": -1.0})


if __name__ == "__main__":
    unittest.main()
