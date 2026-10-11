import uuid
import pytest
from modules.story.continuity.tests.test_p2a_write_side import _scene, _working_draft, _current_checkpoint
from modules.story.continuity.tests.test_p2b_boundary_wiring import _view, _facts
from modules.story.continuity.services import MemoryService
from modules.story.continuity.scene_projection import SceneMemoryProjectionService
from modules.story.continuity.scene_state_view import SceneStateViewService
from modules.writing.repositories import WritingDraftRepository
from modules.writing.schemas import WritingDraftCreate

pytestmark = pytest.mark.asyncio

async def _events(db,nid,scene,events):
    return await MemoryService().record_scene_events(db,nid,scene_id=str(scene.id),scene_index=scene.scene_index,chapter_index=scene.chapter_ids[0],events=events)

async def test_confirmed_v1_assignment_is_not_rebound_to_v2(db_session,test_project_id):
    db,nid=db_session,test_project_id
    scene=await _scene(db,nid,0,1)
    v1=await _working_draft(db,nid,1,1,'甲保管铜钥匙。')
    key,jia=str(uuid.uuid4()),str(uuid.uuid4())
    await _events(db,nid,scene,[{'dimension':'entities','event_type':'entity_created','entity_id':key,'source':'author_confirmation','snapshot_after':{'name':'铜钥匙','custody_holder':jia,'meta':{'author_confirmed':True}}}])
    service=SceneMemoryProjectionService()
    await service.ensure_scene(db,nid,str(scene.id))
    oldcp=await _current_checkpoint(db,nid,scene,'entities')
    oldid=str(oldcp.id)
    v2=await WritingDraftRepository().create(db,WritingDraftCreate(novel_id=nid,chapter_index=1,content='乙拿走铜钥匙，旧保管记录已删除。'))
    assert v2.version_number == 2
    await service.rebuild_from_scene(db,nid,from_scene_id=str(scene.id),dimensions=['entities'])
    view=await SceneStateViewService().get_view(db,novel_id=nid,scene_id=str(scene.id),viewpoint={'kind':'author'})
    fact=next(f for d in view.dimensions if d.dimension=='entities' for f in d.facts if f.field=='custody_holder')
    ref=fact.source['provenance']['source_refs'][0]
    old=await service.get_record(db,nid,oldid)
    print('PROBE old_history_version=',old.field_provenance[0]['source_refs'][0]['version_number'],'current_source_version=',ref['version_number'],'current_value=',fact.value,'provenance_status=',fact.source['provenance']['status'],'dimension_status=',next(d.status for d in view.dimensions if d.dimension=='entities'))
    assert ref['draft_id']==str(v1.id), '旧赋值只能回开 v1，不得被 v2 working 稿洗成 exact'

async def test_reader_with_no_shown_proof_hides_secret(db_session,test_project_id):
    db,nid=db_session,test_project_id
    scene=await _scene(db,nid,0,1)
    key=str(uuid.uuid4())
    await _events(db,nid,scene,[{'dimension':'entities','event_type':'entity_created','entity_id':key,'snapshot_after':{'name':'铜锁','secret_relation':'作者秘密，正文从未展示'}}])
    reader=await _view(db,nid,scene,{'kind':'reader'})
    leaked=_facts(reader,'entities','secret_relation',key)
    print('PROBE no_draft_no_proof_reader=',[(f.field,f.value) for f in leaked])
    assert leaked==[], '无来源证明不得默认公开作者秘密'

async def test_holder_reveal_does_not_reveal_other_secret_field(db_session,test_project_id):
    db,nid=db_session,test_project_id
    scene1=await _scene(db,nid,0,1)
    scene2=await _scene(db,nid,1,2)
    await _working_draft(db,nid,1,1,'甲把铜锁交给乙保管。')
    key,jia=str(uuid.uuid4()),str(uuid.uuid4())
    await _events(db,nid,scene1,[{'dimension':'entities','event_type':'entity_created','entity_id':key,'snapshot_after':{'name':'铜锁','custody_holder':jia,'secret_relation':'未展示的作者关系'}},{'dimension':'timeline','event_type':'timeline_changed','snapshot_after':{'category':'time_order','field_path':f'{key}.custody_holder','new_value':'本章揭示保管者'}}])
    reader=await _view(db,nid,scene2,{'kind':'reader'})
    holder=_facts(reader,'entities','custody_holder',key)
    secret=_facts(reader,'entities','secret_relation',key)
    print('PROBE holder_shown=',[(f.field,f.value) for f in holder],'secret_shown=',[(f.field,f.value) for f in secret])
    assert len(holder)==1
    assert secret==[], '保管字段证明不得授予尚未揭示的关系字段'
