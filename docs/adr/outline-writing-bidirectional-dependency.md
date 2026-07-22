# ADR — Outline / Writing 双向 facade 依赖

- **状态**: Partially superseded
- **日期**: 2026-07-07
- **关联追踪**: M1

> 2026-07-22：Writing 的按正文 offset 断章入口及其 split provider 已取消。
> 下文关于该入口的内容仅记录原始决策，不再是当前契约；Scene contract loader 与
> outline 只读消费 writing facade/contracts 的边界继续有效。

## 背景

`outline` 负责剧情结构，`writing` 负责正文草稿和版本。当前两个模块之间存在双向 facade 调用风险：结构生成需要读取写作草稿上下文，写作流又需要 Scene/章节结构作为导航和生成约束。

这种依赖短期可运行，但长期会让模块边界变浅：任一侧 facade 如果继续承载编排逻辑，容易把结构层和写作层耦合成循环。

## 决策

跨模块协作收敛到明确方向：

- `outline` 继续拥有 Scene、剧情线、篇章纲、伏笔和揭示等结构资产。
- `writing` 继续拥有草稿、版本、正文保存和恢复。
- `outline` 可以只读消费 `writing.facade` / `writing.contracts` 中的草稿和章节索引，不直接 import writing repository / service / model。
- `writing` 服务通过可注入 provider 调用 outline split 和 Scene contract 读取能力；默认 provider 在函数内部 lazy import `outline.facade`，保持旧行为。
- 非平凡编排下沉到拥有领域概念的一侧，facade 只做参数适配、稳定返回形状和委托。

本轮不改 HTTP API、数据库 schema、前端 wire shape 或用户流程；写作断章仍同步调整 outline Scene chunk，写作冲突检查仍能读取 Scene contract，outline 仍可只读读取 writing 草稿/章节索引。

## 结果

- `backend/modules/writing/services.py` 不再顶层 import `modules.outline.facade`。
- `WritingDraftService` 支持注入 split provider，默认 provider lazy 调用 `outline.facade.split_scene_chunk_to_new_chapter`。
- `WritingConflictCheckService` 支持注入 Scene contract loader，默认 provider lazy 调用 `outline.facade.get_scene_contract`，并保留失败降级为 `outline` degraded source 的语义。
- 测试覆盖默认 provider 集成路径、fake provider 注入路径，以及 AST 级顶层 import 边界。

## 后续验证

- 搜索 `modules.outline` 与 `modules.writing` 之间的 facade/contracts 调用。
- 为重构路径补充跨模块行为测试，优先走 facade/contracts/API/DI port。
- 更新 `docs/modules/07_outline.md`、`docs/modules/11_writing.md` 和模块 README 中的稳定接口说明。
