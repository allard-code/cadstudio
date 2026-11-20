// SPDX-License-Identifier: GPL-3.0-or-later
// Tiny i18n: t("key", {var}) + data-i18n / data-i18n-title / data-i18n-placeholder / data-i18n-html attributes.
// Add a language by adding an object to STRINGS with the same keys (missing keys fall back to English).

export const STRINGS = {
  en: {
    "project.new": "＋ Project", "project.new.title": "New project", "project.prompt": "Name of the new project:",
    "add.box": "▭ Box", "add.cylinder": "◯ Cylinder", "add.sphere": "● Sphere", "add.text": "T Text", "add.code": "{ } Code",
    "import": "⤓ Import", "import.title": "Import STL/3MF/OBJ as a reference", "import.done": "Imported: {name}",
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
    "view.iso": "Iso", "view.front": "Front", "view.top": "Top", "view.right": "Right", "view.fit": "Fit",
    "view.undo": "↶ Undo", "view.undo.title": "Undo last part edit (Ctrl+Z)",
    "view.redo": "↷ Redo", "view.redo.title": "Redo (Ctrl+Shift+Z)",
    "view.move": "✥ Move", "view.move.title": "Move the selected part with arrows (G). Hold Shift to snap (10 mm).",
    "view.rotate": "↻ Rotate", "view.rotate.title": "Rotate the selected part with rings (R). Hold Shift to snap (15°).",
    "view.resize": "⤢ Resize", "view.resize.title": "Stretch the selected part per axis with handles (S). Hold Shift to snap (0.1×).",
    "view.xray": "◐ X-ray", "view.xray.title": "Transparent (X)", "view.edges": "▦ Edges", "view.edges.title": "Edges (E)",
    "view.bed": "▤ Bed", "view.bed.title": "Show print bed",
    "dims.total": "Total", "dims.toobig": "⚠ larger than the bed",
    "insp.hint": "Select a part in the list or in the 3D view.",
    "howto.title": "Working with Claude", "howto.ask": "For example, ask Claude:",
    "howto.example": "Make an 80×50×30 mm tray with 2 mm walls, rounded corners and my name as a red inlay on the front. Export as 3MF.",
    "howto.live": "Changes made by Claude appear here live. Afterwards you can tweak parameters, colours and code yourself.",
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
    "project.new": "＋ Project", "project.new.title": "Nieuw project", "project.prompt": "Naam van het nieuwe project:",
    "add.box": "▭ Blok", "add.cylinder": "◯ Cilinder", "add.sphere": "● Bol", "add.text": "T Tekst", "add.code": "{ } Code",
    "import": "⤓ Import", "import.title": "STL/3MF/OBJ importeren als referentie", "import.done": "Geïmporteerd: {name}",
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
    "view.iso": "Iso", "view.front": "Voor", "view.top": "Boven", "view.right": "Rechts", "view.fit": "Passend",
    "view.undo": "↶ Ongedaan maken", "view.undo.title": "Laatste wijziging ongedaan maken (Ctrl+Z)",
    "view.redo": "↷ Opnieuw", "view.redo.title": "Opnieuw uitvoeren (Ctrl+Shift+Z)",
    "view.move": "✥ Verplaats", "view.move.title": "Verplaats geselecteerd onderdeel met pijlen (G). Shift ingedrukt = raster van 10 mm.",
    "view.rotate": "↻ Roteer", "view.rotate.title": "Roteer het geselecteerde onderdeel met ringen (R). Shift ingedrukt = stappen van 15°.",
    "view.resize": "⤢ Uitrekken", "view.resize.title": "Rek het geselecteerde onderdeel per as uit met handvatten (S). Shift ingedrukt = stappen van 0,1×.",
    "view.xray": "◐ X-ray", "view.xray.title": "Doorzichtig (X)", "view.edges": "▦ Randen", "view.edges.title": "Randen (E)",
    "view.bed": "▤ Bed", "view.bed.title": "Printbed tonen",
    "dims.total": "Totaal", "dims.toobig": "⚠ groter dan bed",
    "insp.hint": "Selecteer een onderdeel in de lijst of in de 3D-view.",
    "howto.title": "Werken met Claude", "howto.ask": "Vraag Claude bijvoorbeeld:",
    "howto.example": "Maak een bakje van 80×50×30 mm met 2 mm wand, afgeronde hoeken en mijn naam in rood als inleg op de voorkant. Exporteer als 3MF.",
    "howto.live": "Wijzigingen van Claude verschijnen hier live. Jij kunt daarna parameters, kleuren en code aanpassen.",
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
