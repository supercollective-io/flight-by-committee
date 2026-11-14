# Hosted Flight controls

The public participant interface is deployed at
[fly.supercollective.io](https://fly.supercollective.io). It returns to
[Rehearsing We](https://we.supercollective.io). The relay runs independently of
Polymind and keeps anonymous Flight identities separate. Public HTTPS and service health were checked on 12 November 2026: the homepage
and `/healthz` returned 200, the browser rendered the invitation instructions,
and anonymous `/status`, `/projection` and `/relay.js` requests returned 403.
Authenticated controls, simulator response and physical rehearsal remain unverified.

## One-command local launch

On the simulator computer, make the private configuration once, from the
repository root:

```sh
(umask 077; cp -n .env.example .env)
chmod 600 .env
```

Edit `.env` in your editor and fill in `FLIGHT_BRIDGE_KEY` with the existing
deployed bridge key. Leave `FLIGHT_RELAY_URL=https://fly.supercollective.io`.
Do not use the participant invitation key. This file is ignored by Git and
excluded from Docker builds; keep it on the simulator computer.

For each flight, run from the repository root:

```sh
uv run --env-file .env fly run karlsruhe-747-landing
```

uv reads the environment file and the existing launcher starts FlightGear and
the phone-control bridge together. `karlsruhe-747-landing` starts a paused
landing approach about 12 km from the airport, not a runway take-off.
Wait for `Relay connected` and for `Waiting for approach readiness` to clear,
then open the printed local monitor URL. Keep the terminal open.

Existing shell variables override `.env`; remove stale exports if you
want the file's values. For a deliberate LAN launch, omit `--env-file .env`
and unset any exported `FLIGHT_RELAY_URL`, as shown in the LAN fallback below.
Append `--projection` to open the projection helpers. uv only reads `.env`
when requested; no wrapper or additional configuration-loading dependency is needed.

Connection loss releases momentary controls but retains throttle and does not
pause FlightGear. Keep local pause within reach.

## Operating contract

A single Python/aiohttp process owns one flight session. It serves the existing
phone interface over HTTPS/WebSocket and averages the same bounded controls as
the LAN adapter. `scripts/controls.py` contains the shared aggregation; transport
adapters do not define new flight physics.

Opening a phone page observes. Tap **Join flight controls** to contribute; the
first handshake still contributes nothing. After joining, a centred pad counts
as zero in the denominator. **Observe without voting** removes that connection
from the average, including its retained throttle choice. Closing a hosted
socket removes its vote immediately; stalled input expires after 1 second.
Rejoining inherits the current group throttle, or simulator throttle with nobody
active. Returning to the hub also stops input and the contribution expires.
`?monitor=1` and `/projection` are read-only observers.

Phones send at roughly 10 Hz, one request at a time. The server issues single-use
500 ms challenges and uses its own receive clock, never a phone timestamp.
The local bridge opens the only simulator connection, outbound to `/ws/bridge`.
It polls at roughly 10 Hz with a fresh nonce, simulator generation, readiness
and throttle. Replies contain only the five bounded
axes, a brake-release identifier and display data. They cannot contain property
paths, commands, pause or reset requests.

A fresh relay epoch is created on bridge reconnect, simulator generation or
readiness change, or a bridge lapse of at least 500 ms. Previous participants
must handshake again; old touch state is cleared in the phone. Each bridge reply
must match its outstanding nonce and current simulator generation, arrive within
500 ms, and advance the sequence within its epoch. No offline queue is replayed.
The bridge independently expires aggregates after 500 ms and rechecks freshness
before committing a staged simulator frame. The existing simulator watchdog
remains a third release path (configured to 1 second).

On loss, pitch, roll, rudder and wheel brakes release. **Throttle is retained and
flight continues; it does not pause automatically.** Trim is left alone. A
frozen FlightGear renderer cannot run its watchdog until rendering resumes.
Phones, local monitor and projection show relay loss and hide stale collective
controls.

The bridge telemetry schema changed when the local override capability was
removed. The current relay accepts exactly generation, readiness, throttle and
nonce. Pair the hosted relay and local launcher from the same revision: an old
launcher sends an extra field that the current relay rejects, and a current
launcher omits a field that an old relay requires. Complete this as a coordinated
deployment; this change does not deploy or reconnect a running simulator.

### Upgrade and relaunch as one revision

Perform this upgrade between attempts. The launcher owns its FlightGear process;
restarting the launcher also stops that simulator process. Announce the end of
the current attempt, pause FlightGear locally, and finish the attempt before
stopping it. Do not use a launcher restart as a way to attach to an already
running simulator.

1. Choose and record the exact release commit.
2. Between attempts, announce the end, pause FlightGear locally, finish the
   attempt and stop the old launcher. Stopping the launcher also stops its
   FlightGear process.
3. On the FlightGear computer, preserve any unrelated local changes, fetch the
   repository and check out that commit:

   ```sh
   git fetch origin
   git switch --detach <release-commit>
   git rev-parse HEAD
   ```

   Do not force-reset the checkout. Confirm the printed revision matches the
   release commit before continuing.
4. In Coolify, deploy the Flight application from the same release commit.
   Keep the existing participant key, bridge key, origin and port unchanged.
   Confirm Coolify reports the same commit as the local checkout.
5. With `.env` configured as above, run
   `uv run --env-file .env fly run karlsruhe-747-landing`. This starts the saved
   approach and the bridge from the matching revision. Do not put either key
   in a command argument or print it.
6. Wait for the terminal to report `Relay connected` and for `Waiting for approach
   readiness` to clear. Open the newly printed loopback monitor URL on that
   computer. Share the public participant invitation only after the approach
   is ready.

The relay restart clears the current session and requires fresh participant
handshakes. Loss releases momentary controls, retains throttle and does not
pause FlightGear automatically.

## Coolify Application

Use a Git-backed **Dockerfile Application**, one replica, base directory `/`,
Dockerfile `/Dockerfile`, internal port `8080`. Set the domain to
`https://fly.supercollective.io:8080`; clients use the normal HTTPS URL.
Allow WebSocket upgrades through the proxy. Do not publish a host port or add
custom proxy labels. There is no database, persistent volume, simulator or worker
in this image. Restart intentionally clears the flight session.

Set these runtime variables, unavailable during builds:

| Variable | Value |
| --- | --- |
| `FLIGHT_PUBLIC_ORIGIN` | Optional canonical origin override; otherwise derived from `COOLIFY_URL` |
| `FLIGHT_PARTICIPANT_KEY` | Independent random URL-safe key, 24–128 characters |
| `FLIGHT_BRIDGE_KEY` | A different random URL-safe key, 24–128 characters; operator secret |
| `PORT` | `8080` |

Generate each key separately on your own machine with
`python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`.
Save both values in your password manager, then add them under the application's
**Environment Variables** in Coolify. Set **Available in the container** and
**Not available during build**, and lock the values after saving. Restart the
application to apply them. Preserve the values across ordinary redeployments;
do not generate credentials in the Dockerfile or on every startup. Dockerfile
applications do not automatically generate Compose-style service secrets.

A missing, blank, malformed or duplicated key stops startup with a configuration
error naming the affected setting without printing its value. Both keys are
required before the health endpoint can become ready.
The bare domain serves a public homepage with a link to the GitHub project for
people who want to run their own flight. It exposes no session data or controls.
The audience joins `https://fly.supercollective.io/?key=PARTICIPANT_KEY`.
Invalid or empty invitation keys still return 403, as do unauthenticated requests
for session status, join details, projection or the relay script.
The bridge uses a Bearer header; its key never appears in audience HTML or URLs.
Keep query strings out of proxy access logs because participant invitations
contain a key. Application access logging is disabled. Rotate both keys between
performances and restart/reconnect the service and bridge.

Browsers must send the exact configured Origin. Native bridge connections use
the bridge credential, with at most one connected bridge. Messages are bounded
to 4 KiB inbound; each socket permits 15 messages/s with a burst of four. The
process caps authenticated connections at 400, including observers and bridge.
This is an abuse bound, not evidence for a 400-person performance. Shared audience
keys identify invitations, not verified people; opening multiple controlling
connections creates multiple votes. Do not run multiple relay workers or replicas.

`GET /healthz` is unauthenticated liveness, independent of whether the simulator
is connected. The image's native Python health check uses it. The image runs as
UID 10001 and installs from `uv.lock`. Build and smoke-test on the server's target
architecture before performance. Current local Docker verification is recorded
below. Public DNS, certificate validation and HTTPS routing passed on 12 November
2026; exact running image provenance and private Coolify configuration remain unverified.

## Local simulator computer

Keep the property socket and FlightGear HTTP bound to `127.0.0.1`. The launcher
still allocates a temporary property port. Never forward either simulator port.

```sh
export FLIGHT_RELAY_URL=https://fly.supercollective.io
# Supply FLIGHT_BRIDGE_KEY privately in this shell, matching Coolify.
uv run fly run karlsruhe-747-landing
```

The terminal prints a fresh local read-only monitor and projection URL. Hosted
mode binds that HTTP server to loopback only and rejects every local POST,
including requests with the monitor key. Give the audience the public
participant invitation, not the local monitor URL. Compose the single FlightGear
capture and local overlay following
[Projection](projection.md). The public `/projection?key=PARTICIPANT_KEY` route
also observes the relay without registering a vote.

Pause and reset remain local FlightGear actions. Pause does not change relay
readiness or clear participant votes. Ask participants to release all controls
before resuming. A reset that changes simulator generation or readiness clears
the relay epoch and requires fresh participant handshakes. To finish an
unsuccessful attempt, pause locally, announce the ending and direct participants
back to the hub. Reset locally only when ready for another attempt.

## Saved approach and rehearsal record

The retained baseline is `karlsruhe-747-landing`: pinned official 747-400 package
installed by `scripts/install_747.py`, Nightly base data, HDR/WS3 scenery, EDSB
runway 03, approximately 12 km final, heading 31.661108°, altitude 768.3 m above
sea level, speed 80 m/s, gear down and landing flaps. It starts paused after its
approach initialiser reports readiness. See [Karlsruhe 747](karlsruhe-747.md) for
hydraulics, trim, scenery and reset details. The installed macOS bundle advertises
2024.2.0; record its exact Nightly build and matching base-data revision before
rehearsal. No new simulator run was performed for this relay implementation.
Earlier local report files are not a passing rehearsal certificate.

Start with one audience camera in OBS, capture 1920 × 1080, overlay above the
capture, and verify the runway remains visible from the audience position.
The existing extra-view helper is retained, but a second camera is optional
and should be added only after measuring frame rate. Verify screen-recording
permissions, current capture window, overlay URL, scene switching and projector
readability on the actual equipment.

Before releasing a performance version:

1. Record exact commits/image, simulator build, aircraft checksum, base-data
   revision, scenery state, profile and OBS settings in the performance log.
2. Fly through the public HTTPS interface and check control direction, throttle,
   braking, two opposing phones and an observer that never affects the count.
3. Hold a control while disabling phone data, interrupting the bridge and
   restarting the relay. Confirm release, retained throttle, visible loss and
   fresh-touch recovery without queued commands.
4. Reset during held input. Confirm the approach is ready before new touches,
   old epochs are rejected and throttle follows the reset aircraft.
5. Verify FlightGear pause and reset remain local actions; release controls
   before unpausing. Verify readiness or generation changes require a fresh
   handshake. Exercise failed-attempt ending and restart.
6. Measure phone-to-visible-aircraft response under actual crowd/network load;
   use p95 below 250 ms as the initial target, then assess with people.

## Hybrid camera and phone input

[Hybrid controls](hybrid-controls.md) combines local camera poses with the relay's
phone aggregate through one local simulator writer. Deploy the hybrid-capable
relay before running the new bridge: older relays reject the additional telemetry.
The updated relay retains the original phone-only protocol. Preparation and local
tests do not deploy this change.

Hybrid bridge telemetry adds bounded, display-only `feedback`: relay epoch and
sequence, remaining validity, combined controls, anonymous command dots, source
counts and per-axis counts. The relay acknowledges hybrid support and still
returns only phone contributions to the bridge. It never feeds combined feedback
back into aggregation. The relay discounts feedback validity by the poll interval,
clears it on reset/reconnect, and hides expired combined results. Bridge WebSocket
frames allow up to 65,536 bytes for these bounded displays; participant frames
retain their 4,096-byte limit. Camera images and landmarks remain local.

Hosted local routes remain read-only, including in hybrid mode. Relay loss removes
phone votes without cancelling camera votes. Reset still clears both input sources.

## LAN fallback

The original route remains available and tested. Stop the hosted launch, then:

```sh
env -u FLIGHT_RELAY_URL uv run fly run karlsruhe-747-landing
```

The fallback launcher starts a new approach and prints the same-Wi-Fi LAN
invitation. The fallback uses HTTP on a trusted LAN, never an internet endpoint. Announce the change and distribute
the new QR/link. Do not run hosted and LAN writers against one simulator.
If neither route works, announce an explicit demonstration or the physical
coordination fallback; do not represent recorded output as live participation.

## Synthetic verification and provenance

```sh
uv run python -m unittest discover -s tests
node --test tests/test_phone_ui.js tests/test_projection_ui.js tests/test_relay_ui.js
uv run python -m scripts.relay_load --clients 140 --rounds 300 --jitter-ms 30
```

[Recorded synthetic measurements](relay-load-2026-11-11.json) come from real
localhost WebSockets and a synthetic simulator state on 11 November 2026:
140 clients, 300 control rounds, 42,001 exchanges over 31.16 seconds, injected
0–30 ms scheduling jitter, 20% disconnect/rejoin, bridge loss/recovery and
simulator-generation reset. p95 input RTT was 26.46 ms, aggregate RTT 1.09 ms,
and a synchronised crowd update reached the bridge at p95 102.36 ms. The
403.95 ms maximum bridge frame interval includes the induced outage. The
harness checks counts, release and recovery and fails on missed deadlines.
These figures exclude public TLS, mobile networks, property-socket writes,
FlightGear rendering and OBS, so they do not satisfy the physical rehearsal gate.

Final local checks passed: 98 Python tests and three JavaScript suites. A
disposable Linux/arm64 Docker container passed the native health command,
UID 10001 check, phone/projection asset checks, authenticated participant-to-
bridge aggregate exchange, observer count and bridge-loss visibility. The
container was stopped after the trial. Its local image identifier was
`sha256:20eab264f4dd429d448a3f3958a7bd0557cc9e763935ca0d71184807c87eb969`. No remote image was published;
an amd64 server build and end-to-end HTTPS/FlightGear rehearsal remain unverified.
The later public HTTPS/health checks above confirm availability, not that this
local image is the deployed artefact.

The implementation started from commit `5f716af` plus reviewed existing
phone/projection work captured separately as `da7907e`. The original migration
backup remains at `/private/tmp/tools-migration-20261111/flight-by-committee`
(history bundle, source snapshot and patches). Only required phone/projection
source was adopted; no local simulator assets, reports or machine settings were
added to Git. No remote branch was published.

### Automatic Coolify origin

Enable Coolify default variables and configure the public HTTPS domain. The relay
uses `COOLIFY_URL` when `FLIGHT_PUBLIC_ORIGIN` is absent. A domain plus its `www`
alias selects the non-`www` origin regardless of order; configure the alias to
redirect there. Unrelated domains, missing settings and malformed values stop
startup. An explicit `FLIGHT_PUBLIC_ORIGIN` takes precedence. Outside Coolify,
supply that explicit origin. No request header determines the trusted origin.


## Shared operator API and Hub preparation

Configure optional `FLIGHT_OPERATOR_TOKEN` as a persistent, distinct URL-safe secret
of 32–128 characters. It must differ from both existing keys. Existing deployments
continue running without it; the operator API then rejects access. Keep this token
runtime-only, and configure the same value as `HUB_FLIGHT_TOKEN` in Hub. Allow the
Flight origin in Hub separately. Do not put the operator token in any URL.

Flight’s `/operator` page accepts this token and uses the same Bearer-authenticated
API available to external clients:

- `GET /api/operator/sessions`: a collection containing the current flight.
- `GET /api/operator/sessions/current`: that same resource, with `id`, `title`,
  `participantUrl` and `status` (`simulator-disconnected`, `simulator-loading` or
  `aircraft-ready`).

Responses are not cached. The page keeps the token only in memory; refreshing the
page requires sign-in again. It exposes the audience invitation as a link and can
refresh status. The operator API cannot join as a participant, attach a bridge,
create another simulator, pause, reset or replace a session. Starting and stopping
the local launcher remains a local operation.

Hub’s show profile selects the `current` resource and retrieves its audience link
automatically at launch. The profile stores no credential. The resource represents
the relay’s single current session, shared by rehearsals; preparing it does not
isolate or restart the simulator. Deploy this API before enabling automatic Flight
preparation in Hub, preserving the existing audience and bridge keys.
