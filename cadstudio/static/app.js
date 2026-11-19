import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { TransformControls } from "three/addons/controls/TransformControls.js";

// ------------------------------------------------------------------ state
const S = {
  project: null,          // summary from server
  selected: null,         // part name
  meshes: new Map(),      // name -> {key, mesh, edges}
  xray: false, edges: true, bed: true, move: false,
  dirtyCode: false,
};
const $ = (s, r = document) => r.querySelector(s);
const api = async (url, opts = {}) => {
  const r = await fetch(url, { headers: { "Content-Type": "application/json" }, ...opts });
  const ct = r.headers.get("content-type") || "";
  const body = ct.includes("json") ? await r.json() : await r.arrayBuffer();
  if (!r.ok) throw new Error((body && body.error) || (body && body.detail) || r.statusText);
  return body;
};
const toast = (msg, cls = "", ms = 4500) => {
  const d = document.createElement("div");
  d.className = "t " + cls; d.innerHTML = msg;
  $("#toast").appendChild(d); setTimeout(() => d.remove(), ms);
};

// ------------------------------------------------------------------ three.js scene (Z-up, mm)
const vp = $("#viewport");
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setClearColor(0x1a1d22);
vp.appendChild(renderer.domElement);
const scene = new THREE.Scene();
THREE.Object3D.DEFAULT_UP.set(0, 0, 1);
const camera = new THREE.PerspectiveCamera(40, 1, 0.5, 5000);
camera.up.set(0, 0, 1);
camera.position.set(-160, -220, 160);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true; controls.dampingFactor = 0.12;
controls.target.set(0, 0, 10);
scene.add(new THREE.HemisphereLight(0xffffff, 0x404050, 1.6));
const sun = new THREE.DirectionalLight(0xffffff, 1.6); sun.position.set(-150, -250, 300); scene.add(sun);
const fill = new THREE.DirectionalLight(0xffffff, 0.5); fill.position.set(200, 150, 80); scene.add(fill);

// build plate 250 x 250 centred on origin
const bedGroup = new THREE.Group(); scene.add(bedGroup);
function buildBed(w = 250, d = 250) {
  bedGroup.clear();
  const plate = new THREE.Mesh(new THREE.PlaneGeometry(w, d),
    new THREE.MeshStandardMaterial({ color: 0x23272e, roughness: 1, transparent: true, opacity: 0.9 }));
  plate.position.z = -0.05; bedGroup.add(plate);
  const g10 = new THREE.GridHelper(w, w / 10, 0x3a404a, 0x2c3139); g10.rotation.x = Math.PI / 2; bedGroup.add(g10);
  const g50 = new THREE.GridHelper(w, w / 50, 0x56606e, 0x56606e); g50.rotation.x = Math.PI / 2; g50.position.z = 0.01; bedGroup.add(g50);
  const axes = new THREE.AxesHelper(30); axes.position.set(-w / 2, -d / 2, 0.02); bedGroup.add(axes);
}
buildBed();

const partsGroup = new THREE.Group(); scene.add(partsGroup);
const tc = new TransformControls(camera, renderer.domElement);
tc.setSize(0.8);
scene.add(tc.getHelper ? tc.getHelper() : tc);
tc.addEventListener("dragging-changed", (e) => {
  controls.enabled = !e.value;
  if (!e.value) commitMove();
});

function resize() {
  const w = vp.clientWidth, h = vp.clientHeight;
  renderer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix();
}
new ResizeObserver(resize).observe(vp); resize();
(function loop() { controls.update(); renderer.render(scene, camera); requestAnimationFrame(loop); })();

// picking
const ray = new THREE.Raycaster(); const ptr = new THREE.Vector2(); let downAt = null;
renderer.domElement.addEventListener("pointerdown", (e) => { downAt = [e.clientX, e.clientY]; });
renderer.domElement.addEventListener("pointerup", (e) => {
  if (!downAt || Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 4 || tc.dragging) return;
  const r = renderer.domElement.getBoundingClientRect();
  ptr.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
  ray.setFromCamera(ptr, camera);
  const hits = ray.intersectObjects([...S.meshes.values()].map((m) => m.mesh).filter((m) => m.visible));
  select(hits.length ? hits[0].object.userData.name : null);
});

function material(color) {
  return new THREE.MeshStandardMaterial({
    color, roughness: 0.55, metalness: 0.05, side: THREE.DoubleSide,
    transparent: S.xray, opacity: S.xray ? 0.35 : 1, depthWrite: !S.xray,
    polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1,
  });
}

async function loadMesh(part) {
  const info = part.info || {};
  const cur = S.meshes.get(part.name);
  if (!info.ok) { if (cur) cur.mesh.visible = false; return; }
  if (cur && cur.key === info.key) return;
  const buf = await api(`/api/mesh/${encodeURIComponent(part.name)}`);
  const head = new Uint32Array(buf, 0, 2);
  const nv = head[0], nt = head[1];
  const pos = new Float32Array(buf, 8, nv * 3);
  const idx = new Uint32Array(buf, 8 + nv * 12, nt * 3);
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  geo.setIndex(new THREE.BufferAttribute(idx, 1));
  geo.computeVertexNormals();
  geo.computeBoundingBox();
  const centre = geo.boundingBox.getCenter(new THREE.Vector3());
  geo.translate(-centre.x, -centre.y, -centre.z);   // gizmo sits in the middle of the part
  const mesh = new THREE.Mesh(geo, material(part.color));
  mesh.position.copy(centre);
  mesh.userData.name = part.name; mesh.userData.base = centre.clone();
  const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geo, 25),
    new THREE.LineBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.35 }));
  mesh.add(edges);
  if (cur) { if (tc.object === cur.mesh) tc.detach(); partsGroup.remove(cur.mesh); cur.mesh.geometry.dispose(); }
  partsGroup.add(mesh);
  S.meshes.set(part.name, { key: info.key, mesh, edges });
}

function syncSceneProps() {
  const names = new Set(S.project.parts.map((p) => p.name));
  for (const [n, m] of S.meshes) if (!names.has(n)) { if (tc.object === m.mesh) tc.detach(); partsGroup.remove(m.mesh); S.meshes.delete(n); }
  for (const p of S.project.parts) {
    const m = S.meshes.get(p.name); if (!m) continue;
    m.mesh.visible = p.visible && p.info.ok;
    m.mesh.material.dispose(); m.mesh.material = material(p.color);
    m.edges.visible = S.edges;
    if (p.name === S.selected) m.mesh.material.emissive = new THREE.Color(0x3a1d05);
  }
  bedGroup.visible = S.bed;
  attachGizmo();
  updateDims();
}

function bbox(names) {
  const b = new THREE.Box3();
  for (const p of S.project.parts) {
    if (names && !names.includes(p.name)) continue;
    if (!names && !p.visible) continue;
    if (!p.info.ok) continue;
    b.expandByPoint(new THREE.Vector3(...p.info.bbox_min)); b.expandByPoint(new THREE.Vector3(...p.info.bbox_max));
  }
  return b;
}
function updateDims() {
  const all = bbox();
  let t = "";
  if (!all.isEmpty()) {
    const s = all.getSize(new THREE.Vector3());
    t += `Totaal  ${s.x.toFixed(1)} × ${s.y.toFixed(1)} × ${s.z.toFixed(1)} mm`;
    if (s.x > 250 || s.y > 250 || s.z > 250) t += "  ⚠ groter dan bed";
  }
  const p = S.selected && S.project.parts.find((q) => q.name === S.selected);
  if (p && p.info.ok) {
    const [x, y, z] = p.info.size;
    t += `\n${p.name}  ${x.toFixed(1)} × ${y.toFixed(1)} × ${z.toFixed(1)} mm` + (p.info.volume_mm3 ? `  ·  ${(p.info.volume_mm3 / 1000).toFixed(2)} cm³` : "");
  }
  $("#dims").textContent = t || "—";
}

function setView(v) {
  const b = bbox(); const c = b.isEmpty() ? new THREE.Vector3(0, 0, 10) : b.getCenter(new THREE.Vector3());
  const r = b.isEmpty() ? 80 : Math.max(b.getSize(new THREE.Vector3()).length(), 20);
  const d = r * 1.6;
  const dirs = { iso: [-0.6, -0.9, 0.7], front: [0, -1, 0.0001], top: [0, -0.0001, 1], right: [1, 0, 0.0001], fit: null };
  const dir = dirs[v] ? new THREE.Vector3(...dirs[v]).normalize()
    : camera.position.clone().sub(controls.target).normalize();
  controls.target.copy(c); camera.position.copy(c.clone().add(dir.multiplyScalar(d)));
}

// ------------------------------------------------------------------ gizmo move -> location
function attachGizmo() {
  const m = S.selected && S.meshes.get(S.selected);
  if (S.move && m && m.mesh.visible) { if (tc.object !== m.mesh) tc.attach(m.mesh); }
  else tc.detach();
}
async function commitMove() {
  const obj = tc.object; if (!obj) return;
  const name = obj.userData.name; const p = S.project.parts.find((q) => q.name === name);
  const d = obj.position.clone().sub(obj.userData.base); if (d.lengthSq() < 1e-9) return;
  const loc = [...p.location]; loc[0] += +d.x.toFixed(2); loc[1] += +d.y.toFixed(2); loc[2] += +d.z.toFixed(2);
  await savePart(name, { location: loc });
  // the mesh is reloaded from the server with the new location baked in
}

// ------------------------------------------------------------------ UI: params
function renderParams() {
  const box = $("#params"); box.innerHTML = "";
  const params = S.project.params || {};
  for (const [k, v] of Object.entries(params)) {
    const row = document.createElement("div"); row.className = "param";
    if (typeof v === "number") {
      const max = Math.max(10, Math.abs(v) * 3), step = Number.isInteger(v) ? 1 : 0.1;
      row.innerHTML = `<span title="${k}">${k}</span><input type="range" min="0" max="${max}" step="${step}" value="${v}"><input type="number" step="${step}" value="${v}"><span class="x" title="verwijderen">✕</span>`;
      const [range, num] = row.querySelectorAll("input");
      range.oninput = () => (num.value = range.value);
      range.onchange = () => setParam(k, parseFloat(range.value));
      num.onchange = () => setParam(k, parseFloat(num.value));
    } else {
      row.innerHTML = `<span title="${k}">${k}</span><input value='${JSON.stringify(v).replace(/'/g, "&#39;")}' style="grid-column:span 2"><span class="x">✕</span>`;
      row.querySelector("input").onchange = (e) => { let val; try { val = JSON.parse(e.target.value); } catch { val = e.target.value; } setParam(k, val); };
    }
    row.querySelector(".x").onclick = () => setParam(k, null);
    box.appendChild(row);
  }
  if (!Object.keys(params).length) box.innerHTML = `<div class="muted">Nog geen parameters. Variabelen hier zijn bruikbaar in alle code.</div>`;
}
async function setParam(k, v) {
  try { apply(await api("/api/params", { method: "PUT", body: JSON.stringify({ params: { [k]: v } }) })); }
  catch (e) { toast(e.message, "err"); }
}
$("#addParam").onclick = () => {
  const name = prompt("Naam van de parameter (bv. wall):"); if (!name) return;
  const val = prompt("Waarde:", "2"); if (val === null) return;
  setParam(name.trim(), isNaN(+val) ? val : +val);
};

// ------------------------------------------------------------------ UI: parts list
function renderParts() {
  const box = $("#parts"); box.innerHTML = "";
  for (const p of S.project.parts) {
    const d = document.createElement("div");
    d.className = "part" + (p.name === S.selected ? " sel" : "") + (p.visible ? "" : " hidden");
    d.innerHTML = `<span class="eye ${p.visible ? "" : "off"}" title="zichtbaar">👁</span>
      <span class="sw" style="background:${p.color}"></span>
      <span class="nm">${p.name}</span>
      ${p.type === "mesh" ? '<span class="mesh">mesh</span>' : ""}
      ${p.info.ok ? "" : '<span class="err" title="' + (p.info.error || "").replace(/"/g, "'") + '">⚠</span>'}
      <span class="slot" title="filament / ACE-slot">F${p.filament}</span>`;
    d.onclick = (e) => { if (e.target.classList.contains("eye")) return; select(p.name); };
    d.querySelector(".eye").onclick = () => savePart(p.name, { visible: !p.visible });
    box.appendChild(d);
  }
  if (!S.project.parts.length) box.innerHTML = `<div class="muted">Leeg project. Voeg een vorm toe of vraag Claude om iets te ontwerpen.</div>`;
}

// ------------------------------------------------------------------ UI: inspector
function renderInspector(force = false) {
  const ins = $("#inspector");
  const p = S.selected && S.project.parts.find((q) => q.name === S.selected);
  if (!p) {
    if (!ins.classList.contains("empty")) { ins.className = "empty"; ins.innerHTML = $("#inspectorTpl").dataset.empty; }
    return;
  }
  if (ins.classList.contains("empty") || ins.dataset.part !== p.name || force) {
    ins.className = ""; ins.dataset.part = p.name;
    ins.innerHTML = $("#inspectorTpl").innerHTML;
    const fil = $("#pFilament");
    for (let i = 1; i <= 8; i++) fil.add(new Option(`${i}${i <= 4 ? "  (ACE Pro slot " + i + ")" : "  (2e ACE slot " + (i - 4) + ")"}`, i));
    $("#pName").onchange = (e) => savePart(p.name, { new_name: e.target.value.trim() }, e.target.value.trim());
    $("#pColor").onchange = (e) => savePart(S.selected, { color: e.target.value });
    $("#pFilament").onchange = (e) => savePart(S.selected, { filament: +e.target.value });
    $("#pVisible").onchange = (e) => savePart(S.selected, { visible: e.target.checked });
    $("#pExport").onchange = (e) => savePart(S.selected, { export: e.target.checked });
    ins.querySelectorAll(".loc input").forEach((inp) => inp.onchange = () => {
      const loc = [...ins.querySelectorAll(".loc input")].map((i) => parseFloat(i.value) || 0);
      savePart(S.selected, { location: loc });
    });
    const code = $("#pCode");
    code.oninput = () => { S.dirtyCode = true; $("#pRun").classList.add("dirty"); };
    code.onkeydown = (e) => {
      if (e.key === "Tab") { e.preventDefault(); const s = code.selectionStart; code.setRangeText("    ", s, code.selectionEnd, "end"); code.oninput(); }
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); runCode(); }
    };
    $("#pRun").onclick = runCode;
    $("#pDup").onclick = async () => apply(await api(`/api/parts/${encodeURIComponent(S.selected)}/duplicate`, { method: "POST" }));
    $("#pDel").onclick = async () => {
      if (!confirm(`'${S.selected}' verwijderen?`)) return;
      const n = S.selected; S.selected = null;
      apply(await api(`/api/parts/${encodeURIComponent(n)}`, { method: "DELETE" }));
    };
    S.dirtyCode = false;
  }
  $("#pName").value = p.name;
  $("#pColor").value = p.color.length === 7 ? p.color : "#cccccc";
  $("#pFilament").value = p.filament;
  $("#pVisible").checked = p.visible; $("#pExport").checked = p.export;
  ins.querySelectorAll(".loc input").forEach((inp, i) => { if (document.activeElement !== inp) inp.value = +(+p.location[i]).toFixed(3); });
  const code = $("#pCode");
  if (p.type === "mesh") { code.value = `# geïmporteerde mesh: ${p.mesh_file}\n# (alleen verplaatsen/roteren, kleur en slot zijn aan te passen)`; code.disabled = true; $("#pRun").disabled = true; }
  else if (!S.dirtyCode) { code.value = p.code; code.disabled = false; $("#pRun").disabled = false; $("#pRun").classList.remove("dirty"); }
  else if (code.value !== p.code && force !== "keep") toast("Code is extern gewijzigd (door Claude?) terwijl jij aan het typen was. Klik ‘Bouwen’ om jouw versie te bewaren, of selecteer het onderdeel opnieuw voor de nieuwe.", "", 7000);
  const info = $("#pInfo"); const i = p.info;
  if (i.ok) {
    info.className = "info ok";
    info.textContent = `✓ gebouwd in ${i.build_s}s · ${i.triangles} driehoeken${i.watertight === false ? " · ⚠ niet waterdicht" : i.watertight ? " · waterdicht" : ""}\nmaat  ${i.size.map((v) => v.toFixed(2)).join(" × ")} mm\nmin   ${i.bbox_min.join(", ")}\nmax   ${i.bbox_max.join(", ")}` +
      (i.volume_mm3 ? `\nvolume ${(i.volume_mm3 / 1000).toFixed(2)} cm³ (≈ ${(i.volume_mm3 / 1000 * 1.24).toFixed(1)} g PLA bij 100% infill)` : "") +
      (i.stdout ? `\n\nprint():\n${i.stdout}` : "");
  } else {
    info.className = "info err";
    info.textContent = `✗ ${i.error}\n${i.traceback || ""}`;
  }
}
// store the empty-state html once
$("#inspectorTpl").dataset.empty = $("#inspector").innerHTML;

async function runCode() {
  const code = $("#pCode").value;
  S.dirtyCode = false;
  await savePart(S.selected, { code }, null, "keep");
}

async function savePart(name, body, newSel = null, force = false) {
  try {
    const res = await api(`/api/parts/${encodeURIComponent(name)}`, { method: "PUT", body: JSON.stringify(body) });
    if (newSel) S.selected = newSel;
    await apply(res, force);
    const p = res.parts.find((q) => q.name === (newSel || name));
    if (p && !p.info.ok) toast(`${p.name}: ${p.info.error}`, "err");
  } catch (e) { toast(e.message, "err"); }
}

function select(name) {
  if (S.dirtyCode && name !== S.selected && !confirm("Niet-gebouwde codewijzigingen weggooien?")) return;
  S.dirtyCode = false;
  S.selected = name;
  renderParts(); renderInspector(true); syncSceneProps();
}

// ------------------------------------------------------------------ apply server state
let applying = Promise.resolve();
function apply(summary, force = false) {
  applying = applying.then(async () => {
    const first = !S.project || S.project.name !== summary.name;
    S.project = summary;
    if (S.selected && !summary.parts.find((p) => p.name === S.selected)) S.selected = null;
    await Promise.all(summary.parts.map(loadMesh));
    renderParams(); renderParts(); renderInspector(force); syncSceneProps();
    if (document.activeElement !== $("#notes")) $("#notes").value = summary.notes || "";
    document.title = `CAD-Studio · ${summary.name}`;
    if (first) setView("iso");
  }).catch((e) => toast(e.message, "err"));
  return applying;
}

async function reload() { await apply(await api("/api/project")); }

async function loadProjects() {
  const { projects, current } = await api("/api/projects");
  const sel = $("#projectSelect"); sel.innerHTML = "";
  for (const p of projects) sel.add(new Option(p, p, false, p === current));
}
$("#projectSelect").onchange = async (e) => {
  for (const m of S.meshes.values()) partsGroup.remove(m.mesh);
  S.meshes.clear(); S.selected = null;
  await apply(await api("/api/projects", { method: "POST", body: JSON.stringify({ name: e.target.value }) }));
};
$("#newProject").onclick = async () => {
  const n = prompt("Naam van het nieuwe project:"); if (!n) return;
  for (const m of S.meshes.values()) partsGroup.remove(m.mesh);
  S.meshes.clear(); S.selected = null;
  await apply(await api("/api/projects", { method: "POST", body: JSON.stringify({ name: n }) }));
  loadProjects();
};

let notesTimer;
$("#notes").oninput = (e) => { clearTimeout(notesTimer); notesTimer = setTimeout(() => api("/api/notes", { method: "PUT", body: JSON.stringify({ notes: e.target.value }) }), 600); };

// ------------------------------------------------------------------ toolbar: add / import / export
const TEMPLATES = {
  box: "result = Box(30, 20, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))\nresult = fillet(result.edges().filter_by(Axis.Z), 2)",
  cylinder: "result = Cylinder(radius=10, height=20, align=(Align.CENTER, Align.CENTER, Align.MIN))",
  sphere: "result = Pos(0, 0, 10) * Sphere(10)",
  text: "result = extrude(Text('Hallo', font_size=12), amount=2)",
  code: "# build123d – wijs de vorm toe aan result\nwith BuildPart() as bp:\n    Box(40, 30, 4, align=(Align.CENTER, Align.CENTER, Align.MIN))\n    with Locations((0, 0, 4)):\n        Cylinder(6, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))\n    fillet(bp.edges().group_by(Axis.Z)[-1], 1)\nresult = bp.part",
};
document.querySelectorAll("[data-add]").forEach((b) => b.onclick = async () => {
  const kind = b.dataset.add;
  let name = kind, i = 2; while (S.project.parts.some((p) => p.name === name)) name = `${kind}${i++}`;
  await savePart(name, { code: TEMPLATES[kind], type: "code" }, name, true);
});
$("#importFile").onchange = async (e) => {
  const f = e.target.files[0]; if (!f) return;
  const fd = new FormData(); fd.append("file", f);
  const r = await fetch("/api/import", { method: "POST", body: fd });
  const body = await r.json(); if (!r.ok) return toast(body.error || body.detail, "err");
  await apply(body); toast(`Geïmporteerd: ${f.name}`, "ok"); e.target.value = "";
};
async function doExport(format) {
  try {
    const res = await api("/api/export", { method: "POST", body: JSON.stringify({ format, flavor: $("#exportFlavor").value, mode: $("#exportMode").value }) });
    const links = res.download.map((u) => `<a href="${u}">${decodeURIComponent(u.split("/").pop().split("%2F").pop())}</a>`).join("<br>");
    let slots = "";
    if (res.filament_slots) slots = "\n" + Object.entries(res.filament_slots).map(([k, v]) => `Slot ${k}: ${v.join(", ")}`).join("\n");
    toast(`✓ Opgeslagen: ${(res.path || res.files.join(", "))}${slots}${res.warnings && res.warnings.length ? "\n⚠ " + res.warnings.join("\n") : ""}\n${links}`, "ok", 15000);
    res.download.forEach((u) => { const a = document.createElement("a"); a.href = u; a.download = ""; document.body.appendChild(a); a.click(); a.remove(); });
  } catch (e) { toast(e.message, "err", 8000); }
}
$("#export3mf").onclick = () => doExport("3mf");
$("#exportStl").onclick = () => doExport("stl");
$("#exportStep").onclick = () => doExport("step");

// view bar
document.querySelectorAll("[data-view]").forEach((b) => b.onclick = () => setView(b.dataset.view));
const toggle = (key, btn) => { S[key] = !S[key]; btn.classList.toggle("on", S[key]); syncSceneProps(); };
$("#toggleXray").onclick = (e) => toggle("xray", e.currentTarget);
$("#toggleEdges").onclick = (e) => toggle("edges", e.currentTarget);
$("#toggleBed").onclick = (e) => toggle("bed", e.currentTarget);
$("#toggleMove").onclick = (e) => toggle("move", e.currentTarget);
$("#toggleEdges").classList.add("on"); $("#toggleBed").classList.add("on");
window.addEventListener("keydown", (e) => {
  if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) return;
  if (e.key === "x") $("#toggleXray").click();
  if (e.key === "e") $("#toggleEdges").click();
  if (e.key === "g") $("#toggleMove").click();
  if (e.key === "f") setView("fit");
  if (e.key === "Escape") select(null);
  if (e.key === "Delete" && S.selected) $("#pDel")?.click();
});

// ------------------------------------------------------------------ live updates (Claude via MCP)
function connectEvents() {
  const es = new EventSource("/api/events");
  let lastRev = null, lastProj = null;
  es.onopen = () => $("#live").classList.add("ok");
  es.onerror = () => { $("#live").classList.remove("ok"); };
  es.onmessage = async (ev) => {
    const { project, rev } = JSON.parse(ev.data);
    if (project !== lastProj && lastProj !== null) {
      for (const m of S.meshes.values()) partsGroup.remove(m.mesh);
      S.meshes.clear(); S.selected = null; loadProjects();
    }
    if (rev !== lastRev || project !== lastProj) {
      lastRev = rev; lastProj = project;
      if (!S.project || S.project.rev !== rev || S.project.name !== project) await reload();
    }
  };
}

await loadProjects();
await reload();
connectEvents();
