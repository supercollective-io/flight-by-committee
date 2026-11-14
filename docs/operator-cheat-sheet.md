# Hybrid operator cheat sheet

Launch the Karlsruhe 747 landing with the attached webcam and phones joining
through the internet. **The webcam was camera `0` in the setup confirmed on
14 November 2026.**

## Before launch

Use the configured FlightGear installation and local pose model. The private
`.env` file must contain `FLIGHT_RELAY_URL=https://fly.supercollective.io` and the
existing deployed `FLIGHT_BRIDGE_KEY`. The hosted relay must support hybrid mode.
See [relay setup](relay-operations.md#one-command-local-launch) if configuration
is missing.

## Launch

```sh
cd /Users/jo/Documents/dev/flight-by-committee
uv run --env-file .env --extra body --frozen fly
```

1. In the browser operator, choose **Fly with bodies and phones**. This profile
   uses camera **0**.
2. Select **Check setup**, then **Launch these settings**.
3. Confirm the webcam preview shows the participants, including shoulders,
   elbows and hips. Allow camera access in macOS if prompted.
4. Wait for **Aircraft ready** in the operator. Open the local monitor link and
   confirm the relay is connected.
5. Share the existing public participant invitation or its QR code. The invitation
   includes the participant key; the bare homepage does not join the flight.
   Phones can use mobile data or any internet-connected Wi-Fi.
6. Ask phone participants to select **Join flight controls**.
7. Resume the paused flight in FlightGear. Keep the terminal open.

## During the flight

- **Body controls:** raise both arms, tilt your wings to bank, and lean forwards
  or backwards to lower or raise the nose. Lower both arms to withdraw.
- **Use one method at a time:** lower your arms while using a phone; select
  **Stop controlling** before switching from phone to body.
- **Pause or reset:** use FlightGear on the computer.
- **Stop camera input:** press **q** in the preview. Phones and flight continue;
  select **Stop flight**, then **Launch these settings** to restart the flight
  with camera input.
- **Finish:** select **Stop flight** in the operator. Closing the browser does
  not stop the flight. Press **Ctrl+C** in the terminal to close the operator.
- **Connection loss:** the remaining source continues. The flight does not
  pause automatically.

For camera positioning and troubleshooting, see [body controls](body-controls.md).
For contribution weighting and recovery, see [hybrid controls](hybrid-controls.md).
