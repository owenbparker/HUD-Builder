# PyInstaller build for the desktop app.
#
#   pip install -r requirements-windows.txt pyinstaller
#   pyinstaller --noconfirm HUDBuilder.spec
#
# Produces dist/HUDBuilder/HUDBuilder.exe (plus its _internal folder). The GitHub
# Actions workflow in .github/workflows/build-windows.yml runs this.
import os
import sys

root = SPECPATH
icon = os.path.join(root, "packaging", "icon.ico")

hidden, datas = [], [(os.path.join(root, "web"), "web")]
if sys.platform == "win32":
    # pywebview's Windows window (Edge WebView2) is loaded at runtime.
    hidden += ["webview.platforms.winforms", "webview.platforms.edgechromium", "clr"]

a = Analysis(
    [os.path.join(root, "HUDBuilder.py")],
    pathex=[root],
    datas=datas,
    hiddenimports=hidden,
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HUDBuilder",
    console=False,
    icon=icon if sys.platform == "win32" else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="HUDBuilder")
