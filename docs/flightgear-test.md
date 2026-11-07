# Run the FlightGear feasibility test

By default, the Python harness launches a dedicated C172P flight, tests external controls and lifecycle operations, and writes a JSON report. It uses uv-managed Python 3.11 or later with no third-party packages. This is a simulator experiment; it does not implement the phone application, continuous UDP telemetry or an independent watchdog.

For the target Nightly 747-400 scenario, use `--profile karlsruhe-747-landing`;
see [Karlsruhe landing validation](karlsruhe-747.md) for installation, aircraft
state and the optional operator landing review. The fixed C172P assumptions
below apply only to the default `feasibility` profile.

## Prerequisites

Install [uv](https://docs.astral.sh/uv/) and run `uv sync --locked` from the repository root. Configure the stable installation as described in [FlightGear profiles](flightgear-profiles.md).

Install FlightGear 2024.1.7 and its matching base data. Download the C172P and KSFO scenery through the launcher once. Close FlightGear before running the harness. Disconnect game controllers and leave mouse flight controls inactive. Use the intended display and resolution when assessing rendering.

The example installation settings find the macOS application in `/Applications` and base data in `~/Library/Application Support/FlightGear/fgdata_2024_1`. Other installations require `--binary` and `--fg-root`.

Use a trusted private network. The client connects to loopback, but do not assume the FlightGear telnet server honours the host field as a binding restriction. Do not expose the command port to audience devices or the internet.

## Run

From the repository directory:

```sh
uv run python scripts/flightgear_test.py --dry-run
uv run python scripts/flightgear_test.py
```

The first command prints the exact launch arguments without starting the simulator. The second opens FlightGear and runs the experiment. It starts at 1,000 m and approximately 46.3 m/s, in calm weather at midday. Literal simulator options and property names retain their native units; reported altitude and speed use metric units.

The automated sequence:

1. Wait up to 180 s for flight dynamics, scenery loading and required telemetry.
2. Check the airborne starting state.
3. Check that pause holds position and attitude for 2 s. Pause and resume update both the aircraft and simulation-clock freeze flags.
4. Resume for 3 s and check movement and engine operation.
5. From separate resets, apply +0.1 and -0.1 commands to each axis for 2 s. Check command retention and opposite attitude responses.
6. Disturb the flight and reset three times. Compare position, speed, attitude, engine state and control values with the initial baseline.
7. Open the terminal visual-review loop. Each cycle runs for 20 s, then pauses. Inspect scenery, sky, aircraft, stutters and graphical corruption. Press Enter to reset and repeat; type `pass` or `fail`, followed by your observations, to finish.
8. Neutralise controls, pause and stop the simulator process started by the harness.

Use the review loop for repeated inspection over roughly 10 minutes. This is not a continuous ten-minute endurance or frame-rate benchmark. Include display resolution and any frame-rate observations in your notes. The harness does not measure display latency or rendering performance automatically.

Press Ctrl+C to stop early. The harness attempts to pause and neutralise controls, terminates its own simulator process, and saves the partial report. It refuses to use an occupied command port rather than attaching to another simulator.

To run only the automated checks:

```sh
uv run python scripts/flightgear_test.py --non-interactive
```

For another installation:

```sh
uv run python scripts/flightgear_test.py --binary /path/to/fgfs --fg-root /path/to/fgdata
```

Use `--help` for timeout, port, pulse duration and output-directory settings. Output directories must be new so previous reports are preserved.

## Interpret the report

Each run writes `test-results/<timestamp>/report.json` and `simulator.log`. These generated files are excluded from Git. The report records launch arguments, host information, baseline telemetry, check results, reset timings and visual notes.

| Status | Meaning |
| --- | --- |
| `pass` | All automated checks passed and you explicitly passed visual inspection. |
| `automated_pass_visual_pending` | Automated checks passed; visual inspection was skipped. |
| `fail` | A measured check or visual inspection failed. |
| `error` | The run was interrupted or could not complete. Read the error and simulator log. |

Exit status is 0 for either automated success status, and 1 for test failure or runtime error. Invalid arguments produce exit status 2. A zero exit status alone does not establish a full feasibility pass.

Reset tolerances are experimental: 10 m altitude, 2 m/s speed, 2° attitude/heading, 0.0001° position and 0.01 control input. Engine running state must match exactly. Each axis must produce opposite signed attitude changes greater than 0.2°. These checks establish coarse feasibility, not accurate aircraft dynamics or suitability for audience control.

If a property is missing, the test fails instead of silently treating it as zero. Control read-back failures can indicate competing input sources. Reset may close the command connection; the harness reconnects and waits for flight dynamics before reading state. The harness explicitly pauses after reset; it does not establish that reset itself preserves pause.

The harness shares profile resolution, asset validation, isolated `FG_HOME` state and process lifecycle handling with the launcher. Its `feasibility` profile is fixed to the experiment’s C172P starting assumptions; incompatible edits are rejected.

## Current validation

On 5 November 2026, the harness tests passed. An actual launch from the restricted development environment failed with a Qt processor error. Launches outside that sandbox stayed alive but did not open the command port within 45 s or 60 s; the captured simulator output was empty. No live flight checks or visual inspection completed. Run this procedure from your normal Terminal to collect the first simulator results.

On 6 November 2026, a user run reached the command server but exposed a harness handshake bug: the client waited for a greeting that FlightGear does not send. The client now requests prompt mode before reading, consumes the complete prompt, reports the command that timed out and prints startup progress. A regression test reproduces a server that stays silent until the first command.

A subsequent live run exposed a second bug: `--enable-freeze` sets both `/sim/freeze/master` and `/sim/freeze/clock`, but the harness previously released only the first. Pause/resume now changes both flags, freezing time first and releasing it last. Readiness also waits for `/sim/sceneryloaded`, rather than assuming flight-dynamics initialisation means scenery loading has finished.

After those fixes, a live FlightGear 2024.1.7 run on 6 November 2026 passed all 13 automated checks. It completed seven in-process resets without a crash, including three baseline comparisons. The generated evidence is `test-results/20261106-003932-737639/report.json` (local, excluded from Git). All 15 harness tests also passed. Visual inspection remains pending. The earlier crash was in a background scenery/model-loading thread; the successful run does not establish that this simulator crash can never recur.

When running from an automation environment on macOS, Qt may wait for an application launch event before opening the command server. During development, activating the harness-owned instance with `open -a /Applications/FlightGear.app` allowed startup to complete. Normal Terminal launches did not require this extra step. Close other FlightGear instances first, as described above.

## Troubleshooting

- **Qt reports an incompatible processor or `neon`:** a restricted execution environment produced this during development. Run from your normal macOS Terminal; do not change simulator data to fix this error.
- **Startup timeout:** inspect the FlightGear window for a dialog and read `simulator.log`. Complete base-data installation, check paths and scenery, and retry with `--timeout 300` if initial loading is slow.
- **Missing aircraft or terrain:** complete the initial downloads in the launcher. The harness does not install assets.
- **Engine check fails:** investigate the C172P airborne-start behaviour before accepting FlightGear. Do not waive the check just because the aircraft can glide.
- **Rendering faults on Apple Silicon:** consult the [official release guidance](https://www.flightgear.org/blog/release-2024-1-2/).

## Verify the harness

```sh
uv run python -m unittest discover -s tests -v
```

The tests exercise socket framing, missing and non-finite properties, server errors, disconnects, timeouts, reset comparisons and a simulated complete experiment. They do not replace a successful run against FlightGear.

Protocol references: [FlightGear command interface](https://wiki.flightgear.org/Telnet_usage) and [launch options](https://wiki.flightgear.org/Command_Line_Options).
