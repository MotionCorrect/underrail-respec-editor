# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

block_cipher = None
project_root = Path(SPECPATH).parent


def collect_tree(src_dir: Path, dest_prefix: str):
    entries = []
    for path in src_dir.rglob('*'):
        if path.is_file():
            rel_parent = path.parent.relative_to(src_dir)
            dest = str(Path(dest_prefix) / rel_parent)
            entries.append((str(path), dest))
    return entries

frontend_data = collect_tree(project_root / 'frontend' / 'out', 'underrail_respec_editor/frontend/out')
json_data = collect_tree(project_root / 'src' / 'underrail_respec_editor' / 'data', 'underrail_respec_editor/data')
runtime_patcher_data = collect_tree(project_root / 'runtime-patcher', 'runtime-patcher')

a = Analysis(
    [str(project_root / 'src' / 'underrail_respec_editor' / 'portable.py')],
    pathex=[str(project_root / 'src')],
    binaries=[],
    datas=frontend_data + json_data + runtime_patcher_data,
    hiddenimports=['underrail_respec_editor.save_tool', 'underrail_respec_editor.web_app', 'underrail_respec_editor.runtime_mods'],
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
    name='underrail-respec-editor',
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
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='underrail-respec-editor',
)
