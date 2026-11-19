---
name: cad-design
description: Ontwerp 3D-printbare onderdelen in CAD-Studio (build123d) en exporteer multi-color 3MF voor de Kobra S1 + ACE Pro. Gebruik bij vragen om iets te ontwerpen, modelleren of printklaar te maken, of om een 3MF/STL/STEP te maken.
---

# Ontwerpen met CAD-Studio

Je werkt via de `cad-studio` MCP-tools op een server (meestal een Docker-container). De gebruiker kijkt live mee in de web-editor; `open_editor` geeft de URL.

## Werkwijze

1. **Inventariseer**: `get_project` (of `new_project` voor iets nieuws). Lees `get_build123d_reference` als je de API niet zeker weet.
2. **Maten als parameters**: alle hoofdmaten via `set_params` (bv. `L`, `B`, `H`, `wall`, `clearance`). Zo kan de gebruiker ze later met sliders aanpassen.
3. **Eén part per kleur/onderdeel** met `set_part(name, code, color, filament)`. De code is build123d en wijst de vorm toe aan `result`. Gebruik `part("naam")` om naar een ander part te verwijzen.
4. **Controleer altijd**:
   - lees `ok`, `size`, `bbox_min/max` en `watertight` uit het antwoord van `set_part`;
   - `render_preview()` en kijk echt naar het beeld: klopt de oriëntatie, staat tekst goed leesbaar, zit de inleg op de goede plek?
   - herstel fouten aan de hand van de traceback vóór je verdergaat.
5. **Exporteer** met `export_3mf()` (standaard één object, één extruder per part). Geef de gebruiker:
   - de `download_url`;
   - per ACE-slot welke kleur er in moet (`filament_slots`);
   - eventuele `warnings` (bv. meer dan 4 slots).

## Multi-color (ACE Pro)

- Een kleur = een part met een eigen `filament` (slot 1-4, 5-8 = tweede ACE).
- Inleg: kleur-part maken en aftrekken van het basis-part: `result = body - part("tekst")`. Volumes mogen niet overlappen.
- Kleurlagen ≥ 0.6 mm dik, details ≥ 0.4 mm breed.

## Printbaarheid (FDM, 0.4 mm nozzle)

- Wanden ≥ 1.2 mm (liefst 1.6–2.0), plat vlak onderop, overhang ≤ 45° (chamfer onderaan i.p.v. fillet).
- Passing tussen losse delen 0.2–0.3 mm per zijde. Past het model op het bed (250×250×250)? Gebruik `measure`.

## Bestanden van de gebruiker

De server staat mogelijk niet op de pc van de gebruiker: lokale paden werken daar niet.
- Laat de gebruiker het bestand uploaden in de editor (knop *Import*) of in de inbox-map zetten, en gebruik dan `list_inbox` + `import_mesh(file_path=...)`.
- Of gebruik `import_mesh(url=...)` met een directe download-URL.
- Vanuit Claude Code kan een lokaal bestand ook geüpload worden:
  `curl -H "Authorization: Bearer $CADSTUDIO_TOKEN" -F file=@model.stl "$CADSTUDIO_URL/api/import"`
