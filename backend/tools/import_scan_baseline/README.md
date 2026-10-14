# G7a 导入输入扫描基线与 G7 长篇账本模板

零模型、零费用的本地诊断工具（泳道 A，能力审计后续第二批计划 §3.8 G7a）。它只做两件事：

1. 在专用 PostgreSQL 上用**程序生成的合成长篇**（无版权、无作者数据）测量深度导入
   Phase 2a 上下文准备链路的输入扫描成本，产出 SQL 条数、耗时与内存的规模曲线，
   供 C2 决策是否优化热点
   `backend/modules/evidence/compilation/services/import_activation.py:90-98`
   （每次 `prepare()` 以 `limit=10_000` 读世界上下文与实体词项）。
2. 定义 G7 长篇质量验收的指标与单一账本模板（`ledger_template.json`），
   供 G7b（诡秘前 60 章新 v3 run）填写；世界演化第四阶段 P4-E 的实测指标并入同一账本。

## 规模档位

- 章节等价档 `L10 / L30 / L60`：10/30/60 章，每章 3 Scene；canonical 实体 = 4×章数，
  review 实体 = 1×章数，别名 3 个/实体（词项随章数按比例放大），canonical 关系 = 2×章数。
- 密度探针档 `D2500 / D5000 / D10000`：固定 30 章，canonical 实体 2500/5000/9600
  （+review 250/500/400），逼近 `limit=10_000` 边界。

所有正文由固定句模板程序生成；同一档位的 `content_digest` 恒定，跨机器可比。

## 采集什么

每个档位（默认 prepare×3、热点单查×5）：

- `prepare()` 稳态调用：SQL 总数与按标签分解（`select:world_context_entities`、
  `select:entity_terms`、`select:scenes`、`select:writing_drafts`…）、DB 累计耗时、
  墙钟耗时、tracemalloc 峰值与 ru_maxrss。调用参数取生产默认
  （`context_mode="working"`、`budget_tokens=4000`、`prior_neighbor_limit=2`），
  目标 Scene 为全书最后一场；先做一次暖身提交（落 working 模式 SceneSpan 克隆），
  测量值对应长期顺序导入的稳态。
- 热点单查（隔离测量）：`get_world_context(limit=10_000, include_review=True)` 与
  `list_entity_terms(limit=10_000)` 各自的行数与 DB 耗时。

报告写入 `backend/.test-artifacts/import_scan_baseline/baseline-<时间戳>.{json,md}`
（`baseline-latest.*` 同步刷新），JSON 含 provenance（commit、源文件哈希）。

## 运行

```bash
# 专用库（默认 novel_pg_g7a @ 127.0.0.1:5207）就绪：
createdb -h 127.0.0.1 -p 5207 -U novelist novel_pg_g7a
cd backend && DATABASE_URL='postgresql+asyncpg://novelist:…@127.0.0.1:5207/novel_pg_g7a' \
  uv run --locked alembic upgrade head

# 采集：
cd backend && uv run --locked -- python -m tools.import_scan_baseline.run_baseline \
  --tiers L10,L30,L60 --density-tiers D2500,D5000,D10000
```

安全边界：工具只接受库名带独立 `g7` 标记的显式 PostgreSQL URL（默认常量或
`G7A_DATABASE_URL`/`--database-url`），拒绝共享/开发库，不读 `backend/.env`，
不回退任何其他数据库；合成数据默认在采集后删除（`--keep-data` 保留供检查）。
库为空时可用 `--create-schema` 从 ORM metadata 建表，否则要求 Alembic head。

## 测试

- 离线结构测试（默认套件）：`backend/tests/unit/test_import_scan_baseline.py`
  —— 生成器确定性、合成文本纯程序来源、SQL 标签分类、专用库拒绝规则、账本模板分母规则。
- PG 采集测试（独占库标记，显式运行）：

```bash
cd backend && IMPORT_SCAN_BASELINE_DATABASE_URL='postgresql+asyncpg://novelist:…@127.0.0.1:5207/novel_pg_g7a' \
  uv run --locked --extra ci -- pytest tests/tools/test_import_scan_baseline_pg.py -m e2e
```

## G7 指标与账本（G7b 使用说明）

模板：`ledger_template.json`（机器可读）。核心规则：

- **分母含 dropped/omitted**：`units_total = processed + dropped + omitted`，每阶段
  （source_ingest / scene_scan / entity_extraction / structure / writing_checks /
  evolution）分别报告；覆盖率与成功率不得把 dropped/omitted 剔出分母。
- **unknown 单列**：状态或用量未知的请求只进 unknown 列与 calls 账本（费用按保留上界），
  不折算成败。
- **作者处置单列**：待裁定与 adopted/rejected/edited_then_adopted/deferred/expired
  流转单独计数，不并入模型侧成功率。
- **P4-E 并入**：world 覆盖（每场/每候选）、类别发现覆盖与未检原因、容量延后、
  待裁定量、早期改稿重做范围、内容指纹稳定性 —— 与 G7 导入指标记在同一份账本，
  不重复记真实调用。

G7b（诡秘前 60 章新 v3 run）按此使用：

1. 复制 `ledger_template.json` 为该 run 的账本；填 `run`（runtime=原生 Codex Luna
   `codex-text-v3`，`baseline_commit`，`corpus_unit` 固定 前 60 章/63 来源/212868 字符，
   `cap_usd: null` + 不设上限仍全量记账）。
2. 逐阶段填 `stages`（含 dropped/omitted 原因分布，entity_extraction 至少含
   `phase2_identity_top_k`），每笔真实调用按 `model_calls.calls[]` 的 Meter 对齐格式入账。
3. 受版权原文的完整账本留仓库外私有目录；仓库内快照删除 request/response 与正文，
   留序号/状态/时间/用量/费用上界/`request_hash`，并在 `payload_redacted` 记录私有
   账本位置与 SHA-256。
4. 把本目录 `baseline-latest.json` 填进 `artifacts.g7a_scale_curves`，
   `run.g7a_baseline_report` 引用本次采集报告，作为 C2 热点决策的合成侧证据。

## 边界

本工具不调用任何模型，不接触真实作者数据或受版权稿件；结论仅代表合成语料下的
输入扫描成本曲线，不代表文学质量或语义效果（那属于 G7b 与后续评阅）。
