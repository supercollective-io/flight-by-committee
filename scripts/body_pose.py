"""Map confident MediaPipe body landmarks to normalised aircraft controls.

The returned roll and pitch values are in ``[-1, 1]``. A missing axis is
``None``; ``None`` as the whole result means that the pose should be withdrawn.
"""

from __future__ import annotations

import math
from collections.abc import Mapping


_CONFIDENCE_MIN = 0.5
_DEAD_ZONE_DEG = 5.0
_FULL_SCALE_DEG = 30.0
_PITCH_FULL_SCALE_DEG = 20.0
_MIN_OUTWARD_RATIO = 0.45
_MAX_MEAN_ARM_DROP = 0.35
_LANDMARK_INDEX = {
    "left_shoulder": 11,
    "right_shoulder": 12,
    "left_elbow": 13,
    "right_elbow": 14,
    "left_hip": 23,
    "right_hip": 24,
}
_AXIS_INDEX = {"x": 0, "y": 1, "z": 2}


def _value(landmark, name, default=None):
    if isinstance(landmark, Mapping):
        return landmark.get(name, default)
    if isinstance(landmark, (tuple, list)):
        index = _LANDMARK_INDEX.get(name, _AXIS_INDEX.get(name))
        return landmark[index] if index is not None and len(landmark) > index else default
    return getattr(landmark, name, default)


def _point(landmarks, name):
    """Return a finite world-space xyz tuple, or None."""
    landmark = _value(landmarks, name)
    if landmark is None:
        return None
    try:
        if isinstance(landmark, (tuple, list)) and len(landmark) >= 3:
            result = tuple(float(component) for component in landmark[:3])
        else:
            result = tuple(float(_value(landmark, axis)) for axis in ("x", "y", "z"))
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(component) for component in result):
        return None
    return result


def _confident(landmarks, name):
    landmark = _value(landmarks, name)
    if landmark is None:
        return False
    for field in ("visibility", "presence"):
        confidence = _value(landmark, field, 1.0)
        if confidence is None:
            continue
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            return False
        if not math.isfinite(confidence) or confidence < _CONFIDENCE_MIN:
            return False
    return True


def _sub(a, b):
    return tuple(a[i] - b[i] for i in range(3))


def _dot(a, b):
    return sum(a[i] * b[i] for i in range(3))


def _scale(a, scalar):
    return tuple(component * scalar for component in a)


def _unit(a):
    length = math.sqrt(_dot(a, a))
    if not math.isfinite(length) or length <= 1e-9:
        return None
    return _scale(a, 1.0 / length)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _control(angle_degrees, full_scale_degrees):
    magnitude = abs(angle_degrees)
    if magnitude <= _DEAD_ZONE_DEG:
        return 0.0
    value = min(1.0, (magnitude - _DEAD_ZONE_DEG) /
                (full_scale_degrees - _DEAD_ZONE_DEG))
    return math.copysign(value, angle_degrees)


def map_pose(image, world, camera_elevation_deg=0.0):
    """Map a MediaPipe pose to normalised roll and pitch controls.

    ``image`` supplies visibility and presence confidence; ``world`` supplies
    metric-independent xyz geometry. Both may be MediaPipe landmark lists or
    mappings keyed by MediaPipe names (``left_shoulder``, etc.). The input
    coordinates use camera axes with x right, y down and z away from the lens.
    ``camera_elevation_deg`` tilts gravity-up towards negative z.

    Roll is positive when the person's anatomical right wing drops. Pitch is
    negative for a forward lean and positive for a backward lean. Both controls
    have a 5 degree dead zone and saturate at 30 degrees (roll) or 20 degrees
    (pitch). Arms must both extend outwards by at least 45% of their upper-arm
    length. Invalid or withdrawn arm poses return ``None``; hips are optional,
    in which case accepted poses still provide roll and return ``pitch=None``.
    A shared downward arm transition is withdrawn when the mean upper-arm
    component against gravity-up is below -0.35; opposite arm motion for a bank
    remains available because the mean stays near level.
    """
    if image is None or world is None:
        return None
    required = ("left_shoulder", "right_shoulder", "left_elbow", "right_elbow")
    if not all(_confident(image, name) for name in required):
        return None
    points = {name: _point(world, name) for name in required}
    if any(point is None for point in points.values()):
        return None

    try:
        elevation = math.radians(float(camera_elevation_deg))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(elevation):
        return None
    up = (0.0, -math.cos(elevation), -math.sin(elevation))

    shoulder_axis = _unit(_sub(points["right_shoulder"], points["left_shoulder"]))
    if shoulder_axis is None:
        return None
    horizontal_right = _unit(_sub(shoulder_axis, _scale(up, _dot(shoulder_axis, up))))
    if horizontal_right is None:
        return None
    # For a front-facing subject, up x anatomical-right points towards the lens.
    forward = _unit(_cross(up, horizontal_right))
    if forward is None:
        return None

    arm_drop_components = []
    for side, outward_sign in (("left", -1.0), ("right", 1.0)):
        upper_arm = _sub(points[f"{side}_elbow"], points[f"{side}_shoulder"])
        upper_arm_length = math.sqrt(_dot(upper_arm, upper_arm))
        if not math.isfinite(upper_arm_length) or upper_arm_length <= 1e-9:
            return None
        outward = outward_sign * _dot(upper_arm, horizontal_right)
        if outward / upper_arm_length < _MIN_OUTWARD_RATIO:
            return None
        arm_drop_components.append(_dot(upper_arm, up) / upper_arm_length)
    if sum(arm_drop_components) / len(arm_drop_components) < -_MAX_MEAN_ARM_DROP:
        return None

    elbow_axis = _sub(points["right_elbow"], points["left_elbow"])
    lateral = _dot(elbow_axis, horizontal_right)
    vertical = _dot(elbow_axis, up)
    if lateral <= 1e-9:
        return None
    roll_angle = math.degrees(math.atan2(-vertical, lateral))
    roll = _control(roll_angle, _FULL_SCALE_DEG)

    pitch = None
    hips_available = all(_confident(image, name) for name in ("left_hip", "right_hip"))
    if hips_available:
        left_hip, right_hip = _point(world, "left_hip"), _point(world, "right_hip")
        if left_hip is not None and right_hip is not None:
            shoulder_mid = _scale(tuple(points["left_shoulder"][i] + points["right_shoulder"][i]
                                         for i in range(3)), 0.5)
            hip_mid = _scale(tuple(left_hip[i] + right_hip[i] for i in range(3)), 0.5)
            torso = _sub(shoulder_mid, hip_mid)
            pitch_angle = -math.degrees(math.atan2(_dot(torso, forward), _dot(torso, up)))
            pitch = _control(pitch_angle, _PITCH_FULL_SCALE_DEG)

    return {"roll": roll, "pitch": pitch}
