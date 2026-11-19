"""Project model: a project is a set of named parts plus global parameters.

Each part is either
  * a "code" part: build123d Python code that assigns a 3D shape to `result`, or
  * a "mesh" part: an imported STL/3MF/OBJ (reference geometry, e.g. a model from MakerWorld).

Projects live on disk as JSON so the MCP server (Claude) and the web editor (you)
always see the same state. Every save bumps `rev`, which the web UI polls to live-reload.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import math
import os
import re
import shutil
import threading
import time
import traceback
from pathlib import Path
from typing import Any

import logging

import numpy as np

logging.getLogger("build123d").setLevel(logging.WARNING)

HOME = Path(os.environ.get("CADSTUDIO_HOME", Path.home() / "CADStudio"))
PROJECTS = HOME / "projects"
STATE_FILE = HOME / "state.json"
LOCK = threading.RLock()

# Kobra S1 build volume (mm)
BED = (250.0, 250.0, 250.0)

PALETTE = ["#F2F2F2", "#D62828", "#2A9D8F", "#F4A261", "#264653", "#E9C46A", "#8E44AD", "#111111"]

PART_DEFAULTS: dict[str, Any] = {
    "type": "code",
    "code": "",
    "color": "#F2F2F2",
    "filament": 1,
    "visible": True,
    "export": True,
    "location": [0, 0, 0, 0, 0, 0],  # x, y, z (mm), rx, ry, rz (degrees), applied after the code
    "mesh_file": None,
    "note": "",
}

PART_REF = re.compile(r"""part\(\s*["']([^"']+)["']""")


class PartError(Exception):
    pass


def slugify(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_\- ]+", "", name).strip().replace(" ", "_")
    return s or "project"


def _sha(obj: Any) -> str:
    return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


# --------------------------------------------------------------------------- workspace

def list_projects() -> list[str]:
    PROJECTS.mkdir(parents=True, exist_ok=True)
    return sorted(p.name for p in PROJECTS.iterdir() if (p / "project.json").exists())


def current_project_name() -> str:
    try:
        return json.loads(STATE_FILE.read_text())["current"]
    except Exception:
        return "demo"


def set_current_project(name: str) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({"current": slugify(name)}))


_open: dict[str, "Project"] = {}


def get_project(name: str | None = None) -> "Project":
    """Return the (cached) Project object, reloading from disk when the file changed."""
    with LOCK:
        name = slugify(name or current_project_name())
        proj = _open.get(name)
        if proj is None:
            proj = Project(name)
            _open[name] = proj
        proj.refresh()
        return proj


# --------------------------------------------------------------------------- project

class Project:
    def __init__(self, name: str):
        self.name = slugify(name)
        self.dir = PROJECTS / self.name
        self.file = self.dir / "project.json"
        self.data: dict[str, Any] = {"name": self.name, "rev": 0, "params": {}, "parts": [], "notes": ""}
        self._mtime = None
        self._cache: dict[str, dict] = {}  # part name -> {"key", "shape", "mesh", "info"}
        if self.file.exists():
            self.refresh(force=True)
        else:
            self.dir.mkdir(parents=True, exist_ok=True)
            self.save()

    # ---- persistence
    def refresh(self, force: bool = False) -> None:
        if not self.file.exists():
            return
        m = self.file.stat().st_mtime_ns
        if force or m != self._mtime:
            self.data = json.loads(self.file.read_text(encoding="utf-8"))
            self._mtime = m

    def save(self) -> None:
        with LOCK:
            self.data["rev"] = int(self.data.get("rev", 0)) + 1
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = self.file.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
            os.replace(tmp, self.file)
            self._mtime = self.file.stat().st_mtime_ns

    @property
    def rev(self) -> int:
        return int(self.data.get("rev", 0))

    @property
    def params(self) -> dict:
        return self.data.setdefault("params", {})

    @property
    def parts(self) -> list[dict]:
        return self.data.setdefault("parts", [])

    # ---- part CRUD
    def find(self, name: str) -> dict:
        for p in self.parts:
            if p["name"] == name:
                return {**PART_DEFAULTS, **p}
        raise PartError(f"Part '{name}' bestaat niet. Bestaande parts: {[p['name'] for p in self.parts]}")

    def has(self, name: str) -> bool:
        return any(p["name"] == name for p in self.parts)

    def upsert_part(self, name: str, **fields) -> dict:
        with LOCK:
            fields = {k: v for k, v in fields.items() if v is not None}
            if "location" in fields:
                loc = [float(v) for v in fields["location"]]
                fields["location"] = (loc + [0] * 6)[:6]
            if "filament" in fields:
                fields["filament"] = max(1, min(16, int(fields["filament"])))
            for p in self.parts:
                if p["name"] == name:
                    p.update(fields)
                    break
            else:
                new = {**PART_DEFAULTS, "name": name}
                if "color" not in fields:
                    new["color"] = PALETTE[len(self.parts) % len(PALETTE)]
                if "filament" not in fields:
                    # same colour -> same filament slot; otherwise next free slot
                    used = {q.get("color", "").lower(): q.get("filament", 1) for q in self.parts}
                    col = fields.get("color", new["color"]).lower()
                    free = next(i for i in range(1, 17) if i not in set(used.values()))
                    new["filament"] = used.get(col, free)
                new.update(fields)
                self.parts.append(new)
            self.save()
            return self.find(name)

    def delete_part(self, name: str) -> None:
        with LOCK:
            before = len(self.parts)
            self.data["parts"] = [p for p in self.parts if p["name"] != name]
            if len(self.parts) == before:
                raise PartError(f"Part '{name}' bestaat niet")
            self._cache.pop(name, None)
            self.save()

    def rename_part(self, old: str, new: str) -> None:
        with LOCK:
            if self.has(new):
                raise PartError(f"Part '{new}' bestaat al")
            for p in self.parts:
                if p["name"] == old:
                    p["name"] = new
                    # update references in other parts' code
                    for q in self.parts:
                        q["code"] = re.sub(rf"""part\(\s*(["']){re.escape(old)}\1""", f'part("{new}"', q.get("code", ""))
                    self._cache.clear()
                    self.save()
                    return
            raise PartError(f"Part '{old}' bestaat niet")

    def set_params(self, params: dict, replace: bool = False) -> None:
        with LOCK:
            if replace:
                self.data["params"] = dict(params)
            else:
                self.params.update(params)
                for k, v in list(self.params.items()):
                    if v is None:
                        del self.params[k]
            self.save()

    def import_mesh(self, name: str, src: str | Path, color: str | None = None, filament: int | None = None) -> dict:
        src = Path(src).expanduser()
        if not src.exists():
            raise PartError(f"Bestand niet gevonden: {src}")
        mdir = self.dir / "meshes"
        mdir.mkdir(parents=True, exist_ok=True)
        dst = mdir / f"{slugify(name)}{src.suffix.lower()}"
        shutil.copyfile(src, dst)
        return self.upsert_part(name, type="mesh", mesh_file=str(dst.relative_to(self.dir)), color=color,
                                filament=filament, code="")

    # ---- building
    def _deps(self, name: str, seen: set | None = None) -> list[str]:
        seen = seen if seen is not None else set()
        p = self.find(name)
        out = []
        for ref in PART_REF.findall(p.get("code") or ""):
            if ref not in seen and self.has(ref):
                seen.add(ref)
                out.append(ref)
                out += self._deps(ref, seen)
        return out

    def _key(self, name: str) -> str:
        specs = [self.find(n) for n in [name] + self._deps(name)]
        for s in specs:
            if s["type"] == "mesh" and s.get("mesh_file"):
                f = self.dir / s["mesh_file"]
                s["_mtime"] = f.stat().st_mtime_ns if f.exists() else 0
        return _sha([specs, self.params])

    def build(self, name: str, _stack: tuple = ()) -> dict:
        """Build a part. Returns cache entry {"shape", "mesh": (V, F), "info"}; never raises for user-code errors."""
        with LOCK:
            key = self._key(name)
            hit = self._cache.get(name)
            if hit and hit["key"] == key:
                return hit
            spec = self.find(name)
            t0 = time.time()
            entry: dict[str, Any] = {"key": key, "shape": None, "mesh": None, "info": {"name": name, "key": key[:12]}}
            out = io.StringIO()
            try:
                if name in _stack:
                    raise PartError(f"Circulaire verwijzing: {' -> '.join(_stack + (name,))}")
                if spec["type"] == "mesh":
                    V, F = self._load_mesh(spec)
                    entry["mesh"] = (V, F)
                else:
                    with contextlib.redirect_stdout(out):
                        shape = self._eval_code(spec, _stack + (name,))
                    entry["shape"] = shape
                    entry["mesh"] = tessellate(shape)
                    try:
                        entry["info"]["volume_mm3"] = round(float(shape.volume), 2)
                    except Exception:
                        pass
                V, F = entry["mesh"]
                if len(F) == 0:
                    raise PartError("Resultaat bevat geen geometrie (leeg na boolean?)")
                lo, hi = V.min(axis=0), V.max(axis=0)
                entry["info"].update(
                    ok=True,
                    bbox_min=[round(float(x), 3) for x in lo],
                    bbox_max=[round(float(x), 3) for x in hi],
                    size=[round(float(x), 3) for x in hi - lo],
                    triangles=int(len(F)),
                    watertight=is_watertight(F),
                )
                if spec["type"] == "mesh" and "volume_mm3" not in entry["info"]:
                    entry["info"]["volume_mm3"] = round(mesh_volume(V, F), 2)
            except Exception as e:  # user code errors are reported, not raised
                tb = traceback.format_exc(limit=6)
                # keep only the frames from the user's code where possible
                user = [ln for ln in tb.splitlines() if "<part " in ln]
                entry["info"].update(ok=False, error=f"{type(e).__name__}: {e}",
                                     traceback="\n".join(user) or tb)
            entry["info"]["build_s"] = round(time.time() - t0, 3)
            if out.getvalue():
                entry["info"]["stdout"] = out.getvalue()[-4000:]
            self._cache[name] = entry
            return entry

    def _eval_code(self, spec: dict, stack: tuple):
        import build123d as bd

        ns: dict[str, Any] = {}
        exec("from build123d import *", ns)
        ns.update(math=math, np=np, params=dict(self.params))
        ns.update(self.params)

        def part(ref: str):
            e = self.build(ref, stack)
            if not e["info"].get("ok"):
                raise PartError(f"part('{ref}') faalt: {e['info'].get('error')}")
            if e["shape"] is None:
                raise PartError(f"part('{ref}') is een geïmporteerde mesh en kan niet in CAD-bewerkingen gebruikt worden")
            return e["shape"]

        ns["part"] = part
        code = spec.get("code") or ""
        if not code.strip():
            raise PartError("Part heeft nog geen code")
        exec(compile(code, f"<part {spec['name']}>", "exec"), ns)
        result = ns.get("result")
        if result is None:
            # fall back to the last BuildPart context in the namespace
            for v in reversed(list(ns.values())):
                if isinstance(v, bd.BuildPart):
                    result = v
                    break
        if result is None:
            raise PartError("De code moet een 3D-vorm toewijzen aan `result`")
        if isinstance(result, bd.BuildPart):
            result = result.part
        if isinstance(result, (list, tuple)):
            result = bd.Compound(children=list(result))
        if not isinstance(result, bd.Shape):
            raise PartError(f"`result` is een {type(result).__name__}, verwacht een build123d Part/Solid/Compound")
        if not result.solids():
            raise PartError("`result` bevat geen solids (is het een 2D-sketch? gebruik extrude())")
        x, y, z, rx, ry, rz = spec.get("location") or [0] * 6
        if any((x, y, z, rx, ry, rz)):
            result = bd.Pos(x, y, z) * (bd.Rot(rx, ry, rz) * result)
        return result

    def _load_mesh(self, spec: dict):
        import trimesh

        f = self.dir / (spec.get("mesh_file") or "")
        if not f.exists():
            raise PartError(f"Meshbestand ontbreekt: {f}")
        m = trimesh.load(f, force="mesh")
        V = np.asarray(m.vertices, dtype=np.float64)
        F = np.asarray(m.faces, dtype=np.int64)
        if spec.get("recenter", True):  # models from MakerWorld etc. sit somewhere on *their* bed: centre on origin, z=0
            lo, hi = V.min(axis=0), V.max(axis=0)
            V = V - np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]])
        x, y, z, rx, ry, rz = spec.get("location") or [0] * 6
        if any((rx, ry, rz)):
            R = rot_matrix(rx, ry, rz)
            V = V @ R.T
        V = V + np.array([x, y, z])
        return V, F

    def build_all(self) -> dict[str, dict]:
        return {p["name"]: self.build(p["name"]) for p in self.parts}

    def summary(self) -> dict:
        infos = self.build_all()
        parts = []
        for p in self.parts:
            q = {**PART_DEFAULTS, **p}
            parts.append({**q, "info": infos[p["name"]]["info"]})
        return {"name": self.name, "rev": self.rev, "params": self.params, "notes": self.data.get("notes", ""),
                "parts": parts, "bed": BED, "dir": str(self.dir)}


# --------------------------------------------------------------------------- geometry helpers

def tessellate(shape, tolerance: float = 0.02, angular: float = 0.15):
    verts, tris = shape.tessellate(tolerance, angular)
    V = np.array([[v.X, v.Y, v.Z] for v in verts], dtype=np.float64)
    F = np.array(tris, dtype=np.int64).reshape(-1, 3)
    return weld(V, F)


def weld(V, F, tol: float = 1e-5):
    """Merge coincident vertices (OCCT tessellates every face separately) and drop degenerate triangles,
    so the exported mesh is closed/manifold and slicers don't need to 'repair' it."""
    if len(V) == 0:
        return V, F
    key = np.round(V / tol).astype(np.int64)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    inv = inv.reshape(-1)
    V2, F2 = V[first], inv[F]
    ok = (F2[:, 0] != F2[:, 1]) & (F2[:, 1] != F2[:, 2]) & (F2[:, 0] != F2[:, 2])
    return V2, F2[ok]


def is_watertight(F) -> bool:
    """Every edge shared by exactly two triangles."""
    e = np.sort(np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]]), axis=1)
    _, counts = np.unique(e, axis=0, return_counts=True)
    return bool(len(counts) and np.all(counts == 2))


def mesh_volume(V, F) -> float:
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    return float(abs(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0))


def rot_matrix(rx, ry, rz):
    """Same convention as build123d Rot(rx, ry, rz) (intrinsic X, then Y, then Z)."""
    rx, ry, rz = map(math.radians, (rx, ry, rz))
    Rx = np.array([[1, 0, 0], [0, math.cos(rx), -math.sin(rx)], [0, math.sin(rx), math.cos(rx)]])
    Ry = np.array([[math.cos(ry), 0, math.sin(ry)], [0, 1, 0], [-math.sin(ry), 0, math.cos(ry)]])
    Rz = np.array([[math.cos(rz), -math.sin(rz), 0], [math.sin(rz), math.cos(rz), 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def exportable_meshes(proj: Project, only: list[str] | None = None, include_hidden: bool = False):
    """[(part_spec, V, F)] for every buildable part that should be exported."""
    out = []
    for p in proj.parts:
        spec = {**PART_DEFAULTS, **p}
        if only and spec["name"] not in only:
            continue
        if not only and (not spec["export"] or (not spec["visible"] and not include_hidden)):
            continue
        e = proj.build(spec["name"])
        if not e["info"].get("ok"):
            raise PartError(f"Part '{spec['name']}' bouwt niet: {e['info'].get('error')}")
        V, F = e["mesh"]
        out.append((spec, V, F))
    if not out:
        raise PartError("Niets om te exporteren (geen zichtbare/exporteerbare parts)")
    return out


def ensure_demo() -> None:
    """Create a small multi-colour demo project on first run."""
    if list_projects():
        return
    proj = get_project("demo")
    proj.set_params({"w": 60, "d": 40, "h": 18, "wall": 2.0})
    proj.upsert_part("bakje", color="#F2F2F2", filament=1, code=(
        "body = Box(w, d, h, align=(Align.CENTER, Align.CENTER, Align.MIN))\n"
        "body = fillet(body.edges().filter_by(Axis.Z), 4)\n"
        "body = offset(body, amount=-wall, openings=body.faces().sort_by(Axis.Z)[-1])\n"
        "result = body - part('tekst')\n"))
    proj.upsert_part("tekst", color="#D62828", filament=2, code=(
        "# Plane.XZ kijkt naar -Y (voorkant). Inleg van 0.8 mm, vlak met de voorwand.\n"
        "label = Plane.XZ.offset(d/2 - 0.8) * Text('XMAS', font_size=9)\n"
        "result = Pos(0, 0, h/2) * extrude(label, amount=0.8)\n"))
    set_current_project("demo")
