# P0 + P1 审计候选清单（已复核分诊）

**来源**: 20 轮审计 + 并行 sub-agent 验证  
**原始生成日期**: 2026-07-13  
**当前代码复核**: 2026-07-14（以当前工作区、模块 README、测试与 GitHub 仓库设置为准）

## 当前工作树权威摘要（2026-07-14）

原“当前适合修复 0 项”是修复前的失效判断。本轮复核发现并已收口以下真实阻塞：

- 后端 12 项失败、前端 1 项地图编辑历史失败及 2 个 migration lint 错误；
- #19 `effective-llm-settings` 的不存在/已软删除项目 500 语义；
- #17 全量 patch 硬约束：初始 AST 清单 627 个调用中 578 个缺少
  `autospec=True`，当前工作树 638/638 合规并由 import-aware AST 门禁防回归；
- world 锁定读取测试替身、自定义实体类型测试语义及地图本地 UUID 草稿撤销/重做
  测试均已与当前稳定行为同步。

最终门禁：后端 **3,630/3,630** 通过、生产覆盖率 **85.97%**；前端
**1,183/1,183** 通过；`make lint`、`make secret-hygiene`、
`git diff --check` 均通过。不存在及已软删除项目的 effective settings 均返回
既有 DomainError 404 envelope，成功响应 schema 与前端 wire shape 不变。

当前仍保留的非代码/部署前门禁：GitHub `main` 分支保护需远端授权；正式部署
runbook 需验收迁移与运行时数据库最小权限；Docker、多 worker、TLS、监控与备份
待部署目标确定后重新立证。EbookLib 上游明确使用 AGPL-3.0，本轮仅登记为
[正式分发前许可证评估门禁](https://github.com/aerkalov/ebooklib)，不替换依赖。

#15 的当前事实是：Writing/Scene 使用软废弃，顶层地图使用软归档并提供
impact/restore；marker、terrain layer、binding、territory 等可重建局部地图素材
仍保留显式删除。#16 的当前事实是：应用首屏、全局工作区、写作、大纲和 Scene
工作台均使用共享可访问骨架屏。#11 仍是 HTML sink 纵深防御关注点，但当前未发现
未经转义的可利用路径；T4、CI、90 秒 LLM timeout、认证和安全头继续标记为已验证。

> 下方二十八批处置记录与原始表格作为历史证据保留；与本节冲突时，以本节、
> 当前稳定接口和最新测试结果为准。

**最新处置**: 第一批 #3 已移除生产 Mock/dummy 分支；第二批 #7 已用 connection-level savepoint 修复 pg_trgm 事务恢复；第三批 #6 已为 4 条 best-effort 降级补充受控 warning 与 traceback；第四批 #13/S8 已引入恢复请求模型并统一 `DEBUG` 配置；第五批 #10 已收口 Scene workbench 未知异常的 500 响应泄露；第六批 #2 已建立仓库侧后端 CI，远端 `main` 分支保护仍待单独授权启用；第七批 T2 已统一异步 fixture 装饰器并增加静态回归门禁；第八批 U1/U3 已补齐 409 冲突提示和大纲结构页加载失败状态；第九批 U7 已为生成中心本地会话增加单项目容量、项目数 LRU、异常提示和项目隔离；第十批 U6 已使项目元数据请求乱序时只有最新导航继续提交路由状态、URL 与渲染；第十一批 O4 已为 `DomainError` 增加不含用户内容的受控结构化日志；第十二批 D2 已把旧 `start.sh` 收敛到包含 worker 的权威开发栈，并补齐部分启动失败和信号退出清理；第十三批 U4 已为共享业务模态框补齐 dialog 语义、标题关联、焦点约束和关闭后焦点恢复；第十四批 U5 已在共享模态关闭边界增加未保存表单保护，并隔离异步 action 与替换弹窗竞态；第十五批 U2 已以 `onRendered` / `onActivate` 生命周期和同步 DOM 绑定取代猜测式 timer 绑定，并保留具有明确业务语义的定时器；第十六批 O2 已在最外层 ASGI 耗时中间件增加安全结构化 access log，覆盖正常、错误、流式和安全/CORS 短路响应；第十七批 T3 已为 fast 测试层增加单测试超时、可配置的 xdist 并行目标，并将 CI 固定为 2 worker；第十八批 T6 已建立只统计生产 Python 包的 85% 覆盖率门禁，并修复 SQLite 测试中 PostgreSQL UUID 被 NUMERIC affinity 偶发转成 `inf` 的问题；第十九批 T1 已按真实缺口补齐 core/shared 公共契约与 LLM JSON 恢复测试，并统一 fenced JSON 的 dict 返回语义；第二十批 T5 已增加导入→生成→采用→发布→检索的确定性串行集成场景，并修复 review 暴露的项目 LLM 凭据进入生成 prompt 问题；第二十一批 S3 已在统一解析入口增加不信任客户端 MIME 的内容签名、EPUB 结构/资源与 MOBI 复合头门禁；第二十二批 #5 已在最外层 ASGI 响应边界统一注入安全响应头，并覆盖未处理 500、流式和各类短路响应；第二十三批 #16 已把应用首屏、全局切换、写作、大纲和 Scene 工作台的纯文本主加载态改为可访问骨架屏；第二十四批 #1 已在 Git index 与已跟踪工作区边界增加零依赖敏感文件和高置信凭据门禁；第二十五批 S5 已把封闭测试访问令牌从 `sessionStorage` 收口到当前页面 module memory，并统一普通请求、上传和错误上报的认证路径；第二十六批 #4 已增加按 direct peer 的进程级 HTTP token bucket，并让非本地环境在缺少正限流配置时拒绝启动；第二十七批 O1 已为 HTTP 请求和 worker attempt 增加验证后才绑定的安全 `novel_id` 日志关联；第二十八批 S4 已让非本地 API、普通 worker 和 reload 监督进程在 LLM RPM 非正时拒绝启动。二十八批均未改变数据库 schema；第四批保持有效请求与成功响应的 wire contract，仅为原先未校验的错误类型补充 422 响应；第五批保持已知 400/404/409 的状态码与消息不变；第九、十、十三、十四、十五、二十三、二十五批仅改变前端本地状态与交互呈现；第十一、十六、二十七批保持 HTTP 响应 shape 和状态码不变；第十二批只改变本地开发进程编排；第十七、十八、二十四批只改变测试、仓库和 CI 门禁；第十九批只收紧内部 LLM JSON 解析契约；第二十批只收紧 Context prompt 投影并新增测试；第二十一批只让内容与允许扩展名不匹配的上传稳定返回 422；第二十二批有意新增统一响应头；第二十六批只新增超限 429 和非本地启动配置门禁，保持既有成功响应、API schema 与 PostgreSQL schema 不变；第二十七批只改变日志关联和异常日志内容，不改变 API/schema/wire；第二十八批只新增启动配置门禁，不改变 limiter 算法或 API/schema/wire。

**原始表格统计修正**: 8 P0 + 8 Top 项 + 8 安全 + 6 测试 + 5 部署 + 7 UX + 5 运维 = **47 项**，不是 49；“Top 20”一节实际只列出 8 项。

**终审统计（47/47）**：已修复 30 项；当前报告不成立、已过时或未立证 10 项；
合理明确暂缓 7 项。该统计是本轮开始前的历史分诊；其“无剩余适中代码修复项”
已被后续复核推翻，新增发现的 #17/#19 与测试/lint 阻塞现已在本轮修复。其中 #2
仅剩远端 `main` 分支保护，属于需要授权的外部仓库设置，不计作仓库代码漏修。

| 终审分类 | 项目 |
|---|---|
| 已修复（30） | #1、#3、#4、#5、#6、#7、#10、#12、#13、#16；S3、S4、S5、S8；T1、T2、T3、T5、T6；D2；U1–U7；O1、O2、O4 |
| 不成立、过时或未立证（10） | #9、#11、#14、#15；S1、S6、S7；T4；D4、D5 |
| 合理暂缓（7） | #2（仅远端分支保护）、#8、S2、D1、D3、O3、O5 |
| 当前适合修复（0） | **历史快照；后续复核证明失效，相关项现已修复** |

> 本文下半部分保留原始审计条目，便于追溯；它们不再都表示“当前已验证的
> P0/P1”。路径在后续重构中已有迁移，优先以模块 README、稳定接口、当前实现和
> 测试为准。

## 复核结论与当前阶段分诊（2026-07-14）

项目当前仍是 demo / 本地开发阶段。以下分诊区分现阶段的代码约束、服务暴露前的
上线门槛和普通 backlog；不得把后两类当作阻塞当前功能迭代的 P0。

### 当前阶段决策摘要

| 分类 | 当前是否必须修复 | 决策 |
|---|---|---|
| #3 生产代码识别 `Mock` | **已修复** | 生产代码不再 import 或检测 Mock；测试通过构造器依赖、monkeypatch 或真实 DB fixture 显式建立边界，并增加全 backend 静态回归门禁。 |
| #1 API Key 曾提交 | **当前防回归已完成，历史无需重写** | 历史值是已删除的 `sk-placeholder` 而非真实凭据；当前 `.env` 未跟踪且已 ignore，CI 在安装依赖前扫描 index 与已跟踪工作区，阻止敏感文件和高置信凭据再次进入版本库。 |
| #2 CI/CD 与分支保护 | **仓库侧已完成，远端设置待授权** | 已新增稳定的 `Backend quality` 工作流，并以 Python 3.12、锁定依赖、lint、完整 fast-test 和 RuntimeWarning 门禁验证；GitHub `main` 仍未启用分支保护，需获得远端设置授权后把该 job 设为必需检查。 |
| #5 后端安全响应头 | **已修复** | 最外层响应边界统一写入 `nosniff`、`DENY` 和请求耗时；仅对权威 HTTPS scheme 写入一年期 HSTS，并覆盖正常、错误、流式、CORS 与安全门禁短路响应。 |
| #4 HTTP 速率限制 | **当前单 worker/direct-peer 边界已修复** | 非本地环境必须配置正 RPM/burst；无效认证、未匹配和普通请求共用进程级 direct-peer token bucket。它不信任代理头，也不宣称提供多来源 DDoS 或聚合连接池容量保证。 |
| S4 LLM 默认 RPM | **已修复** | 本地/测试仍可显式设为 0；其他环境必须按 provider 配额配置正 RPM，否则 API、普通 worker 与 `worker --reload` 监督进程均拒绝启动。限制仍按进程执行，不在代码中武断写死生产吞吐。 |
| S5 Web Storage 中保存 Bearer token | **已修复** | 封闭测试 token 只存在当前页面的 `api.js` module memory；刷新后重新输入，普通请求、上传和错误上报共用同一认证路径，任一路径收到 401 都清除被拒 token。 |
| S3 上传内容只看扩展名 | **已修复** | 客户端 MIME 不可信；统一解析入口按 TXT/HTML、EPUB、MOBI/AZW3 的实际内容校验后才调用解析器，并为 EPUB 限制成员、路径、压缩算法和解压规模。 |
| #8/D1/D3 部署方案项 | **合理暂缓** | Dockerfile、多 worker 与反向代理必须由正式部署目标、进程模型和 TLS 边界共同决定，不应在 demo 阶段拆成孤立配置文件。 |
| D4/D5 独立缺陷 | **当前报告不成立** | `novel_dev_pass` 是本地 Compose 与 `.env.example` 配套的开发凭据，不是生产 secret；仓库没有 Dockerfile，`.dockerignore` 也没有构建消费者。正式容器方案确定后再重新评估凭据注入与构建上下文。 |
| #7 pg_trgm fallback 事务恢复 | **已修复** | PostgreSQL 相似度查询在 connection-level savepoint 内执行；失败先回滚 savepoint，再在同一外层事务中执行 fallback，且不覆盖项目 `autoflush=False` 语义。 |
| #6 静默 best-effort 异常 | **已修复** | 原报告列出 3 处，但实际还漏了 `rag/tuning.py` 的 embedding 降级，共 4 处；现均保留降级语义，并记录固定字段不含正文/Key 的结构化 warning 与 traceback。tuning 整次网格只记录首个失败 traceback，避免日志风暴。 |
| #13 dict body 与 S8 debug 配置漂移 | **已修复** | resume/abandon 共用 typed request model，保持 `{task_id: string}`、缺失/空值 400、错误类型 422、ownership/project gate/404 语义；`.env.example`、Settings 与 FastAPI 启动统一使用 `DEBUG`，默认 false。 |
| #10 Scene workbench 未知异常响应 | **已修复当前确认路径** | 未知异常只向客户端返回稳定的通用 500 消息，同时记录异常类型和 traceback；已知 400/404/409 继续返回领域校验消息。当前没有证据支持全仓库统一替换所有 `detail=str(exc)`。 |
| #16 已定义但未使用骨架屏 | **已修复真实主加载边界** | 应用首屏、全局工作区、写作、大纲和 Scene 工作台使用共享骨架；具体加载文本对屏幕阅读器可见，视觉条为装饰内容并遵守 reduced-motion。按钮、任务进度和局部刷新继续保留明确业务状态。 |
| #14 embedding cache key 缺模型名 | **当前报告路径不成立** | 缓存只属于进程内 BGE 单例，模型路径在单例构造时固定；当前没有不重建单例的动态 embedding 模型切换入口，进程退出又会清空缓存，因此无法复现“切换模型后一小时返回旧向量”。 |
| T2 异步 fixture 装饰器 | **已修复** | 实际为 11 个测试文件中的 18 处，不是原报告的 10 处；均改用 `pytest_asyncio.fixture`，并由可识别模块/import alias、调用形式和嵌套 class 的静态门禁防回归。 |
| T3 无测试并行与挂起防护 | **已修复** | `ci`/`dev`/`test` extras 锁定 pytest-xdist 与 pytest-timeout；fast 层默认每项 120 秒超时，串行与并行目标共享相同路径和 marker，CI 固定 2 worker 并使用 `loadscope`。E2E、真实 LLM 和外部语料验收不继承该超时或并行策略。 |
| T6 无覆盖率阈值与报告 | **已修复** | CI 在同一 fast 范围内统计 `app/core/shared/infrastructure/modules` 的生产代码，排除测试文件与 `conftest.py`，输出缺失行并要求至少 85.0%；第二十八批复验基线为 86.44%。 |
| T1 core/shared 测试覆盖不足 | **已按真实缺口修复** | 原报告“dependencies.py 和整个 shared 零覆盖”已过时；现直接覆盖 DI alias、项目上下文、公共类型别名，以及 LLM JSON 的直接、代码块、嵌入、列表、截断恢复和拒绝路径。 |
| T5 跨模块串行场景缺失 | **已修复并补安全回归** | 快速集成层现串行执行文件导入、导入章节发布索引与快照、基于导入证据的确认生成、人工采用、再次发布索引与快照、canonical 检索；同时验证相同关键词的异项目正文和项目 LLM 凭据均不能进入生成 prompt。 |
| U1 409 提示与 U3 大纲加载错误 | **已修复** | API 统一把 409 映射为“请求冲突”并保留领域 detail；剧情线、篇章纲、伏笔、揭示加载失败不再伪装为空列表，而是显示安全转义的错误、可重试入口和请求代次保护。 |
| U7 生成中心本地会话无边界 | **已修复** | 每项目快照上限 512 KiB，最多保留 5 个项目并按最近保存时间淘汰；超限先丢弃可重建预览，再将持久化对话收敛为最近 40 条。配额、禁用和损坏均有去重警告，失败不覆盖旧快照，项目切换先保存旧项目并只恢复目标项目。 |
| U6 路由快速项目切换竞态 | **已修复** | 项目元数据同步使用 AbortSignal、请求代次和应用内 `no-store` 语义；过期的导航不再提交项目、view/subview、hash 或渲染。初始化等待期间即可响应 `popstate`，且监听器只绑定一次。 |
| U4 模态框 ARIA 与焦点约束 | **已修复** | 共享模态 shell 声明 modal dialog 与标题关联；打开后焦点进入内容或操作区，Tab/Shift+Tab 在对话框内循环，输入控件内 Escape 也可关闭，关闭或连续替换内容后恢复到最初触发控件。 |
| U5 模态表单无脏状态保护 | **已修复** | 共享模态自动比较可编辑控件的打开基线；值、选中项或控件结构发生用户可编辑变化时，关闭按钮、取消、遮罩和 Escape 均先确认放弃。成功 action、恢复原值与不可编辑动态控件不误提示。 |
| U2 `setTimeout` 绑定竞态 | **已修复真实绑定竞态** | 原报告“11 处”不是可靠现状口径；当前生产前端保留 18 处 `setTimeout`，均承担轮询、退避、自动保存、防抖、拖拽状态释放、布局初始化或短暂反馈，不再延迟绑定事件。新鲜渲染在 DOM 提交后调用 `onRendered`，keep-alive 恢复只调用 `onActivate`；同步模态和视图自身提交的 DOM 立即绑定。 |
| O4 DomainError 处理器无日志 | **已修复** | 预期 4xx 记 INFO，领域 5xx 记 ERROR；只记录有界 method、FastAPI 路由模板、status 和白名单 code，不记录领域 message、动态路径参数、请求体、Key 或 traceback。未知异常由全局 handler 记录白名单类型和有界 frame 位置，不记录异常正文或 cause chain。 |
| O2 无请求日志中间件 | **已修复** | 最外层纯 ASGI middleware 在完整响应或流结束后记录一条 access log，并继续注入 `X-Request-Time-Ms`；只记录受控 method、框架路由模板、status 和 duration。未匹配或预路由短路使用 `<unresolved>`，不记录实际 path、query、body、header、token 或用户内容。 |
| O1 日志缺少 `novel_id` 上下文 | **已修复当前请求/任务关联边界** | HTTP 请求和 worker attempt 使用隔离 ContextVar；仅在 project facade 验证成功或成功项目路径后绑定规范化 UUID，未知、非法和未验证任务元数据只记录安全占位符。它不等同于跨进程 trace/span。 |
| D2 `start.sh` 未启动 worker | **已修复** | `start.sh` 作为兼容薄入口通过 `exec` 委托与 `make dev` 相同的 `scripts/dev_stack.py start`；backend、worker、Vite 由同一 pidfile 和退出清理管理。 |
| 其余设计、体验、测试覆盖和运维项 | **当前无统一修复必要** | 保留为 backlog；由真实故障、用户反馈或正式部署目标重新触发和排序。 |

因此，本报告不再支持原始“立即修复十余项”的排期。#3 已在第一批修复中收口；
#2 的仓库代码已在第六批完成，当前只剩需要单独授权的远端分支保护设置；S4 已在
第二十八批收口，其余项目按部署边界或实际需求触发。

### 当前收口结果

| 原始项 | 复核结果 | 当前动作 |
|---|---|---|
| #1 API Key 曾提交至 Git 历史 | **当前防回归已修复**。历史中的 `sk-placeholder` 是占位符且早已删除，不构成需要吊销或重写历史的真实密钥事件；当前 runtime `.env` 未被跟踪。 | `make secret-hygiene` 与 CI checkout 后的零依赖入口同时扫描 Git index 各 stage 和已跟踪工作区，覆盖 staged/unstaged/deleted、二进制与非法 UTF-8；拒绝 runtime `.env`、常见私钥文件及高置信服务凭据。输出只含安全化路径、规则和短指纹，不回显原文。定向 32 项、完整 2-worker fast-test 3405 项通过，全仓生产代码覆盖率 86.38%。 |
| #2 零 CI/CD + 无分支保护 | **部分已修复**。仓库已有 pull request 与 `main` push 触发的 `Backend quality` workflow；公开 GitHub 仓库的 `main` 分支仍未受保护。 | 仓库侧门禁固定 Python 3.12 和 uv lock，执行 `make lint` 与完整 `make test-fast-coverage TEST_WORKERS=2 ARGS="-W error::RuntimeWarning"`；窄 `ci` extra 不安装本地 embedding/Torch/CUDA，测试也不连接 PostgreSQL、真实 LLM 或外部语料。后续需获远端设置授权，再要求 PR 和该状态检查通过。 |
| #3 Mock-in-production | **已修复**。原有 4 个文件的 Mock import、9 处 `isinstance(..., Mock)` 分支及 1 处模块名检测均已移除。 | 由静态回归测试禁止生产代码重新 import 或按模块名检测 `unittest.mock`；单元测试显式注入 snapshot builder/restorer 与 project LLM opener。 |
| S4 LLM RPM 默认 0 | **已修复**。共享校验拒绝负数，并在非 `development/test/local` 环境拒绝 0；API、普通 worker、`worker --reload` 监督进程及重载子进程均 fail closed。 | 本地默认吞吐和 limiter 算法不变，生产正值仍由 provider 配额决定。review 修复了仅子进程失败而 watchfiles 监督进程继续存活的问题；定向 146 项、完整 2-worker fast-test 3457 项通过，生产覆盖率 86.44%。 |

### 服务不再严格限于本机时的上线门槛

| 原始项 | 复核结果 | 说明 |
|---|---|---|
| #4 无 HTTP 速率限制 | **当前单 worker/direct-peer 边界已修复**。应用在认证、CORS 和路由前执行有界 token bucket；本地可显式关闭，其他环境缺少正 RPM/burst/bucket 容量会拒绝启动。 | 身份只取 ASGI direct peer，不信任 forwarding headers；超限返回固定 429、`Retry-After` 和 `no-store`，并保留安全头/access log。多 worker 会按进程数放大配额，多个真实 peer 仍可形成聚合负载，因此正式部署仍须结合反向代理和容量计划。 |
| S4 LLM RPM 默认 0 | **已修复当前启动边界**。统一校验允许本地/测试为 0，拒绝任意环境负数，并要求其他环境为正值。 | API、普通 worker、reload 监督进程与重载子进程均在开始服务前校验；实际 RPM 继续按 provider 配额部署，多进程总吞吐仍需容量规划。 |
| S2 CSP `style-src 'unsafe-inline'` | **方向成立，但合理暂缓**。Accepted ADR 明确保留该策略，当前还有大量内联样式与 JS style 操作。 | 正式启动 CSP 收紧前先完成系统性前端样式迁移并更新 ADR，避免零散删除导致界面失效。 |
| #8、D1、D3 | **部署能力缺口成立，但当前不宜拆分修补**。 | Dockerfile、多 worker 与反向代理应在正式部署目标、进程模型和 TLS 边界明确后作为一次部署方案交付。 |

### 下一轮小型硬化（不应标为 P0）

| 原始项 | 复核结果 | 建议范围 |
|---|---|---|
| #5 后端完全缺失安全响应头 | **已修复**。最外层 ASGI 响应边界会移除下游同名弱值或重复值，并写入单个 `X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY` 与 `X-Request-Time-Ms`；只有权威 ASGI `scheme=https` 时才写入 `Strict-Transport-Security: max-age=31536000`，不信任原始 `X-Forwarded-Proto`。 | 正常 HTTP/HTTPS、未处理 500、204/304、流式响应、CORS 预检和 access-token/XHR 短路均经过同一边界；默认非 DEBUG 模式的稳定 500 JSON、状态码和空响应语义不变，异常日志与 access log 各一条。未来引入反向代理时，必须通过受信配置传递真实 scheme，或由 TLS 终止层自行写入 HSTS。 |
| #4 无 HTTP 速率限制 | **已修复当前运行边界**。进程级 token bucket 按 direct peer 共享连接端口配额，状态容量有界；review 修复了耗尽 bucket 被 LRU 驱逐后通过 peer churn 重获 burst、时钟回退重复 refill、NaN 和畸形 method 字符串化问题。 | `OPTIONS` 不消耗配额；其余认证失败、未匹配、健康检查和业务请求均受限，429 经过统一响应头与 access log。定向 138 项、完整 2-worker fast-test 3431 项通过，生产覆盖率 86.42%。该结论不扩张为多来源 DDoS 或全局连接池容量保证。 |
| #16 CSS 骨架屏已定义但零使用 | **已修复当前主要工作区加载路径**。原报告“5 个视图”不是可靠现状计数；当前修复范围是应用静态首屏、全局路由切换、写作、大纲和 Scene 工作台五个主加载边界。 | 共享 helper 转义可访问文本，`role=status` / `aria-live=polite` 暴露具体加载对象，四个视觉占位均 `aria-hidden=true`；既有 `prefers-reduced-motion` 会关闭 shimmer。未把按钮提交、轮询任务、地图摘要或其他局部业务 loading 机械替换成骨架。定向 222 项、完整前端 60 个文件 1122 项 Vitest 通过。 |
| #6 `except Exception: pass` | **已修复**。原报告列出的 query expansion、alias context invalidation、suggestion context invalidation，以及漏算的 tuning embedding 降级共 4 处，均已移除 silent pass。 | warning 固定字段携带 novel/asset 或 chapter 上下文和 `exc_info`，不主动拼接查询正文、LLM payload 或 API Key；失败继续原 best-effort 路径。suggestion 测试清空 identity map 后重读 suggestion 与目标资产，证明接受写入已 flush。 |
| #7 pg_trgm fallback 缺 rollback | **已修复**。两个 pg_trgm 查询均在当前 Session connection 的 nested transaction 中隔离；`OperationalError` / `ProgrammingError` 离开 savepoint 后才执行 Python/ILIKE fallback。这里不使用 `AsyncSession.begin_nested()`，避免其无条件 flush 破坏项目的 `autoflush=False`。 | 真实 SQLite session 测试强制进入 PostgreSQL 分支并触发缺失 `similarity()`，证明 fallback 可继续查询、外层未提交写入仍保留且未被 flush，并且 novel_id、排序、分页和筛选不变。 |
| #10 `detail=str(exc)` | **已修复当前确认的泄露路径**。Scene workbench 原先会把未知异常原文包装为 500；现已返回稳定通用消息并在服务端记录异常类型与 traceback。当前全部模块 API 的精确匹配扫描仍有 21 处 `detail=str(...)`，均位于显式 4xx 分支，不等于报告声称的 50+ 个未知异常泄露点。 | HTTP 回归测试证明内部 SQL/路径不会进入响应，并覆盖已知 LookupError、PermissionError、ValueError 与冲突异常仍保持 400/404/409 及原消息。其余领域异常不在本批次扩张处理；只有发现真实未知异常被包装为 5xx 时再逐路径修复。 |
| #13 两个 dict body、S8 `APP_DEBUG` 漂移 | **已修复**。`DeepImportRecoveryRequest` 是两个恢复入口共享的 API-local 权威模型；额外字段继续按旧 dict 语义忽略，task_id 不做隐式类型转换或空白裁剪。`DEBUG` 通过实例化时 env factory 读取并传给 `FastAPI(debug=...)`。 | API 测试覆盖缺失/空值 400、非字符串/null 422、空白兼容、共享 OpenAPI schema、task owner → project gate → 404；配置测试隔离环境后验证 DEBUG/LOG_LEVEL 默认、env 覆盖和旧 APP_DEBUG 不再生效。 |
| S3 上传无 MIME/幻数验证 | **已修复**。`parse_file()` 在具体解析器前校验不可信 bytes：文本严格解码并拒绝二进制控制字符，HTML 需要可识别标记；EPUB 校验首个 stored mimetype、唯一安全成员、container/OPF namespace/结构、允许压缩算法及成员/解压上限；MOBI/AZW3 联合校验 PalmDB 记录表、PalmDOC 与 MOBI header。 | 伪装 PE 即使声明 `text/plain` 也在真实 API→service→parser 路径返回稳定 422、记录 failed 且不写草稿/任务；空文件仍为原 400，合法 UTF-16/GBK、HTML fragment、最小 EPUB 和满足复合头的 MOBI/AZW3 路由样本保持通过。review 另发现依赖清单未声明 `mobi` 包，因此真实 MOBI/AZW3 内容解析仍是独立兼容性 backlog，不影响本批伪装内容在解析前 fail closed。定向 225 项、完整 2-worker fast-test 3378 项通过，全仓生产代码覆盖率 86.37%。 |
| S5 Bearer Token 明文存 `sessionStorage` | **已修复**。封闭测试访问令牌只存在 `api.js` 的 module scope，不再读、写或清理任何 Web Storage token key；刷新页面即丢失并在下次 401 时重新提示。 | fetch、导入上传 XHR 和前端错误上报共用内存令牌；401 会清除已拒令牌，GET 认证重试绕过旧 pending/cache 以免自等待，显式调用方 Authorization 仍优先。递归静态门禁覆盖根目录、shared、ui 和嵌套 views；定向 82 项、完整前端 60 个文件 1131 项 Vitest，以及 fresh backend 独立端口首页 Playwright 6 项通过。 |
| T2 async fixture 装饰器 | **已修复**。11 个文件中的 18 个异步 fixture 已从 `pytest.fixture` 改为显式 `pytest_asyncio.fixture`；静态门禁同时扫描根 `conftest.py` 和全部测试文件，并有 alias/call/class/允许场景自测。 | 模块统一收集、lint 和完整 fast-test 通过。6 个位于两个 E2E 文件的 fixture 已完成静态核对，但本地 PostgreSQL schema 落后于当前 Alembic head，未冒险迁移含潜在开发数据的库，因此该两文件本轮未实际执行。 |
| T3 无 pytest-xdist 并行与 pytest-timeout | **已修复**。pytest-xdist 与 pytest-timeout 只进入测试相关 extras；`test-fast`/`test-v` 默认施加 120 秒单测试超时，`test-fast-parallel` 在完全相同的路径和 marker 上按 `TEST_WORKERS` 并行，CI 固定 2 worker 与 `loadscope`。E2E、真实 LLM、外部语料和手工验收保持显式串行且不继承 fast 层超时。 | 并行验证暴露并修复了 task registry 测试替身跨用例泄漏：相关 fixture 现在在测试前后恢复 singleton seam，registry 自测也显式注销类型。定向 72 项、串行 fast-test 3337 项（31 项按 marker 排除）和 2-worker 并行 fast-test 3337 项均在 RuntimeWarning 门禁下通过；uv lock 与 Ruff 门禁通过。 |
| T6 无 pytest-cov 阈值/报告配置 | **已修复**。`test-fast-coverage` 与并行 fast 目标使用完全相同的路径、marker、120 秒超时、`loadscope` 和 worker 数；coverage 只统计 `app/core/shared/infrastructure/modules`，完整排除 pytest 允许的三种测试文件命名、测试目录和 `conftest.py`，终端报告缺失行并以 85.0% 作为失败阈值。E2E、真实 LLM 与手工验收不继承 coverage。 | 门禁建立时生产代码语句覆盖率 86.13%，3340 项 2-worker fast tests 在 RuntimeWarning 门禁下通过；100% 阈值验证返回非零，证明门禁真实控制退出状态。复验还发现 PostgreSQL `UUID` 在 SQLite 被赋予 NUMERIC affinity，特定合法 UUID hex 会被存为 `inf`；测试组合根现仅为 SQLite 将其编译成 `CHAR(32)`，1000 个特殊 UUID 全部往返正确，PostgreSQL DDL 仍为原生 `UUID`。 |
| T1 core/shared 层测试覆盖不足 | **已按当前证据修复，原始“整层零覆盖”不成立**。`core.dependencies` 与 `shared.types` 现为 100%，`shared.utils` 为 95%；测试验证 DI re-export/Annotated metadata、项目上下文、PEP 695 公共别名，以及 LLM JSON 的直接 dict、列表包装、Markdown fence、嵌入对象/数组、截断恢复、失败与脱敏日志。 | review 发现 fenced JSON 分支原会直接返回 list/scalar，绕过函数的 dict 契约；现 dict 原样返回、list 统一包装为 `{"items": ...}`、scalar 走既有失败路径。定向 35 项、相关 imports 541 项和完整 2-worker fast-test 3357 项通过；目标三文件合计覆盖率 97%，全仓生产代码覆盖率 86.28%。 |
| T5 跨模块 E2E 串行场景缺失 | **已以无外部依赖的快速集成场景修复**。场景走真实 API、数据库、任务处理器、RAG 索引/回读和 Memory 快照，仅替换远程生成与 embedding，完整验证导入→生成→采用→发布→检索。 | 首轮 review 发现原测试未执行导入章节发布任务，也未证明导入正文进入生成上下文；补强后进一步暴露 `ProjectLoader` 把 effective settings（含 API Key）写入 `style_assets`。现 Loader 仅投影 prompt-safe 项目字段，Compiler 再按作者/读者安全格式化；相同关键词的异项目证据、API Key、Base URL 和 key 名均有负向断言。受影响范围 231 项、完整 2-worker fast-test 3360 项通过，全仓生产代码覆盖率 86.28%。 |
| U1 409 错误提示、U3 大纲子视图错误 | **已修复**。409 现在使用本地化冲突前缀，同时 `Error.status/detail/body` 和后端领域消息保持不变；四个结构子视图使用持久内联错误与真实重试，不再把失败显示成“暂无数据”。 | 错误详情经 `esc()` 转义；重试期间按钮禁用，失败后恢复；请求代次与离开视图失效处理防止旧请求晚到覆盖新数据。定向和完整 Vitest 覆盖四个页签、无 detail 409、XSS 文本和竞态。 |
| U7 generateView localStorage 无大小限制 | **已修复**。本地快照以 UTF-8 字节计算 512 KiB 单项目上限，最多保留 5 个生成中心项目快照；达到上限时先省略可重新生成的预览数据，再只持久化最近 40 条对话，仍超限则保留当前页面与旧快照并提示用户。 | LRU 只清理生成中心前缀下的最旧项目，不触碰其他模块；配额淘汰会验证删除结果以避免无限重试。读取禁用、写入失败和损坏快照均显示每项目去重警告；旧 v1 快照补齐新增表单字段，项目切换先保存旧状态再恢复目标项目。定向 63 项与前端完整 1077 项 Vitest 通过。 |
| U6 router.js 快速导航竞态 | **已修复**。A→B→A 的项目同步会取消前一请求，并以代次阻止旧请求继续提交 metadata、view/subview、hash 与渲染；项目强制同步绕过应用内 30 秒 GET 缓存，也不让过期响应写回缓存。 | `popstate` 在初始 metadata 等待前绑定且全局只绑定一次；即使 transport 忽略 abort 并返回成功，API 层仍按取消处理。定向 51 项与前端完整 1084 项 Vitest 覆盖乱序导航、取消静默、初始化抢占、no-store 和真实 signal 传递。 |
| U4 模态框 ARIA 三重缺失 | **已修复**。共享 `modal-content` 声明 `role="dialog"`、`aria-modal="true"` 和 `aria-labelledby="modal-title"`；关闭按钮有显式类型和可访问名称。显示模态时焦点优先进入正文控件或操作区，Tab/Shift+Tab 被约束在可见可用控件之间。 | Escape 在输入控件内同样关闭模态；关闭恢复原触发控件，模态内容连续替换不会把模态内部元素误记为触发点，触发控件已移除时安全跳过。禁用、hidden、`aria-hidden`、`inert` 及 CSS 隐藏祖先下的控件均不参与焦点选择。定向 90 项与前端完整 1091 项 Vitest 通过。 |
| U5 编辑器中无脏状态保护 | **已修复共享模态路径**。`worldView.js`、`outlineView.js` 及其他复用共享模态的表单无需各自复制状态机；打开时记录 input、textarea、select、checkbox/radio、multi-select 与 contenteditable 的控件身份和值，关闭时只对真实可编辑差异确认放弃。修改后恢复原值、disabled/readonly/hidden/inert/CSS 隐藏控件及显式 `protectUnsaved: false` 不提示。 | 关闭按钮、自动/自定义取消、遮罩和 Escape 共用保护；成功 action 免确认，返回 false 或异常保持表单。按 modal generation 隔离并发 action：异步保存期间用户仍需确认，保存后显式关闭不误提示，旧 action 不能关闭替换后的新弹窗。定向 51 项、受影响范围 322 项与前端完整 1113 项 Vitest 通过；真实 Chromium 临时核对 multi-select、contenteditable 和恢复原值行为。 |
| U2 各 View 的 `setTimeout` 竞态 | **已修复真实绑定竞态，原始数量与归因已修正**。当前生产前端有 18 处 `setTimeout`；轮询、重试退避、自动保存、防抖、拖拽状态释放、Leaflet/布局初始化和短暂提示具有明确生命周期，不属于绑定竞态。已确认的问题是 view 返回 HTML 后用零延时定时器猜测 DOM 已提交，以及同步模态或视图自身已写入 DOM 后仍延迟绑定。 | 路由在新鲜 HTML 提交后调用 `onRendered()`，keep-alive DOM 恢复只调用 `onActivate()`；项目、写作、世界、大纲、Scene、RAG、生成、设置和地图工作区均使用该确定性生命周期。同步模态和地图视图自身提交的 DOM 立即绑定；同步确认不会在 Promise 已 settle 后泄漏取消监听器。定向 18 个文件 732 项、完整前端 59 个文件 1117 项 Vitest 通过，静态扫描未发现剩余 delayed event-binding timer。 |
| O4 DomainError 不记录日志 | **已修复**。异常处理器在不改变响应的前提下记录安全结构字段：4xx 为 INFO、5xx 为 ERROR；route 使用框架路由模板而非实际 URL，method/code 均有长度与字符门禁，畸形或非 HTTP scope 安全降级。 | 真实 ASGI 参数化路由与 `_TimingMiddleware` 测试证明动态 ID、领域消息和恶意控制字符不进入日志，且每个 DomainError 只记一条目标日志；5xx 不附 traceback，避免泄露 cause。第二十七批进一步把未知异常兜底收紧为白名单异常类型和有界 frame 位置，不记录异常正文、cause chain 或源码行。 |
| O2 无请求日志中间件 | **已修复**。现有 `_TimingMiddleware` 扩展为最外层安全 access logger，因此正常响应、4xx/5xx、流式响应结束、CORS 预检和 access-token/XHR 短路都保留一条完成或失败记录；非 HTTP scope 不记录。 | 日志只含经过字符/长度门禁的 method、FastAPI route template、status 与 duration；动态 path 值、query、body、header、token、异常消息和响应内容均不进入日志，预路由响应使用 `<unresolved>`。5xx/异常记 ERROR，其余记 INFO；`X-Request-Time-Ms` 保持恰好一个。定向 44 项、完整 fast-test 3334 项及 RuntimeWarning/Ruff 门禁通过。 |
| O1 日志中几乎无 `novel_id` 上下文 | **已修复当前 HTTP/worker 关联边界**。最外层 HTTP scope 和每个 worker attempt 建立独立 ContextVar；project facade 只有在 active/context 查询成功后才绑定规范化 UUID，成功的项目路径响应也可绑定。claim 阶段只把存在的任务 owner 标为 `<unverified>`，门禁失败、畸形或缺失 meta 不会伪装成可信 ID。 | access、DomainError、未知 500 和 worker lifecycle 日志携带安全 `novel_id` 或占位符；未知 500 只记录白名单异常类型与有界 frame 位置，不记录异常正文/cause/source line。review 修复了预门禁信任 meta、实际 preflight seam 未绑定、异常与控制字符回显及 xdist 随机参数收集漂移。定向 183 项、完整 2-worker fast-test 3444 项通过，生产覆盖率 86.44%。范围只覆盖当前请求/attempt，不宣称提供跨进程 distributed tracing。 |
| D2 `start.sh` 未启动 worker | **已修复**。旧脚本不再复制一套缺少 worker 的后台启动逻辑，而是从任意工作目录安全委托权威 dev stack；`PYTHON` override、含空格路径、PID、信号和退出码均保持。 | `start_stack()` 明确启动 backend、worker、frontend；worker/frontend/pidfile 任一步失败会逆序回滚。启动及数据库健康等待期间响应 SIGINT/SIGTERM，回收前台 CLI 和已启动进程，分别返回 130/143；父信号优先于清理产生的子进程退出码。14 项无 Docker/真实服务定向测试、完整 fast-test 3323 项和 RuntimeWarning 门禁通过。 |

### 已失效、被夸大或需重新立证的原始项

| 原始项 | 复核结论 |
|---|---|
| #1 API Key 曾提交 | 历史中确有已删除的 `sk-placeholder`，但它不是需要吊销的真实密钥，且当前 `backend/.env` 未跟踪并已忽略。无需仅为占位符重写公开历史；当前树的敏感文件与高置信凭据防回归门禁已完成。若未来发现真实凭据，仍必须独立吊销、轮换并评估历史清理。 |
| #9 领域事件机制、#11 `showModalHtml` | 都是设计/质量改进，未证明阻塞当前主流程。`showModalHtml` 仍要求调用方转义，应在发现未转义动态输入时按安全缺陷处理，而不是机械重构全部调用点。 |
| #14 embedding cache key 缺模型名 | 当前 BGE client 与内存 cache 同属进程内单例；模型路径只在 client 构造时读取，关闭会清空 cache，运行时也没有不重建该单例的 embedding 模型切换入口。原报告的旧向量路径无法复现；将来若新增热切换，必须同时以模型身份隔离或清空 cache，再针对新路径立项。 |
| #12 LLM 前端 15s 超时 | **已修复**：当前 LLM 请求使用 90 秒 timeout。 |
| #15 无删除撤销系统 | **原始描述已过时**：writing 删除为软废弃且保留版本历史；Scene 工作台的权威删除语义是 `deprecated`；顶层地图现为软归档并支持 impact/restore。marker、terrain layer、binding、territory 等可重建局部素材仍有显式删除，不需要因此建立通用 undo 系统。 |
| S1 CSRF 仅依赖 `X-Requested-With` | 论证不准确：当前不是 cookie 会话，且该头不能抵御同源 XSS。将来若改为 cookie 身份体系，再单独设计 CSRF 防护。 |
| S6 rag/metrics 无路由级认证 | 已由全局 access-token 中间件在配置 `APP_ACCESS_TOKEN` 时覆盖；是否需要额外路由级限制取决于未来指标暴露策略。 |
| S7 迁移/运行时共用 DB 用户 | 原论证未成立。Alembic 与 runtime 是独立进程；二者都读取 `DATABASE_URL` 不代表部署时必须注入同一账号。当前缺少的是未来正式部署的最小权限 runbook 与验收证据，不能据此认定代码强制 DDL/DML 共用账号。 |
| T4 Memory/RAG 无 API 层测试 | **原始描述已失效**：两个模块当前都有 `tests/test_api.py`，分别覆盖全部 Memory 路由的回收站项目门禁，以及 RAG query/body scoped 路由和全局工具豁免；完整 fast-test 会实际收集并执行这些测试。是否继续扩充成功路径覆盖应按真实回归风险决定，不再以“零 API 测试”立项。 |
| D4 本地 Compose 明文密码、D5 无 `.dockerignore` | D4 的 `novel_dev_pass` 是本地 Compose/.env 示例配套开发凭据，未证明生产 secret 泄露；D5 在仓库无 Dockerfile 时没有构建消费者。两项当前均不构成独立代码缺陷，正式容器方案确定后再重新立证。 |

### 排期结论

1. **#1（凭据防回归）与 #3（生产 Mock）已完成**；**#2（仓库门禁）** 的 workflow 已完成并在等价干净环境中验证，剩余 GitHub 分支保护设置须获得远端授权后独立处理。`make format` 因 27 个存量未格式化文件暂未进入 CI，应另开纯机械批次形成干净基线后再启用。
2. **S4 已完成**：本地/测试环境可关闭 LLM RPM，非本地 API 与所有 worker 启动形态必须显式配置正值并 fail closed；具体数值仍按 provider 配额部署。反向代理/TLS 终止层还必须满足 #4 的 direct-peer 与 #5 的可信 scheme 部署约束。
3. #1/#4/#5/#6/#7/#13/#16/S3/S4/S5/S8/T1/T2/T3/T5/T6/U1/U2/U3/U4/U5/U6/U7/O1/O2/O4/D2 已完成；#14 与 T4 的原始描述已失效；#10 当前确认的 Scene workbench 未知 500 泄露路径也已完成，不据此批量替换已校验的 4xx 用户消息。MOBI/AZW3 解析依赖缺失作为独立兼容性 backlog 处理，不回退 S3 内容门禁。
4. 合理暂缓项是 #2（远端设置）、#8、S2、D1、D3、O3、O5；其中 #2 需要外部授权，其他项需要正式部署目标、系统性前端迁移或外部运维方案。S7、D4、D5 当前论证不成立，不作为该部署批次的既定缺陷；任何重新启动的工作须针对实际部署配置重新验证。

---

## P0-CRITICAL（8 项）

| # | 标题 | 位置 | 描述 | 工作量 |
|---|------|------|------|--------|
| 1 | API Key 曾提交至 Git 历史 | `backend/.env` | 占位符密钥 `sk-placeholder` 在 `ee3290966` 提交，后于 `87144222a` 删除。非真实密钥但环境文件进历史是不安全实践 | 2h |
| 2 | 零 CI/CD + 无分支保护 | 项目根 | 任何变更直接合入 main，无测试/审查门禁 | 4h |
| 3 | Mock-in-production | `imports/workflow.py:17`, `orchestrator.py:514,541`, `extraction_service.py:81` | 9 处 `isinstance(db, Mock)` 改变生产行为，测试未验证真实路径 | 3h |
| 4 | 无 HTTP 速率限制 | 全局（FastAPI 应用） | 任何客户端可耗尽连接池、压垮 LLM | 3h |
| 5 | 后端完全缺失安全响应头 | `main.py` 中间件 | 无 HSTS/X-Frame-Options/X-Content-Type-Options | 2h |
| 6 | 3 处 `except Exception: pass` | `rag/query_expansion.py:65`, `world/entity_alias_service.py:181`, `world/suggestion_queue_service.py:680` | 纯 `pass` 掩盖错误，无日志记录 | 2h |
| 7 | pg_trgm fallback 缺 `db.rollback()` | `world/repositories.py:158-165,725-728` | 错误后直接 fallback，session 处于错误状态 | 2h |
| 8 | 无 Dockerfile | 项目根 | 零容器化部署路径 | 4h |

### P0 快速修复总工作量: ~22h

---

## P1-HIGH（Top 20）

| # | 标题 | 位置 | 描述 | 工作量 |
|---|------|------|------|--------|
| 9 | 领域事件机制缺失 | `writing/tasks.py` publish_chapter handler | RAG 索引→内存快照硬编码顺序，无法扩展 | 8h |
| 10 | 50+ 处 `detail=str(exc)` 泄露异常 | 7 个 api.py 文件（21 处） | 暴露 SQL/路径/内部细节给客户端 | 3h |
| 11 | `showModalHtml` 依赖调用方转义纪律 | `modal.js:107` | 74 处 innerHTML 中大部分已转义，但无法强制 | 2h |
| 12 | LLM 生成 API 前端 15s 超时 | 前端 `api.js` | AI 生成需 60-120s，前端超时远低于实际 | 1h |
| 13 | 2 个 dict body 端点 | `imports/api.py:281,308` | `body: dict = Body(...)` 绕过 Pydantic 校验 | 2h |
| 14 | 嵌入缓存 key 缺模型名 | `embedding/cache.py:28-30` | 切换模型最多 1h 返回旧结果 | 1h |
| 15 | 无删除撤销系统 | world/outline/writing 模块 | 章节/场景/剧情线/伏笔/揭示硬删除 | 12h |
| 16 | CSS 骨架屏已定义但零使用 | `styles.css:3165-3186` + 各视图 | 5 个视图用"加载中..."文本，骨架屏完全浪费 | 2h |

### P1 Top 20 修复总工作量: ~31h

---

## 🔒 安全 P1-HIGH（8 项）

| # | 标题 | 位置 | 描述 | 工作量 |
|---|------|------|------|--------|
| S1 | CSRF 仅依赖 X-Requested-With | 全局中间件 | 同源 XSS 可绕过 | 3h |
| S2 | CSP style-src 'unsafe-inline' | `index.html:6` | 削弱 XSS 防御 | 1h |
| S3 | 文件上传无 MIME/幻数验证 | `imports/upload` | `.exe` 重命名即接受 | 2h |
| S4 | LLM_RATE_LIMIT_PER_MINUTE=0 | `config.py:141` | 默认无限流 | 0.5h |
| S5 | Bearer Token 明文存 sessionStorage | 前端认证 | XSS 可窃取 token | 4h |
| S6 | rag/metrics 端点无路由级认证 | `rag/api.py:143` | 仅依赖可选全局中间件 | 1h |
| S7 | 数据库单用户运行迁移和运行时 | `alembic.ini` + config | DDL+DML 共用同一账号 | 2h |
| S8 | APP_DEBUG vs DEBUG 不匹配 | `config.py:234` + `.env.example:23` | .env.example 的 APP_DEBUG 从未被读取 | 0.5h |

### 安全修复总工作量: ~14h

---

## 🧪 测试 P1-HIGH（6 项）

| # | 标题 | 位置 | 描述 | 工作量 |
|---|------|------|------|--------|
| T1 | core/shared 层测试覆盖不足 | `core/dependencies.py`, `shared/` | core 有部分测试但 dependencies.py 和整个 shared 零覆盖 | 6h |
| T2 | 10 处 `@pytest.fixture` + `async def` 误用 | e2e + unit 测试文件 | 应与 `@pytest_asyncio.fixture` 一致 | 1.5h |
| T3 | 无 pytest-xdist 并行 + pytest-timeout | `pyproject.toml` | 串行执行、无挂起防护 | 1h |
| T4 | Memory/RAG 无 API 层测试 | `modules/memory/tests/`, `modules/rag/tests/` | 两个模块缺少 `test_api*.py` | 4h |
| T5 | 跨模块 E2E 串行场景缺失 | E2E tests | 各模块有碎片化 E2E 但缺完整流程（导入→生成→发布→检索） | 6h |
| T6 | 无 pytest-cov 阈值/报告配置 | `pyproject.toml` | 已安装 `pytest-cov` 但未激活 | 1h |

### 测试修复总工作量: ~19.5h

---

## 🚀 部署 P1-HIGH（5 项）

| # | 标题 | 位置 | 描述 | 工作量 |
|---|------|------|------|--------|
| D1 | 无 gunicorn/多 worker 配置 | 项目根 | 零生产级启动配置 | 3h |
| D2 | start.sh 未启动任务 worker | `start.sh` | 后台任务不处理 | 0.5h |
| D3 | 无反向代理（nginx/Caddy） | 项目根 | 无 TLS/静态文件服务 | 4h |
| D4 | POSTGRES_PASSWORD 明文硬编码 | `docker-compose.yml:14` | `novel_dev_pass` 明文 | 0.5h |
| D5 | 无 .dockerignore | 项目根 | 构建上下文过大 + 含 .env | 0.5h |

### 部署修复总工作量: ~8.5h

---

## 🎨 用户体验 P1-HIGH（7 项）

| # | 标题 | 位置 | 描述 | 工作量 |
|---|------|------|------|--------|
| U1 | HTTP 409 未在前端 errorMap 映射 | `api.js:202-210` | 显示"请求失败 (409)"而非业务消息 | 2h |
| U2 | 11 处 `setTimeout` 竞赛条件 | 各 View.js | 依赖微任务调度，重复绑定/丢失绑定 | 6h |
| U3 | 大纲子视图错误静默吞掉 | `outlineView.js:207-240` | 4 处 `.catch` 仅清空数组，无 toast/内联错误 | 2h |
| U4 | 模态框 ARIA 三重缺失 | `index.html:165` + `modal.js` | 无 role="dialog"、无焦点陷阱、无 aria-labelledby | 3h |
| U5 | 编辑器中无脏状态保护 | `worldView.js`, `outlineView.js` 表单 | 取消/关闭即丢失输入 | 4h |
| U6 | router.js 快速导航竞态 | `router.js:276-306` | A→B→A 时慢请求覆盖新项目。无 AbortController | 3h |
| U7 | generateView localStorage 无大小限制 | `generateView.js:1093-1150` | 无 LRU/大小限制，超限时用户数据静默丢失 | 2h |

### UX 修复总工作量: ~22h

---

## ⚙️ 运维 P1-HIGH（5 项）

| # | 标题 | 位置 | 描述 | 工作量 |
|---|------|------|------|--------|
| O1 | 日志中几乎无 novel_id 上下文 | 全局日志 | 65+ logger 模块，仅 1 处记录 novel_id | 4h |
| O2 | 无请求日志中间件 | `main.py` | 零 access log、无审计轨迹 | 2h |
| O3 | 无外部指标系统 | 项目根 | 零 Sentry/Prometheus/Datadog | 8h |
| O4 | DomainError 处理器不记录日志 | `main.py:307-318` | 对比 global_exception_handler 有 `logger.exception` | 0.5h |
| O5 | 无备份策略 | `docker-compose.yml` | 无 pg_dump 脚本、无 cron | 2h |

### 运维修复总工作量: ~16.5h

---

## 📋 汇总

| 类别 | 项数 | 总工作量 |
|------|------|---------|
| P0-CRITICAL | 8 | ~22h |
| P1 Top 20 | 8 | ~31h |
| 安全 P1 | 8 | ~14h |
| 测试 P1 | 6 | ~19.5h |
| 部署 P1 | 5 | ~8.5h |
| UX P1 | 7 | ~22h |
| 运维 P1 | 5 | ~16.5h |
| **总计** | **47** | **~133.5h** |

### 原始按阶段建议（已废止，由文首复核分诊取代）

> 以下内容仅保留原始报告追溯性，不再作为当前排期依据。

**立即（1-2 天）：** #1，#2，#3，#4，#5，#6，#7 + S4，S6，S8，D2，D4，D5
**短期（1 周）：** #8，#10，#12，#13，#14，#16 + S1，S3，S5，T1，T3，T6，D1，D3，U3，U7，O2，O4
**中期（2-4 周）：** #9，#11，#15 + S2，S7，T2，T4，T5，U1，U2，U4，U5，U6，O1，O3，O5
