# Projection

The minimal setup uses two FlightGear camera windows and one browser overlay.
The main audience output is composed in OBS; the external view goes directly on
another screen. Keep the existing browser monitor on the operator screen.

## Start the flight

```sh
uv run fly run karlsruhe-747-landing --projection
```

On macOS, `--projection` opens OBS and the overlay preview in your default
browser, then prints the composition command for the current flight. OBS still
needs the one-time setup below; opening OBS does not configure its scene.

Current Nightly already enables CompositeViewer; the launcher prints setup
guidance without passing the removed `--enable-composite-viewer` option.
Select the desired external view in FlightGear,
choose **View → Add Clone View**, move that window to the second screen, then
return the main window to Captain. The extra window keeps its own view. Camera
creation and window placement are manual for this first slice; verify fly-by
behaviour in the installed Nightly before a performance.

The terminal prints an **OBS browser overlay** URL. It changes each run. The
page is read-only: it never registers a participant or sends control commands.
It shows individual pitch/roll dots, the collective ring, throttle, rudder,
brakes and participant count. It hides controls when input is stale, FlightGear
is unavailable or the approach is initialising. With no active participants it
shows that status rather than a misleading neutral command.

## One-time OBS setup (macOS)

1. Install OBS Studio 28 or newer and grant macOS screen recording permission.
2. Set OBS's base canvas to your main projector resolution (start with 1920×1080).
3. Add a **macOS Screen Capture** source named **FlightGear**. Select window
   capture and choose the main FlightGear window, not the external camera.
   Disable cursor capture. Keep FlightGear rendered and do not minimise it.
4. Under **Tools → WebSocket Server Settings**, enable the server and authentication.
   Put its password in the `OBS_WEBSOCKET_PASSWORD` environment variable in the
   terminal running the helper. Default port is 4455.

## Compose the main output

Copy the complete overlay URL printed by the flight launcher:

```sh
uv run scripts/projection.py --url 'http://127.0.0.1:8081/projection?key=YOUR_RUN_KEY'
```

The helper creates/reuses the **Flight by committee** scene, reuses the capture
source, adds a transparent browser overlay, fits both to the base canvas and
selects the scene. It does not start streaming or recording. Rerun each flight
to update the URL. Existing scenes are preserved; the named scene and overlay
are managed by this helper. It requires the optional `obsws-python` package,
which `uv run` installs via the script's inline dependency declaration.

To choose a fullscreen output:

```sh
uv run scripts/projection.py --list-monitors
uv run scripts/projection.py --url 'http://127.0.0.1:8081/projection?key=YOUR_RUN_KEY' --monitor 1
```

Use the actual monitor index returned by the first command. Supplying `--monitor`
opens a projector window; omit it when updating an already-open projection.
After restarting FlightGear, check that the capture source still selects the
correct window. If necessary, reselect it in OBS.

Alternatively, add a Browser source manually with the printed URL and the same
width/height as the canvas, above the FlightGear capture. No helper is required.
The page itself has transparent HTML and body backgrounds.

## Rehearsal check

Check two opposing phones: both dots must remain visible with the ring centred.
Check throttle, rudder and braking; stop the bridge and confirm that controls
vanish and disconnected status appears. Reset and confirm readiness recovery.
Check readability from the audience position and that the panel avoids the runway.

Compare frame rate and responsiveness with one FlightGear view, then two, then
OBS composition, at the actual output resolutions. Reduce the external view's
resolution first if necessary. Nightly/HDR/WS3 multi-window behaviour, macOS
capture and live projector performance require an on-machine rehearsal; automated
tests do not validate them. No aircraft telemetry or landing effects are added.

Full FlightGear output is saved in the run log. Explicit errors are shown live;
routine warnings and alerts stay in the log. Non-zero exits print the last 20
log lines and the exit status. Some macOS startup errors appear only in
a FlightGear popup; if the log is empty, the launcher says so rather than inventing
a cause.

## Overlay connection problems

Keep the `fly` process running: its HTTP server stops when the flight exits or
when you press Ctrl+C. Copy the complete URL from the current run, including
`?key=...`; a URL from an earlier run is rejected. The `127.0.0.1` overlay URL
works on the FlightGear computer only. On another device, substitute the LAN
address printed in the current phone join URL, retaining `/projection` and the key.
The browser preview intentionally has a transparent background and a small panel
at the bottom right. In OBS it sits over the captured flight image.

The two web servers use separate ports:

| Service | Address | Purpose |
| --- | --- | --- |
| FlightGear | `http://127.0.0.1:8080/` | Phi, property inspection and simulator HTTP endpoints |
| Collective bridge | Port `8081`, with the current run's key | Phone controls, operator monitor and projection overlay |

FlightGear's web server remains loopback-only. Phones use the bridge's LAN URL.
On macOS, a localhost listener can intercept traffic from a wildcard listener
on the same port; keeping these ports distinct prevents the overlay's status
requests reaching FlightGear and returning 404. Restart the launcher after this
change and use its new URLs. A status HTTP 404 stops overlay polling; other
failures retry with a delay that grows to five seconds.
