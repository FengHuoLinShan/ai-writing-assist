# TypeScript / API Contracts Design

- **状态**: 共享 JavaScript API 契约校验已落地第一阶段；TypeScript/codegen 仍是未来设计
- **日期**: 2026-07-07
- **关联追踪**: H7

## 当前状态

`frontend-console` 当前使用 Vue 3 SFC，既有 hash router 和 `api.js` 保留为窄的基础设施 seam。
`package.json` 已提供 Vue/Vite 构建链，但未引入 TypeScript、OpenAPI codegen 或独立前端
lint/format 依赖。API 调用仍集中在 `frontend-console/api.js`，测试主要通过 Vitest 和
Playwright 覆盖行为。

H7 的第一阶段已在共享 JavaScript API seam 中落地：`frontend-console/apiContracts.js` 注册高风险 wrapper 的 `method`、`path(params)`、必需 path/query 参数、body 标记和长耗时 timeout kind；`api.js` 的项目、设置、导入、上下文、世界/地图、写作冲突检查和 RAG 关键 wrapper 通过该 registry 生成实际 path/method/timeout。`frontend-console/tests/api-contract.test.js` 校验入口加载顺序、registry key 是否在 `api.js` 中存在，以及代表性 endpoint 映射。

当前范围不覆盖响应字段级 schema drift，也不提供编辑期类型检查。TypeScript、OpenAPI codegen 或新增强制 build/check 命令仍属于未来设计项，需要用户确认或 ADR 更新。

## 目标

未来 API 契约层仍应继续解决：

- 前端调用参数和后端 Pydantic schema 漂移。
- 响应字段改名或删除时缺少静态/测试反馈。
- 大量手写 API wrapper 难以确认 endpoint 覆盖范围。

## 可选方案

### 方案 A：OpenAPI 生成类型

- 后端导出 OpenAPI schema。
- 使用 openapi-typescript 或等价工具生成只读类型。
- 保留现有 `api.js` request 封装，逐步给高风险 endpoint 加 JSDoc 类型。

优点是可在不替换现有 Vue 页面或 JavaScript API seam 的前提下渐进引入；缺点是类型只在编辑器/检查步骤生效，需要新增工具链和命令。

### 方案 B：OpenAPI 生成客户端

- 生成 typed client 并替代部分手写 wrapper。
- API wrapper 只保留认证、超时、错误映射和兼容适配。

优点是契约覆盖更强；缺点是迁移成本高，可能引入新 runtime/build 约束。

### 方案 C：契约快照测试

- 保持现有 JavaScript API seam。
- 在测试中加载后端 OpenAPI schema 或静态导出快照。
- 校验 `api.js` 中关键 endpoint、method、path、参数和响应字段。

优点是无需立即引入 TypeScript；缺点是不能提供完整编辑期类型反馈。

## 拟议路线

已先做方案 C 的 JavaScript 最小集合：选 `project`、`settings`、`imports`、`context`、`world/maps`、`writing conflict`、`rag` 等高风险 endpoint，建立静态 contract registry 与 Vitest drift 测试。确认收益后再决定是否升级到生成类型或生成客户端。

任何 TypeScript、codegen 或强制前端 build/check 命令都需要用户确认或 ADR 更新。
