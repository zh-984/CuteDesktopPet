# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PIL import Image

root = Path(SPECPATH)
runtime_frames = Path(workpath) / 'runtime_frames'
runtime_frames.mkdir(parents=True, exist_ok=True)
for source in (root / 'assets' / 'processed').glob('*.png'):
    # The pet is at most 400 logical pixels. Keep enough detail for 2x DPI.
    with Image.open(source) as image:
        image = image.convert('RGBA')
        image.thumbnail((800, 800), Image.Resampling.LANCZOS)
        image.save(runtime_frames / source.name, optimize=True)

a = Analysis(
    ['pet.py'],
    pathex=[],
    binaries=[],
    datas=[(str(runtime_frames / '*.png'), 'assets/processed'),
           ('assets/app_icon.ico', 'assets'), ('assets/葡萄冻冻.ico', 'assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CuteDesktopPet',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/葡萄冻冻.ico',
)


coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='CuteDesktopPet',
)
