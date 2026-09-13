# ROOT 独立代码审查

日期：2026-09-12。审查对象：主代理指定的 RedesignApp、Search、Structure、Map、Settings、Reader、VersionReview、Assistant、Identity、Workspace 及 workspace-details.css。只读代码审查，未进行浏览器操作；不把未接真实业务本身判为缺陷，也未审查本代理负责的 Writing/Candidate/Import/World。

| 优先级 | 位置 | 触发 | 影响 | 最小建议 |
|---|---|---|---|---|
| P1 | RedesignApp.vue:33,57-64,161 | 直接寻址或试图导航 `assistant` | 模板虽有 `page === 'assistant'` 分支，但 `pageTitles` 没有 assistant；`navigate` 先拒绝未知页面，预览页选择器也不会列出它，AssistantPreview 的独立页面分支不可达。AI 抽屉仍可达，不应把死分支当作覆盖。 | 要么删掉不可达的独立页分支并明确 AI 只走抽屉，要么把 assistant 加入页面清单并定义返回上下文；选择一个真实入口。 |
| P1 | ReaderPreview.vue:25-26 | 尚未选择分支时直接点击“查看分支反馈示例”，再点击“采用这个发展” | `Math.max(choice,0)` 将空选择伪装成第一个分支；读者可在没有有效选择或输入时采用候选，违反“未选分支与有效分支区别清楚”。 | 只有 `choice >= 0 || readerInput.trim()` 才打开反馈；采用按钮继续禁用至有效选择/明确输入。 |
| P1 | IdentityPreview.vue:14 | 输入任意邮箱、甚至未发送/验证验证码，点击“以演示身份继续” | 直接 emit navigate(intent)，绕过验证码发送/校验状态；“发送失败/验证失败”与可继续进入相矛盾，复核时会误以为身份已确认。 | 将继续按钮绑定到明确的已验证演示状态，失败/等待状态只提供重试和返回；保留当前意图与输入。 |
| P1 | StructurePreview.vue:35-36 | 页面 state=error，点击“重试读取示例” | 只写 `feedback='✓ 重新读取完成 · 演示'`，但 props state 仍为 error，错误提示继续显示；成功反馈与失败状态同时存在。 | 用本地 `retryState` 控制错误提示收起，或按钮文案改为“查看上次示例”，不要同时宣称读取完成。 |
| P1 | SearchPreview.vue:10,44,21-28 | 将“正文范围”切换为“仅正式正文”后查找 | `version` 只绑定选择器，results 计算完全不读取它；工作稿与正式正文返回同一结果，范围控件给出虚假过滤。 | 当前仅做演示时移除未生效的选择，或在结果 fixture 上按 version 过滤并标注示例范围。 |
| P1 | WorkspacePreview.vue:26-29,47,52 | 编辑一个任务/作品后直接打开另一个任务/作品或切换页面 | `editTask`、`editBook` 直接覆盖 active draft；没有脏状态、取消确认或草稿保全。输入会被静默丢弃，尤其不符合计划要求的输入保护。 | 记录编辑 dirty；切换对象/离开前确认，取消保留当前 draft；最小方案是覆盖前调用一次本地确认。 |
| P2 | workspace-details.css:1-19,20-33 | 不支持 CSS Nesting 的浏览器或构建检查 | 文件以 `#redesign-root { ... }` 包住整段普通选择器，且同一文件重复打开嵌套块；依赖原生 CSS Nesting，旧浏览器/静态解析可能整段规则失效，导致详情布局和窄屏规则丢失。 | 使用普通完整选择器 `#redesign-root .rd-...`，或明确构建目标已保证 CSS Nesting；不要用未验证的嵌套作为唯一样式来源。 |
| P2 | RedesignApp.vue:58-70,150-153 | 从 writing 打开 search/settings 等页面再返回 | `navigate` 只保存当前滚动，不保存各页的 section/对象/选区；返回按钮只使用单个 `previousPage`，多次跨页后可能回到最后一个页面而不是原始任务上下文，且每次导航将 state 重置为 normal。 | 为跨域返回记录入口页＋section/对象；至少让 Search/Settings/来源返回携带原入口，避免把单一 previousPage 当完整返回栈。 |
| P2 | SettingsPreview.vue:11-18,23-30 | 连接模型服务后切换到图片服务，或反向切换 | `connection` 是两类服务共用的单一 ref；一类服务的“验证通过/失败/验证中”会显示在另一类服务页面，身份与状态不一致。 | 按服务类型拆两个最小状态 ref，或切换服务时重置 connection；不要把一个验证结果复用给两种服务。 |
| P2 | ReaderPreview.vue:21-22,24-30 | state=loading/error 与 stage 手动反馈同时存在 | state=loading 只增加等待提示，reader 正文仍渲染；state=error 也继续显示正文并同时允许“重试示例”。这可以是“已读内容保留”的设计，但当前没有明确区分服务错误与正文可读状态，且 state 变化不会重置 stage。 | 给等待/错误卡明确“已读内容仍可读”层级，并在 props state 变化时同步本地 stage；保留正文是设计选择，不要让两个状态文案互相覆盖。 |

## 可复用点

- RedesignApp 已集中 KeepAlive、主题、减少动态效果、dialog/抽屉焦点、跨域 navigate 和候选对象映射；后续应修补这些接缝，不另建状态引擎。
- Search 的来源详情已有焦点回还、定位原章和来源过期表达；Structure/Map/Reader 已使用手动状态推进，符合不以动画伪造成功的原则。
- Assistant 已把快捷意图、自然语言、任务结果、批次审阅和提醒放进同一视觉体系；VersionReview 已明确“采用工作稿”与“正式正文确认”分开。
- workspace-details.css 已有统一的详情、比较、表格和窄屏规则，但需要验证 CSS 作用域/嵌套兼容性后再作为共享样式依据。

## 限制

本报告仅依据源码和行号，未浏览器实看，未判断截图、焦点实际回还、窄屏溢出、CSS 编译结果或动画中间帧。上述建议均为最小修补方向，不要求在设计阶段接真实 API、作品、身份、模型或任务服务。
