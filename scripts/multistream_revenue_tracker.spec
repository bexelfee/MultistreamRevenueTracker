# PyInstaller spec — Windows release (run scripts/build_release.ps1)
# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

block_cipher = None

ROOT = Path(SPECPATH).parent
SRC = ROOT / "src"
PKG = SRC / "multistream_revenue_tracker"
APP_ICON = ROOT / "res" / "app.ico"

datas = [
    (str(PKG / "ui" / "templates"), "multistream_revenue_tracker/ui/templates"),
    (str(PKG / "ui" / "static"), "multistream_revenue_tracker/ui/static"),
    (str(PKG / "static" / "supported_currencies.json"), "multistream_revenue_tracker/static"),
]

# tzdata: IANA zones for zoneinfo on Windows frozen builds
try:
    datas += collect_data_files("tzdata")
except Exception:
    pass

# pycparser (cffi/grpc); pycparser 3.x has no lextab/yacctab modules — ignore those warnings
_pyc_datas, _pyc_binaries, _pyc_hidden = collect_all("pycparser")
datas += _pyc_datas

hiddenimports = [
    "multistream_revenue_tracker",
    "multistream_revenue_tracker.__main__",
    "multistream_revenue_tracker.monitors",
    "multistream_revenue_tracker.platforms",
    "multistream_revenue_tracker.revenue",
    "multistream_revenue_tracker.goals",
    "multistream_revenue_tracker.appearance",
    "multistream_revenue_tracker.services",
    "googleapiclient",
    "googleapiclient.discovery",
    "google_auth_oauthlib",
    "google_auth_oauthlib.flow",
    "google.oauth2.credentials",
    "twitchAPI",
    "twitchAPI.oauth",
    "twitchAPI.type",
    "twitchAPI.eventsub.websocket",
    "socketio",
    "socketio.client",
    "engineio",
    "engineio.client",
    "grpc",
    "httpx",
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "starlette",
    "starlette.websockets",
    "starlette.routing",
    "starlette.middleware",
    "starlette.middleware.exceptions",
    "starlette.responses",
    "jinja2",
    "jinja2.ext",
    "anyio",
    "anyio._backends",
    "anyio._backends._asyncio",
    "multipart",
    "email_validator",
    "tzdata",
    "pycparser",
]
hiddenimports += _pyc_hidden

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(SRC)],
    binaries=_pyc_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MultistreamRevenueTracker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(APP_ICON) if APP_ICON.is_file() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="MultistreamRevenueTracker",
)
