# Implementation plan

This is a starting direction, not a fixed specification. The [ADRs](README.md) contain the proposed technical choices; change them as experiments produce better information.

## What matters

People should understand their own contribution, the group's combined intent and the aircraft's response. The projection is central to that experience. Keep phone controls simple enough that people can look up.

Begin with an already airborne aircraft in calm weather. Turning and maintaining flight are better first experiments than requiring a crowd to complete take-off or landing. Recovery and disagreement may become part of the performance; a successful landing need not be the only satisfying ending.

## Build in small steps

| Step | Build | Learn before expanding |
| --- | --- | --- |
| One phone, one plane | Connect browser input through a server to a simulator; read telemetry; pause and reset | Does the chosen simulator render well on the available computer? Are controls, units and reset predictable? |
| A small ensemble | Combine inputs and try shared controls versus two roles with 8–12 people | Can participants recognise their influence? Which arrangement is enjoyable and understandable? |
| A performance prototype | Add projected group feedback, operator controls and connection recovery | Can people look up? Can the operator recover without a confusing restart? |
| Venue rehearsal | Run the actual devices, projection and network at the intended audience size | Can everyone join and participate for the full duration? What fails, and what is the fallback? |

The first worthwhile milestone is a twelve-person rehearsal. Custom scenery, a complete cockpit and thousands of simultaneous phones can wait.

## Compare the experience

Try the same simple manoeuvre under shared and distributed controls. Compare assisted and direct flight separately where practical. Vary the order so later attempts do not always benefit from practice.

Ask participants what they controlled, how the room's input affected the aircraft and when they felt ignored or confused. Observe time looking at phones, empty roles and operator interventions. Record a short dated result near the relevant ADR; create a separate rehearsal report only when there is enough evidence to justify one.

The projection should distinguish individual participation, conflicting inputs, the combined command and the actual aircraft response. Opposing inputs averaging to zero is different from everyone releasing the controls. Show that difference.

## Check failure cases early

- Lock a phone or switch tabs while holding a command: its contribution must expire.
- Interrupt and restore a connection: old queued controls must not replay into the current round.
- Remove everyone from a required role: deliberately pause or enter a selected assisted state.
- Stop the coordination server: an independent simulator-side fallback must prevent the last command being held indefinitely.
- Reset the simulator while phones are active: discard previous-round input.

Aim initially for a 95th-percentile delay below 200 ms from phone input to projected command feedback. This is a proposed tuning target, not a measured capability. Measure it separately from the aircraft's physical response and include display latency, not just server processing.

Synthetic clients can test server load. They cannot validate a room full of radios. Test actual joining, Wi-Fi, screen locking and reconnection before promising capacity.

## Questions to resolve as work starts

The project owner needs to choose the intended feeling of the performance, approximate duration and audience size. The venue determines network access and projection constraints. Available hardware and visual ambition inform simulator selection. Decide how much participant data to record before the first recorded rehearsal; keep only what is useful for the experiment.

There is no committed language, framework or delivery date yet. Choose the implementation stack after the simulator connection works and the people doing the work are known.
