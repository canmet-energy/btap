"""Isolated glTF export worker — ALWAYS invoked as a child process
(python render_worker.py <model.osm> <out.gltf> [control.json]) because the
C++ GltfForwardTranslator can HARD-CRASH (segfault) on un-triangulatable
surfaces; an in-process try/except cannot catch that. Direct port of the
campus repo's geometry_view.py worker (canmet-energy/campus,
src/buildings/reports/geometry_view.py), via the Ruby gem's
render_worker.rb (D-79).

control.json: {"remove_subsurfaces": bool,
               "keep_surfaces": [handle,...] | null,
               "drop_surfaces": [handle,...]}
Exit codes: 0 ok, 1 translator returned false, 2 model unloadable,
            3 nothing left to render.
"""

import json
import sys

import openstudio


def main(argv):
    osm_path = argv[0]
    out_path = argv[1]
    ctrl_path = argv[2] if len(argv) > 2 else None
    if ctrl_path:
        with open(ctrl_path, encoding="utf-8") as f:
            control = json.load(f)
    else:
        control = {}

    loaded = openstudio.model.Model.load(openstudio.path(osm_path))
    if not loaded.is_initialized():
        sys.exit(2)
    model = loaded.get()

    if control.get("remove_subsurfaces"):
        for sub_surface in model.getSubSurfaces():
            sub_surface.remove()

    keep = control.get("keep_surfaces")
    drop = control.get("drop_surfaces") or []
    if keep is not None:
        keep_set = {str(h) for h in keep}
        for surface in model.getSurfaces():
            if str(surface.handle()) not in keep_set:
                surface.remove()
    elif drop:
        drop_set = {str(h) for h in drop}
        for surface in model.getSurfaces():
            if str(surface.handle()) in drop_set:
                surface.remove()

    if len(model.getSurfaces()) == 0 and len(model.getShadingSurfaces()) == 0:
        sys.exit(3)

    ok = openstudio.gltf.GltfForwardTranslator().modelToGLTF(
        model, openstudio.path(out_path))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main(sys.argv[1:])
