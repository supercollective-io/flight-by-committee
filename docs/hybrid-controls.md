# Camera and phone controls together

For launch commands and session controls, use the
[operator cheat sheet](operator-cheat-sheet.md).

Hybrid mode lets people use body gestures or the phone controls in the same
flight. Choose one method at a time: lower your arms while using a phone, and
select **Stop controlling** on the phone before contributing with your body.
The system counts anonymous contributions, not verified people. It does not
match camera poses to phone sessions or prevent someone contributing twice.

## Launch

First install the optional camera dependencies and local pose model using
[Body controls](body-controls.md#install-and-launch). Then launch the new profile:

```sh
uv run --extra body --frozen fly run karlsruhe-747-hybrid
```

Run `uv run --extra body --frozen fly` to open the [local operator app](local-operator.md),
then select **Fly with bodies and phones** from its profile list. Camera defaults
live in `config/inputs/hybrid-landing.toml`. Camera overrides, including
`--camera 1` and `--no-camera-preview`, work as in body mode. To combine sources
with the existing body profile, use:

```sh
uv run --extra body --frozen fly run karlsruhe-747-body --input-mode hybrid
```

The three input modes are `phone`, `body` and `hybrid`. Existing phone and body
profiles retain their single-source behaviour.

Without `FLIGHT_RELAY_URL`, phones join over the trusted LAN using the printed
QR code or URL. To select this explicitly, even with relay variables exported:

```sh
env -u FLIGHT_RELAY_URL uv run --extra body --frozen fly run karlsruhe-747-hybrid
```

With `FLIGHT_RELAY_URL` and `FLIGHT_BRIDGE_KEY` configured, hybrid mode uses
hosted phones. Follow [relay operations](relay-operations.md) for invitation and
connection setup. The hosted relay must include this hybrid protocol update;
update the relay before starting a hybrid bridge. The updated relay still
supports existing phone-only bridges. An older relay rejects hybrid telemetry;
phones remain unavailable while camera input can continue. This is not an
automatic switch to local phone controls. Local hosted-mode HTTP routes remain
read-only.

## Equal influence

For each of pitch and roll, the combined command is:

```text
(m × phone mean + n × camera mean) / (m + n)
```

Here `m` is the number of fresh, participating phone sessions and `n` is the
number of fresh, eligible camera contributions readable on that axis. Every
contribution has weight `1 / (m + n)`. Opening the phone page without joining,
lowering your arms, leaving the camera frame or allowing input to expire removes
your contribution. A confidently read neutral pose or a centred joined phone
still counts. Releasing the phone pad centres its vote; **Stop controlling**
withdraws the phone from the average.

Counts are per axis. Hidden hips exclude a camera pose from pitch, while its
readable roll still counts. Camera group smoothing happens before combining
source means, using the current count of readable poses. Neither source gets
extra weight by sending more updates. Throttle, rudder and brakes are averaged
only over phones; bodies never dilute those commands.

For example, eight camera contributions requesting +1 roll and two phones
requesting −1 produce +0.6. Removing the camera contributions leaves −1;
removing the phones leaves +1. With nobody contributing, pitch, roll, rudder and
brakes release, throttle is retained, and flight continues.

## Feedback and recovery

Phones show the combined command and camera/phone contribution counts. Projection
uses squares for camera contributions, dots for phones and a ring for the group.
A hollow square means one axis is unreadable; its missing coordinate is drawn
at the centre for display only and does not enter the average.

Camera frames expire after 0.5 s. Local phone input expires after the configured
interval (1 s by default). Hosted phone sessions expire at the relay after 1 s,
and the local bridge additionally rejects stale relay exchanges after 0.5 s.
Camera exit or failure clears only camera contributions. Relay or phone loss
clears only phone contributions. The surviving source continues. Expired phone
brake-release requests cannot be carried forward by an active camera.

There is one simulator writer and watchdog. If a contribution expires or a source
withdraws while commands are being staged, the bridge rejects that staged mix
and recomputes on its next cycle. Reset invalidates both sources, rejects camera
images captured before the transition and requires fresh phone handshakes.
Delayed relay responses cannot restore votes invalidated during their request.

The camera must initialise successfully when launching hybrid mode; missing
models or startup failure abort launch rather than silently changing the chosen
mode. After startup, pressing **q** in the preview stops only camera input.
Restart the launcher to restart the camera; FlightGear pause/reset remains on
the computer.

Camera processing remains local, without recording frames or participant
identities. In hosted mode, the bridge sends anonymous command dots, counts and
the combined command back to the relay for display. No images or body landmarks
are sent. This display feedback never enters the phone vote calculation. It is
bound to the relay epoch and aggregate sequence and expires independently. While
waiting for fresh feedback, hosted displays say **Updating combined controls…**
instead of presenting a phone-only mean as the combined command.

## Verification

```sh
uv run --extra body --frozen python -m unittest discover -s tests
node --test tests/test_phone_ui.js tests/test_projection_ui.js tests/test_relay_ui.js
```

`tests/test_hybrid_control.py` covers unequal group sizes, missing axes, centred
votes, observers, independent expiry, camera process exit, reset, staged-command
expiry, brake-release expiry, local HTTP participation and real hosted WebSocket
feedback. Hosted local write routes remain forbidden. Existing single-source
tests also run.

Before a hybrid rehearsal, try the 8-to-2 example or a smaller equivalent, then
withdraw each source separately. Check the phone ring against the projection,
stop the camera, interrupt phone networking, and reset while both sources are
steering. Confirm the surviving controls and throttle behaviour. These synthetic
tests do not establish camera recognition quality, physical-phone response or
room readiness; the existing camera trial remains necessary for the new mix.
