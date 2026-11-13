"""Designs from elsewhere into a HUD: a GFX Engine graphic (.sccgfx, or an
"Export HTML" zip) or a Photoshop file (.psd / .psb).

import_design() puts the files into the HUD's assets (in a folder named
after the design) and returns the layers (and variables) for the editor to
add, so the import is one step it can undo:

    {"name", "layers": [...], "vars": [...], "fonts_missing": [...],
     "linked": n, "notes": [...]}

A GFX Engine graphic keeps its layers as they are (the same player draws
them). Its fields (what Control fills in) become the HUD's variables, so the
control panel runs them. Its links to Global and the game HUDs stay; they
follow live once HUD Builder connects to the GFX Engine.

A Photoshop file becomes one layer per Photoshop layer: text stays text
(font, size, colour, spacing, alignment), everything else a PNG of its
pixels (with its layer effects) in its place. Groups are flattened, keeping
their visibility and opacity, and the whole file comes in as one group.
"""

import copy
import io
import json
import os
import re
import tempfile
import zipfile

from . import fontnames
from .log import log
from .store import ASSET_TYPES, FONT_TYPES, MAX_ASSET, new_id

W, H = 1920, 1080
BUILTIN_FONTS = {"inter", "montserrat", "barlow condensed", "bebas neue", "anton", "permanent marker", "vazirmatn"}
ANIM_NONE = {"type": "none", "dur": 400, "delay": 0}
DESIGN_TYPES = (".sccgfx", ".psd", ".psb", ".fig", ".zip")

GENERIC = re.compile(r"^(layer|rectangle|ellipse|line|shape|group|polygon|path|vector|background|bg|color fill|"
                     r"gradient fill|pattern fill|brightness|levels|curves|hue|vibrance|exposure|copy)\b", re.I)
BLENDS = {"multiply": "multiply", "screen": "screen", "overlay": "overlay", "darken": "darken",
          "lighten": "lighten", "color_dodge": "color-dodge", "color_burn": "color-burn",
          "hard_light": "hard-light", "soft_light": "soft-light", "difference": "difference",
          "exclusion": "exclusion", "hue": "hue", "saturation": "saturation", "color": "color",
          "luminosity": "luminosity", "linear_dodge": "plus-lighter"}


def is_design(filename):
    return os.path.splitext(filename or "")[1].lower() in DESIGN_TYPES


def import_design(store, hud_id, filename, blob):
    ext = os.path.splitext(filename or "")[1].lower()
    name = os.path.splitext(os.path.basename(filename or "Design"))[0] or "Design"
    if ext in (".psd", ".psb"):
        return _import_psd(store, hud_id, name, blob)
    if ext == ".fig":
        return _import_figma(store, hud_id, name, blob)
    if ext in (".sccgfx", ".zip"):
        return _import_gfx(store, hud_id, name, blob)
    raise ValueError("Import takes a GFX Engine graphic (.sccgfx), a Photoshop file (.psd) or a Figma file (.fig)")


# --- helpers -------------------------------------------------------------------------
def _font_stems(store, hud_id):
    """{lower-case name the font is known by: the name HUD Builder uses (its file's name)}."""
    out = {}
    for rel in store.assets(hud_id):
        if os.path.splitext(rel)[1].lower() not in FONT_TYPES:
            continue
        stem = os.path.splitext(os.path.basename(rel))[0]
        out[stem.lower()] = stem
        path = store.asset_file(hud_id, rel[len("assets/"):])
        try:
            with open(path, "rb") as f:
                for v in fontnames.names(f.read()).values():
                    out.setdefault(v.lower(), stem)
        except OSError:
            pass
    return out


WEIGHTS = [("thin", 100), ("extralight", 200), ("ultralight", 200), ("light", 300), ("regular", 400), ("book", 400),
           ("medium", 500), ("semibold", 600), ("demibold", 600), ("extrabold", 800), ("ultrabold", 800), ("bold", 700),
           ("black", 900), ("heavy", 900)]


def _builtin(name):
    """("Montserrat", 900) for "Montserrat-Black", a font that comes with HUD Builder; else None."""
    low = re.sub(r"[\s_]+", "", name.lower())
    for fam in BUILTIN_FONTS:
        key = fam.replace(" ", "")
        if low == key or low.startswith(key + "-") or low.startswith(key) and low[len(key):] in {w for w, _ in WEIGHTS}:
            rest = low[len(key):].lstrip("-")
            weight = next((w for k, w in WEIGHTS if rest.startswith(k)), None)
            return " ".join(p.capitalize() for p in fam.split()), weight
    return None


def _missing_fonts(layers, known):
    missing = set()
    for layer in layers:
        f = str(layer.get("font") or "")
        if layer.get("type") == "text" and f and f.lower() not in known and f.lower() not in BUILTIN_FONTS:
            missing.add(f)
    return sorted(missing)


def _match_fonts(layers, known):
    for layer in layers:
        f = str(layer.get("font") or "")
        if layer.get("type") != "text" or not f:
            continue
        if f.lower() in known:
            layer["font"] = known[f.lower()]
        elif f.lower() not in BUILTIN_FONTS and _builtin(f):
            fam, weight = _builtin(f)
            layer["font"] = fam
            if weight:
                layer["weight"] = weight


def _scale(layers, k):
    """A design made at another size, to 1920x1080."""
    if abs(k - 1) < 0.001:
        return
    for layer in layers:
        for key in ("x", "y", "w", "h"):
            if isinstance(layer.get(key), (int, float)):
                layer[key] = round(layer[key] * k)
        for key in ("size", "radius", "strokeWidth", "skew"):
            if isinstance(layer.get(key), (int, float)):
                layer[key] = round(layer[key] * k, 2)
        if isinstance(layer.get("radii"), list):
            layer["radii"] = [round((r or 0) * k, 2) for r in layer["radii"]]
        if isinstance(layer.get("glow"), dict):
            layer["glow"] = dict(layer["glow"], **{key: round((layer["glow"].get(key) or 0) * k, 2) for key in ("blur", "x", "y")})


def _group(layers, name):
    if len(layers) > 1:
        g = new_id("g")
        for layer in layers:
            layer["group"] = g
            layer["groupName"] = name
    return layers


def _replace(value, mapping):
    if isinstance(value, dict):
        return {k: _replace(v, mapping) for k, v in value.items()}
    if isinstance(value, list):
        return [_replace(v, mapping) for v in value]
    if isinstance(value, str):
        return mapping.get(value, value)
    return value


# --- GFX Engine graphics ------------------------------------------------------------------
def _read_gfx(z):
    """(manifest, the folder in the zip its files are in)."""
    names = set(z.namelist())
    if "hud.json" in names:
        raise ValueError("That's a whole HUD (.scchud): open it with Import on My HUDs")
    if "scc-gfx.json" in names:
        data = json.loads(z.read("scc-gfx.json").decode("utf-8"))
        if data.get("format") != "scc-gfx":
            raise ValueError("That isn't a GFX Engine graphics file")
        return data, "files/"
    if "gfx-data.js" in names:
        text = z.read("gfx-data.js").decode("utf-8")
        m = re.search(r"window\.GFX_EXPORT\s*=\s*(\{.*\})\s*;?\s*$", text, re.S)
        if m:
            return json.loads(m.group(1)), ""
    raise ValueError("That zip isn't a GFX Engine graphic (.sccgfx, or an Export HTML zip)")


def _import_gfx(store, hud_id, name, blob):
    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        raise ValueError("That isn't a GFX Engine graphics file (.sccgfx)")
    data, root = _read_gfx(z)
    comps = [c for c in data.get("compositions") or [] if isinstance(c, dict) and isinstance(c.get("layers"), list)]
    if not comps:
        raise ValueError("That file has no graphics in it")
    title = (comps[0].get("name") if len(comps) == 1 else data.get("name")) or name
    sub = store.unique_folder(hud_id, title)
    mapping = {}
    for info in z.infolist():
        member = info.filename
        if info.is_dir() or not member.startswith(root) or info.file_size > MAX_ASSET:
            continue
        rel = member[len(root):]
        ext = os.path.splitext(rel)[1].lower()
        if ext not in ASSET_TYPES:
            continue
        if ext in FONT_TYPES:
            # Fonts sit with the HUD's other fonts, named as the design knows them.
            mapping[rel] = store.add_asset(hud_id, os.path.basename(rel), z.read(info))
        elif rel.startswith("assets/"):
            inner = os.path.dirname(rel[len("assets/"):])
            mapping[rel] = store.add_asset(hud_id, os.path.basename(rel), z.read(info), sub + ("/" + inner if inner else ""))
    known = _font_stems(store, hud_id)
    layers, variables, seen, linked = [], [], {}, 0
    for comp in comps:
        made = []
        width = comp.get("width") or W
        for layer in comp["layers"]:
            if not isinstance(layer, dict):
                continue
            layer = _replace(copy.deepcopy(layer), mapping)
            layer["id"] = new_id("l")
            layer.pop("group", None)
            # A field (what Control fills in) becomes one of the HUD's variables.
            field = str(layer.get("field") or "").strip()
            key = {"text": "text", "rect": "fill"}.get(layer.get("type"), "src")
            # (one that already follows Global or a game HUD keeps that link)
            if field and not re.search(r"\{\{[^{}]+\}\}", str(layer.get(key) or "")):
                vname = re.sub(r"[{}!|]", "", field)[:60]
                if vname.lower() not in seen:
                    kind = {"text": "text", "rect": "color"}.get(layer.get("type"), "image" if layer.get("type") in ("image", "video") else "text")
                    seen[vname.lower()] = vname
                    variables.append({"name": vname, "kind": kind, "value": str(layer.get(key) or ""), "group": comp.get("name") or title})
                layer[key] = "{{HUD!" + seen[vname.lower()] + "}}"
            layer["field"] = ""
            if re.search(r"\{\{\s*(?!HUD!)[^{}]+![^{}]+\}\}|\{\{\s*sponsors", json.dumps(layer), re.I):
                linked += 1
            made.append(layer)
        _scale(made, W / width if width else 1)
        layers += _group(made, comp.get("name") or title)
    _match_fonts(layers, known)
    notes = []
    if linked:
        notes.append(f"{linked} layer{'s' if linked != 1 else ''} read Global or a game HUD: they fill in once HUD Builder connects to the GFX Engine")
    log(f"Imported {title} (GFX Engine graphic): {len(layers)} layers, {len(variables)} variables")
    return {"name": title, "layers": layers, "vars": variables, "fonts_missing": _missing_fonts(layers, known),
            "linked": linked, "notes": notes}


# --- Photoshop --------------------------------------------------------------------------------
def _hex(values):
    if not values:
        return "#ffffff"
    rgb = values[1:4] if len(values) == 4 else values[:3]
    return "#" + "".join(f"{max(0, min(255, round(v * 255))):02x}" for v in rgb)


def _text_layer(layer):
    engine = layer.engine_dict
    resources = layer.resource_dict
    run = engine["StyleRun"]["RunArray"][0]["StyleSheet"]["StyleSheetData"]
    para = engine["ParagraphRun"]["RunArray"][0]["ParagraphSheet"]["Properties"]
    font_set = resources.get("FontSet", [])
    font = "Inter"
    if "Font" in run and run["Font"] < len(font_set):
        raw = font_set[run["Font"]]["Name"]
        font = str(getattr(raw, "value", raw)).strip("\x00'\" ")
    xx, xy, yx, yy, tx, ty = layer.transform
    scale = (xx * xx + xy * xy) ** 0.5 or 1
    size = float(run.get("FontSize", 24)) * scale
    leading = float(run.get("Leading", 0)) * scale if not run.get("AutoLeading", True) else 0
    line_height = round(leading / size, 3) if leading and size else 1.2
    text = layer.text.replace("\r", "\n").rstrip("\n")
    align = {0: "left", 1: "right", 2: "center"}.get(int(para.get("Justification", 0)), "left")
    left, top, right, bottom = layer.bbox
    lines = max(1, text.count("\n") + 1)
    # Point text sits on its baseline at (tx, ty); the box starts one ascent above the first baseline.
    box_h = size * line_height * lines
    width = max(right - left, 10)
    w = width * 1.3 + size
    x = min(left, tx) if align == "left" else max(right, tx) - w if align == "right" else (left + right) / 2 - w / 2
    return {
        "id": new_id("l"), "name": layer.name, "type": "text",
        "x": round(x), "y": round(ty - size * 0.86), "w": round(w), "h": round(box_h + size * 0.2),
        "opacity": 1, "rotation": 0, "visible": True, "blend": "normal", "field": "",
        "anim": {"in": dict(ANIM_NONE), "out": dict(ANIM_NONE)},
        "text": text, "font": font, "size": round(size, 2), "color": _hex(run.get("FillColor", {}).get("Values")),
        "align": align, "valign": "top", "tracking": float(run.get("Tracking", 0)),
        "caps": int(run.get("FontCaps", 0)) == 2, "lineHeight": line_height, "fit": "shrink",
        "weight": 400, "italic": False, "scroll": 0,
    }


def _leaves(group, opacity=1.0, visible=True):
    for layer in group:
        op = opacity * (layer.opacity / 255)
        vis = visible and layer.visible
        if layer.is_group():
            yield from _leaves(layer, op, vis)
        else:
            yield layer, op, vis


def _import_psd(store, hud_id, name, blob):
    try:
        from psd_tools import PSDImage
    except ImportError:
        raise ValueError("Photoshop import isn't in this copy of HUD Builder (psd-tools is missing)")
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "design.psd")
        with open(path, "wb") as f:
            f.write(blob)
        try:
            psd = PSDImage.open(path)
        except Exception as e:
            raise ValueError(f"That Photoshop file can't be read ({e})")
        width, height = psd.size
        sub = store.unique_folder(hud_id, name)
        layers, used, skipped = [], set(), 0

        def save_png(image, base):
            stem, n = re.sub(r"[^\w\- ]+", "_", base).strip() or "layer", 2
            fname = stem
            while fname.lower() in used:
                fname, n = f"{stem}-{n}", n + 1
            used.add(fname.lower())
            buf = io.BytesIO()
            image.save(buf, "PNG", optimize=True)
            return store.add_asset(hud_id, fname + ".png", buf.getvalue(), sub)

        for layer, opacity, visible in _leaves(psd):
            kind = layer.kind
            if kind in ("adjustment", "brightnesscontrast", "curves", "levels", "huesaturation"):
                continue
            if getattr(layer, "clipping", False):
                continue   # (composited into the layer it clips to)
            try:
                if kind == "type":
                    item = _text_layer(layer)
                    item["opacity"] = round(opacity, 3)
                    item["visible"] = visible
                    layers.append(item)
                    continue
                left, top, right, bottom = layer.bbox
                if right - left <= 0 or bottom - top <= 0:
                    continue
                try:
                    image = layer.composite()   # with its layer effects and clipped layers
                except Exception:
                    image = None
                if image is None:
                    image = layer.topil()
                if image is None:
                    continue
                layers.append({
                    "id": new_id("l"), "name": layer.name, "type": "image",
                    "x": left, "y": top, "w": image.size[0], "h": image.size[1],
                    "opacity": round(opacity, 3), "rotation": 0, "visible": visible,
                    "blend": BLENDS.get(str(getattr(layer.blend_mode, "name", layer.blend_mode)).lower(), "normal"),
                    "field": "", "anim": {"in": dict(ANIM_NONE), "out": dict(ANIM_NONE)},
                    "src": save_png(image, layer.name), "fit": "fill", "loop": True,
                })
            except Exception as e:
                skipped += 1
                log(f"{name}: skipped layer {layer.name!r} ({e})", "warn")
        if not layers:
            # A flat file (no layers): the whole picture as one.
            image = psd.composite()
            if image is None:
                raise ValueError("That Photoshop file has nothing to import")
            layers.append({"id": new_id("l"), "name": name, "type": "image", "x": 0, "y": 0, "w": width, "h": height,
                           "opacity": 1, "rotation": 0, "visible": True, "blend": "normal", "field": "",
                           "anim": {"in": dict(ANIM_NONE), "out": dict(ANIM_NONE)}, "src": save_png(image, "Image"), "fit": "fill", "loop": True})
    _scale(layers, W / width if width else 1)
    known = _font_stems(store, hud_id)
    _match_fonts(layers, known)
    notes = []
    if width and abs(width - W) > 1:
        notes.append(f"It was {width} × {height}: scaled to 1920 × 1080")
    if skipped:
        notes.append(f"{skipped} layer{'s' if skipped != 1 else ''} couldn't be read and were left out")
    log(f"Imported {name} (Photoshop): {len(layers)} layers")
    return {"name": name, "layers": _group(layers, name), "vars": [], "fonts_missing": _missing_fonts(layers, known),
            "linked": 0, "notes": notes}


# --- Figma ----------------------------------------------------------------------------------------
def _import_figma(store, hud_id, name, blob):
    from . import figimport
    comps, notes = figimport.import_fig(store, hud_id, name, blob)
    layers = []
    for i, (title, width, made) in enumerate(comps):
        for layer in made:
            for key in ("x", "y", "w", "h"):
                layer[key] = round(layer[key])
        _scale(made, W / width if width else 1)
        if i:
            for layer in made:
                layer["visible"] = False
        layers += _group(made, title)
    if not layers:
        raise ValueError("That Figma file has nothing to import")
    widths = {round(w) for _, w, _ in comps}
    if any(abs(w - W) > 1 for w in widths):
        notes.insert(0, "Scaled to 1920 wide")
    if len(comps) > 1:
        notes.insert(0, f"{len(comps)} frames, one group each: the first is shown, the others are hidden")
    known = _font_stems(store, hud_id)
    _match_fonts(layers, known)
    title = name     # (frame names are often "Frame 1": the file's name)
    log(f"Imported {title} (Figma): {len(layers)} layers")
    return {"name": title, "layers": layers, "vars": [], "fonts_missing": _missing_fonts(layers, known),
            "linked": 0, "notes": notes}
