# ADR-0013 — Operation receipt 与页内长任务恢复

- **状态**: Accepted
- **日期**: 2026-08-13
- **决策来源**: 用户选择“可恢复 AI 长任务”方案 1B

## 背景

作者主动发起的 World、Outline 和 Writing 长耗时 AI 操作原先部分由浏览器
持有同步请求。刷新、离开或响应丢失时，浏览器无法区分“未提交”与“已入队但未收到
响应”，重试可能产生重复任务或重复待处理结果。全局任务中心和新调度框架会扩大
产品与基础设施面，而作者需要的是回到原功能位置继续。

## 决策

1. 前端在提交前生成 UUID `operation_id`，并先持久化页内 workflow receipt。服务端将该
   UUID 直接作为 `async_tasks.id`。同一 `operation_id + novel_id + task_type + request
   fingerprint` 返回原任务，包括终态；同 ID 异请求返回 409。不新增表、索引或迁移。
2. 新长任务入口必填 `operation_id`；已有异步入口以可选字段兼容旧客户端，官方前端
   始终提供。刷新后只按 receipt 查询原任务；404 提示重新开始，不自动重放不确定请求。
3. 选择性启用的 LLM task handler 关闭 client transport retry，由 worker 最多执行两个 attempt。
   仅连接、超时、限流和明确临时 provider 错误自动重排一次；认证、额度、内容过滤、
   结构校验、确认失效和来源冲突立即失败。结构化输出自身的修复预算不计作 transport attempt。
4. provider 前释放数据库事务，写入前重验 active project、来源基线/指纹与当前
   lease/attempt。取消或旧 attempt 结果不得写入业务表。
5. 恢复范围只是发起位置的 project/page workflow。进度、失败、取消和结果原位展示，
   不暴露 raw task ID，不刷新整座 island，不覆盖期间的输入、筛选、焦点、滚动或多选。

## 适用范围

- World 生成中心建议、世界对象抽取/融合、项目智能去重；
- Outline 故事总览、P20/大纲生成与分析、Scene 融合预览；
- Writing 正文生成、冲突整体 AI 判断和单条修复建议。

Imports、RAG、World Bible 简介/投影已有 durable domain owner 或 active-task 状态，不叠加第二套。

## 非目标与后果

- 不新增全局任务中心、新队列/调度器、账户级或跨设备锁。不同标签页/设备可各自提交。
- operation receipt 只收敛同一显式操作的不确定重试，不替代 ADR-0011 的 keyed active
  coalescing，也不替代业务 source/confirmation/domain owner fence。
- 旧同步长操作在一个正式版本内保留并标记 deprecated；下一正式版本删除旧入口、调用方与兼容测试。
