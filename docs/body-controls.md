# Body controls

The operator can select a local camera instead of phones at launch. Participants
spread their wings to contribute, tilt to bank, and lean forwards for nose down
or backwards for nose up. Bent elbows are welcome. Lowering the arms withdraws
the contribution; nobody needs to hold their arms out for the whole flight.

This is an experimental single-camera mode. It samples the poses it can see,
not every person in the room. Camera recognition, comfort over the full
2.5-minute flight and the mapping need an in-person trial. Automated geometry
tests do not establish recognition quality or venue readiness.

To offer camera and phones together, use [Hybrid controls](hybrid-controls.md).
The instructions below describe camera-only mode.

## Install and launch

Install the optional dependencies on the show computer:

```sh
uv sync --extra body --frozen
mkdir -p assets/models
curl --fail --location --output assets/models/pose_landmarker_lite.task \
  https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task
```

The model is a separate, ignored local asset. Download it before arriving at the
venue. Runtime processing stays local and does not download models, upload video,
record frames or store participant identities.

From the project folder, start the body-controlled landing with:

```sh
uv run --extra body --frozen fly run karlsruhe-747-body
```

Or run `uv run --extra body --frozen fly` to open the
[local operator app](local-operator.md), then select **Fly with your body**
from its profile list. The profile selects the Karlsruhe landing, the downloaded local
model, camera 0, a maximum of 12 poses and the camera preview. These defaults
live in `config/inputs/body-landing.toml`; the model path is relative to the
repository root. Adjust that file for the venue instead of repeating flags.

Command-line overrides still work, such as `--camera 1`,
`--camera-elevation-deg 20` or `--no-camera-preview`.
Keep `--extra body` on operator-app and flight launches so uv retains the
optional camera dependencies.

For a different flight profile or a launch without the preview, use the full
launcher: `uv run --extra body fly run PROFILE --input-mode body --pose-model
assets/models/pose_landmarker_lite.task`, adding any camera options needed.

`--camera` is the local capture-device index. On macOS, grant the launching
application camera permission in System Settings if requested. A capture device
must be accessible through OpenCV's camera backend; not every SDI/Thunderbolt
device presents a compatible camera source. Confirm the device and driver with
ZKM before relying on it.

The preview is local and unmirrored. Press **q** in its window to stop camera
input; this does not stop or pause FlightGear. Restart the launcher to restart
the camera. Use `--no-camera-preview` during a performance if it is not needed.
`--projection` opens the existing projection workflow. The local overlay URL is
also printed. Phone input routes are disabled in body mode, even when
`FLIGHT_RELAY_URL` is set. The original `karlsruhe-747-landing` profile still uses phones.

To check the camera and gestures without starting FlightGear:

```sh
uv run --extra body python -m scripts.body_camera \
  --model assets/models/pose_landmarker_lite.task --camera 0 \
  --max-poses 12 --preview
```

This diagnostic prints timestamped control samples, not images or landmarks.

## Camera setup

Start with a fixed camera near the projection end of the room, elevated and
roughly 45 degrees to one side of the audience's facing direction. Frame the
standing audience with room for their arms and enough light to see bodies.
Oblique placement helps expose forward lean but is not a guarantee of reliable
depth estimates. Hips hidden by other people reduce pitch participation.

Set `--camera-elevation-deg N` to the camera's approximate downward tilt from
horizontal (0–75 degrees; default 0). This is a single mounting setting, not a
participant calibration. Camera roll should be level. Anatomical shoulder
direction supplies heading, so there is no per-person yaw setting or identity.
Do not mirror the input before inference. Check both control directions after
placing the camera.

The Cube questionnaire specifies front projection via HDMI at 3840 × 2160;
camera and capture equipment remain to be confirmed with ZKM. A wired camera
feed enters the MacBook through a compatible capture device; its HDMI output
goes to projection. Start with the worker's requested 1280 × 720, 30 frames/s
capture; the driver may negotiate a different format. The detection limit
defaults to 12, and can be raised with `--max-poses` (maximum 100). That limit
does not promise recognition or throughput at that population.

## Mapping and withdrawal

- Both upper arms must point sufficiently outwards to count. Recognition uses
  shoulders and elbows, so bent or hidden wrists do not prevent participation.
  A shared downward drop of both upper arms withdraws the pose early, while
  opposite upward/downward wing movements remain eligible for banking.
- Roll comes from the elbow-to-elbow wing line relative to gravity. Anatomical
  right wing down gives right roll. The neutral zone is 5 degrees, with full
  requested input at 30 degrees.
- Pitch comes from shoulder-to-hip inclination along anatomical forward. The
  neutral zone is 5 degrees, with full requested input at 20 degrees.
- Each detected, eligible pose has equal influence on each readable axis.
  Hidden hips exclude that pose from pitch without adding a neutral pitch vote.
  A confidently readable neutral pose does count.
- Frames are independent: there are no remembered neutral poses, participant
  accounts or identities. A returning pose can contribute immediately.
- Group commands use brief smoothing. An axis with no contributors releases
  immediately; old contributions are never latched while someone rests.

The arm threshold rejects lowered arms, including sufficiently lowered single
arms. During the early part of lowering an arm, a pose can still resemble an
intentional bank. This ambiguity cannot be eliminated by a single-frame rule;
test normal withdrawal and tune the threshold if resting causes noticeable
steering. Lower both arms to withdraw most clearly.

## Flight behaviour and recovery

Body mode controls **pitch and roll only**, using the selected aircraft's
existing gains and signs. It never writes throttle, rudder or wheel brakes;
those remain operator controls in FlightGear. Gear, flaps and trim retain the
profile's behaviour. No automatic levelling, speed control or flight assistance
is added. Avoid another input device competing for pitch or roll.

The camera drains into one replaceable frame slot, and inference uses the latest
available frame. Frames older than 0.5 s are rejected before and after inference
and again by the bridge. This bounds application staleness; it cannot measure
hidden buffering inside a camera or capture driver. Measure actual response at
the venue. Camera loss, exit or expiry releases pitch and roll through the
existing bridge/watchdog. Flight continues. Reset invalidates old camera work;
only images captured after the reset/readiness transition can contribute.

The existing overlay shows pitch/roll dots and the aggregate. A missing personal
pitch estimate is displayed at the centre but is excluded from the average.
Rudder and brake fields are hidden in this mode. Throttle is read from the
simulator. Use FlightGear for the other operator controls.

## Verify before a rehearsal

Run `uv run --extra body python -m unittest discover -s tests -v` for automated
checks. Then use a short in-person trial:

1. Confirm level wings, both bank directions and forward/backward lean. Repeat
   with bent elbows and combined roll/pitch gestures.
2. Lower both arms, lower one arm, leave the frame and return. Check withdrawal
   without retained steering. Test people overlapping and hips disappearing.
3. Run the full 2.5-minute sequence with explicit permission to rest. Check
   comfort and whether recognition feedback is understandable.
4. Stop/disconnect the camera while steering. Confirm pitch/roll release,
   retained operator throttle and continuing flight. Reset during a gesture and
   verify old camera results cannot resume steering.
5. Run FlightGear, vision and the actual projection together on the show laptop;
   measure response and frame rate. Reduce the detection limit if inference
   cannot finish within the freshness budget.

The reference implementation uses [MediaPipe Pose Landmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker/python).
Its 3D landmarks are estimates from one image; crowd occlusion and camera angle
remain empirical limitations.
