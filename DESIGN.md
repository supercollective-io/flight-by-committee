# Interface design

## Direction

Applied on 12 November 2026, following Supercollective Tools main at
`9d5ada3` and the approved “Redesign tools interfaces” conversation.
The requested direction is functional, bold, almost Swiss: strong Helvetica
hierarchy, square controls, flat surfaces and copy tied to real actions or states.
No slogans, decorative imagery, external fonts or added performance rhetoric.

## Foundations

- Local `Helvetica Neue`, Helvetica, Arial, sans-serif stack.
- Paper `#f3f3ef`, ink `#191919`, white fields and muted text `#555650`.
- Neutral rules `#bfc1b8`, field borders `#85877e`, focus blue `#2455cc`.
- Lime `#e3fa49` identifies current or selected states; primary buttons are ink.
- Minimum 44 px targets, visible focus, browser zoom and narrow-screen reflow.
- Sentence case and British English. Keep participant/generated text distinct
  from interface copy. Explain exceptional recovery when it occurs.

## Surfaces

Controls, monitor and livery studio use Operate mode; the projection is an
Experience surface that overlays the flight. The touch pad and vertical throttle
remain the primary controls. Circles and crosshairs communicate positions rather
than decorate the interface. Ink marks an individual command; olive `#354f12`
marks the group command. Their dot/ring shapes distinguish them without colour.

The monitor is read-only: its local-control button and handler are removed.
Simulator instructions remain. Participant control legends and explanatory
guidance were removed after user review. Projection retains a transparent page with an opaque
readable data panel. The studio keeps the aircraft model as the main surface and
uses lime for selected camera views. Design-description prose is omitted. Aircraft
textures and liveries are unchanged.

Controls support arrow-key steering and held Space/Enter for rudder and brakes.
Key-up, blur and disconnect release keyboard inputs. Touch cancellation and
simultaneous throttle/pad behaviour remain covered by existing tests.

Styles remain local to `scripts/phone/index.html`, `scripts/phone/projection.html`
and `preview/studio.css`; no runtime dependency on Tools is introduced.

## Verification

- All 98 Python unittest tests passed.
- All three Node UI suites passed, including added keyboard release checks.
- Synthetic browser review exercised pointer and keyboard input, release and
  stopping control, plus monitor and projection states at 390 px and 1440 px.
- Livery studio rendered the installed aircraft with mobile and desktop captures.
- Screenshots: `test-results/design/tools-alignment/`. Mobile studio evidence uses
  separate viewport captures because the full-page WebGL capture repeated an area.
- Independent read-only critique verified that the apparent repeated studio content
  was a capture artefact. The user subsequently removed the keyboard hint because
  participants use touch on their phones; keyboard controls remain available.
- Current Vercel Web Interface Guidelines reviewed on 12 November 2026 from
  https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md.
- Impeccable detector: Helvetica is deliberate; QR and texture images receive their
  sources at runtime. Pad geometry is intentionally edge-to-edge. Removed whole-panel
  disabled opacity so labels remain readable.

Browser flight replies were synthetic, with no simulator control, paid calls or
deployment. Keyboard tests and viewport emulation do not establish physical-device
or venue readiness. The local livery preview is not a live FlightGear lighting test.
