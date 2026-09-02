# 写作编辑器 UI/UX 执行规范

> 路由：`writing` 工作台视图（`#workspace-content[data-workspace-view="writing"]`）。
> 唯一权威：本文件是 writing 页的页面级执行规范，遵循 `docs/frontend/uiux/design-standard.md`
>（下称主规范）的内容优先契约 §4、长正文排版 §3.2、Loading 归一 §5.9、点缀系统 §2。
> 事实来源：`frontend-console/vue/views/writing/` 源码（含 `writing-desk.css` 与
> `writing-decorations.css`）与 `e2e/writing.spec.js`、`e2e/visual-writing.spec.js`。
> 所有行号以调研时点的源码为准，漂移时以源码为准并回改本文件。
> 2026-08 三主题、保存恢复、候选决策与专注写作改造已落地：固定三栏、底部状态栏、章节加载边界、
> 保存失败就地重试、AI 建议按当前正文给出下一步、候选先决策后阅读、可恢复专注模式与点缀系统均为当前事实；§2 问题清单内逐条标注了当前状态。

## 1. 页面定位与目标画像

- **定位**：全产品停留时间最长的页面，是画像 A「安心继续创作」核心任务的承载页；也是唯一在全局
  顶栏拥有字数仪表盘（`#topbar-wordcount`）的路由（`vue/shell/components/Topbar.vue`）。
- **目标画像**：画像 A（长期创作的作家）。本页不为画像 B 服务；RP 用户走独立路径（见
  `pages/rp-experience.md`）。
- **用户任务与情绪收益**：作者打开本页时的心理状态是「继续写」，不是「管理作品」。页面必须让作者
  3 秒内确认：写到哪一章、上次保存是否安全、当前场景有哪些相关设定——然后立刻能开始打字。
- **用户会喜欢的理由**（对应 `user-personas.md` §画像 A）：
  - 写作时就地查看人物/地点/警报（副驾驶 rail），不离开当前思路；
  - 草稿三层保护（会话快照 + localStorage 备份 + 离开守卫），页面切换不丢稿；
  - AI 候选只进「待处理」，可先与当前工作稿逐段比较，再由作者采用或拒绝，不静默覆盖正文。
- **主要摩擦（现状）**：details 菜单的展开状态、键盘关闭和触控入口已完成；保存失败恢复、
  切章加载边界、移动端模式切换、专注写作闭环与小字号信息层级均已完成。
- **验证方式**：e2e 场景化验收（§8）；「喜欢」为产品假设，待真实行为数据修正。

## 2. 现状问题清单（按严重度排序）

> 2026-08 复核：样式类条目（5、6、7、13）大部分随 `writing-desk.css` 重写与
> `editorial-theme.css` 瘦身消解；保存恢复条目（1–3）已完成。其余条目保持原状。

### P0 — 直接影响写作安全感

1. **保存失败无恢复路径**：**已解决**。正文附近持续显示 `role=alert` 的作者说明和“重试保存”；
   底部徽标使用错误色，本机备份保持可见，保存失败会阻止切章与发布，成功后恢复正常状态。
2. **正文加载无反馈**：**已解决**。切章期间显示 `.loading-skeleton` 并卸下旧 textarea；失败时
   显示可重试的 `.error-card`。失败目标不写入项目会话指针，旧章正文与工作稿身份保持不变。
3. **保存徽标只读态语义错误**：**已解决**。`saveBadgeClass` 已区分 saving / error / readonly /
   unsaved / saved，只读态使用中性色点，不再沿用绿色已保存观感。
4. **「聚焦模式」测试债**：**已解决**。UI 统一使用「专注模式 / 进入专注 / 退出专注」，功能 e2e
   覆盖刷新、路由往返、作品隔离、Esc 与 390px；视觉基线为 `writing-focus-{sticky,mobile-sticky}.png`。

### P1 — 信息层级与视觉一致性

5. **编辑器头部三行拥挤**：**大部分消解**。字数条、保存/版本状态徽标、字体循环切换与专注按钮
   已移入 38px 底部状态栏（`.writing-statusbar`）；版本选择条保留在编辑器上方工具区。
   编辑器头收敛为标题组 + 主按钮行 + context 行（版本条 + 冲突条）；版本条只保留选择和
   “版本历史”，重复的外层“比较”已删除，比较能力保留在历史弹窗内。
6. **三层 CSS 重复/冲突**：**大部分消解**。`writing-desk.css` 已按新设计语言整体重写，
   `editorial-theme.css` 瘦身（旧 Editorial Archive 装饰与死覆写移除）。原 12 处冲突清单的行号
   全部失效，已确认消解的代表项：`.cockpit-tab` 激活色统一为 `--nc-accent` 2px 下划线（accent 蓝
   残留消除）、稿纸顶 3px 墨线与朱红页边线随旧设计语言移除、专注模式稿纸居中双写收敛为
   `.focus-mode-active .writing-sheet`（max-width 860px）一处。残留冲突执行时按源码重新清点，
   权威层分工见主规范 §1.1。
7. **已解决（2026-09-02）—死样式/死 class**：删除无任何生产消费者的
   `.writing-editor-buttons__group` 和 `.wc-bar-left/.wc-bar-right`；`.writing-empty-hint` 仍有多个
   失败、空态和说明文本消费者，不为统一外观强制改成错误卡。
8. **已解决（2026-09-02）—重复 id 隐患**：写作页只保留 `WritingView.vue` 的
   `#writing-conflict-strip`；删除 `WritingWorkflowBars` 中从未启用的第二渲染源和
   `showConflict` 开关，冲突摘要的位置不变。
9. **候选采纳 UI 与正文抢层级**：**已解决**。审核条紧贴编辑器头部、位于只读正文之前，
   明示“还没有改动工作稿”；候选态隐藏正常发布与 AI 生成入口，各审查状态只保留一个主操作。
   存在当前工作稿时可一步打开既有版本差异；采用/拒绝已统一走 `confirmAsync`，处理中禁用全部决策，
   失败在审核条内保留可重试错误。

### P2 — 响应式与模式完整性

10. **600–760px 断档 + 双断点体系**：**核心断档已解决**。JS `isNarrow` 与主 CSS 断点统一为
    760px；900/1099px 仍是 cockpit 与 rail 的局部布局阈值。
11. **专注模式不完整**：**已解决**。全局顶栏、导航、两栏 rail 与编辑器工具区临时隐藏，正文居中；
    顶部保留章节、保存反馈与 44px「退出专注 Esc」。状态写入项目级安全恢复指针，刷新、路由往返与
    作品切换隔离；Esc 退出并恢复焦点，正文和自动保存状态不重建。`body.focus-mode-active` 下点缀隐藏。
12. **移动速记与完整编辑脱节**：**核心切换已解决**。速记继续只承载正文、Scene、保存与设为正式正文；
    标题、版本和检查通过「更多编辑」渐进展开。两种模式可逆切换、共用当前草稿，完整模式会先收起两侧栏，
    选择按项目写入既有恢复指针，刷新、前进后退和切换作品后不会串用。速记仍不展示日目标，这是保持低干扰的产品取舍。
13. **密度断层已收敛**：正文由 17px/1.9 调整为 14px/行高 2.0（§4.2）；非必要元数据使用
    `--text-xs` 11px，区块标题、必要状态与操作使用 `--text-sm` 13px。警报和冲突状态改用
    三主题可读的正文/secondary 色，真实按钮与展开入口满足桌面 28px、触控 42px 命中。
14. **details 菜单无障碍缺陷**：**已解决**。`.writing-tools-menu` 与页头 `.writing-page-menu`
    均保留原生 `<details>`，已实现外部点击/动作/Escape 关闭、焦点归还和 `aria-expanded` 同步；
    页头入口补充方向提示与展开视觉态，≤760px 入口和菜单项保持 44px 触控高度。
15. **已裁定：写作空态保持文本优先**。ChapterTree / WritingEditor / SceneCockpit 已给出
    对应下一步，不引入新插图或强行复用其他页的 `.empty-icon`；在高密度长篇写作台中，
    装饰图形不提供额外信息，反而会抬高首次写作入口。

## 3. 目标布局与信息层级

**三栏布局（桌面，≥1100px）**：写作页不使用共享 fr 份额，grid 固定为
`238px / minmax(0,1fr) / 257px`，gap 20px（`.writing-workspace-layout`，styles.css）；
rail 折叠后对应列变为 `--workspace-rail-collapsed` 44px。底部状态栏通栏（grid-column 1/-1）：

```
┌──────────────────────────────────────────────────────────┐
│ Topbar（全局，57px）：#topbar-chapter ｜ #topbar-wordcount ｜ 主题三点切换器 │
├──────────────────────────────────────────────────────────┤
│ view-header.writing-toolbar：写作 · 共 N 章 · 写作视图▾    │
├─────────┬──────────────────────────────┬─────────────────┤
│ 章节树   │  编辑器（第一视觉焦点）        │  副驾驶          │
│ 238px   │  · 编辑器头（标题+菜单+版本条）  │  SceneCockpit   │
│ (左)    │  · 稿纸 .writing-sheet       │  257px(右,sticky)│
├─────────┴──────────────────────────────┴─────────────────┤
│ .writing-statusbar（38px 通栏）：字数进度/段落/阅读时长 · 字体/专注/保存徽标 │
├──────────────────────────────────────────────────────────┤
│ 浮窗层：OutlineFloat 抽屉 / 各模态                         │
└──────────────────────────────────────────────────────────┘
```

- **第一视觉焦点 = 正文编辑区**。章节树与副驾驶是「索引与参照」，视觉重量（字号、色对比、边框强度）
  必须低于稿纸。稿纸是页面唯一允许有独特构图的区域：1px `--nc-hairline` 边框 + `--nc-surface` 底 +
  主题点缀（§4.2）；旧 Editorial Archive 的顶 3px 墨线与朱红页边线已移除。
- **主对象契约的落实**（主规范 §4）：写作页以固定三栏（238 / 弹性 / 257）替代 64fr/18fr 份额，
  主对象仍是弹性中栏；共享 `--workspace-main-share:64fr` 契约对其他工作台页不变。
  不得为「呼吸感」加宽 rail 或压缩中栏。
- **专注模式**：进入后全局顶栏/导航、两栏 rail 与编辑器工具区 `display:none`，稿纸单列居中
  （≤860px，≥761px 时编辑器 min-height 82vh）；顶部 `.writing-focus-header` 只显示章节、保存反馈与
  「退出专注 Esc」，底部保留字数/版本/保存状态。**点缀一律隐藏**（主规范 §2）。入口 = 底部状态栏
  桌面/完整编辑入口只保留底部状态栏「专注模式」；移动速记没有状态栏时，入口保留在「写作视图」
  菜单。任何显示状态下都只有一个入口。状态复用 `writing_resume_pointer:v1:{projectId}` 的 `focusMode` 字段。
  默认专注只在章节成功打开后生效，避免隐藏尚未选择章节时的入口。
- **信息层级**：Primary = 稿纸正文 + 主按钮「设为正式正文」（每屏唯一 primary）；Secondary = 章节树
  当前章、副驾驶手选 Scene 与当前 tab、保存状态；Tertiary = 版本条、状态栏读数、菜单项。层级靠字阶与留白，
  不新增卡片边框（主规范 §0、§4 分隔优先级）。

## 4. 逐区域标准

### 4.1 章节树 rail（左，`aside.writing-tree-rail`，aria-label="章节"）

- 结构：`#writing-tree-container` → `ChapterTree.vue`（`.card.chapter-tree-card`：头部
  `.chapter-tree-header` → 纯章节顺序列表 `.chapter-tree-list` → 管理区 → 底部唯一新建入口）。
- 头部文案只显示「共 N 章」；Scene 名称、数量、跨章标记和关联入口都不进入左栏。
- 「＋ 新建章节」固定在章节框底部；页面顶栏、章节框顶部与空态不重复提供新建入口。
- 收起控件附着在章节框左上外缘，竖排「收 / 起 / ◀」；收起后原位显示「展 / 开 / ▶」。
- 视觉：rail 面板 = `--nc-surface` + `--line-subtle`，无阴影（主规范 §5.3）；当前章 =
  `--nc-surface` 底 + `--nc-ink` 加粗（700），其余行 `--nc-dim`，hover `--bg-hover`——选中态靠
  表面差与字重表达，不再使用左侧 3px 索引线。
- 字阶：章节标题 12px（`--font-body`）、章号与非必要 meta 使用 `--text-xs` 11px；rail 收窄时
  允许标题截断省略号，但必须保留完整 title 提示。
- 状态点：章状态 = 文字 + 小色点/描边点（draft = `--warning` 描边、published = `--success` 实心），
  语义不变；造型以源码为准（主规范 §5.8）。
- 空态只显示「尚无章节」说明，仍使用框底的唯一「＋ 新建章节」完成首次创建；列表加载失败
  保留 rail 内 `role=alert`，样式归并入 `.error-card` 基准。
- 映射主规范：§5.3 Card、§5.8 状态点、§5.9 Empty/Error。

### 4.2 编辑器（中栏，`main#writing-editor-container`）

**编辑器头**（`.writing-editor-header`）：

- 第一行 = `#writing-chapter-title` / `#writing-title-input` + 主按钮 `#btn-publish` +
  三个 details 菜单（保存 / AI 写作助手 / 检查与导出）；第二行 = context 插槽
  （`#writing-versions-container` 版本选择条 + `#writing-conflict-strip` 冲突条）。
  版本选择条保留在编辑器上方工具区，不随状态栏平移。
- **版本历史**：当前打开版本只显示状态；其他版本优先提供“与当前版本比较”，旧活跃版本保留
  “从此版本继续写”。低频的“单独预览 / 移入历史”收入行内“更多”，后者保持后端软废弃语义，
  不声称删除数据；390px 展开菜单进入文档流，操作不被弹窗裁切。单独预览成功后关闭弹窗并聚焦正文，
  同章切换前先保存未落盘修改；保存失败时停留当前版本。任意两版比较收入原生折叠区，默认仍为
  较旧版本 A / 较新版本 B，结果在手机单列中持续显示 A/B 归属。
- 保存/版本状态徽标（`#writing-save-status`、`#writing-version-info`）与字数条已平移至底部状态栏
  （见下），id 不变，e2e 契约不破。
- **每屏至多一个 primary**：`#btn-publish` 是中栏唯一 `.btn-primary`；章节框底部的新建入口使用
  secondary 样式，AI 建议和正文整理菜单项也使用普通按钮。
- **入口去重**：完整编辑器以页内「AI 写作助手」菜单为唯一 AI 入口，不再在页头重复显示
  「AI 工具」；候选审阅和零章节状态只保留菜单内「更多 AI 工具」，继续打开既有整理资料、
  查找资料与指定写法抽屉。移动速记未挂载编辑器菜单时，页头保留该入口。Writing Home 的 owner AI 入口不变。

**正文排版（稿纸 `.writing-sheet`）—— 当前值**：

| 属性 | 当前值 | 说明 |
|---|---|---|
| 字族 | `--font-body`（ink 主题为 LXGW Bright/WenKai 栈，主规范 §1.3） | 状态栏字体循环可在会话内临时 override，不写偏好存储 |
| 正文字号 | 14px | 页面级值（writing-desk.css），与主规范「正文/控件」档一致 |
| 行高 | 2.0 | 页面级值（稿纸阅读节奏） |
| 行宽 | 正常态无 max-width；由编辑区左右 padding 59px 收边 | 旧「32–40 中文字符」目标不再以 max-width 实现；专注模式稿纸 ≤860px |
| min-height | 58vh（专注模式 ≥761px 时 82vh） | 页面级值 |
| 稿纸 padding | `30px 59px 34px` | 页面级值 |
| 边框/焦点 | 1px `--nc-hairline`；focus-within 边 `--nc-hairline-strong` + `--nc-accent-soft` 光晕 | 旧顶 3px 墨线、朱红页边线已移除 |
| 只读区分 | 候选稿纸使用沉底背景、正常正文色与默认光标 | 已与可编辑稿纸分层，不用“禁止”光标暗示内容异常 |
| 点缀/水印 | 编辑区右上 + 正文下方各 1 组；ink 主题水印字 = `data-watermark`（当前章标题首字） | 硬规则见主规范 §2 点缀系统；实现 `writing-decorations.css` |

**底部状态栏**（`.writing-statusbar`，38px，sticky bottom，通栏 grid-column 1/-1，mono 11px）：

- 发布、生成、冲突检查和深度导入反馈使用脱离网格的顶部浮层，状态栏始终保持吸底，不因任务状态变更而跳动。
- 左：`#writing-wordcount-bar`——字数进度「1,240 / 3,000 字」+ 3px accent 进度条
  （`.wc-goal-progress`）、段落数、预计阅读时长（字数 / 400 向上取整，`WritingView.vue`
  `statusReadMinutes`）。日目标只累计每章当日首次基线后超过历史高水位的正增量，切章、刷新和删后补回不重计；底部状态栏与顶栏字数仪表盘共用同一 `todayWords`。日目标进度属行内轻量进度，不引入 `.workflow-progress`（主规范 §5.9）。
- 右：字体循环切换（会话内临时 override，不写偏好存储）→ 专注模式按钮 → 保存/版本状态徽标
  （`#writing-save-status` / `#writing-version-info`）；专注中隐藏字体与进入按钮，退出入口移至顶部专注栏。
- 上述 DOM 自 WritingEditor 头部平移，id 全部不变（§7 契约）；保存徽标已实现五态语义：
  saving / error / readonly / unsaved / saved。错误态重试入口位于正文附近的持续提示，不把紧凑
  状态徽标改成第二个按钮；状态仍以文字 + 色点表达，不引入彩色 pill（主规范 §5.8）。

**自动保存指示**：五态徽标 + 顶栏 ◆ 点（`#topbar-save-state`）双指示保留，同态同色（§4.4）。

**候选采纳 UI**（`.pov-candidate-panel.writing-candidate-review-panel`，仅 status==='candidate'
渲染）：
- 位于编辑器头部之后、只读正文之前；加载完成后焦点进入审核条，刷新和浏览器返回仍恢复该位置。
- 视觉使用 `--warning` 左边线 + 低对比底，标题先说明工作稿未被改动；只读正文使用沉底稿纸。
- 存在当前工作稿时显示“与当前工作稿比较”：直接复用版本历史弹窗，以工作稿为版本 A、候选为版本 B；
  不创建、采用或恢复版本。比较结果聚焦，Esc/关闭后焦点返回触发按钮；没有可比较基线时不显示入口。
- 按审查状态在“采用到工作稿 / 运行独立语义审查 / 按问题定向返修”中只显示一个 primary；重新审查与拒绝为次操作。
- 采用/拒绝统一使用全局 `confirmAsync`；Esc/取消不请求 API 并返回触发按钮，失败就地显示且恢复操作。
- ≤760px 使用完整只读审阅：自动收起章节目录、隐藏只读状态条，决策按钮单列且至少 44px；章节目录仍可从“展开”原生按钮恢复。

**工作流通知**（`WritingWorkflowBars.vue`：发布 / AI 正文建议 / AI 冲突检查 / 深度导入与自动提取）：固定在全局顶栏下方、写作工作区水平居中，从页面上缘向下进入；最宽 360px，窄屏保留 12px 页边距，不参与正文 grid 排版。`prefers-reduced-motion` 下取消位移动画。工作流内容继续复用
`.workflow-progress*`（主规范 §5.9）；运行、失败、取消、降级、恢复待处理及带查看/审阅/审计/恢复/重试操作的状态持续显示，只有无后续业务操作的成功态在 3 秒后自动关闭。单纯“关闭”不算后续业务操作。同一生命周期已在顶部浮层表达的成功和失败不重复发送全局 toast。版本加载失败 `.writing-empty-hint`（裸文本，§2-7）迁入
`.error-card` 基准样式或补定义（执行时核实其使用点逐一收口）。

映射主规范：§3.2 长正文、§5.1 Button、§5.2 输入（只读区分）、§5.6 Modal、§5.7 Toast（保存成功）、
§5.8 状态、§5.9 Loading/Error。

### 4.3 副驾驶 rail（右，`aside.writing-panel-rail`，aria-label="写作副驾驶"）

- 结构：`#writing-panel-container`（sticky）→ `SceneCockpit.vue`（`.scene-cockpit`：标题栏 +
  本章 Scene 快速切换 + 警报摘要 + role=tab 内容）。快速切换只显示当前章关联的
  `draft/canonical` Scene，并按全书 `scene_index` 顺序排列；跨章 Scene 只加轻量标签，不跳章。
- Scene 由作者点击手动选择；光标移动只记录编辑位置，不改变 Scene。项目会话按章节记住上次
  选择，失效时回退本章首个有效 Scene。警报、人物、地点、设定、AI 参考、规则检查和发布检查
  均消费同一个手选 Scene，切换时拒绝旧 Scene 的晚到响应。
- 「关联 Scene」打开可连续操作的模态：已有项点击 `＋` 后原位变为不可解除的 `✓`，不关闭
  模态；底部并列「新建 Scene」和「打开 Scene 工作台」。新建只填写名称并自动关联当前章；
  解除、排序、合并、拆分和移入历史仍由 Scene 工作台负责。
- 警报卡：`--nc-alert-bg` 底保留警报语义，标题与右上「查看 →」使用可读正文色；查看按钮为
  `--text-sm` 13px，并满足桌面 28px、触控 42px 命中（`.scene-alert-card`）。
- 页签：激活 tab = `--text-primary` + 底部 2px `--nc-accent` 下划线（inset），accent 蓝残留已消解
  （§2-6）。仅「警报」tab 允许 accent 色点计数（待处理语义）。
- 实体行：头像块 4px 圆角（ink 主题圆形 50%）；在场状态纯文字，不用色块/pill。
- 模块头作为可点击区块标题使用 mono `--text-sm` 13px/700；模块正文保持约 13px 与宽松行高。
- tab 内容加载中行内等待用 `.loading` dots（主规范 §5.9）；同章切换 Scene 时先清空旧派生内容，
  不保留容易误认的旧警报或人物。
- 无关联 Scene 的空态复用 `.empty-state` 简式，并提供「关联 Scene」主路径。
- 映射主规范：§5.5 Tabs、§5.8 Badge/计数、§5.9 Empty/Loading。

### 4.4 顶栏字数仪表盘（全局 Topbar，`#topbar-wordcount`）

- 结构：`#topbar-chapter-wc` / `#topbar-today-wc` / `#topbar-save-state`（◆ 点，class
  saving/unsaved/saved）+ `#topbar-chapter`；数据经 window 事件 `writing:dashboard-update` 推送
  （`useWritingWorkspace.js` → `useWordcountDashboard.js`）。
- 视觉：mono 元数据档 + `--tracking-wide`（主规范 §3.1 mono 分工：字数仪表盘是 mono 的正牌用途）。
- 状态点三态语义色：saving = `--warning`、unsaved = `--text-tertiary`、saved = `--success`
  （执行时核实现色值归属）；与 §4.2 保存徽标状态机保持一致，同态同色。
- 顶栏右侧另有全局主题三点切换器（`.topbar-theme`，主规范 §1.5），非本页独有。
- 本页是顶栏仪表盘的唯一数据源路由；离开 writing 路由时仪表盘退出由 Topbar 全局负责，
  本页规范不约束。

### 4.5 浮窗与模态

- **OutlineFloat**（`#outline-float-panel`，fixed 右侧抽屉，aria-label="大纲浮窗"）：
  抽屉 = radius `--radius-lg` + `--shadow-float`（浮层才用阴影，主规范 §1.4）。加载中用
  `.loading` dots。z-index 归全局浮层档位。旧双主题并存问题随样式重写行号失效，执行时按源码
  核实收敛状态。
- **模态五件**（AutoExtractionDialog / ConflictOptionsDialog / ConflictDetailDialog /
  DeepImportAuditDialog / VersionHistoryDialog）：统一走 `useModalDialog` + 全局
  `.modal-overlay/.modal-content`（现状已是，保持）。宽度按主规范 §5.6 三档：确认 400 /
  表单 560 / 复杂内容 720——版本历史 diff 网格（role=table）归 720 档，冲突详情归 560 档
  （执行时核实现状宽度）。焦点陷阱/Esc/inert 由全局 modal 保证，页面不得自行实现。
- **候选采用/拒绝的原生 confirm**（§2-9）迁入全局确认模态，文案写动作本身。
- **Owner AI「写作建议」**：先显示当前章节与关联 Scene；已有已保存正文时只突出「续写这一章」，
  空章时改为「生成整章建议」。其他写法收入原生 `<details>`；未设置视角人物时保留角色视角入口并
  原位说明先决条件，不显示可点击的空动作。正文尚未保存时在主操作旁提供既有保存/重试路径；生成中
  可收起抽屉查看页面顶部的持久任务进度，完成后回到只读候选审阅。抽屉刷新、浏览器历史与项目切换
  沿用现有 owner route 状态，不能把上一部作品的章节上下文带入当前项目。
- 映射主规范：§5.6 Modal、§5.7 Toast、§1.4 阴影只用于浮层。

## 5. 状态覆盖清单

| 状态 | 目标行为 | 现状差距 |
|---|---|---|
| 无章节空态 | 章节树 `.empty-state` + 框底唯一「新建章节」；编辑器区 `.writing-editor-empty`；副驾驶引导句 | 旧「文」水印已随 Editorial Archive 移除；ink 主题水印字 = 当前章标题首字（`data-watermark`，主规范 §2 点缀系统） |
| 有章节未选中 | 编辑器区「请从左侧选择章节开始写作」 | 达标 |
| 章节加载中 | `.loading-skeleton` 稿纸骨架（主规范 §5.9，reduced-motion 禁动画） | 达标；旧正文 textarea 不同时显示 |
| 章节加载失败 | `.error-card`：人话说明 + 重试按钮，就地渲染在中栏 | 达标；失败目标不覆盖上一章指针或正文 |
| 保存中 | 徽标「正在保存」（底部状态栏）+ 顶栏 ◆ saving；输入不打断 | 达标 |
| 已保存 | 徽标「已保存到工作稿」+ toast + 顶栏 ◆ saved | 达标 |
| 保存失败 | 徽标变错色 + toast + 正文附近“重试保存” + 本地备份说明；切章与发布暂时阻断 | 达标；桌面和移动端共用同一恢复状态 |
| 只读（候选/正式正文） | 徽标使用中性色点、文案「只读」；候选正文使用沉底稿纸 | 达标 |
| 仅排版差异 | 「排版修改已保留在本地」，不请求后端 | 达标，文案保留 |
| AI 生成中 | 写作建议抽屉说明任务可收起，页面顶部持久进度继续反馈；按钮禁用，完成后聚焦候选审阅 | 达标；普通生成仍须执行时核实流式动画降级 |
| 候选待处理 | 见 §4.2 候选采纳 UI | 达标；含处理中、就地失败与窄屏首屏决策 |
| 离开恢复 | 三层：路由守卫 confirm + `beforeunload` + 会话快照免确认恢复 / localStorage 跨会话 confirm 恢复 | 达标（机制在，§2 无此项问题），重构不得破坏 |
| 冲突/并发 | 乐观锁 autosave；发布冲突走全局 `#modal-overlay` | 达标 |
| 专注模式 | §3 目标态：全局 chrome/rail/工具区隐藏、稿纸居中、点缀隐藏、顶部明确退出 | 达标；项目级恢复、Esc、焦点归还及桌面/390px 均有 e2e |
| 窄屏 <760 | 整页替换 MobileQuickNote（已选章且非只读时）；顶部保留本章 Scene 最小切换 | 不展示完整副驾驶，也不允许关联或管理 Scene |

## 6. 响应式行为（四档）

| 档位 | 宽度 | 行为 |
|---|---|---|
| Desktop | ≥1440 | 工作台不限宽（主规范 §6），三栏全形态；rail 默认开 |
| Laptop | 1100–1440 | 默认形态；右 rail 默认开（`innerWidth > 1099`） |
| Tablet | 760–1100 | 右 rail 掉到整行或默认收起；左 rail 可折叠；单栏主区保持排版契约 |
| Mobile | <760 | 单栏、触控目标 ≥42/44px；**MobileQuickNote 整页替换的边界**见下 |

- **MobileQuickNote 切换边界（目标态）**：统一到主规范 §6 的 760px 主断点——JS `isNarrow` 阈值
  从 600 改为 760，消除 600–760px 死区（§2-10）。切换条件保持四元：
  `isNarrow && !forceDesktop && 已选章 && 非只读`。
  该行为已确认，并与移动端 Scene 最小切换器一并覆盖 e2e（390px 快照不受影响；
  600–760px 区间改用 MobileQuickNote）。
- 移动速记顶部使用与桌面相同的章节级手选 Scene 状态；只提供紧凑选择器，无关联时显示
  「本章未关联 Scene」，不把关联、新建或完整副驾驶塞进移动速记。
- 候选为只读决策，不进入 MobileQuickNote；≤760px 保留完整审阅内容，自动收起章节目录并隐藏底部只读状态条，保证主次决策均在首屏。
- **完整编辑模式**：速记中的「更多编辑」置 `forceDesktop=true`，沿用既有 ≤760px 单栏 CSS，
  并先收起章节目录和写作副驾驶；页头提供「返回速记」，切换后把焦点交给新模式入口。
  模式选择随项目级写作恢复指针持久化，刷新、前进后退和作品切换均保持隔离；正文与标题仍由同一编辑器状态管理。
- **断点归并**：rail 折叠 760px、正文移动态随 JS 阈值一并归入 760；900px cockpit max-height 与
  1099px 归 1100 档（主规范 §6：长尾断点逐个审查）。硬编码视口判断（§2-10）收编为共享
  composable 或 CSS 单一来源（执行时定实现）。
- 600px 以下 topbar 压缩、章节树 max-height 42vh 等局部自适应保留，逐行注释理由。
- 点缀系统 ≤760px 一律隐藏（主规范 §2 点缀系统）。
- 390px 页面级横向溢出零容忍（主规范 §6），由 `writing-mobile-390-sticky.png` 快照守住。

## 7. 必须保留的契约

以下语义钩子是 e2e 与全局基建的硬依赖，**重命名/删除前必须全局 grep 并同步测试**
（主规范 §9）。统计口径：`e2e/writing.spec.js` 全文 `#id` 选择器共 121 处、16 个不同 id
（2026-08 实测 `grep -o` 结果）。三主题改造只平移 DOM 位置（编辑器头 → 底部状态栏），
id 与可访问名称不变。

**#id（writing.spec.js 实测命中次数）**：

| id | 命中 | 所在 |
|---|---|---|
| `#writing-editor` | 38 | 正文 textarea（`.novel-editor`，aria-label="章节正文"） |
| `#btn-autosave` | 15 | 保存工作稿按钮 |
| `#modal-footer` | 10 | 全局确认框（全局契约） |
| `#btn-publish` | 9 | 发布主按钮 |
| `#writing-title-input` | 7 | 章节标题输入 |
| `#writing-save-status` | 7 | 保存状态徽标（现位于底部状态栏右侧） |
| `#version-selector` | 7 | 版本下拉（aria-label="选择章节版本"） |
| `#modal-overlay` | 7 | 全局模态遮罩（全局契约） |
| `#btn-conflict-check` | 5 | 冲突检查按钮 |
| `#writing-tree-container` / `#writing-panel-container` / `#writing-editor-container` / `#workspace-content` | 各 3 | 三栏与页面挂载点 |
| `#btn-checkpoint-version` | 2 | 检查点按钮 |
| `#modal-content` / `#mobile-note-editor` | 各 1 | 全局模态体 / 移动速记正文 |

**未在 writing.spec.js 命中但属公共契约，同样不得擅动**：
`#writing-chapter-title`、`#writing-version-info`、`#writing-editor-buttons`、`#writing-wordcount-bar`、
`#writing-versions-container`、`#publish-status-dot`、`#writing-conflict-strip`（注意双渲染源，§2-8）、
`#writing-publish-bar-container`、`#writing-deep-import-bar-container`、`#outline-float-panel`、
`#outline-float-body`、`#mobile-note-wc`、`#auto-extraction-dialog-label` 等 sr-only 标签，
`#writing-focus-exit`（`aria-keyshortcuts="Escape"`），
以及顶栏 `#topbar-wordcount` / `#topbar-chapter-wc` / `#topbar-today-wc` / `#topbar-save-state` /
`#topbar-chapter`。

**data-action**：`toggle-outline-float`、`writing-ai-menu`、`writing-more-menu`、
`deep-import-map-next`、`conflict-ai-review` 及 ConflictDetailDialog 内 8 个行动态 action
（`copy-conflict-suggestion` / `apply-conflict-suggestion` / `locate-conflict` / `open-conflict-source` /
`resolve-conflict` / `ignore-conflict` / `later-conflict` / `generate-conflict-suggestion`）、
`data-conflict-item-id`、`data-scene-cockpit-project`、`data-cockpit-module`、`data-panel`、
`data-version` / `data-latest`。

**role / 可访问名称**（e2e `getByRole({name})` 直接依赖，改文案必须同步测试）：

- 按钮名：「新建章节」「创建第一章」「打开第 N 章…」（ChapterRow 动态 aria-label）、「上一章」
  「下一章」「版本历史」「查看差异」「与当前工作稿比较」「与当前打开版本比较」「展开章节/收起章节」「收起写作副驾驶/展开」（动态）、「打开第 N 章」
  （OutlineFloat）、「专注模式」「进入专注」「退出专注 Esc」「保存工作稿」「保存为新工作稿」「放弃未设为正式正文的更改」
  「设为正式正文」「继续设为正式正文」「确认恢复」「从此版本继续写」「移入历史」「单独预览」「定位正文/无正文定位」
  「打开来源/无可打开来源」「生成 AI 修复建议」「补充 AI 软冲突判断」「稍后」「完整编辑器」。
- dialog 名：「自动提取」「剧情设定冲突检查选项」「剧情设定冲突检查」「版本历史」
  「深度导入快照状态」；aria-label：「章节正文」「移动端速记正文」「选择章节版本」
  「写作字数仪表盘」「版本差异结果」；rail：「章节」「写作副驾驶」。
- tab：「警报/人物/地点/设定/地图」（role=tab，`.active` class 断言）。
- 结构 role：`role=tablist`（`.cockpit-tabs`）、`role=alert`（章节列表失败、版本加载失败）、
  `role=status`（`.mobile-note-status`、冲突条无 latest 时）、`role=table`（版本 diff 网格）、
  冲突条 `role=button`（有 latest 时）。

**class 契约**：`.writing-toolbar`（`waitWritingReady` 入口，helpers/workbench.js）、
`.writing-workspace-layout`、`.writing-tree-rail` / `.writing-panel-rail` + `.is-collapsed`、
`.chapter-tree-create`、`.scene-cockpit-switcher__item`、`.scene-cockpit`、`.cockpit-panel`、`.writing-version-history-item`、
`.writing-conflict-item`、`.mobile-quick-note`、body `.focus-mode-active`、
`details.writing-tools-menu` 结构（被 `openWritingToolMenu` 依赖）。
三主题改造新增：`.writing-statusbar` / `.writing-statusbar__right` / `.writing-statusbar__font` /
`.writing-statusbar__focus`（状态栏）；shell 级 `.topbar-theme` / `button.theme-dot[data-theme-value]`
（主题三点切换器，视觉快照经 `SEL.themeOption(theme)` 消费）。
集中登记处：`e2e/helpers/selectors.js`。

**样式文件现状（三主题改造后）**：

- `writing-desk.css` 已按新设计语言整体重写，继续承担写作页页面级样式（章节树行密度、稿纸构图、
  状态栏、cockpit 模块密度、MobileQuickNote 布局）；旧「归并策略」所列行号全部失效，残留归并项
  执行时按源码重新清点。
- 新增 `writing-decorations.css`：编辑区点缀与 ink 水印字，硬规则见主规范 §2 点缀系统；
  shell 级点缀（顶栏品牌区、左栏导航底部）在 `editorial-theme.css` 末尾分节。
- 全局视觉权威层分工（颜色/圆角/阴影归 editorial-theme.css，结构归 styles.css）不变，
  见主规范 §1.1。

## 8. 验收标准 + 验证命令

**验收标准**：

1. §5 状态覆盖清单逐条可走通，加载骨架、加载失败 error-card、保存失败重试已有单测、功能 e2e
   与桌面/390px 视觉基线。
2. 正文排版 = 14px / 行高 2.0 / 编辑区左右 padding 59px，页面级值有注释说明，无游离 px 字号
   （新触碰代码）。
3. 每个 class 的视觉规则只剩一个权威层（主规范 §1.1）；旧三层冲突清单（§2-6）残留项按源码
   清点消解。
4. 主对象契约不回退：三栏固定 238 / 弹性 / 257；390px 无横向溢出。
5. §7 全部契约钩子在位：`#id` 16 个、data-action、role/可访问名称零意外变更；
   文案改动（如专注模式入口）已全局同步 e2e。
6. 「聚焦模式」测试债已解决（改测试名或改 UI 文案，二选一并记录）；三主题视觉基线已重录。
7. 主规范 §8 无障碍：触控档按钮 ≥42px、focus-visible 2px accent 环不被 desk 层
   `outline/box-shadow` 覆写（`.writing-sheet .novel-editor:focus { box-shadow: none }` 只清
   稿纸光晕、不动全局 outline 环，执行时核实）。
8. AI 候选在正文前聚焦且只有一个 primary；可一步比较当前工作稿，结果聚焦且 Esc 返回触发按钮；
   刷新、路由往返、确认取消和采用后恢复编辑均有功能 e2e。桌面/390px 由
   `writing-candidate-review-{desktop,mobile}-sticky.png` 与 `writing-candidate-compare-mobile-sticky.png` 守住。
9. 专注模式隐藏全局 chrome/rail/编辑工具，保留章节、保存反馈与 44px 退出入口；进入聚焦正文，Esc
   退出并归还焦点，刷新、前进后退、作品切换和 390px 正文均不丢失；视觉由
   `writing-focus-sticky.png` / `writing-focus-mobile-sticky.png` 守住。
10. 版本历史不展示无法执行的最新版操作；旧版可一步与当前打开版本比较，单独预览与“移入历史”收入
    “更多”，后者经确认且数据仍可预览。比较结果生成后聚焦结果，390px 菜单完整可见并持续显示版本
    A/B 归属；视觉由 `writing-version-history-{desktop,mobile}-sticky.png`、
    `writing-version-history-menu-mobile-sticky.png` 与 `writing-version-diff-mobile-sticky.png` 守住。
11. 页头“写作视图”菜单公开 `aria-expanded`，外点、动作与 Escape 均能关闭，后两者归还触发器焦点；
    390px 菜单完整入屏且动作触控高度不少于 44px。视觉由
    `writing-view-menu-{desktop,mobile}-sticky.png` 守住。
12. Owner AI 写作建议展示当前章/Scene，按正文状态只突出续写或整章建议；其他写法渐进展开，缺少
    POV、未保存正文和保存失败都有原位恢复说明。刷新、路由往返、作品切换、Esc 取消 AI 参考弹窗及
    收起生成任务均有功能 e2e；375px 竖屏与 812×375 横屏无横向溢出，视觉由
    `owner-ai-writing-advice-{desktop,mobile}-*-darwin.png` 守住。

**验证命令**（工作目录 `frontend-console/`）：

```bash
# 功能 e2e（writing 页主契约）
npx playwright test e2e/writing.spec.js

# 视觉基线（仅 darwin 有基线；保存恢复与候选决策均覆盖桌面/390px）
npx playwright test e2e/visual-writing.spec.js

# 全局基建回归（主题 token / 排版 token / 骨架屏 / 模态无障碍，受样式归并影响时必跑）
npx vitest run tests/editorialTheme.test.js tests/typographyTokens.test.js \
  tests/loadingSkeleton.test.js tests/modalAccessibility.test.js   # 文件名执行时核实

# 文档漂移门禁（仓库根目录）
make docs-check BASE_REF=origin/main
```

改动样式后视觉快照需 `--update-snapshots` 重建 darwin 基线并在 PR 中说明；非 darwin 平台按
`VISUAL_BASELINE=1` 流程生成本地快照核对（visual-writing.spec.js）。
