import ast
import os
from pathlib import Path
import runpy
import sys
from dotenv import dotenv_values
repo = Path(__file__).resolve().parents[4]
demo = Path('/Users/tywww/Desktop/NovelCraft-诡秘地图演示-20260909/完整项目演示')
environment = runpy.run_path(str(demo/'app/scripts/dev_stack.py'))['_local_object_storage_env']()
environment.update({k:v for k,v in dotenv_values(demo/'app/backend/.env').items() if v is not None})
for node in ast.walk(ast.parse((demo/'launch_demo.py').read_text())):
    if isinstance(node, ast.Assign) and any(isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant) and target.slice.value == 'DATABASE_URL' for target in node.targets):
        environment['DATABASE_URL'] = ast.literal_eval(node.value)
assert environment['DATABASE_URL'].rstrip('/').endswith('/ai_novel_acceptance_guimi')
python = sys.executable
mode = sys.argv[1]
command = {
    'guard': [python, '-m', 'scripts.dev_schema_guard'],
    'backend': [python, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000'],
    'worker': [python, 'run_worker.py'],
}[mode]
os.chdir(repo/'backend')
print('Using current repository code and preserved ai_novel_acceptance_guimi for',mode,flush=True)
os.execve(python,command,environment)
