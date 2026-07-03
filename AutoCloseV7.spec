# -*- mode: python ; coding: utf-8 -*-
"""
AutoCloseV7.spec
-----------------
PyInstaller-Konfiguration fuer AutoCloseV7.

Erzeugt eine einzelne, eigenstaendige AutoCloseV7.exe (kein Python auf dem
Zielrechner noetig). Aufruf unter Windows:

    pyinstaller AutoCloseV7.spec

oder einfach build.bat doppelklicken (siehe README.md).
Die fertige Datei liegt danach in dist\\AutoCloseV7.exe.
"""

block_cipher = None

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=[
        # Tray-Icon-Backend von pystray (wird dynamisch geladen).
        "pystray._win32",
        # PIL-Module, die pystray zur Icon-Erzeugung nutzt.
        "PIL.Image",
        "PIL.ImageDraw",
        # Windows-API-Module (werden teilweise dynamisch importiert).
        "win32gui",
        "win32con",
        "win32process",
        "win32api",
        # Globaler Hotkey.
        "keyboard",
    ],
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
    name="AutoCloseV7",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Kein schwarzes Konsolenfenster - reine GUI-Anwendung.
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
