---
id: T-20261017-director-scales-impl
title: 导演多尺度独立探索多批次实施
status: completed
created: 2026-10-17T19:30:00+08:00
updated: 2026-10-19T14:35:22+08:00
---

# 导演多尺度独立探索：多批次实施

## 恢复快照

- 2026-10-19 本轮已交付 [PR #263](https://github.com/FengHuoLinShan/ai-writing-assist/pull/263)：用户要求继续定位六项知识审查阻断与自主跨层失败，修实际缺陷、不放宽门禁，guimi隔离副本/Luna复测后审查提PR。分支 `codex/director-scales-followup`；源码提交 f3573945f 与 5583632f924f26dbbeb796df0adeacc75701e152，基线origin/main b4a42119a2c2a05552072669baaf99e31798d82c。未合并、未部署。
- 主证据：[M5-REMEDIATION.md](M5-REMEDIATION.md)、[M5-REMEDIATION-LEDGER.json](M5-REMEDIATION-LEDGER.json)；原M5报告/账本未改。r1/r2原文与运行环境留仓库外私有目录，原源库只读，临时任务库为62321。
- 修复：真实当前单元合同/可知包参与审查；自身候选与安全摘录返修；Goal显式直接依赖；候选空投影在scope前省略而保留全部有内容/知识/控制包门禁；新生成归一化无解，旧持久结果与移交指纹原样；条件规划提示不再把可通过合法行动建立的前提直接判为永久无解。
- 最终冻结 r2 hash ca7ef4fc6be20e1307d43cd88b2d0a169293d6c84724df9c760524616cfeec62，运行中无代码漂移。同17定义逐字段相等；最终六原例及真无解控制均完成，37次正常原生返回。两个人物例保留首审阻断及一次返修。
- 跨层r1一次规划七步完成，批准前停止完成；r1单层与r2跨层分别遇一次完整不合合同响应，均取消、未重规划/重发。r2真实原文回放确认内层JSON格式错，合法对照通过，无适配器实现缺陷证据。r1失败原文缺失是局限，22,969 tokens按产品持久预算核对，原观察unknown记录保留。
- 两波91物理请求：89正常、2完整不合合同，已知1,293,168 tokens；无在途、无未知重发、provider/model漂移0，货币费用未知。源153表及副本受保护表无变化，120稿完整指纹保持；15人物请求所选canary/越界包键命中0，非完整语义证明。
- 最终源码test-ci：后端9691/85.52%、前端3406、部署324、桌面47通过；定向Story124、专用PG10通过。Standards的P2旧指纹问题已修复并复核，Spec与最终增量审查均无剩余工程阻断。远端检查以PR当前固定head为准。
- 诊断误带出临时库凭据已说明；全部在途结束后完成轮换并验证旧凭据失效、新凭据可用；原源库未变。私有当前配置在r2/environment-current.json，历史旧配置凭据已失效。不读取/输出凭据值。
- 独立教师、真实作者认可、净收益与Goal格式可靠性仍未验收；功能默认关闭、ADR0042仍Proposed。任务完成指缺陷修复、保留失败、工程审查及PR交付，不是质量/生产验收。
- 若继续：先读PR当前head/检查与本报告；合并、部署或开放功能需对应新授权/质量门禁，不重跑已终结案例掩盖失败。

### 前轮M5诊断快照（历史，后续以上为准）

- 本轮目标：用户 `/goal` 授权完成后续任务，实测用 guimi 项目内 Luna，纯 Luna 不设费用上限，长任务并行。另明确选择 G7b v3 evolution（06f08dc3…）隔离副本，并允许向“能力审计第三批与诡秘 v3 验收”发送数据库使用范围；两次确认均已执行，不重复询问。不授权生产发布、作者招募或恢复封存评测。
- 工作树：`.worktrees/director-scales-impl`，分支 `codex/director-scales-followup`，基线 `origin/main@b4a42119a2c2a05552072669baaf99e31798d82c`；本轮全部修改尚未提交。根目录地图 WIP 保留。PR255 已合入 `404f597c1100280564812eb73d47794e1852d7b0`，本轮不依赖其旧未合并状态。
- 实际证据主入口：[M5-RESULTS.md](M5-RESULTS.md)、[M5-LEDGER.json](M5-LEDGER.json)（已定稿）。原始请求、输出、备份、脚本与环境在仓库外 `/Users/tywww/.codex/private/director-scales-m5-20261019`，不复制入仓库。
- 源容器 `guimi60-v3-pg-20261015` / 65197 只读；任务容器 `director-scales-m5-pg-20261019` / 62321，模型库 `director_scales_guimi_test`、工程库 `director_scales_e2e_test`。owner 连接正常验证，Project facade/snapshot 核验 Codex/gpt-6-luna/max。只领取本任务精确 task_id，不启动全局 worker。
- 并行：固定独立案例组4、派生组2，账户原生池8/RPM0；Goal 因同项目单活约束顺序运行。两个工程子代理均不接触真实库/业务模型。没有金额上限，领域请求/时间/预算/未知保护保持。
- 修复并保留反例：同项目锁升级死锁；导演删必需任务包；语义失败被软预算分类掩盖；包封预留4k不足；full author_goal 丢失；无解空路径校验；继承模型伪报DS。新预算v2保留32k包封，旧根v1继续原账本与额度；Goal最大token改5m、默认不变。
- 固定17例均终结：11完成、6被产品自身Luna知识审查阻断；六向移交4完成、2阻断。双人两轮完整排演18次settled请求。guimi真实首Scene锚点完成（4项资产/5项来源）；其余固定例为同隔离项目内的合成临时起点，不冒充全书验收。
- 反事实比较与detail完成；不支持单独改附带action（409且零模型调用）；event局部修订5次settled后被审查阻断，父结果及锁定项保持。缺少已确认空间材料的尺寸假设没有得到正向支持，预登记 supported_geometry=false，不能宣称物理可行性通过。
- 记录器失误保留：final-v1跨案例哈希误判在进入原生provider前阻断一例；final-v2限定同case，复用已settled结果，未重发未知原生请求。冻结/active检查等私有脚本错误均发生在调用前，单列，不计为模型失败。
- Goal版本：原跨层规划失败后取消；补项目UUID/结果字段说明后，final-v3真实7步计划完成前6步，第7步漏target_ref，未建立任务/未调用模型，保守保留未知领域回执后取消；限定单层发现目录漏选前置依赖。final-v4补目录依赖提示与执行前目标校验：单层三步全部完成；跨层模型计划漏声明直接依赖，规划校验拒绝，未执行领域步骤且已取消。final-v3批准前取消实测通过。旧未知步骤未恢复或重发。
- 最后补丁：prepare与REST共用目标resolver，目标/intent/确认起点尺度焦点/预算hash错误统一在副作用前拒绝；避免已知错误误记未知回执。7项目标拒绝与5项确认/预算拒绝先红后绿，7种合法模式保留。最终补丁只追加工程回归，模型结果仍按各自冻结版本判断。
- 最终工程：组合396 passed（含目录快照14项）、基础设施LLM496 passed/2 deselected、PG生命周期/迁移/并发10 passed、浏览器8、Goal Vue17；Ruff、ESLint、secret-hygiene、diff-check、普通docs-check通过。BASE_REF影响复核按既有no-change-reason机制注明两份架构流程文档无当前影响后通过。未运行本轮全量test-ci/远端CI。
- 请求终检160次全部settled（含2次连接健康验证），provider/model/effort漂移0，已知token2,215,281，实际货币费用未知。源库153表终检全等，副本受保护表无变化，120份稿件完整指纹保持；16个人物生成请求私密canary命中0。锁定失败修订仅留下原结果及锁元数据，无可用新修订。上述机械检查不代替完整知识质量评审。
- 三轨结论：工程与当前模型诊断单列；无匹配旧路径质量比较、独立教师、真实作者认可、阅读修正时间或净收益证据。默认关闭不变，ADR0042仍Proposed。M5退出条件是范围、失败与开放决定可审查，不能宣称质量/作者/生产验收完成。

- 2026-10-18 深审追加发现 5 项：Goal 失败账本回退、历史编辑绕过锁、Scene 缺父版本 CAS、
  取消后领域检查点不可恢复、沙盘受影响者字段不匹配。用户要求“修复，然后 pr”。
- 五项已修，追加 PostgreSQL 根/分支外键排序和截止后历史费用结算修复；沿用主实施工作树 codex/director-scales-impl；修复提交 a12c80169。
  原 26 项修复的未提交成果保留并纳入本次 PR；修改前补丁与 3 个未跟踪文件备份在
  /private/tmp/director-before-review-fix.patch 与 director-before-review-untracked.tgz。
- 阶段证据：完整 test-ci 通过（后端 9505/85.48%，前端 3335，部署 324），专用 PG critical 112 项通过。
  最终后端全量 9508 passed / 2 skipped，覆盖率 85.48%；详细证据见 REVIEW-FIXES.md。
- 已提交推送并创建 [PR #255](https://github.com/FengHuoLinShan/ai-writing-assist/pull/255)；固定修复提交 a12c80169 的 repo-gates/docs-check 通过，与 origin/main 083843474 可无冲突合并。
- 2026-10-19：用户授权整理合并，PR #255最终head8691ab9cf全部必需检查通过后普通合入main，merge404f597c1100280564812eb73d47794e1852d7b0；最新修复见REVIEW-FIXES.md及T-20261019-worktree-housekeeping。
- 上轮结束时第五批仅离线；本轮用户已新增上述隔离 guimi / Luna 实测授权。真实作者招募与生产发布未授权；ADR-0042 仍 Proposed。
- 上轮工程证据保留在 REVIEW-FIXES.md；上轮“未见剩余缺陷”已被本轮反例推翻。

此前实施批次及 4778e40c8 等提交仅为工程历史；审查发现的旧设计偏差已由本轮整改替换。

## 目标与授权

- 用户指令（2026-10-17）：“并行执行 codex/director-scales-plan 中的多批次计划”，视为实施授权。
- 依据计划：`docs/plans/2026-10-17-director-scales-independent-exploration.md`（Draft）与 ADR-0042（Proposed）。
- 原实施授权：第一批 P0–P4 全量，第二/三/四批按依赖推进；原第五批仅离线准备。
  2026-10-19 新授权覆盖隔离 guimi/Luna 实测；作者招募、生产开启、部署及封存评测仍不在范围内。
- 前置规划任务：[T-20261017-director-layer-design](../T-20261017-director-layer-design/TASK.md)（completed）。

## 工作区

- 主实施区：`/Users/tywww/项目/ai-writing-assist/.worktrees/director-scales-impl`，
  当前分支 `codex/director-scales-followup`，基线 origin/main `b4a42119a2c2a05552072669baaf99e31798d82c`。旧实施分支与提交仅为历史。
- 原规划参考树已清理；计划与契约保留在main及本任务目录，私有归档见T-20261019-worktree-housekeeping。
- 并行代理按独立 worktree/分支规则工作；主区负责集成与验证。

## 批次与并行结构（依赖序）

- Wave0：三探索（Evidence / Story / Assistant+前端）并行 → P0 契约冻结（P0-CONTRACTS.md）。
- Wave1 P1：Evidence 新起点确认 + Story 两类根/历史 + Alembic（契约冻结后分 Evidence/Story 并行）。
- Wave2 P2：B1+B2 世界推进链 / B3 导演链并行。
- Wave3 P3：助手操作目录与前端结果闭环并行。
- Wave4 P4：兼容回归 + 文档 + 门禁。
- 第二批起按计划依赖顺序，跨批并行仅限设计/准备类只读工作。

## 决策、发现与失败

- 2026-10-17：规划分支 `codex/director-scales-plan` 无领先提交（完全包含于 main），实施改从
  origin/main 新建分支；计划文档已在 main。
- 实施不放松：novel_id 隔离、owner 校验、Evidence confirmation 重物化、预算/幂等、不可变触发器。
- P0 关键裁定（细节见 P0-CONTRACTS.md）：紧凑输出复用两类既有根/分支/结果表 + `output_kind`
  判别联合（不新建表/模块）；两根表加 `source_kind` 列并放开 scene_id 非空（CHECK 限定仅
  provisional 可空）；Evidence 新增 `ExplorationContextRequest` 与三项能力注册，重物化跳过
  Scene/大纲指纹门但保留核心指纹；隐藏守卫仅覆盖 canonical 引用，临时主体以声明知识包为边界；
  联网仅冻结助手当轮已读快照，worker 不做实时检索；操作目录六项、runtime_version 17→18；
  gate `STORY_EXPLORATION_ENABLED` 默认关，history/compare 关闭可读。

## 验证证据

- 2026-10-17：基线 origin/main 与本地 main 6004d3703 一致；各批实施历史见 Git 与同目录契约材料。
- 2026-10-18：整改完成后的完整门禁、逐项回归映射、未验范围及本地日志见 [REVIEW-FIXES.md](REVIEW-FIXES.md)。
- 最终离线通过不构成 ADR 采纳、作者确认、真实模型效果、生产可用性或远端交付证明。

## 前轮交付时状态（历史）

- 本轮授权工作已完成：工程缺陷修复、隔离 Luna 诊断、全部失败和版本账本、三轨证据报告及默认关闭决定。M5退出条件按“证据范围、失败、未验证项和开放清单可审查”核对完成；不把报告完成等同独立质量、作者或生产验收通过。
- 修改仍在本地，未提交、未推送、未创建新PR、未部署；保留工作树和私有证据供审阅，任务专用数据库不再写入。若后续要求开放能力，先补相应独立质量/作者门禁；本轮不自动招募、不恢复封存教师评测。

本轮后续已完成并交付PR #263；全部冻结请求、失败与数据终检见恢复快照和M5-REMEDIATION。禁止自动合并或部署。
