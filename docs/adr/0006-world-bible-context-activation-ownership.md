# ADR-0006 — 世界书资料与上下文激活规则分属 world / context

- **状态**: Accepted
- **日期**: 2026-07-15
- **关联设计**: `docs/superpowers/specs/2026-07-14-world-bible-module-v2-design.md`

## 背景

当前 `world` 已拥有 CoreEntity、Profile、关系、世界书类别、页面、工作稿、修订和投影；
`context` 已拥有可见性、预算、确认、snapshot 与最终编译。世界书 V2 需要增加多段资料编辑、
可复用激活规则和逐项 trace，但不能建立第二套世界事实，也不能让页面字段直接控制 Prompt。

## 决策

> 2026-07-15 补充：第 4 节中与世界书 AI 旧接口共存有关的 additive 决定已由
> [ADR-0007](0007-world-generation-center-consolidation.md) 取代；本 ADR 的所有权与安全边界继续有效。

### 1. world 拥有资料，context 拥有激活

- `world` 拥有页面 sections、页面模板、发布/revision、TargetRef 校验和可重建投影。
- `context` 拥有 Activation Profile、规则 revision、匹配、可见性、预算和 trace。
- 前端可把二者组合成一个世界书工作区，生产代码仍只能通过 facade/contracts 跨模块调用。

### 2. 页面不是事实源或 Prompt

世界书页面只组织和解释既有事实。结构化事实仍归 CoreEntity/Profile/关系/地图事实等拥有者；
正文识别出的新事实先进入建议。页面内容始终作为不可信参考资料渲染，不能选择 Prompt role、
depth、outlet、工具或 system scaffold。

### 3. Activation Profile 是确定性、版本化 aggregate

第一版以 `context_activation_profiles.rules_json` 保存最多 128 条 schema-validated 规则，并以
不可变 revision 固定完整规则集。相同 profile revision、输入 hash 和资产 revision 必须得到
相同结果；不支持随机概率、任意 regex、无限递归或 `ignoreBudget`。

### 4. 现有契约 additive 演进

- 保留 `WorldBiblePage.free_text` 和现有世界书 API。
- 保留 `GET /api/context/activation-preview`；结构化预览使用同路径 POST。
- `activation_defaults_json` 只作为编辑提示，不是正式运行时规则源。
- reader/character/future Scene、candidate 和 `novel_id` 门禁不能被规则放宽。

## 影响

- 新增 world 页面模板与 context Activation Profile 表，但不新增顶级模块或运行时依赖。
- 页面、模板和 Profile 独立 CAS；既有 confirmation/snapshot 固定实际使用的 revision/hash。
- `imports`、`writing` 和生成中心只消费 context facade，不读取 world/context 内部表。

## 拒绝方案

### A. 将规则塞入 `world_bible_pages.activation_defaults_json`

拒绝。它会让资料编辑静默改变运行时上下文，并使 world 同时承担选择、预算和可见性。

### B. 新建独立 worldbook 模块

拒绝。它会复制 world 事实和 context 编译能力，形成双向同步。

### C. 复制 SillyTavern entry 与 Prompt 插槽

拒绝。资料、规则和 Prompt 耦合会破坏 Pydantic 边界、可重放性和安全门禁。
