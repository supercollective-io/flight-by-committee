# Boeing 747-400 livery workspace

The `supercollective` livery uses oversized lowercase lettering on a warm white
fuselage, an orange stripe, and orange tails and engines with a four-circle motif.
Edit `supercollective.svg` as text or in an SVG editor. FlightGear uses the
4096 × 1024 PNG generated from it.

## Edit and fly

From the repository root:

```sh
uv run python -m scripts.build_livery
uv run fly run karlsruhe-747-landing
```

The build command renders the SVG without launching FlightGear. Launching the
profile also rebuilds it automatically, so the first command is optional.
No GIMP, Inkscape or ImageMagick installation is required for routine builds:
`uv` installs the locked `resvg-py` renderer. The bundled Montserrat font makes
text rendering independent of the computer's installed fonts.

The profile contains this top-level setting, before any TOML table:

```toml
livery = "supercollective"
```

The runner finds the installed 747 in the configured aircraft search directories,
then creates a private aircraft overlay under `test-results/liveries/`. Model XML
and AC3D files are copied into that overlay; textures, sounds and other assets
are linked. Its base paint texture and custom livery XML/PNG point to the artwork
in this repository. The overlay is placed first in FlightGear's aircraft search
path. The original aircraft installation is never modified.

This model's legacy material animation does not switch its visible texture in
the nightly HDR renderer. The overlay supplies our texture at model-load time,
so the profile's livery works with HDR as well. Change the profile and restart to
switch designs; do not rely on the in-simulator livery menu with this renderer.

The runner also prepares the overlay for the terminal simulator test. Each
resolved launch gets its own directory, avoiding conflicts between profiles.
These generated directories can be removed when their simulator runs have ended.
Removing `livery` from the profile restores the original aircraft search path.

The command grants Nasal read access specifically to the repository's livery
directory using `--allow-nasal-read`, because FlightGear checks the destination
of symbolic links when loading the XML. It does not grant access to the whole
repository. Dry runs resolve the selection without building, linking or launching
anything. Livery integration currently supports this 747-400 model only.

For subsequent changes, save the SVG and launch again. If FlightGear is already
running, rebuild with the first command and restart the simulator to avoid its
texture cache. A fresh launch after moving the checkout builds new links using
the new paths. Keep the editable assets here, outside ignored `test-results/`.

## Design layout

- The upper fuselage strip faces left; its main windows are around y=152.
- The lower strip faces right; its main windows are around y=432.
- Engine nacelles occupy the two blocks at the upper right.
- Vertical stabilisers occupy the two lower-left islands. The right-hand island
  is mirrored on the model; the symmetric circle motif reads correctly either
  way. Reverse any lettering you add to that island within its own bounds.
- Winglets occupy the four small islands on the far right.

Keep the `viewBox="0 0 4096 1024"` and these positions unchanged. Edit the SVG's
text, colours, shapes and transforms. The main palette is `#f5f2e9` (warm white),
`#171c24` (near-black) and `#ff512b` (orange). The four-circle motif is defined once
as `collective` and reused. Windows and doors are composited over the artwork;
construction lines are deliberately faint.

Inspect both sides in FlightGear after changing placement: flat texture previews
cannot establish whether lettering crosses a seam or wraps awkwardly.

To create another livery, duplicate both `supercollective.svg` and
`supercollective.xml` under the same new filename stem. Set the XML's `name` to
that stem and `texture` to `Liveries/STEM.png`, then set `livery = "STEM"` in the
profile. Build it independently with `uv run python -m scripts.build_livery STEM`.

## Files and provenance

- `supercollective.svg`: editable project design, including lowercase wordmarks.
- `supercollective.png`: generated texture; do not paint directly into this file.
- `supercollective.xml`: aircraft livery definition.
- `texture.xcf`: unmodified upstream GIMP source, retained for reference.
- `reference/KLM.png` and `reference/KLM.xml`: unmodified upstream example.
- `details/airframe.png`: windows and doors merged from XCF layers 2 and 3.
- `details/construction.png`: XCF layer 1, rendered at low opacity in the SVG.
- `fonts/Montserrat.ttf` and `fonts/OFL.txt`: Montserrat variable font and its
  SIL Open Font Licence, from the [Google Fonts Montserrat directory](https://github.com/google/fonts/tree/main/ofl/montserrat).
- `committee.xml`: earlier manual-workflow example; the profile uses
  `supercollective.xml` instead.
- `COPYING`: GNU GPL version 2 licence text supplied with the aircraft assets.

The XCF, KLM references and COPYING came from the locally installed nightly
747-400 package. The XCF was extracted from `Models/Liveries/texture.zip`.
Retain the upstream licence and provenance alongside the derived texture details.
Commit SVG changes and the regenerated PNG together.

For maintainers, the detail overlays were extracted once using ImageMagick:

```sh
magick 'texture.xcf[2-3]' -background none -layers merge +repage details/airframe.png
magick 'texture.xcf[1]' details/construction.png
```

Package URL recorded by `scripts/install_747.py`:
<https://fgaddon.b-cdn.net/Aircraft-trunk/747-400.zip>

Package SHA-256 recorded by that installer:
`e6cd96ca081891988db2e1bd8480b54850a6fb184cc339cfabdee7c09d7c6e2f`.
