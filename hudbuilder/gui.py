"""The desktop app: runs HUD Builder and shows it in its own window (no
command prompt).

    HUDBuilder.exe                 the built app
    python -m hudbuilder.gui     the same, from source (needs: pip install pywebview)

Takes the same options as python -m hudbuilder (--port).
"""

import argparse
import json
import os
import sys
import urllib.request
import webbrowser

from .__main__ import add_arguments, build_app
from .app import start
from .config import DATA_DIR
from .log import log

TITLE = "HUD Builder"


def message_box(text, title=TITLE, error=False):
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x10 if error else 0x40)
    else:
        print(f"{title}: {text}")


def already_running(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=2) as r:
            return "huds" in json.loads(r.read())
    except Exception:
        return False


def smoke_test(port):
    """Used by the build: check the packaged app serves its pages and can load
    its window library. Writes smoke-test.txt next to the app."""
    results, ok = [], True
    for path in ("/", "/hud.html", "/control.html", "/app.js", "/editor.js", "/runtime.js", "/vendor/lottie.min.js",
                 "/appearance.css", "/appearance.js", "/update.js", "/api/state", "/api/log", "/api/appearance",
                 "/fonts/Inter.ttf", "/fonts/BebasNeue.ttf", "/assets/app_icon.png"):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
                results.append(f"OK   {path} ({len(r.read())} bytes)")
        except Exception as e:
            ok = False
            results.append(f"FAIL {path}: {e}")
    try:
        import webview  # noqa: F401
        if sys.platform == "win32":
            import webview.platforms.winforms  # noqa: F401  (loads the Edge WebView2 bridge)
        results.append("OK   window library")
    except Exception as e:
        ok = False
        results.append(f"FAIL window library: {e!r}")
    with open(os.path.join(DATA_DIR, "smoke-test.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(results + ["PASSED" if ok else "FAILED"]) + "\n")
    return ok


def main():
    # A windowed .exe has no console; give print() somewhere harmless to go.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")

    parser = argparse.ArgumentParser(description="HUD Builder desktop app")
    add_arguments(parser)
    parser.add_argument("--debug", action="store_true", help="allow right-click > Inspect in the window")
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    app = build_app(args)
    port = app.config.get()["http_port"]
    own_server = True
    try:
        start(app)
    except OSError as e:
        if already_running(port):
            # Another copy is running: just open a window onto it.
            own_server = False
        else:
            message_box(f"Couldn't start HUD Builder on port {port}:\n{e}\n\n"
                        "Another program may be using that port. Change http_port in config.json.", error=True)
            return 1

    if args.smoke_test:
        ok = smoke_test(port)
        app.stop()
        return 0 if ok else 1

    url = f"http://127.0.0.1:{port}/"
    try:
        import webview
        window = webview.create_window(f"{TITLE} {app.updater.current}", url, width=1440, height=860,
                                       min_size=(1100, 680), background_color="#000000", text_select=True)
        # Installing an update closes the window; the updater restarts the app.
        app.updater.on_exit = window.destroy
        # (Export saves a .scchud file through the window's own Save dialog)
        try:
            webview.settings["ALLOW_DOWNLOADS"] = True
        except Exception:
            pass
        webview.start(debug=args.debug, private_mode=True)
    except Exception as e:
        # No WebView2 (very old Windows 10) or no window library: use the browser.
        log(f"Couldn't open the app window ({e!r}); using the web browser instead", "warn")
        webbrowser.open(url)
        if own_server:
            message_box("HUD Builder has opened in your web browser.\n\n"
                        "It keeps running until you close this box.")
    finally:
        if own_server:
            app.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
