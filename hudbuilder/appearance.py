"""The control panel's Appearance setting (look + highlight colour), shared by
GFX Engine, every SCC HUD and the HUD Manager. Copied verbatim into each app.

Saved next to the app's other settings in appearance.json, so it survives a
restart (the app window keeps no browser storage between runs).

    GET  /api/appearance  -> {"look": "studio", "accent": ""}
    POST /api/appearance  {"look": "glass"} or {"accent": "#ff9f0a"} ("" = the look's own colour)
"""

import ipaddress
import json
import os
import re
import threading

LOOKS = ("studio", "graphite", "daylight", "glass")
DEFAULT = {"look": "studio", "accent": ""}
_lock = threading.Lock()


def _path(data_dir):
    return os.path.join(data_dir, "appearance.json")


def load(data_dir):
    try:
        with open(_path(data_dir), encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        saved = {}
    return clean(dict(DEFAULT, **(saved if isinstance(saved, dict) else {})))


def clean(a):
    look = a.get("look") if a.get("look") in LOOKS else DEFAULT["look"]
    accent = a.get("accent") or ""
    if not (isinstance(accent, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", accent)):
        accent = ""
    return {"look": look, "accent": accent.lower()}


def save(data_dir, change):
    with _lock:
        a = load(data_dir)
        a.update({k: v for k, v in (change or {}).items() if k in DEFAULT})
        a = clean(a)
        tmp = _path(data_dir) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(a, f, indent=2)
        os.replace(tmp, _path(data_dir))
        return a


def _local(ip):
    try:
        a = ipaddress.ip_address(ip)
        return a.is_loopback or (a.ipv4_mapped is not None and a.ipv4_mapped.is_loopback) if a.version == 6 else a.is_loopback
    except ValueError:
        return False


def handle(req, method, path, data_dir):
    """Answers /api/appearance on a BaseHTTPRequestHandler. True when it did."""
    if path != "/api/appearance" or method not in ("GET", "POST"):
        return False
    status = 200
    try:
        if method == "POST" and not _local(req.client_address[0]):
            out, status = {"error": "Appearance can only be changed on this PC"}, 403
        elif method == "POST":
            length = int(req.headers.get("Content-Length") or 0)
            body = json.loads(req.rfile.read(length) or b"{}") if length else {}
            out = save(data_dir, body if isinstance(body, dict) else {})
        else:
            out = load(data_dir)
    except (OSError, ValueError) as e:
        out, status = {"error": str(e)}, 400
    data = json.dumps(out).encode("utf-8")
    req.send_response(status)
    req.send_header("Content-Type", "application/json")
    req.send_header("Cache-Control", "no-store")
    req.send_header("Content-Length", str(len(data)))
    req.end_headers()
    req.wfile.write(data)
    return True
