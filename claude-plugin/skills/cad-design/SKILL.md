---
name: cad-design
description: Design 3D-printable parts in CAD-Studio (build123d) and export multi-colour 3MF for Orca/Bambu/Anycubic/Prusa slicers. Use when asked to design, model or make something print-ready, or to produce a 3MF/STL/STEP.
---

# Designing with CAD-Studio

You work through the `cad-studio` MCP tools on a server (usually a Docker container). The user watches live in the web editor; `open_editor` returns the URL. Reply in the user's language.

## Workflow

1. **Take stock**: `get_project` (or `new_project` for something new). Read `get_build123d_reference` if you're unsure about the API.
2. **Dimensions as parameters**: put all main dimensions in `set_params` (e.g. `L`, `W`, `H`, `wall`, `clearance`) so the user can adjust them with sliders later.
3. **One part per colour/component** with `set_part(name, code, color, filament)`. The code is build123d and assigns the shape to `result`. Use `part("name")` to reference another part.
4. **Always verify**:
   - read `ok`, `size`, `bbox_min/max` and `watertight` from the `set_part` response;
   - call `render_preview()` and actually look at the image: is the orientation right, is text readable, is the inlay in the right place?
   - fix errors using the traceback before continuing.
   - before exporting: `check_floating()` (nothing may print in mid-air - the slicer's "floating regions"
     warning), `check_wall_thickness()` and `check_bridges()` (long spans sag); fix what they report and run them again.
5. **Prepare the print** (ask how the part is used if you don't know: what loads it, must it seal, is it seen):
   - `suggest_orientation(load_direction=...)` - pick the side that faces the bed; layer lines are the weak
     direction, so a part that is pulled or bent should have the load running along the layers. Apply with
     `apply=<rank>`, then run `render_preview()`, `check_floating()` and `check_bridges()` again.
   - `set_print_settings(profile=...)` - `functional` / `strong` / `watertight` / `decorative` / `draft` / `fine`,
     plus overrides; per part for e.g. a decorative inlay on a strong body. The settings go into the 3MF.
   - tell the user in two lines which orientation and settings you chose and why.
6. **Export** with `export_3mf()` (default: one object, one extruder per part). Give the user:
   - the `download_url`;
   - which colour goes in which filament slot (`filament_slots`);
   - any `warnings` (e.g. more than 4 slots).

## Assembly (multi-part builds)

When several printed parts go together (a body on a chassis, wheels on axles), describe the assembly so the user can
see the end result. Preferred: in each printed part's code set `assembled = <shape in assembled position>` next to
`result` (a dict for several pieces). For anything else: one `set_assembly_item(name, code, color)` per component, in the assembled position (rotate parts
printed upside down back; add reference objects like a motor or rails too). Check it with `render_assembly()`
(`ghost=["body"]` to look inside, `section="y"` to cut it open, `explode=1` for an exploded view) and give the user a
picture with `export_assembly_png()`. Run `check_assembly_fit()` (one item per physical component) to catch
parts that overlap or jam. Assembly items are never exported or sliced.

Use the built-in helpers (`spur_gear`, `d_hole`, `teardrop`, `pin_hole`, `screw_boss`, `magnet_pocket`, ...)
instead of writing them again, and offer a `tolerance_coupon()` before a design with tight fits.

## Inserts (magnets, nuts)

Enclose them: subtract `magnet_pocket(d, h)` with at least 0.6 mm above it, set `pause_at = [top of the pocket]`
in the part's code, and tell the user at which layer the print pauses (slice_plate and export_3mf report it;
the exported 3MF carries the pause when opened as a project in the slicer).

## Multi-colour (AMS / ACE Pro / MMU)

- One colour = one part with its own `filament` (slot 1-4, 5-8 = second unit).
- Inlay: make the colour part and subtract it from the base: `result = body - part("label")`. Volumes must not overlap.
- Colour layers ≥ 0.6 mm thick, details ≥ 0.4 mm wide.

## Printability (FDM, 0.4 mm nozzle)

- Walls ≥ 1.2 mm (preferably 1.6–2.0), a flat face at the bottom, overhangs ≤ 45° (chamfer instead of fillet at the bottom).
- Clearance between separate parts 0.2–0.3 mm per side. Does it fit the bed? Use `measure`.
- Parts that don't fit on one bed together (e.g. two 200 mm spool halves): give each its own build plate
  (`set_part(..., plate=2)`) or call `arrange_plates()` — never park a part off the bed. Name each plate after what is
  on it with `set_plate_name(plate, name)`; the slicer shows that name. `export_3mf` then writes
  all plates into one project file — tell the user to open it as a project (File → Open project), not import it
  as geometry (`split_plates=True` for one file per plate).

## User files

The server may not be on the user's computer: local paths don't work there.
- Ask the user to upload the file in the editor (*Import* button) or drop it in the inbox folder, then use `list_inbox` + `import_mesh(file_path=...)`.
- Or use `import_mesh(url=...)` with a direct download URL.
- From Claude Code a local file can also be uploaded:
  `curl -H "Authorization: Bearer $CADSTUDIO_TOKEN" -F file=@model.stl "$CADSTUDIO_URL/api/import"`
