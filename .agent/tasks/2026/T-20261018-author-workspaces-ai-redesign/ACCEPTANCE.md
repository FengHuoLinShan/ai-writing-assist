# 作者工作台改造验收记录

日期：2026-10-18。范围为 [HANDOFF.md](HANDOFF.md) 六批；执行状态以 [TASK.md](TASK.md) 为准。
全部变更位于本地主题分支，保留已有 WIP；未提交、推送、合并、远端 CI 或部署。

## 已实现与工程证据

| 批次 | 交付 | 验证 |
| --- | --- | --- |
| 1 | 精确正文/对象/档案/关系焦点，有限集合，冻结摘要，临时稿讨论，隔离草稿与往返恢复 | 跨账户/项目、来源版本/排除范围、迟到响应/冲突；1280/900/390 返回原段实际可见，中文/emoji/重复引文/长稿 |
| 2 | 写作四路径、对象/前文固定参考、按需助手；世界详情分区、经历来源和搜索关系端点 | 原手动保存/确认/采用入口；浅深色、窄屏、键盘及失败恢复；资料不冒充利用证明 |
| 3 | 共享 ActionBatch/Goal 任务授权、专用 low 判断、根预算、失效/撤回/回执 | 三态、注入/越界/人工保留项、预览变化、未知/超时、并发撤回和重放；真实模型结果另列 |
| 4 | 局部修改组组成完整派生候选、独立重审/采用；关系修改/结束/移除/历史恢复 | 两宽度选组→重审→刷新→采用→手改；领域真实 CAS/幂等与 PostgreSQL 竞争，关系移除始终人工 |
| 5 | 服务端冻结对象身份/版本清单，20 项分页和勾选处置，最近清单恢复；现有 Goal 依赖与影响查证 | 新对象不混入、变更不算已核对、同名仅线索；依赖真实回执身份/端点重验、scope CAS/并发；部分成功保留原回执 |
| 6 | 版本化操作帮助、来源回原文、提醒复用、存为参考/成果导航、旧运行兼容、文档 | 不调用模型的操作帮助；长 emoji 原文及同章第二次定位；完整创作试改/恢复、资料工作稿确认/回读，原正文不变 |

最近证据（路径为本机日志，模型 I/O 合成的浏览器不算真实模型质量）：

- 完整前端：267 文件 / 3306 passed；`/tmp/author-workspaces-final-frontend.log`。最终 Forecast 成果导航组件另 1 passed，`/tmp/author-workspaces-forecast-ui.log`。
- Assistant/World 焦点、清单/关系和 Goal/公共契约：391 passed；`/tmp/author-workspaces-batch56-backend.log`。此前 World+Assistant+目录/治理 1951 passed、1 deselected，`/tmp/author-workspaces-relation-backend-all.log`。
- 最终 Forecast/校准 CLI/Goal 依赖：28 passed，`/tmp/author-workspaces-last-backend.log`。
- 治理/架构：65 passed，`/tmp/author-workspaces-batch56-governance.log`；依赖基线未放宽。
- PostgreSQL：清单/关系并发 2 passed，`/tmp/author-workspaces-relation-pg.log`；授权并发 2 passed，`/tmp/author-workspaces-approval-pg.log`（历史各轮命令见 TASK）。
- 作者工作台完整功能浏览器：65 passed（2.7m），`/tmp/author-workspaces-workspaces-final-browser.log`。
- 助手/编辑员完整 API/worker 浏览器：12 passed（1.9m），`/tmp/author-workspaces-assistant-complete-final-browser.log`。
- 创作跨流此前 9 passed（2.0m），`/tmp/author-workspaces-creative-crossflows-browser.log`；新增完整“下一步→存参考→打开成果→返回→试改采用→刷新”1 passed（34.1s），`/tmp/author-workspaces-reference-save-complete-browser.log`；加入该路径后的 9 项全套复验也通过（2.3m），`/tmp/author-workspaces-creative-delivery-complete-browser.log`。
- ESLint、production build（14 引用/59 JS bundles/98 发布路径）、`make docs-check BASE_REF=origin/main` 和 `git diff --check` 通过。最终新文档加入后再跑 docs-check。

最新收尾（覆盖上述旧轮次对应范围，历史日志保留）：

- 全前端267文件/3308 passed（33.46s），`/tmp/author-workspaces-delivery-frontend-final.log`；全量ESLint与production build通过，日志`delivery-lint-final`/`delivery-build-final`。
- 助手全模块/公共facade/目录349 passed（32.07s），`/tmp/author-workspaces-assistant-backend-guard-final.log`，包括临时上下文准备/确认均禁止正式修改且无授权/执行回执；新增边界测试首次漏传confirmed，修正测试后通过，未改门禁。
- 完整助手/编辑员14项浏览器通过（2.2m），`/tmp/author-workspaces-assistant-delivery-final-browser.log`；临时门禁后两个宽度再验2 passed（23.4s），`/tmp/author-workspaces-temporary-formal-guard-final-browser.log`。延迟真实保存请求核对原稿、讨论、保存后重新绑定及旧轮不变；合成模型IO。
- 写作/批注33 passed（1.5m），`/tmp/author-workspaces-writing-adopt-final-browser.log`；409/412并发冲突另2 passed（15.5s），`/tmp/author-workspaces-writing-conflict-final-browser.log`。采用后即时手改两宽度真实完整链通过，消除重复加载正文覆盖新输入的竞争。
- 助手扩大/收起保持同一输入和选区、390×420短视口焦点可见；已查看扩大浮层和临时讨论手机渲染。真实设备软键盘仍未验。
- Ruff、`make docs-check BASE_REF=origin/main`、`git diff --check`通过；最新门禁日志`/tmp/author-workspaces-temp-guard-docs-final.log`。

## 审查整改验收（2026-10-19）

R1–R7 已全部修复，另补齐扩大门禁发现的能力/路由/固定输出预算登记和清单项目索引。
具体反例、修复边界、首次失败与最终证据见 [REVIEW.md](REVIEW.md)。本轮未重跑真实模型。

- 完整快速后端 9291 passed / 2 skipped，覆盖率 85.32%；完整前端 267 文件 / 3318 passed。
- 针对性 PostgreSQL 24 passed；PG critical 105 passed / 3 个已确认干净 HEAD 基线失败，新增迁移失败全部消除。
- 浏览器 8 passed，覆盖两宽度重新选组/刷新/重审/采用/手改、代批撤回、草稿撤回后刷新与关系恢复；真实 API/worker，模型 I/O 合成。
- 全量 ESLint、Ruff lint、修复文件 format、diff 空白检查通过。全仓 format 剩余 167 个均在干净 HEAD 的失败集合内，无新增失败，见 [ENGINEERING-BASELINE.md](ENGINEERING-BASELINE.md)。
- 新索引迁移只升级两套确切专用测试库；原 Guimi/G7b/校准库不改。仍未提交、推送、合并、部署，作者体验和真实文学质量未新增验收。

## 实际模型校准（历史结果，本轮未重跑）

用户指定G7b v3隔离库evolution作品 / Codex / 仅Luna。原库只读备份后在本任务专用容器复制迁移；原库未写入/迁移/续跑。校准前后原库与副本120条文稿全字段聚合指纹相同。

单独授权的1次Luna/max连接检查完成。最终新轮固定18案例经Project专用Luna/low，18/18三态符合预期，误放行0、误阻断0；18请求全部结算、零unknown，用量完整175726 token，低于新授权262144上限，无自动重试。

随后只读查询当前真实配置，approval_availability返回available=true。通过回执仅属于G7b校准副本，不修改原库或声称其他作品自动模式已开放。开始任何自动任务仍须显式任务范围授权及每次领域重验。

早先默认guimi/DeepSeek17/18为选早了的错误目标历史运行；G7b旧轮7请求因回执校验及65536额度耗尽停止。两轮失败证据均保留，不计入最终18/18。完整逐例结果、指纹和私有账本见[CALIBRATION.md](CALIBRATION.md)。

## 限制与未验事项

- 完整 PG 历史套件仍有 24 个在干净已跟踪 HEAD 同样复现的基线失败；详见 [ENGINEERING-BASELINE.md](ENGINEERING-BASELINE.md)。不是全量绿色，也没有削弱有效断言。
- 选组浏览器旧独立世界提案fixture失败证据保留；现已对纯正文返回空提案并显式核验真实子任务完成，两宽度完整流程通过。
- 构建有既有 chunk size 提示；实际作者试用、文学质量、真实生成/证据利用/最小修改的模型质量没有验收，不能据工程检查声称效率或品质提升。
- 生产、远端 CI、非 Chromium/真实软键盘行为未在本轮验证。原有部署和真实数据门禁保留。
