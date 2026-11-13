"""Figma files (.fig, from Figma's File > Save local copy) as HUD layers.

Each frame on the page becomes a group of layers (scaled to 1920 wide); the
first is shown, others start hidden. Rectangles and ellipses stay shapes (with
their colour or gradient, rounded corners, outline and drop shadow), text stays
text, pictures are saved cut to their frame (crop, fit, rounded corners), and
vector shapes (paths, stars, lines, boolean shapes) are saved as SVG pictures.
"""

import io
import math
import re
import zipfile

from . import kiwi
from .store import new_id

ANIM_NONE = {"type": "none", "dur": 400, "delay": 0}
CONTAINERS = {"FRAME", "GROUP", "SECTION", "SYMBOL", "INSTANCE", "COMPONENT", "COMPONENT_SET"}
VECTORS = {"VECTOR", "STAR", "LINE", "REGULAR_POLYGON", "BOOLEAN_OPERATION", "POLYGON"}
SHAPES = {"RECTANGLE", "ROUNDED_RECTANGLE", "ELLIPSE"}
BLENDS = {"MULTIPLY": "multiply", "SCREEN": "screen", "OVERLAY": "overlay", "DARKEN": "darken", "LIGHTEN": "lighten",
          "COLOR_DODGE": "color-dodge", "COLOR_BURN": "color-burn", "HARD_LIGHT": "hard-light",
          "SOFT_LIGHT": "soft-light", "DIFFERENCE": "difference", "EXCLUSION": "exclusion", "HUE": "hue",
          "SATURATION": "saturation", "COLOR": "color", "LUMINOSITY": "luminosity", "LINEAR_DODGE": "plus-lighter"}
WEIGHTS = [("thin", 100), ("hairline", 100), ("extralight", 200), ("ultralight", 200), ("light", 300),
           ("medium", 500), ("semibold", 600), ("demibold", 600), ("extrabold", 800), ("ultrabold", 800),
           ("bold", 700), ("black", 900), ("heavy", 900)]


# --- reading the file ---------------------------------------------------------------------------
def read(blob):
    """(message, {image hash hex: bytes})."""
    images = {}
    if blob[:2] == b"PK":
        try:
            z = zipfile.ZipFile(io.BytesIO(blob))
        except zipfile.BadZipFile:
            raise ValueError("That Figma file is damaged")
        names = z.namelist()
        canvas = next((n for n in names if n.lower().endswith(".fig")), None)
        if not canvas:
            raise ValueError("That zip has no Figma design in it (canvas.fig)")
        for n in names:
            if n.startswith("images/") and not n.endswith("/"):
                images[n[len("images/"):].lower()] = z.read(n)
        canvas = z.read(canvas)
    else:
        canvas = blob
    return kiwi.read_fig(canvas), images


def _gid(guid):
    return (guid or {}).get("sessionID"), (guid or {}).get("localID")


def _tree(nodes):
    """{parent id: [children, in drawing order (bottom first)]}."""
    kids = {}
    for n in nodes:
        p = n.get("parentIndex")
        if p:
            kids.setdefault(_gid(p.get("guid")), []).append(n)
    for lst in kids.values():
        lst.sort(key=lambda n: n["parentIndex"].get("position") or "")
    return kids


# --- geometry -----------------------------------------------------------------------------------
IDENTITY = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)


def _matrix(t):
    t = t or {}
    return (t.get("m00", 1.0), t.get("m01", 0.0), t.get("m02", 0.0), t.get("m10", 0.0), t.get("m11", 1.0), t.get("m12", 0.0))


def _mul(a, b):
    return (a[0] * b[0] + a[1] * b[3], a[0] * b[1] + a[1] * b[4], a[0] * b[2] + a[1] * b[5] + a[2],
            a[3] * b[0] + a[4] * b[3], a[3] * b[1] + a[4] * b[4], a[3] * b[2] + a[4] * b[5] + a[5])


def _apply(m, x, y):
    return m[0] * x + m[1] * y + m[2], m[3] * x + m[4] * y + m[5]


def _place(m, w, h):
    """The HUD box (x, y, w, h, rotation) and whether it's mirrored, for a w x h box under m."""
    flip = m[0] * m[4] - m[1] * m[3] < 0
    sx = -1 if flip else 1
    angle = math.degrees(math.atan2(sx * m[3], sx * m[0]))
    cx, cy = _apply(m, w / 2, h / 2)
    return {"x": round(cx - w / 2, 2), "y": round(cy - h / 2, 2), "w": round(w, 2), "h": round(h, 2),
            "rotation": round(angle, 2) if abs(angle) > 0.01 else 0}, flip


# --- paint --------------------------------------------------------------------------------------
def _hex(color, opacity=1.0):
    c = color or {}
    a = max(0.0, min(1.0, c.get("a", 1.0) * opacity))
    rgb = "".join(f"{max(0, min(255, round(c.get(k, 0) * 255))):02x}" for k in "rgb")
    return "#" + rgb + ("" if a >= 0.999 else f"{round(a * 255):02x}")


def _visible(paints):
    return [p for p in paints or [] if p.get("visible", True) and p.get("opacity", 1.0) > 0]


def _gradient(p, w, h):
    """(first colour, last colour, CSS angle) for a gradient paint."""
    stops = sorted(p.get("stops") or [], key=lambda s: s.get("position", 0))
    if not stops:
        return None
    op = p.get("opacity", 1.0)
    first, last = _hex(stops[0].get("color"), op), _hex(stops[-1].get("color"), op)
    # The paint's transform maps the box (0..1) to gradient space, where it runs along x.
    m = _matrix(p.get("transform"))
    det = m[0] * m[4] - m[1] * m[3]
    if abs(det) < 1e-9:
        return first, last, 90
    inv = (m[4] / det, -m[1] / det, (m[1] * m[5] - m[4] * m[2]) / det,
           -m[3] / det, m[0] / det, (m[3] * m[2] - m[0] * m[5]) / det)
    x0, y0 = _apply(inv, 0, 0.5)
    x1, y1 = _apply(inv, 1, 0.5)
    dx, dy = (x1 - x0) * w, (y1 - y0) * h
    return first, last, round(math.degrees(math.atan2(dx, -dy)) % 360, 1)


def _shadow(node):
    for e in node.get("effects") or []:
        if e.get("type") == "DROP_SHADOW" and e.get("visible", True):
            off = e.get("offset") or {}
            return {"color": _hex(e.get("color")), "blur": round(e.get("radius", 0), 2),
                    "x": round(off.get("x", 0), 2), "y": round(off.get("y", 0), 2)}
    return None


def _radii(node):
    if node.get("rectangleCornerRadiiIndependent"):
        r = [node.get(f"rectangle{k}CornerRadius", 0) or 0 for k in ("TopLeft", "TopRight", "BottomRight", "BottomLeft")]
        if len(set(r)) > 1:
            return r
        return r[0]
    return node.get("cornerRadius", 0) or 0


# --- the importer -------------------------------------------------------------------------------
class _Import:
    def __init__(self, store, hud_id, name, blob):
        self.store, self.hud_id, self.name = store, hud_id, name
        self.msg, self.images = read(blob)
        self.blobs = [b.get("bytes", b"") for b in self.msg.get("blobs") or []]
        self.nodes = self.msg.get("nodeChanges") or []
        self.by_id = {_gid(n.get("guid")): n for n in self.nodes}
        self.kids = _tree(self.nodes)
        self.sub = store.unique_folder(hud_id, name)
        self.skipped, self.missing_images, self.masks = 0, 0, 0

    def layer(self, node, place, opacity, kind, **extra):
        out = {"id": new_id("l"), "name": node.get("name") or kind.capitalize(), "type": kind,
               "opacity": round(opacity, 3), "visible": True, "blend": BLENDS.get(node.get("blendMode"), "normal"),
               "field": "", "anim": {"in": dict(ANIM_NONE), "out": dict(ANIM_NONE)}}
        out.update(place)
        out.update(extra)
        return out

    # The layers for one node (and what's in it), m = its parent's matrix in the frame.
    def walk(self, node, m, opacity, out, visible=True):
        if node.get("type") in ("CANVAS", "DOCUMENT") or node.get("internalOnly"):
            return
        vis = visible and node.get("visible", True)
        op = opacity * node.get("opacity", 1.0)
        mm = _mul(m, _matrix(node.get("transform")))
        size = node.get("size") or {}
        w, h = size.get("x", 0), size.get("y", 0)
        start = len(out)
        t = node.get("type")
        try:
            if node.get("mask"):
                self.masks += 1
            elif t == "TEXT":
                self.text(node, mm, w, h, op, out)
            elif t in VECTORS:
                self.vector(node, mm, op, out)
            elif t in SHAPES or t in CONTAINERS:
                self.box(node, mm, w, h, op, out)
        except Exception:
            self.skipped += 1
        if t in CONTAINERS:
            children = self.kids.get(_gid(node.get("guid")), [])
            if not children and t == "INSTANCE":
                # (an instance's layers are its component's)
                sym = self.by_id.get(_gid(((node.get("symbolData") or {}).get("symbolID"))))
                if sym:
                    children = self.kids.get(_gid(sym.get("guid")), [])
            for child in children:
                self.walk(child, mm, op, out, vis)
        if not vis:
            for layer in out[start:]:
                layer["visible"] = False

    def box(self, node, m, w, h, op, out):
        """A rectangle, ellipse or frame: a shape layer per fill, pictures cut to it."""
        if w <= 0 or h <= 0:
            return
        place, flip = _place(m, w, h)
        ellipse = node.get("type") == "ELLIPSE"
        radius = _radii(node)
        fills = _visible(node.get("fillPaints"))
        strokes = _visible(node.get("strokePaints"))
        sw = node.get("strokeWeight", 0) or 0
        glow = _shadow(node)
        made = []
        for p in fills:
            kind = p.get("type", "")
            if kind == "IMAGE":
                src = self.picture(node, p, w, h, flip, ellipse, radius)
                if src:
                    made.append(self.layer(node, place, op, "image", src=src, fit="fill", loop=True))
                continue
            extra = {"shape": "ellipse" if ellipse else "rect", "stroke": "#ffffff", "strokeWidth": 0}
            if isinstance(radius, list):
                extra["radii"] = radius
                extra["radius"] = 0
            else:
                extra["radius"] = radius
            if kind == "SOLID":
                extra["fill"] = _hex(p.get("color"), p.get("opacity", 1.0))
            elif kind.startswith("GRADIENT"):
                g = _gradient(p, w, h)
                if not g:
                    continue
                extra["fill"], extra["fill2"], extra["gradAngle"] = g
            else:
                continue
            made.append(self.layer(node, place, op, "rect", **extra))
        if strokes and sw > 0 and strokes[-1].get("type") == "SOLID":
            colour = _hex(strokes[-1].get("color"), strokes[-1].get("opacity", 1.0))
            if made and made[-1]["type"] == "rect":
                made[-1].update(stroke=colour, strokeWidth=sw)
            else:
                ring = {"shape": "ellipse" if ellipse else "rect", "fill": "transparent", "stroke": colour, "strokeWidth": sw}
                if isinstance(radius, list):
                    ring.update(radii=radius, radius=0)
                else:
                    ring["radius"] = radius
                made.append(self.layer(node, place, op, "rect", name=(node.get("name") or "Shape") + " outline", **ring))
        if glow:
            for layer in made:
                layer["glow"] = glow
        out.extend(made)

    def picture(self, node, paint, w, h, flip, ellipse, radius):
        """An image fill drawn as it shows in Figma, saved as a PNG; its asset path."""
        from PIL import Image, ImageDraw, ImageOps
        ref = (paint.get("image") or {}).get("hash")
        data = self.images.get(ref.hex()) if isinstance(ref, (bytes, bytearray)) else None
        if not data:
            self.missing_images += 1
            return None
        img = Image.open(io.BytesIO(data))
        img.load()
        img = img.convert("RGBA")
        k = max(1.0, min(2.0, img.width / w if w else 1))
        ow, oh = max(1, round(w * k)), max(1, round(h * k))
        mode = paint.get("imageScaleMode", "FILL")
        rot = round((paint.get("rotation") or 0) / 90) % 4
        if rot:
            img = img.rotate(-90 * rot, expand=True)
        canvas = Image.new("RGBA", (ow, oh), (0, 0, 0, 0))
        if mode == "FIT":
            s = min(ow / img.width, oh / img.height)
            fit = img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))), Image.LANCZOS)
            canvas.paste(fit, ((ow - fit.width) // 2, (oh - fit.height) // 2))
        elif mode == "TILE":
            s = (paint.get("scale") or 1) * k
            tile = img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))), Image.LANCZOS)
            for ty in range(0, oh, tile.height):
                for tx in range(0, ow, tile.width):
                    canvas.paste(tile, (tx, ty))
        elif mode == "STRETCH" or mode == "CROP":
            # The paint's transform maps the box (0..1) to the part of the picture it shows.
            t = _matrix(paint.get("transform"))
            x0, y0 = _apply(t, 0, 0)
            x1, y1 = _apply(t, 1, 1)
            box = (min(x0, x1) * img.width, min(y0, y1) * img.height, max(x0, x1) * img.width, max(y0, y1) * img.height)
            canvas = img.resize((ow, oh), Image.LANCZOS, box=box) if box[2] > box[0] and box[3] > box[1] else img.resize((ow, oh), Image.LANCZOS)
        else:   # FILL: cover, centred
            canvas = ImageOps.fit(img, (ow, oh), Image.LANCZOS)
        if flip:
            canvas = ImageOps.mirror(canvas)
        op = paint.get("opacity", 1.0)
        if op < 1:
            alpha = canvas.getchannel("A").point(lambda v: round(v * op))
            canvas.putalpha(alpha)
        r = max(radius) if isinstance(radius, list) else radius
        if ellipse or r:
            mask = Image.new("L", (ow, oh), 0)
            d = ImageDraw.Draw(mask)
            if ellipse:
                d.ellipse((0, 0, ow - 1, oh - 1), fill=255)
            else:
                d.rounded_rectangle((0, 0, ow - 1, oh - 1), radius=r * k, fill=255)
            cut = Image.new("L", (ow, oh), 0)
            cut.paste(canvas.getchannel("A"), mask=mask)
            canvas.putalpha(cut)
        buf = io.BytesIO()
        canvas.save(buf, "PNG", optimize=True)
        stem = re.sub(r"[^\w\- ]+", "_", node.get("name") or "picture").strip() or "picture"
        return self.store.add_asset(self.hud_id, stem + ".png", buf.getvalue(), self.sub)

    def text(self, node, m, w, h, op, out):
        chars = (node.get("textData") or {}).get("characters") or ""
        if not chars.strip():
            return
        font = node.get("fontName") or {}
        style = (font.get("style") or "").lower().replace(" ", "")
        family = font.get("family") or "Inter"
        name = font.get("postscript") or (family + ("-" + font.get("style", "").replace(" ", "") if font.get("style") else ""))
        size = node.get("fontSize") or 24
        fills = [p for p in _visible(node.get("fillPaints")) if p.get("type") == "SOLID"]
        colour = _hex(fills[-1].get("color"), fills[-1].get("opacity", 1.0)) if fills else "#ffffff"
        ls = node.get("letterSpacing") or {}
        tracking = ls.get("value", 0) * 10 if ls.get("units") == "PERCENT" else (ls.get("value", 0) / size * 1000 if size else 0)
        lh = node.get("lineHeight") or {}
        if lh.get("units") == "PERCENT":
            line_height = lh.get("value", 100) / 100
        elif lh.get("units") == "PIXELS" and size:
            line_height = lh.get("value", size) / size
        elif lh.get("units") == "RAW":
            line_height = lh.get("value", 1.2)
        else:
            line_height = 1.2
        place, _ = _place(m, w, h)
        layer = self.layer(node, place, op, "text",
                           text=chars.rstrip("\n"), font=name, size=round(size, 2), color=colour,
                           align={"CENTER": "center", "RIGHT": "right", "JUSTIFIED": "left"}.get(node.get("textAlignHorizontal"), "left"),
                           valign={"CENTER": "middle", "BOTTOM": "bottom"}.get(node.get("textAlignVertical"), "top"),
                           tracking=round(tracking, 1), caps=node.get("textCase") == "UPPER", lineHeight=round(line_height or 1.2, 3),
                           fit="shrink", weight=next((v for k, v in WEIGHTS if k in style), 400), italic="italic" in style or "oblique" in style,
                           scroll=0)
        glow = _shadow(node)
        if glow:
            layer["glow"] = glow
        out.append(layer)

    def vector(self, node, m, op, out):
        """A path shape, as an SVG picture of its fill and outline."""
        fills = _visible(node.get("fillPaints"))
        strokes = _visible(node.get("strokePaints"))
        parts, xs, ys = [], [], []

        def colour(paints):
            for p in reversed(paints):
                if p.get("type") == "SOLID":
                    return _hex(p.get("color"), p.get("opacity", 1.0))
                if p.get("type", "").startswith("GRADIENT") and p.get("stops"):
                    return _hex(p["stops"][0].get("color"), p.get("opacity", 1.0))
            return None

        for geom, paint in ((node.get("fillGeometry"), colour(fills)), (node.get("strokeGeometry"), colour(strokes))):
            if not paint:
                continue
            for g in geom or []:
                i = g.get("commandsBlob")
                if not isinstance(i, int) or i >= len(self.blobs):
                    continue
                d = _path(self.blobs[i], xs, ys)
                if d:
                    rule = "evenodd" if g.get("windingRule") in ("ODD", "EVENODD") else "nonzero"
                    parts.append(f'<path d="{d}" fill="{paint}" fill-rule="{rule}"/>')
        if not parts:
            if node.get("type") != "BOOLEAN_OPERATION":
                self.skipped += 1
            return
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        bw, bh = max(x1 - x0, 1), max(y1 - y0, 1)
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{bw:g}" height="{bh:g}" viewBox="{x0:g} {y0:g} {bw:g} {bh:g}">'
               + "".join(parts) + "</svg>")
        stem = re.sub(r"[^\w\- ]+", "_", node.get("name") or "shape").strip() or "shape"
        src = self.store.add_asset(self.hud_id, stem + ".svg", svg.encode("utf-8"), self.sub)
        place, flip = _place(_mul(m, (1, 0, x0, 0, 1, y0)), bw, bh)
        layer = self.layer(node, place, op, "image", src=src, fit="fill", loop=True)
        glow = _shadow(node)
        if glow:
            layer["glow"] = glow
        out.append(layer)

    def run(self):
        """[(frame name, its width, its layers)], loose layers last."""
        pages = [n for n in self.nodes if n.get("type") == "CANVAS" and not n.get("internalOnly")]
        frames, loose = [], []
        for page in pages:
            for top in self.kids.get(_gid(page.get("guid")), []):
                if top.get("type") in ("FRAME", "SYMBOL", "COMPONENT") and (top.get("size") or {}).get("x"):
                    frames.append(top)
                elif top.get("type") == "SECTION":
                    frames += [c for c in self.kids.get(_gid(top.get("guid")), []) if c.get("type") in ("FRAME", "SYMBOL", "COMPONENT")]
                else:
                    loose.append(top)
        comps = []
        for f in frames:
            layers = []
            # (the frame at 0,0: its own fill, then what's in it)
            local = dict(f)
            local["transform"] = None
            self.walk(local, IDENTITY, 1.0, layers)
            comps.append((f.get("name") or self.name, (f.get("size") or {}).get("x") or 1920, layers))
        if loose:
            layers = []
            for n in loose:
                self.walk(n, IDENTITY, 1.0, layers)
            if layers:
                left = min(l["x"] for l in layers)
                top = min(l["y"] for l in layers)
                for l in layers:
                    l["x"] -= left
                    l["y"] -= top
                width = max(l["x"] + l["w"] for l in layers) or 1920
                comps.append((self.name, max(width, 1920), layers))
        return comps


def _path(blob, xs, ys):
    """Figma's path commands (0 close, 1 move, 2 line, 3 quad, 4 cubic; float32 points) as SVG path data."""
    import struct
    out, o, n = [], 0, len(blob)
    counts = {1: 1, 2: 1, 3: 2, 4: 3}
    letters = {0: "Z", 1: "M", 2: "L", 3: "Q", 4: "C"}
    while o < n:
        cmd = blob[o]
        o += 1
        if cmd == 0:
            out.append("Z")
            continue
        if cmd not in counts or o + 8 * counts[cmd] > n:
            break
        pts = struct.unpack_from("<" + "f" * (2 * counts[cmd]), blob, o)
        o += 8 * counts[cmd]
        xs.extend(pts[0::2])
        ys.extend(pts[1::2])
        out.append(letters[cmd] + " ".join(f"{v:.2f}".rstrip("0").rstrip(".") for v in pts))
    return " ".join(out)


def import_fig(store, hud_id, name, blob):
    """(comps [(name, width, layers)], notes)."""
    job = _Import(store, hud_id, name, blob)
    comps = job.run()
    notes = []
    if job.missing_images:
        notes.append(f"{job.missing_images} picture{'s' if job.missing_images != 1 else ''} weren't in the file")
    if job.masks:
        notes.append(f"{job.masks} mask{'s' if job.masks != 1 else ''} left out (export masked parts as pictures)")
    if job.skipped:
        notes.append(f"{job.skipped} layer{'s' if job.skipped != 1 else ''} couldn't be read and were left out")
    return comps, notes
