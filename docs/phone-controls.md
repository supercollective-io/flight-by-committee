# Phone aircraft controls

For operator-selected camera input instead of phones, see [Body controls](body-controls.md).

The Karlsruhe landing profile now selects a shared phone input layout. Launch on
the computer, then use phones for aircraft controls only:

```sh
uv run fly run karlsruhe-747-landing
```

The terminal prints a QR code and the preferred LAN join URL. Put the phone on
the same Wi-Fi and scan the QR code with its camera. The computer-only status
link also displays the QR code if scanning the terminal is awkward.

Active physical network interfaces are preferred over VPN tunnels. If there
are several LAN interfaces, the terminal lists alternative URLs; use the one
on the phone's network. `127.0.0.1` is labelled computer-only and is never encoded
in the phone QR code. If address detection fails, connect to Wi-Fi and relaunch.

QR generation uses the local `qrencode` executable (already installed on this
development computer). On another Mac, install it with `brew install qrencode`.
If it is missing, joining by URL still works. No join URL is sent to an external
QR service. Allow incoming connections to Python if macOS asks. Guest Wi-Fi
with client isolation will not work. Keep the phone page visible while flying.

The approach starts paused. Resume, pause and reset using FlightGear on the
computer. The phone has no simulation-management actions.

| Control | Action |
| --- | --- |
| Touch pad | Left/right rolls; drag down to raise the nose, up to lower it. Release centres both controls. |
| Throttle | Vertical slider: up increases thrust, down reduces it. Sets all four engines together; holds its setting. Initially matches the group throttle (or simulator throttle for the first participant). |
| Rudder | Hold left/right for yaw and nosewheel steering. |
| Hold to brake | Hold for both wheel brakes; lift your finger to disengage. |
| Release brakes | Releases your brake input, clears parking/copilot brakes and switches autobrake off; others can still brake. |

Gear and flaps are preset by the approach. The input adapter leaves trim alone.
Disable mouse flight control and disconnect joysticks so they do not compete
with the phone. There is no autopilot or stabilisation added by the phone input.
Opening the link observes; tap **Join flight controls** to begin contributing.
Use **Observe without voting** to leave the average. Everyone who joins the
controls through the same invitation controls the aircraft together. Each active
session contributes one equally weighted input, averaged separately for pitch,
roll, rudder, wheel brakes and throttle. Centred input counts; expired input does
not. More messages do not give a participant more influence. One phone is the
single-participant case of the same calculation.

The filled pad marker shows your command; the amber ring shows the collective
command, not aircraft attitude. Use the pad and vertical throttle simultaneously
with two thumbs. Your throttle slider keeps your own setting; the amber marker
and Group percentage show the collective setting. New and reconnecting
participants start at the group throttle, avoiding a jump on joining.

The computer monitor shows the active count, aggregate controls and individual
pitch/roll dots. Opposing commands are visible even when the mean is zero.
Sessions are anonymous browser-tab identities, not verified people.

## Connection feedback and recovery

The phone distinguishes server disconnection, FlightGear unavailability,
approach initialisation and active participant count. The terminal reports
connection transitions. For a persistent computer display, open a join URL with
`&monitor=1` appended. That page observes status without claiming controls.

After approximately one second without fresh input, that participant leaves the
average. With nobody active, the bridge requests neutral pitch, roll, rudder and brakes. Throttle and trim are retained and flight
continues. A separate FlightGear Nasal watchdog releases momentary controls
if the bridge stops updating. It checks wall-clock time on rendered frames,
including while paused; a frozen renderer cannot execute that check until its
next frame. Neither failure path pauses the simulation.

A reconnect requires a new handshake and fresh touches. Reset changes the
simulator generation, discards previous input, waits for the saved approach to
be ready and synchronises throttle. Do not hold a touch through reset: release
and touch again after readiness returns.

## Profile configuration

The profile selects a reusable input definition:

```toml
input = "phone-landing"
```

`config/inputs/phone-landing.toml` defines the layout, HTTP port, input expiry,
readiness property, control paths, axis gains and the aircraft-specific brake-release paths. Copy it under another name to
try different mappings or sensitivities, and reference it from a profile.
Currently `landing` is the implemented layout; another input type or layout
requires a corresponding adapter/UI implementation. Profiles without `input`
retain ordinary FlightGear launch behaviour. The automated scenario harness
continues to run without the phone service.

The initial roll/pitch authority is 60%; rudder, brakes and throttle have their
full range. Pitch has an inverted mapping because recorded 747 response tests
show positive elevator input lowers the nose. These gains need a real-phone
flight trial and are deliberately easy to adjust.

## Scope and implementation

The default launcher retains the local, trusted-network route. For the hosted
HTTPS/WebSocket route, outbound bridge and deployment procedure, see
[Hosted Flight controls](relay-operations.md). The remainder of this section
describes LAN transport. Assets are served locally; QR generation uses the optional local
`qrencode` executable. The join URL contains a new random access key each run;
anyone with it can join. HTTP is unencrypted, so do not expose this service to
the internet. FlightGear's command socket binds only to `127.0.0.1` on a temporary
port; phones can only submit the defined aircraft controls and brake-release action.

The browser sends complete momentary state approximately every 100 ms, with
only one HTTP request in flight. Each participant’s throttle choice is retained while their input remains fresh;
simulator read-back does not overwrite individual choices. Responses carry a single-use challenge valid for
500 ms; delayed/replayed requests cannot refresh input. The adapter runs at
approximately 10 Hz plus property-connection overhead. There is no WebSocket
or additional Python dependency in this slice.

The per-run directory contains the generated watchdog XML and actual launch
command. Connection transitions are printed in the terminal; simulator-side
watchdog messages appear in `simulator.log`.

## Try it

1. Launch, join from a phone and wait for readiness. Check that throttle matches
   the simulator before touching it.
2. Resume from the computer. Check all steering directions, throttle and brakes;
   release each momentary control and verify it centres.
3. Fly and land using the phone, brake to a stop, then reset from the computer.
4. While holding a control, lock the phone or interrupt Wi-Fi. Verify control
   release, unchanged throttle, continuing flight and disconnected status.
5. Rejoin and verify old touches do not return. Join a second phone, oppose pitch/roll commands, and check that they cancel.
   Release one pad and check that it still contributes zero. Adjust throttle
   on both phones and check their choices stay separate from the group value.
6. Hold brakes on both phones, then use Release brakes on one: the other should
   still contribute half braking. Disconnect one phone and verify the remaining
   participant gains full influence. Reset with both active and check fresh touches
   are required and throttle synchronises to the saved approach.

Automated checks cover profile validation, freshness, equal weighting, independent expiry, throttle choices, reset
invalidation, HTTP routes and browser touch lifecycles. A real phone/network
and live FlightGear trial is still required; this is not validation for a room
of participants.

For an audience overlay and a second camera window, see [Projection](projection.md).
