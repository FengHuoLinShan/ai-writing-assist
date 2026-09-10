---
id: T-20260910-agent-main-integration
title: Agent 与 main 隔离整合
status: completed
---

# Agent 与 main 隔离整合

目标：解决Agent全量WIP与本地main冲突并验证。用户仅授权隔离整合与回归，不移动main、
不推送/部署；原工作树与暂存区保留。当前目录为唯一整合笔记写入位置。

基线：Agent快照8ee03fb9b（基于a8de5aa9e），main=6eec78cca。分支codex/agent-main-integration，
工作树/Users/tywww/.codex/worktrees/agent-main-integration/ai-writing-assist。
正在merge --no-commit；39个文本冲突已编辑，尚未标记解决。

决策：保留main的世界持久共创任务/模型迭代、跨域复核、工具栏与惰性加载；共享会话CRUD
归Assistant，World subclass仅持有本域generation_context/enqueue_turn。检查点仍经World port
验证，指针行锁、来源payload轮次/深度及作者决定迁到共享服务。分页offset同步所有调用方。
去重保留Agent的哈希重放保护与main的跨设备裁决读取，写入workbench_receipts，只留成功组，
读取兼容旧group_receipts；失败组继续可重试。前端同时保留Assistant讨论入口与main设计任务。

验证：docs-check初检通过。首批119例中115通过，4失败为迁移调用锁参数和去重失败回执
语义；已按真实调用修复，待复测。前端lint发现作用域变量与旧卸载钩子引用，已修。
无真实数据访问。下一步：通过冲突相关后端/前端检查后运行全套test-ci、独立PG和浏览器。


进展检查点：冲突标记已清零并在独立index标记解决；main/原工作树不动。新专用库
ai_novel_agent_e2e_merge_20260910，只在该库迁移和验证。PG critical31passed，Assistant/
旧会话迁移/复核/世界checkpoint并发7passed。浏览器8038/8108真实API与worker、合成模型
IO，Assistant确认/跨页恢复/390px键盘1passed，服务已由Playwright停止。
前端全量180files/2467passed（首次断言全绿但异步动态import在teardown后继续，已加
vi.dynamicImportSettled等待，重跑无未处理错误）。lint和build/生产产物验证通过。
补齐地图工具栏上传能力禁用与旧草稿发布回执的按需加载恢复，相关测试已更新行为证据。

make test-ci初次部署层267passed/1failed，原因为SearXNG日志正常但测试服务清单漏列，
已补清单并定向通过；后续单独继续相同门禁的npm audit/coverage/Vitest，未跳过检查。
后端依赖审计通过（langchain-community archived状态提示），npm audit无high/critical，
2个moderate属于既有Vitest依赖，未擅自升级。Coverage全套仍在收集结果，出现失败需修。
日志统一位于本工作树backend/.test-artifacts/integration-*.log，不含明文DSN。

下一步：读取integration-coverage.log的失败摘要并修复，复跑必要门禁；收尾恢复原backend
venv的editable package绑定（测试uv曾因共享venv链接重绑到整合目录），为整合树独立sync
venv，避免后续交叉影响；不删除原venv。保存最终任务状态，不提交merge。


回归修整：首次全量5243例中14失败，覆盖率85.90%；涉及迁移后旧fixture/API门禁清单、
SearXNG服务清单和新检查点作者决定。公开API显式require_active_project，确认清单同时
覆盖路由委托和实际服务confirmation消费，未删除鉴权/确认断言。取消入口不提前锁父任务，
由生命周期统一先子后父并重验终态，新增通用取消PG用例；专项PG现8passed。
旧配置测试同步canonical deepseek-flash，心跳传入原session_factory，人物fixture核验
同项目source.changed事件，P20测试绑定实际迁移服务。检查点测试核对2条作者决定和2条
成果回执，均引用对应来源，不把新增决定当重复成果删除。

第一次最终CI部署268passed，后端5242passed/1failed、coverage85.91%；最后失败为写作
preflight测试伪项目ID仅patch服务门禁，已换真实测试项目并保持stale 409精确断言，定向通过。
正在再次完整make test-ci。主干World/地图browser7passed；Assistantbrowser首轮1passed，
API门禁修正后正在复测。map E2E mock显式声明模拟图片能力，不借真实存储配置通过。

隔离核对：原工作树所有交付文件的临时index tree与8ee03fb9b初始快照完全一致，main仍
6eec78cca417d2cf0f35b23ca47e89825bbf1c7a。原backend venv已恢复source editable及ci/dev
依赖；整合backend/.venv现为独立目录，无原venv链接。源码/真实.env/开发作品未修改。
下一步：收齐integration-ci-final.log、browser结果，完成docs-check BASE_REF=origin/main、
格式与diff检查，保存最终交付状态；不创建merge提交，不移动main。


## 最终交付：隔离冲突解决与工程回归完成

- 39个冲突文件全部解决，保留main九个独有提交的功能与Agent全量快照；无未合并index项。
- 最终 `make test-ci TEST_WORKERS=2` 完整返回0：后端5243passed/12skipped，覆盖率85.92%
  （门槛85%）；前端180files/2467passed；部署268passed；文档、secret hygiene、Ruff及
  后端依赖审计通过，npm audit满足无high/critical门禁（既有2个moderate，未升级依赖）。
- 专用PG critical31passed，Agent/迁移/复核/checkpoint并发8passed，共39passed；新增
  通用任务取消入口也验证父子任务取消、预算保留和正文未写入。
- 浏览器：World共创/地图7passed，Assistant确认/跨页恢复/390px键盘1passed，均使用专用
  数据库与合成模型/图片响应，不构成真实模型质量或生产验收。相关临时服务均已退出。
- frontend lint、build及生产产物验证通过；21份手工调整Python文件格式检查通过；
  docs-check BASE_REF=origin/main和工作树/暂存区git diff --check通过。
- 所有整合修改仅在本工作树。原目录交付文件tree与初始Agent快照一致，原main不动。
  当前HEAD=8ee03fb9b（隔离WIP快照），MERGE_HEAD=main的6eec78cca；合并结果已暂存，
  尚未创建merge commit、未推送/部署。主干/源分支清理不在本次授权范围。
- 日志：backend/.test-artifacts/integration-ci-final.log、integration-pg-critical.log、
  integration-pg-agent.log、integration-browser.log、integration-browser-workflows.log。
  当前最终tree与父提交记录在忽略产物integration-state.json中，便于后续验证未漂移。

下一步：用户授权提交/合入main时，先核对上述基线、当前index tree和main状态；若无新增
变化，完成本工作树merge commit，再按授权更新main。若任何基线变化，重新核对差异并
验证受影响路径。正式模型质量、人工验收和部署仍延期，不能从本轮工程绿色推导完成。


## 本地 main 合并完成

用户随后明确要求“合并”。预检确认已验证tree e45de383f824727c61564828bcaa1600b924bd5b、
整合HEAD与main基线均未漂移，main工作树干净。已创建合并提交
`a6c9ecf8a20ab11f190419aa7806b62b775cecbb`，其tree与上述验证结果完全一致；
本地main已由6eec78cca fast-forward到该提交。本记录随后作为独立文档提交同步到main，
不改变已验证业务代码。未重复运行无变化的整套回归。

交付：Agent接入及冲突解决已进入本地main。未推送/部署，原Agent工作树WIP保留；
整合分支与工作树未清理。本节取代此前“待授权提交/合入”的恢复状态。
下一步：只有用户要求推送或发布时才继续相应交付，执行前重验远端与本地状态。
