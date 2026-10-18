# 第二轮评审整改回执

记录时间：2026-10-19T01:19:00+08:00。用户明确要求“修复”，范围为 [独立评审交接](REVIEW-HANDOFF-20261019.md) 的 F1–F3；F4 保留不动。进度唯一记录为 [TASK.md](TASK.md)。

## 修复

- F1：共享 `referencePicker.js` 在结果容器具名 mousedown 处理器中取消默认焦点移动，destroy 移除监听；保留 focusout 关闭、取消搜索与拒绝迟到结果。单测验证可取消事件及销毁清理；原 WebKit 门禁的“移动核心流程”增加实际对象认知选择器 click/tap 两条用例，同时验证选中、输入焦点与离开关闭结果。
- F2：`useProjectAssistant.js` 恢复 context/blueprint 后再恢复 approvalRequest。组件测试使用真实 composable 和组件同步 watcher，从 research 蓝图切至含审批请求的本机草稿，验证请求保留、随后范围变化仍清空审批。临时还原原赋值顺序时新测试失败，恢复修复后组件 8 项通过；未修改 watcher 或 open(request) 的范围清除语义。
- F3：`EntityRelationResponse.review_meta` 仅在序列化时省略 author_change_history，其他键和作者状态投影保持原行为；ORM 存储、分页历史及恢复不变。新增实际 HTTP/助手 _read 用例：连续修改 6 次，两种响应均无完整历史、其他元数据保留、列表体积基本恒定；两页取全 6 次历史，恢复最早修改前内容后仍有 7 次历史。World README 同步响应边界。

## 验证

- 实现前 `make docs-check` 通过。
- 前端针对性 3 文件 44 passed；完整 Vitest 267 文件 / 3320 passed（80.86s）。日志 `/tmp/author-review-focused-frontend.log`、`/tmp/author-review-vitest-all.log`。
- World + Assistant 全模块 1925 passed / 1 既有 Pydantic schema 默认值警告（101.96s，内存 SQLite）。关系专项 6 passed。日志 `/tmp/author-review-world-assistant.log`、`/tmp/author-review-focused-backend.log`。
- 项目匹配 Playwright WebKit v2359 安装成功，完整 `test:e2e:webkit` 14 passed（1.7m），含新增 click/tap 两条真实点选。仅复用确切专用容器 `ai-writing-assist-author-workspaces-e2e-20261018` 的 `ai_writing_assist_e2e_test`，fresh backend/frontend；未访问其他库。日志 `/tmp/author-review-webkit.log`。
- `make lint`、前端全量 ESLint、修改 Python 文件 Ruff format、`make docs-check BASE_REF=origin/main`、`git diff --check` 通过；最终任务记录更新后再次检查文档和空白。
- F2 反证/修复日志 `/tmp/author-review-f2-red.log`、`/tmp/author-review-f2-green.log`。全量 Vitest 中 WritingView 的 localhost:3000 ECONNREFUSED stderr 是交接已归因的原测试后台请求，本轮未改相关产品或断言。

## 交付边界

- 继续原分支 `codex/writing-workbench-ai-research`，HEAD `98598127f933782f26019ca0e9970c53849c2a97`。原已跟踪工作区指纹与交接一致；原未跟踪指纹 `3ceb570bfe5c8502` 与交接不同，原文件全部保留。本轮不覆盖、丢弃或重新组织既有 WIP。
- F1–F3 本地工程整改完成；无子代理、真实模型、共享/真实数据库、提交、推送、合并、远端 CI 或部署操作。
- 未做真机 macOS Safari / iOS Safari 手动验收，本轮 WebKit 为 Playwright 构建；未重跑独立 PostgreSQL 后端套件（本轮没有 schema、存储或锁语义修改）。本轮没有新增 Chrome/Firefox 实测，既往结果不当作当前验收。
- 比较 origin/main..HEAD 的二进制/文件大小/发布证据门禁在未提交状态不能代表当前工作区，若后续提交须重跑。后续提交/合并/发布继续遵守项目授权和门禁。
