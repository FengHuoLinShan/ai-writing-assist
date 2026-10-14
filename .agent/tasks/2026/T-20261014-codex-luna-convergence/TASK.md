---
id: T-20261014-codex-luna-convergence
title: G2 Codex Luna运行时收敛
status: active
created: 2026-10-14T11:36:30+08:00
updated: 2026-10-14T13:49:31.019101+08:00
---

# G2 Codex Luna运行时收敛

## 目标与授权

用户在源线程01a1386b-f1a0-7550-b2f2-f3bfc1bb39eb的真实userMessage01a1386c-05e2-7282-aa01-d593dcd78648明确要求G2由Codex原线程执行，已通过read_thread核验。规格为根.worktrees/audit-followup/docs/plans/2026-10-14-audit-followup-batch.md §4及§10：最新main上单一运行时PR，ADR0033/迁移/权威文档/验收报告；owner、当前授权、包装快照、未知不重放、取消/超时、Key/登录轮换、跨worker账户并发均有证据。

当前会话用户“全部授权”覆盖G2实现、验证、提交、推送/PR和门禁后的合入。Guimi T-20261012仍paused，自动化60已删除；不恢复全量或确认真实缺口，不重放旧hash/case，不部署、不清理八旧树、不向源线程发送消息。工程使用Sol/高级模型；必要新业务探针仅verified owner→Project facade/snapshot→原生gpt-6-luna/max。无需记录Luna额度或费用；本G2规格要求的新探针次数单列，不读/调用付费API、Key或embedding。

## 工作树与版本

- 当前附着目录：/Users/tywww/.codex/worktrees/g2-codex-luna-convergence/ai-writing-assist，分支codex/g2-codex-luna-convergence。
- 从main22bb499789cba89fea92e918fd853ab768688e07（PR222）新建；已并入模型规则main e02137f79fc4e8f5ba4f79f541b66b5dbaa47a05。
- 模型规则PR225已squash合入该e02137f7，全部CI通过；六文档仅迁入原b22f7334e规则，保留main教师/holdout暂停记录。旧规则树未清理。
- 单一运行时PR226：https://github.com/FengHuoLinShan/ai-writing-assist/pull/226，已附着。已推送HEAD904530e891d3ac2f0720cc5028f23b83eb6251a3，其CI存在8个账户测试失败及1个地图浏览器失败，不能合入。
- 当前WIP只包含本轮复核修复、对应测试/文档及本任务记录。G2独占provider/migration/W8四README；不改G8a的DI键/注册/ADR0031/模块检查器或G3旧本机API/RP。

## 已完成及证据

- /tmp/codex-luna-g2/inventory.json冻结118份W8及八旧树；OLD-TREE-REVIEW.json逐条裁定60路径差异（54内容、6presence），58相同。old-tree-preservation-proof.json再次核验八树全部记录文件hash零漂移，没有凭路径覆盖就认内容超集。
- 迁入并手工解决10个主干冲突，保留PR222服务拆分、语义manifest和教师暂停；未调用的退休helper删除。八份纯格式改动已恢复。原稿、旧运行库、unknown及付费账本未变。
- native v3固定Luna/max，当前owner连接/ChatGPT身份回读、显式包装版本/指令hash进入snapshot、本机同系统用户同账户API/worker共享fcntl槽（默认2、整数1..8、空闲才改容量）。metadata-only失败诊断；未知执行不自动重发；旧local_agent文本快照失败关闭、历史回执可读。确定性配置拒绝不计可用性熔断，仍不证明供应商可用。
- 旧约1.91秒unknown仅能证实缺原退出码/回合事件及宿主环境差异，因果未定、不能归为并发过载；旧请求无重放。官方non-interactive-mode说明ephemeral无rollout留存，未来诊断保留白名单元数据。
- 3204项扩大后端（3 real/external deselected）、9项PG领域/窗口门禁；专用migration库约束、危险降级拒绝、往返及alembic check通过；初版前端39项通过。后续517、1554、451回归集合重叠，不相加。旧API Key轮换、新登录身份、真实跨进程槽、源化resume均有测试。
- 唯一新增真实native3请求：专用codex_luna_g2_probe_test中账户显式验证1次、facade/open-map和snapshot/closed合成提取各1次，全部完成；后两者10.91/11.62秒且exit0/turn.completed。私有terminal.json在/tmp/codex-luna-g2/native-probe-v3-config-fixed。首次脚本误标unknown的marker保留，pre-dispatch-proof.json证明它在provider构造前受平台auth644权限守卫拒绝、零I/O；修复后才首次发送。未重发实际unknown。小样本不证明长篇或八路稳定/文学质量。

## 当前复核修复

Code Review技能只读两路固定904530e，报告见REVIEW.md：Standards两项P2（独立图片Key误隐藏、预检丢未知元数据）；Spec一项P1（导入恢复会重复无journal的原生验证探针）。尚待修后复核，不能将原报告当通过。

- 图片Key与错误区域恢复独立显示，Codex文本无Key规则仅限文本；新增合成Vue失败/可操作检查，无实际图片API调用。
- 账户active继续表示已选择，清Key保留选择且禁止运行；UI未连接显示“已选择”，不声称正在使用。连接测试按provider身份断言，新默认Codex与旧已选付费提供方/门禁契约分别保留。
- Codex导入预检只检查已验证配置/登录/包装并通过Project当前授权回读，不再发送模型探针；scope=project_configuration、remote_check=false。真实验证仍只在账户显式入口。7种正常/漂移配置各重复预检两次均零派发，撤销授权关闭客户端，新增8项回归。
- 账户66项、前端40项及最终受影响后端1619项通过/2 real deselected/1既有OpenAPIwarning；取消/unknown原规则未削弱。最后仅精简预检失败回传及稳定contracts导入，专用回归尚待终态。
- 地图CI失效证据为刷新后编辑工具按产品规则折叠，旧用例漏掉展开操作；补一条用户点击，原移动持久化、城市图创建等断言完整保留，不改地图生产代码。真实浏览器重验待新HEAD CI。

## 恢复快照与一个下一步

所有新请求已终态，无业务driver/自动任务。根Guimi HANDOFF仍为暂停入口；旧v2快照不静默升级为v3，恢复需用户明确恢复并合法重验来源/请求/版本与成功前缀。

下一步：核验专用预检终态和模块依赖棘轮（仅将稳定contracts导入移到模块层，绝不升基线）→最终Ruff/docs/secret/diff→提交复核修复并推送PR226→两路只读复核新固定HEAD及最终CI→按当前授权合入、记录mergeSHA和交接；没有完整门禁前不合入，不启动Guimi，不部署。

## 2026-10-14T13:39:52.673667+08:00 最新签收快照

修复已提交并推送abb5b9682632e7137ce6dbc05e564212412f5565。两路独立修后复核都确认原问题闭合，增量无新发现。新HEAD后端全量/PG/CodeQL/前端单元/镜像/文档与仓库门禁均远端通过，仅浏览器两shard仍在运行。当前不得用此前失败904530e签收或合入；下一步等同一abb5b968全部浏览器/聚合终态，通过后按授权squash合入、记录mergeSHA并保存最终handoff。自动化60文件再次核实不存在，无业务请求追加，旧树不清理。这一最新快照覆盖上方历史待办。

## 2026-10-14T13:49:31.019101+08:00 浏览器门禁纠正

abb5b968后端远端7962 passed/2 skipped，coverage86.84%；部署合同272 passed，PG与全部其它门禁通过。浏览器shard2通过，shard1地图用例仍失败。两个实际error-context分别显示合法的专注/编辑模式；此前固定展开操作判断不充分，已改为等待展开或编辑的可见入口，仅在专注时展开，再继续原编辑/保存/子图断言。地图生产代码和所有Python均未变；ESLint通过，禁止据失败head合入。下一步提交这次E2E适配及已完成复核记录，核验新HEAD全部CI后按授权合入；仍不启动业务。
