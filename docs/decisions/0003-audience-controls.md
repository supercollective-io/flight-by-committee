# ADR 0003: Keep audience controls configurable during prototyping

Status: **Proposed** · Date: 2026-11-05

## Context

We do not yet know whether identical controls or distributed roles will make the better performance. Assistance and aggregation affect that experience too. The research below supports experimenting rather than assuming one arrangement will work.

## Research informing this choice

Sources checked on 5 November 2026.

### Carpenter's 1991 demonstration

[Kevin Kelly's account in *Out of Control*](https://kk.org/mt-files/outofcontrol/ch2-b.html) describes nearly 5,000 people using two-sided coloured paddles tracked by a camera. A shared display made their contributions visible. The audience played Pong and formed collective images before flying an aircraft. For flight, one side controlled roll and the other pitch. Kelly describes overcorrection, aborted approaches and an eventual collective roll.

This is a historical narrative, not a controlled evaluation. It supports exploring distributed roles and a progression from simple shared feedback to flight. It does not establish a successful landing method or phone-network capacity.

**Our interpretation:** making influence visible and learning together are part of the performance. Start simply, allow recovery to be meaningful, and distinguish aircraft-response delay from network delay when tuning controls.

### Legion: real-time crowd control

[Lasecki et al., *Real-time Crowd Control of Existing Interfaces*, UIST 2011](https://www.cs.rochester.edu/hci/pubs/pdfs/roboturk.pdf) presents Legion and compares individual control, serialised crowd input, windowed voting, an active random controller and an agreement-selected leader. Evaluations involved robot navigation and spreadsheet entry using online workers, not an audience flying an aircraft.

The paper reports that voting can mix incompatible plans; a leader can maintain continuity and avoid waiting for each voting window. It also reports confusion when individual inputs were not reflected in the interface. Showing chosen inputs encouraged copying in an experiment where agreement affected rewards. Specialised groups are discussed as future work, not validated by those evaluations.

**Our interpretation:** prototype feedback and mediation together. Show accepted input, group intent and aircraft response separately; test whether feedback helps understanding or merely encourages following. Leadership is an alternative if continuity becomes essential, but it changes the artistic premise of simultaneous collective control. The paper does not validate our proposed arithmetic mean or assistance settings.

## Proposal

Build one small control path with configurable settings, rather than separate applications:

- **Distribution:** everyone controls roll and pitch, or two groups control one axis each. Change roles between rounds.
- **Assistance:** begin with bounded bank and climb/descent requests; compare direct control-surface commands. Assistance needs tuning and must be visible to participants. Zero surface input is not the same as level flight.
- **Aggregation:** start with the arithmetic mean of the latest eligible input per session, separately for each axis. More messages must not increase a session's weight. Bound inputs and tune modest smoothing during rehearsal.

Neutral input counts; disconnected or expired input does not. If a required role becomes empty, pause or enter an explicitly selected assisted state. Show the input distribution so disagreement is not hidden by a zero mean.

An anonymous session is not proof of one person. Preserve identity across ordinary reconnects; strict prevention of multiple-session voting would require a separate identity or ticket choice.

## Alternatives and trade-offs

A fixed scheme would be simpler, but could commit us before we understand the interaction. Majority voting can turn a narrow preference into a full command; median aggregation suppresses minority influence; choosing a leader concentrates control. An average is transparent but permits cancellation. Keep the experiment small rather than adding every possible cockpit role.

## What would change this

Use the [small-group rehearsal](../plan.md#compare-the-experience) to choose a production arrangement. Change the algorithm or assistance if participants cannot understand their influence, or if the flight response makes coordination unrewarding.
