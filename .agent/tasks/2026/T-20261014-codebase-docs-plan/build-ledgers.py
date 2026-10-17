"""Build fixed-baseline task ledgers; no business or private data reads."""
from pathlib import Path
import csv,json,subprocess,tomllib,re,collections
ROOT=Path('/Users/tywww/.codex/worktrees/docs-refresh-luna/ai-writing-assist')
OUT=Path('/Users/tywww/Desktop/项目/ai-writing-assist/.agent/tasks/2026/T-20261014-codebase-docs-plan')
B='22bb499789cba89fea92e918fd853ab768688e07'
def git(*args):return subprocess.check_output(['git','-c','core.quotepath=false',*args],cwd=ROOT,text=True)
def rows_write(name,rows):
 assert rows and len({r[next(iter(r))] for r in rows})==len(rows)
 with (OUT/name).open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
def compact(v):return json.dumps(v,ensure_ascii=False,separators=(',',':')) if not isinstance(v,str) else v
changed=set(git('diff','--name-only').splitlines())
changed.update(git('ls-files','--others','--exclude-standard').splitlines())
claims=[];targeted=collections.defaultdict(list);docrefs=collections.defaultdict(list)
update_ids={'L1-ACCOUNT-CONNECTION-VERIFICATION','L1-PROJECT-TEXT-SNAPSHOT-RESTORE','L1-PROJECT-IMAGE-SNAPSHOT','L1-LOCAL-TEXT-RETIREMENT-MISMATCH','L1-LOCAL-RECEIPT-UNKNOWN-RESULTS','WS-02','WS-03','WS-05','WS-07','ST-01','L3-WE-007','L3-WE-008','L3-WE-010','L3-WE-012','L4-IMP-01','L4-EVD-09','L4-EVD-10','L5-I-03','L5-I-04','L6-DI-COMPOSITION-ROOT','L6-EVAL-PAUSE-PREFLIGHT','L7-WRITING-003','L7-RP-004','L7-NAV-005','L7-RP-TOGGLE-006','L7-DOCX-007'}
def getpaths(v):
 if isinstance(v,str):return [p.strip() for p in v.split(';')]
 if isinstance(v,list):return [x.get('path','') if isinstance(x,dict) else x for x in v]
 return []
for n in range(1,8):
 d=json.loads((OUT/f'research/L{n}-claims.json').read_text());items=d if isinstance(d,list) else d['claims']
 for c in items:
  assert c['baseline_sha']==B
  for key in ['claim_id','domain','conclusion','code_refs','callers','read_depth','validation_identity','unknowns','proposed_action']:assert key in c,(n,key)
  docs=c.get('document_refs',c.get('doc_path',''));tests=c.get('test_refs',c.get('test_refs/proof_scope',[]));cid=c['claim_id']
  for p in getpaths(docs):
   if p.startswith('infrastructure/'):p='backend/'+p
   docrefs[p].append(cid)
  for ref in c['code_refs']:
   p=ref.get('path','') if isinstance(ref,dict) else str(ref).split(':')[0]
   if p and (ROOT/p).is_file():targeted[p].append(cid)
   elif p and not (ROOT/p).exists():raise AssertionError(('missing code ref',cid,p))
  # Preserve raw L1 research but amend the final ledger from the independent Sol review.
  if cid=='L1-PROJECT-TEXT-SNAPSHOT-RESTORE':
   c['conclusion']=c['conclusion'].replace('obtains a secret-free account runtime profile','obtains a server-only transient account runtime profile containing the decrypted current Key; secret-free applies to public projections and persisted execution snapshots')
   c['validation_identity']=compact(c['validation_identity'])+'; final runtime-profile wording independently corrected and re-read by gpt-6.1-sol/high, see SOL-CONTRACT-REVIEW.md'
  decision='updated' if cid in update_ids else 'retained_with_limits'
  if cid=='L1-RUNTIME-POLICY-CATALOG-UNRESOLVED':decision='unknown_runtime_connection_no_call'
  if cid in {'L3-WE-006','L3-WE-011'}:decision='coverage_gap_recorded_no_test_added'
  claims.append({'claim_id':cid,'role':f'L{n}','baseline_sha':B,'domain':c['domain'],'document_refs':compact(docs),'conclusion':c['conclusion'],'code_refs':compact(c['code_refs']),'callers':compact(c['callers']),'test_refs':compact(tests),'proof_scope':compact(c.get('proof_scope','See each test reference; static source unless explicitly executed')),'read_depth':compact(c['read_depth']),'validation_identity':compact(c['validation_identity']),'unknowns':compact(c['unknowns']),'proposed_action':compact(c['proposed_action']),'decision':decision,'evidence':f'research/L{n}.md'+('; research/SOL-CONTRACT-REVIEW.md (gpt-6.1-sol/high independent correction)' if cid=='L1-PROJECT-TEXT-SNAPSHOT-RESTORE' else '')})
rows_write('claims.csv',claims)
base_rows=list(csv.DictReader((OUT/'doc-inventory.csv').open()))
for r in base_rows:
 p=r['path'];cat=r['category']
 if p=='docs/prompts/Prompt体系设计.md':r['owner']='L6'
 if p.endswith('.html') and (ROOT/Path(p).with_suffix('.drawio')).exists():r['canonical_source']=str(Path(p).with_suffix('.drawio'))
 if p.endswith('.drawio'):r['canonical_source']=p
 if p=='docs/product/NovelCraft-新用户指南.docx':r['canonical_source']='docs/product/word-guide-source.md (historical correspondence; generator unknown)'
 if p in changed:r.update(status='updated_semantic_reviewed',action='review_integrated_diff',evidence='fixed B diff; '+(';'.join(docrefs[p]) or 'main shared source checks'))
 elif cat=='current_registered':
  r.update(status='retained_scope_review',action='retain_existing_source_of_truth',evidence='bounded domain research '+r['owner']+'; machine inventory/link checks; not a whole-file semantic guarantee')
 elif cat in {'current_repository_governance','current_adjacent_or_guidance','adjacent_workflow_or_tool_reference'}:
  r.update(status='retained_scope_limited',action='retain_no_identified_in_scope_change',evidence='classification/trigger navigation; not whole-body audited')
 elif cat=='adr':r.update(status='retained_accepted_decision',action='retain_accepted_decision_no_policy_change',evidence='ADR inventory and relevant role references; not every ADR re-audited')
 elif cat=='derived_export' and p=='docs/product/NovelCraft-新用户指南.docx':r.update(status='historical_export_not_refreshed',action='retain_mark_historical_no_current_delivery_claim',evidence='L7 DOCX OpenXML read; old source match, no rendering')
 elif cat=='derived_export':r.update(status='private_export_inventory_only',action='retain_no_body_ingest',canonical_source='unknown_not_inspected',evidence='path inventory only; no source or currency assertion')
 if p=='docs/product/word-guide-source.md':r.update(status='historical_source_marked',action='retain_history_current_source_new_user_guide')
reg=tomllib.loads((ROOT/'docs/architecture/architecture-documents.toml').read_text());registered=set(reg['central_documents'])|set(reg['architecture_files'])
for c in reg['components']:registered.update(c.get('design_docs',[])+c.get('code_docs',[]))
for p in sorted(registered-{r['path'] for r in base_rows}):
 base_rows.append({'path':p,'category':'new_current_registered','canonical_source':p,'owner':'main','baseline_sha':B,'baseline_blob':'new','status':'added_pending_independent_review','evidence':'main reading guide/runtime flow; fixed B sources','action':'registered_entry_and_paired_diagram_checks'})
assert not any(r['status']=='queued' for r in base_rows)
rows_write('doc-disposition.csv',base_rows)
source=[]
for raw in git('ls-tree','-r','--full-tree',B).splitlines():
 _,p=raw.split('\t');suffix=Path(p).suffix
 if not p.startswith(('backend/','frontend-console/','deploy/','scripts/','.github/')) or suffix not in {'.py','.js','.mjs','.vue','.toml','.yaml','.yml','.sh','.json'}:continue
 if any(x in p for x in ['/tests/','/test/','/e2e/','/fixtures/','/.test-logs/','/node_modules/','/artifacts/']) or Path(p).name.startswith('test_'):continue
 refs=targeted[p]
 source.append({'path':p,'baseline_sha':B,'read_grade':'targeted_sections' if refs else 'inventory_only','claims':';'.join(refs),'scope':'claim-linked owning/caller sections read; not every line' if refs else 'no L1-L7 claim-linked read recorded; additional R1/R2 reads are in review reports; no semantic assurance'})
rows_write('source-coverage.csv',source)
summary={'baseline_sha':B,'claims':len(claims),'role_claims':dict(collections.Counter(r['role'] for r in claims)),'claim_decisions':dict(collections.Counter(r['decision'] for r in claims)),'baseline_document_paths':len(base_rows)-3,'new_registered_documents':3,'registered_documents_now':len(registered),'source_paths':len(source),'source_grades':dict(collections.Counter(r['read_grade'] for r in source)),'read_scope':'L1-L7 claim-linked key workflows; excludes extra main/R1/R2 reads; not whole codebase line-by-line audit','checks':'tests are source references unless role validation explicitly records a command'}
(OUT/'ledger-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n');print(json.dumps(summary,ensure_ascii=False))
