"""The HUDs: one folder each in huds/, with its design and its pictures.

    huds/<id>/hud.json    {"id", "name", "game", "rev", "updated",
                           "layers": [...],   GFX Engine Composer layers (see the
                                              engine's project.py), plus "group"
                                              (layers that move together) and
                                              "reference" (shown while editing,
                                              never on air)
                           "vars": [{"name", "kind", "value", ...}],
                                              the HUD's own variables, set from
                                              its control panel ({{HUD!name}})
                           "values": {name: value},   what they're set to now
                           "shown": true}             on air (false: played out)
    huds/<id>/assets/     its pictures, videos and fonts

A design saved from the editor never overwrites the values: the control
panel may have changed them while the editor had the HUD open.
"""

import copy
import json
import os
import re
import shutil
import threading
import time
import uuid

from . import fontnames

GAMES = {
    "other": "Other game",
    "lol": "League of Legends",
    "valorant": "VALORANT",
    "cod": "Call of Duty",
    "rl": "Rocket League",
    "smash": "Super Smash Bros. Ultimate",
    "overwatch": "Overwatch 2",
}
KINDS = ("text", "number", "toggle", "color", "image", "choice")
FONT_TYPES = {".ttf", ".otf", ".woff", ".woff2"}
ASSET_TYPES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".webm", ".mp4", ".json", ".ttf", ".otf", ".woff", ".woff2"}
MAX_ASSET = 200 << 20

_id_re = re.compile(r"^[a-z0-9]{6,40}$")


def new_id(prefix=""):
    return prefix + uuid.uuid4().hex[:10]


def clean_name(name, fallback="New HUD"):
    name = re.sub(r"\s+", " ", str(name or "")).strip()[:80]
    return name or fallback


def clean_var(v):
    kind = v.get("kind") if v.get("kind") in KINDS else "text"
    name = re.sub(r"[{}!|]", "", str(v.get("name") or "")).strip()[:60]
    if not name:
        raise ValueError("A variable needs a name")
    out = {"name": name, "kind": kind, "value": str(v.get("value") if v.get("value") is not None else "")}
    if kind == "number":
        out["step"] = v.get("step") or 1
        for k in ("min", "max"):
            if v.get(k) not in (None, ""):
                out[k] = v[k]
    if kind == "choice":
        out["options"] = [str(o) for o in (v.get("options") or []) if str(o).strip()][:50]
    if v.get("group"):
        out["group"] = str(v["group"])[:40]
    return out


def tables(hud):
    """The data the HUD's layers read: {"HUD": rows} for {{HUD!name}}."""
    values = hud.get("values") or {}
    rows = [["Variable", "Value"]]
    for v in hud.get("vars") or []:
        val = values.get(v["name"], v.get("value", ""))
        if v.get("kind") == "toggle":
            val = "1" if str(val).lower() in ("1", "true", "yes", "on") else ""
        rows.append([v["name"], str(val)])
    return {"HUD": rows}


def summary(hud):
    return {"id": hud["id"], "name": hud["name"], "game": hud.get("game", "other"), "rev": hud.get("rev", 0),
            "updated": hud.get("updated", 0), "layers": len(hud.get("layers") or []), "vars": len(hud.get("vars") or [])}


class Store:
    def __init__(self, folder):
        self.folder = folder
        os.makedirs(folder, exist_ok=True)
        self._lock = threading.RLock()
        self._cache = {}
        self.version = 0          # goes up on every change (the live pages follow it)
        self._cond = threading.Condition()

    # --- reading ---------------------------------------------------------------
    def path(self, hud_id, *rest):
        if not _id_re.match(hud_id or ""):
            raise KeyError("no such HUD")
        return os.path.join(self.folder, hud_id, *rest)

    def list(self):
        out = []
        for name in sorted(os.listdir(self.folder)):
            try:
                out.append(summary(self.get(name)))
            except (KeyError, OSError, ValueError):
                continue
        out.sort(key=lambda h: -h["updated"])
        return out

    def get(self, hud_id):
        with self._lock:
            if hud_id in self._cache:
                return copy.deepcopy(self._cache[hud_id])
            p = self.path(hud_id, "hud.json")
            if not os.path.isfile(p):
                raise KeyError("no such HUD")
            with open(p, encoding="utf-8") as f:
                hud = json.load(f)
            hud["id"] = hud_id
            hud.setdefault("layers", [])
            hud.setdefault("vars", [])
            hud.setdefault("values", {})
            hud.setdefault("shown", True)
            self._cache[hud_id] = hud
            return copy.deepcopy(hud)

    # --- writing ---------------------------------------------------------------
    def _write(self, hud):
        hud["updated"] = time.time()
        hud["rev"] = int(hud.get("rev") or 0) + 1
        folder = self.path(hud["id"])
        os.makedirs(os.path.join(folder, "assets"), exist_ok=True)
        tmp = os.path.join(folder, "hud.json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(hud, f, indent=1)
        os.replace(tmp, os.path.join(folder, "hud.json"))
        self._cache[hud["id"]] = copy.deepcopy(hud)
        self.changed()
        return copy.deepcopy(hud)

    def changed(self):
        with self._cond:
            self.version += 1
            self._cond.notify_all()

    def wait(self, version, timeout):
        with self._cond:
            if self.version == version:
                self._cond.wait(timeout)
            return self.version

    def create(self, name="", game="other", template=None):
        game = game if game in GAMES else "other"
        hud = {"id": new_id("h"), "name": clean_name(name), "game": game, "rev": 0, "layers": [], "vars": [], "values": {}}
        if template:
            hud["layers"] = copy.deepcopy(template.get("layers") or [])
            hud["vars"] = [clean_var(v) for v in template.get("vars") or []]
        with self._lock:
            return self._write(hud)

    def save_design(self, hud_id, body):
        """The editor's save: the name, game, layers and variables (not the values)."""
        with self._lock:
            hud = self.get(hud_id)
            if "name" in body:
                hud["name"] = clean_name(body["name"], hud["name"])
            if body.get("game") in GAMES:
                hud["game"] = body["game"]
            if "layers" in body:
                if not isinstance(body["layers"], list):
                    raise ValueError("layers must be a list")
                hud["layers"] = body["layers"]
            if "vars" in body:
                seen, out = set(), []
                for v in body["vars"] or []:
                    v = clean_var(v)
                    if v["name"].lower() in seen:
                        raise ValueError(f"Two variables are called {v['name']}")
                    seen.add(v["name"].lower())
                    out.append(v)
                # (a renamed or removed variable's value goes with it)
                hud["values"] = {k: val for k, val in hud["values"].items() if k.lower() in seen}
                hud["vars"] = out
            return self._write(hud)

    def set_values(self, hud_id, values):
        """The control panel: {name: value} for the HUD's variables."""
        with self._lock:
            hud = self.get(hud_id)
            names = {v["name"].lower(): v for v in hud["vars"]}
            for k, val in (values or {}).items():
                v = names.get(str(k).lower())
                if not v:
                    raise ValueError(f"This HUD has no variable called {k}")
                hud["values"][v["name"]] = str(val if val is not None else "")
            return self._write(hud)

    def set_shown(self, hud_id, shown):
        """Show the HUD (its In animations) or take it off (its Out animations)."""
        with self._lock:
            hud = self.get(hud_id)
            hud["shown"] = bool(shown)
            return self._write(hud)

    def reset_values(self, hud_id):
        with self._lock:
            hud = self.get(hud_id)
            hud["values"] = {}
            return self._write(hud)

    def delete(self, hud_id):
        with self._lock:
            folder = self.path(hud_id)
            self._cache.pop(hud_id, None)
            if os.path.isdir(folder):
                shutil.rmtree(folder)
            self.changed()

    def duplicate(self, hud_id):
        with self._lock:
            hud = self.get(hud_id)
            new = dict(hud, id=new_id("h"), name=clean_name(hud["name"] + " copy"), rev=0)
            shutil.copytree(self.path(hud_id, "assets"), os.path.join(self.folder, new["id"], "assets"), dirs_exist_ok=True)
            return self._write(new)

    def add_asset(self, hud_id, filename, blob, sub=""):
        """A picture (video, font...) for the HUD: saved in its assets (in a
        folder of them, sub), named after the file (a different file with the
        same name gets a number). A font is named by its PostScript name, the
        name a design (a Photoshop file) knows it by."""
        self.get(hud_id)
        stem, ext = os.path.splitext(os.path.basename(filename or "picture.png"))
        ext = ext.lower()
        if ext not in ASSET_TYPES:
            raise ValueError("Send a picture (PNG, JPG, WebP, GIF, SVG), a video (WebM, MP4), a Lottie .json or a font")
        if len(blob) > MAX_ASSET:
            raise ValueError("That file is too big (200 MB at most)")
        if ext in FONT_TYPES:
            stem = fontnames.names(blob).get("postscript") or stem
        stem = re.sub(r"[^A-Za-z0-9 _.-]+", "", stem).strip() or "file"
        sub = "/".join(p for p in (re.sub(r"[^A-Za-z0-9 _.-]+", "", x).strip(" .") for x in str(sub or "").split("/")) if p)
        folder = self.path(hud_id, "assets", *([sub] if sub else []))
        os.makedirs(folder, exist_ok=True)
        prefix = "assets/" + (sub + "/" if sub else "")
        name, n = stem + ext, 1
        while os.path.exists(os.path.join(folder, name)):
            with open(os.path.join(folder, name), "rb") as f:
                if f.read() == blob:
                    return prefix + name
            n += 1
            name = f"{stem} {n}{ext}"
        with open(os.path.join(folder, name), "wb") as f:
            f.write(blob)
        return prefix + name

    def assets(self, hud_id):
        folder = self.path(hud_id, "assets")
        out = []
        for dirpath, _, names in os.walk(folder):
            for n in names:
                rel = os.path.relpath(os.path.join(dirpath, n), folder).replace(os.sep, "/")
                out.append("assets/" + rel)
        return sorted(out)

    def unique_folder(self, hud_id, name):
        """A new folder name in the HUD's assets for an imported design's files."""
        base = re.sub(r"[^A-Za-z0-9 _.-]+", "", name or "").strip(" .")[:60] or "Import"
        out, n = base, 2
        while os.path.exists(self.path(hud_id, "assets", out)):
            out, n = f"{base} {n}", n + 1
        return out

    def asset_file(self, hud_id, rel):
        """Path on disk of one of the HUD's assets (None if it climbs out or isn't there)."""
        base = os.path.normpath(self.path(hud_id, "assets"))
        path = os.path.normpath(os.path.join(base, rel))
        if not path.startswith(base + os.sep) or not os.path.isfile(path):
            return None
        return path
