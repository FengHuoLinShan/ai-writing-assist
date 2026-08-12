# R01–R14 脱敏回放夹具（replay-v1）

本目录保存 14 个脱敏作者流程回放夹具（R01–R14），覆盖「恢复创作、作者改目标、
候选山收口、选择性采用、语义漂移、外部交接回流、视觉候选、校验节奏与停止、
作者纠错修订、邻接探索回查、正典变更影响预演、最低充分深度、Scene 认知预演、
Scene 时点可证状态」。夹具把真实创作史中的状态转换（候选→采用、目标修订→冲突、
外部来源→建议）保留为合成短句与事件序列，供离线回放与人工诊断。

## 定位声明：夹具不驱动 pytest

- 夹具是纯数据层。除结构守卫测试
  `backend/evals/tests/test_replay_fixtures.py`（由 `make eval-fast` 运行）外，
  本目录的 JSON 不被任何测试、runner 或 EvalSuite 消费。
- 本包不新增 `make eval-*` 命令，不建 runner，不建 EvalSuite，不改产品代码与
  现有测试文件。
- `assertion_map` 只是人工维护的落点索引，标明每个回放对应的确定性合同测试
  （pytest / vitest）与人工判断项；守卫测试不解析、不执行这些引用（防脆）。

## 脱敏规则与 blocklist

- 不出现 Vault 专名、人物绰号、核心概念词、私人路径、会话原文与真实项目 ID；
  `novel_id` 一律为不透明值 `novel-replay`。
- 全部内容使用与 `ask-world` 数据集共享的合成世界短句（北境港、南岸果园、
  灰河桥、西岭驿站、白塔议会、旧塔铜铃、潮汐行会、黎明道路重排等），不复制
  Vault 年表、三时序或历史制度。
- blocklist 由 `backend/evals/tests/test_replay_fixtures.py` 的 `FORBIDDEN_TERMS`
  常量维护（含 Vault 地标与组织专名、人物绰号、核心概念词、本机绝对路径前缀），
  README 不重复列出专名原文；对 `replays/` 目录内全部 `.json` / `.md` 文件做
  全目录扫描，任何新增文件都必须通过。
- 所有夹具为单文件合法 JSON（不是 JSONL），UTF-8 无 BOM，不含控制字符。

## 字段语义表

| 字段 | 语义 |
|---|---|
| `schema_version` | 固定 `replay-v1` |
| `scenario_id` | `rNN-<kebab-slug>`；全局唯一，且前缀与文件名一致（如 `r01-resume`） |
| `novel_id` | 一律 `novel-replay`（不透明值，不得出现真实项目 ID） |
| `tier` | R01–R14 全部为 `deterministic`；B 层模型/人工判断以 `assertion_map` 的 `manual` 条目表达，不单独建 `model_diagnostic` 文件 |
| `initial_state_refs` | 合成初始资产：`kind ∈ page/object/manuscript/suggestion/draft/checkpoint/character/knowledge`；`state ∈ current/superseded/pending/candidate`；`visibility ∈ author/reader/role` |
| `content_digest` | 真实 sha256 十六进制，或由 `source_manifest_rule.digest_derivation` 推导的表达式 `sha256('novel-replay:' + ref_id + ':' + synthetic_title)`；守卫测试验证推导公式可复算 |
| `source_manifest_rule` | 批量源声明（不逐条铺开）：`counted_ids`（R03 的 180 项候选）与 `packets`（R06 的 5 份回包）两种 kind |
| `author_events` | 按序作者动作，`seq` 从 1 连续递增；`action` 为产品动作名 |
| `expected_read_model` | 机器可查的期望读模型合同；每个 R 覆盖其「补的空档」 |
| `forbidden_outcomes` | 人审清单（≥1 条）；由参考计划的「禁止结果」列改写为合成世界版本 |
| `metrics` | 3–6 个 `[a-z_]+` 键，值只允许数字/布尔/短字符串 |
| `assertion_map` | 每条恰有 `pytest` 或 `manual` 之一；`pytest` 引用必须真实存在，前端 vitest 引用到具体 `it(...)` 描述 |

## 14 个夹具一览

| 文件 | scenario_id | tier | 补的空档 | 断言落点 |
|---|---|---|---|---|
| r01-resume.json | r01-resume | deterministic | 恢复≠重放（导航 LLM 调用为零）；指针只由作者明确动作更新 | `test_workspace_summary.py`；generateSession / GenerateView / todayIsland / WorldBibleTab 前端测试 |
| r02-retarget.json | r02-retarget | deterministic | 页面提案 decision_state 持久化；作者层表述不泄露角色层；world 不写 outline | `test_world_generation_center_api.py` 多轮生成与知识表达边界；`test_story_outline.py`；manual：知识层级 |
| r03-convergence.json | r03-convergence | deterministic | 乱序固定分块覆盖不变；缺失+stale+超限组合 fail-closed；预览/选择/恢复三阶段零写入 | converge 系列（含 180 固定分块、缺失 fail closed、单超时、选择消息）；manual：双人归组评分 |
| r04-selective-adopt.json | r04-selective-adopt | deterministic | 留白不投影为事实；未选细账不增 pending；无「采用整组」主操作 | 选择消息编译；author-only 分区持久化与投影默认；manual：三分类 |
| r05-semantic-drift.json | r05-semantic-drift | deterministic | 未触发门槛/历史 stale/诊断状态不进当前待办 | 语义检修替换 stale 队列结果；top-k 不限制已选资产；WorldBibleTab 作者可读状态；manual：authority order 正反例 |
| r06-handoff-roundtrip.json | r06-handoff-roundtrip | deterministic | 精确重复 no-op；外部 ID 不映射；外部 checks_run 不冒充本地回执；每包 ≤55,000；超限请求前拒绝 | 外部回包五类回执与 hash 绑定；收敛后重校验来源；`test_context_compiler.py` 单会话序列化；GenerateView 超限与单包回流；manual：混淆矩阵 |
| r07-visual-candidates.json | r07-visual-candidates | deterministic | source-hash drift 只标复核；批准简报零写入；不建图片资产 | quick-create 候选只读与 confirm 资格；视觉修订 baseline；useMapQuickCreate 候选只读；manual：标签/泄漏核对 |
| r08-cadence-stop.json | r08-cadence-stop | deterministic | 取消后零 follower；scope/未运行项可见；不建通用轮次调度器 | tasks `test_api.py` cancel 隔离；`test_lifecycle.py` 取消、lease 冻结与 heartbeat 栅栏 |
| r09-author-revision.json | r09-author-revision | deterministic | 旧版退出待办+shadow 封存同事务；拒绝新版不复活旧版；另起方案不串线 | supersede 系列（核心对象、独立方向、CAS 回滚、页类型与 baseline 校验、source drift）；manual：纠错保留率 |
| r10-adjacent-explore.json | r10-adjacent-explore | deterministic | 深度=1；入口≤3；只执行所选一个；源修订建议≤1；停止后零续跑 | 一跳探索只读且只创建所选对；上下文漂移 fail closed；GenerateView 三缺口单选择；manual：入口相关性 |
| r11-impact-preview.json | r11-impact-preview | deterministic | 显式 affected set/路径/版本；scope drift 使旧预演失效；0 backlink 不显示无影响；预演零写入 | `test_world_bible_v2.py` 最短 backlink 与诚实空态；synopsis workspace 发布/确认 stale；WorldBibleTab 诚实空态与路径折叠 |
| r12-minimal-sufficient.json | r12-minimal-sufficient | deterministic | 首轮不问卷（最多一个问题）；一个锚点贯穿普通日/故障；明确大范围请求不被缩窄 | chat 只读与快照；纵切保留显式 scope；空文本重试；弃用 scene 前拒绝；manual：B 层分项（正/负/边界样本各 ≥1） |
| r13-character-knowledge.json | r13-character-knowledge | deterministic | 乱序第 1/3/5/6 章结果稳定；同章新发现不提前生效；管理动作 LLM 调用为零 | `test_character_knowledge_levels.py` 检查点决胜/传言过滤/冻结版本；`test_context_compiler.py` 误信隐藏真相/场景与认知分离/公开基线 |
| r14-scene-state.json | r14-scene-state | deterministic | current World fallback=0；未锚定对象不判为「当时不存在」；修复后下游重建+旧确认失效 | `test_scene_projection.py` 五维检查点/人工修复/重建失效；`test_context_compiler.py` 场景时点边界与未锚定摘要 |

## B 层人工诊断入口

- 模型质量与作者可用性判断复用现有 `make eval-review-export` /
  `make eval-review-import` 的 JSONL 审查包与双审一致性流程；本包不新增命令。
- 需要模型判断的场景（R02 目标修订与知识层级、R03 归组质量、R04 三分类、
  R05 authority order、R06 分流、R07 视觉核对、R09 纠错保留、R10 入口相关性、
  R12 最低充分）只作 diagnostic 回放，不冒充现有 `world` Pilot，不与
  RAG/抽取基线混分；judge 未校准前不得单独阻断或放行。
- R12 的 B 层样本说明：正/负/边界样本各至少一个（最低充分正例、问卷化负例、
  明确大范围请求边界例），分项标注首轮可用内容、问题数、无依据横向新增、
  锚点漂移、普通日与故障可观察性、作者下一步选择；不合成「世界观成熟度总分」。

## assertion_map 维护纪律

- 引用 `pytest` 前先读对应测试文件核实函数名（后端为 `test_xxx.py::test_name`，
  前端为 `test_xxx.js::it 描述`）；无法核实的用 `{"manual": "..."}` 表达，
  不编造测试名。
- 守卫测试只查结构（文件齐全、schema、scenario 唯一性、digest 可复算、事件
  序列、metrics 形状、blocklist），不解析 `assertion_map` 引用是否存在；
  该映射由本 README 人工维护，改动后需在此处同步。
