"""HUD Builder: the HUD store, .scchud files and the web server.

    python -m unittest discover -s tests -v
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hudbuilder import designimport, fontnames, pack  # noqa: E402
from hudbuilder.app import HudBuilderApp, start  # noqa: E402
from hudbuilder.config import Config  # noqa: E402
from hudbuilder.store import Store, tables  # noqa: E402
from hudbuilder.templates import TEMPLATES  # noqa: E402

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")



# --- a small Figma file, written with a kiwi encoder ---------------------------------------------
def _fig_file():
    import struct
    import zlib

    def uint(v):
        out = bytearray()
        while True:
            b = v & 127
            v >>= 7
            out.append(b | (128 if v else 0))
            if not v:
                return bytes(out)

    def sint(v):
        return uint((v << 1) ^ (v >> 63) if v < 0 else v << 1)

    def flt(v):
        bits = struct.unpack("<I", struct.pack("<f", v))[0]
        bits = ((bits >> 23) | (bits << 9)) & 0xFFFFFFFF
        return b"\0" if bits & 255 == 0 else struct.pack("<I", bits)

    def cstr(t):
        return t.encode() + b"\0"

    BUILTIN = {"bool": -1, "byte": -2, "int": -3, "uint": -4, "float": -5, "string": -6}
    defs = [
        ("NodeType", 0, [("DOCUMENT", 0), ("CANVAS", 1), ("FRAME", 2), ("ROUNDED_RECTANGLE", 3), ("TEXT", 4), ("VECTOR", 5)]),
        ("PaintType", 0, [("SOLID", 0), ("IMAGE", 1)]),
        ("GUID", 1, [("sessionID", "uint"), ("localID", "uint")]),
        ("Color", 1, [("r", "float"), ("g", "float"), ("b", "float"), ("a", "float")]),
        ("Vector", 1, [("x", "float"), ("y", "float")]),
        ("Matrix", 1, [("m00", "float"), ("m01", "float"), ("m02", "float"), ("m10", "float"), ("m11", "float"), ("m12", "float")]),
        ("ParentIndex", 2, [("guid", "GUID"), ("position", "string")]),
        ("Paint", 2, [("type", "PaintType"), ("color", "Color"), ("opacity", "float"), ("visible", "bool")]),
        ("TextData", 2, [("characters", "string")]),
        ("FontName", 2, [("family", "string"), ("style", "string"), ("postscript", "string")]),
        ("Path", 2, [("commandsBlob", "uint")]),
        ("NodeChange", 2, [("guid", "GUID"), ("parentIndex", "ParentIndex"), ("type", "NodeType"), ("name", "string"),
                           ("visible", "bool"), ("opacity", "float"), ("size", "Vector"), ("transform", "Matrix"),
                           ("fillPaints", "Paint[]"), ("cornerRadius", "float"), ("textData", "TextData"),
                           ("fontName", "FontName"), ("fontSize", "float"), ("fillGeometry", "Path[]")]),
        ("Blob", 2, [("bytes", "byte[]")]),
        ("Message", 2, [("nodeChanges", "NodeChange[]"), ("blobs", "Blob[]")]),
    ]
    index = {d[0]: i for i, d in enumerate(defs)}

    def ftype(t):
        t = t.rstrip("[]")
        return BUILTIN[t] if t in BUILTIN else index[t]

    sch = bytearray(uint(len(defs)))
    for name, kind, fields in defs:
        sch += cstr(name) + bytes([kind]) + uint(len(fields))
        for i, (fname, t) in enumerate(fields):
            if kind == 0:
                sch += cstr(fname) + sint(0) + b"\0" + uint(t)
            else:
                sch += cstr(fname) + sint(ftype(t)) + bytes([t.endswith("[]")]) + uint(i + 1)

    def enc(t, v):
        if t.endswith("[]"):
            if t == "byte[]":
                return uint(len(v)) + v
            return uint(len(v)) + b"".join(enc(t[:-2], x) for x in v)
        if t in BUILTIN:
            return {"bool": lambda: bytes([v]), "uint": lambda: uint(v), "int": lambda: sint(v),
                    "float": lambda: flt(v), "string": lambda: cstr(v)}[t]()
        name, kind, fields = defs[index[t]]
        if kind == 0:
            return uint(dict(fields)[v])
        if kind == 1:
            return b"".join(enc(ft, v[fn]) for fn, ft in fields)
        out = b""
        for i, (fn, ft) in enumerate(fields):
            if fn in v:
                out += uint(i + 1) + enc(ft, v[fn])
        return out + uint(0)

    def guid(n):
        return {"sessionID": 1, "localID": n}

    def move(x, y):
        return {"m00": 1.0, "m01": 0.0, "m02": float(x), "m10": 0.0, "m11": 1.0, "m12": float(y)}

    white = {"type": "SOLID", "color": {"r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0}, "opacity": 1.0, "visible": True}
    red = dict(white, color={"r": 1.0, "g": 0.0, "b": 0.0, "a": 1.0})
    path = bytes([1]) + struct.pack("<2f", 0, 0) + bytes([2]) + struct.pack("<2f", 100, 0) + bytes([2]) + struct.pack("<2f", 50, 80) + bytes([0])
    nodes = [
        {"guid": guid(0), "type": "DOCUMENT", "name": "Document"},
        {"guid": guid(1), "parentIndex": {"guid": guid(0), "position": "!"}, "type": "CANVAS", "name": "Page 1"},
        {"guid": guid(2), "parentIndex": {"guid": guid(1), "position": "!"}, "type": "FRAME", "name": "Scorebug",
         "size": {"x": 3840.0, "y": 2160.0}, "transform": move(500, 500)},
        {"guid": guid(3), "parentIndex": {"guid": guid(2), "position": "!"}, "type": "ROUNDED_RECTANGLE", "name": "Bar",
         "size": {"x": 800.0, "y": 100.0}, "transform": move(200, 1800), "fillPaints": [red], "cornerRadius": 20.0},
        {"guid": guid(4), "parentIndex": {"guid": guid(2), "position": "#"}, "type": "TEXT", "name": "Score",
         "size": {"x": 200.0, "y": 80.0}, "transform": move(400, 1810), "fillPaints": [white], "fontSize": 64.0,
         "textData": {"characters": "3 - 1"}, "fontName": {"family": "Bebas Neue", "style": "Regular", "postscript": "BebasNeue-Regular"}},
        {"guid": guid(5), "parentIndex": {"guid": guid(2), "position": "$"}, "type": "VECTOR", "name": "Arrow",
         "size": {"x": 100.0, "y": 80.0}, "transform": move(1200, 1800), "fillPaints": [white], "fillGeometry": [{"commandsBlob": 0}]},
    ]
    data = enc("Message", {"nodeChanges": nodes, "blobs": [{"bytes": path}]})
    pack_ = lambda b: zlib.compress(b)[2:-4]
    canvas = b"fig-kiwi" + struct.pack("<I", 15)
    for chunk in (pack_(bytes(sch)), pack_(data)):
        canvas += struct.pack("<I", len(chunk)) + chunk
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("canvas.fig", canvas)
        z.writestr("meta.json", "{}")
    return buf.getvalue()


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.store = Store(self.dir)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_create_from_template(self):
        hud = self.store.create("Cup bug", "valorant", TEMPLATES["scorebug"][1]())
        self.assertEqual(hud["name"], "Cup bug")
        self.assertEqual(hud["game"], "valorant")
        self.assertTrue(hud["layers"])
        self.assertIn("Left score", [v["name"] for v in hud["vars"]])
        self.assertEqual([s["id"] for s in self.store.list()], [hud["id"]])

    def test_values_follow_variables(self):
        hud = self.store.create("A", "other", {"vars": [{"name": "Score", "kind": "number", "value": "0"},
                                                        {"name": "Planted", "kind": "toggle", "value": ""}]})
        self.store.set_values(hud["id"], {"score": "3", "Planted": "true"})
        rows = dict(tables(self.store.get(hud["id"]))["HUD"])
        self.assertEqual(rows["Score"], "3")
        self.assertEqual(rows["Planted"], "1")
        with self.assertRaises(ValueError):
            self.store.set_values(hud["id"], {"Nope": "1"})
        # The editor's save keeps the values, and drops a removed variable's.
        self.store.save_design(hud["id"], {"layers": [], "vars": [{"name": "Score", "kind": "number", "value": "0"}]})
        self.assertEqual(self.store.get(hud["id"])["values"], {"Score": "3"})

    def test_duplicate_variable_names_refused(self):
        hud = self.store.create("A")
        with self.assertRaises(ValueError):
            self.store.save_design(hud["id"], {"vars": [{"name": "X"}, {"name": "x"}]})

    def test_assets(self):
        hud = self.store.create("A")
        self.assertEqual(self.store.add_asset(hud["id"], "logo.png", PNG), "assets/logo.png")
        self.assertEqual(self.store.add_asset(hud["id"], "logo.png", PNG), "assets/logo.png")   # same file: kept once
        self.assertEqual(self.store.add_asset(hud["id"], "logo.png", PNG + b"x"), "assets/logo 2.png")
        with self.assertRaises(ValueError):
            self.store.add_asset(hud["id"], "evil.exe", b"MZ")
        self.assertIsNone(self.store.asset_file(hud["id"], "../hud.json"))
        with self.assertRaises(KeyError):
            self.store.get("../etc")

    def test_scchud_round_trip(self):
        hud = self.store.create("Share me", "rl", TEMPLATES["scorebug"][1]())
        self.store.add_asset(hud["id"], "logo.png", PNG)
        self.store.set_values(hud["id"], {"Left score": "2"})
        blob = pack.export(self.store, hud["id"])
        copy = pack.import_(self.store, blob)
        self.assertNotEqual(copy["id"], hud["id"])
        self.assertEqual(copy["name"], "Share me")
        self.assertEqual(copy["game"], "rl")
        self.assertEqual(len(copy["layers"]), len(hud["layers"]))
        self.assertEqual(self.store.assets(copy["id"]), ["assets/logo.png"])
        self.assertEqual(copy["values"], {})      # values aren't shared
        with self.assertRaises(ValueError):
            pack.import_(self.store, b"not a zip")


    def test_font_names(self):
        with open(os.path.join(ROOT, "web", "fonts", "BebasNeue.ttf"), "rb") as f:
            got = fontnames.names(f.read())
        self.assertEqual(got.get("postscript"), "BebasNeue-Regular")
        self.assertEqual(fontnames.names(b"not a font"), {})

    def _sccgfx(self):
        comp = {"name": "Scorebug", "width": 3840, "height": 2160, "layers": [
            {"id": "a", "type": "text", "name": "Left name", "field": "Left team", "text": "BLUE", "x": 100, "y": 200, "w": 800, "h": 100, "font": "BebasNeue-Regular"},
            {"id": "b", "type": "text", "name": "Event", "field": "Event", "text": "{{Global!Event}}", "x": 0, "y": 0, "w": 400, "h": 80},
            {"id": "c", "type": "image", "name": "Logo", "src": "assets/logos/blue.png", "x": 0, "y": 0, "w": 200, "h": 200}]}
        with open(os.path.join(ROOT, "web", "fonts", "BebasNeue.ttf"), "rb") as f:
            font = f.read()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("scc-gfx.json", json.dumps({"format": "scc-gfx", "compositions": [comp]}))
            z.writestr("files/assets/logos/blue.png", b"\x89PNG fake")
            z.writestr("files/library/BebasNeue.ttf", font)
            z.writestr("files/assets/../../escape.png", b"x")
        return buf.getvalue()

    def test_import_sccgfx(self):
        hud = self.store.create("Bug", "other", {"layers": [], "vars": []})
        r = designimport.import_design(self.store, hud["id"], "bug.sccgfx", self._sccgfx())
        flat = [c for l in r["layers"] for c in [l] + (l.get("children") or [])]
        by = {l.get("name"): l for l in flat}
        # A field becomes a HUD variable; one already reading Global keeps its link.
        self.assertEqual([v["name"] for v in r["vars"]], ["Left team"])
        self.assertEqual(by["Left name"]["text"], "{{HUD!Left team}}")
        self.assertEqual(by["Event"]["text"], "{{Global!Event}}")
        self.assertEqual(r["linked"], 1)
        # Halved from 4K, pictures in the HUD's own assets, the font saved by its PostScript name.
        self.assertEqual(by["Left name"]["w"], 400)
        self.assertTrue(by["Logo"]["src"].startswith("assets/Scorebug/logos/"))
        assets = self.store.assets(hud["id"])
        self.assertIn(by["Logo"]["src"], assets)
        self.assertIn("assets/BebasNeue-Regular.ttf", assets)
        self.assertEqual(r["fonts_missing"], [])
        self.assertFalse(os.path.exists(os.path.join(self.dir, "escape.png")))

    def test_import_psd(self):
        try:
            from PIL import Image
            from psd_tools import PSDImage
        except ImportError:
            self.skipTest("psd-tools isn't installed")
        buf = io.BytesIO()
        PSDImage.frompil(Image.new("RGBA", (3840, 2160), (255, 0, 0, 255))).save(buf)
        hud = self.store.create("Bug", "other", {"layers": [], "vars": []})
        r = designimport.import_design(self.store, hud["id"], "overlay.psd", buf.getvalue())
        self.assertEqual(len(r["layers"]), 1)
        self.assertEqual(r["layers"][0]["w"], 1920)
        self.assertIn(r["layers"][0]["src"], self.store.assets(hud["id"]))

    def test_import_figma(self):
        hud = self.store.create("Bug", "other", {"layers": [], "vars": []})
        r = designimport.import_design(self.store, hud["id"], "bug.fig", _fig_file())
        by = {l["name"]: l for l in r["layers"]}
        self.assertEqual(r["name"], "bug")
        # Positions inside the frame, halved from 3840 wide.
        self.assertEqual((by["Bar"]["type"], by["Bar"]["x"], by["Bar"]["y"], by["Bar"]["w"]), ("rect", 100, 900, 400))
        self.assertEqual((by["Bar"]["fill"], by["Bar"]["radius"]), ("#ff0000", 10))
        self.assertEqual((by["Score"]["type"], by["Score"]["text"], by["Score"]["size"]), ("text", "3 - 1", 32))
        self.assertEqual(by["Arrow"]["type"], "image")
        with open(self.store.asset_file(hud["id"], by["Arrow"]["src"][len("assets/"):]), encoding="utf-8") as f:
            self.assertIn('d="M0 0 L100 0 L50 80 Z"', f.read())
        self.assertEqual((by["Score"]["font"], r["fonts_missing"]), ("Bebas Neue", []))   # (one HUD Builder has)

    def test_game_data(self):
        from hudbuilder import enginefeed, gamedata
        for game in gamedata.GAMES:
            cat = gamedata.catalog(game)
            tokens = [f["token"] for g in cat for f in g["fields"]]
            self.assertEqual(len(tokens), len(set(tokens)), game)
            self.assertTrue(any(f["guide"] for g in cat if g["table"] != "Global" for f in g["fields"]), game)
        self.assertIn("{{League HUD!KILLS LEFT}}", [f["token"] for g in gamedata.catalog("lol") for f in g["fields"]])
        self.assertEqual(gamedata.samples("lol")["Global"][0], ["Field", "Value"])
        self.assertEqual(enginefeed.normalise(""), "http://127.0.0.1:8782")
        self.assertEqual(enginefeed.normalise("192.168.1.20"), "http://192.168.1.20:8782")
        # Pictures in the engine's tables get its address (or the HUD's, for what a HUD sends).
        changes = []
        feed = enginefeed.EngineFeed(lambda: "", lambda: changes.append(1))
        feed._take("http://10.0.0.5:8782", {"feeds": {"League HUD": {"game": "lol"}}, "tables": {
            "Global": [["Field", "Value"], ["Left logo", "global/left.png"], ["Left name", "Blue"]],
            "League HUD": [["Field", "Value"], ["LOGO LEFT", "assets/logos/a.png"], ["KILLS LEFT", "4"]],
            "HUDs": [["Field", "Value"], ["League HUD In-game HUD", "http://10.0.0.9:8777/overlay"]]}})
        self.assertEqual(feed.tables["Global"][1][1], "http://10.0.0.5:8782/global/left.png")
        self.assertEqual(feed.tables["League HUD"][1][1], "http://10.0.0.9:8777/assets/logos/a.png")
        self.assertEqual(feed.tables["League HUD"][2][1], "4")
        self.assertEqual(changes, [1])

    def test_embedded_tables(self):
        from hudbuilder import embed
        snap = {"fields": {"KILLS LEFT": 5, "LOGO LEFT": "assets/logos/a.png"},
                "series": {"left": {"name": "Blue", "short": "BLU", "score": 1, "logo": "assets/logos/a.png"},
                           "right": {"name": "Red", "short": "RED", "score": 0}, "best_of": 3}}
        t = embed.tables("League HUD", snap, "http://127.0.0.1:8777")
        self.assertIn(["KILLS LEFT", "5"], t["League HUD"])
        self.assertIn(["LOGO LEFT", "http://127.0.0.1:8777/assets/logos/a.png"], t["League HUD"])
        g = dict(t["Global"][1:])
        self.assertEqual((g["Left name"], g["Left won 1"], g["Right won 1"], g["Game box 2"], g["Game box 3"], g["Game"]),
                         ("Blue", "1", "", "1", "", "2"))
        self.assertEqual(g["Left logo"], "http://127.0.0.1:8777/assets/logos/a.png")
        feed = embed.LocalFeed({"game": "lol", "title": "League HUD", "snapshot": lambda: snap, "host_url": ""}, lambda: None)
        self.assertTrue(feed.read())
        self.assertFalse(feed.read())   # (no change)

    def test_import_refuses_other_files(self):
        hud = self.store.create("Bug", "other", {"layers": [], "vars": []})
        with self.assertRaises(ValueError):
            designimport.import_design(self.store, hud["id"], "x.sccgfx", b"not a zip")
        with self.assertRaises(ValueError):
            designimport.import_design(self.store, hud["id"], "x.psd", b"not a psd")
        with self.assertRaises(ValueError):
            designimport.import_design(self.store, hud["id"], "x.fig", b"not a fig")


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        config = Config(os.path.join(cls.dir, "config.json"))
        config.data["http_port"] = 8809
        cls.app = HudBuilderApp(config, huds_dir=os.path.join(cls.dir, "huds"))
        start(cls.app)
        cls.base = "http://127.0.0.1:8809"

    @classmethod
    def tearDownClass(cls):
        cls.app.stop()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def call(self, path, body=None, raw=False):
        data = None if body is None else (body if raw else json.dumps(body).encode())
        req = urllib.request.Request(self.base + path, data=data, method="POST" if data is not None else "GET")
        with urllib.request.urlopen(req, timeout=5) as r:
            out = r.read()
            return json.loads(out) if r.headers.get("Content-Type", "").startswith("application/json") else out

    def test_pages_and_flow(self):
        for page in ("/", "/runtime.js", "/editor.js", "/app.js", "/panel.js", "/fonts/Inter.ttf", "/assets/app_icon.png"):
            self.assertTrue(self.call(page))
        hud = self.call("/api/huds", {"name": "Live", "template": "scorebug"})["hud"]
        hid = hud["id"]
        self.assertIn(b"runtime.js", self.call(f"/hud/{hid}"))
        self.assertIn(b"Panel.render", self.call(f"/control/{hid}"))
        # The player finds the web folder's files beside the HUD's own pictures.
        self.assertTrue(self.call(f"/huds/{hid}/fonts/BebasNeue.ttf"))
        up = self.call(f"/api/huds/{hid}/asset?name=logo.png", PNG, raw=True)
        self.assertEqual(up["path"], "assets/logo.png")
        self.assertEqual(self.call(f"/huds/{hid}/assets/logo.png"), PNG)
        out = self.call(f"/api/huds/{hid}/values", {"values": {"Left score": "4"}})
        self.assertEqual(dict(out["tables"]["HUD"])["Left score"], "4")
        self.assertFalse(self.call(f"/api/huds/{hid}/shown", {"shown": False})["shown"])
        saved = self.call(f"/api/huds/{hid}/save", {"name": "Renamed", "layers": []})
        self.assertGreater(saved["rev"], 1)
        self.assertEqual(self.call(f"/api/huds/{hid}")["name"], "Renamed")
        blob = self.call(f"/api/huds/{hid}/export")
        self.assertTrue(blob.startswith(b"PK"))
        self.assertEqual(self.call("/api/import", blob, raw=True)["hud"]["name"], "Renamed")
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.call("/api/huds/nothere1/save", {"layers": []})
        self.assertEqual(e.exception.code, 404)
        self.call(f"/api/huds/{hid}/delete", {})
        self.assertNotIn(hid, [h["id"] for h in self.call("/api/state")["huds"]])


if __name__ == "__main__":
    unittest.main()
