# CAD-Studio – build123d cheat sheet (algebra mode)

Every code part is Python with `from build123d import *` already imported. Assign the 3D shape to `result`.
Units: mm. Z = up, the bed is the XY plane (default 250 x 250 x 250 mm).
Project parameters (set_params) are plain variables (e.g. `w`, `wall`) and also available as `params["w"]`.
`part("name")` returns the shape of another part (for booleans, alignment, inlays).
`math` and `np` (numpy) are available. print() output is returned in the build info.

## Primitives (centred on the origin by default)
```python
Box(l, w, h)                                   # x, y, z
Box(l, w, h, align=(Align.CENTER, Align.CENTER, Align.MIN))   # sits on z=0
Cylinder(radius, height)                       # axis along Z
Sphere(radius)
Cone(bottom_radius, top_radius, height)
Torus(major_radius, minor_radius)
Wedge(xsize, ysize, zsize, xmin, zmin, xmax, zmax)
```

## Placing and rotating
```python
Pos(x, y, z) * shape            # move
Rot(rx, ry, rz) * shape         # rotate in degrees (X, then Y, then Z)
Pos(0, 0, 5) * Rot(0, 90, 0) * Cylinder(2, 20)
shape.moved(Location((x, y, z)))
mirror(shape, about=Plane.YZ)   # mirror in X
```

## Booleans
```python
a + b          # union
a - b          # subtract (b may also be a list of shapes)
a & b          # intersection
holes = [loc * Cylinder(1.6, 50) for loc in GridLocations(20, 15, 2, 2)]
plate = plate - holes
spokes = [loc * Box(10, 2, 2) for loc in PolarLocations(radius=15, count=6)]
```

## Selectors (edges/faces) + fillets
```python
s.edges().filter_by(Axis.Z)          # vertical edges
s.edges().group_by(Axis.Z)[-1]       # edges at the top
s.faces().sort_by(Axis.Z)[-1]        # top face
s.faces().sort_by(Axis.Z)[0]         # bottom face
s.faces().filter_by(Axis.X)          # faces with a normal along X
fillet(s.edges().filter_by(Axis.Z), radius=3)
chamfer(s.edges().group_by(Axis.Z)[-1], length=0.6)
```

## Hollow box / shell
```python
body = Box(60, 40, 20, align=(Align.CENTER, Align.CENTER, Align.MIN))
tray = offset(body, amount=-2, openings=body.faces().sort_by(Axis.Z)[-1])   # 2 mm wall, open top
```

## 2D sketches -> 3D
```python
Rectangle(w, h); RectangleRounded(w, h, radius); Circle(r); Ellipse(rx, ry)
RegularPolygon(radius, side_count); Polygon((0,0), (10,0), (5,8)); SlotOverall(length, height)
Text("Text", font_size=10, font="Arial")       # font_style=FontStyle.BOLD
extrude(Rectangle(20, 10), amount=5)           # up from the XY plane
extrude(sketch, amount=2, both=True)           # symmetric
Plane.XY.offset(10) * Circle(5)                # sketch at z=10
Plane.XZ * sketch                              # front plane (normal = -Y)
Plane.YZ * sketch                              # side plane (normal = +X)
revolve(Plane.XZ * Polygon((0,0),(10,0),(8,20),(0,20)), axis=Axis.Z)   # revolve around Z (vase, wheel)
loft([Plane.XY * Circle(10), Plane.XY.offset(20) * Rectangle(8, 8)])
sweep(Plane.YZ * Circle(1), path=Spline((0,0,0), (10,5,5), (20,0,10)))
make_face(Polyline((0,0), (10,0), (10,5), (0,0)))
```
Lines/paths: `Line`, `Polyline`, `Spline`, `ThreePointArc`, `CenterArc`, `Helix(pitch, height, radius)`.

## Text on a face
```python
# embossed on top of a 3 mm plate
label = extrude(Plane.XY.offset(3) * Text("XMAS", font_size=8), amount=0.6)
# inlay in the front wall (flush), at y = -d/2
label = Plane.XZ.offset(d/2 - 0.8) * Text("XMAS", font_size=9)
inlay = Pos(0, 0, h/2) * extrude(label, amount=0.8)
```

## Multi-colour (AMS / ACE Pro / MMU) – workflow
* Each colour = its own part with `color` (hex) and `filament` (slot 1-4, up to 8 with two units).
* Inlay / two-colour: make the colour part and subtract it from the base part: `result = body - part("label")`.
  Then the volumes don't overlap and the slicer doesn't cut anything away.
* Export with export_3mf(mode="assembly") -> one object, parts per extruder, aligned.
* Minimum thickness for a colour layer: ~0.4–0.6 mm (2–3 layers of 0.2). Minimum detail ~0.4 mm (nozzle).
* If several colour parts share helper functions, constants or a profile (a common pattern once a design has
  3+ colour parts), define that once with `set_common_code()` instead of pasting it into every part's code.
  It runs once before each part's own code, in the same namespace, so its functions/variables are just
  available by name afterwards (no `part("...")` needed to reach them).

## Importing a STEP file (real solid, not a mesh)
`import_mesh("name", "file.step")` (same tool, dispatches on extension) gives a real BRep solid, unlike
STL/3MF/OBJ/PLY/GLB imports. `part("stepname")` works normally, so it combines with code geometry via the
regular `+ - &` operators, and can be exported to STEP again:
```python
result = part("bracket") - Cylinder(2, 20)   # "bracket" was imported from a .step file
```

## Combining an imported mesh with your own geometry
`part("name")` only works between build123d parts (it needs an OCCT solid); an imported mesh (from
`import_mesh`) has none, so `part()` raises if you try. Use `mesh_boolean(a, b, op)` instead:
```python
result = mesh_boolean("ref", Cylinder(3, 20), "subtract")   # "union" | "subtract" | "intersect"
```
* `a`/`b` can each be a part name (code part, imported mesh, or another `mesh_boolean()` part), a `(V, F)`
  tuple from `mesh_of("name")`, or a build123d shape built inline (as in the example above).
* Returns a `MeshResult` - assign it straight to `result`. It bypasses build123d entirely, so it can't be
  combined further with `+ - &`, only with more `mesh_boolean()` calls. `scale`/`location` on that part still
  work normally (applied to the resulting triangles).
* It can't be exported to STEP (no BRep solid, same as a plain imported mesh) - 3MF/STL and the preview work fine.
* Needs the meshes to be reasonably watertight; a badly broken import may fail with an error instead of a result.

## Printability (FDM, 0.4 nozzle)
* Wall thickness ≥ 1.2 mm (3 lines), preferably 1.6–2.0. Check with `check_wall_thickness()` - it flags any
  spot thinner than that (default 1.2 mm) and gives you its location.
* No floating regions: every layer must rest on the layer below (or on the bed). `check_floating()` slices the
  parts like a slicer and reports islands - e.g. a cylinder that starts inside a hollow body below its ceiling,
  or a sphere tip hanging into a cavity. Start such features *on* the ceiling instead.
* Overhang ≤ 45°, otherwise supports, or a chamfer instead of a fillet at the bottom. `render_preview(overhangs=True)`
  highlights those spots.
* Clearance between separate parts: 0.2–0.3 mm per side.
* M3 screw holes: Ø3.2 clearance, Ø2.8–2.9 for self-tapping. M3 heat-set insert: Ø4.0–4.2.
* Flat face at the bottom for bed adhesion.

## Common mistakes
* Forgetting `result` -> error "must assign a 3D shape".
* 2D sketch without extrude -> no solids.
* Fillet too large for the geometry -> OCCT error; use a smaller radius.
* Text font not found -> falls back to the default font (no error).
