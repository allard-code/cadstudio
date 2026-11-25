// SPDX-License-Identifier: GPL-3.0-or-later
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { TransformControls } from "three/addons/controls/TransformControls.js";
import { toCreasedNormals } from "three/addons/utils/BufferGeometryUtils.js";
import { applyI18n, LANG, setLang, t } from "./i18n.js";

// ------------------------------------------------------------------ state
const S = {
  project: null,          // summary from server
  selected: null,         // part name
  meshes: new Map(),      // name -> {key, mesh, edges}
  xray: false, edges: true, bed: true, move: false, resize: false, rotate: false, overhangs: false,
  measure: false, measurePoints: [], measureDist: null,
  clip: false, clipAxis: "z", clipFlip: false,
  plate: 0,               // build plate shown in the viewport; 0 = all plates side by side
  asm: false,             // assembly view (how the parts go together) instead of the build plates
  asmExplode: 0, asmHide: new Set(), asmGhost: null,   // asmGhost: Set of see-through items (null = from the project)
  dirtyCode: false, dirtyCommon: false,
};
const undoStack = []; const redoStack = []; const UNDO_LIMIT = 30;
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
renderer.localClippingEnabled = true;
const clipPlane = new THREE.Plane(new THREE.Vector3(0, 0, -1), 0);
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

// build plates (beds), 250 x 250 each; plate 1 centred on the origin, further plates in the same grid as
// Orca/Bambu/Anycubic Slicer Next (columns to +X, rows to -Y, 1/5 bed gap) - positions come from the server
const bedGroup = new THREE.Group(); scene.add(bedGroup);
const plateCount = () => (S.project && S.project.plates) || 1;
const partPlate = (p) => p.plate || 1;
const onShownPlate = (p) => !S.plate || partPlate(p) === S.plate;
function plateOrigin(n) {
  const o = S.project && S.project.plate_origins && S.project.plate_origins[String(n)];
  return o ? new THREE.Vector3(o[0], o[1], 0) : new THREE.Vector3();
}
function plateLabel(text, active) {
  const c = document.createElement("canvas"); c.width = 256; c.height = 64;
  const g = c.getContext("2d");
  g.font = "bold 40px system-ui, sans-serif"; g.textBaseline = "middle";
  g.fillStyle = active ? "#ff8a3d" : "#8b93a1"; g.fillText(text, 4, 34);
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(c), depthTest: false }));
  sp.scale.set(64, 16, 1);
  return sp;
}
let bedKey = "";
function buildBeds(w = 250, d = 250) {
  const n = plateCount();
  const key = `${n}|${S.plate}|${JSON.stringify(S.project && S.project.plate_origins)}|${LANG}`;
  if (key === bedKey) return;
  bedKey = key;
  bedGroup.clear();
  for (let i = 1; i <= n; i++) {
    const active = n > 1 && S.plate === i;
    const g = new THREE.Group(); g.position.copy(plateOrigin(i)); g.userData.plate = i;
    const plate = new THREE.Mesh(new THREE.PlaneGeometry(w, d),
      new THREE.MeshStandardMaterial({ color: active ? 0x2b3038 : 0x23272e, roughness: 1, transparent: true, opacity: 0.9 }));
    plate.position.z = -0.05; g.add(plate);
    const g10 = new THREE.GridHelper(w, w / 10, 0x3a404a, 0x2c3139); g10.rotation.x = Math.PI / 2; g.add(g10);
    const g50 = new THREE.GridHelper(w, w / 50, active ? 0xff8a3d : 0x56606e, active ? 0xff8a3d : 0x56606e);
    g50.rotation.x = Math.PI / 2; g50.position.z = 0.01; g.add(g50);
    if (i === 1) { const axes = new THREE.AxesHelper(30); axes.position.set(-w / 2, -d / 2, 0.02); g.add(axes); }
    if (n > 1) { const lab = plateLabel(t("plates.plate", { i }), active); lab.position.set(-w / 2 + 34, d / 2 + 12, 0.1); g.add(lab); }
    bedGroup.add(g);
  }
}
buildBeds();

const partsGroup = new THREE.Group(); scene.add(partsGroup);
const asmGroup = new THREE.Group(); asmGroup.visible = false; scene.add(asmGroup);
const asmMeshes = new Map();  // assembly item name -> {key, mesh, edges, centre}
const measureGroup = new THREE.Group(); scene.add(measureGroup);
const tc = new TransformControls(camera, renderer.domElement);
tc.setSize(0.8);
scene.add(tc.getHelper ? tc.getHelper() : tc);
tc.addEventListener("dragging-changed", (e) => {
  controls.enabled = !e.value;
  if (!e.value) {
    const mode = tc.getMode();
    if (mode === "scale") commitResize();
    else if (mode === "rotate") commitRotate();
    else commitMove();
  }
});
// hold Shift while dragging a gizmo handle to snap to coarse steps
window.addEventListener("keydown", (e) => {
  if (e.key === "Shift") { tc.setTranslationSnap(10); tc.setRotationSnap(THREE.MathUtils.degToRad(15)); tc.setScaleSnap(0.1); }
});
window.addEventListener("keyup", (e) => {
  if (e.key === "Shift") { tc.setTranslationSnap(null); tc.setRotationSnap(null); tc.setScaleSnap(null); }
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
  const pool = S.asm ? asmMeshes : S.meshes;
  const hits = ray.intersectObjects([...pool.values()].map((m) => m.mesh).filter((m) => m.visible));
  if (S.measure) { if (hits.length) addMeasurePoint(hits[0].point); return; }
  if (S.asm) return;  // assembly items aren't editable parts
  select(hits.length ? hits[0].object.userData.name : null);
});

// ------------------------------------------------------------------ measure tool: click two points on a
// part's surface, see the straight-line distance between them (e.g. to check a hole spacing visually)
function clearMeasure() {
  measureGroup.clear();
  S.measurePoints = []; S.measureDist = null;
  updateDims();
}
function addMeasurePoint(point) {
  if (S.measurePoints.length >= 2) clearMeasure();
  const marker = new THREE.Mesh(new THREE.SphereGeometry(1.4, 16, 16),
    new THREE.MeshBasicMaterial({ color: 0xffd60a, depthTest: false }));
  marker.position.copy(point); marker.renderOrder = 999;
  measureGroup.add(marker);
  S.measurePoints.push(point.clone());
  if (S.measurePoints.length === 2) {
    const [a, b] = S.measurePoints;
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([a, b]),
      new THREE.LineBasicMaterial({ color: 0xffd60a, depthTest: false }));
    line.renderOrder = 999;
    measureGroup.add(line);
    S.measureDist = a.distanceTo(b);
  }
  updateDims();
}

function material(color) {
  return new THREE.MeshStandardMaterial({
    color, roughness: 0.55, metalness: 0.05, side: THREE.DoubleSide,
    transparent: S.xray, opacity: S.xray ? 0.35 : 1, depthWrite: !S.xray,
    polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1,
  });
}

// Overhang highlighting: faces steeper than 45deg from vertical, facing down, not resting on the bed -
// these need support material when printing. Mirrors the threshold used by render_preview on the server.
const OVERHANG_COS = Math.cos(Math.PI / 4);
const OVERHANG_COLOR = new THREE.Color(0xff6e0f);

function computeOverhangMask(shadedGeo, centreZ) {
  const sp = shadedGeo.attributes.position.array;
  const ntri = sp.length / 9;
  const mask = new Uint8Array(ntri);
  const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3();
  const ab = new THREE.Vector3(), ac = new THREE.Vector3(), nrm = new THREE.Vector3();
  for (let i = 0; i < ntri; i++) {
    const o = i * 9;
    a.set(sp[o], sp[o + 1], sp[o + 2]); b.set(sp[o + 3], sp[o + 4], sp[o + 5]); c.set(sp[o + 6], sp[o + 7], sp[o + 8]);
    ab.subVectors(b, a); ac.subVectors(c, a);
    nrm.crossVectors(ab, ac).normalize();
    const minWorldZ = Math.min(a.z, b.z, c.z) + centreZ;
    mask[i] = (nrm.z < -OVERHANG_COS && minWorldZ > 0.05) ? 1 : 0;
  }
  return mask;
}

function applyOverhangColors(entry, colorHex) {
  const geo = entry.mesh.geometry;
  const ntri = entry.overhangMask.length;
  let attr = geo.getAttribute("color");
  if (!attr || attr.count !== ntri * 3) { attr = new THREE.BufferAttribute(new Float32Array(ntri * 9), 3); geo.setAttribute("color", attr); }
  const base = new THREE.Color(colorHex);
  for (let i = 0; i < ntri; i++) {
    const col = S.overhangs && entry.overhangMask[i] ? OVERHANG_COLOR : base;
    const o = i * 9;
    for (let v = 0; v < 3; v++) { attr.array[o + v * 3] = col.r; attr.array[o + v * 3 + 1] = col.g; attr.array[o + v * 3 + 2] = col.b; }
  }
  attr.needsUpdate = true;
  entry.mesh.material.vertexColors = S.overhangs;
  entry.mesh.material.color.set(S.overhangs ? 0xffffff : colorHex);
  entry.mesh.material.needsUpdate = true;
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
  geo.computeBoundingBox();
  const centre = geo.boundingBox.getCenter(new THREE.Vector3());
  geo.translate(-centre.x, -centre.y, -centre.z);   // gizmo sits in the middle of the part
  // welded meshes: keep flat faces flat and sharp edges sharp, but curved surfaces smooth
  const shaded = toCreasedNormals(geo, Math.PI / 6);
  const mesh = new THREE.Mesh(shaded, material(part.color));
  mesh.userData.local = centre.clone();   // position on its own plate; the plate offset is added in syncSceneProps
  mesh.position.copy(centre).add(plateOrigin(partPlate(part)));
  mesh.userData.name = part.name; mesh.userData.base = mesh.position.clone();
  const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geo, 25),
    new THREE.LineBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.35 }));
  mesh.add(edges);
  if (cur) { if (tc.object === cur.mesh) tc.detach(); partsGroup.remove(cur.mesh); cur.mesh.geometry.dispose(); }
  partsGroup.add(mesh);
  const overhangMask = computeOverhangMask(shaded, centre.z);
  const entry = { key: info.key, mesh, edges, overhangMask };
  S.meshes.set(part.name, entry);
  applyOverhangColors(entry, part.color);
}

// ------------------------------------------------------------------ assembly view
const asmItems = () => (S.project && S.project.assembly) || [];
const asmGhosts = () => S.asmGhost || new Set(asmItems().filter((a) => a.ghost).map((a) => a.name));

async function loadAsmMesh(item) {
  const info = item.info || {};
  const cur = asmMeshes.get(item.name);
  if (!info.ok) { if (cur) cur.mesh.visible = false; return; }
  if (cur && cur.key === info.key) return;
  const buf = await api(`/api/assembly/mesh/${encodeURIComponent(item.name)}`);
  const head = new Uint32Array(buf, 0, 2);
  const nv = head[0], nt = head[1];
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(buf, 8, nv * 3), 3));
  geo.setIndex(new THREE.BufferAttribute(new Uint32Array(buf, 8 + nv * 12, nt * 3), 1));
  geo.computeBoundingBox();
  const centre = geo.boundingBox.getCenter(new THREE.Vector3());
  geo.translate(-centre.x, -centre.y, -centre.z);
  const mesh = new THREE.Mesh(toCreasedNormals(geo, Math.PI / 6), material(item.color));
  const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geo, 25),
    new THREE.LineBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.35 }));
  mesh.add(edges);
  if (cur) { asmGroup.remove(cur.mesh); cur.mesh.geometry.dispose(); }
  asmGroup.add(mesh);
  asmMeshes.set(item.name, { key: info.key, mesh, edges, centre });
}

// explode: every item moves away from the assembly centre (or along its own explode vector), times the slider
function asmOffset(item) {
  const f = S.asmExplode;
  if (!f || !item.info || !item.info.ok) return new THREE.Vector3();
  if (item.explode) return new THREE.Vector3(...item.explode).multiplyScalar(f);
  const all = new THREE.Box3();
  for (const a of asmItems()) if (a.info && a.info.ok) all.expandByPoint(new THREE.Vector3(...a.info.bbox_min)).expandByPoint(new THREE.Vector3(...a.info.bbox_max));
  const c = new THREE.Vector3(...item.info.bbox_min).add(new THREE.Vector3(...item.info.bbox_max)).multiplyScalar(0.5);
  return c.sub(all.getCenter(new THREE.Vector3())).multiplyScalar(f);
}

function syncAsm() {
  const names = new Set(asmItems().map((a) => a.name));
  for (const [n, m] of asmMeshes) if (!names.has(n)) { asmGroup.remove(m.mesh); asmMeshes.delete(n); }
  const ghosts = asmGhosts();
  for (const a of asmItems()) {
    const m = asmMeshes.get(a.name); if (!m) continue;
    m.mesh.position.copy(m.centre).add(asmOffset(a));
    m.mesh.visible = a.visible && a.info.ok && !S.asmHide.has(a.name);
    m.mesh.material.dispose(); m.mesh.material = material(a.color);
    if (ghosts.has(a.name)) Object.assign(m.mesh.material, { transparent: true, opacity: 0.22, depthWrite: false });
    m.edges.visible = S.edges;
  }
  asmGroup.visible = S.asm;
}

function renderAsm() {
  const items = asmItems();
  if (!items.length && S.asm) S.asm = false;
  $("#asmTab").classList.toggle("hidden", !items.length);
  $("#asmTab").classList.toggle("on", S.asm);
  $("#asmPanel").classList.toggle("hidden", !S.asm);
  for (const id of ["#plateTabs", "#plateAdd", "#plateDel", "#plateArrange"]) $(id).classList.toggle("hidden", S.asm);
  if (S.asm) $("#printBar").classList.add("hidden");
  const box = $("#asmItems"); box.innerHTML = "";
  const ghosts = asmGhosts();
  for (const a of items) {
    const row = document.createElement("div"); row.className = "it" + (a.info.ok ? "" : " err");
    if (!a.info.ok) row.title = a.info.error || "";
    const sw = document.createElement("span"); sw.className = "sw"; sw.style.background = a.color;
    const nm = document.createElement("span"); nm.className = "nm"; nm.textContent = a.name;
    const chk = (label, on, fn) => {
      const l = document.createElement("label"); const c = document.createElement("input");
      c.type = "checkbox"; c.checked = on; c.onchange = () => { fn(c.checked); syncAsm(); };
      l.append(c, document.createTextNode(label)); return l;
    };
    row.append(sw, nm,
      chk(t("asm.show"), !S.asmHide.has(a.name), (v) => { if (v) S.asmHide.delete(a.name); else S.asmHide.add(a.name); }),
      chk(t("asm.ghost"), ghosts.has(a.name), (v) => { S.asmGhost = new Set(asmGhosts()); if (v) S.asmGhost.add(a.name); else S.asmGhost.delete(a.name); }));
    box.appendChild(row);
  }
}

function setAsm(on) {
  S.asm = on && asmItems().length > 0;
  history.replaceState(null, "", S.asm ? "#assembly" : location.pathname + location.search);
  if (S.asm && S.selected) { S.selected = null; renderParts(); renderInspector(); }
  clearMeasure(); renderAsm(); syncSceneProps(); setView("fit"); refreshPrintBar();
}
$("#asmTab").onclick = () => setAsm(!S.asm);
$("#asmExplode").oninput = (e) => { S.asmExplode = +e.target.value / 100; syncAsm(); updateDims(); };
$("#asmPng").onclick = () => {
  // the server picks the view direction closest to the editor camera and cuts the half facing the viewer
  const d = camera.position.clone().sub(controls.target).normalize();
  const views = { iso: [0.5, -0.71, 0.5], iso_back: [-0.5, 0.71, 0.5], front: [0, -1, 0], back: [0, 1, 0],
    right: [1, 0, 0], left: [-1, 0, 0], top: [0, 0, 1], bottom: [0, 0, -1] };
  let view = "iso", best = -2;
  for (const [k, v] of Object.entries(views)) { const s = d.dot(new THREE.Vector3(...v).normalize()); if (s > best) { best = s; view = k; } }
  const q = new URLSearchParams({ view, explode: String(S.asmExplode), ghost: [...asmGhosts()].join(","), download: "1" });
  if (S.asmHide.size) q.set("hide", [...S.asmHide].join(","));
  if (S.clip) {
    const axis = CLIP_AXES[S.clipAxis]; const b = bbox();
    const lo = b.min.dot(axis), hi = b.max.dot(axis);
    q.set("section", S.clipAxis); q.set("section_at", String(lo + (hi - lo) * (+$("#clipSlider").value / 1000)));
  }
  const a = document.createElement("a"); a.href = `/api/assembly.png?${q}`; a.download = ""; document.body.appendChild(a); a.click(); a.remove();
};

function syncSceneProps() {
  const names = new Set(S.project.parts.map((p) => p.name));
  for (const [n, m] of S.meshes) if (!names.has(n)) { if (tc.object === m.mesh) tc.detach(); partsGroup.remove(m.mesh); S.meshes.delete(n); }
  buildBeds();
  for (const p of S.project.parts) {
    const m = S.meshes.get(p.name); if (!m) continue;
    if (!tc.dragging) {
      m.mesh.position.copy(m.mesh.userData.local).add(plateOrigin(partPlate(p)));
      m.mesh.userData.base = m.mesh.position.clone();
    }
    m.mesh.visible = p.visible && p.info.ok && onShownPlate(p);
    m.mesh.material.dispose(); m.mesh.material = material(p.color);
    applyOverhangColors(m, p.color);
    m.edges.visible = S.edges;
    if (p.name === S.selected) m.mesh.material.emissive = new THREE.Color(0x3a1d05);
  }
  bedGroup.visible = S.bed && !S.asm;
  partsGroup.visible = !S.asm;
  syncAsm();
  attachGizmo();
  updateDims();
  if (S.clip) updateClipPlane();
}

// world-space bounding box (plate offsets included) of the given parts, or of the visible parts on the shown plate(s)
function bbox(names) {
  const b = new THREE.Box3();
  if (S.asm && !names) {
    for (const a of asmItems()) {
      if (!a.visible || !a.info.ok || S.asmHide.has(a.name)) continue;
      const o = asmOffset(a);
      b.expandByPoint(new THREE.Vector3(...a.info.bbox_min).add(o)); b.expandByPoint(new THREE.Vector3(...a.info.bbox_max).add(o));
    }
    return b;
  }
  for (const p of S.project.parts) {
    if (names && !names.includes(p.name)) continue;
    if (!names && (!p.visible || !onShownPlate(p))) continue;
    if (!p.info.ok) continue;
    const o = plateOrigin(partPlate(p));
    b.expandByPoint(new THREE.Vector3(...p.info.bbox_min).add(o)); b.expandByPoint(new THREE.Vector3(...p.info.bbox_max).add(o));
  }
  return b;
}
// plates whose (visible, exported) contents don't fit on one bed
function overfullPlates() {
  const boxes = new Map();
  for (const p of S.project.parts) {
    if (!p.visible || !p.export || !p.info.ok) continue;
    const k = partPlate(p); if (!boxes.has(k)) boxes.set(k, new THREE.Box3());
    boxes.get(k).expandByPoint(new THREE.Vector3(...p.info.bbox_min)).expandByPoint(new THREE.Vector3(...p.info.bbox_max));
  }
  const bed = S.project.bed || [250, 250, 250];
  return [...boxes].filter(([, b]) => { const s = b.getSize(new THREE.Vector3()); return s.x > bed[0] + 1e-6 || s.y > bed[1] + 1e-6 || s.z > bed[2] + 1e-6; })
    .map(([k]) => k).sort((a, b) => a - b);
}
function updateDims() {
  const all = bbox();
  let txt = "";
  const over = overfullPlates();
  if (!all.isEmpty()) {
    const s = all.getSize(new THREE.Vector3());
    txt += `${t("dims.total")}  ${s.x.toFixed(1)} × ${s.y.toFixed(1)} × ${s.z.toFixed(1)} mm`;
    if (plateCount() === 1 && over.length && !S.asm) txt += "  " + t("dims.toobig");
  }
  if (plateCount() > 1 && !S.asm) for (const k of over) txt += "\n" + t("plates.over", { i: k });
  const p = S.selected && S.project.parts.find((q) => q.name === S.selected);
  if (p && p.info.ok) {
    const [x, y, z] = p.info.size;
    txt += `\n${p.name}  ${x.toFixed(1)} × ${y.toFixed(1)} × ${z.toFixed(1)} mm` + (p.info.volume_mm3 ? `  ·  ${(p.info.volume_mm3 / 1000).toFixed(2)} cm³` : "");
  }
  if (S.measureDist != null) txt += `\n${t("measure.distance")}  ${S.measureDist.toFixed(2)} mm`;
  else if (S.measure && S.measurePoints.length === 1) txt += `\n${t("measure.hint2")}`;
  else if (S.measure) txt += `\n${t("measure.hint1")}`;
  $("#dims").textContent = txt || "—";
}

// ------------------------------------------------------------------ section/clip-plane view
const CLIP_AXES = { x: new THREE.Vector3(1, 0, 0), y: new THREE.Vector3(0, 1, 0), z: new THREE.Vector3(0, 0, 1) };
function updateClipPlane() {
  const axis = CLIP_AXES[S.clipAxis];
  const sign = S.clipFlip ? 1 : -1;
  clipPlane.normal.copy(axis).multiplyScalar(sign);
  const all = bbox();
  if (all.isEmpty()) { clipPlane.constant = 0; return; }
  const lo = all.min.dot(axis), hi = all.max.dot(axis);
  const frac = +$("#clipSlider").value / 1000;
  const cut = lo + (hi - lo) * frac;
  clipPlane.constant = -sign * cut;
  renderer.clippingPlanes = S.clip ? [clipPlane] : [];
}

function setView(v) {
  const b = bbox();
  if (plateCount() > 1 && !S.asm) {  // several beds: frame the shown bed(s), not only the parts on them
    const bed = S.project.bed || [250, 250, 250];
    for (let i = 1; i <= plateCount(); i++) {
      if (S.plate && i !== S.plate) continue;
      const o = plateOrigin(i);
      b.expandByPoint(new THREE.Vector3(o.x - bed[0] / 2, o.y - bed[1] / 2, 0));
      b.expandByPoint(new THREE.Vector3(o.x + bed[0] / 2, o.y + bed[1] / 2, 0));
    }
  }
  const empty = S.plate ? plateOrigin(S.plate).add(new THREE.Vector3(0, 0, 10)) : new THREE.Vector3(0, 0, 10);
  const c = b.isEmpty() ? empty : b.getCenter(new THREE.Vector3());
  const r = b.isEmpty() ? (S.plate ? 250 : 80) : Math.max(b.getSize(new THREE.Vector3()).length(), 20);
  const d = r * 1.6;
  const dirs = { iso: [-0.6, -0.9, 0.7], front: [0, -1, 0.0001], top: [0, -0.0001, 1], right: [1, 0, 0.0001], fit: null };
  const dir = dirs[v] ? new THREE.Vector3(...dirs[v]).normalize()
    : camera.position.clone().sub(controls.target).normalize();
  controls.target.copy(c); camera.position.copy(c.clone().add(dir.multiplyScalar(d)));
}

// ------------------------------------------------------------------ gizmo move/resize/rotate -> location/scale
function attachGizmo() {
  const m = S.selected && S.meshes.get(S.selected);
  if ((S.move || S.resize || S.rotate) && m && m.mesh.visible) {
    if (tc.object !== m.mesh) tc.attach(m.mesh);
    tc.setMode(S.rotate ? "rotate" : S.resize ? "scale" : "translate");
  } else tc.detach();
}
async function commitMove() {
  const obj = tc.object; if (!obj) return;
  const name = obj.userData.name; const p = S.project.parts.find((q) => q.name === name);
  const d = obj.position.clone().sub(obj.userData.base); if (d.lengthSq() < 1e-9) return;
  const loc = [...p.location]; loc[0] += +d.x.toFixed(2); loc[1] += +d.y.toFixed(2); loc[2] += +d.z.toFixed(2);
  pushUndo(name); await savePart(name, { location: loc });
  // the mesh is reloaded from the server with the new location baked in
}
async function commitResize() {
  const obj = tc.object; if (!obj) return;
  const name = obj.userData.name; const p = S.project.parts.find((q) => q.name === name);
  const s = obj.scale;
  if (Math.abs(s.x - 1) < 1e-4 && Math.abs(s.y - 1) < 1e-4 && Math.abs(s.z - 1) < 1e-4) return;
  const cur = p.scale || [1, 1, 1];
  const next = [cur[0] * s.x, cur[1] * s.y, cur[2] * s.z].map((v) => +v.toFixed(3));
  pushUndo(name); await savePart(name, { scale: next });
  // the mesh is reloaded from the server with the new scale baked into the geometry
}
async function commitRotate() {
  const obj = tc.object; if (!obj) return;
  const q = obj.quaternion;
  const angle = 2 * Math.acos(Math.min(1, Math.abs(q.w)));
  if (angle < 1e-4) return;  // no change
  const name = obj.userData.name; const p = S.project.parts.find((qq) => qq.name === name);
  // the part's existing rotation (location[3:5]) is already baked into the loaded geometry (the mesh itself
  // starts at identity orientation), so the gizmo's quaternion is a pure delta on top of it - compose them
  // with the same axis-order convention as build123d's Rot(rx,ry,rz) (three.js Euler order "ZYX" matches it).
  const existing = new THREE.Quaternion().setFromEuler(new THREE.Euler(
    THREE.MathUtils.degToRad(p.location[3]), THREE.MathUtils.degToRad(p.location[4]), THREE.MathUtils.degToRad(p.location[5]), "ZYX",
  ));
  const combined = q.clone().multiply(existing);
  const e = new THREE.Euler().setFromQuaternion(combined, "ZYX");
  const loc = [...p.location];
  loc[3] = +THREE.MathUtils.radToDeg(e.x).toFixed(2);
  loc[4] = +THREE.MathUtils.radToDeg(e.y).toFixed(2);
  loc[5] = +THREE.MathUtils.radToDeg(e.z).toFixed(2);
  pushUndo(name); await savePart(name, { location: loc });
  // the mesh is reloaded from the server with the new rotation baked into the geometry (back to identity here)
}

// ------------------------------------------------------------------ UI: params
function renderParams() {
  const box = $("#params"); box.innerHTML = "";
  const params = S.project.params || {};
  for (const [k, v] of Object.entries(params)) {
    const row = document.createElement("div"); row.className = "param";
    if (typeof v === "number") {
      const max = Math.max(10, Math.abs(v) * 3), step = Number.isInteger(v) ? 1 : 0.1;
      row.innerHTML = `<span title="${k}">${k}</span><input type="range" min="0" max="${max}" step="${step}" value="${v}"><input type="number" step="${step}" value="${v}"><span class="x" title="${t("params.remove")}">✕</span>`;
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
  if (!Object.keys(params).length) box.innerHTML = `<div class="muted">${t("params.empty")}</div>`;
  const sel = $("#presetSelect"); const names = Object.keys(S.project.presets || {});
  sel.innerHTML = `<option value="" data-i18n="presets.select"></option>` + names.map((n) => `<option value="${n}">${n}</option>`).join("");
  applyI18n(sel);
}
async function setParam(k, v) {
  try { apply(await api("/api/params", { method: "PUT", body: JSON.stringify({ params: { [k]: v } }) })); }
  catch (e) { toast(e.message, "err"); }
}
$("#addParam").onclick = () => {
  const name = prompt(t("params.prompt.name")); if (!name) return;
  const val = prompt(t("params.prompt.value"), "2"); if (val === null) return;
  setParam(name.trim(), isNaN(+val) ? val : +val);
};
$("#presetSelect").onchange = async (e) => {
  const name = e.target.value; if (!name) return;
  try { apply(await api(`/api/presets/${encodeURIComponent(name)}/apply`, { method: "POST" })); }
  catch (err) { toast(err.message, "err"); }
};
$("#presetSave").onclick = async () => {
  const name = prompt(t("presets.save")); if (!name) return;
  try { apply(await api("/api/presets", { method: "POST", body: JSON.stringify({ name: name.trim() }) })); }
  catch (err) { toast(err.message, "err"); }
};
$("#presetDel").onclick = async () => {
  const name = $("#presetSelect").value; if (!name) return;
  try { apply(await api(`/api/presets/${encodeURIComponent(name)}`, { method: "DELETE" })); }
  catch (err) { toast(err.message, "err"); }
};

// ------------------------------------------------------------------ checkpoints (full project snapshots)
function renderCheckpoints() {
  const sel = $("#checkpointSelect"); const prev = sel.value;
  const names = (S.project.checkpoints || []).map((c) => c.name);
  sel.innerHTML = `<option value="" data-i18n="checkpoints.select"></option>` + names.map((n) => `<option value="${n}">${n}</option>`).join("");
  if (names.includes(prev)) sel.value = prev;
  applyI18n(sel);
}
$("#checkpointSave").onclick = async () => {
  const name = prompt(t("checkpoints.save")); if (!name) return;
  try { apply(await api("/api/checkpoints", { method: "POST", body: JSON.stringify({ name: name.trim() }) })); }
  catch (err) { toast(err.message, "err"); }
};
$("#checkpointRestore").onclick = async () => {
  const name = $("#checkpointSelect").value; if (!name) return;
  if (!confirm(t("checkpoints.confirm", { name }))) return;
  try { apply(await api(`/api/checkpoints/${encodeURIComponent(name)}/restore`, { method: "POST" }), true); }
  catch (err) { toast(err.message, "err"); }
};
$("#checkpointDel").onclick = async () => {
  const name = $("#checkpointSelect").value; if (!name) return;
  try { apply(await api(`/api/checkpoints/${encodeURIComponent(name)}`, { method: "DELETE" })); }
  catch (err) { toast(err.message, "err"); }
};

// ------------------------------------------------------------------ UI: parts list
function renderParts() {
  const box = $("#parts"); box.innerHTML = "";
  for (const p of S.project.parts) {
    const d = document.createElement("div");
    d.className = "part" + (p.name === S.selected ? " sel" : "") + (p.visible ? "" : " hidden");
    d.innerHTML = `<span class="eye ${p.visible ? "" : "off"}" title="${t("parts.visible")}">👁</span>
      <span class="sw" style="background:${p.color}"></span>
      <span class="nm">${p.name}</span>
      ${p.type === "mesh" ? '<span class="mesh">mesh</span>' : ""}
      ${p.info.ok ? "" : '<span class="err" title="' + (p.info.error || "").replace(/"/g, "'") + '">⚠</span>'}
      ${plateCount() > 1 ? `<span class="slot" title="${t("insp.plate")}">B${partPlate(p)}</span>` : ""}
      <span class="slot" title="${t("parts.slot")}">F${p.filament}</span>`;
    if (!onShownPlate(p)) d.style.opacity = 0.5;
    d.onclick = (e) => {
      if (e.target.classList.contains("eye")) return;
      if (!onShownPlate(p)) showPlate(partPlate(p), false);  // selecting a part on another bed switches to it
      select(p.name);
    };
    d.querySelector(".eye").onclick = () => { pushUndo(p.name); savePart(p.name, { visible: !p.visible }); };
    box.appendChild(d);
  }
  if (!S.project.parts.length) box.innerHTML = `<div class="muted">${t("parts.empty")}</div>`;
}

// ------------------------------------------------------------------ UI: inspector
function renderInspector(force = false) {
  const ins = $("#inspector");
  const p = S.selected && S.project.parts.find((q) => q.name === S.selected);
  if (!p) {
    if (!ins.classList.contains("empty")) { ins.className = "empty"; ins.innerHTML = $("#inspectorTpl").dataset.empty; applyI18n(ins); }
    return;
  }
  if (ins.classList.contains("empty") || ins.dataset.part !== p.name || force) {
    ins.className = ""; ins.dataset.part = p.name;
    ins.innerHTML = $("#inspectorTpl").innerHTML;
    applyI18n(ins);
    const fil = $("#pFilament");
    for (let i = 1; i <= 8; i++) fil.add(new Option(t(i <= 4 ? "slot.option" : "slot.second", { i }), i));
    $("#pName").onchange = (e) => savePart(p.name, { new_name: e.target.value.trim() }, e.target.value.trim());
    $("#pColor").onchange = (e) => { pushUndo(S.selected); savePart(S.selected, { color: e.target.value }); };
    $("#pFilament").onchange = (e) => { pushUndo(S.selected); savePart(S.selected, { filament: +e.target.value }); };
    $("#pPlate").onchange = async (e) => {
      const k = +e.target.value; pushUndo(S.selected);
      const follow = !!S.plate;
      await savePart(S.selected, { plate: k });
      if (follow) showPlate(k); else renderPlates();  // follow the part to its new bed
    };
    $("#pVisible").onchange = (e) => { pushUndo(S.selected); savePart(S.selected, { visible: e.target.checked }); };
    $("#pExport").onchange = (e) => { pushUndo(S.selected); savePart(S.selected, { export: e.target.checked }); };
    ins.querySelectorAll("[data-i]").forEach((inp) => inp.onchange = () => {
      const loc = [...ins.querySelectorAll("[data-i]")].map((i) => parseFloat(i.value) || 0);
      pushUndo(S.selected); savePart(S.selected, { location: loc });
    });
    ins.querySelectorAll("[data-s]").forEach((inp) => inp.onchange = () => {
      const scale = [...ins.querySelectorAll("[data-s]")].map((i) => parseFloat(i.value) || 1);
      pushUndo(S.selected); savePart(S.selected, { scale });
    });
    const code = $("#pCode");
    code.oninput = () => { S.dirtyCode = true; $("#pRun").classList.add("dirty"); };
    code.onkeydown = (e) => {
      if (e.key === "Tab") { e.preventDefault(); const s = code.selectionStart; code.setRangeText("    ", s, code.selectionEnd, "end"); code.oninput(); }
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); runCode(); }
    };
    $("#pRun").onclick = runCode;
    $("#pDup").onclick = async () => {
      const res = await api(`/api/parts/${encodeURIComponent(S.selected)}/duplicate`, { method: "POST" });
      if (res.new_name) S.selected = res.new_name;
      await apply(res, true);
    };
    $("#pDel").onclick = async () => {
      if (!confirm(t("insp.delete.confirm", { name: S.selected }))) return;
      const n = S.selected; S.selected = null;
      apply(await api(`/api/parts/${encodeURIComponent(n)}`, { method: "DELETE" }));
    };
    S.dirtyCode = false;
  }
  $("#pName").value = p.name;
  $("#pColor").value = p.color.length === 7 ? p.color : "#cccccc";
  $("#pFilament").value = p.filament;
  const ps = $("#pPlate"); const n = plateCount();
  if (ps.options.length !== n + 1) {
    ps.innerHTML = "";
    for (let i = 1; i <= n + 1; i++) ps.add(new Option(t("plates.plate", { i }) + (i > n ? " ＋" : ""), i));
  }
  ps.value = partPlate(p);
  $("#pVisible").checked = p.visible; $("#pExport").checked = p.export;
  ins.querySelectorAll("[data-i]").forEach((inp, i) => { if (document.activeElement !== inp) inp.value = +(+p.location[i]).toFixed(3); });
  const scaleVals = p.scale || [1, 1, 1];
  ins.querySelectorAll("[data-s]").forEach((inp, i) => { if (document.activeElement !== inp) inp.value = +(+scaleVals[i]).toFixed(3); });
  const code = $("#pCode");
  if (p.type === "mesh") { code.value = t("insp.mesh", { file: p.mesh_file }); code.disabled = true; $("#pRun").disabled = true; }
  else if (!S.dirtyCode) { code.value = p.code; code.disabled = false; $("#pRun").disabled = false; $("#pRun").classList.remove("dirty"); }
  else if (code.value !== p.code && force !== "keep") toast(t("insp.external"), "", 7000);
  const info = $("#pInfo"); const i = p.info;
  if (i.ok) {
    info.className = "info ok";
    info.textContent = t("info.built", { s: i.build_s, tris: i.triangles }) +
      (i.watertight === false ? t("info.notwatertight") : i.watertight ? t("info.watertight") : "") +
      `\n${t("info.size").padEnd(5)} ${i.size.map((v) => v.toFixed(2)).join(" × ")} mm\nmin   ${i.bbox_min.join(", ")}\nmax   ${i.bbox_max.join(", ")}` +
      (i.volume_mm3 ? "\n" + t("info.volume", { cm3: (i.volume_mm3 / 1000).toFixed(2), g: (i.volume_mm3 / 1000 * 1.24).toFixed(1) }) : "") +
      (i.stdout ? `\n\nprint():\n${i.stdout}` : "");
  } else {
    info.className = "info err";
    info.textContent = `✗ ${i.error}\n${i.traceback || ""}`;
  }
}
// store the empty-state html once
$("#inspectorTpl").dataset.empty = $("#inspector").innerHTML;  // untranslated; applyI18n runs on restore

async function runCode() {
  const code = $("#pCode").value;
  S.dirtyCode = false;
  pushUndo(S.selected);
  await savePart(S.selected, { code }, null, "keep");
}

// ------------------------------------------------------------------ undo/redo (location/scale/color/filament/
// visibility/export/code - not rename, delete or create, to keep part identity stable across the stack)
function snapshotPart(name) {
  const p = S.project?.parts?.find((q) => q.name === name);
  if (!p) return null;
  return { color: p.color, filament: p.filament, visible: p.visible, export: p.export, plate: partPlate(p),
    location: [...p.location], scale: [...(p.scale || [1, 1, 1])], code: p.code };
}
function refreshUndoButtons() {
  if ($("#btnUndo")) $("#btnUndo").disabled = undoStack.length === 0;
  if ($("#btnRedo")) $("#btnRedo").disabled = redoStack.length === 0;
}
function pushUndo(name) {
  const snap = snapshotPart(name); if (!snap) return;
  undoStack.push({ name, snap });
  if (undoStack.length > UNDO_LIMIT) undoStack.shift();
  redoStack.length = 0;
  refreshUndoButtons();
}
async function undo() {
  const entry = undoStack.pop(); if (!entry) return;
  const cur = snapshotPart(entry.name); if (cur) redoStack.push({ name: entry.name, snap: cur });
  await savePart(entry.name, entry.snap, null, "keep");
  refreshUndoButtons();
}
async function redo() {
  const entry = redoStack.pop(); if (!entry) return;
  const cur = snapshotPart(entry.name); if (cur) undoStack.push({ name: entry.name, snap: cur });
  await savePart(entry.name, entry.snap, null, "keep");
  refreshUndoButtons();
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
  if (S.dirtyCode && name !== S.selected && !confirm(t("insp.discard"))) return;
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
    await Promise.all([...summary.parts.map(loadMesh), ...(summary.assembly || []).map(loadAsmMesh)]);
    if (S.plate > plateCount()) S.plate = 0;
    renderAsm();
    renderParams(); renderParts(); renderInspector(force); syncSceneProps(); renderCheckpoints(); renderPlates();
    if (document.activeElement !== $("#notes")) $("#notes").value = summary.notes || "";
    if (document.activeElement !== $("#common")) { $("#common").value = summary.common || ""; S.dirtyCommon = false; $("#commonRun").classList.remove("dirty"); }
    document.title = `CAD-Studio · ${summary.name}`;
    if (first) setView("iso");
    if (first && location.hash === "#assembly" && asmItems().length) setAsm(true);  // link straight to the assembly
  }).catch((e) => toast(e.message, "err"));
  return applying;
}

async function reload() { await apply(await api("/api/project")); refreshUndoButtons(); }

async function loadProjects() {
  const { projects, current } = await api("/api/projects");
  const sel = $("#projectSelect"); sel.innerHTML = "";
  for (const p of projects) sel.add(new Option(p, p, false, p === current));
}
$("#projectSelect").onchange = async (e) => {
  for (const m of S.meshes.values()) partsGroup.remove(m.mesh);
  S.meshes.clear(); S.selected = null; S.plate = 0;
  await apply(await api("/api/projects", { method: "POST", body: JSON.stringify({ name: e.target.value }) }));
};
$("#newProject").onclick = async () => {
  const n = prompt(t("project.prompt")); if (!n) return;
  for (const m of S.meshes.values()) partsGroup.remove(m.mesh);
  S.meshes.clear(); S.selected = null; S.plate = 0;
  await apply(await api("/api/projects", { method: "POST", body: JSON.stringify({ name: n }) }));
  loadProjects();
};

let notesTimer;
$("#notes").oninput = (e) => { clearTimeout(notesTimer); notesTimer = setTimeout(() => api("/api/notes", { method: "PUT", body: JSON.stringify({ notes: e.target.value }) }), 600); };

// shared code, run before every part's own code (helpers/constants reused across parts) - explicit build,
// like part code, since a mistake here breaks every part at once rather than just one.
const commonEl = $("#common");
commonEl.oninput = () => { S.dirtyCommon = true; $("#commonRun").classList.add("dirty"); };
commonEl.onkeydown = (e) => {
  if (e.key === "Tab") { e.preventDefault(); const s = commonEl.selectionStart; commonEl.setRangeText("    ", s, commonEl.selectionEnd, "end"); commonEl.oninput(); }
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); runCommon(); }
};
async function runCommon() {
  S.dirtyCommon = false; $("#commonRun").classList.remove("dirty");
  try { apply(await api("/api/common", { method: "PUT", body: JSON.stringify({ common: commonEl.value }) })); }
  catch (e) { toast(e.message, "err"); }
}
$("#commonRun").onclick = runCommon;

// ------------------------------------------------------------------ toolbar: add / import / export
const TEMPLATES = {
  box: "result = Box(30, 20, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))\nresult = fillet(result.edges().filter_by(Axis.Z), 2)",
  cylinder: "result = Cylinder(radius=10, height=20, align=(Align.CENTER, Align.CENTER, Align.MIN))",
  sphere: "result = Pos(0, 0, 10) * Sphere(10)",
  text: "result = extrude(Text('Hello', font_size=12), amount=2)",
  code: "# build123d – wijs de vorm toe aan result\nwith BuildPart() as bp:\n    Box(40, 30, 4, align=(Align.CENTER, Align.CENTER, Align.MIN))\n    with Locations((0, 0, 4)):\n        Cylinder(6, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))\n    fillet(bp.edges().group_by(Axis.Z)[-1], 1)\nresult = bp.part",
};
document.querySelectorAll("[data-add]").forEach((b) => b.onclick = async () => {
  const kind = b.dataset.add;
  let name = kind, i = 2; while (S.project.parts.some((p) => p.name === name)) name = `${kind}${i++}`;
  await savePart(name, { code: TEMPLATES[kind], type: "code", plate: S.plate || 1 }, name, true);
});
$("#importFile").onchange = async (e) => {
  const f = e.target.files[0]; if (!f) return;
  const fd = new FormData(); fd.append("file", f);
  const r = await fetch("/api/import", { method: "POST", body: fd });
  const body = await r.json(); if (!r.ok) return toast(body.error || body.detail, "err");
  await apply(body); toast(t("import.done", { name: f.name }), "ok"); e.target.value = "";
};
async function doExport(format) {
  try {
    const how = plateCount() > 1 ? $("#exportPlates").value : "all";
    const res = await api("/api/export", { method: "POST", body: JSON.stringify({
      format, flavor: $("#exportFlavor").value, mode: $("#exportMode").value,
      split_plates: how === "split", plate: how === "current" && S.plate ? S.plate : null }) });
    const links = res.download.map((u) => `<a href="${u}">${decodeURIComponent(u.split("/").pop().split("%2F").pop())}</a>`).join("<br>");
    let slots = "";
    if (res.filament_slots) slots = "\n" + Object.entries(res.filament_slots).map(([k, v]) => `Slot ${k}: ${v.join(", ")}`).join("\n");
    toast(`${t("export.saved", { path: res.path || (res.paths || res.files).join(", ") })}${slots}${res.warnings && res.warnings.length ? "\n⚠ " + res.warnings.join("\n") : ""}\n${links}`, "ok", 15000);
    res.download.forEach((u) => { const a = document.createElement("a"); a.href = u; a.download = ""; document.body.appendChild(a); a.click(); a.remove(); });
  } catch (e) { toast(e.message, "err", 8000); }
}
$("#export3mf").onclick = () => doExport("3mf");
$("#exportStl").onclick = () => doExport("stl");
$("#exportStep").onclick = () => doExport("step");

// ------------------------------------------------------------------ build plates (beds)
// ------------------------------------------------------------------ print bar (slice + send via Home Assistant)
const printPlate = () => (plateCount() === 1 ? 1 : S.plate);
let printSeq = 0;
function showSlice(last) {
  const info = $("#sliceInfo");
  if (!last) { info.textContent = ""; info.classList.remove("old"); $("#printBtn").classList.add("hidden"); return; }
  const bits = [last.print_time, last.filament_g ? `${last.filament_g} g` : ""];
  if (last.pauses) bits.push(t("print.pauses", { n: last.pauses }));
  info.textContent = bits.filter(Boolean).join(" · ") + (last.outdated ? ` (${t("print.outdated")})` : "");
  info.classList.toggle("old", !!last.outdated);
  $("#printBtn").classList.toggle("hidden", !S.printHA || last.outdated);
}
async function refreshPrintBar() {
  const seq = ++printSeq;
  const bar = $("#printBar");
  if (!S.project || S.asm) { bar.classList.add("hidden"); return; }
  const k = printPlate();
  try {
    const st = await api(`/api/printing?plate=${k || 1}`);
    if (seq !== printSeq) return;
    S.printHA = st.home_assistant;
    bar.classList.toggle("hidden", !st.slicer);
    $("#sliceBtn").disabled = !k;
    if (!k) { $("#sliceInfo").textContent = t("print.pickbed"); $("#printBtn").classList.add("hidden"); return; }
    showSlice(st.last);
  } catch { bar.classList.add("hidden"); }
}
$("#sliceBtn").onclick = async () => {
  const k = printPlate(); if (!k) return;
  $("#sliceBtn").disabled = true; $("#sliceInfo").textContent = t("print.busy"); $("#printBtn").classList.add("hidden");
  try {
    const r = await api("/api/slice", { method: "POST", body: JSON.stringify({ plate: k, one_filament: true }) });
    showSlice(r.last);
    for (const w of r.warnings || []) toast(w, "err");
  } catch (e) { toast(e.message, "err", 9000); $("#sliceInfo").textContent = ""; }
  finally { $("#sliceBtn").disabled = false; }
};
$("#printBtn").onclick = async () => {
  const k = printPlate(); if (!k || !confirm(t("print.confirm", { i: k }))) return;
  try { await api("/api/print", { method: "POST", body: JSON.stringify({ plate: k }) }); toast(t("print.sent")); }
  catch (e) { toast(e.message, "err", 9000); }
};

function renderPlates() {
  if (!S.project) return;
  refreshPrintBar();
  const n = plateCount(); const over = overfullPlates();
  const box = $("#plateTabs"); box.innerHTML = "";
  const mk = (label, k, title) => {
    const b = document.createElement("button"); b.textContent = label; if (title) b.title = title;
    b.classList.toggle("on", S.plate === k || (n === 1 && k === 1));
    if (k && over.includes(k)) b.classList.add("over");
    b.onclick = () => showPlate(k);
    box.appendChild(b);
  };
  if (n > 1) mk(t("plates.all"), 0, t("plates.tab.title", { i: 0 }));
  for (let i = 1; i <= n; i++) mk(t("plates.plate", { i }), i, t("plates.tab.title", { i }));
  $("#plateDel").disabled = n <= 1;
  $("#exportPlates").classList.toggle("hidden", n <= 1);
}
function showPlate(k, focus = true) {
  if (k > plateCount() || k < 0) return;
  S.plate = plateCount() > 1 ? k : 0;
  const sel = S.selected && S.project.parts.find((q) => q.name === S.selected);
  if (sel && !onShownPlate(sel)) { S.selected = null; renderInspector(); }
  renderParts(); syncSceneProps(); renderPlates();
  if (focus) setView("fit");
}
$("#plateAdd").onclick = async () => {
  try {
    await apply(await api("/api/plates", { method: "POST" }));
    showPlate(plateCount());
  } catch (e) { toast(e.message, "err"); }
};
$("#plateDel").onclick = async () => {
  const n = plateCount(); if (n <= 1) return;
  const k = S.plate || n;
  if (!confirm(t("plates.remove.confirm", { i: k, to: Math.max(1, k - 1) }))) return;
  try { S.plate = 0; await apply(await api(`/api/plates/${k}`, { method: "DELETE" })); setView("fit"); }
  catch (e) { toast(e.message, "err"); }
};
$("#plateArrange").onclick = async () => {
  try {
    const res = await api("/api/plates/arrange", { method: "POST", body: "{}" });
    S.plate = 0; await apply(res);
    const w = res.arrange.warnings || [];
    toast(t("plates.arrange.done", { n: res.arrange.plates }) + (w.length ? "\n⚠ " + w.join("\n") : ""), w.length ? "" : "ok");
    setView("fit");
  } catch (e) { toast(e.message, "err"); }
};

// view bar
document.querySelectorAll("[data-view]").forEach((b) => b.onclick = () => setView(b.dataset.view));
const toggle = (key, btn) => { S[key] = !S[key]; btn.classList.toggle("on", S[key]); syncSceneProps(); };
// move/resize/rotate share one gizmo, so turning one on turns the other two off
const GIZMO_KEYS = ["move", "resize", "rotate"];
const setGizmoMode = (key) => {
  for (const k of GIZMO_KEYS) S[k] = k === key ? !S[k] : false;
  $("#toggleMove").classList.toggle("on", S.move);
  $("#toggleResize").classList.toggle("on", S.resize);
  $("#toggleRotate").classList.toggle("on", S.rotate);
  syncSceneProps();
};
$("#toggleXray").onclick = (e) => toggle("xray", e.currentTarget);
$("#toggleEdges").onclick = (e) => toggle("edges", e.currentTarget);
$("#toggleBed").onclick = (e) => toggle("bed", e.currentTarget);
$("#toggleOverhangs").onclick = (e) => toggle("overhangs", e.currentTarget);
$("#toggleMeasure").onclick = (e) => { clearMeasure(); toggle("measure", e.currentTarget); updateDims(); };
$("#toggleClip").onclick = (e) => {
  S.clip = !S.clip; e.currentTarget.classList.toggle("on", S.clip);
  $("#clipPanel").classList.toggle("hidden", !S.clip);
  updateClipPlane();
};
$("#clipSlider").oninput = updateClipPlane;
$("#clipAxis").onchange = (e) => { S.clipAxis = e.target.value; updateClipPlane(); };
$("#clipFlip").onclick = () => { S.clipFlip = !S.clipFlip; updateClipPlane(); };
$("#btnUndo").onclick = undo;
$("#btnRedo").onclick = redo;
$("#toggleMove").onclick = () => setGizmoMode("move");
$("#toggleResize").onclick = () => setGizmoMode("resize");
$("#toggleRotate").onclick = () => setGizmoMode("rotate");
$("#toggleEdges").classList.add("on"); $("#toggleBed").classList.add("on");
window.addEventListener("keydown", (e) => {
  if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) return;
  if (e.key === "x") $("#toggleXray").click();
  if (e.key === "e") $("#toggleEdges").click();
  if (e.key === "g") $("#toggleMove").click();
  if (e.key === "s") $("#toggleResize").click();
  if (e.key === "r") $("#toggleRotate").click();
  if (e.key === "o") $("#toggleOverhangs").click();
  if (e.key === "m") $("#toggleMeasure").click();
  if (e.key === "c") $("#toggleClip").click();
  if (e.key === "f") setView("fit");
  if (/^[0-9]$/.test(e.key) && !e.ctrlKey && !e.metaKey && !e.altKey) showPlate(+e.key);
  if (e.key === "Escape") { select(null); if (S.measure) clearMeasure(); }
  if (e.key === "Delete" && S.selected) $("#pDel")?.click();
  if ((e.key === "z" || e.key === "Z") && (e.ctrlKey || e.metaKey)) { e.preventDefault(); e.shiftKey ? redo() : undo(); }
  if (e.key === "d" && (e.ctrlKey || e.metaKey) && S.selected) { e.preventDefault(); $("#pDup")?.click(); }
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
      for (const m of asmMeshes.values()) asmGroup.remove(m.mesh);
      S.meshes.clear(); asmMeshes.clear(); S.selected = null; S.plate = 0;
      S.asm = false; S.asmHide = new Set(); S.asmGhost = null; loadProjects();
    }
    if (rev !== lastRev || project !== lastProj) {
      lastRev = rev; lastProj = project;
      if (!S.project || S.project.rev !== rev || S.project.name !== project) await reload();
    }
  };
}

// version footer (right panel): running build + whether a newer one is published
let versionInfo = null;
function renderVersion() {
  const el = $("#version");
  if (!el || !versionInfo) return;
  const v = versionInfo;
  const esc = (x) => String(x).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const date = v.built ? new Date(v.built).toLocaleString(LANG === "nl" ? "nl-NL" : "en-GB",
    { dateStyle: "medium", timeStyle: "short" }) : "";
  let line2 = v.commit ? t("version.build", { commit: esc(v.short), date: esc(date || "?") }) : t("version.dev");
  let status = "";
  if (v.up_to_date === true) status = `<span class="ok">✓ ${t("version.latest")}</span>`;
  else if (v.up_to_date === false) status = `<span class="upd">⚠ ${t("version.update", { commit: esc(v.latest_commit) })}</span>`;
  else if (v.update_check_error) status = t("version.nocheck");
  const orca = v.orcaslicer ? ` · ${t("version.orca", { v: esc(v.orcaslicer) })}` : "";
  el.innerHTML = `CAD-Studio v${esc(v.version)}${orca}<br>${line2}${status ? "<br>" + status : ""}`;
}
async function loadVersion() {
  try { versionInfo = await api("/api/version"); renderVersion(); } catch { /* optional */ }
}
loadVersion();
setInterval(loadVersion, 60 * 60 * 1000);

// language
applyI18n();
$("#langSelect").value = LANG;
$("#langSelect").onchange = (e) => {
  setLang(e.target.value);
  renderVersion();
  if (S.project) { renderParams(); renderParts(); renderInspector(true); updateDims(); renderPlates(); syncSceneProps(); }
};

await loadProjects();
await reload();
connectEvents();
