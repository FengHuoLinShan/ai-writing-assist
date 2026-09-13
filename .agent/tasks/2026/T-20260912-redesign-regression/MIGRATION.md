# 视觉断言迁移与保留记录

旧文件来自执行前工作树副本（含前轮未提交精简）。35 个场景声明，其中 experience 的3个场景各跑浅/深色，合计38个旧视觉用例。纯像素/几何/组件结构断言撤除；下表记录有效功能断言的已有或新增去向。测试标题可用 Playwright `--grep` 定位，后续可随入口变化适配定位器。

| 原文件/场景 | 行为套件/场景 | 保留结果 |
| --- | --- | --- |
| visual-generate: 任务上下文 × 浅／深色与手机 | `generate.spec.js`：任务草稿可跨类别、刷新和浏览器前进恢复，并按项目隔离 | 任务输入、跨类别/刷新恢复 |
| visual-generate: AI 参考资料审阅 × 桌面与手机 | `generate.spec.js`：参考资料审阅保留任务、来源和未覆盖提醒 | 迁入：4类参考资料、未覆盖提醒、完整来源读取 |
| visual-generate: 世界设定参考资料栏 × 桌面与手机 | `generate.spec.js`：手机参考资料栏支持键盘、刷新、历史和作品隔离 | 参考选择/恢复；展开方式不再是约束 |
| visual-generate: 世界建议使用主栏审阅 | `generate.spec.js`：粘贴外部对话后生成世界对象建议 | 同一任务结果的名称、待处理状态、确认与进入队列 |
| visual-generate: 世界设定共创输入区 × 桌面、手机与矮窗口 | `generate.spec.js`：世界共创输入区在桌面、手机和矮窗口不遮挡操作 | 输入保留、发送可命中；失败/防重另有同域用例 |
| visual-generate: 角色视角正文表单 × 桌面与手机 | `generate.spec.js`：角色视角正文保留表单、路由位置和项目隔离 | 章节/Scene/角色选择与指令恢复 |
| visual-outline: outline 小说总纲 × 浅／深色 | `outline-scenes.spec.js`：已有故事总览可连续阅读并安全回看过往版本 | 总纲标题、内容与版本；移除时间文本覆写 |
| visual-outline: outline 篇章纲 × 浅／深色 | `outline-threads-arcs.spec.js`：创建篇章并显示在列表中 | 篇章创建/读取 |
| visual-outline: outline 剧情线 × 浅／深色 | `outline-threads-arcs.spec.js`：创建剧情线并显示在列表中 | 剧情线创建/读取 |
| visual-world: world 对象库 × 浅／深色 | `world.spec.js`：对象库分页 | 种子对象列表与计数/翻页 |
| visual-world: world 待处理（对象队列）× 浅／深色 | `world.spec.js`：待处理对象可微调后采用 | 候选读取、微调和采用 |
| visual-world: world 待处理直达建议 × 桌面与手机 | `world.spec.js`：待处理深链在桌面与窄屏读取同一候选 | 迁入：精确候选深链及决定内容 |
| visual-world: world 世界书 × 浅／深色 | `world-bible.spec.js`：页面创建、正文保存、投影刷新、审核弹窗和子视图切换都可用 | 世界资料创建/内容保存/阅读 |
| visual-world: world 世界书 × 手机宽度 | `world-bible.spec.js`：390px 下世界书表单、操作区和 AI 转交入口保持可用 | 窄屏资料填写、保存与转交 |
| visual-writing: should preserve the populated writing desk across light and dark modes | `themes.spec.js`：手机资料与主题切换保留正文；写作内容可保存恢复 | 编辑、主题切换后的内容与保存恢复，不固定DOM身份 |
| visual-writing: should preserve writing advice entry on desktop and mobile | `writing.spec.js`：AI 写作建议按当前正文给出主操作，任务可收起并回到审阅 | 建议入口与处理结果 |
| visual-writing: should preserve the writing view menu on desktop and mobile | `writing.spec.js`：专注模式可恢复、可退出，并在桌面与手机保持正文状态 | 视图菜单键盘与焦点恢复 |
| visual-writing: should preserve the centered paper in focus mode | `writing.spec.js`：专注模式可恢复、可退出，并在桌面与手机保持正文状态 | 专注切换、退出、正文状态 |
| visual-writing: should preserve version history on desktop and mobile | `writing.spec.js`：版本历史查看与恢复 | 版本读取、对比正文、焦点、取消确认、恢复新版本 |
| visual-writing: should preserve the 390px mobile editor | `writing.spec.js`：390px 下短文本可保存为工作稿并在刷新后恢复 | 手机读写保存 |
| visual-writing: should preserve the 390px complete editor | `writing.spec.js`：390px 抽屉开关与跨作品导航保留正文和编辑会话 | 资料退出、正文恢复、项目隔离 |
| visual-writing: should keep candidate decisions ahead of read-only prose | `writing.spec.js`：AI 建议在刷新和返回后仍先决策，采用前可取消确认 | 候选只读、对比、采用确认 |
| visual-writing: should keep save recovery visible on desktop and mobile | `writing.spec.js`：保存与切章失败时保留正文并可在桌面和手机重试 | 保存失败后的正文、恢复入口和重试 |
| visual-project-rag: 项目页 × 浅／深色 | `project.spec.js`：作品搜索按当前输入显示匹配结果 | 迁入：两项目搜索结果与过滤，去除截图排序等待 |
| visual-project-rag: rag 状态页 × 浅／深色 | `rag.spec.js`：修复查找页面优先展示用户可理解的状态 | 未准备状态与修复入口 |
| visual-project-rag: rag 检索结果页 × 浅／深色 | `rag.spec.js`：58 条证据按 20 条渐进展示并由 URL 前进后退恢复 | 20条分页、原文、来源、筛选和返回恢复 |
| visual-project-rag: AI 工具查找资料首屏 × 桌面与手机 | `rag.spec.js`：AI 工具内查找保留抽屉、搜索状态和手机安全边界 | AI内查找、状态恢复与关闭焦点 |
| visual-settings: 账户设置页 × 浅／深色 | `settings_flow.spec.js`：账户页可直达并同时提供模型连接与作者偏好 | 账户设置、连接和创作偏好 |
| visual-settings: 项目设置页 × 浅／深色 + 两个 Tab | `settings_flow.spec.js`：项目设置页深链 + Tab 切换 | 作品偏好、专家字段、保存/刷新和键盘语义 |
| visual-settings: 账户与项目设置保持单栏且无横向溢出 | `settings_flow.spec.js`：项目偏好加载失败可重试，切换作品前保护未保存输入 | 项目范围与恢复；窄屏旧布局不保留 |
| visual-today: should preserve the Today hierarchy across desktop themes and 390px | `author-workspace.spec.js`：写作首页读取当前作品的续写、任务和待决定结果 | 迁入：当前项目续写/计划/待决定数据与数量 |
| visual-experience: 公共入口、认证与外观 ${mode} | `auth.spec.js`：marker 缺失的公开邮箱登录会清除旧账号数据并写入账号 marker | 公共/认证与账号隔离；外观入口由 themes 覆盖 |
| visual-experience: 互动故事与手机阅读 ${mode} | `interaction.spec.js`：双入口进入 RP 列表并打开当前旅程 | 列表、故事内容与主题选择；窄屏读写另有RP用例 |
| visual-experience: 地图首次进入与手机浏览 ${mode} | `map-atlas.spec.js`：结构引导生图先审查 Context 并提交同一 confirmation | 首次进入与任务确认；地图窄屏读取由 map-structure 覆盖 |
| visual-experience: 互动故事使用资源包中的正文字体 | `interaction.spec.js`：导入主题包后互动故事继续使用用户选择的正文资源 | 迁入：导入主题的正文资源作用于故事内容 |

## 单测与普通行为套件

- 删除 CSS 源码/像素专用测试与独立 styles profile；保留旧 PNG，删除平台跳过规则。
- editorialTheme / typographyTokens / loadingSkeleton / rpReadingUx 的键盘、焦点、可读性与 reduced-motion 转由 home / interaction / project 的真实浏览器行为检查承担；取消 token 名称、颜色写法、列数、固定命中尺寸和动画名称约束。
- subnavAccessibility 的导航键盘、选中状态由 home / outline-scenes / outline-threads-arcs / world 的行为与组件测试覆盖；删固定按钮数量和组件归属扫描。
- modalAccessibility 的真实可访问名称与焦点由 home 的账户模态、writing 的版本确认、scene-workbench 的原生对话框行为覆盖；原保存失败、离开保护、重复点击防重单测保留。
- ProjectAssistant 的 can_resume 源码字符串检查改成真实组件状态切换与 resume(false) 调用断言。
- 普通 e2e 的像素/列数/尺寸/DOM归属断言撤除；地图坐标与数据几何编辑仍验证真实领域数据。主题包颜色和字体为用户导入数据的功能效果，保留运行时验证，不检查 CSS 写法或冻结内置外观。
- 旧分页遮挡断言改为实际点击下一页并读取新页；旧长详情滚动几何断言改为矮窗口编辑、保存和刷新读取。
- 首轮和最终验证、环境与限制见 TASK.md。
