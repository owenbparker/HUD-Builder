"""HUD Builder: the HUD store, .scchud files and the web server.

    python -m unittest discover -s tests -v
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hudbuilder import pack  # noqa: E402
from hudbuilder.app import HudBuilderApp, start  # noqa: E402
from hudbuilder.config import Config  # noqa: E402
from hudbuilder.store import Store, tables  # noqa: E402
from hudbuilder.templates import TEMPLATES  # noqa: E402

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


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
