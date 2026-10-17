# Codebase 文档刷新结果与验证边界

时间：2026-10-14T11:30:33+08:00。源码固定基线：`22bb499789cba89fea92e918fd853ab768688e07`；收尾远端 main 与 origin/main 仍为该 SHA。

7名 `gpt-6-luna/max` 领域代理完成定向理解与文档修订。按用户最新要求，最终两路独立复核均使用 `gpt-6.1-sol/high`；旧Luna复核保留历史。7项早期语义问题及Sol新增1项运行时凭据边界错误已修复并定向确认；最终桌面/中屏/窄屏视觉复验通过，本地文档验收已关闭。

## 当前交付

- 正式文档在隔离树 `/Users/tywww/.codex/worktrees/docs-refresh-luna/ai-writing-assist`，分支 `codex/docs-refresh-luna`；29个既有文件修订、3个新登记阅读/图形文件、1份执行计划。原主树正式文档和其它任务WIP没有被本轮批量覆盖。
- [Codebase阅读与运行边界](/Users/tywww/.codex/worktrees/docs-refresh-luna/ai-writing-assist/docs/architecture/codebase-reading-guide.md)：从问题定位真实入口、资料和写入拥有者，不复制权威表/路由/任务目录。
- [HTML运行图](/Users/tywww/.codex/worktrees/docs-refresh-luna/ai-writing-assist/docs/architecture/runtime-boundaries.html)及[Draw.io图源](/Users/tywww/.codex/worktrees/docs-refresh-luna/ai-writing-assist/docs/architecture/runtime-boundaries.drawio)：正文候选、演化、绑定作品的RP、本机世界对象图片4条不同流程。
- [当前用户指南](/Users/tywww/.codex/worktrees/docs-refresh-luna/ai-writing-assist/docs/product/new-user-guide.md)：当前入口、模型连接、保存失败保护、授权导入和撤销边界。旧Word源稿与现存DOCX只保留历史身份；未新生成二进制导出。
- 表格：[72条结论/证据/处置](claims.csv)、[文档处置](doc-disposition.csv)、[源码读取分级](source-coverage.csv)。[基线清点](doc-inventory.csv)仅路径快照，不能解释为逐行审计。

## 核心修正

- 同一幂等键重复采用返回原稿；无键/异键拒绝。Scene执行资料经Story facade；Workbench拆分仍共用服务、仓储和锁。
- Local Agent正常新建入口仅图片，Project/直接snapshot拒旧文字设置；旧claim/companion文字兼容仍在。未查询真实旧pending记录，未将兼容路径重新授权为文字能力。
- RP只把已释放visible_text正式化；审查前hold私有。停止清除可恢复消息，仍保留hold审计记录且不经API返回。
- Canon五个formal family保持disabled；公开preview只Page/Revert，正式提交业务侧拒Assertion。地图/Canon消费者缺口和单盘图片无外部备份明确保留。
- Evidence补confirmation/focused-search API，GET读历史摘要不重新编译；imports补HTM。图片credential-only验证与文本最小生成验证分开。
- DI组合根/类型化键、已注册有界Agent及独立eval暂停边界校准。没有把模型政策或合成测试写成当前provider接线、文学质量或生产启用。

## 证据与独立复核

[7领域报告与claims](research/)绑定B。72项claim处置：26项对应更新，43项按现有说明保留，1项运行时接线未知，2项关系历史反例覆盖限制；数字不是实测通过数量。

679条基线文档相关路径全部分类，新增3个当前登记件，当前登记57项。1,381条生产源码路径仅登记路径，其中152条有L1–L7 claim绑定的定向段落阅读；分级不统计主代理/R1/R2额外回读，也不证明每个文件每行都已理解。受限运行日志和个人PDF仅路径清点，未读正文。

- [R1独立契约复核](research/R1-REVIEW.md)：4项发现已修复，按owning source定向确认。
- [R2独立可理解性复核](research/R2-REVIEW.md)：3项发现已修复，旧轮语义问题已关闭；最终浏览器与图片复查见后续Sol报告。

- [Sol/high最终契约复核](research/SOL-CONTRACT-REVIEW.md)：新增SC-1已修复并回读；Account内部profile含瞬态Key，公开/持久投影无Key。最终CSV已加入本次独立校正来源。
- [Sol/high最终视觉复核](research/SOL-VISUAL-REVIEW.md)：独立查看9张最终图并核对6源SHA与截图指纹，允许关闭限定视觉验收。
- [最终视觉验收详单](VISUAL-ACCEPTANCE.md)与[原始核对包](visual-verification.json)。

## 实际验证

| 检查 | 结果与范围 |
|---|---|
| 起始 `make docs-check`；收尾 `make docs-check BASE_REF=origin/main` | 通过；12业务模块、152ORM表、60handler、16route、40ADR；当前链接/登记和差异规则 |
| L6 `make prompt-contracts` | 26个静态合约通过；没有模型或DB |
| `git diff --check`及文档范围自检 | 通过；无业务源码/测试/配置改动；检查新文件换行/行尾 |
| CSV/JSON生成自检 | 唯一键、必需字段、固定SHA、source路径存在、无未处置queued项通过 |
| `verify-diagram-pairs.py` | 两XML的ID/edge有效；运行图4标题/20节点/16有向连接与HTML精确一致 |
| 修改前HTML浏览器检查 | 390/768/1440宽度、离线阅读、键盘、减少运动、无横向溢出/脚本错误通过，已查看PNG |
| 最终标签后的HTML视觉复验 | 通过：同一内置浏览器经正式支持的localhost HTTP检查两HTML 1440/768/390、工具栏390展开/收起、焦点与键盘图内滚动；9张新JPEG与源SHA绑定。修正工具栏溢出和3处图源文字余量；Sol/high独立读图通过 |

没有运行本轮业务pytest/CI、真实模型/DB/用户文稿、图片provider、生产配置/备份/恢复/部署或作者质量验收。测试源码只说明断言范围。Draw.io的既有可视证据为XML几何预览，不是原生Draw.io渲染。

## 恢复与交付边界

唯一主任务笔记仍是原主树 `TASK.md`；本文件与证据在集成树的副本只是交付快照，不是第二份进度源。领域writer树已停写，保留供diff复查；未清理任何其它工作树或数据。

本地未提交、推送、合并或部署。无剩余必需文档验收项。此前file协议失败保留历史；本轮核对正式浏览器文档后使用支持的localhost HTTP完成验证，未改安全配置或使用其他浏览器/CDP。图源辅助图不是原生Draw.io渲染，可选Copy/PNG/PDF/打印未实测；这些不作为通过声明。
