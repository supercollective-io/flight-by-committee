# Local livery studio

Develop the SVG on the actual FlightGear 747-400 exterior geometry, with automatic
texture updates. Nothing is uploaded or published. The server listens on loopback.

## Start

Install the aircraft using the project's normal setup, then install the Assimp
command-line converter (on macOS, `brew install assimp`). From the repository root:

```sh
npm ci --prefix preview
uv run python -m scripts.preview_livery
```

Open <http://127.0.0.1:8765>. Use `--port 8766` if that port is occupied, or
`--profile NAME` to preview another profile with a 747-400 livery setting.
Stop the server with Ctrl+C. Node/npm is only needed to install the pinned Three.js
dependency; Python serves the application and watches the design files.

## Design loop

1. Choose a **Design** in the dropdown, then open its SVG in
   `assets/liveries/747-400/` in your editor. Each alternative is retained separately.
2. Start with **Orbit** (front left), **Front right ¾**, **Rear left ¾** and
   **Rear right ¾**. These perspective presets use the same distance and height
   around the aircraft, and remain freely rotatable. Check the name at these
   angles before using **Both sides** to inspect alignment and texture seams.
   The side and other fixed views use orthographic projection.
3. Choose **Pin this design** before an edit. The pin holds the current texture
   in this browser tab; **Live** and **Pinned** switch textures without moving
   the camera. You can also select another design and compare it with the pin.
   Refreshing the browser clears the pin.
4. Save the SVG. The server checks every 0.5 s, renders it with the same build
   function used by FlightGear, and updates the preview. Invalid edits show an
   error while keeping the last good texture visible; fixing and saving recovers
   automatically. Detail-overlay and font changes are watched too.
5. Try both sides, three-quarter angles, daylight and dusk. Check the name at
   smaller sizes and with wings crossing the fuselage. **Save image** downloads
   the current view as a PNG, including both elevations in the split view.
6. Launch `uv run fly run karlsruhe-747-landing` for the final simulator check.

The generated PNG is still the texture used by the simulator. Saving the SVG
updates that ignored output file. Commit the SVG source; the PNG is rebuilt
automatically after checkout. Textures render at 8192 × 2048 while the SVG retains
its 4096 × 1024 coordinate system.
The source-file link opens the SVG for inspection, not an in-browser editor.

## Model fidelity and limits

Assimp converts the installed aircraft's fuselage, wings, gear and engine meshes
to glTF, retaining their UV coordinates. Engine placements are read from the
aircraft's XML and converted from FlightGear's Z-up coordinates to glTF's Y-up
coordinates. The aircraft installation is read-only. Converted geometry is cached
under ignored `test-results/preview-models/`, and regenerated when mesh content
changes. Heavy aircraft assets remain outside Git.

This is a static exterior design preview: it does not execute FlightGear's Nasal
scripts, animations or HDR effects. Gear visibility is a display toggle, not a
retraction simulation. FlightGear remains authoritative for final lighting,
materials, control-surface positions and the flight view. The model's upstream
licence remains in its installation and in the livery workspace's `COPYING`.

The browser polls `/state`; it only replaces the livery material textures when
the PNG content changes. Camera, lighting and comparison state remain in place.
No CDN or network connection is required after installing dependencies and assets.

The server discovers SVG/XML pairs when it starts; restart after adding a new
design. Optional display labels live in `assets/liveries/747-400/designs.json`.
Each browser tab selects independently. Preview selection does not change the
profile: set its top-level `livery` to the chosen filename stem before flying.
