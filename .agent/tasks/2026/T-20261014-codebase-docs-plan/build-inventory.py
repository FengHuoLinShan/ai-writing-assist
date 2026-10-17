from pathlib import Path
import subprocess,tomllib,csv,json,re,datetime
from zoneinfo import ZoneInfo
root=Path('/Users/tywww/.codex/worktrees/docs-refresh-luna/ai-writing-assist');out=Path('/Users/tywww/Desktop/项目/ai-writing-assist/.agent/tasks/2026/T-20261014-codebase-docs-plan');B='22bb499789cba89fea92e918fd853ab768688e07'
r=tomllib.loads(subprocess.check_output(['git','show',B+':docs/architecture/architecture-documents.toml'],cwd=root,text=True))
roles={'account':'L1','project':'L1','local_agent':'L1','writing':'L2','story':'L2','world':'L3','evolution':'L3','imports':'L4','evidence':'L4','assistant':'L5','collaboration':'L5','interaction':'L5','infrastructure':'L6','frontend':'L7','prompts':'main'}
registered=set(r['central_documents'])|set(r['architecture_files']);doc_owners={p:'main' for p in registered}
for c in r['components']:
 for p in c.get('design_docs',[])+c.get('code_docs',[]):
  registered.add(p);doc_owners[p]=roles[c['name']] if p not in r['central_documents'] else 'main'
doc_owners['docs/product/new-user-guide.md']='L7';doc_owners['deploy/README.md']='L6'
records=[]
for raw in subprocess.check_output(['git','-c','core.quotepath=false','ls-tree','-r','--full-tree',B],cwd=root,text=True).splitlines():
 entry,path=raw.split('\t');mode,kind,oid=entry.split()
 suffix=Path(path).suffix.lower()
 if path not in registered and suffix not in {'.md','.drawio','.docx','.pdf','.xlsx','.csv','.html'}:continue
 if suffix=='.html' and path not in registered and not path.startswith(('docs/','frontend-console/docs/')):continue
 owner=doc_owners.get(path,'main')
 for c in r['components']:
  if any(path.startswith(x+'/') for x in c['source_roots']):owner=roles[c['name']]
 if path in r['central_documents']:owner=doc_owners[path]
 if path in registered:category='current_registered';action='review_current';status='queued'
 elif path in {'.agent/PLANS.md','.agent/TASKS.md','.github/pull_request_template.md','DECISIONS.md','NOTES.md','SECURITY.md','THIRD_PARTY_LICENSES.md'}:
  category='current_repository_governance';status='queued';action='review_role_and_pointer_preserve_policy'
 elif '/.test-logs/' in path or path.startswith(('.test-logs/','backend/evals/artifacts/')):
  category='restricted_runtime_evidence';status='inventory_only';action='retain_no_body_ingest_no_current_quality_inference'
 elif path.startswith('backend/prompts/'):
  category='runtime_prompt_template';owner='L6';status='contract_inventory';action='read_contract_mapping_only_do_not_edit_runtime_prompt'
 elif '/fixtures/' in path:
  category='test_fixture';status='inventory_only';action='retain_fixture_not_document_contract'
 elif path.startswith(('docs/diagrams/','docs/reviews/')):
  category='historical_diagram_or_review';status='inventory_only';action='retain_snapshot_check_current_navigation_labels'
 elif path.startswith(('workflows/','tools/')) or path=='frontend-console/e2e/scenario-coverage.md':
  category='adjacent_workflow_or_tool_reference';status='queued';action='trace_current_consumer_and_status'
 elif path.startswith('.agent/tasks/'):
  category='task_record';status='inventory_only';action='retain_history_no_body_ingest'
 elif path.startswith(('docs/archive/','frontend-console/docs/')):
  category='archive_or_legacy_reference';status='inventory_only';action='retain_provenance_review_links_if_referenced'
 elif path.startswith('docs/adr/'):
  category='adr';status='queued';action='read_relevant_decisions_retain_accepted_rules'
 elif path.startswith('docs/plans/'):
  category='plan';status='inventory_only';action='retain_plan_identity_check_current_pointers'
 elif path.startswith(('docs/references/','docs/diagnostics/','docs/acceptance/','docs/evidence/')):
  category='dated_evidence_or_reference';status='inventory_only';action='retain_snapshot_no_current_status_inference'
 elif suffix in {'.docx','.pdf','.xlsx'}:
  category='derived_export';status='queued';action='trace_authoritative_source_export_status'
 elif path.endswith(('README.md','AGENTS.md','CLAUDE.md')) or path.startswith(('docs/agents/','docs/product/','docs/testing/','docs/security/','docs/frontend/')):
  category='current_adjacent_or_guidance';status='queued';action='review_trigger_scope_and_current_links'
 else:
  category='unclassified_document';status='inventory_only';action='classify_before_any_edit'
 if path.endswith(('AGENTS.md','CLAUDE.md')):owner='main';action='read_constraints_preserve_permission_semantics'
 records.append({'path':path,'category':category,'canonical_source':path if suffix=='.md' else 'to_trace','owner':owner,'baseline_sha':B,'baseline_blob':oid,'status':status,'evidence':'git ls-tree at fixed B; path inventory only','action':action})
fields=list(records[0]);p=out/'doc-inventory.csv'
with p.open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(records)
from collections import Counter
summary={'baseline':B,'checked_at':datetime.datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds'),'registered_current_paths':len(registered),'tracked_document_paths':len(records),'categories':dict(Counter(x['category'] for x in records)),'components':[{'name':c['name'],'owner':roles[c['name']],'source_roots':c['source_roots'],'docs':c.get('design_docs',[])+c.get('code_docs',[])} for c in r['components']],'read_scope':'path inventory; not whole-file semantic audit','registered_docs_not_in_tree':sorted(registered-{x['path'] for x in records})}
assert not summary['registered_docs_not_in_tree']
(out/'inventory-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in summary.items() if k not in {'components'}},ensure_ascii=False))
