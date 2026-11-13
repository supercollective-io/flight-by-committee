# Local operator app

From the repository root:

```sh
uv run fly
```

This starts a loopback server on an available port and opens the operator in your
browser. Keep the terminal open. Closing the browser leaves the flight running;
Ctrl+C in the terminal shuts down the operator, its flight and its controls.
To choose a port or open the browser yourself:

```sh
uv run fly operator --port 8765 --no-browser
```

Use the full local URL printed by the launcher. Its fragment contains a temporary
operator credential; the page removes it from the address bar and retains it in
that tab's session storage. Restarting the server creates a new credential. Open
the new terminal URL to reconnect. The API rejects unauthenticated requests,
foreign origins and unexpected Host headers. It does not expose arbitrary files
or raw simulator logs through HTTP.

## Prepare a flight

1. Choose a saved profile. The form shows explicit settings; **Resolved launch
   settings** also shows the selected location, rendering weather/time options,
   input configuration summary and generated command. Values left to FlightGear
   are labelled as defaults, not reported as measured state.
2. Select **Duplicate**, give the copy a unique name and edit its values. Or
   select **New profile** to start with a paused UFO free-flight setup and enter
   coordinates. Select the aircraft, installation and rendering combination
   appropriate to the machine; new locations and combinations need validation.
3. Select **Check setup**. This validates the configuration and checks the
   executable, base data and aircraft files. It does not start FlightGear or
   prove scenery readiness, compatible rendering, terrain clearance or trimming.
4. Select **Save local profile** to keep the settings, or **Launch these
   settings** to run the draft without saving it. Launch checks the assets again.

Local profiles are TOML files under `profiles/local/`, ignored by Git. Shipped
profiles cannot be overwritten through the app. Saving an existing local profile
uses its content revision to reject stale edits from another tab. To share a
profile, inspect its contents and copy it into `profiles/` under a unique name.
Both `uv run fly list` and `uv run fly run PROFILE` recognise local profiles.
Installation paths still belong in `config/installations.local.toml`.

Coordinates use degrees; altitude is metres **above sea level**, not height above
terrain. Ground starts get elevation from scenery and omit airborne altitude and
descent-angle settings. Changing a location field makes the location inline in
that profile; it does not modify a shared location preset.

The 747 landing initialiser still bootstraps over EDSB before relocating. Its
hydraulics, landing configuration and runway assessment remain scenario-specific.
Changing coordinates does not create a validated landing scenario elsewhere.
There is no address lookup in this version.

## Operate and recover

The current-flight panel distinguishes preparation, a running process, loading,
aircraft readiness, stopping and failure. Readiness is available when the profile
uses the existing controls bridge. Without that bridge, the panel says the process
is running and asks you to check the simulator window. Neither label establishes
successful flying or venue readiness.

Monitor, projection and participant links appear when supplied by the local
controls server. In hosted mode, the local monitor and projection remain
available; obtain the participant invitation from the existing hosted operator.
The new local operator does not ask for or expose the relay operator token.
Continue using the existing environment setup for hosted controls, for example
`uv run --env-file .env fly`; the app and its worker inherit that environment.

**Stop flight** terminates the owned worker, which closes its simulator and
controls. If it cannot exit within 15 seconds, the operator kills the owned process
group. The app remains open for another launch. Edits and saves do not change the
running flight: each launch gets a resolved settings snapshot.

The panel names local diagnostic files. Operator snapshots and worker logs live
under `test-results/operator/RUN/`; normal simulator logs and launch records remain
under `test-results/PROFILE/TIMESTAMP/`. These files can contain local paths and
control invitation links. Keep them private.

A missing installation or invalid profile produces an error in the editor. A
worker or simulator failure leaves the app available to correct settings and
retry. If the browser loses the local connection, launch and stop controls are
disabled until it reconnects. Use the terminal to stop the app if needed.

## Implementation and verification

The surface uses Operate mode and extends `DESIGN.md`: a profile list, labelled
settings grouped by task, and a separate current-flight panel. Advanced aircraft
properties and generated arguments are expandable. Desktop and narrow layouts
use the same semantic form and keyboard controls.

Run the Python and existing JavaScript tests:

```sh
uv run python -m unittest discover -s tests -v
node tests/test_phone_ui.js
node tests/test_projection_ui.js
node tests/test_relay_ui.js
```

`tests/test_local_operator_browser.cjs` uses Playwright against a running operator.
Run it in a disposable checkout: it saves synthetic local profiles. Install
Playwright in a temporary test environment, install its Chromium browser, set
`PLAYWRIGHT_MODULE` to that environment's `node_modules/playwright`, and set
`FLIGHT_OPERATOR_URL` to the terminal URL including its fragment. Then run:

```sh
node tests/test_local_operator_browser.cjs
```

The browser suite checks selection, duplication, saved values after reload,
coordinate editing, ground starts, synthetic launch/stop and failure responses,
keyboard focus and mobile overflow. Screenshots go to
`test-results/operator-browser/`. The Python suite separately exercises actual
worker subprocesses with a fake simulator, including failure, stop, relaunch and
server cleanup. No live FlightGear or venue trial is implied.

### Review evidence (14 November 2026)

The final browser captures cover 1440 px desktop and 390 px mobile layouts;
`mobile-viewport.png` records the exact active-flight viewport. The narrow layout
keeps a fixed status/Stop bar while a flight is active. The profile scroller
reveals the selected profile. An independent visual reviewer marked both mobile
findings resolved. Aircraft readiness shown in these captures is synthetic.

The existing Helvetica, paper/ink/lime palette, square controls and semantic form
structure were checked against `DESIGN.md`; that design system was preserved.
The Impeccable context engine could not download, so its detector did not run;
project context and craft guidance were read directly. Source review used the
[Vercel Web Interface Guidelines](https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md)
on the review date, with the existing sentence-case design convention retained.
