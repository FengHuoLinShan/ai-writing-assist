# Semantic evaluation datasets

This directory stores schemas, small synthetic fast-gate fixtures, and redacted
manifests. It must not contain the local novel source text.

## Local corpus

- Pilot: `/Users/tywww/Desktop/项目/wirting skill/诡秘之主_第一部 小丑_前60章.txt`
- Full v1: `/Users/tywww/Desktop/项目/wirting skill/诡秘之主_第一部 小丑.txt`

The paths above are local inputs explicitly selected by the user. Generated
local datasets, review packages, judge caches, and source-bearing reports belong
under `evals/datasets/local`, `evals/artifacts`, or `evals/.cache`; all are
gitignored. Committed manifests contain hashes and logical aliases only.

## Approved models

Every generation, judge, and Ragas LLM metric defaults to the locally installed
Codex CLI pinned to `gpt-5.3-codex-spark`. A user-authorized, explicit
`EVAL_CODEX_MODEL=gpt-5.6-luna` override is accepted for usage-limit recovery;
that model is invoked with the separate `model_reasoning_effort="medium"` config;
it is never selected automatically. Cache keys and provenance retain the model
that actually produced each result. The generator/judge runner does not read project API
keys or project LLM profiles and does not silently fall back to an unapproved model. It runs
ephemerally, ignores user plugins/config/rules,
explicitly disables plugins and model tools, uses a read-only empty temporary
directory, and accepts source text only on stdin. Codex runs in a dedicated
process group; timeout cleanup kills the whole group so model-refresh children
cannot survive a cancelled eval call.

Surrogate review uses a separate, enforced assignment and does not change the
generator/judge model contract:

- reviewer A: `deepseek-v4-flash`, through the disposable project's effective
  project profile and previously configured API key (`--novel-id` is required);
- reviewer B: local Codex `gpt-5.6-luna` with reasoning effort `medium`;
- disagreement adjudicator: local Codex `gpt-5.6-terra`.

Reviewer A is the only eval-data step allowed to read a project LLM profile. Its
client is opened through the novel-scoped project runtime context and always
closed; cache/provenance store only a sanitized profile hash, never the key.
Reviewer B and the adjudicator remain isolated Codex CLI executions. The CLI
rejects a reviewer role/model mismatch.

## Commands

```bash
make eval-corpus VARIANT=pilot OUTPUT=evals/artifacts/pilot-manifest.json
make eval-fixture-manifest OUTPUT=evals/artifacts/fixture-sources.json
make eval-generate SUITE=rag VARIANT=pilot SIZE=80 \
  OUTPUT=evals/datasets/local/rag-pilot-candidate.jsonl
make eval-qc DATASET=evals/datasets/local/rag-pilot-candidate.jsonl VARIANT=pilot
make eval-judge DATASET=evals/datasets/local/rag-pilot-candidate.jsonl \
  VARIANT=pilot OUTPUT=evals/datasets/local/rag-pilot-judged.jsonl
make eval-review-export DATASET=evals/datasets/local/pilot-v0.raw-judged.jsonl \
  HTML=evals/artifacts/review-a.html JSONL=evals/artifacts/review-a.jsonl \
  DOUBLE_HTML=evals/artifacts/review-b.html \
  DOUBLE_JSONL=evals/artifacts/review-b.jsonl
make eval-review-import DATASET=evals/datasets/local/pilot-v0.raw-judged.jsonl \
  REVIEWS=evals/artifacts/review-a.jsonl REVIEWER_VERSION=reviewer-a-v1 \
  OUTPUT=evals/datasets/local/pilot-reviewed-a.jsonl \
  REPORT=evals/artifacts/reviewer-a-agreement.json
make eval-review-import DATASET=evals/datasets/local/pilot-reviewed-a.jsonl \
  REVIEWS=evals/artifacts/review-b.jsonl REVIEWER_VERSION=reviewer-b-v1 \
  OUTPUT=evals/datasets/local/pilot-reviewed-ab.jsonl \
  REPORT=evals/artifacts/reviewer-ab-agreement.json
python -m evals.cli review-model \
  evals/datasets/local/pilot-reviewed.jsonl evals/artifacts/review-a.jsonl \
  --variant pilot --suite scene --reviewer-role reviewer-a \
  --model deepseek-v4-flash --novel-id <disposable-project-id> \
  --output evals/artifacts/review-a.deepseek.jsonl
python -m evals.cli review-model \
  evals/datasets/local/pilot-reviewed.jsonl evals/artifacts/review-b.jsonl \
  --variant pilot --suite scene --reviewer-role reviewer-b \
  --model gpt-5.6-luna --output evals/artifacts/review-b.luna.jsonl
python -m evals.cli review-model \
  evals/datasets/local/pilot-reviewed-ab.jsonl evals/artifacts/ambiguous.jsonl \
  --variant pilot --suite scene --reviewer-role adjudicator \
  --model gpt-5.6-terra --output evals/artifacts/adjudication.terra.jsonl
make eval-rag DATASET=evals/datasets/local/pilot-v1.jsonl \
  NOVEL_ID=<isolated-project-id> DATASET_ID=pilot-v1 DATASET_VERSION=1.0.0
make eval-rag-prepare NOVEL_ID=<isolated-project-id> \
  CHAPTER_FROM=1 CHAPTER_TO=60 CONTENT_MODE=canonical FORCE=1
make eval-full DATASET=evals/datasets/local/pilot-v1.jsonl \
  NOVEL_ID=<isolated-project-id> DATASET_ID=pilot-v1 DATASET_VERSION=1.0.0
make eval-baseline-check DATASET=evals/datasets/local/pilot-v1.jsonl \
  SUITE=all TIER=pilot OUTPUT=evals/artifacts/pilot-v1.readiness.json
make eval-freeze DATASET=evals/datasets/local/pilot-v0-reviewed.jsonl \
  VARIANT=pilot TIER=pilot DATASET_ID=semantic-pilot-v1 \
  DATASET_VERSION=1.0.0 OUTPUT=evals/datasets/local/pilot-v1.jsonl \
  MANIFEST=evals/datasets/local/pilot-v1.manifest.json \
  READINESS=evals/artifacts/pilot-v1.readiness.json
make eval-report DATASET=evals/datasets/local/pilot-v1.jsonl \
  DATASET_ID=pilot-v1 DATASET_VERSION=1.0.0 \
  RESULTS="evals/artifacts/results/rag.result.json \
evals/artifacts/results/scene.result.json \
evals/artifacts/results/world.result.json \
evals/artifacts/results/outline.result.json" \
  JSON=evals/artifacts/pilot-v1.report.json \
  MARKDOWN=evals/artifacts/pilot-v1.report.md
make eval-fast
```

`eval-fixture-manifest` covers the stable Writing, Outline, and World synthetic
and prompt-contract fixtures. It stores only logical roles, repository-relative
paths, sizes, and SHA-256 hashes; fixture payloads are not copied into the
manifest.

The resumable full Pilot pipeline is:

```bash
make eval-pilot STAGE=generate
make eval-pilot STAGE=judge
```

When quota must be protected, add `CACHE_ONLY=1`. This mode fails immediately
on any cache miss and guarantees that no Codex process is started:

```bash
make eval-pilot STAGE=generate CACHE_ONLY=1
make eval-pilot STAGE=judge CACHE_ONLY=1
```

It targets 400 raw cases (RAG 160, Scene 80, World 100, Outline 60), exactly
twice the per-suite accepted minimums. It batches
judges by source group, and writes the combined QC, review package, manifest,
and JSON/Markdown reports under `evals/datasets/local/pilot-v0`.
The combined files are named `pilot-v0.raw-judged.*` and their manifest version
is `candidate`; they are intentionally not named like a frozen baseline.

Generation is deliberately two-stage for every chapter batch. It first writes
`*.references.json` with frozen answer/boundary/asset references, then generates
author-style questions that may only select those reference IDs. The manifest
and each case record the pinned model, executor/prompt/source hashes, fixed seed,
runtime, cache status, and an explicit `unavailable_codex_cli` cost status because
the local Codex CLI does not expose a trustworthy per-request price.

`eval-fast` is fully offline. A full candidate dataset is not a baseline until
deterministic QC, the two independent judge views, and the required stratified
human review have completed.

`eval-baseline-check` is also fully offline and only reads decisions already
stored in each case. It does not rerun QC or start Codex. Pilot readiness requires
at least 200 accepted cases with RAG/Scene/World/Outline minimums 80/40/50/30,
coverage of every configured scenario, no non-safety deterministic errors, and
explicit human acceptance/edit for every safety-critical case. Release readiness
uses the 800/300/180/200/120 thresholds and at least 20 accepted cases per
required scenario. Every tier rejects source-group split leakage; release also
requires the unique source-group ratio to remain within ±5% of 60/20/20.
Every accepted case must also retain the pinned generator model plus valid
executor/prompt/source SHA-256 values. Normal cases require at least one pinned
judge record; safety-critical cases require two pinned judge records in addition
to human review. Freeze readiness also requires judge-vs-human Cohen's kappa
≥0.75, ordinal Spearman rho ≥0.70, and inter-reviewer Cohen's kappa ≥0.75.
The full reviewed input—not only the accepted subset—must retain at least 95%
human faithful/answerable outcomes and no more than 2% ambiguous/invalid outcomes.
`eval-run`, `eval-rag`, and `eval-full` enforce this check by
default. `ALLOW_UNFROZEN=1` is only for runner smoke tests and stamps every result
with `unfrozen_dataset_smoke_only`; such output must never be frozen as a baseline.

`eval-freeze` is the only supported accepted-dataset freezing path. It reruns
deterministic QC but never starts Codex, leaves the judged/reviewed input file
unchanged, selects only cases allowed by stored judge/human decisions and current
deterministic invariants, then enforces the readiness thresholds before atomically
writing the accepted-only JSONL. Its manifest records the source dataset hash,
input/accepted/excluded counts, excluded-ID hash, corpus hash, prompt hashes, and
selection rule. The local readiness report retains excluded case IDs for audit.

Review export includes every safety-critical case, at least 15% of every
suite/scenario stratum, and at least 30 cases per suite. Supplying both
`DOUBLE_HTML` and `DOUBLE_JSONL` creates a deterministic 25% independent second
review package before either reviewer sees the other's answers. Successive
`eval-review-import` calls append reviewer decisions instead of overwriting them.
Agreement produces both judge-vs-human and inter-reviewer Cohen's kappa. A
disagreement leaves the final status `ambiguous` and restores the generated
reference; import a separate adjudicator record with `ADJUDICATION=1` to resolve
it. LLM-derived metrics remain non-blocking unless judge-vs-human binary kappa,
ordinal Spearman, and inter-reviewer kappa all pass their gates. Edited cases
retain the original generated reference and modification reason.

The production-shape runners use stable seams: RAG calls `modules.rag.facade`,
Scene submits and executes the authorized imports Scene stage then reads committed
SceneSpan contracts, World reuses the authorized imports `world_objects` stage and
reads results through `modules.world.facade`, and Outline calls the suggestion-only
preview seam. Scene/World/Outline workflow runners require
`isolated_db=True`; `make eval-full` supplies that explicit acknowledgement and
must only point at a disposable evaluation database/project. The runner never
creates, clears, or deletes a database. The Outline runner never imports or calls
the apply seam. Each suite writes `<suite>.result.json` under
`evals/artifacts/results` by default; pass `OUTPUT_DIR=...` to override it.
Each completed suite result is atomically written before the next suite starts,
so a later failure does not erase prior evidence. Pass those files through
`RESULTS="..."` to `make eval-report` to include system metrics in JSON and
Markdown reports.

Runner reports keep the complete target metric inventory. Metrics backed by
current output evidence are calculated; evidence-dependent metrics such as
calibrated Ragas scores, source-hash validity, mapping attribution, endpoint
resolution, rollback bounds, or rubric scores are emitted with
`available=false` and an explicit reason when the workflow output cannot prove
them. Missing evidence is never converted to zero or a passing result.

`make eval-ask-world` is the separate author-question launch gate. It first runs
the real API contract tests for project isolation, structured claims, citation
reopening, and current-source revalidation, then runs the fully offline synthetic
dataset through the production relevance and evidence-budget helpers. The JSON
report covers evidence ranking and dataset integrity only: it fails unless
source hashes and fixture reopening are perfect, precision@5 is at least 0.8,
no-answer false positives are at most 0.05, and every metric is available. It
does not impersonate a model judge or replace the
API contract tests that precede it.

## Ask World offline gate datasets

### ask-world-v1（确定性证据契约门禁）

`baselines/ask-world-v1.jsonl` 是 `make eval-ask-world` 的离线证据契约门禁数据
集：23 行（16 正例 + 7 负例），全部为合成短句（北境港/南岸果园/西岭驿站/灰河桥/
旧塔铜铃风格），不含本地路径与 Vault 专名。每条 source 的 `source_hash` 是
`sha256(content.encode("utf-8"))` 的真实值，`openable=true` 且
`open_hash==source_hash`；`source_hash_validity` 覆盖全部 eligible 源（含低分
干扰），不只是被 ranked 的源。

四门（`backend/evals/ask_world.py` 的 THRESHOLDS）：

| 指标 | 门禁 | 含义 |
|---|---|---|
| source_hash_validity | = 1.0 | 所有 eligible 源的 source_hash 与内容一致 |
| citation_open_rate | = 1.0 | retrieved 源 openable 且 open_hash 与 source_hash 一致 |
| p_at_5 | >= 0.8 | 前 5 个证据源中相关源占比 |
| no_answer_false_positive_rate | <= 0.05 | 负例被误答的比例 |

23 行构成：

- 既有 9 行锚点（6 正例 + 3 负例）：单源命中、双相关源、world_object、无证据、
  跨 novel 隔离、role 可见性隔离。
- P1 单源正例 ×2：`ask-salt-well-guard-shifts`（world_object）、
  `ask-ferry-tariff`（manuscript），各配 2 个无关干扰。
- P2 多源/多跳 ×3：`ask-spring-flood-bridge-toll`（双源拼接：灰河桥通行规则 +
  春汛巡堤）、`ask-pigeon-order-route`（三源传递：驿站信鸽 → 盐税仓订货 →
  红炉工坊铸造）、`ask-guild-objects`（灰河桥巡堤灯与北境港浮标同属潮汐行会）。
  干扰源共享部分 bigram 但低于 0.2 阈值。
- N1 干扰密度阶梯 ×3：同一问题「旧塔铜铃取出条件」×1/4/8 个干扰源
  （`ask-bell-density-1/4/8`）；最密档 8 个 ranked 源触发 max_sources=5 的
  rank-budget 路径，5 个相关源全部保留在前 5（p@5=1）。
- N2 近失负例 ×2：`ask-fog-lake-fish-count`（源内有雾湖与鱼、无数量）、
  `ask-dawn-road-reorder-date`（有黎明钟声、无日期），词面门对二者返回空
  retrieved。
- N3 隔离变体 ×2：`ask-reader-only-evidence-blocked`（同 novel 但
  visibility=reader）、`ask-same-name-cross-novel`（两个 novel 都有「白塔议会」
  页，仅 novel-b 含答案）。
- B 边界歧义 ×2：`ask-mill-conflict`（风车/水车双源部分冲突，双 relevant key，
  测冲突容忍，p@5=1）、`ask-partial-credit`（2 个 relevant key 中 1 个词面可
  分离、1 个不可分离，p@5=0.5，全数据集唯一不拿满分的正例，使 p_at_5 成为有区
  分力的指标）。

诚实边界：**no_answer_false_positive_rate 测的是确定性空集合同（词面检索后无证
据即不答），不是 LLM 拒答质量；LLM 拒答/忠实度属 model-probes 的未来模型层。**

### ask-world-model-probes-v1（模型质量层预备数据）

`baselines/ask-world-model-probes-v1.jsonl` 与 ask-world-v1 同 schema，但**不接
门禁**、不进 `test_ask_world.py`，也不被 `make eval-ask-world` 消费。它保存词面
门无法裁决、必须由模型判断的场景，供未来模型质量层使用：近失拒答（源内有主体词
但无答案要素且词面会命中，如雾湖鱼市无数量、黎明钟声无日期）、证据不足必须
no_answer（货船记录无数量、角色知识受限不算正史）、版本冲突必须并列说明而非
二选一（灰河桥封闭日期、白塔议会档案保管处、灰河桥渡船票价各两版）。7 行
（3 正例 + 4 负例），自带与 ask-world-v1 相同的 blocklist 自守。

The first local run produced a legacy 300-case raw candidate set before the
2x oversampling and strict scenario/persona guards were added. It remains a
local diagnostic artifact and must not be frozen as the Pilot baseline.
