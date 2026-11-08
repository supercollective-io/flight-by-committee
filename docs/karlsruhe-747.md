# Boeing 747-400 landing at Karlsruhe

The target is approximately 100 people collectively landing a Boeing 747-400 at
Karlsruhe/Baden-Baden (EDSB). This profile uses **FlightGear Nightly, HDR and WS3**.
The profile includes [single-phone aircraft controls](phone-controls.md).
Simulation management stays on the computer.

## Install and launch

Configure the Nightly executable and matching base data as described in
[FlightGear profiles](flightgear-profiles.md). Install the official Nightly
747-400 package with:

```sh
uv run python scripts/install_747.py
```

The installer downloads the official FGAddon trunk archive into
`test-results/assets/nightly/747-400`, checks its pinned SHA-256 and refuses to
overwrite an existing aircraft. The example installation configuration includes
that aircraft directory. If `config/installations.local.toml` exists, add
`"../test-results/assets/nightly"` to its `nightly.aircraft_dirs` array.
Do not delete that asset directory when clearing test reports.

Close other FlightGear instances, then launch:

```sh
uv run fly run karlsruhe-747-landing
```

The simulator starts paused. Use FlightGear's pause control to begin flying.
The aircraft starts approximately 12 km before runway 03's displaced threshold, aligned with
the runway, at 768.3 m above sea level and 80 m/s indicated airspeed. The altitude
approximates a 3° approach with a 15 m threshold crossing height. Weather is calm
at noon. These are initial simulation tuning values, not a validated flight plan.

Flaps are commanded to 30°, landing gear is down, parking brake is released,
and all four flight engines are running. A 45% throttle starting guess is
passed to JSBSim; automatic trim chooses the settled throttles and pitch for
the requested 3° descent. The harness records those values and checks their
retention after resume and restoration after reset. Fuel is explicitly
20,000 kg, distributed symmetrically. Payload uses the pinned aircraft model's
default; the harness records total mass and checks its repeatability on reset.
No approach autopilot is engaged. The phone controls pitch, roll, yaw, thrust
and braking; the person flying performs the flare. Flaps and gear begin
configured for landing. Multi-person roles and assistance remain open.

The aircraft's airborne engine preset does not initialise its hydraulics.
`config/aircraft/747-400-approach.xml` initialises the four engine pumps and
hydraulic model before trim and on each flight-model initialisation, including resets. This is
an aircraft-specific integration with the pinned package, not a generic 747 API.

The tested Nightly also stalls during flight-model initialisation at the approach
coordinates, even after scenery downloads finish. The initialiser first loads
over EDSB's airport mesh, then relocates to the saved approach using writable
flight-model position properties. It waits for telemetry to confirm the new
position, restores altitude and
attitude in the updated local coordinate frame, then pauses and signals that
the approach is ready. This sequence runs on each reset. If relocation does
not complete within 600 rendered frames, it pauses with a failed readiness
signal. The simulator runs briefly during this initialisation. The harness waits
for that signal as well as real scenery
and flight-model readiness; it does not override either readiness flag.

FlightGear clears its native descent-angle preset after initialisation. The
initialiser retains the requested angle in a preserved property and reapplies
it before each reset's trim calculation. Otherwise resets silently switch to
level-flight trim and change pitch and throttle.

## Validate the profile

Disconnect controllers for the automated tests. Disable mouse flight control.
Allow extra time for the first WS3 scenery download:

```sh
uv run python scripts/flightgear_test.py --profile karlsruhe-747-landing --non-interactive --timeout 600
```

The harness checks approach position, altitude, airspeed, heading, measured descent rate, flap command
and actual position, gear command and all five gear positions, pause/resume, all four flight engines,
throttle retention, four hydraulic pressures, roll/pitch response and three baseline reset comparisons. Control pulses last 4 s for this aircraft.
The APU is engine index 4 in this model and is excluded from the four flight-engine
checks. Reset comparisons include total mass, descent rate and landing configuration. The
numerical tolerances remain experimental; inspect the report as well as its status.
The initial-position check allows 100 m of movement during the WS3 startup
sequence. Reset comparisons retain the tighter 0.0001° position tolerance against
the measured baseline. The 747 control test subtracts a separate neutral-input
flight of the same duration, so natural roll/pitch drift is not mistaken for the
command's effect. The report preserves both raw and corrected responses. This
checks control authority; it does not establish that the aircraft is trimmed.

Add `--capture-views` to save cockpit and external screenshots without marking
visual review as passed.

For the visual inspection and an operator landing:

```sh
uv run python scripts/flightgear_test.py --profile karlsruhe-747-landing --landing-review --timeout 600
```

After the automated checks, inspect repeated 20 s flights. Confirm the four
engines, upper-deck hump and upturned wingtips in an external view. Inspect runway
alignment, terrain elevation, missing scenery, lighting and stutters at the
intended projection resolution. Enter `pass` or `fail` with observations.

The harness then resets and releases pause for an operator-controlled approach.
Fly and stop the aircraft. Enter `pass NOTES` or `fail NOTES` in the terminal.
The flight continues while you fly; Ctrl+C aborts and attempts to pause. This
review records telemetry in `landing.jsonl` and the result in `report.json`.

The provisional landing checks require:

- An observed transition to main-gear ground contact.
- Touchdown within the runway width and first 2,740 m after the threshold.
- Last sampled airborne vertical speed no greater than 3 m/s in magnitude.
- Bank no greater than 5° at contact.
- A stop on the runway below 1 m/s with main-gear contact.
- No modelled wing failure at touchdown or the final stop.

These are prototype acceptance criteria, not real aircraft operating limits.
Sampling can miss brief events, and the wing-failure flag does not cover every
possible damage mode. The operator must review the actual landing. A full
`pass` requires automated checks, visual inspection and the operator landing.
`automated_pass_visual_pending` or `automated_pass_landing_pending` leaves the
corresponding review incomplete. Neither establishes readiness for 100 people.

## Validation result — 7 November 2026

The installed FlightGear Nightly completed all 27 automated checks with HDR and
WS3 enabled. The measured initial descent was 4.42 m/s, with all four flight
engines running and all four hydraulic systems pressurised. Three reset
comparisons passed without reported differences; each reset took approximately
9 s. All 43 unit tests in the scenario-only commit passed. The combined working
checkout, including the separate livery work, also passed its 50 tests.

The local report is `test-results/747-nightly-descent-validation/report.json`.
Cockpit and external screenshots are saved alongside it. The external capture
shows the upper-deck hump, upturned wingtip and deployed landing gear over loaded
WS3 scenery. Static screenshots do not establish frame rate or absence of stutters.

The result remains `automated_pass_visual_pending`. Complete the interactive
visual review and an operator landing before treating this approach as ready for
a rehearsal. Collective phone control and capacity for approximately 100 people
remain subsequent milestones.

## Sources and reproducibility

- [Official aircraft source](https://github.com/gijsrooy/747-400).
- [Official Nightly aircraft catalogue](https://fgaddon.b-cdn.net/Aircraft-trunk/catalog.xml),
  package revision 21475, inspected on 7 November 2026.
- Pinned archive SHA-256: `e6cd96ca081891988db2e1bd8480b54850a6fb184cc339cfabdee7c09d7c6e2f`.
- Runway geometry comes from the installed Nightly `Airports/apt.dat.ws3.gz`:
  runway 03 physical end 48.76784332°, 8.06972798°; opposite end 48.79084241°,
  8.09125803°; displaced threshold 264 m; airport elevation 124.36 m.
- [Airport operator's runway information](https://www.baden-airpark.de/en/passengers-visitors/aviation-sector/pilot-information/)
  lists runway 03/21 and a 2,740 m landing distance. Simulator scenery remains
  the authority for this experiment's visual and positional checks.

## Operator report — 8 November 2026

The project owner reported one successful landing in FlightGear using this
profile. This is a manual baseline; it does not establish phone-control validation
or replace the recorded harness results above.
