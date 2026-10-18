# Build with the locked backend desktop extra after build_assets.py and npm build.
import importlib.metadata
import sys
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_all, collect_data_files, collect_submodules, copy_metadata,
)

root = Path(SPECPATH).parent
backend = root / 'backend'
assets = root / 'desktop/build/assets'
datas = [
    (str(backend / 'prompts'), 'prompts'),
    (str(backend / 'alembic'), 'alembic'),
    (str(backend / 'alembic.ini'), '.'),
    (str(root / 'frontend-console/dist'), 'frontend'),
    (str(assets / 'model'), 'model'),
    (str(assets / 'licenses'), 'licenses'),
    (str(assets / 'manifest.json'), '.'),
]
binaries = []
for file in (assets / 'postgres').rglob('*'):
    if file.is_file():
        destination = 'postgres/' + file.relative_to(assets / 'postgres').parent.as_posix()
        binary = file.parent.name == 'bin' or file.suffix in {'.dll', '.so', '.dylib'}
        (binaries if binary else datas).append((str(file), destination))
hidden = ['run_worker', 'onnxruntime', 'tokenizers', 'asyncpg', 'psycopg2',
          'sqlalchemy.dialects.postgresql.asyncpg', 'uvicorn.logging',
          'uvicorn.loops.auto', 'uvicorn.protocols.http.auto', 'uvicorn.lifespan.on']
for package in ['app', 'core', 'infrastructure', 'modules', 'shared', 'scripts', 'desktop']:
    hidden += collect_submodules(package, filter=lambda name: 'tests' not in name.split('.'))
    if package != 'desktop':
        datas += collect_data_files(
            package, include_py_files=True,
            excludes=['**/tests/**', '**/test_*.py', '**/__pycache__/**', '**/*.pyc'],
        )
web_datas, web_binaries, web_hidden = collect_all('webview')
datas += web_datas
binaries += web_binaries
hidden += web_hidden
for distribution in importlib.metadata.distributions():
    datas += copy_metadata(distribution.metadata['Name'])
a = Analysis([str(root / 'desktop/entry.py')], pathex=[str(root), str(backend)],
             binaries=binaries, datas=datas, hiddenimports=hidden,
             excludes=['pytest', 'ruff', 'torch', 'sentence_transformers', 'tkinter',
                       'PyQt5', 'PyQt6', 'PySide2', 'PySide6'])
pyz = PYZ(a.pure)
options = [('X utf8', None, 'OPTION')]
exe = EXE(pyz, a.scripts, options, exclude_binaries=True, name='NovelCraft',
          debug=False, strip=False, upx=False, console=False)
runtime = EXE(pyz, a.scripts, options, exclude_binaries=True, name='NovelCraftRuntime',
              debug=sys.platform == 'win32', strip=False, upx=False, console=True)
app = COLLECT(exe, runtime, a.binaries, a.datas,
              strip=False, upx=False, name='NovelCraft')
if sys.platform == 'darwin':
    app = BUNDLE(app, name='NovelCraft.app', bundle_identifier='io.novelcraft.desktop',
                 info_plist={'NSHighResolutionCapable': True,
                             'LSMinimumSystemVersion': '14.0'})
