"""The running app: the web server for the editor, each HUD's page (the
browser source) and each HUD's control panel.

    /                       the app (HUDs, editor, control panels, settings)
    /hud/<id>               the HUD, 1920x1080 on transparent (OBS / vMix browser source)
    /control/<id>           the HUD's control panel on its own (another PC, a phone...)
    /huds/<id>/assets/...   its pictures; /huds/<id>/<file> is the web folder's file
                            (so the GFX player finds fonts/ and vendor/ beside assets/)
"""

import json
import mimetypes
import os
import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlparse

from . import appearance, designimport, pack
from .config import DATA_DIR, HUDS_DIR, web_file
from .log import log, since
from . import gamedata
from .enginefeed import EngineFeed, normalise as engine_address
from .store import GAMES, KINDS, Store, tables
from .templates import TEMPLATES
from .updater import Updater, clean_up_old_update

mimetypes.add_type("font/ttf", ".ttf")
mimetypes.add_type("font/otf", ".otf")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("video/webm", ".webm")
mimetypes.add_type("application/javascript", ".js")

PAGES = {"/": "app.html", "/app": "app.html", "/editor": "app.html"}
ID = r"([a-z0-9]{6,40})"


class HudBuilderApp:
    def __init__(self, config, huds_dir=HUDS_DIR, embed=None, data_dir=DATA_DIR):
        self.config = config
        self.store = Store(huds_dir)
        self.updater = Updater()
        self.data_dir = data_dir
        # Built into a game HUD app (embed.py): its game, and its data instead of the GFX Engine's.
        self.embed = embed
        self.server = None
        self.data_rev = 0      # goes up when the game data changes (the pages follow it)
        if embed:
            from .embed import LocalFeed
            self.engine = LocalFeed(embed, self._data_changed)
        else:
            self.engine = EngineFeed(lambda: self.config.get().get("engine_url", ""), self._data_changed)

    def _data_changed(self):
        self.data_rev += 1
        self.store.changed()

    def set_engine(self, url):
        url = (url or "").strip()
        if url:
            engine_address(url)     # (raises on nonsense)
        self.config.update({"engine_url": url})
        self.engine.reconnect()
        log(f"Game data from the GFX Engine at {engine_address(url)}")

    def host(self):
        cfg = self.config.get()
        return "0.0.0.0" if cfg.get("allow_network") else cfg["http_host"]

    def set_network(self, on):
        self.config.update({"allow_network": bool(on)})
        if self.server:
            self.server.restart(self.host())
        log("Other PCs on your network can now show the HUDs" if on else "The HUDs are now only reachable from this PC")

    def info(self):
        cfg = self.config.get()
        port = self.server.port if self.server else cfg["http_port"]
        lan = lan_ip() if cfg.get("allow_network") else None
        return {"port": port, "lan_url": f"http://{lan}:{port}" if lan else None, "network": bool(cfg.get("allow_network")),
                "engine": dict(self.engine.status(), setting=cfg.get("engine_url", "")),
                "update": None if self.embed else self.updater.info(), "data_dir": self.data_dir}

    def state(self):
        return {"app": self.info(), "huds": self.store.list(), "games": GAMES, "kinds": KINDS,
                "embed": {"game": self.embed["game"], "title": self.embed["title"], "host_url": self.engine.status()["url"]} if self.embed else None,
                "templates": {k: v[0] for k, v in TEMPLATES.items()}}

    def hud_payload(self, hud_id):
        hud = self.store.get(hud_id)
        hud["tables"] = dict(self.engine.tables, **tables(hud))
        hud["assets"] = self.store.assets(hud_id)
        hud["engine"] = self.engine_brief()
        return hud

    def engine_brief(self):
        st = self.engine.status()
        return {"connected": st["connected"], "name": st["name"], "url": st["url"], "error": st["error"],
                "feeds": sorted(st["feeds"])}

    def data_payload(self, hud_id):
        """Just the data (the game moved on, the design didn't)."""
        return {"id": hud_id, "data_only": True, "tables": dict(self.engine.tables, **tables(self.store.get(hud_id))),
                "engine": self.engine_brief()}

    def stop(self):
        self.engine.stop()
        if self.server:
            self.server.stop()


def lan_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return None


def _is_local(address):
    return address in ("127.0.0.1", "::1") or address.startswith("127.")


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def _send(self, body, ctype="application/json", status=200, extra=None):
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data, status=200):
            self._send(json.dumps(data), status=status)

        def _file(self, full):
            with open(full, "rb") as f:
                self._send(f.read(), mimetypes.guess_type(full)[0] or "application/octet-stream")

        def _page(self, name):
            full = web_file(name)
            if not full:
                return self._json({"error": "not found"}, 404)
            self._file(full)

        def _stream(self, hud_id):
            """Server-sent events: the HUD (design, values, data) each time it changes."""
            app.store.get(hud_id)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            rev, data_rev, version = None, None, -1
            try:
                self.wfile.write(b"retry: 1000\n\n")
                while True:
                    version = app.store.wait(version, 15)
                    try:
                        hud = app.store.get(hud_id)
                    except KeyError:
                        self.wfile.write(b'data: {"gone": true}\n\n')
                        self.wfile.flush()
                        return
                    if hud["rev"] != rev:
                        rev, data_rev = hud["rev"], app.data_rev
                        self.wfile.write(b"data: " + json.dumps(app.hud_payload(hud_id)).encode("utf-8") + b"\n\n")
                    elif app.data_rev != data_rev:
                        data_rev = app.data_rev
                        self.wfile.write(b"data: " + json.dumps(app.data_payload(hud_id)).encode("utf-8") + b"\n\n")
                    else:
                        self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
            except (OSError, ValueError):
                pass

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(n) if n else b""

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self):
            url = urlparse(self.path)
            path = url.path
            q = parse_qs(url.query)
            if appearance.handle(self, "GET", path, app.data_dir):
                return
            try:
                if path in PAGES:
                    return self._page(PAGES[path])
                m = re.fullmatch(r"/hud/" + ID, path)
                if m:
                    app.store.get(m.group(1))
                    return self._page("hud.html")
                m = re.fullmatch(r"/control/" + ID, path)
                if m:
                    app.store.get(m.group(1))
                    return self._page("control.html")
                m = re.fullmatch(r"/huds/" + ID + r"/(.+)", path)
                if m:
                    rel = unquote(m.group(2))
                    full = app.store.asset_file(m.group(1), rel[len("assets/"):]) if rel.startswith("assets/") else web_file(rel)
                    if not full:
                        return self._json({"error": "not found"}, 404)
                    return self._file(full)
                if path == "/api/state":
                    return self._json(app.state())
                m = re.fullmatch(r"/api/gamedata/(\w+)", path)
                if m:
                    return self._json({"catalog": gamedata.catalog(m.group(1)), "samples": gamedata.samples(m.group(1)),
                                       "source": gamedata.SOURCES.get(m.group(1), "")})
                if path == "/api/log":
                    return self._json({"lines": since(int((q.get("after") or ["0"])[0]))})
                m = re.fullmatch(r"/api/huds/" + ID, path)
                if m:
                    return self._json(app.hud_payload(m.group(1)))
                m = re.fullmatch(r"/api/huds/" + ID + r"/stream", path)
                if m:
                    return self._stream(m.group(1))
                m = re.fullmatch(r"/api/huds/" + ID + r"/export", path)
                if m:
                    hud = app.store.get(m.group(1))
                    blob = pack.export(app.store, m.group(1))
                    name = re.sub(r'[\\/:*?"<>|]+', "", hud["name"]).strip() or "HUD"
                    return self._send(blob, "application/zip", extra={
                        "Content-Disposition": f"attachment; filename=\"{name}.scchud\"; filename*=UTF-8''{quote(name)}.scchud"})
                full = web_file(unquote(path))
                if not full:
                    return self._json({"error": "not found"}, 404)
                self._file(full)
            except KeyError as e:
                self._json({"error": str(e).strip("'")}, 404)

        def do_POST(self):
            path = urlparse(self.path).path
            q = parse_qs(urlparse(self.path).query)
            if appearance.handle(self, "POST", path, app.data_dir):
                return
            local = _is_local(self.client_address[0])
            try:
                # A HUD's control panel works from other PCs (when they can reach the app);
                # making and changing HUDs only on this one.
                m = re.fullmatch(r"/api/huds/" + ID + r"/(values|reset|shown)", path)
                if m:
                    body = json.loads(self._body() or b"{}")
                    if m.group(2) == "reset":
                        app.store.reset_values(m.group(1))
                    elif m.group(2) == "shown":
                        app.store.set_shown(m.group(1), body.get("shown"))
                    else:
                        app.store.set_values(m.group(1), body.get("values") or {})
                    return self._json(app.hud_payload(m.group(1)))
                if not local:
                    return self._json({"error": "HUDs can only be changed on HUD Builder's own PC"}, 403)
                m = re.fullmatch(r"/api/huds/" + ID + r"/asset", path)
                if m:
                    name = (q.get("name") or ["picture.png"])[0]
                    rel = app.store.add_asset(m.group(1), name, self._body())
                    return self._json({"path": rel, "assets": app.store.assets(m.group(1))})
                m = re.fullmatch(r"/api/huds/" + ID + r"/import-design", path)
                if m:
                    # A GFX Engine graphic or a Photoshop file, for the editor to add.
                    name = (q.get("name") or ["design.sccgfx"])[0]
                    out = designimport.import_design(app.store, m.group(1), name, self._body())
                    out["assets"] = app.store.assets(m.group(1))
                    return self._json(out)
                if path == "/api/import":
                    name = (q.get("name") or ["hud.scchud"])[0]
                    blob = self._body()
                    if designimport.is_design(name) and not pack.is_hud(blob):
                        # A design from elsewhere: a new HUD made from it.
                        hud = app.store.create(os.path.splitext(os.path.basename(name))[0], app.embed["game"] if app.embed else "other")
                        try:
                            out = designimport.import_design(app.store, hud["id"], name, blob)
                            hud = app.store.save_design(hud["id"], {"name": out["name"], "layers": out["layers"], "vars": out["vars"]})
                        except Exception:
                            app.store.delete(hud["id"])
                            raise
                        return self._json({"hud": hud, "state": app.state(), "notes": out["notes"], "fonts_missing": out["fonts_missing"]})
                    hud = pack.import_(app.store, blob)
                    log(f"Imported {hud['name']}")
                    return self._json({"hud": hud, "state": app.state()})
                body = json.loads(self._body() or b"{}")
                if path == "/api/huds":
                    template = TEMPLATES.get(body.get("template") or "blank", TEMPLATES["blank"])[1]()
                    game = app.embed["game"] if app.embed else body.get("game") or "other"
                    hud = app.store.create(body.get("name"), game, template)
                    log(f"New HUD: {hud['name']}")
                    return self._json({"hud": hud, "state": app.state()})
                m = re.fullmatch(r"/api/huds/" + ID + r"/(save|delete|duplicate)", path)
                if m:
                    hud_id, what = m.groups()
                    if what == "save":
                        hud = app.store.save_design(hud_id, body)
                        return self._json({"rev": hud["rev"], "updated": hud["updated"]})
                    if what == "delete":
                        name = app.store.get(hud_id)["name"]
                        app.store.delete(hud_id)
                        log(f"Deleted {name}")
                        return self._json(app.state())
                    hud = app.store.duplicate(hud_id)
                    return self._json({"hud": hud, "state": app.state()})
                if path == "/api/network":
                    app.set_network(bool(body.get("on")))
                    return self._json(app.state())
                if path == "/api/engine":
                    app.set_engine(body.get("url"))
                    time.sleep(1.2)     # (time to reach it, so the page shows how it went)
                    return self._json(app.state())
                if path == "/api/update/check":
                    app.updater.check()
                    return self._json(app.state())
                if path == "/api/update/install":
                    app.updater.install_in_background()
                    return self._json(app.state())
                return self._json({"error": "not found"}, 404)
            except KeyError as e:
                self._json({"error": str(e).strip("'")}, 404)
            except (ValueError, TypeError, OSError) as e:
                self._json({"error": str(e)}, 400)

    return Handler


class Server:
    def __init__(self, app, host, port):
        self.app, self.port = app, port
        self._start(host)

    def _start(self, host):
        self.httpd = ThreadingHTTPServer((host, self.port), make_handler(self.app))
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.host = host

    def restart(self, host):
        if host != self.host:
            self.httpd.shutdown()
            self.httpd.server_close()
            self._start(host)

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def start(app):
    """Start the web server (raises OSError if the port is taken)."""
    port = app.config.get()["http_port"]
    app.server = Server(app, app.host(), port)
    clean_up_old_update()
    if not app.embed:
        app.updater.check_in_background()
    app.engine.start()
    if app.embed:
        log(f"Custom design (HUD Builder) - http://localhost:{port}/")
    else:
        log(f"HUD Builder {app.updater.current} running - http://localhost:{port}/")
    return app.server


__all__ = ["HudBuilderApp", "start"]
