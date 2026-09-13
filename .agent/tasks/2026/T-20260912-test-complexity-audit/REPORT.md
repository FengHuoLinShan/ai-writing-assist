# 前端视觉与后端行为基线复杂度审计

审计日期：2026-09-12。代码基准：`eeeb32b40c44b22bd0fcaff3d25ddd83c22ad04a`，分支 `codex/minio-quay-registry`。仅新增审计材料，未修改产品、测试、CI、阈值或项目规则。

结论：存在明显过度约束。主要问题是把实现写法当成行为契约、把同一配置复制到测试，以及让低风险变化触发不相关的重型检查。不能据此认定所有严格测试都多余，也不能仅凭 85% 或 0.5% 两个数值断言阈值不合理。

## 范围与证据强度

对 Git 已跟踪的测试、支持文件和测试入口做全仓静态扫描，逐项深入核查下列热点。扫描包括后端 modules/infrastructure/evals/tests、前端 tests/e2e、deploy/tests、Makefile、六份 CI workflow、测试/开发指南和架构文档门禁。不包括未跟踪历史测试产物、外部平台分支保护设置或付费模型质量验收。

| 扫描对象 | 文件数 | 源码行数 |
| --- | ---: | ---: |
| 后端测试及支持文件 | 424 | 192,339 |
| 前端测试及支持文件 | 249 | 70,532 |
| 部署测试及支持文件 | 13 | 6,187 |
| 合计 | 686 | 269,058 |

[scan.csv](scan.csv) 记录每个文件的扫描覆盖与源码读取、AST、mock 调用断言、等待、Prompt 文本断言命中数。命中只用于筛选，**不是问题判定，也不是逐条业务验收**。本次没有逐行人工审查全部 26.9 万行，不能保证不存在遗漏；已对测试体系及下列复杂度来源完成全仓扫描和重点证据审查。

视觉基线共 95 张、8,075,983 字节，全部为 `darwin.png`：writing 21、experience 20、generate 13、project-rag 13、world 10、settings 9、outline 6、today 3。八个 visual spec 的配置、准备逻辑与截图调用均纳入检查；未逐张重新渲染图片。

当前执行边界：视觉回归不在自动 CI 必跑项中；前端 PR 跑四文件 smoke，main 跑 functional；PostgreSQL PR 跑 critical 子集，全套另有 nightly/manual。付费和真实语料测试已经分层，不能误报为每次提交都必须全跑。依据：`.github/workflows/frontend-ci.yml:153`、`.github/workflows/backend-postgresql-e2e.yml:3`、`testing-guide.md:95`。

## 已确认可精简：按预期减负优先级排列

以下是 18 个问题簇。每项都限定要削减的部分；同一文件里的安全、边界和有效行为断言不随之删除。建议不构成此次修改授权。

### A01 · shrink：CSS 正则把视觉实现逐句抄进测试

- 证据：`frontend-console/tests/editorialTheme.test.js:110`、`sceneWorkbenchSpacing.test.js:10`、`typographyTokens.test.js:19`、`uiSizeContracts.test.js:11`，四文件共 418 行；同类还见 `tests/vue/world/worldLibraryMobile.test.js:10`、`tests/rpReadingUx.test.js`、`tests/loadingSkeleton.test.js`。
- 锁定内容包括属性顺序、选择器拼接、精确间距、字距、250ms 动画、64fr 布局、旧类名是否存在。修改样式组织方式即可失败，且正则出现不证明浏览器最终样式生效。
- 已复现：从真实 `.outline-scene-layout > .outline-toolbar` 规则中只交换 `gap` 和 `padding` 的顺序，值完全不变，原断言由匹配变为不匹配。
- 最小替代：删除装饰性数值和源码顺序断言；少量真实浏览器检查保留“不溢出、可聚焦、点击目标足够大、文本对比度可读”。已有截图覆盖风格变化；不用再为每个 CSS 修复增加一份正则快照。

### A02 · shrink：纯转发 facade 的测试重复模拟服务行为

- 证据：`backend/tests/unit/test_character_facade.py:1` 共 681 行，自述被测对象为 thin delegators；129、221、333、455、583 行重复测试服务异常原样透传。实现 `backend/modules/world/character_facade.py:54` 等为直接 await 转发。`test_event_facade.py`、`test_entity_facade.py`、`test_rag_facade_extra.py` 也应按相同标准筛选。
- 负担：大量 mock 返回值、参数位置与异常透传断言，重构服务接缝就必须同步测试，但未增加领域行为证据。
- 最小替代：保留 facade 的真实转换、默认参数、隔离参数传递和对外返回契约；纯透传的成功/空值/异常组合合并成少量参数化接线检查。不得整文件删除人物知识边界测试。

### A03 · shrink：视觉检查承担了后端集成测试的准备成本

- 证据：`frontend-console/playwright.visual.config.js:5` 复用 `playwright.base.config.js:45`，强制执行 Alembic、启动 FastAPI 和 Vite，并要求专用 PostgreSQL；`e2e/visual-settings.spec.js:49` 为截图写账户全局默认；`visual-outline.spec.js:50` 创建真实 revision；`visual-project-rag.spec.js:56` 创建真实项目，再 mock 搜索结果。
- 负担：仅检查排版也依赖 migration、账户状态、后端可用性和数据清理；纯 mock 的互动故事截图同样承受整套启动成本。
- 最小替代：用现有 Playwright `page.route` 固定视觉数据，视觉入口仅启动前端；保留少量真实全栈功能测试验证绑定。无需引入 Storybook 或第二套组件平台。转换前必须补齐该截图场景全部必要响应，不能只是取消数据库保护。

### A04 · shrink：CI 配置被后端测试复制成第二份配置

- 证据：`backend/tests/unit/test_repository_security_automation.py:133` 精确冻结 job 列表、顺序、concurrency 文本；160 行按 step 名查找并逐字比较命令；209 行固定 CodeQL runner、名称、矩阵形状；279 行固定 Dependabot 每天几点执行、PR 上限和所有字段。
- 负担：调整调度时间、重命名 step、增加无害 job 都会破坏“后端行为测试”。这些值大部分已经由 YAML 表达。
- 最小替代：只验证最小权限、可信触发事件、必要检查存在、固定 Action SHA、敏感输出限制。删除日程、显示名称和非安全字段的精确镜像；必需状态检查名称可能被远端规则引用，不能随意改名。

### A05 · shrink：工具链版本和镜像摘要在测试里再次硬编码

- 证据：`backend/tests/unit/test_test_harness.py:449` 再写 Python/Node/nginx/PostgreSQL 版本与完整 digest，精确统计 runner 出现次数，甚至要求 Dockerfile 的换行和 COPY 写法；`deploy/tests/test_scripts.py:398`、410 行另抄数据库和 embedding 镜像。
- 负担：例行版本轮换需要同步配置、工作流和多份测试常量；安全补丁升级本身会触发这种失败。
- 最小替代：从现有权威版本文件或 Dockerfile 读取版本，检查引用一致性及 tag+digest 格式，保留真实镜像启动、非 root、只读和健康检查。无需新增版本配置中心，也不取消供应链固定。

### A06 · native：测试里手写 JavaScript 词法状态机

- 证据：`frontend-console/tests/api-contract.test.js:55` 的 `stripNonCodeText` 约 100 行，自行处理字符串、注释、模板与嵌套状态，随后用正则抓 `api.group.method`；文件其余 HTTP method/path/requiredBody 测试有独立价值。
- 负担：为了检查 API 引用，维护一套不完整的 JavaScript 语法解释。语法扩展需要给扫描器及其测试一起补丁。
- 最小替代：复用现有 ESLint 解析后的 MemberExpression；Vue 使用已安装插件的解析能力。保留 API 方法存在性规则及请求契约测试，不新增解析依赖。

### A07 · shrink：CSS 变量检查维护了一份平行作用域模型

- 证据：`frontend-console/tests/cssVariableContracts.test.js:12` 手写 owner/consumer/injectedBy 表，77 行开始自己解析声明、选择器和用法，共 182 行。
- 负担：组件移动、局部变量或动态注入变化需要额外登记；只能用字符串近似 CSS 继承和 DOM 作用域。
- 最小替代：静态层只检查共享 token 定义；动态/继承变量用实际代表组件的 computed style 检查。保留未定义 token 保护，但不再为每个业务组件建立手工作用域白名单。

### A08 · shrink：facade 导出清单和 Prompt registry 被精确冻结

- 证据：`backend/tests/unit/test_facade_public_api.py:10`、85、123 行维护三份完整集合，155 行以后用集合相等验证；`backend/tests/prompt_contracts/test_prompt_contracts.py:21` 再维护 22 个合同 ID 的精确集合。
- 负担：向后兼容地新增一个公开能力也必然失败，需要同步复制清单。这不是在验证新增能力是否破坏旧调用者。
- 最小替代：必要旧接口用存在性与调用契约检查；导出实现从 `__all__` 自洽验证；registry 对实际加载项逐项校验，并保留必要合同覆盖与重复 ID/非法模型/未知 probe 拒绝。不得删除真实兼容契约或允许 HTTP schema 泄漏。

### A09 · delete：异步 fixture 的装饰器拼写有独立 AST 审查系统

- 证据：`backend/tests/unit/test_test_harness.py:197` 至 299 行识别别名和嵌套定义，再为扫描器编写测试；`backend/pyproject.toml:107` 已启用 `asyncio_mode = "auto"`，`testing-guide.md:342` 也明确普通 pytest 异步 fixture 可运行。
- 负担：约百行检查只为了强制一种等价装饰器写法，不验证隔离和清理行为。
- 最小替代：删除该风格扫描及其自测，保留实际 fixture 回滚、loop、资源释放测试。若实施，应同步移除文档中的强制写法要求。

### A10 · shrink：全局 autospec 规则只接受字面量，没有例外机制

- 证据：`backend/tests/unit/test_test_harness.py:71` 的 `_unautospecced_patch_calls` 只接受 `ast.Constant(True)`，147 行全库检查；测试指南 337 行却允许无法 autospec 的场景附说明。
- 负担：合法的显式替身、无法 autospec 的对象或非字面量配置仍被拒绝，形成“约定有例外、机器无例外”的额外摩擦。
- 最小替代：保留对可调用依赖的 autospec 默认要求；仅增加窄、带理由、可审计的真实例外，或将纯写法检查降为 lint。不要以改用无 spec 的 MonkeyPatch 规避签名验证。当前规则仍有效，本次没有绕过。

### A11 · shrink：测试把普通数据对象的构造赋值逐字段复述

- 证据：`backend/tests/unit/test_rag_extra.py:65` 给 dataclass 传全部字段再逐字段读回；`test_world_extra.py:1686` 一组默认值/冻结测试；同类散见各 `*_extra.py`。
- 负担：字段增加或内部默认调整引发大量机械维护，普通赋值主要是 Python/Pydantic 自身行为。
- 最小替代：删除纯构造读回；保留有业务意义的默认可见性、状态、序列化兼容、独立可变容器和真正自定义校验。不能把 `author_only` 等安全默认值一并当成样板删除。

### A12 · shrink：Prompt 文案甚至换行被逐字冻结

- 证据：`backend/modules/world/tests/test_world_generation_center_api.py:481` 至 498 行锁定自然语言片段，含 `不能以\n…`、`核心前提、\n…`；`backend/modules/writing/tests/test_conflict_checks.py:1696` 固定“1-2 句”“300-600 字”；`test_writing_api_generation.py:934` 等也有措辞断言。
- 负担：同义改写、排版变更也失败；包含一句提示不等于模型实际遵守。
- 最小替代：删除普通修辞与换行断言；保留来源是否进入/排除、确认标识、隐藏事实不泄漏、结构化输出字段、选中范围等可检查合同。关键指令仍可做少量存在性检查，不能用付费 LLM 测试替换全部确定性测试。

### A13 · shrink：仅修改测试或截图仍触发重型 CI

- 证据：`scripts/classify_ci_changes.py:13` 仅按 backend/frontend 顶级目录分类；已直接调用 `classify` 验证：后端测试文件 → backend+postgresql+browser+images；一张 darwin PNG → frontend+browser+images。
- 负担：截图更新触发镜像构建与功能冒烟，后端 mock 测试调整也触发数据库契约；风险与执行范围明显不相称。
- 最小替代：在现有分类函数中增加窄的测试源码、快照、非运行时产物规则。共享 fixture、CI 脚本、构建输入不能一概视为低风险；同时修改生产代码时仍按并集运行。保留必需 job 状态，不用 workflow paths 导致检查 Pending。

### A14 · shrink：普通行为改动触发多文档“必须变化或说明”

- 证据：`docs/architecture/architecture-documents.toml:173` 对所有业务生产 Python 要求模块设计文档和 README；303 行覆盖全部前端 JS/Vue；`scripts/check_architecture_docs.py:596` 将路径命中转为 required documents，否则依赖 PR 勾选和固定格式原因。
- 负担：不涉及架构或对外契约的内部修复也进入文档影响流程。存在 no-impact 出口，但每次都要操作这一出口。
- 最小替代：普通实现文件给出影响提示；稳定契约、schema、router、任务协议等变化才硬阻断。保留文档清单、断链与确实改变用户行为的文档要求，不以全面关闭 docs-check 解决。

### A15 · shrink：架构目录要求同一实现清单在人类文档重复出现

- 证据：`scripts/check_architecture_docs.py:375` 起要求表名同时出现在数据库目录、模块设计和代码 README；433 行起逐一核对三个 route catalog、两个 task catalog；配置位于 `docs/architecture/architecture-documents.toml:35` 起。
- 负担：新增表、任务或路由后在多个位置重复补名字，检查的是字符串存在，不是说明是否有用。
- 最小替代：表、路由、任务各留一份权威目录；其他文档链接引用。保留实现与权威目录的一致性，不要求多处复制完整清单。

### A16 · shrink：同一文档全量检查在后端测试与独立 job 重复执行

- 证据：`backend/tests/unit/test_architecture_docs.py:21` 调用真实仓库 `check_inventory`；`Makefile:110` 的 test-ci 已依赖 docs-check；独立 `architecture-docs.yml` 也检查真实仓库。
- 负担：后端快速测试又承担一次全仓文档盘点，让同一错误在多个 job 出现。
- 最小替代：真实 inventory 仅归 docs-check；保留 checker 对合成输入、坏链接、路径编码等行为的单元测试。先于实现的项目文档门禁要求仍须遵守，不能自行删除入口规则。

### A17 · shrink：视觉辅助逻辑和平台分支重复八份

- 证据：八个 `frontend-console/e2e/visual-*.spec.js` 都有截图包装与 darwin 判断，七个重复主题切换；配置已固定 viewport、animations、caret，调用处仍多次重写。settings/writing/today 使用 300ms 等待；project-rag 58 行等待 1100ms 确保数据库排序。
- 负担：同一确定性修复需在多个文件同步；又要等待 toast、双 RAF、主题动画、字体与真实时间排序。
- 最小替代：保留一个很小的视觉 fixture，共享字体就绪和截图准备；主题默认通过已有 localStorage 在加载前设定，单独保留真正的主题切换行为测试；固定数据时间与排序。由已有截图禁动画配置处理动画，不再无依据地叠加固定 sleep。不要把有必要的 readiness 等待一起删掉。

### A18 · shrink：纯 mock/校验测试也要求真实 SQLite fixture

- 证据：`backend/tests/unit/test_character_facade.py:112` 请求 `db_session`，但测试体仅创建 `CharacterCreate` 并检查 ValidationError；其他纯转发用例把 session 作为不执行操作的 mock 参数。
- 负担：纯 schema 或参数转发测试与全库 ORM schema 建立无必要依赖，增加准备和故障牵连。
- 最小替代：从不触碰数据库的测试移除 db_session；需要校验 session 传递的纯接线测试可用明确替身。真实查询、事务、隔离用例仍使用原 fixture。此项不包含已合理共享的 session 级 schema 和每例回滚。

## 需要进一步证据的 5 项政策候选

这些有结构性成本，但不能直接定性为应删除，也不计入上面 18 项。

1. **覆盖率 85% 全仓硬阈值及其二次锁定。** `backend/pyproject.toml:150` 配置阈值，`test_test_harness.py:367` 又要求不小于 85；后者可以去掉重复数值保护。是否把总覆盖率改为非阻断趋势或调整阈值，需要当前覆盖率分布、漏测风险与失败历史。本次未生成全仓覆盖率报告，不推荐拍脑袋改成 60% 或 70%。若继续保持阈值，删除低价值测试前还要检查覆盖率变化。

2. **95 张全页/多主题截图的数量与统一 0.5% 阈值。** 95 不自动等于过多；写作恢复、候选采用、窄屏等有独立价值。可先用共享布局代表图覆盖主题，再为特殊控件保留局部截图；是否减少具体哪张应看最近变更的差异和重复区域。0.5% 对大画布可能漏掉小但重要的控件，对某些字体漂移又可能敏感。本次未生成差异图，不能宣称应统一放宽。只审阅新增/变化基线，而不是无差别重看所有图片。

3. **平台基线维护。** 当前全部 darwin，其他平台默认 skip，`VISUAL_BASELINE=1` 再按平台建立图片。建议指定一个权威环境供共享视觉基线运行，不必增加 macOS/Linux/Windows 三套；普通开发者可跑行为检查。但从 macOS 切换环境应显式重建并审查，不能直接改文件后缀视为等价。

4. **自写调用顺序/文件路径静态分析。** `test_active_project_route_closure.py:197` 递归近似分析鉴权先后；`test_non_deep_llm_token_inheritance.py:11` 维护允许显式预算的文件路径；`test_entity_facade.py:37` 禁止 root facade 任何 async 函数；`modules/writing/tests/test_writing.py:78` 同时测导入行为及特定 import 位置。存在实现耦合，但鉴权闭包、预算继承和循环导入有真实保护目标。先以运行时依赖枚举、越权失败与合法导入的行为检查提供等价证据，再缩减不必要的文件形态限制；不得直接移除安全静态门禁。

5. **本地预审全层和无条件全局初始化。** `testing-guide.md:99` 后端-only 要求全 make test、前端-only 全 Vitest；`backend/conftest.py:77` 每例重置并注册全局 DI。共享基础设施改动有理由全跑，纯 schema 用例可能不需要全局 app。但未测量初始化成本，也未证明缩小 fixture 会保持独立性。可按影响分层，并继续让 CI 做相应总验收；不先建复杂的动态影响图、依赖分析器或自制调度器。

## 明确保留的严格要求

| 已审查要求 | 结论 |
| --- | --- |
| 显式专用数据库、拒绝普通开发库、全局 manager 目标校验 | 必须保留，防止测试访问真实数据；视觉 mock 化后才可不启动数据库 |
| SQLite schema 一次创建、每例外层事务与 savepoint 回滚、UUID 适配 | 已是复用方案，不属于应删除的复杂度 |
| PostgreSQL CAS、并发唯一性、lease、提交立即可见、pgvector | SQLite/mocks 不能替代；保留 critical 与 nightly 分层 |
| owner/novel_id、Evidence confirmation/hash、隐藏事实、授权采用与回滚 | 属于产品安全和数据语义，不能因简化测试放宽 |
| 真实付费模型/语料显式运行 | 合理边界，未进入默认快速层；不建议并入普通回归 |
| 秘密扫描、Action SHA 固定、非 root/只读运行、备份恢复 | 保留实际不变量；只去掉镜像常量和 YAML 写法的重复镜像 |
| 保存失败、离开保护、候选覆盖、键盘访问、触控与对比度 | 保留行为与可见效果检查，删正则样式快照不等于删这些保护 |
| workers=1、retries=0 | 当前有共享服务/账户状态，不能直接开并行或加重试隐藏问题；不是本次优先减负点 |
| 既有 API/base URL/requiredBody、Prompt schema 与 fixture 校验 | 保留真实合同；只减少手写解析、文案措辞和精确清单重复 |

## 最小落地方向

先处理 A01/A04/A05/A08/A09/A11/A12 的非行为断言，再处理 A13/A14/A16 的门禁触发；这是最少产品改动即可减少维护负担的路径。随后按已有 Playwright 能力完成 A03/A17，逐场景保持原有效视觉断言。A02/A18 按调用链清理，不能按测试文件名批量删。

不建议引入新的测试平台、快照审核系统、自动影响分析服务或更多测试配置文件。不要用全局提高像素容忍度、关闭覆盖率、吞 warning、增加 retries 的方式掩盖复杂度。

初步估算上述已确认项可净减约 **600–1,200 行**重复测试/辅助代码，**0 个新增依赖**；这是尚未实施的人工粗估，不包含截图数量缩减、有效行为测试和数据库隔离代码，不能作为承诺的精确 diff 或性能收益。

## 已执行验证

- 前端六文件：`npm test -- tests/sceneWorkbenchSpacing.test.js tests/uiSizeContracts.test.js tests/typographyTokens.test.js tests/editorialTheme.test.js tests/cssVariableContracts.test.js tests/api-contract.test.js`：56 passed，6 files passed。
- 后端四文件：`uv run --locked --extra ci -- pytest tests/unit/test_test_harness.py tests/unit/test_facade_public_api.py tests/unit/test_repository_security_automation.py tests/unit/test_ci_change_selection.py -q --timeout=120`：53 passed。
- 对真实 CSS 规则做内存中等价属性重排：原正则匹配 true，重排后 false；仓库 CSS 未改。
- 对当前 CI 分类函数输入测试文件/截图路径：确认 A13 的实际输出；未触发远端 CI。
- 未运行全仓 pytest/Vitest、浏览器截图、真实 PostgreSQL、Docker 构建、模型或部署；没有声称完整回归通过或实测节省耗时。
- 文档门禁结果见同目录 TASK.md 的最终记录。
