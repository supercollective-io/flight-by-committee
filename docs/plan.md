# Implementation plan

This is a starting direction, not a fixed specification. The [ADRs](README.md) contain the proposed technical choices; change them as experiments produce better information.

## Target scenario

Confirmed by the project owner on 7 November 2026:

- Approximately 100 people collectively land one simulated Boeing 747-400.
- The aircraft visibly has four engines, the distinctive upper-deck hump and upturned wingtips.
- The destination is the airport nearest Karlsruhe. The working interpretation is Karlsruhe/Baden-Baden (FKB/EDSB), the nearby commercial airport. The [airport operator identifies the airport and its codes](https://www.baden-airpark.de/app/uploads/2024/06/FBO.pdf).
- Participants use phones; the shared projection shows the aircraft and collective feedback.

The C172P feasibility checks and Amsterdam/UFO visual exploration are supporting experiments. They do not validate the target aircraft or landing scenario.

## What matters

People should understand their own contribution, the group's combined intent and the aircraft's response. The projection is central to that experience. Keep phone controls simple enough that people can look up.

Begin the prototype with an already airborne 747-400 in calm weather on a repeatable approach. Turning and maintaining flight can serve as introductory exercises. The end goal is a collective landing; recovery and disagreement can remain part of the performance.

## Build in small steps

The [747-400 Nightly scenario](karlsruhe-747.md) now provides a saved runway 03
approach at EDSB, with HDR and WS3 scenery. On 7 November 2026 it passed 27
automated checks covering the four engines, landing configuration, descent,
control response and repeatable reset. The profile records the initial approach
and fuel configuration; the guide defines provisional landing-success criteria.

The project owner reported a successful manual landing on 8 November 2026.
The individual phone trial succeeded. The implemented next slice is
[shared phone controls](phone-controls.md): equal per-session averages of
pitch, roll, rudder, all-engine throttle and wheel brakes. Gear and flaps remain
preset. The computer owns pause, resume and reset. Lost input releases momentary
controls while retaining throttle and allowing flight to continue. This is the
chosen behaviour for the single-phone slice, superseding the pause-on-expiry
suggestion in the original control/runtime ADRs. The group uses the same fallback when everyone is inactive. Next, validate
collective feedback and coordination with 2–4 phones, then 8–12 people.

| Step | Build | Learn before expanding |
| --- | --- | --- |
| One phone, one plane | Connect browser input through a server to the validated 747-400 approach; read telemetry; pause and reset | Does the chosen simulator render well on the available computer? Are controls, units and reset predictable? |
| A small ensemble | Combine inputs and try shared controls versus two roles with 8–12 people | Can participants recognise their influence? Which arrangement is enjoyable and understandable? |
| A performance prototype | Add projected group feedback, operator controls and connection recovery | Can people look up? Can the operator recover without a confusing restart? |
| Venue rehearsal | Run the actual devices, projection and network with approximately 100 participants | Can everyone join and participate for the full duration? What fails, and what is the fallback? |

The first group milestone is a twelve-person rehearsal of the target approach, followed by a rehearsal with approximately 100 participants. Custom scenery, a complete cockpit and thousands of simultaneous phones can wait.

## Compare the experience

Try the same simple manoeuvre under shared and distributed controls. Compare assisted and direct flight separately where practical. Vary the order so later attempts do not always benefit from practice.

Ask participants what they controlled, how the room's input affected the aircraft and when they felt ignored or confused. Observe time looking at phones, empty roles and operator interventions. Record a short dated result near the relevant ADR; create a separate rehearsal report only when there is enough evidence to justify one.

The projection should distinguish individual participation, conflicting inputs, the combined command and the actual aircraft response. Opposing inputs averaging to zero is different from everyone releasing the controls. Show that difference.

## Check failure cases early

- Lock a phone or switch tabs while holding a command: its contribution must expire.
- Interrupt and restore a connection: old queued controls must not replay into the current round.
- Disconnect everyone: verify neutral momentary controls, retained throttle and continuing flight. Role-specific fallback remains a later experiment.
- Stop the coordination server: an independent simulator-side fallback must prevent the last command being held indefinitely.
- Reset the simulator while phones are active: discard previous-round input.

Aim initially for a 95th-percentile delay below 200 ms from phone input to projected command feedback. This is a proposed tuning target, not a measured capability. Measure it separately from the aircraft's physical response and include display latency, not just server processing.

Synthetic clients can test server load. They cannot validate a room full of radios. Test actual joining, Wi-Fi, screen locking and reconnection before promising capacity.

## Questions to resolve as work starts

The project owner still needs to choose the intended feeling of the performance and approximate duration. The target audience size is approximately 100 people. The venue determines network access and projection constraints. Available hardware and visual ambition inform simulator selection. Decide how much participant data to record before the first recorded rehearsal; keep only what is useful for the experiment.

There is no committed language, framework or delivery date yet. Choose the implementation stack after the simulator connection works and the people doing the work are known.
