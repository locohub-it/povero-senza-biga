# PyInstaller: un solo file PoveroSenzaBiga.exe con Python, librerie e sito dentro.
#   pyinstaller desktop/PoveroSenzaBiga.spec
import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
skip = lambda name: not any(p in name for p in (".mcp", ".cli", "tests"))

hidden = (
    collect_submodules("app")
    + collect_submodules("fli", filter=skip)
    + collect_submodules("fast_flights", filter=skip)
    + collect_submodules("uvicorn")
)
datas = [
    (os.path.join(ROOT, "static"), "static"),
    (os.path.join(ROOT, "app", "data"), os.path.join("app", "data")),
] + collect_data_files("fli") + collect_data_files("fast_flights")

icon = os.path.join(SPECPATH, "icon.ico")

a = Analysis(
    [os.path.join(SPECPATH, "launcher.py")],
    pathex=[ROOT],
    datas=datas,
    hiddenimports=hidden,
    excludes=["playwright", "tkinter", "matplotlib", "pytest", "IPython"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas,
    name="PoveroSenzaBiga",
    console=False,
    upx=False,
    icon=icon if os.path.exists(icon) else None,
)
