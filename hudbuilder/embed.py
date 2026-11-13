"""HUD Builder inside a game HUD app (League, VALORANT, CoD, Rocket League,
Smash, Overwatch): the app's "Custom design" page. Its designs read the app's
own data, so they need no GFX Engine:

    from hudbuilder import embed
    builder = embed.start(game="lol", title="League HUD", port=8810,
                          data_dir=DATA_DIR, snapshot=self._engine_snapshot,
                          host_url=lambda: f"http://127.0.0.1:{port}")

snapshot() is what the app sends the GFX Engine ({"fields": {...}, "series":
{"left": {"name", "short", "score", "color", "logo"?}, "right": ..., "best_of"}}),
so a design shows {{League HUD!KILLS LEFT}} and {{Global!Left name}} exactly as
in HUD Builder and the GFX Engine.

The game HUD repositories keep a copy of this package (with its web folder in
hudbuilder/web): copy it from the hud-builder repository after changing it.
"""

import json
import os
import re
import threading

from .log import log

PORTS = {"lol": 8810, "valorant": 8811, "cod": 8812, "rl": 8813, "smash": 8814, "overwatch": 8815}


def _pic(value, base):
    if not value or not isinstance(value, str) or re.match(r"^(https?:|data:|\{\{)", value, re.I) or not base:
        return value or ""
    return base.rstrip("/") + "/" + value.lstrip("/")


def tables(source, snap, base=""):
    """{source: the app's fields, "Global": its teams} as data tables."""
    snap = snap or {}
    fields = snap.get("fields") or {}
    rows = [["Field", "Value"]] + [[str(k), "" if v is None else str(v)] for k, v in fields.items()]
    rows = [[k, _pic(v, base) if re.search(r"\.(png|jpe?g|webp|gif|svg)(\?.*)?$", v, re.I) else v] for k, v in rows]
    series = snap.get("series") or {}
    best_of = int(series.get("best_of") or 3)
    g = [["Field", "Value"], ["Best of", str(best_of)]]
    played = 0
    for side in ("left", "right"):
        t = series.get(side) or {}
        S = side.title()
        score = int(t.get("score") or 0)
        played += score
        g += [[f"{S} name", t.get("name") or ""], [f"{S} short", t.get("short") or ""],
              [f"{S} logo", _pic(t.get("logo") or "", base)], [f"{S} color", t.get("color") or ""],
              [f"{S} score", str(score)]]
        g += [[f"{S} won {n}", "1" if score >= n else ""] for n in range(1, 5)]
    g += [[f"Game box {n}", "1" if n <= (best_of + 1) // 2 else ""] for n in range(1, 5)]
    g += [["Game", str(played + 1)], ["Event", str(snap.get("event") or "")], ["Stage", str(snap.get("stage") or "")]]
    return {source: rows, "Global": g}


class LocalFeed:
    """The host app's data, read a few times a second (the same face as EngineFeed)."""

    def __init__(self, embed, on_change, every=0.2):
        self.embed, self.on_change, self.every = embed, on_change, every
        self.tables, self._key = {}, None
        self._stop = threading.Event()
        self.connected, self.error = True, ""

    def start(self):
        threading.Thread(target=self._run, name="hud-builder-data", daemon=True).start()

    def stop(self):
        self._stop.set()

    def reconnect(self):
        pass

    def status(self):
        host = self.embed.get("host_url", "")
        return {"url": host() if callable(host) else host, "connected": True, "error": "", "name": self.embed["title"],
                "version": "", "feeds": {self.embed["title"]: {"game": self.embed["game"], "age": 0}}}

    def read(self):
        try:
            host = self.embed["host_url"]
            base = host() if callable(host) else host
            t = tables(self.embed["title"], self.embed["snapshot"](), base)
        except Exception as e:   # (the app's data can't take the builder down)
            if self.error != repr(e):
                log(f"HUD Builder: couldn't read the HUD's data ({e!r})", "warn")
            self.error = repr(e)
            return False
        key = json.dumps(t, sort_keys=True)
        if key == self._key:
            return False
        self._key, self.tables = key, t
        return True

    def _run(self):
        while not self._stop.wait(self.every):
            if self.read():
                self.on_change()


def start(game, title, snapshot, data_dir, port=None, host_url=""):
    """Start the built-in HUD Builder (its own little web server). Returns the
    HudBuilderApp; its address is http://localhost:<port>/ and a design's
    browser source is .../hud/<id>."""
    from .app import HudBuilderApp, start as serve
    from .config import Config
    folder = os.path.join(data_dir, "hud-builder")
    os.makedirs(folder, exist_ok=True)
    config = Config(os.path.join(folder, "config.json"))
    config.update({"http_port": int(port or PORTS.get(game, 8816))})
    embed = {"game": game, "title": title, "snapshot": snapshot, "host_url": host_url}
    # (the app's own Appearance look: appearance.json beside it)
    app = HudBuilderApp(config, os.path.join(folder, "huds"), embed=embed, data_dir=data_dir)
    app.engine.read()
    try:
        serve(app)
    except OSError as e:
        log(f"Custom design (HUD Builder) couldn't start on port {config.get()['http_port']}: {e}", "warn")
        return None
    return app


def url(app):
    return f"http://localhost:{app.server.port}/" if app and app.server else ""


def open_window(app, title="Custom design"):
    """The Custom design page: a window of the app's own (pywebview), else the browser."""
    address = url(app)
    if not address:
        raise ValueError("Custom design isn't running (its port may be taken: see the log)")
    try:
        import webview
        if webview.windows:
            webview.create_window(title, address, width=1440, height=900, min_size=(1100, 700),
                                  background_color="#000000", text_select=True)
            return address
    except Exception as e:   # (no window library: the browser)
        log(f"Custom design: opening it in the browser ({e!r})")
    import webbrowser
    webbrowser.open(address)
    return address
