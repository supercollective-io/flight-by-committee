# Flight by Committee

A room of people uses a phone web app to collectively fly one simulated aircraft on a shared projection. This repository will implement that software. These notes preserve the initial research and give implementation a starting point.

The project prefers open source. Audience size, venue, simulator and final control arrangement remain open. The terminal simulator harness is an initial implementation experiment. The audience application is not implemented, and the simulator has passed the initial automated feasibility checks; visual quality and rehearsal suitability remain unverified.

## Start here

- [FlightGear profiles](flightgear-profiles.md): choose saved flights, configure installations and run Python with uv.
- [Terminal simulator test](flightgear-test.md): run the FlightGear feasibility harness and interpret its report.
- [FlightGear nightly and Amsterdam](flightgear-nightly.md): reproduce the HDR scenery setup and find the local installation paths.
- [Implementation plan](plan.md): what to build first and what to learn.
- [Documentation approach](decisions/0001-documentation.md): keeping these notes lean and easy to change.
- [Simulator](decisions/0002-simulator.md): proposed choice and supporting research.
- [Audience controls](decisions/0003-audience-controls.md): proposed experiments, Carpenter's demonstration and Legion research.
- [Runtime and networking](decisions/0004-runtime.md): proposed architecture and deployment.
