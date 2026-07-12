# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

project_root = Path.cwd().resolve()
assets_dir = project_root / "app" / "gui" / "assets"
icon_path = assets_dir / "jpllama-logo.icns"

block_cipher = None

a = Analysis(
    [str(project_root / "app" / "gui" / "main_window.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        (str(assets_dir), "app/gui/assets"),
    ],
    hiddenimports=[],
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="JPLlamA",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_path) if icon_path.exists() else None,
)

app = BUNDLE(
    exe,
    name="JPLlamA.app",
    icon=str(icon_path) if icon_path.exists() else None,
    bundle_identifier="com.jpllama.desktop",
    version="2.0.0",
    info_plist={
        "CFBundleName": "JPLlamA",
        "CFBundleDisplayName": "JPLlamA",
        "CFBundleShortVersionString": "2.0.0",
        "CFBundleVersion": "2.0.0",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
    },
)
