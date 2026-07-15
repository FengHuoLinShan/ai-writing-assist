# ADR-0007 — 世界设定 AI 全量统一到生成中心

- **状态**: Accepted
- **日期**: 2026-07-15
- **关联设计**: `docs/superpowers/specs/2026-07-14-world-bible-module-v2-design.md`
- **取代范围**: 仅取代 ADR-0006 第 4 节中“现有世界书 API additive 保留”的世界书 AI
  接口共存决定；ADR-0006 的 world/context 所有权、页面非事实源和 Activation Profile
  决定继续有效。

## 背景

世界对象共创与世界书页面生成原本分散在生成中心和世界书侧栏，使用不同服务、请求形状与
页面 patch 语义。侧栏空间不足以承载长对话、完整上下文选择和整页预览；两套流程也让来源
冻结、上下文追踪、suggestion-only 和工作稿应用产生重复实现。项目尚未上线，因此无需保留
旧 HTTP、wire 或 localStorage 兼容层。

## 决策

### 1. 世界设定 AI 只从生成中心进入

world 生成中心提供三种由作者明确选择的 target：`core_entity`、`world_bible_page` 和
`world_bible_new_page`。模型只能生成聊天回复或待处理建议，不能自主切换目标、调用工具、
发布页面或写 canonical。世界书页面保留“用 AI 完善此页”入口；有未保存内容时必须先保存，
再携带项目、来源页面和目标 ID 跳转生成中心。

### 2. world 统一编排，context 统一编译背景

world 内的 `WorldGenerationCenterService` 统一项目 LLM 配置、Prompt 分派、服务器来源重载、
页面/工作稿 baseline、输出校验、来源追踪和 suggestion 创建。context 继续拥有 Scene、剧情线、
人物、对象、RAG、预算、Top-K、Activation Profile 与 snapshot 编译；两个模块只通过稳定
facade/contracts 交互。不新建跨 writing/context 的通用 AI 服务。

### 3. 页面生成是完整提案，不是 patch

现有页和新页面都使用 `world_bible_page_draft` suggestion target。提案包含完整标题、类别、
概览、sections 和已校验资产关联；作者可以编辑完整提案。应用时重新校验 pending 状态、
`novel_id`、页面/工作稿 baseline、section、类别和资产引用，仅替换或创建服务器工作稿。
baseline 漂移返回 409，不自动合并或覆盖作者新修改。正式页仍只能由作者显式发布。
页面来源请求用 `published` / `draft` 判别 baseline 明确表达作者看到的状态；
“预期没有工作稿”也是可校验的前置条件，不会被服务器当前工作稿静默取代。

### 4. 世界观简介生命周期留在 world

`WorldBibleSynopsisService` 继续负责简介来源 manifest、不可变 revision、pin、history、stale
和自动刷新。生成中心只按作者开关消费当前可用简介，并在 context snapshot 中记录 revision；
不复制简介生成或维护流程。

### 5. 删除旧兼容面

以下接口和对应服务、schema、前端状态直接删除，不提供别名：

- `POST /api/world/object-draft-chat`
- `POST /api/world/object-drafts/generate`
- `POST /api/world/bible/pages/{page_id}/ai-generate`
- `POST /api/world/suggestions/{id}/apply-to-world-bible-draft`

新公共入口只有 generation center chat、suggestions 和页面工作稿 apply。旧 `page_patch`、
`append_text`、混合响应和 generic confirm 写世界书页面分支同时删除。

## 影响

- 世界书 UI 删除 AI 侧栏、聊天与目标/模板状态；简介维护和 Activation Profile 编辑仍留原位。
- 生成中心 world 工作区承载来源、目标、对话、上下文、目标配置和结构化预览；本地状态以
  项目、来源页面和目标隔离，不缓存服务器页面正文。
- 世界对象继续走现有待处理队列；页面建议使用专用工作稿应用入口。
- 不新增顶级模块、前端框架、运行时依赖或数据库表。

## 拒绝方案

### A. 保留世界书侧栏 AI 作为快捷兼容入口

拒绝。它继续复制对话状态、上下文选择、Prompt 分派和页面应用语义，也无法提供完整页面预览。

### B. 继续生成 append/patch

拒绝。追加文本把当前页面误当作不可重构骨架，难以同时改善资料组织、逻辑一致性和资产引用。

### C. 建立跨模块通用 AI 大服务

拒绝。world 拥有目标和 suggestion 语义，context 拥有背景编译；抽象成通用服务会模糊领域权限
和落库边界。
