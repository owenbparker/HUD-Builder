"""A HUD as one file to share: .scchud, a zip of its hud.json and its assets.

The values the control panel set aren't shared: the HUD opens with its
variables' starting values.
"""

import io
import json
import os
import zipfile

from .store import ASSET_TYPES, GAMES, MAX_ASSET, clean_name, clean_var

FORMAT = "scc-hud-builder"
MAX_FILE = 500 << 20


def export(store, hud_id):
    hud = store.get(hud_id)
    design = {"format": FORMAT, "version": 1, "name": hud["name"], "game": hud.get("game", "other"),
              "layers": hud["layers"], "vars": hud["vars"]}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("hud.json", json.dumps(design, indent=1))
        for rel in store.assets(hud_id):
            path = store.asset_file(hud_id, rel[len("assets/"):])
            if path:
                z.write(path, rel)
    return buf.getvalue()


def import_(store, blob):
    """A .scchud file as a new HUD (its own copy, beside any it came from)."""
    if len(blob) > MAX_FILE:
        raise ValueError("That file is too big")
    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        raise ValueError("That isn't a HUD Builder file (.scchud)")
    if "hud.json" not in z.namelist():
        raise ValueError("That isn't a HUD Builder file (no hud.json inside)")
    try:
        design = json.loads(z.read("hud.json"))
    except ValueError:
        raise ValueError("That HUD Builder file is damaged (its hud.json can't be read)")
    if not isinstance(design, dict) or not isinstance(design.get("layers", []), list):
        raise ValueError("That HUD Builder file is damaged")
    hud = store.create(clean_name(design.get("name"), "Imported HUD"),
                       design.get("game") if design.get("game") in GAMES else "other",
                       {"layers": design.get("layers") or [], "vars": [v for v in design.get("vars") or [] if isinstance(v, dict) and v.get("name")]})
    for info in z.infolist():
        name = info.filename.replace("\\", "/")
        if not name.startswith("assets/") or info.is_dir() or "/" in name[len("assets/"):]:
            continue
        if os.path.splitext(name)[1].lower() not in ASSET_TYPES or info.file_size > MAX_ASSET:
            continue
        folder = store.path(hud["id"], "assets")
        os.makedirs(folder, exist_ok=True)
        base = os.path.basename(name)
        with open(os.path.join(folder, base), "wb") as f:
            f.write(z.read(info))
    return store.get(hud["id"])


__all__ = ["export", "import_", "clean_var"]
