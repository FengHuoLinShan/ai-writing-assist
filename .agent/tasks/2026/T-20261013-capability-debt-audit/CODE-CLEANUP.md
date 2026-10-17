# 当前代码清理与过时逻辑分类账

基线与方法见 [REPORT.md](REPORT.md)。本账是后续开发依据，不包含删除或破坏性操作的执行授权。本轮没有删任何业务代码、测试、数据、worktree、设计稿或付费证据。

“词法零引用”只对本仓库 tracked 内容成立，不能证明外部插件、历史数据库负载和动态注册不存在。“测试唯一消费者”也不自动意味着可删：公开契约、候选领域能力和历史恢复须先裁定。分类为：可小批清理、需退役合同、实测后优化、在用/保留、历史已修或待复核。

## 1. 证据充分的小批候选

以下四函数由 Python AST 确定定义范围，并扫描全部 tracked 源码、测试、文档、配置词法引用；名称均只有定义一次，未见装饰器注册。动态名字拼接/仓库外调用尚无证据，实施前再次确认。合计定义范围 **54 行**，不是精确最终净删行数。

| ID | 当前位置与内容 | 影响与最小方案 | 验证与回退 |
|---|---|---|---|
| C01 | `backend/modules/imports/phase2_world_extraction.py:1035`–:1049 `_scene_source_fingerprint` | 15 行、没有消费者；只删函数，先确认 hash helper 的其它消费者再处理 import | Imports Phase2/Scene tests、ruff、全仓引用核对；单独 revert |
| C02 | `backend/modules/imports/spreadsheet_migration/planning.py:298`–:311 `_accepted_ai_coverage` | 14 行、无消费者；不改变表格预览、授权 coverage 和 apply 冲突合同 | spreadsheet migration tests，尤其 stale preview/冲突不写入/回执；单独 revert |
| C03 | `backend/modules/imports/workflow_llm_adapters.py:55`–:66 `_phase0_scene_max_tokens` | 12 行、旧 Phase0 配置壳；只删未调用函数 | Phase0/Scene 真实注册调用点与 env 配置检索、Imports adapter tests；单独 revert |
| C04 | 同文件 :69–:81 `_phase0_scene_timeout_seconds`；:36–:37 两 Phase0 默认常量 | 13 行函数；两个常量只由 C03/C04 引用。删旧路径，不改在用 Phase1/2 timeout 或 author override | 同 C03；保留冻结运行的当前超时语义；一簇 revert |

本轮只确认这四项为高置信私有函数候选，不宣称整个代码库仅有四个死函数；public/method/schema 的引用证明需要不同方法。

## 2. 旧实现簇：先明确退役与兼容

### C05：window Phase2 World 抽取及私有 adapter

- **位置。** `imports/phase2_world_extraction.py` 的 `Phase2WorldExtractor.run` :110、`_run_windows` :288 及 window 专用辅助；`workflow_llm_adapters.py:1174` 的 `_Phase2WorldExtractionLLM`。主文件 1321 行，但不能全部计为可删除量。
- **当前证据。** 生产 tracked Python 中类仅定义，README 说明继承；实例化出现在 `test_workflow.py`，adapter 在 `test_scene_phase_refactor.py`；当前 workflow entity stage 使用按 Scene 抽取。`existing_checkpoints` 入参接受后丢弃，window 与 Scene 双合同仍保留。
- **影响。** 一个测试能跑通的 window 实现容易被误认为主导入具备该能力；对应 schema/Prompt/转换又可能由 eval/probe 独立使用。
- **方案。** 先确定是否作为冻结试验保留；若退役，删 run/window 专属簇和私有 adapter，保留独立使用的 `_to_delta_event`/schema 等转换面。不要整文件或整 Prompt 目录直接删除。
- **验收/回退。** 用完整 Imports/Prompt contracts/Evolution World 测试证明在用 Scene 路径不变；检查 eval/probe、README 和外部 seam；逐簇 revert，不迁移真实数据。

### C06：本机文本 Agent 退役尾巴

- **位置。** `local_agent/client.py` 的 LocalCLIClient、`runtime.py` 的文本 runner、`executor_service.py:69` 的 task_snapshot_client `_local_agent` 分支、`companion.py:222` 文本 job/shim，以及 Story rehearsal、Interaction task/proactive、Assistant forecast、Collaboration runtime 的旧分支。
- **证据。** Project `llm_runtime.py:208` 明确拒绝含 local_agent 的文本 snapshot。Local Agent README 已限定图片；根 README :79/:106/:130、Interaction README :331 起仍声明文字 Agent。正常入口与旧执行链不一致。
- **方案。** 先修错误能力文档；确认历史 pending/failed job 和 device API 的处置，再缩文本 schema/客户端/companion 分支。新 Codex text provider 属另一运行时，不应靠复活旧文本装置替代。
- **风险。** 图片设备配对、图片授权/存储、历史 receipts 与 UI 状态共用模块。全部删 local_agent 会破坏仍活跃能力。
- **验收/回退。** 新文本配置不能走旧分支；旧请求得到可解释终态、历史可读取；图片正常/拒绝/取消/重复批准/owner 隔离测试与浏览器走查；按层 revert。

### C07：旧 bundle Markdown renderer

- **位置。** `evidence/compilation/markdown_renderer.py:54` `render_context_markdown` 及一组 `_render_*`、facade 和 `__init__` 导出。
- **证据。** 全仓正常生产引用只有定义、包装和公开导出；确认动作、生成背景和 API 使用 `render_compiled_context`。StructureContextBundle 的加载/规划/Story 自有渲染仍活跃，不能随旧 renderer 删除。
- **方案。** 核对公开 surface 和外部工具，再删除仅旧 renderer 使用的 helper/数据及只验证旧路径的测试；保留共享转义、compiled renderer 和 bundle 编译。旧“约 600 行可删”不能作为当前承诺。
- **验收/回退。** Evidence compilation、Story generation、Writing confirmation 与角色知识边界测试；同一 compiled 输出/hash 不变；契约缩面单独回退。

### C08：legacy GET activation-preview

- **位置。** `evidence/compilation/api.py:697` GET 与 :723 POST；前端 `api/context.js:85` 用 POST。
- **证据。** 旧 GET 仍注册并有兼容守卫测试，前端零调用不等于所有 API 客户端零调用。
- **方案。** 独立标注兼容状态、收集调用证据，决定弃用期限或继续窄维护；不直接当死函数删除。POST 为活入口。
- **验收/回退。** HTTP project/owner 隔离、GET 兼容和 POST 本体契约；路由恢复可 revert，不新增绕过检查。

### C09：Evolution legacy adapter 的提前弃用话术

- **位置。** `evolution/legacy_adapter.py`，`adapt_deep_import_start`、DEPRECATION_NOTICE。
- **证据。** mapper 本身有测试；旧 deep-import 入口尚未接入它，模块 docstring 明确 canary 之后才重定向。notice 却说“请求将改由…执行/不再拥有独立所有权”。
- **方案。** 先将状态写明为未启用 adapter；若保留未来迁移，标冻结能力；若决定退役独立编排，连旧运行恢复/授权/预算/新回执语义一起迁，不能凭参数映射宣布完成。
- **验收/回退。** 新旧开始、历史恢复、取消和 unknown receipt 不重放；每一入口合同分别验收；按入口切换回退。

### C10：评测模型和教师合同过时

- **位置。** `evals/ask_world.py:37` teacher 固定 Sol；`evals/cli.py:151` 起 review-model 旧 choices、scene-gold-repair 旧 Spark 默认与 fallback，:1966 附近旧 executor；Makefile :121/:124 旧 Codex5.3说明。
- **证据。** 与当前业务开发/教师 Luna/max 约定不一致，testing-guide 已暂停对应实测。
- **方案。** 区分脚本工具工程宿主、SUT 和评测教师；先校准 Luna，再更新 CLI/config/schema 与 holdout 元数据。不能批量替换模型名后混用历史分数。
- **验收/回退。** 离线配置/拒绝不符模型/无回退测试；真实模型校准另按授权；冻结数据版本和旧报告解释；回退代码时不能抹去已发生费用。

### C11：失效说明旧于真实登记面

- **位置。** `evolution/invalidation.py:15` 附近 docstring 仍把 world 知识、助手建议写作未接线；实际 :57 UNSUPPORTED_CONSUMERS 仅地图/正典。
- **方案。** 同步说明至当前 constants/registry，并显式描述尚未登记的消费者；不要为消警告删 constants。
- **验收/回退。** 文档门禁和 registry 反例；说明可独立回退。属于文档漂移，不据此推断实际所有消费者失效错误。

### C12：文稿 MOBI/AZW3 声明需保持受限

- **位置。** Imports 文稿 whitelist/README 与 AGENTS 格式约束。
- **证据。** 枚举存在，锁定运行时依赖及真实文件验收未闭环。前端已只展示前四类验证格式。
- **方案。** 保持“尚未验证”说明；若正式支持，补依赖、真实合法文件和大小/内容反例；若去掉枚举需考虑 API 兼容。不要把 `.xlsx/.csv` 加入文稿上传。
- **验收/回退。** 文稿真实格式解析与恶意压缩/签名测试，表格独立确认合同；可回退格式入口，保留导入记录。

## 3. 重复/性能/结构：收益未测，不先做大重构

| ID | 位置与证据 | 建议最小处理 | 必需验证与风险 |
|---|---|---|---|
| C13 | `evolution/invalidation.py:149`–:164 与 `writing/recompute.py:103`–:119 `_scene_chapter_indices` AST body 相同（含 docstring 差别） | 下次改章绑定时评估已有 Story seam；不要跨模块引用私有 helper 或为了 16 行新增万能 shared | 跨章/混合 chapter_ids/ref/空值语义完全一致；Writing+Evolution 回归；独立 revert |
| C14 | `frontend-console/styles.css` PostCSS 55 组同 selector/declaration/祖先作用域，290 行重复上界 | [CSS-DUPLICATES.csv](CSS-DUPLICATES.csv) 按组检查中间 cascade，保留最终有效规则；不自动去重 | 世界书/世界抽取/设置桌面与窄屏等价；共享多选择器只删确认无用部分；逐簇 revert |
| C15 | `evidence/indexing/index_state.py:723/:755` 全 ORM 载入再 Python total/fresh/stale | 先长章节规模查询/内存基线；SQL aggregate 严格保持 nullable/status/hash 语义 | 同状态集计数完全相同、novel隔离、范围过滤；实际改善才合入 |
| C16 | `evidence/compilation/services/import_activation.py` 宽世界资料/词项读取，逐 Scene 准备 | 先量化对象数/aliases/SQL；按来源/可见性过滤、请求内缓存，不跳回读 | 不带入被排除对象、后续事实或旧 revision；修改后冷/热、漂移反例 |
| C17 | Writing services 4554、Interaction services 3287、Scene workbench 3081 行 | 下一次真实生命周期修改按职责拆，保持稳定 facade；不全面机械拆文件 | 原正常/失败链和事务锁不变，相关模块门禁；按领域职责 revert |
| C18 | 多处 hash/request/snapshot 序列化与字段读集 | 同域收敛、跨域先证明 byte 等价；优先已有权威 helper | 保存旧值 golden/读取历史冻结记录；禁止修改 whitespace/order/Unicode/default 造成 fingerprint 漂移 |
| C19 | `Makefile eval-technical-coverage` 固定3.13并共用backend/.venv，本次实际替换3.14环境 | 每目标独立 UV_PROJECT_ENVIRONMENT 或专用实验 venv | 工程目标/实验并行互不删依赖；恢复默认解释器；不因本次环境错误造产品bug |
| C20 | API命名空间、hash router/bridge、若干旧 non-module script，构建成功 | 它们有当前消费者/资源发布合同，按真实迁移逐步收缩 | 16 routes资源发布与桥接、浏览器功能；不能仅因Vite提示删除script |

C14 样例：world-bible-template-actions :11853–:11863 / :12536–:12546；world-bible-sections :11904–:11913 / :12567–:12576；world-hot-overview :11601–:11609 / :12239–:12247；world-extract input :9708–:9715 / :11311–:11318。完整 55 组已列 CSV；同规则重复不证明相隔位置可以互换。

## 4. 未完成能力与运维风险，不当死代码

| ID | 项目 | 当前事实/保留理由 | 后续决定与验收 |
|---|---|---|---|
| C21 | formal authority families | 五族 formal-disabled；AssertBatch拒绝未支持kind；Canon页面仍活跃 | 若有明确作者价值，先一个族 accepted spec/冲突/采用/回退；否则冻结并如实说明 |
| C22 | 地图/正典消费者 | 明确未进入统一失效账本，不是未引用即可删的常量 | 补真实read-set与来源登记；改地图/正典、后文边界和保守扩张反例 |
| C23 | Assistant/forecast/guided/research等蓝图 | 实现存在，多开关默认关闭；实验不等于无用 | 按真实作者任务决定开放/冻结；单蓝图质量/预算/恢复证据，不自由开放工具 |
| C24 | MinIO数据备份 | 生产单盘，两bucket无外部图片备份；是已接受风险 | 补备份与隔离恢复；成本/生产操作授权单独处理；不能以DB备份覆盖图片 |
| C25 | forwarded-allow-ips=* | Dockerfile仍保留；历史任务因生产拓扑未知明确暂缓 | 取得代理peer/可达边界证据再改；本次未访问生产，不宣称已可绕过 |
| C26 | night E2E旧断言与复用证明 | 两项在本轮隔离PG复现；见REPORT3.1/3.2 | 按语义修复，保留反例；不削弱断言/伪造调用数来过检 |
| C27 | 正文首次保存影响提示、编辑台资料排除输入 | 无相关资产仍提示地图/正典；排除项示例chapter:12 | 限定实际适用状态、提供章节选择；不能隐藏真实失效或改变排除语义 |

## 5. 已修/误报/仍在用：禁止重复清理

下列是对历史高价值候选的当前复核，不是依赖旧任务“已完成”标签直接认可：

| 历史项 | 当前核验 | 判断 |
|---|---|---|
| F4-1/E1-3 测试扫venv | task identity测试用production_python_files；本次fast快速完成 | 已修，不重复立项 |
| E1-1/E1-2 账号偏好/eval测试漏CI | 当前testpaths含两目录，本次全量执行 | 已修 |
| F1-1 枚举14/17死 | shared/enums当前3个在用值域 | 旧规模失效 |
| F1-2 parse_llm_json/is_valid_uuid | shared/utils无旧函数 | 已修 |
| D5a-1 prompt硬编码旧作品/内部评测名 | 当前抽取相关生产代码未见原特判 | 已修；不引入旧语料复测 |
| D5a-2 千行scene_fusion旧reducer | 文件已成共享candidate schema，多个生产consumer | 旧reducer已去；文件在用 |
| D5b-1 failed显式恢复窄窗口 | orchestrator重新入队带恢复语义 | 旧问题不直接重报 |
| D6a-1 旧query expansion复制函数 | `_expand_query_with_project_terms`已不存在；QueryExpander活跃 | 已修；不可删全部检索扩展 |
| A8-1 bulkSelection DOM renderer | 当前只保留在用状态/动作helper | 已修；活helper保留 |
| D8c-3 settings LlmFormFields/llmForm | 旧组件/logic路径消失 | 已修 |
| D8a-1 账户草稿prefix缺失 | 当前accountStorage登记各类草稿prefix | 已修 |
| AO-13 巨型api.js | 当前约71行namespace组装，实际API已分域 | 已修，不再当2000行大文件 |
| A5-4/A5-5 同步正文/冲突双轨 | 当前同步候选函数与旧同步AI路线已退役，生产走任务轨 | 不重复删除在用任务接口；本轮未做真实模型验收 |
| F5-1/F6-3 backend/backend日志 | tracked路径清单已无旧目录 | 已修；不执行旧rm命令 |
| F6-2 空格coverage副本 | tracked清单已无对象 | 已修 |
| B1c 第三方原文样本 | 当前合成样本与分类账已替代旧样本 | 不能把付费原始证据顺带删 |
| AO-15 容器加固“未实施” | 当前Docker USER app/nginx、Compose read_only/cap_drop/no-newprivileges | 代码已有；本轮没做新生产部署/镜像恢复 |
| #209 freshness分页 | 本轮PG规模1/10/100 Scene，warm查询5、分页有界128 | 已实现，本次验证；Issue仍开不代表功能缺失 |
| deep_import被Evolution替代 | legacy adapter未接旧入口，deep_import仍生产使用 | 未替代，必须保留 |
| 旧RAG chunks“重复垃圾” | ADR-0018需要历史来源revision检索 | 必须保留，默认/显式版本检索分开 |
| tools/deepseek_scene_probe/验收脚本 | 含正式设计依据与既有证据 | 历史工具不因零import而无用；不运行付费probe |
| frontend-console/docs、设计探索 | tracked且有资料/设计用途 | 不作递归删除候选 |
| “只要import少就可删facade” | 公开契约、DI、API调用并非局部符号频数能证明 | 逐符号/模块路径/注册/外部合同查证 |

World review、检索planner、private facade、测试假断言等历史其它条目没有足够本轮现况证据时，保留在机器账本并标 `historical_not_revalidated`。它们不是当前确认的问题，也不冒充“全部已修”。

## 6. 历史目录、工具证据和工作树

- **C28：旧清理命令。** `.agent/tasks/code-simplification-audit.md` 的 Wave0 `rm-rf` 是2026-09-10历史候选，后来已多次纠偏。不得复制执行。其严重误报包括 deep_import真实验收工具、deepseek_scene_probe、frontend-console/docs和实质设计稿。
- **C29：付费/原生证据。** B1c分类账保留239份历史真实模型证据及设计探索，当前数量可能变动。既有唯一回执、unknown费用、版权原文/用户数据须按受控政策留仓库外或最小脱敏摘要；本任务没有移动、上传或删除它们，也没有读取未跟踪secret配置。
- **C30：.superpowers/.claude 等。** 初始tracked清单仍有20个HTML设计稿及Claude配置/前端docs。它们是档案或工具配置，不是生产死代码；未完成设计吸收/唯一性分类前保留，不能直接rm整个隐藏目录。
- **C31：20个worktree。** ancestor仅证明提交历史包含，不证明未提交内容无用。3个Codex相关树含生产WIP；其它清洁树也只能列归档候选，需确认所有权/受保护数据并先快照。本次不操作。
- **C32：旧审计规模与标题。** 历史“241问题”“700+1400行”“CSS780行”不是当前事实，本文只按现行代码出判断。机器账本保留显式ID提及及原始位置，不作当前问题数。

[HISTORICAL-CANDIDATES.csv](HISTORICAL-CANDIDATES.csv) 收录旧units中的标题/表格ID、历史描述、来源、当前复核状态与证据；356行/301唯一ID含cross-ref与重复，不能和历史241去重口径相加或相减。状态字段可用于后续按目标模块重新复核，不授权批量执行。

## 7. 建议清理次序

1. 先修 C10/C11/C06 的能力说明及 C26 的夜间门禁；这些影响后续开发判断。
2. 一小批只做 C01–C04；删对应 import/常量前确认仍有其它消费者，验证后停止扩圈。
3. 与 Codex集成同步裁定 C06；单独裁定 C05/C07/C08 的兼容退役。
4. 在真实性能/维护任务中处理 C13–C19；每个收益独立量化，不拿总行数作为重构目标。
5. C21–C25/C28–C31 走产品、存储或档案的独立决定；无权限或证据不删除、不冒称已实现。

所有回退以独立代码变更/revert为原则；本轮没有创建这些实现提交。数据迁移、历史回执、真实费用和公开契约的回退不能只用Git恢复来保证。

更早简化审计的全部可识别 ID 引用见 [OLD-AUDIT-REFERENCES.csv](OLD-AUDIT-REFERENCES.csv)。其命名空间与后续 unit 独立，ID 相同不代表同一问题；保留历史原文位置不代表今天仍成立。
