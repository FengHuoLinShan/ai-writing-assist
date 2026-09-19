"""Explicit paid synthetic comparison. Run from backend with a dedicated E2E URL."""
import asyncio, json, os, sys, time, uuid, hashlib
from contextvars import ContextVar
from datetime import datetime, UTC
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path.cwd()))
from cryptography.fernet import Fernet
from dotenv import dotenv_values
transport=dotenv_values("/Users/tywww/Desktop/项目/ai-writing-assist/backend/.env")
for transport_key in ("LLM_PROXY_URL", "LLM_TRUST_ENV"):
    if transport.get(transport_key): os.environ[transport_key]=transport[transport_key]
os.environ['LLM_SETTINGS_ENCRYPTION_KEY'] = Fernet.generate_key().decode()
os.environ['ASSISTANT_ENABLED'] = 'true'
os.environ['ASSISTANT_DEEP_REVIEW_ENABLED'] = 'true'
os.environ['EMBEDDING_PROVIDER'] = 'openai'
os.environ['EMBEDDING_API_KEY'] = ''
os.environ['OPENAI_API_KEY'] = ''
os.environ['LLM_HEALTH_REQUIRED'] = 'false'
from sqlalchemy import delete, select
from core.config import Settings
from core.database import isolated_database_manager_for_testing
from app.bootstrap import register_container_services
from app.task_runtime import register_task_handlers
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.account.models import Account
from modules.account.settings_service import SettingsService
from modules.project.models import Project
from modules.writing.facade import create_draft_only
from modules.writing.schemas import WritingWorldReviewScope
from modules.writing.semantic_review import WritingSemanticWorkflowService
from modules.assistant.service import AssistantService
from modules.assistant.models import AssistantRun
from modules.assistant.schemas import SessionCreate, TurnCreate, WorkContext
from modules.assistant.teams.contracts import TeamRunCreate
from infrastructure.llm.agent_runtime import AgentRunBudget
from infrastructure.llm.providers import OpenAIProvider
from infrastructure.llm.workflow_budget import current_managed_step_context
from infrastructure.tasks.worker import TaskWorker
from infrastructure.tasks.models import AsyncTask
from run_worker import _guard_active_task_project_finalize, _require_active_task_project
from tests.e2e.config import require_e2e_database_url
ROOT = Path.cwd().parent
ART = ROOT/'.agent/tasks/2026/T-20260920-agent-teams/artifacts'/('live-'+datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ'))
ART.mkdir(parents=True, exist_ok=False)
CASES = json.loads((ART.parent/'f1-cases.json').read_text())['cases'][:4]
label = ContextVar('eval_case', default='connection')
prior_records=[]
for journal in ART.parent.glob('live-*/requests.jsonl'):
    prior_records.extend(json.loads(line) for line in journal.read_text().splitlines() if line.strip())
prior_prompt=sum(row.get('prompt_tokens',500000 if row.get('unknown_charge') else 0) for row in prior_records)
prior_output=sum(row.get('completion_tokens',row.get('max_tokens',8192) if row.get('unknown_charge') else 0) for row in prior_records)
records, pending, pending_input, pending_output = [], 0, 0, 0
from modules.assistant.teams import contracts as team_contracts, runner as team_runner
from infrastructure.llm.collaboration import content_hash
from infrastructure.llm.agent_runtime import _ALLOCATION
original_blueprint=team_contracts.blueprint_snapshot
original_instructions=team_runner._INSTRUCTIONS
def comparison_blueprint(blueprint='deep_review'):
    snapshot=original_blueprint(blueprint)
    if blueprint=='deep_review' and label.get().endswith('/B'):
        snapshot={**snapshot,'roles':{'single':'依次核对事实规则、人物动机与知识、叙事与读者信息，主动反证并保留分歧。'},'member_requests':12,'concurrency':1}
        snapshot['hash']=content_hash({key:value for key,value in snapshot.items() if key!='hash'})
    return snapshot
team_contracts.blueprint_snapshot=comparison_blueprint
team_runner.blueprint_snapshot=comparison_blueprint
lock = asyncio.Lock()
original = OpenAIProvider.generate
async def measured(self, request):
    global pending, pending_input, pending_output
    if request.model != 'deepseek-flash':
        raise RuntimeError('Only authorized deepseek-flash may be called')
    request = request.model_copy(update={'max_tokens':min(request.max_tokens or 8192,8192)})
    reserve_input = len(request.model_dump_json().encode())
    reserve_output = request.max_tokens
    async with lock:
        if len(prior_records)+len(records)+pending>=120 or any(row.get('unknown_charge') for row in records):
            raise RuntimeError('Explicit request/unknown-usage boundary reached')
        if prior_prompt+sum(row.get('prompt_tokens',0) for row in records)+pending_input+reserve_input>2000000 or prior_output+sum(row.get('completion_tokens',0) for row in records)+pending_output+reserve_output>256000:
            raise RuntimeError('Explicit token boundary reached')
        pending+=1; pending_input+=reserve_input; pending_output+=reserve_output
    step = current_managed_step_context()
    row={'case_path':label.get(),'requested_model':request.model,'step':step.step_name if step else 'connection_verification','input_hash':hashlib.sha256(request.model_dump_json().encode()).hexdigest(),'max_tokens':request.max_tokens,'temperature':request.temperature,'extra':request.extra,'reserved_input_tokens':reserve_input,'work_item':_ALLOCATION.get().work_item_id if _ALLOCATION.get() else None}
    started=time.monotonic()
    try:
        response=await original(self,request)
        usage=response.usage
        if not usage or not usage.total_tokens:
            row['unknown_charge']=True
        else:
            row.update(usage.model_dump())
        row['actual_model']=response.model
        row['tool_names']=[call.name for call in response.tool_calls]
        raw_usage=(response.raw or {}).get('usage') or {}
        row['cache_hit_tokens']=raw_usage.get('prompt_cache_hit_tokens')
        return response
    except BaseException as exc:
        row.update(error=type(exc).__name__,unknown_charge=True)
        raise
    finally:
        row['seconds']=round(time.monotonic()-started,3)
        async with lock:
            pending-=1; pending_input-=reserve_input; pending_output-=reserve_output
            records.append(row)
            with (ART/'requests.jsonl').open('a') as file:file.write(json.dumps(row,ensure_ascii=False,default=str)+'\n')
        print('CALL',row['case_path'],row['step'],row.get('total_tokens'),row.get('error','ok'),flush=True)
async def main():
    if os.environ.get('RUN_AGENT_TEAM_LIVE')!='1' or not os.environ.get('DEEPSEEK_API_KEY'):
        raise RuntimeError('Explicit live opt-in and process credential required')
    url=require_e2e_database_url(os.environ.get('E2E_DATABASE_URL'))
    register_container_services(ignore_existing=True); register_task_handlers()
    manifest={'model':'deepseek-flash','max_requests':120,'max_prompt_tokens':2000000,'max_completion_tokens':256000,'max_output_per_request':8192,'cases':[case['id'] for case in CASES],'comparison':'A existing semantic review; B one investigator with 12 requests; C three investigators with 4 each. B/C use the same authorized tools, frozen scope, shared total 30, domain acceptance and final audit. Actual usage is measured, not asserted equal.','prior_requests':len(prior_records),'prior_prompt_reserved_including_unknown':prior_prompt,'prior_completion_reserved_including_unknown':prior_output,'human_review':'pending','production_enabled':False}
    (ART/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    paths=['backend/infrastructure/llm/agent_runtime.py','backend/infrastructure/llm/collaboration.py','backend/modules/assistant/teams/runner.py','backend/modules/assistant/teams/contracts.py','backend/modules/assistant/evidence_tools.py','backend/modules/writing/semantic_review.py']
    manifest['code_hashes']={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in paths}
    (ART/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    summaries=[]
    async with isolated_database_manager_for_testing(Settings(database_url=url,pool_size=10,max_overflow=0)) as manager:
        owner=uuid.uuid4(); token=bind_principal(AccountPrincipal(account_id=owner,status='active',identity_type='email',support_code='team-live-'+owner.hex[:12]))
        OpenAIProvider.generate=measured
        try:
            async with manager.session_factory() as db:
                db.add(Account(id=owner,status='active',support_code='team-live-'+owner.hex[:12]));await db.commit()
                await SettingsService().connect_account_llm_provider(db,'deepseek',os.environ['DEEPSEEK_API_KEY'])
                await SettingsService().upsert_global_llm_defaults(db,{'max_tokens':8192,'temperature':0.2,'timeout':180})
                await db.commit()
            worker=TaskWorker(db_manager=manager,task_preflight=_require_active_task_project,task_commit_guard=_guard_active_task_project_finalize,heartbeat_interval=30)
            for case in CASES:
                for path in ['A','B','C']:
                    if any(row.get('unknown_charge') for row in records):break
                    label.set(case['id']+'/'+path); before=len(records); started=time.monotonic()
                    team_runner._INSTRUCTIONS=original_instructions.replace('最多四次模型请求','最多十二次模型请求') if path=='B' else original_instructions
                    nid=uuid.uuid4()
                    async with manager.session_factory() as db:
                        db.add(Project(id=nid,owner_id=owner,title='合成审稿样本'));await db.flush()
                        draft=await create_draft_only(db,str(nid),1,'正文',case['input']['text'])
                        if path=='A':
                            result=await WritingSemanticWorkflowService().submit_review(db,novel_id=str(nid),draft_ids=[draft.id],manual_world_scope=WritingWorldReviewScope(cutoff_chapter=1))
                            task_id=result['task_id'];run_id=None
                        else:
                            service=AssistantService();session=await service.create_session(db,SessionCreate(novel_id=nid))
                            cls=TeamRunCreate
                            result=await service.submit(db,str(session.id),cls(novel_id=nid,operation_id=uuid.uuid4(),message=case['input']['goal'],context=WorkContext(page='writing',draft_id=draft.id,chapter_index=1),allow_web=False),str(owner))
                            task_id=result['task_id'];run_id=result['id']
                        await db.commit()
                    print('RUN',case['id'],path,flush=True)
                    result=await asyncio.wait_for(worker.run_once(task_id=task_id,novel_id=str(nid)),timeout=1800)
                    async with manager.session_factory() as db:
                        task=await db.get(AsyncTask,uuid.UUID(task_id))
                        run=await db.get(AssistantRun,uuid.UUID(run_id)) if run_id else None
                        output=run.result_json if run else task.result
                        failure=(run.checkpoint_json or {}).get('failure') if run else None
                        row={'case_id':case['id'],'path':path,'task_status':task.status,'run_status':run.status if run else task.status,'seconds':round(time.monotonic()-started,2),'provider_requests':len(records)-before,'prompt_tokens':sum(x.get('prompt_tokens',0) for x in records[before:]),'completion_tokens':sum(x.get('completion_tokens',0) for x in records[before:]),'output':output,'failure':failure,'fees':'not_estimated','human_review':'pending'}
                        summaries.append(row)
                        (ART/(case['id']+'-'+path+'.json')).write_text(json.dumps(row,ensure_ascii=False,indent=2,default=str))
                        (ART/'summary.json').write_text(json.dumps(summaries,ensure_ascii=False,indent=2,default=str))
                        print('DONE',case['id'],path,row['task_status'],row['provider_requests'],row['seconds'],flush=True)
        finally:
            OpenAIProvider.generate=original
            async with manager.session_factory() as db:
                await db.execute(delete(Project).where(Project.owner_id==owner));await db.execute(delete(Account).where(Account.id==owner));await db.commit()
            reset_principal(token)
    print('ARTIFACTS',ART,flush=True)
asyncio.run(main())
