"""Run HUD Builder without a window:  python -m hudbuilder   (then open http://localhost:8800/).

For the desktop app, run HUDBuilder.exe (or python -m hudbuilder.gui).
"""

import argparse
import os
import time

from .app import HudBuilderApp, start
from .config import Config


def build_app(args):
    config = Config()
    if not os.path.exists(config.path):
        config.save()
    if args.port:
        config.update({"http_port": args.port})
    return HudBuilderApp(config)


def add_arguments(parser):
    parser.add_argument("--port", type=int, help="web server port (saved to config.json)")


def main():
    parser = argparse.ArgumentParser(description="SCC HUD Builder")
    add_arguments(parser)
    app = build_app(parser.parse_args())
    start(app)
    print("  Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        app.stop()


if __name__ == "__main__":
    main()
