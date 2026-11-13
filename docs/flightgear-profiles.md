# FlightGear profiles

The 747 profile supports a top-level `livery = "supercollective"` setting. On
launch, the runner renders the repository SVG, creates a private aircraft overlay
with the generated texture, and selects it automatically. The installed aircraft
is unchanged. Dry runs make no asset changes.
See the [livery workspace](../assets/liveries/747-400/README.md) for editing,
building and adding designs.

Install [uv](https://docs.astral.sh/uv/), then run from the repository root:

```sh
uv run fly                                       # Pick a profile
uv run fly list
uv run fly run amsterdam-explore
uv run fly run amsterdam-explore --dry-run        # Preview without launching
uv run fly run amsterdam-explore --altitude-m 900
```

uv manages Python and the project environment automatically. Use `uv run fly run
--help` for overrides.

| Profile | Installation / aircraft | Start |
| --- | --- | --- |
| `karlsruhe-747-takeoff` | Nightly / Boeing 747-400 | EDSB runway 03, stationary, calm, paused; phone controls |
| `karlsruhe-747-landing` | Nightly / Boeing 747-400 | 12 km final to EDSB runway 03, calm, paused; [setup and validation](karlsruhe-747.md) |
| `schiphol-inspect` | Nightly / UFO | Schiphol ground |
| `amsterdam-explore` | Nightly / UFO | 600 m above Schiphol, towards Amsterdam |
| `keflavik-diagnostic` | Nightly / UFO | BIKF; experimental, known elevation faults |
| `amsterdam-flight` | Nightly / C172P | Schiphol at 1,000 m, calm, paused; requires aircraft installation and validation |
| `feasibility` | Stable / C172P | KSFO at 1,000 m, paused |

Amsterdam starts at Schiphol to avoid a [nightly scenery startup fault](flightgear-nightly.md).
The feasibility profile launches the flight; the [test harness](flightgear-test.md)
runs the checks. KSFO is retained because the original successful control and
reset checks used that location; it is a regression baseline, not a proposed
performance location.

`amsterdam-flight` is a candidate for manual flying and later audience-control
experiments. Install a nightly-compatible C172P and verify startup, controls and
reset before treating it as ready. Its `flight.wind_m_s = 0` replaces the
rendering preset’s METAR with fixed calm weather.

## Take off from Karlsruhe/Baden-Baden

```sh
uv run fly run karlsruhe-747-takeoff
```

This uses the same EDSB airport, Nightly aircraft installation and livery as the
[Karlsruhe landing profile](karlsruhe-747.md). It starts on runway 03's centreline,
100 m beyond the physical runway end, with zero initial speed, engines requested
running at idle, gear down, parking brake applied and flaps commanded to 10°.
Weather is calm at noon, with the same 20,000 kg fuel load as the landing profile.

For local [phone controls](phone-controls.md), join using the printed LAN URL
or QR code, with phones on the computer's Wi-Fi. If `FLIGHT_RELAY_URL` is set,
the launcher uses hosted mode: share the deployed participant invitation
(`https://fly.supercollective.io/?key=PARTICIPANT_KEY`), using the participant
key configured on the relay, and wait for the relay to connect. The printed
local monitor link is read-only and its key is not a participant invitation.
See [hosted controls](relay-operations.md) for configuration.

To select local controls for one launch:

```sh
env -u FLIGHT_RELAY_URL uv run fly run karlsruhe-747-takeoff
```
Unpause on the computer with the parking brake applied,
allow hydraulic pressure and flaps to settle, then tap **Release brakes** on the phone
and apply take-off thrust with its throttle slider. Retract gear and flaps using the simulator controls
as appropriate after departure. The phone controls pitch, roll, rudder, throttle and brakes.
It deliberately omits the landing initialiser, which relocates the aircraft into
the approach. Ground elevation comes from scenery.

Startup, runway alignment, reset behaviour and an operator take-off still need
in-simulator validation; the landing harness does not validate this ground start.

## Configure

Copy `config/installations.example.toml` to `config/installations.local.toml` and
adjust paths for this machine. Without a local file, the example's macOS paths
are used. Keep each executable paired with its matching base data; add separately
installed aircraft to `aircraft_dirs`. Nightly does not include C172P.
Paths accept `~`; relative paths are relative to the configuration file.

To save a flight, copy a file in `profiles/`, rename it and edit its TOML.
It appears automatically in the picker. For example:

```toml
description = "Explore Amsterdam at 900 m"
installation = "nightly"
location = "schiphol-airborne"
rendering = "ws3-hdr"
aircraft = "ufo"

[flight]
altitude_m = 900
time_of_day = "noon"
```

Locations live in `config/locations/*.toml`; rendering presets in
`config/rendering/*.fgfsrc` use one FlightGear option per line.
CLI overrides apply to one run; simulator UI changes do not update saved profiles.
Changing installation may also require a different rendering preset.
`--fg-root` resets the aircraft search path to that root's `Aircraft` directory.

## Logs and tests

Each flight writes `launch.json` (resolved settings and command), `simulator.log`
and isolated simulator state under `test-results/PROFILE/TIMESTAMP/`.
Scenery caches are reused. Ctrl+C stops the launched simulator.
Local installation settings and run output are ignored by Git.

```sh
uv run python -m unittest discover -s tests -v
```

Profiles may include a numeric/boolean `[properties]` table for aircraft-specific
initial state. An optional `initialisation` name loads `config/aircraft/NAME.xml`.
Keep these separate from rendering presets; validate aircraft-specific state
and scripts against the installed aircraft package.
