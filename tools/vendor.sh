#!/bin/sh
# Copies HUD Builder into a game HUD repository (its "Custom design" page):
#   tools/vendor.sh ../leaguehudscc
# -> <repo>/hudbuilder/ (the package, with its web folder inside). See hudbuilder/embed.py.
set -e
src="$(cd "$(dirname "$0")/.." && pwd)"
dest="$1/hudbuilder"
[ -d "$1" ] || { echo "usage: $0 <game HUD repo>"; exit 1; }
rm -rf "$dest"
mkdir -p "$dest/web"
for f in "$src"/hudbuilder/*.py; do
  case "$(basename "$f")" in gui.py|__main__.py) ;; *) cp "$f" "$dest/" ;; esac
done
cp -R "$src"/web/. "$dest/web/"
cp "$src/README.md" "$dest/HUD-BUILDER.md"
echo "HUD Builder $(cd "$src" && git rev-parse --short HEAD 2>/dev/null) copied into $dest"
