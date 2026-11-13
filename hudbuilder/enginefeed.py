"""Game data from the SCC GFX Engine: its tables (Global - the teams -, and
what each connected game HUD sends, e.g. "League HUD"), followed live from its
/api/stream. The HUDs show them as {{Global!Left name}}, {{League HUD!KILLS LEFT}}.

Pictures in the tables (a team logo saved in the engine) are given the engine's
address, so the HUD's page can load them from it."""

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .log import log

DEFAULT_URL = "http://127.0.0.1:8782"
MEDIA = re.compile(r"\.(png|jpe?g|webp|gif|svg|webm|mp4|mov)(\?.*)?$", re.I)


def normalise(url):
    url = (url or "").strip().rstrip("/")
    if not url:
        return DEFAULT_URL
    if not re.match(r"^https?://", url, re.I):
        url = "http://" + url
    parts = urllib.parse.urlsplit(url)
    if not parts.port:
        url = f"{parts.scheme}://{parts.hostname}:8782"
    return url


def _absolute(value, base):
    """A picture path in the engine (or a HUD) made a full address."""
    if not base or not isinstance(value, str) or not value or not MEDIA.search(value):
        return value
    if re.match(r"^(https?:|data:|blob:|\{\{)", value, re.I):
        return value
    return base + "/" + value.lstrip("/")


class EngineFeed:
    def __init__(self, get_url, on_change):
        self.get_url = get_url        # () -> the address set in Settings ("" = this PC)
        self.on_change = on_change    # () -> None, after the tables change
        self.tables = {}
        self.feeds = {}
        self.engine = {}
        self.error = ""
        self.connected = False
        self.url = ""
        self._stop = threading.Event()
        self._kick = threading.Event()
        self._resp = None

    def start(self):
        threading.Thread(target=self._run, name="engine-feed", daemon=True).start()

    def stop(self):
        self._stop.set()
        self.reconnect()

    def reconnect(self):
        """After the address changes."""
        self._kick.set()
        r = self._resp
        if r:
            try:
                r.close()
            except Exception:
                pass

    def status(self):
        return {"url": self.url or normalise(self.get_url()), "connected": self.connected, "error": self.error,
                "name": self.engine.get("name", ""), "version": self.engine.get("version", ""),
                "feeds": {k: {"game": v.get("game", ""), "age": v.get("age", 0)} for k, v in self.feeds.items()}}

    def _run(self):
        wait = 1
        while not self._stop.is_set():
            self._kick.clear()
            self.url = url = normalise(self.get_url())
            try:
                with urllib.request.urlopen(url + "/api/hello", timeout=3) as r:
                    hello = json.loads(r.read() or b"{}")
                if not str(hello.get("app", "")).lower().startswith("scc gfx") and "id" not in hello:
                    raise ValueError("That address isn't an SCC GFX Engine")
                self.engine = hello
                self._follow(url)
                wait = 1
            except urllib.error.HTTPError as e:
                self._lost(url, "The GFX Engine doesn't let other PCs in (in the engine: Outputs > Network)"
                           if e.code == 403 else f"The GFX Engine said {e.code}")
            except (OSError, ValueError) as e:
                self._lost(url, "No GFX Engine at " + url if isinstance(e, (urllib.error.URLError, ConnectionError, TimeoutError))
                           else str(e))
            if self._stop.is_set():
                return
            self._kick.wait(wait)
            wait = min(wait * 2, 10)

    def _lost(self, url, why):
        if self.connected or self.error != why:
            log(f"GFX Engine: {why}", "warn" if self.connected else "info")
        was = self.connected or bool(self.tables)
        self.connected, self.error = False, why
        self.tables, self.feeds = {}, {}
        if was:
            self.on_change()

    def _follow(self, url):
        r = self._resp = urllib.request.urlopen(url + "/api/stream", timeout=20)
        try:
            if not self.connected:
                log(f"GFX Engine: connected to {self.engine.get('name') or url}")
            self.connected, self.error = True, ""
            buf = []
            while not self._stop.is_set() and not self._kick.is_set():
                line = r.readline()
                if not line:
                    raise ConnectionError("the engine closed the connection")
                line = line.decode("utf-8", "replace").rstrip("\r\n")
                if line.startswith("data:"):
                    buf.append(line[5:].lstrip())
                elif not line and buf:
                    text, buf = "\n".join(buf), []
                    try:
                        msg = json.loads(text)
                    except ValueError:
                        continue
                    if isinstance(msg, dict) and isinstance(msg.get("data"), dict):
                        self._take(url, msg["data"])
        finally:
            self._resp = None
            try:
                r.close()
            except Exception:
                pass

    def _take(self, url, data):
        raw = data.get("tables") or {}
        # Where each game HUD's own pictures are: the address of its pages.
        hud_base = {}
        for row in (raw.get("HUDs") or [])[1:]:
            if len(row) >= 2 and isinstance(row[1], str):
                parts = urllib.parse.urlsplit(row[1])
                for name in (data.get("feeds") or {}):
                    if row[0].startswith(name + " ") and parts.netloc:
                        hud_base.setdefault(name, f"{parts.scheme}://{parts.netloc}")
        tables = {}
        for name, rows in raw.items():
            if not isinstance(rows, list):
                continue
            base = hud_base.get(name) if name in (data.get("feeds") or {}) else url
            tables[name] = [[_absolute(c, base) for c in row] if isinstance(row, list) else row for row in rows]
        feeds = data.get("feeds") or {}
        if tables != self.tables or set(feeds) != set(self.feeds):
            self.tables, self.feeds = tables, feeds
            self.on_change()
        else:
            self.feeds = feeds
