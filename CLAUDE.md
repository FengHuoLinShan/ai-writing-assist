@AGENTS.md

# Claude Code

仓库共享约束、命令与验收规则以 `AGENTS.md` 为准，开发导航按其指向的模块 README、
`development-guide.md` 与 `testing-guide.md` 读取；本文件只导入，不另行定义。

涉及导演独立探索、跨尺度移交或暂停恢复时，读取 `backend/modules/story/README.md` 的对应契约。

涉及任务级自动修改时，补读 [Assistant 契约](backend/modules/assistant/README.md) 与
[ADR-0038](docs/adr/0038-ai-operation-catalog-goal-runs-and-trace.md) 的授权、撤回和模型校准边界。
