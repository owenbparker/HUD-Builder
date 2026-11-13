"""Settings for HUD Builder, saved to config.json next to the project (or
next to HUDBuilder.exe in the desktop build). The HUDs themselves are in the
huds/ folder beside it (see store.py)."""

import copy
import json
import os
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FROZEN = getattr(sys, "frozen", False)
RESOURCE_DIR = getattr(sys, "_MEIPASS", ROOT) if FROZEN else ROOT
DATA_DIR = os.path.dirname(os.path.abspath(sys.executable)) if FROZEN else ROOT
WEB_DIR = os.path.join(RESOURCE_DIR, "web")
# (built into a game HUD app, its web folder travels inside the package: see embed.py)
_PKG_WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
if os.path.isdir(_PKG_WEB):
    WEB_DIR = _PKG_WEB
HUDS_DIR = os.path.join(DATA_DIR, "huds")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")

DEFAULTS = {
    # Not a port any other SCC app uses (HUDs 8777-8798, GFX Engine 8782/8783).
    "http_host": "127.0.0.1",
    "http_port": 8800,
    # Other PCs on the network can show the HUDs (OBS / vMix on another PC)
    # and use their control panels.
    "allow_network": False,
    # The SCC GFX Engine the game data comes from (the teams, and what the game
    # HUDs send it); "" = the one on this PC.
    "engine_url": "",
}

_lock = threading.Lock()


def _merge(base, extra):
    out = copy.deepcopy(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


class Config:
    def __init__(self, path=CONFIG_PATH):
        self.path = path
        self.data = copy.deepcopy(DEFAULTS)
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    self.data = _merge(DEFAULTS, json.load(f))
            except (OSError, ValueError):
                pass

    def get(self):
        with _lock:
            return copy.deepcopy(self.data)

    def update(self, changes):
        with _lock:
            self.data = _merge(self.data, changes)
            snapshot = copy.deepcopy(self.data)
        self.save(snapshot)
        return snapshot

    def save(self, snapshot=None):
        snapshot = snapshot if snapshot is not None else self.get()
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2)
        os.replace(tmp, self.path)


def web_file(rel):
    """Path on disk for a URL path in the web folder (None if it climbs out or isn't there)."""
    rel = rel.replace("\\", "/").lstrip("/")
    path = os.path.normpath(os.path.join(WEB_DIR, rel))
    if not path.startswith(os.path.normpath(WEB_DIR) + os.sep) or not os.path.isfile(path):
        return None
    return path
