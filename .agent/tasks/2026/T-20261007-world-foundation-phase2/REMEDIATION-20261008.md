# 阶段 2 审查整改（2026-10-08）

本轮承接已存在的未提交修复，补齐 [原审查](REVIEW-20261008.md) 的 S1/S2 与 F1–F9。
实现和验证均在原主题 worktree；原有补丁已在仓库外备份，主 checkout 的 WIP 保留。
状态为本地工程修复完成，未提交、推送、合并或部署。

## 修复结果

| 项目 | 当前行为与证据 |
|---|---|
| S1 来源重验 | 执行必须带预览来源指纹；重建绑定历史前缀、稿版本/hash、场景区间及结构。共用正文章节锁，等待后重读目录，再以结构事务锁和 NOWAIT 共享行锁冻结来源；已有写者时返回冲突。 |
| S2 幂等与回放 | 操作及不可变回执同事务，项目内编号唯一。并发同请求只执行一次；换目标或来源基线拒绝；原操作在后来改稿后仍回原结果。回执失败回滚域动作。 |
| F1 历史来源 | 摄入时固定经服务器回读的 draft/hash/range；重建不按事件时间猜版本。原地改稿失配标 unverified；重新摄入同一稳定事件可绑定新稿。旧数据无绑定不制造 exact。 |
| F2 已展示证明 | reader 逐字段验证值 hash、当前 working 稿 hash 和回读区间里的值/历史对象名；同章多场景仅使用已读范围，缺偏移不拿整章放行。旧版稿里的口令不能放行当前已删去口令的版本。作者历史事实与 v1 来源仍保留。 |
| F3 字段边界 | 单字段证明不放行其他秘密；位置聚合逐键裁剪隐藏字段。 |
| F4 来源定位 | 位置来源只从当前 payload 仍有的受控字段挑选赋值链。 |
| F5 时间实例 | 月相按稳定事件/事实实例挂链；旧载荷缺实例键时不借全局最后赋值。 |
| F6 实际消费 | 真实投影经 Evolution facade 登记本维度的本场与继承前缀消费；旧格式仍保守。登记元数据不参与内容指纹；重复 ensure 保持历史行及登记时间。 |
| F7 跨会话恢复 | 保存失效提示、操作回执持久落库，按项目回读。仅索引入队、索引失败、正史索引未成功、场景再次失效或 basis 漂移均保留待处理。部分分类/部分场景不会清空整章提示；先过滤实际完成再应用列表上限。恢复失败明确提示重试，正文保持可编辑。 |
| F8 预览一致 | 预览冻结方式、目标、回执、操作键和来源；切换方式/新提示使旧响应失效，执行只用预览快照。 |
| F9 在途恢复 | 新提示不解除已发出的执行；唯一解锁点为其 finally。旧响应记录到原项目，不写入新提示的面板。 |

最后独立复核额外发现并修复：Evolution 的 source_revision 是观察来源契约版本，不是
Writing 草稿版本号；真实 v2 来源回执现在可经 MemoryService 落入 v2 来源。
场景结构等待窗口、同章后场景泄密、当前消费者状态消解均有新增回归。

## 验证

- Story continuity/outline_state、Evolution、Writing 与 Scene Lens：1223 passed，1 deselected。
- Collaboration 与 Evidence indexing/compilation：644 passed，2 deselected。两组有少量重叠，不合计为独立用例数。
- 最后来源版本与恢复补充后，continuity、重算恢复、Scene Lens：230 passed；失败回滚及完成后列表上限用例通过。
- 前端 writing：28 文件、339 passed；全量 eslint 和生产 build/产物引用检查通过。
- 新建独立库 agent_e2e_world_p2repair_20261008：空库 upgrade head、alembic check 通过；8 项真实 PostgreSQL API/并发 E2E 通过。未重建或使用既有真实验收库。
- backend make lint、改动 Python format、git diff --check、module-import-gate 通过，函数内跨模块导入 524/525，其余方向预算未增加。
- make docs-check 完整性通过。BASE_REF=origin/main 差异门禁按既有协议提供逐项无变化理由后通过：CLAUDE 导入文件、文档维护流程及两个架构图没有节点/归属/治理变化；数据库目录和五个领域文档已同步。

核心回归在 backend/modules/story/continuity/tests/test_p2_review_regressions.py、
backend/modules/writing/tests/test_p2c_recompute_recovery.py 与
backend/tests/e2e/test_p2_recompute_concurrency.py。测试资料均为合成数据，零真实模型调用。

## 验收边界

这些结果证明工程调用链、数据库事务与界面状态行为。字面展示证据不证明语义蕴含，
也不等于文学/作者质量验收。完整真实浏览器、真实模型和作者验收本轮未运行；父任务 R7
仍未闭合，没有启用 formal family 或扩大模型费用授权。原 PR/CI 不覆盖当前未提交补丁。
