"""Run only this task's isolated acceptance copy with the demo's local configuration."""
import ast
import os
from pathlib import Path
import runpy
import subprocess
import sys
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[5]
DEMO = Path('/Users/tywww/Desktop/NovelCraft-诡秘地图演示-20260909/完整项目演示')
env = {**dotenv_values(DEMO / 'app/backend/.env'), **runpy.run_path(str(ROOT / 'scripts/dev_stack.py'))['_local_object_storage_env']()}
for node in ast.walk(ast.parse((DEMO / 'launch_demo.py').read_text())):
    if isinstance(node, ast.Assign) and any(isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant) and target.slice.value == 'DATABASE_URL' for target in node.targets):
        url = ast.literal_eval(node.value)
        break
else:
    raise RuntimeError('Demo database configuration not found')
env.update(DATABASE_URL=url.rsplit('/', 1)[0] + '/ai_novel_audit_guimi_ux_live_20260911', ALLOWED_ORIGINS='http://localhost:8098', PUBLIC_BASE_URL='http://localhost:8098', BACKEND_PORT='8018', FRONTEND_PORT='8098')
if __name__ == '__main__':
    if sys.argv[1] == 'migrate':
        raise SystemExit(subprocess.call([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=ROOT/'backend', env=env))
    if sys.argv[1] == 'backend':
        os.chdir(ROOT/'backend')
        os.execve(sys.executable, [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8018'], env)
    if sys.argv[1] == 'worker':
        os.chdir(ROOT/'backend')
        os.execve(sys.executable, [sys.executable, 'run_worker.py'], env)
    if sys.argv[1] == 'frontend':
        raise SystemExit(subprocess.call(['node','node_modules/vite/bin/vite.js','preview','--host','127.0.0.1','--port','8098','--strictPort'], cwd=ROOT/'frontend-console',env=env))
    raise RuntimeError('Choose migrate, backend, worker or frontend')
