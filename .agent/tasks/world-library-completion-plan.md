# 世界资料库补全任务

状态：本地工程验收完成；本记录所在主题分支提交承载补全交付。未推送、合并或部署。

## 目标与授权

执行审查报告形成的 R0–R4 补全计划，完成持续世界模型、历史与异步恢复、跨域来源/定向复核、大库加载和作者完整流程。用户最后明确“继续修复这两项并完成验收”，已恢复此前三次测试失败停止门禁并关闭两项待修。

## 工作区与依赖

- 实施工作区：`/Users/tywww/Desktop/项目/ai-writing-assist-world-library-review`，分支 `codex/world-library-review-fixes`。
- R0 提交 b00c7f241a9983d834625eccc20dd3559ddaba82；origin/main a8de5aa9e98301943e4311aa1e5a356dd1fb177e，收尾 ls-remote 验证一致。
- 原工作区当前有用户的助手运行时 WIP，未修改、暂存或提交其中内容；不得根据旧“干净”记录处理它。
- 正式计划：`docs/product/world-library-completion-plan.md`；实现及全部证据：`docs/references/2026-09-10-world-library-completion.md`。

## 完成内容与决策

R1–R4 已完成，具体接口和能力以代码、README、ADR-0021/0022与执行报告为准。不新增基础设施、表或依赖；复用现有 checkpoint、suggestion、队列和 Evidence/Story facade，候选成果不等于 Canon 采用。

两项收尾：
1. 完整作者流程限定页面内“更多工具”，等待健康面板初始化结束，直接 summary/状态徽标定位，按需展开；完成断言不接受“校验失败”。
2. 共用 OwnerAiDrawer 通过现有 Teleport to body 方式脱离 workspace-content 的 isolation；层级95介于侧栏90和顶栏100之间。三个宽度增加 elementFromPoint 边缘/中心命中；旧代码768测试先红，再验证修复后编辑、父版本保护、失效与恢复。组件和生成中心浏览器断言读取真实浮层。

812px 共创旧视觉基线同样有侧栏遮挡，逐图核对后只额外更新该图。写作菜单有一次截图黑块，未改代码/预期，隔离复跑及最终全量均通过。像素阈值没有调整。

## 验证与证据

- 后端 World/Evidence/Story/任务：1978 passed、12 skipped、2 deselected；真实 PostgreSQL 并发2 passed。本次只改前端与测试，沿用这些未受影响证据。
- 前端全量2401/2401、ESLint、Ruff、构建通过（12引用/51 JS/77资产）。
- 功能完整运行264 passed/4 failed/2 skipped；4项都是旧容器定位，修正后生成中心完整文件21/21 passed，覆盖全部4项。合计覆盖268项，不冒称单次全量268/268。
- 完整作者流程在定向和全站运行中均通过；390/768/1440编辑、1000历史选择通过。最终visual38/38 passed。
- 100/1000资料性能实测与原始JSON保留。1000项cold p95 261.20ms、warm270.89、search832.47、input23；首屏最大25324B/10请求。此为本机合成资料，非生产SLA或真实作者/模型质量验收。
- 证据目录：`/Users/tywww/.codex/artifacts/world-library-completion-20260910/`。最终图片world-drawer-768-final.png与world-model-{390,768,1440}-final.png；最终日志frontend-resume-final.log、functional-resume-full.log、generate-resume-final.log、visual-resume-final.log、build-resume-final.log。
- 开始及收尾 docs-check、diff-check 通过；提交前最后再核对文档门禁。

## 运行环境与恢复

专用PG：ai_novel_test_world_completion_20260910、ai_novel_test_world_completion_visual_20260910、ai_novel_test_world_completion_concurrency_20260910，容器ai-novel-db/5207；MinIO ai-novel-minio/9000。测试仅合成资料、假provider，不读.env/真实Vault/付费模型。保留这些专用库，未触碰原用户与演示worker。

恢复时先核对本分支git status/log及执行报告。当前工程工作已结束；下一步若用户要求远端交付，再按仓库规则处理push/PR。合并、删除和部署均未授权，任务记录不能扩展授权。
