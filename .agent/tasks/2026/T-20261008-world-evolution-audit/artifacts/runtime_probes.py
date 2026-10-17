"""Synthetic, in-memory probes; no database or provider calls.
Run: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend backend/.venv/bin/python /tmp/world-evolution-audit-20261008.py
"""
import asyncio
from types import SimpleNamespace
from modules.evolution import reading, structure
from modules.evolution.commit import FrozenAttempt
from modules.writing import facade as writing
from modules.story.outline_state import facade as story

calls=[]
frozen=FrozenAttempt(novel_id='00000000-0000-0000-0000-000000000001',run_id='old-drained',attempt_id='a'*32,owner_epoch=1,producer_version='review',source_manifest_hash='b'*64,previous_receipt='c'*32,payload={'scene_id':'scene-2','scene_index':1,'execution_mode':'live','world_result':{'parent_derived':True},'scene_text':'unchanged scene 2','source_binding':{'draft_id':'draft-2','chapter_index':2,'content_hash':'d'*64,'start_offset':0,'end_offset':17}})
class Store:
    def __init__(self,*args): pass
    async def load_run(self,*args): return SimpleNamespace(status='drained')
    async def load_frozen(self,*args): return frozen
    async def load_receipt(self,*args): return object()
    async def latest_scene_attempts(self,*args): return {'scene-2':('old-drained','a'*32)}
async def get_draft(db,novel,draft):
    calls.append(('draft',draft))
    return SimpleNamespace(id='draft-2',content='unchanged scene 2',content_hash='d'*64)
async def latest(db,novel,chapter):
    calls.append(('chapter',chapter))
    return SimpleNamespace(id='draft-2')
async def validate(*args): pass

async def main():
    reading.PostgresAttemptStore=Store
    writing.get_draft=get_draft
    writing.get_latest_draft_for_chapter=latest
    story.validate_scene_source_ranges=validate
    await reading.require_current_world_candidate(None,frozen.novel_id,{'run_key':'old-drained','attempt_id':'a'*32})
    assert calls == [('draft','draft-2'),('chapter',2)],calls
    print('World adoption gate: accepted drained old result; only chapter 2 revalidated, ancestor chapter 1 never read:',calls)
    result=await structure.enqueue_structure(None,frozen.novel_id,SimpleNamespace(reading_plan_json={'structure':{'complete':True,'through_scene_index':0,'batches':[{'batch_key':'old'}]},'steps':[{'scene_index':0},{'scene_index':1}], 'structure_version':1},committed_scene_index=1,budget_remaining=100))
    assert result=={'reading_complete':True}
    print('Appended Scene 1 with structure through Scene 0: returned complete without enqueuing:',result)

if __name__ == '__main__':
    asyncio.run(main())
