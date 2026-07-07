# Content Sanitization Policy

- **状态**: Draft policy
- **日期**: 2026-07-07
- **关联追踪**: M23, L24, L29

## 范围

本文区分三类净化边界，避免把 prompt 防护、AI 输出净化和前端 HTML escaping 混成一条规则。

## 1. Prompt 输入净化

Prompt 输入净化保护 LLM 调用边界，目标是降低 prompt injection、超长输入和敏感诊断泄漏风险。

要求：

- 动态用户/章节/AI 历史内容进入 prompt 前应有边界包装和长度限制。
- 可疑 prompt injection 模式应被检测并转为 warning 或拒绝。
- 错误日志不得回显完整原文、API Key、token 或长敏感片段。

L29 仍需补齐章节文本进入 LLM 前的统一净化策略；不要把已有局部防护写成全链路完成。

## 2. AI 输出净化

AI 输出净化保护存储和 API 返回边界，目标是防止未受控 HTML、超长内容或危险片段进入草稿/正史对象。

要求：

- 写入草稿、候选或 canonical 之前，应按字段类型做长度限制和最小 HTML 标签处理。
- 结构化输出必须先通过 Pydantic/schema 校验，再进入数据库。
- 用户确认启动的自动流水线可直接写 canonical，但仍必须保留 provenance、可编辑/可回滚标记和测试覆盖。

M23 仍需代码补齐，本文只记录策略，不表示 AI 草稿输出净化已完成。

## 3. 前端 HTML escaping

前端 HTML escaping 保护浏览器渲染边界，目标是防止用户/AI/API 动态内容作为 HTML 执行。

要求：

- 动态文本优先写入 `textContent`。
- 必须拼接 HTML 时，所有动态片段先经 `esc()` 或等价 escaping。
- 静态模板可以使用 `innerHTML`，但不得混入未转义动态内容。
- CSP baseline 是兜底，不替代 escaping。

L24 仍需后端 HTML 净化策略补齐；不能只依赖前端 escaping。

## 当前状态

本文是 Draft policy。M23/L24/L29 都仍是代码实现项，未因本文创建而完成。
