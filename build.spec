# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

hidden_imports = [
    'solvers_opt.solver_1_standard',
    'vtk',
    'pyvistaqt',
    'sklearn.utils._typedefs',
    'scipy.special.cython_special'
]

a = Analysis(
    ['app_gui.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hidden_imports,
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

# --- KONFIGURACJA SPLASH SCREENA ---
splash = Splash(
    'logo.png',                # Nazwa Twojego obrazka (musi być w folderze projektu!)
    binaries=a.binaries,
    datas=a.datas,
    text_pos=(10, 50),
    text_size=12,
    text_color='white',
    minify_script=True,
    always_on_top=True,
)

exe = EXE(
    pyz,
    a.scripts,
    splash,                    # <--- Dodajemy splash tutaj
    [],
    exclude_binaries=True,
    name='OptymalizatorSlupa',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,             # <--- Wyłączamy czarne okno konsoli
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    splash.binaries,           # <--- Dodajemy binaria splasha do folderu
    strip=False,
    upx=True,
    upx_exclude=[],
    name='OptymalizatorSlupa',
)