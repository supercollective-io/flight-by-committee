# ADR 0002: Start with FlightGear

Status: **Proposed** · Date: 2026-11-05

## Context

We need one externally controlled aircraft and a projected visual world. Open source is preferred. The simulator must expose controls, telemetry and a repeatable way to start, pause and reset.

## Proposal

Try FlightGear first. It already includes aircraft, scenery and rendering, leaving more effort for the audience experience. The target, clarified on 7 November 2026, is approximately 100 people collectively landing a Boeing 747-400 at the airport nearest Karlsruhe, interpreted as Karlsruhe/Baden-Baden (FKB/EDSB). Verify the four engines, distinctive upper-deck hump and upturned wingtips in the selected model. Start with a repeatable airborne approach in calm weather and test the available show computer before committing. The earlier C172P experiment remains a regression baseline; its results do not establish 747-400 compatibility.

Evaluate its generic protocol for continuous controls and telemetry, and its command interface for occasional lifecycle actions. Verify actual property names, signs, units, reset behaviour and control ownership for the selected aircraft and version. Joystick input, autopilot and scripts must not compete for the same axis.

## Alternatives and trade-offs

JSBSim with a custom renderer would give more visual freedom but requires more integration. YSFlight is another open-source candidate worth considering if its visual character is attractive. X-Plane is a proprietary fallback with a documented web API.

FlightGear reduces initial scope, but aircraft-specific behaviour and hardware compatibility still need testing. This is not a claim that the integration works yet.

## Research informing this choice

Sources checked on 5 November 2026; recheck versions during implementation.

| Candidate | Evidence and relevance |
| --- | --- |
| FlightGear | Complete open-source simulator. The download page lists stable release 2024.1.7 and flags Apple Silicon rendering issues. Its XML-defined generic channels support control/telemetry exchange, including UDP; its command interface supports runtime inspection and commands. These interfaces make it a plausible integration starting point, subject to testing. [Downloads](https://www.flightgear.org/download/), [generic protocol](https://wiki.flightgear.org/Generic_Protocol), [command interface](https://wiki.flightgear.org/Telnet_usage). |
| JSBSim | LGPL-2.1 flight-dynamics library with C++ and Python integration. It needs a visual environment and can also run inside FlightGear. Consider it if a custom world becomes central. [Repository](https://github.com/JSBSim-Team/jsbsim). |
| YSFlight | The author's simulator source is BSD-3-Clause. We have not tested its build or control integration. [Repository](https://github.com/captainys/YSFLIGHT). |
| X-Plane | Proprietary, with REST/WebSocket access. Commands and flight initialisation depend on version. A fallback if the preferred open-source options prove unsuitable. [Web API](https://developer.x-plane.com/article/x-plane-web-api/). |

## Experiment: 6 November 2026

The terminal harness passed all 13 automated checks against FlightGear 2024.1.7 on macOS ARM64: airborne telemetry, pause/resume, running engine, opposite roll/pitch responses and three repeatable baseline comparisons. Seven in-process resets completed without a crash in that run. See the [test procedure](../flightgear-test.md) for tolerances and local evidence.

Earlier runs exposed harness handshake and clock-freeze bugs, which are corrected, and a FlightGear crash in a background scenery/model-loading thread. Readiness now waits for scenery as well as flight dynamics. Visual quality and long-run reliability remain unverified, so the simulator choice remains proposed.

## What would change this

Revise the proposal if rendering, external control or reliable reset fails on the chosen hardware, or if the artistic direction requires a custom world. The first one-phone experiment should produce enough evidence to accept or replace this choice.
