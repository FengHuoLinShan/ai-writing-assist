"""Hash this project's authored rows without exporting their content."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

PROJECT = '937c86f1-a2c3-4db5-963d-f3181095f339'
TABLES = ['projects', 'story_outline_heads', 'story_outline_revisions', 'writing_drafts', 'core_entities', 'entity_relations', 'scenes', 'plot_threads', 'outline_arcs', 'foreshadowing_plans', 'reveal_plans', 'map_atlas_nodes', 'map_atlas_pages', 'map_atlas_revisions', 'world_bible_pages', 'world_bible_page_drafts', 'project_author_tasks']
DB = sys.argv[1]
assert DB in {'ai_novel_acceptance_guimi', 'ai_novel_audit_guimi_ux_live_20260911', 'ai_novel_test_guimi_restore_20260911'}

def sql(query):
    return subprocess.check_output(['docker', 'exec', 'ai-novel-db', 'psql', '-U', 'novelist', '-d', DB, '-Atc', query], text=True)

baseline = json.loads(Path(sys.argv[3]).read_text()) if len(sys.argv) > 3 else None
result = {}
for table in TABLES:
    columns = sql(f"SELECT column_name FROM information_schema.columns WHERE table_name='{table}' ORDER BY ordinal_position").splitlines()
    if not columns:
        continue
    assert ('novel_id' in columns or table == 'projects') and 'id' in columns, table
    selected = baseline[table]['columns'] if baseline and table in baseline else [name for name in columns if name not in {'created_at', 'updated_at'}]
    assert set(selected) <= set(columns)
    data = sql(f"SELECT row_to_json(t) FROM (SELECT {','.join(selected)} FROM {table} WHERE {'id' if table == 'projects' else 'novel_id'}='{PROJECT}' ORDER BY id) t")
    rows = [json.loads(line) for line in data.splitlines()]
    digest = hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    result[table] = {'columns': selected, 'rows': len(rows), 'sha256': digest}
    if table == 'writing_drafts':
        published = [row for row in rows if row.get('status') == 'published']
        result['published_drafts'] = {'rows': len(published), 'sha256': hashlib.sha256(json.dumps(published, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()}
Path(sys.argv[2]).write_text(json.dumps(result, ensure_ascii=False, indent=2))
print({table: values['rows'] for table, values in result.items()})
if baseline:
    print('Changed hashes:', [table for table in baseline if table not in result or baseline[table]['sha256'] != result[table]['sha256']])
