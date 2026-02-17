# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

# Lista modułów, których PyInstaller może nie wykryć automatycznie
hidden_imports = [
    'solvers_opt.solver_1_standard',  # Twój dynamiczny solver
    'vtk',                            # Potrzebne dla PyVista
    'pyvistaqt',
    'sklearn.utils._typedefs',        # Często wymagane przez scikit-learn/pandas
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

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='OptymalizatorSlupa',  # Nazwa Twojego programu
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,               # Zmień na False, jeśli chcesz ukryć czarne okno
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
    strip=False,
    upx=True,
    upx_exclude=[],
    name='OptymalizatorSlupa',
)