# Flight by Committee

Approximately 100 people use a phone web app to collectively land a simulated Boeing 747-400 on a shared projection. The aircraft must visibly have four engines, the distinctive upper-deck hump and upturned wingtips. The destination is the airport nearest Karlsruhe, interpreted as Karlsruhe/Baden-Baden (FKB/EDSB). See the [implementation plan](plan.md) for the target scenario and next steps.

The project prefers open source. The venue, simulator and final control arrangement remain open. The target audience is approximately 100 people. The terminal simulator harness is an initial implementation experiment. The audience interface and hosted relay are implemented and publicly deployed at [fly.supercollective.io](https://fly.supercollective.io); public interface and health checks passed on 12 November 2026. See [hosted operations](relay-operations.md) for the scope and remaining checks. The simulator has passed initial automated feasibility checks; visual quality and rehearsal suitability remain unverified.

## Start here

- [Hybrid operator cheat sheet](operator-cheat-sheet.md): launch webcam 0 with phones joining over the internet.

- [Local operator app](local-operator.md): run `uv run fly` to choose, edit, save and launch profiles.

- [747-400 landing at Karlsruhe](karlsruhe-747.md): launch and validate the target Nightly/HDR/WS3 scenario.

- [747-400 livery workspace](../assets/liveries/747-400/README.md): edit the aircraft artwork and preview it in FlightGear.
- [Live 3D livery studio](../preview/README.md): edit the SVG and inspect changes on the aircraft without restarting the simulator.
- [FlightGear profiles](flightgear-profiles.md): choose saved flights, configure installations and run Python with uv.
- [Terminal simulator test](flightgear-test.md): run the FlightGear feasibility harness and interpret its report.
- [FlightGear nightly and Amsterdam](flightgear-nightly.md): reproduce the HDR scenery setup and find the local installation paths.
- [Implementation plan](plan.md): what to build first and what to learn.
- [Documentation approach](decisions/0001-documentation.md): keeping these notes lean and easy to change.
- [Simulator](decisions/0002-simulator.md): proposed choice and supporting research.
- [Audience controls](decisions/0003-audience-controls.md): proposed experiments, Carpenter's demonstration and Legion research.
- [Runtime and networking](decisions/0004-runtime.md): proposed architecture and deployment.

- [Hosted Flight controls](relay-operations.md): relay, outbound bridge, Coolify, recovery and LAN fallback.
- [Body controls](body-controls.md): operator-selected camera input, bent-elbow wings, torso lean and voluntary rest.
- [Hybrid controls](hybrid-controls.md): equal-weight camera and phone contributions in one flight.
