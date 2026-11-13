"""Starting points for a new HUD: a blank canvas, or a scorebug run from the
control panel (for any game)."""

from .store import new_id

NONE = {"type": "none", "dur": 400, "delay": 0}


def layer(kind, name, x, y, w, h, **extra):
    out = {"id": new_id("l"), "name": name, "type": kind, "x": x, "y": y, "w": w, "h": h, "opacity": 1, "rotation": 0,
           "visible": True, "blend": "normal", "field": "", "anim": {"in": dict(NONE), "out": dict(NONE)}}
    if kind == "text":
        out.update({"text": "Text", "font": "Inter", "size": 48, "color": "#ffffff", "align": "left", "valign": "middle",
                    "tracking": 0, "caps": False, "lineHeight": 1.1, "fit": "shrink", "weight": 700, "italic": False, "scroll": 0})
    elif kind == "rect":
        out.update({"fill": "#111318", "radius": 0, "stroke": "#ffffff", "strokeWidth": 0, "shape": "rect"})
    elif kind in ("image", "video", "lottie"):
        out.update({"src": "", "fit": "contain", "loop": True})
    out.update(extra)
    return out


def scorebug():
    g = new_id("g")
    cx, y = 960, 24
    slide = {"in": {"type": "slide-down", "dur": 450, "delay": 0}, "out": {"type": "slide-up", "dur": 350, "delay": 0}}
    layers = [
        layer("rect", "Left bar", cx - 520, y, 420, 64, fill="{{HUD!Left colour}}", fill2="#0b0c10", gradAngle=270,
              shape="angled", skew=24, group=g, anim=slide),
        layer("rect", "Right bar", cx + 100, y, 420, 64, fill="#0b0c10", fill2="{{HUD!Right colour}}", gradAngle=270,
              shape="angled", skew=-24, group=g, anim=slide),
        layer("rect", "Centre", cx - 110, y, 220, 64, fill="#0b0c10", shape="rect", radius=0, group=g, anim=slide,
              glow={"color": "#000000", "blur": 16, "x": 0, "y": 4}),
        layer("text", "Left team", cx - 480, y, 340, 64, text="{{HUD!Left team}}", font="Bebas Neue", weight=400, size=44,
              caps=True, align="left", group=g, anim=slide),
        layer("text", "Right team", cx + 140, y, 340, 64, text="{{HUD!Right team}}", font="Bebas Neue", weight=400, size=44,
              caps=True, align="right", group=g, anim=slide),
        layer("text", "Left score", cx - 110, y, 80, 64, text="{{HUD!Left score}}", font="Bebas Neue", weight=400, size=56,
              align="center", group=g, anim=slide),
        layer("text", "Right score", cx + 30, y, 80, 64, text="{{HUD!Right score}}", font="Bebas Neue", weight=400, size=56,
              align="center", group=g, anim=slide),
        layer("text", "Dash", cx - 30, y, 60, 64, text="-", font="Bebas Neue", weight=400, size=40, align="center",
              color="#8e8e93", group=g, anim=slide),
        layer("rect", "Round box", cx - 90, y + 64, 180, 30, fill="#f5c518", shape="angled", skew=12, group=g, anim=slide),
        layer("text", "Round", cx - 90, y + 64, 180, 30, text="{{HUD!Round label}}", font="Inter", weight=800, size=18,
              caps=True, align="center", color="#111111", group=g, anim=slide),
    ]
    variables = [
        {"name": "Left team", "kind": "text", "value": "Team One", "group": "Left"},
        {"name": "Left colour", "kind": "color", "value": "#1f6feb", "group": "Left"},
        {"name": "Left score", "kind": "number", "value": "0", "step": 1, "min": 0, "group": "Left"},
        {"name": "Right team", "kind": "text", "value": "Team Two", "group": "Right"},
        {"name": "Right colour", "kind": "color", "value": "#e5352b", "group": "Right"},
        {"name": "Right score", "kind": "number", "value": "0", "step": 1, "min": 0, "group": "Right"},
        {"name": "Round label", "kind": "text", "value": "Round 1", "group": "Match"},
    ]
    return {"layers": layers, "vars": variables}


TEMPLATES = {
    "blank": ("Blank canvas", lambda: {"layers": [], "vars": []}),
    "scorebug": ("Scorebug (teams, score, round)", scorebug),
}
