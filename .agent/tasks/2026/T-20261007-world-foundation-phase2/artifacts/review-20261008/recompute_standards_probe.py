import asyncio
from modules.writing import recompute
from modules.writing.schemas import WritingRecomputeRequest, WritingRecomputeAdoptRequest
from core.errors import ConflictError

class Service(recompute.WritingRecomputeService):
    version = 1
    async def _scene_roster(self, db, novel_id):
        return []
    async def _source_state(self, db, novel_id, chapters):
        return {'chapters': {str(ch): {'draft_id': f'draft-{ch}-{self.version}', 'version_number': self.version, 'content_hash': f'hash-{ch}-{self.version}'} for ch in chapters}}

writes = []
async def index(db, novel_id, chapter, *, content_mode):
    writes.append((chapter, service.version))
    return {'requested_hash': f'hash-{chapter}-{service.version}', 'status':'pending','task_id':f'task-{chapter}-{service.version}'}
recompute.request_chapter_index = index
service = Service()
async def main():
    base = dict(novel_id='synthetic-project', operation_id='same-operation', scope='reload_evidence', targets=[{'chapter_index':1}])
    preview = await service.preview(None, WritingRecomputeRequest(**base))
    service.version = 2
    first = await service.adopt(None, WritingRecomputeAdoptRequest(**base, confirmed=True))
    assert writes == [(1,2)]
    print('missing source digest: preview v1 -> adopt v2 succeeds, writes=', writes)
    changed = dict(base, targets=[{'chapter_index':2}])
    second = await service.adopt(None, WritingRecomputeAdoptRequest(**changed, confirmed=True))
    assert first.operation_id == second.operation_id and first.request_hash != second.request_hash
    assert writes == [(1,2),(2,2)]
    print('same operation_id with different targets: no conflict, writes=', writes)
    recovery_base = dict(base, operation_id='recovery-operation')
    recovery_preview = await service.preview(None, WritingRecomputeRequest(**recovery_base))
    recovery_request = WritingRecomputeAdoptRequest(**recovery_base, confirmed=True, expected_source_digest=recovery_preview.source_digest)
    done = await service.adopt(None, recovery_request)
    service.version = 3
    try:
        await service.adopt(None, recovery_request)
        raise AssertionError('probe expected failure of recovery')
    except ConflictError as err:
        assert err.code == 'recompute_source_drift'
        print('completed operation replay after new source: original receipt not recovered, result=', err.code)
asyncio.run(main())
