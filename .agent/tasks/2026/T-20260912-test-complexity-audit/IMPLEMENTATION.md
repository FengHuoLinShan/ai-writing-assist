# 回归基线精简实施结果

2026-09-12，用户在审计后明确授权“直接进行修改优化”。基于 `a8c331024`，分支 `codex/test-baseline-simplification`。只修改测试、测试工具、CI 分类和维护说明；没有改产品服务、真实数据、依赖版本、覆盖率或像素阈值，也未提交、合并、推送、部署。

## 逐项结果

| 审计项 | 实施结果与保留边界 |
| --- | --- |
| A01 CSS 写法快照 | 删除装饰性属性顺序、字距、旧样式名和动画时长等断言；增加真实 Chromium 的共享样式可访问性检查。保留尚有保护意义的滚动、安全区、对比度、组件触控/焦点检查，没有整文件批量删除。 |
| A02 转发测试 | 删除 character facade 五份重复异常透传用例；保留参数转换、novel_id/知识边界参数、返回形状与有效边界用例。对有实际 UUID/返回转换的其他 facade 保留检查。 |
| A03 视觉全栈准备 | 调整原方案：新增 `npm run test:e2e:styles`，仅 Vite+Chromium，无数据库/账户/后端；普通 CSS 改动使用此入口。整页截图继续复用真实种子。全面 mock 八个业务面会再造一份业务 API，反而增加本次要消除的复杂度，因此不实施整套 mock 替换。 |
| A04 CI 镜像配置测试 | 删除固定日程、显示名称、job 顺序和 runner 等无关精确值；保留必要 job、最小权限、触发事件、唯一 concurrency、Action SHA 与重大依赖升级独立审查。 |
| A05 工具链常量复制 | 版本从现有文件读取，验证镜像 tag+digest、版本/示例一致性；删除测试中重复写死的版本/摘要及 Dockerfile 写法。保留非 root、只读、健康与实际镜像运行命令的安全检查。 |
| A06 JS 自制解析器 | 用已安装 ESLint/Vue parser 替代字符串状态机；新增嵌套模板、Vue 模板和可选链覆盖，保留 API method/path/requiredBody 检查。 |
| A07 CSS 平行作用域表 | 移除 owner/consumer/injector 白名单；静态层仅校验变量声明词汇，真实浏览器检查代表性继承变量，不再声称字符串扫描能证明 DOM 作用域。 |
| A08 冻结集合 | facade 与 Prompt 合同清单改为必要旧能力子集检查，允许兼容新增；仍检查 facade 导出与实现自洽、禁止的 schema 泄漏及 registry 校验。保留旧接口清单作为兼容保证，不为净减行数删除。 |
| A09 fixture 拼写检查 | 删除异步 fixture 装饰器 AST 扫描与自测，允许 asyncio auto 模式支持的两种写法；保留真实隔离/清理测试。 |
| A10 autospec 例外 | 保留默认 autospec=True；允许调用结束行的 `# autospec-exempt: 具体原因`。用 Python tokenize 只接受实际注释；空说明和伪装在字符串里的注释均拒绝。没有给现有测试新增豁免。 |
| A11 普通赋值测试 | 删除 RagChunkContract 全字段构造后原样读回的冗余用例；保留公开默认状态、可见性和不可变等实际契约。 |
| A12 Prompt 措辞冻结 | 删除本次确认的自然语言修辞/换行/句数长度断言；保留正文/设定进出、确认来源、无写入和输出 schema 等行为验证。 |
| A13 CI 范围 | 测试源码只选所属质量层，后端 E2E 测试另选 PostgreSQL；截图 PNG 不触发业务/镜像测试。共享 fixtures/support、未知路径、构建输入仍按原重层执行，混合变更取并集。 |
| A14 文档影响 | 普通实现改为 advisory；API/schema/facade/tasks/wire 等稳定边界保留硬门禁。覆盖子目录和 *_api/*_facade 路径，排除测试源码，并验证正反例。 |
| A15 重复目录 | 表、路由、任务各检查一个权威文档；取消在模块设计/README 重复列全量表名。未删除现有有效领域说明。 |
| A16 重复文档扫描 | 删除后端测试中的真实全库 inventory 调用；docs-check 继续独立执行，checker 合成输入/错误路径测试保留。 |
| A17 截图辅助重复 | 八份 visual spec 共用字体就绪、toast 等待、主题设置和平台判断；移除重复后端 health 等待、双 RAF 和主题固定 sleep；原截图名、区域和基线保留。真实数据库排序所需的 1100ms 等待未用伪造时间或更多 mock 代替。 |
| A18 无必要数据库 fixture | character facade 的纯 mock/schema 测试改用 sentinel 参数，不再建立无关 SQLite schema；其他真实数据库用例未改。 |

额外修复两处本次验证发现的测试问题：视觉配置的 reducedMotion 应放在 `contextOptions` 才生效；performance probe 的拒绝重定向测试应把 ROOT 指向临时目录，避免本地 `.env` 抢先触发另一保护分支。两处均保留原保护断言。

报告中的五项政策候选未被当成删除授权：85% 覆盖率、0.5% 像素阈值、95 张 macOS 图片、鉴权/预算静态门禁和全局隔离策略均保留。仅去除覆盖率数值的重复元测试锁定。

## 验证

- 前端完整 Vitest：185 文件、2424 测试通过。
- 后端完整 coverage 层：5414 passed、13 skipped，覆盖率 **85.75%**，满足未改动的 85% 门禁；RuntimeWarning 按 error 执行。另有 11 条 ResourceWarning 等诊断未隐藏，不能称无警告。
- 最后文档规则/测试基础设施调整另跑定向测试；不因纯规则变更重复整套覆盖率。
- 部署契约：270 passed；secret hygiene、backend Ruff、frontend ESLint 通过。
- 后端锁文件审计无已知漏洞，但提示 `langchain-community` 已归档；前端锁文件审计 0 vulnerabilities。没有增加依赖或扩大豁免。
- 无数据库样式浏览器：浅/深两种模式均通过，约 2.4 秒的单次本地记录；不是与旧全栈检查的等价性能基准。
- `make docs-check BASE_REF=origin/main` 与 `git diff --check` 最终结果在 TASK.md 更新。

## 视觉基线的实际限制

当前与未修改 `a8c331024` 的全部视觉收集均为 **38 tests / 8 files**，95 张已跟踪基线没有改动。整套当前视觉运行在第三个失败后按 max-failures 停止：2 passed，3 failed，33 未运行；随后定向复核 experience 文件。不能声称全套视觉通过。

在本次临时 PostgreSQL 库上，对未修改的 detached worktree 使用原配置和原测试复跑，重现相同三个失败。当前与原版本的对应 actual PNG 经 SHA-256 比较，**三张逐字节相同**：

- `story-mobile-light-actual.png`
- `story-mobile-dark-actual.png`
- `map-empty-mobile-light-actual.png`

这些是已有截图漂移，不是本次测试精简引入的差异；没有放宽阈值或覆盖 expected 图片。现有实际/差异图留在本地忽略目录 `frontend-console/test-results/visual/`。其余未运行截图不作通过声明。

专用容器 `novelcraft-test-baseline-audit` 使用本地可用的 pgvector 0.8.2 / PostgreSQL 17、独立端口和 tmpfs 数据；不是生产镜像固定版本验收。未触碰开发库及《诡秘之主》持久验收库。对照 worktree 与该容器均为本任务创建，结束时清理。

## 交付边界

测试/工具及对应说明净减约 740 行（不计本审计材料），新增一个轻量样式入口和共用视觉 helper，无新依赖。原报告是候选审计，不应把它的全部建议机械变成删除清单；本表记录了实际执行、修订方案与明确保留项。

仅本地实现。旧截图漂移与未执行的完整浏览器/生产镜像验收仍然公开记录；本次不做上线、更新图片或合并授权推断。
