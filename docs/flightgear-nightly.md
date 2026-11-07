# FlightGear nightly: Amsterdam visual profile

The macOS nightly is installed separately from stable FlightGear. HDR/PBR has
been visually confirmed by Jo using the UFO. This profile adds OpenStreetMap
scenery layers and repeatable Amsterdam starting positions. It is a visual
exploration setup, not a validated aircraft or audience-control configuration.

## Launch

Use [uv and the profile launcher](flightgear-profiles.md). From the repository root:

```sh
uv run fly run schiphol-inspect
uv run fly run amsterdam-explore
```

Run one at a time. `schiphol-inspect` starts at Schiphol (EHAM); `amsterdam-explore` starts above
Schiphol at 600 m altitude, facing northeast towards Amsterdam. Both use explicit
coordinates (52.3086, 4.7639) and the UFO. The Qt launcher is bypassed because this nightly's launcher failed
to load QtQuick Controls and crashed on this machine.

On this Mac, launching the executable directly can stall before normal startup
logs until its Dock icon is clicked. The script now requests macOS activation
of the exact process it starts, bringing FlightGear to the foreground while
preserving simulator logs. This addresses startup activation; it does not
disable App Nap or establish whether background simulation is throttled.

Preview the arguments without starting FlightGear:

```sh
uv run fly run amsterdam-explore --dry-run
```

Use the launcher’s named overrides for one-off changes. Save installation paths
in `config/installations.local.toml`; edit profiles and rendering presets for
repeatable settings.

## Local installation

| Component | Location on Jo's Mac |
| --- | --- |
| Nightly 2024.2.0 application | `/Applications/FlightGear-Nightly/FlightGear.app` |
| Development data (`next` Git checkout) | `/Users/jo/FlightGear-Nightly/fgdata` |
| Downloaded WS3 scenery | `/Users/jo/Library/Application Support/FlightGear/TerraSync_WS3` |
| Stable 2024.1.7 application | `/Applications/FlightGear.app` |
| Stable data | `/Users/jo/Library/Application Support/FlightGear/fgdata_2024_1` |

The launch script stores its separate `FG_HOME` state and timestamped logs under
`test-results/<profile>/<timestamp>/`, which is ignored by Git. Large scenery and application
files stay outside the repository. It ignores saved/default launch options and
sets the visual profile explicitly on each run.

The development data was obtained with a shallow clone of
`https://gitlab.com/flightgear/fgdata.git`, branch `next`. A clone of current
`fgdata` does **not** include the Cessna 172P. It was removed from that repository
in August 2026. The UFO is present and works without another aircraft download.
Install a suitably compatible aircraft separately before changing `--aircraft`.

## Visual settings

- HDR compositor and World Scenery 3 terrain enabled explicitly.
- OpenStreetMap buildings, scenery objects, pylons, details and tree layers enabled.
- Procedural vegetation and vegetation shadows enabled at normal density.
- Random buildings disabled to avoid overlapping the OSM buildings.
- Older OSM road overlay disabled because WS3 supplies roads.
- Texture filtering set to 16; visibility limited to 25 km.
- Noon, a fixed clear-weather METAR and a 1440 × 900 window for comparison.
- TerraSync enabled; scenery downloads and updates as the view moves.
- Online weather and AI traffic-data downloads disabled for this visual profile.

Changing settings during a session does not change the scripted profile. Edit
the TOML profile or `config/rendering/ws3-hdr.fgfsrc` to make a repeatable change. More buildings and vegetation increase
GPU, memory and download requirements; allow initial downloads to settle before
judging coverage or performance.

## Scenery scope and limitations

### Verification on 6 November 2026

Later diagnosis identified a separate startup problem after disk space was
available: the original central-Amsterdam start (52.3676, 4.9041) remained on
“loading scenery” with no pending downloads or pager work. The installed
Nightly revision `a96ddff2faf7d34b7a4d41eef70cae6f9ac01465` fails its initial
ground-elevation check there, preventing flight-model initialisation. Removing
the optional scenery layers did not resolve it. The Amsterdam WS3 archive
passed its ZIP integrity check.

Starting with only `--airport=EHAM` also proved unreliable: its airport-dynamics
lookup failed and it fell back to 0° latitude, 0° longitude. The presets now use
explicit Schiphol coordinates. The revised airborne `city` start was tested
offline with all configured scenery layers enabled: scenery and flight-model
readiness both became true, and the position was confirmed as 52.3086, 4.7639
at 600 m. This verifies startup, not visual quality or complete regional coverage.
Fly towards Amsterdam after starting; the preset no longer starts in the centre.

The central-Amsterdam stall is distinct from the observed abort during scenery
cleanup on exit. The latter remains unresolved.

#### Earlier download attempt

Shell syntax and command generation passed. The city profile launched and
downloaded Amsterdam terrain, buildings, trees and objects, but did not reach
confirmed readiness. FlightGear then reported `No space left on device` while
writing the pylons layer. The data volume had approximately 475 MB available.
The test instance was stopped; the regional download is incomplete and the
Amsterdam result has not been visually verified.

The launcher imposes no fixed free-space requirement. TerraSync manages the
downloads; the launcher does not know their remaining size and does not implement
a predictive capacity check. Actual filesystem write failures appear in the
FlightGear logs. TerraSync can check and resume its downloads; retain the existing
scenery cache when retrying.

### Included scenery

The profile uses the official TerraSync airport models, terrain and OSM scenery.
It does not install an unverified third-party airport replacement. In particular,
do not mix older WS2 airport meshes into this WS3 profile without checking their
elevations and compatibility.

Satellite imagery is **not installed or enabled**. The familiar Julia/WS2
photoscenery workflow is not a drop-in solution for WS3. A WS3-compatible imagery
source and conversion pipeline need a separate small-area validation before a
larger Amsterdam download. Enabling a photoscenery property alone does not fetch
imagery or prove that a particular tile format works.

Keflavík (BIKF) exhibited floating buildings and aircraft. Logs confirmed a
surface near 0 m while object placements were around 40–48 m. An upstream
discussion describes the same WS3 elevation problem. Turning on WS3 did not fix
that airport. Amsterdam is a separate comparison, not a repair to BIKF.

The UFO is also a scenery editor: clicking the ground places a measuring cursor.
Use Ctrl-click to select an object and Backspace (Mac Delete ⌫) to remove it.
Press `?` in the simulator for its movement and editing controls.

## Sources

- [HDR pipeline](https://wiki.flightgear.org/HDR_Pipeline)
- [WS3 terrain and layer guidance](https://wiki.flightgear.org/World_Scenery_3.0)
- [OSM2City world build and automatic downloads](https://wiki.flightgear.org/OSM2City_1st_Worldbuild)
- [WS3 photoscenery compatibility discussion](https://forum.flightgear.org/viewtopic.php?f=5&t=43960)
- [BIKF elevation discussion](https://sourceforge.net/p/flightgear/mailman/message/59320226/)
