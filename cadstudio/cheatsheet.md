# CAD-Studio – build123d spiekbrief (algebra-modus)

Elke code-part is Python met `from build123d import *` al geïmporteerd. Wijs de 3D-vorm toe aan `result`.
Eenheden: mm. Z = omhoog, het bed is het XY-vlak (Kobra S1: 250 x 250 x 250 mm).
Projectparameters (set_params) zijn gewone variabelen (bv. `w`, `wall`) en ook beschikbaar als `params["w"]`.
`part("naam")` geeft de vorm van een ander part terug (voor booleans, uitlijnen, inleg).
`math` en `np` (numpy) zijn beschikbaar. print() output komt terug in de build-info.

## Primitieven (standaard gecentreerd rond de oorsprong)
```python
Box(l, w, h)                                   # x, y, z
Box(l, w, h, align=(Align.CENTER, Align.CENTER, Align.MIN))   # staat óp z=0
Cylinder(radius, height)                       # as langs Z
Sphere(radius)
Cone(bottom_radius, top_radius, height)
Torus(major_radius, minor_radius)
Wedge(xsize, ysize, zsize, xmin, zmin, xmax, zmax)
```

## Plaatsen en draaien
```python
Pos(x, y, z) * shape            # verplaatsen
Rot(rx, ry, rz) * shape         # roteren in graden (X, dan Y, dan Z)
Pos(0, 0, 5) * Rot(0, 90, 0) * Cylinder(2, 20)
shape.moved(Location((x, y, z)))
mirror(shape, about=Plane.YZ)   # spiegelen in X
```

## Booleans
```python
a + b          # samenvoegen
a - b          # aftrekken (b mag ook een lijst vormen zijn)
a & b          # doorsnede
holes = [loc * Cylinder(1.6, 50) for loc in GridLocations(20, 15, 2, 2)]
plate = plate - holes
spokes = [loc * Box(10, 2, 2) for loc in PolarLocations(radius=15, count=6)]
```

## Selectors (edges/faces) + afronden
```python
s.edges().filter_by(Axis.Z)          # verticale randen
s.edges().group_by(Axis.Z)[-1]       # randen aan de bovenkant
s.faces().sort_by(Axis.Z)[-1]        # bovenvlak
s.faces().sort_by(Axis.Z)[0]         # ondervlak
s.faces().filter_by(Axis.X)          # vlakken met normaal langs X
fillet(s.edges().filter_by(Axis.Z), radius=3)
chamfer(s.edges().group_by(Axis.Z)[-1], length=0.6)
```

## Holle bak / shell
```python
body = Box(60, 40, 20, align=(Align.CENTER, Align.CENTER, Align.MIN))
bak = offset(body, amount=-2, openings=body.faces().sort_by(Axis.Z)[-1])   # wand 2 mm, open boven
```

## 2D-sketches -> 3D
```python
Rectangle(w, h); RectangleRounded(w, h, radius); Circle(r); Ellipse(rx, ry)
RegularPolygon(radius, side_count); Polygon((0,0), (10,0), (5,8)); SlotOverall(length, height)
Text("Tekst", font_size=10, font="Arial")      # font_style=FontStyle.BOLD
extrude(Rectangle(20, 10), amount=5)           # vanaf XY-vlak omhoog
extrude(sketch, amount=2, both=True)           # symmetrisch
Plane.XY.offset(10) * Circle(5)                # sketch op hoogte z=10
Plane.XZ * sketch                              # sketch op voorvlak (normaal = -Y)
Plane.YZ * sketch                              # zijvlak (normaal = +X)
revolve(Plane.XZ * Polygon((0,0),(10,0),(8,20),(0,20)), axis=Axis.Z)   # draaien rond Z (vaas, wiel)
loft([Plane.XY * Circle(10), Plane.XY.offset(20) * Rectangle(8, 8)])
sweep(Plane.YZ * Circle(1), path=Spline((0,0,0), (10,5,5), (20,0,10)))
make_face(Polyline((0,0), (10,0), (10,5), (0,0)))
```
Lijnen/paden: `Line`, `Polyline`, `Spline`, `ThreePointArc`, `CenterArc`, `Helix(pitch, height, radius)`.

## Tekst op een vlak
```python
# reliëf bovenop een plaat van 3 mm dik
label = extrude(Plane.XY.offset(3) * Text("XMAS", font_size=8), amount=0.6)
# inleg in voorwand (vlak), op y = -d/2
label = Plane.XZ.offset(d/2 - 0.8) * Text("XMAS", font_size=9)
inleg = Pos(0, 0, h/2) * extrude(label, amount=0.8)
```

## Multi-color (ACE Pro) – werkwijze
* Elke kleur = een eigen part met `color` (hex) en `filament` (ACE-slot 1-4, tot 8 met 2 ACE's).
* Inleg / tweekleurig: maak het kleur-part, en trek het af van het basis-part: `result = body - part("tekst")`.
  Dan overlappen de volumes niet en snijdt de slicer niets weg.
* Export met export_3mf(mode="assembly") -> één object, onderdelen per extruder, uitgelijnd.
* Min. laagdikte voor een kleurlaag: ~0.4-0.6 mm (2-3 lagen van 0.2). Min. detail ~0.4 mm (nozzle).

## Printbaarheid (FDM, 0.4 nozzle)
* Wanddikte ≥ 1.2 mm (3 lijnen), bij voorkeur 1.6–2.0.
* Overhang ≤ 45°, anders support of chamfer i.p.v. fillet aan de onderkant.
* Passing/speling tussen losse delen: 0.2–0.3 mm per zijde.
* Schroefgaten M3: Ø3.2 doorgang, Ø2.8–2.9 voor zelftappend. Heat-insert M3: Ø4.0–4.2.
* Plat vlak onderaan voor bedhechting.

## Veelgemaakte fouten
* `result` vergeten -> fout "moet een 3D-vorm toewijzen".
* 2D sketch zonder extrude -> geen solids.
* fillet te groot voor de geometrie -> OCCT-fout; kleinere radius.
* Text-font niet gevonden -> valt terug op standaardfont (geen fout).
