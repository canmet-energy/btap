"""3D geometry viewer — port of the campus repo's renderer
(canmet-energy/campus, src/buildings/reports/geometry_view.py, via the Ruby
gem's render.rb): export the model to glTF with the SDK's
GltfForwardTranslator and render it with Google's <model-viewer> web
component, glTF embedded as a base64 data URI so the HTML needs no side
files.

Robustness measures carried over verbatim from campus:
 1. The C++ translator can SEGFAULT on un-triangulatable surfaces, so
    every export runs in an isolated child process (render_worker.py) —
    NEVER call the exporter in-process.
 2. A fallback ladder repairs crashing models on in-memory copies (the
    source .osm is never modified): (a) full export -> (b) sub-surfaces
    removed (massing shell) -> (c) binary-search the offending base
    surfaces in child processes and drop just those.
 3. Material colors boosted for contrast (palette keyed on the SDK's
    glTF material names).

NOTE: the <model-viewer> SCRIPT loads from the Google CDN at view time
(needs internet, same trade-off campus ships with; the caption says so).
The geometry itself is fully embedded.

Port of btap-modeling/lib/btap_modeling/geometry/render.rb (D-79).
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile

import openstudio

WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "render_worker.py")
MV_VERSION = "4.3.1"
MV_CDN = f"https://ajax.googleapis.com/ajax/libs/model-viewer/{MV_VERSION}/model-viewer.min.js"
MAX_REMOVE = 12
MAX_PROBES = 80

#: name -> ([r, g, b, a], roughness) (campus palette, verbatim)
PALETTE = {
    "Wall": ([0.84, 0.57, 0.26, 1.00], 0.65),        # warm sand
    "RoofCeiling": ([0.70, 0.19, 0.16, 1.00], 0.65),  # terracotta
    "Floor": ([0.29, 0.33, 0.39, 1.00], 0.70),        # cool slate
    "Door": ([0.50, 0.29, 0.10, 1.00], 0.60),         # rich wood
    "Window": ([0.18, 0.60, 0.93, 0.42], 0.08),       # vivid glass
}


# ---------------------------- material contrast ----------------------------

def saturate(rgb, factor=1.5):
    lum = (0.2126 * rgb[0]) + (0.7152 * rgb[1]) + (0.0722 * rgb[2])
    return [min(max(lum + ((c - lum) * factor), 0.0), 1.0) for c in rgb]


def boost_materials(gltf):
    """Ruby's boost_materials!: mutates and returns the parsed glTF."""
    for mat in gltf.get("materials") or []:
        pbr = mat.setdefault("pbrMetallicRoughness", {})
        entry = PALETTE.get(mat.get("name"))
        if entry is not None:
            pbr["baseColorFactor"] = list(entry[0])
            pbr["roughnessFactor"] = entry[1]
        else:
            base = pbr.get("baseColorFactor") or [0.7, 0.7, 0.7, 1.0]
            alpha = base[3] if len(base) > 3 else 1.0
            pbr["baseColorFactor"] = saturate(base[:3]) + [alpha]
            pbr["roughnessFactor"] = 0.62
        pbr["metallicFactor"] = 0.0
    return gltf


# ---------------------------- subprocess export ----------------------------

def run_export(osm_path, out_path, control, timeout=240):
    """One worker run with a control dict. True iff clean exit + non-empty
    file. The worker is ALWAYS a spawned child process — the crash isolation
    that makes untrusted geometry survivable."""
    if os.path.exists(out_path):
        os.remove(out_path)
    fd, ctrl_path = tempfile.mkstemp(prefix="gltf_ctrl", suffix=".json")
    try:
        with os.fdopen(fd, "w") as ctrl:
            ctrl.write(json.dumps(control))
        try:
            proc = subprocess.run(
                [sys.executable, WORKER, str(osm_path), str(out_path), ctrl_path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)
        except subprocess.TimeoutExpired:
            # subprocess.run already killed the child on timeout.
            return False
        return (proc.returncode == 0 and os.path.exists(out_path)
                and os.path.getsize(out_path) > 0)
    finally:
        try:
            os.unlink(ctrl_path)
        except FileNotFoundError:
            pass


def surface_handles(osm_path):
    """Loading a model never crashes (only export does) — in-process is
    fine."""
    loaded = openstudio.model.Model.load(openstudio.path(str(osm_path)))
    if not loaded.is_initialized():
        return []

    return [str(s.handle()) for s in loaded.get().getSurfaces()]


def export_repaired(osm_path, out_path, audit=None, exporter=None):
    """The campus fallback ladder. Returns ``(ok, note)``; leaves the good
    glTF at out_path. ``exporter`` is injectable for deterministic ladder
    tests."""
    if exporter is None:
        exporter = lambda ctrl, out: run_export(osm_path, out, ctrl)  # noqa: E731

    if exporter({"remove_subsurfaces": False}, out_path):
        return True, ""

    if exporter({"remove_subsurfaces": True}, out_path):
        note = "Approximate massing — windows/doors omitted to render."
        if audit is not None:
            audit.warn("render", "glTF export crashed on sub-surfaces — windows/doors omitted (massing shell)")
        return True, note

    handles = surface_handles(osm_path)
    if not handles:
        return False, ""

    probe_out = f"{out_path}.probe.gltf"

    def keep_ok(keep):
        return exporter({"remove_subsurfaces": True, "keep_surfaces": keep}, probe_out)

    removed = []
    probes = 0
    while probes < MAX_PROBES:
        keep = [h for h in handles if h not in removed]
        probes += 1
        if keep_ok(keep):
            break

        # binary-search one offending surface within `keep` (which crashes)
        cur = keep
        while len(cur) > 1 and probes < MAX_PROBES:
            left = cur[:len(cur) // 2]
            probes += 1
            cur = cur[len(cur) // 2:] if keep_ok(left) else left
        removed.append(cur[0])
        if audit is not None:
            audit.info("render", f"bisection: crashing surface isolated ({len(removed)}), {probes} probes")
        if len(removed) >= MAX_REMOVE:
            break
    if os.path.exists(probe_out):
        os.remove(probe_out)

    if removed and exporter({"remove_subsurfaces": True, "drop_surfaces": removed}, out_path):
        note = f"Approximate massing — windows/doors + {len(removed)} bad surface(s) omitted."
        if audit is not None:
            audit.warn("render",
                       f"glTF export required dropping {len(removed)} crashing surface(s) — approximate massing",
                       inputs={"dropped_handles": removed})
        return True, note
    return False, ""


# ------------------------------- viewer -----------------------------------

def _escape_html(value):
    """Ruby CGI.escapeHTML: & < > " and ' (as &#39;)."""
    return (str(value).replace("&", "&amp;").replace('"', "&quot;")
            .replace("'", "&#39;").replace("<", "&lt;").replace(">", "&gt;"))


def viewer_html(src, height=480, note=""):
    if note == "":
        banner = ""
    else:
        banner = ('<div style="font-size:12px;color:#b06a00;background:#fff6e5;'
                  'border-left:4px solid #e8a33d;padding:5px 9px;border-radius:4px;margin:0 0 6px">'
                  f"&#9888; {_escape_html(note)}</div>")
    return (
        f"<h2>3D geometry</h2>{banner}"
        f'<script type="module" src="{MV_CDN}"></script>'
        f'<model-viewer src="{src}" alt="Building geometry" '
        "camera-controls "
        'tone-mapping="neutral" shadow-intensity="0.9" shadow-softness="0.8" exposure="1.0" '
        'environment-image="neutral" camera-orbit="-35deg 68deg 70%" bounds="tight" '
        'min-camera-orbit="auto auto auto" max-camera-orbit="auto 95deg auto" '
        'interaction-prompt="none" touch-action="pan-y" '
        f'style="width:100%;height:{int(height)}px;background:'
        'linear-gradient(#f7fafc,#e6edf2);border:1px solid #e3eaef;border-radius:8px">'
        '<div slot="poster" style="display:flex;align-items:center;justify-content:center;'
        'height:100%;color:#62707c">Loading 3D model&#8230;</div>'
        "</model-viewer>"
        '<div style="font-size:12px;color:#8794a1;margin:4px 0 8px">'
        "Drag to orbit &#183; scroll to zoom. "
        "(3D viewer script loads from Google CDN; needs internet.)</div>")


def geometry_viewer(model_or_path, height=480, work_dir=None, audit=None):
    """Model or .osm path -> self-contained viewer fragment ('' if
    unrenderable)."""
    work = os.path.abspath(os.path.expanduser(work_dir)) if work_dir else tempfile.gettempdir()
    os.makedirs(work, exist_ok=True)

    osm_path = model_or_path
    temp_osm = None
    gltf_path = None
    try:
        if not isinstance(model_or_path, str):
            temp_osm = os.path.join(work, f"render_{os.getpid()}_{id(model_or_path)}.osm")
            model_or_path.save(openstudio.path(temp_osm), True)
            osm_path = temp_osm

        base = os.path.basename(osm_path)
        if base.endswith(".osm"):
            base = base[:-len(".osm")]
        gltf_path = os.path.join(work, f"{base}.__geom.gltf")
        ok, note = export_repaired(osm_path, gltf_path, audit=audit)
        if not ok:
            if audit is not None:
                audit.warn("render", "glTF export failed after the full fallback ladder — no 3D view produced",
                           target=os.path.basename(osm_path))
            return ""

        with open(gltf_path, encoding="utf-8") as f:
            gltf = boost_materials(json.load(f))
        # Ruby JSON.generate: compact separators, UTF-8 passthrough.
        payload = json.dumps(gltf, separators=(",", ":"), ensure_ascii=False)
        if audit is not None:
            materials = gltf.get("materials")
            audit.decision("render", "3D geometry viewer produced (glTF embedded as data URI)",
                           target=os.path.basename(osm_path),
                           inputs={"gltf_bytes": len(payload.encode("utf-8")),
                                   "materials": None if materials is None else len(materials),
                                   "approximate": note != ""},
                           value="full geometry (windows/doors included)" if note == "" else note)
        data_uri = "data:model/gltf+json;base64," + base64.b64encode(
            payload.encode("utf-8")).decode("ascii")
        return viewer_html(data_uri, height=height, note=note)
    finally:
        for path in (temp_osm, gltf_path):
            if path and os.path.exists(path):
                os.remove(path)
