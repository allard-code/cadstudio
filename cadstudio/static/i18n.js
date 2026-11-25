// SPDX-License-Identifier: GPL-3.0-or-later
// Tiny i18n: t("key", {var}) + data-i18n / data-i18n-title / data-i18n-placeholder / data-i18n-html attributes.
// Add a language by adding an object to STRINGS with the same keys (missing keys fall back to English).

export const STRINGS = {
  en: {
    "asm.tab": "⚙ Assembly", "asm.tab.title": "Show how the printed parts go together (the assembly), instead of the build plates",
    "asm.explode": "Explode", "asm.show": "show", "asm.ghost": "see-through",
    "asm.png": "⤓ Picture (PNG)", "asm.png.title": "Download a picture of the assembly as shown (view, hidden/see-through items, explode, section)",
    "plates.all": "All beds", "plates.plate": "Bed {i}", "plates.add": "Add a build plate (bed)",
    "plates.remove": "Remove the selected bed (its parts move to the previous bed)",
    "plates.remove.confirm": "Remove bed {i}? Its parts move to bed {to}.",
    "plates.arrange": "⊞ Arrange", "plates.arrange.title": "Spread all printable parts over as many beds as needed (adds beds automatically)",
    "plates.arrange.done": "Arranged over {n} bed(s)", "plates.tab.title": "Show only bed {i} (key {i}; 0 = all beds)",
    "plates.over": "⚠ bed {i} is overfull - use Arrange or move a part to another bed",
    "insp.plate": "Build plate (bed)",
    "export.plates.title": "Several beds: how to export them", "export.plates.all": "all beds in 1 file",
    "export.plates.split": "1 file per bed", "export.plates.current": "only the shown bed",
    "project.new": "＋ Project", "project.new.title": "New project", "project.prompt": "Name of the new project:",
    "add.box": "▭ Box", "add.cylinder": "◯ Cylinder", "add.sphere": "● Sphere", "add.text": "T Text", "add.code": "{ } Code",
    "import": "⤓ Import", "import.title": "Import STL/3MF/OBJ as a reference, or STEP as a real editable solid", "import.done": "Imported: {name}",
    "export.mode.title": "Layout", "export.mode.assembly": "1 object (multi-colour)", "export.mode.objects": "separate objects",
    "export.3mf": "Export 3MF", "export.saved": "✓ Saved: {path}",
    "live.title": "Live connection: changes made by Claude appear immediately",
    "params": "Parameters", "params.add": "Add parameter", "params.empty": "No parameters yet. Variables here can be used in all code.",
    "presets.select": "Presets…", "presets.save": "Save current parameters as a preset",
    "presets.delete": "Delete selected preset",
    "params.prompt.name": "Parameter name (e.g. wall):", "params.prompt.value": "Value:", "params.remove": "remove",
    "parts": "Parts", "parts.empty": "Empty project. Add a shape or ask Claude to design something.",
    "parts.visible": "visible", "parts.slot": "filament slot",
    "common": "Shared code", "common.hint": "(runs before every part's code)",
    "common.placeholder": "Helper functions / constants reused by several parts, e.g.:\ndef rod(r, l): return Cylinder(r, l)",
    "common.build": "▶ Build all",
    "notes": "Notes", "notes.placeholder": "Requirements, dimensions, ideas… (Claude reads this too)",
    "checkpoints": "Checkpoints", "checkpoints.hint": "Full project snapshots you can restore to later",
    "checkpoints.select": "Checkpoints…", "checkpoints.save": "Save the current project as a checkpoint",
    "checkpoints.restore": "Restore selected checkpoint", "checkpoints.delete": "Delete selected checkpoint",
    "checkpoints.confirm": "Restore \"{name}\"? This replaces the current project state (not undoable).",
    "view.iso": "Iso", "view.front": "Front", "view.top": "Top", "view.right": "Right", "view.fit": "Fit",
    "view.undo": "↶ Undo", "view.undo.title": "Undo last part edit (Ctrl+Z)",
    "view.redo": "↷ Redo", "view.redo.title": "Redo (Ctrl+Shift+Z)",
    "view.move": "✥ Move", "view.move.title": "Move the selected part with arrows (G). Hold Shift to snap (10 mm).",
    "view.rotate": "↻ Rotate", "view.rotate.title": "Rotate the selected part with rings (R). Hold Shift to snap (15°).",
    "view.resize": "⤢ Resize", "view.resize.title": "Stretch the selected part per axis with handles (S). Hold Shift to snap (0.1×).",
    "view.xray": "◐ X-ray", "view.xray.title": "Transparent (X)", "view.edges": "▦ Edges", "view.edges.title": "Edges (E)",
    "view.overhangs": "⚠ Overhangs", "view.overhangs.title": "Highlight downward-facing surfaces steeper than 45° - these need support material (O)",
    "view.measure": "📏 Measure", "view.measure.title": "Click two points on a part to see the distance between them (M)",
    "measure.hint1": "Measure: click a point on a part…", "measure.hint2": "Measure: click a second point…",
    "measure.distance": "Distance",
    "view.clip": "✂ Section", "view.clip.title": "Cut the model with a plane to see the interior",
    "view.clip.flip": "Flip the cut direction",
    "view.bed": "▤ Bed", "view.bed.title": "Show print bed",
    "dims.total": "Total", "dims.toobig": "⚠ larger than the bed",
    "insp.hint": "Select a part in the list or in the 3D view.",
    "howto.title": "Working with Claude", "howto.ask": "For example, ask Claude:",
    "howto.example": "Make an 80×50×30 mm tray with 2 mm walls, rounded corners and my name as a red inlay on the front. Export as 3MF.",
    "howto.live": "Changes made by Claude appear here live. Afterwards you can tweak parameters, colours and code yourself.",
    "version.build": "build {commit} of {date}", "version.dev": "development version (no build info)",
    "version.latest": "latest version", "version.update": "update available ({commit})",
    "version.nocheck": "could not check for updates", "version.orca": "OrcaSlicer {v}",
    "insp.name": "Name", "insp.color": "Colour", "insp.filament": "Filament / slot",
    "insp.visible": "visible", "insp.export": "export",
    "insp.location": "Position (mm) & rotation (°) — applied after the code",
    "insp.scale": "Scale (× per axis) — stretches the part about its own centre",
    "insp.code": "build123d code", "insp.code.hint": "(Ctrl+Enter = build, assign to <b>result</b>)",
    "insp.build": "▶ Build", "insp.duplicate": "Duplicate", "insp.delete": "Delete",
    "insp.delete.confirm": "Delete '{name}'?", "insp.discard": "Discard unbuilt code changes?",
    "insp.external": "The code was changed externally (by Claude?) while you were typing. Click ‘Build’ to keep your version, or select the part again to load the new one.",
    "insp.mesh": "# imported mesh: {file}\n# (only position/rotation, colour and slot can be changed)",
    "slot.option": "{i}", "slot.second": "{i}  (2nd unit)",
    "info.built": "✓ built in {s}s · {tris} triangles", "info.watertight": " · watertight", "info.notwatertight": " · ⚠ not watertight",
    "info.size": "size", "info.volume": "volume {cm3} cm³ (≈ {g} g PLA at 100% infill)",
    "lang.title": "Language",
  },
  nl: {
    "asm.tab": "⚙ Samenstel", "asm.tab.title": "Laat zien hoe de geprinte onderdelen in elkaar zitten (het samenstel), in plaats van de bedden",
    "asm.explode": "Uit elkaar", "asm.show": "tonen", "asm.ghost": "doorzichtig",
    "asm.png": "⤓ Afbeelding (PNG)", "asm.png.title": "Afbeelding van het samenstel downloaden zoals getoond (aanzicht, verborgen/doorzichtige delen, uit elkaar, doorsnede)",
    "plates.all": "Alle bedden", "plates.plate": "Bed {i}", "plates.add": "Bed (printplaat) toevoegen",
    "plates.remove": "Geselecteerd bed verwijderen (onderdelen gaan naar het vorige bed)",
    "plates.remove.confirm": "Bed {i} verwijderen? De onderdelen gaan naar bed {to}.",
    "plates.arrange": "⊞ Verdeel", "plates.arrange.title": "Verdeel alle printbare onderdelen over zoveel bedden als nodig (voegt zelf bedden toe)",
    "plates.arrange.done": "Verdeeld over {n} bed(den)", "plates.tab.title": "Toon alleen bed {i} (toets {i}; 0 = alle bedden)",
    "plates.over": "⚠ bed {i} is te vol - gebruik Verdeel of zet een onderdeel op een ander bed",
    "insp.plate": "Printplaat (bed)",
    "export.plates.title": "Meerdere bedden: hoe exporteren", "export.plates.all": "alle bedden in 1 bestand",
    "export.plates.split": "1 bestand per bed", "export.plates.current": "alleen getoond bed",
    "project.new": "＋ Project", "project.new.title": "Nieuw project", "project.prompt": "Naam van het nieuwe project:",
    "add.box": "▭ Blok", "add.cylinder": "◯ Cilinder", "add.sphere": "● Bol", "add.text": "T Tekst", "add.code": "{ } Code",
    "import": "⤓ Import", "import.title": "STL/3MF/OBJ importeren als referentie, of STEP als echte bewerkbare solid", "import.done": "Geïmporteerd: {name}",
    "export.mode.title": "Indeling", "export.mode.assembly": "1 object (multi-color)", "export.mode.objects": "losse objecten",
    "export.3mf": "Exporteer 3MF", "export.saved": "✓ Opgeslagen: {path}",
    "live.title": "Live verbonden: wijzigingen van Claude verschijnen direct",
    "params": "Parameters", "params.add": "Parameter toevoegen", "params.empty": "Nog geen parameters. Variabelen hier zijn bruikbaar in alle code.",
    "presets.select": "Presets…", "presets.save": "Huidige parameters opslaan als preset",
    "presets.delete": "Geselecteerde preset verwijderen",
    "params.prompt.name": "Naam van de parameter (bv. wall):", "params.prompt.value": "Waarde:", "params.remove": "verwijderen",
    "parts": "Onderdelen", "parts.empty": "Leeg project. Voeg een vorm toe of vraag Claude om iets te ontwerpen.",
    "parts.visible": "zichtbaar", "parts.slot": "filament-slot",
    "common": "Gedeelde code", "common.hint": "(draait vóór de code van elk onderdeel)",
    "common.placeholder": "Hulpfuncties / constanten die meerdere onderdelen gebruiken, bv.:\ndef rod(r, l): return Cylinder(r, l)",
    "common.build": "▶ Bouw alles",
    "notes": "Notities", "notes.placeholder": "Eisen, maten, ideeën… (Claude leest dit ook)",
    "checkpoints": "Checkpoints", "checkpoints.hint": "Volledige projectsnapshots om later naar terug te gaan",
    "checkpoints.select": "Checkpoints…", "checkpoints.save": "Huidig project opslaan als checkpoint",
    "checkpoints.restore": "Geselecteerd checkpoint terugzetten", "checkpoints.delete": "Geselecteerd checkpoint verwijderen",
    "checkpoints.confirm": "\"{name}\" terugzetten? Dit vervangt de huidige projectstatus (niet ongedaan te maken).",
    "view.iso": "Iso", "view.front": "Voor", "view.top": "Boven", "view.right": "Rechts", "view.fit": "Passend",
    "view.undo": "↶ Ongedaan maken", "view.undo.title": "Laatste wijziging ongedaan maken (Ctrl+Z)",
    "view.redo": "↷ Opnieuw", "view.redo.title": "Opnieuw uitvoeren (Ctrl+Shift+Z)",
    "view.move": "✥ Verplaats", "view.move.title": "Verplaats geselecteerd onderdeel met pijlen (G). Shift ingedrukt = raster van 10 mm.",
    "view.rotate": "↻ Roteer", "view.rotate.title": "Roteer het geselecteerde onderdeel met ringen (R). Shift ingedrukt = stappen van 15°.",
    "view.resize": "⤢ Uitrekken", "view.resize.title": "Rek het geselecteerde onderdeel per as uit met handvatten (S). Shift ingedrukt = stappen van 0,1×.",
    "view.xray": "◐ X-ray", "view.xray.title": "Doorzichtig (X)", "view.edges": "▦ Randen", "view.edges.title": "Randen (E)",
    "view.overhangs": "⚠ Overhang", "view.overhangs.title": "Markeer neerwaartse vlakken steiler dan 45° - deze hebben support nodig (O)",
    "view.measure": "📏 Meten", "view.measure.title": "Klik twee punten op een onderdeel om de afstand te zien (M)",
    "measure.hint1": "Meten: klik een punt op een onderdeel…", "measure.hint2": "Meten: klik een tweede punt…",
    "measure.distance": "Afstand",
    "view.clip": "✂ Doorsnede", "view.clip.title": "Snijd het model met een vlak om de binnenkant te zien",
    "view.clip.flip": "Snijrichting omdraaien",
    "view.bed": "▤ Bed", "view.bed.title": "Printbed tonen",
    "dims.total": "Totaal", "dims.toobig": "⚠ groter dan bed",
    "insp.hint": "Selecteer een onderdeel in de lijst of in de 3D-view.",
    "howto.title": "Werken met Claude", "howto.ask": "Vraag Claude bijvoorbeeld:",
    "howto.example": "Maak een bakje van 80×50×30 mm met 2 mm wand, afgeronde hoeken en mijn naam in rood als inleg op de voorkant. Exporteer als 3MF.",
    "howto.live": "Wijzigingen van Claude verschijnen hier live. Jij kunt daarna parameters, kleuren en code aanpassen.",
    "version.build": "build {commit} van {date}", "version.dev": "ontwikkelversie (geen build-info)",
    "version.latest": "nieuwste versie", "version.update": "update beschikbaar ({commit})",
    "version.nocheck": "kon niet controleren op updates", "version.orca": "OrcaSlicer {v}",
    "insp.name": "Naam", "insp.color": "Kleur", "insp.filament": "Filament / slot",
    "insp.visible": "zichtbaar", "insp.export": "exporteren",
    "insp.location": "Positie (mm) & rotatie (°) — na de code toegepast",
    "insp.scale": "Schaal (× per as) — rekt het onderdeel uit om zijn eigen midden",
    "insp.code": "build123d-code", "insp.code.hint": "(Ctrl+Enter = bouwen, wijs toe aan <b>result</b>)",
    "insp.build": "▶ Bouwen", "insp.duplicate": "Dupliceren", "insp.delete": "Verwijderen",
    "insp.delete.confirm": "'{name}' verwijderen?", "insp.discard": "Niet-gebouwde codewijzigingen weggooien?",
    "insp.external": "Code is extern gewijzigd (door Claude?) terwijl jij aan het typen was. Klik ‘Bouwen’ om jouw versie te bewaren, of selecteer het onderdeel opnieuw voor de nieuwe.",
    "insp.mesh": "# geïmporteerde mesh: {file}\n# (alleen positie/rotatie, kleur en slot zijn aan te passen)",
    "slot.option": "{i}", "slot.second": "{i}  (2e unit)",
    "info.built": "✓ gebouwd in {s}s · {tris} driehoeken", "info.watertight": " · waterdicht", "info.notwatertight": " · ⚠ niet waterdicht",
    "info.size": "maat", "info.volume": "volume {cm3} cm³ (≈ {g} g PLA bij 100% infill)",
    "lang.title": "Taal",
  },
};

const pick = () => {
  try { const s = localStorage.getItem("cs_lang"); if (s && STRINGS[s]) return s; } catch { /* storage unavailable */ }
  return (navigator.language || "en").toLowerCase().startsWith("nl") ? "nl" : "en";
};
export let LANG = pick();

export function t(key, vars = {}) {
  const s = (STRINGS[LANG] && STRINGS[LANG][key]) ?? STRINGS.en[key] ?? key;
  return s.replace(/\{(\w+)\}/g, (_, k) => (k in vars ? vars[k] : `{${k}}`));
}

export function applyI18n(root = document) {
  document.documentElement.lang = LANG;
  root.querySelectorAll("[data-i18n]").forEach((el) => (el.textContent = t(el.dataset.i18n)));
  root.querySelectorAll("[data-i18n-html]").forEach((el) => (el.innerHTML = t(el.dataset.i18nHtml)));
  root.querySelectorAll("[data-i18n-title]").forEach((el) => (el.title = t(el.dataset.i18nTitle)));
  root.querySelectorAll("[data-i18n-placeholder]").forEach((el) => (el.placeholder = t(el.dataset.i18nPlaceholder)));
}

export function setLang(lang) {
  if (!STRINGS[lang]) return;
  LANG = lang;
  try { localStorage.setItem("cs_lang", lang); } catch { /* ignore */ }
  applyI18n();
}
