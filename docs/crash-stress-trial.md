# 747 crash-and-stress trial

Every profile selecting `aircraft = "747-400"` automatically uses crash-and-stress
effects, including new profiles, ground starts and flights without a custom
livery. No profile flag is required. The integration reuses the JA37's GPL
crash-and-stress system (version 0.19) and six sounds. The installed aircraft
remains unchanged: code and sound configuration are
installed into the launcher's private aircraft overlay. Sound is enabled by
default for all profiles. Upstream provenance and licence are in
[the asset directory](../assets/crash-stress/README.md).

## Run

Follow [747 installation](karlsruhe-747.md) first, then from this checkout:

```sh
uv sync --locked
uv run fly run karlsruhe-747-crash-trial --dry-run
uv run fly run karlsruhe-747-crash-trial
```

The flight starts paused on the existing Karlsruhe approach. Use local simulator
controls and enable sound. This profile does not start phone controls or the
projection bridge. Use File → Reset between attempts; the 747 Repair menu also
clears the trial failures and sound state. Repair does not reposition the plane.

## What is included

- Five real landing-gear contacts, and seven belly/nose/wingtip/tail contacts.
  The installer checks their names and order against the pinned 747 package.
- Upstream impact sounds and speed-dependent random failures. The registered
  consequences use the 747's native wing-loss switch and four engine cutoffs.
- Upstream creaking, cracking and wing-detachment sounds, audible from external
  views too. Stress is scaled to the initial flight weight and the aircraft's
  existing 5 g cutoff. This is an experimental scale, not Boeing damage data.
- Startup, pause, replay and reset guards; a one-second impact cooldown prevents
  several simultaneous contact points repeatedly rolling the failure dice.

The upstream system also has a high-speed, fuel-dependent explosion rule; this is inherited game logic,
not a physical fire simulation. There is no added freeze, camera shake,
asymmetric wing model, nacelle contact geometry or damaged mesh. The trial is
intended to reveal whether those additions are necessary.

## Compare four attempts

Use the camera view and speakers intended for the audience. Start with modest
speaker volume before trying the impact sounds.

| Attempt | Observe |
| --- | --- |
| Normal landing | No structural impact sound or damage from wheel contact alone |
| Hard landing | No added wheel-impact cue; upstream crash/stress effects still apply |
| Wingtip strike | Impact sound/message and any native failures; outcomes are probabilistic |
| Nose-first crash | Whether sound and native damage make the crash unmistakable, or whether it still appears to bounce away |

After each, record what was audible, visible and still controllable. Reset and
check that the approach is paused, engines run, wings are restored and sounds
are cleared. Repeat a strike to check that detection still works after reset.
If a catastrophic impact still looks recoverable, evaluate an explicit terminal
crash response next. 

## Verification

```sh
uv run python -m unittest discover -s tests -v
```

Automated tests check automatic 747 integration with and without liveries,
contact-layout rejection and installation
of every script/sound reference. They do not establish audible quality, convincing
damage or reliable physical contact behaviour; those require the simulator trial.

### Local smoke-test evidence

On 2026-11-14, the installed FlightGear Nightly 2024.2.0 loaded the adapter
and exposed all twelve contacts. A deliberate ground impact set the crash-sound
signal and native wing failure. File → Reset restored the paused approach,
cleared damage and sound state, and a second impact triggered again. No trial
Nasal parse/runtime errors were reported. Existing aircraft/base-data warnings
about tied-property listeners and the HDR pipeline remain in the simulator log.

These are telemetry checks, not a listening assessment. The four-attempt
audience-view comparison above is still required.


The automatic integration was also checked with a newly created ground-start
747 profile with no custom livery or approach initialiser. Nightly loaded the
damage system, remained undamaged on the ground, and initialised it again
after Reset without adapter parse/runtime errors.
