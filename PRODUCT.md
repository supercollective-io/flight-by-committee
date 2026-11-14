# Flight by Committee

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users and purpose

An operator prepares and runs a local FlightGear simulation for collective
control. The existing target scenario is a Boeing 747-400 landing at
Karlsruhe/Baden-Baden; audience control uses the phone interface and optional
hosted relay. See [the project guide](docs/README.md).

## Operator workflow

Run `uv run fly`, select a profile, inspect its values, edit or duplicate it,
check installed assets and launch. The operator app remains available between
flights. Saving settings is explicit and separate from launching. New profiles
can be created through the same interface. The command-line launcher remains
available for automation and diagnostics.

## Constraints

Python owns configuration validation and the simulator lifecycle. TOML remains
the profile format. The local app binds to loopback; participant controls retain
their separate local-network or relay connection. Browser settings prepare the
next launch. Pause and reset remain in FlightGear in this first version.

Arbitrary-location startup and reset still require simulator validation. Address
search and generalised runway scenarios are future work. Synthetic interface and
process tests do not establish aircraft behaviour or venue readiness.

## Interface commitments

Extend the existing [design system](DESIGN.md): British English, metric values,
labelled keyboard-accessible controls, readable progress and recoverable errors.
