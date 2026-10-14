# PR #227 独立审查

审查时间：2026-10-14T14:12:59+08:00。范围固定为 base
`e02137f79fc4e8f5ba4f79f541b66b5dbaa47a05` 到 head
`4acf184c4426adca5d1f5bc883e2d7ab1ce75047`；本地未提交收尾记录不计入代码审查。
PR：https://github.com/FengHuoLinShan/ai-writing-assist/pull/227。

用户要求独立子代理 review。三名全新 GPT-6.1 Sol / medium 审查者分别检查规范、计划和 G4
备份可靠性，没有复用实现者。主 Agent 复核专项问题的实际调用方，并使用真实函数的隔离合成探针
验证。确认 **1 项 P1、1 项 P2**，建议修复后再合并；本轮没有修改产品代码或部署脚本。

## 规范轴

`review_227_standards` 未发现可达的 P1/P2 规范违规，也没有单独报告 Fowler 判断建议。
核对 G3 renderer 导出与调用方、旧文字 pending/approve/claim/RP 快照失败关闭、历史回执、
G8 Writing → Evolution → World → Vue 调用链、owner/novel 过滤、只读 DI port、SAVEPOINT
降级与回执持久化。结论不覆盖 G4 存储可靠性专项。

## 计划轴

`review_227_spec` 未发现 G3/G8 的可达 P1/P2：活跃 renderer `_TIER_HEADERS` 至 EOF 与基线
逐字一致，隐藏真相和开放义务断言保留；旧文字入口/快照失败关闭；地图按 current saved head
和历史稿身份核对，只作建议、不改变 Scene 窗口和重算选项。G4 仅完成基本规格核对，不能覆盖
下述专项发现。

独立定向合成测试：
`modules/evolution/tests/test_map_consumption.py modules/local_agent/tests/test_text_retirement.py modules/interaction/tests/test_services.py -k 'map_consumption or legacy or text_settings'`
得到 19 passed / 83 deselected。

## G4 可靠性专项：已确认问题

### P1：正式对象备份入口的临时文件名不符合发布器合同

- 位置：`deploy/scripts/backup_objects.sh:15-16,37`；共享校验
  `deploy/scripts/backup_pair_publish.py:14,103-109`。
- 触发：正常运行 `backup_objects.sh`，且前面的 dump/归档校验成功。systemd service 的
  `ExecStart` 直接调用此入口（`deploy/systemd/ai-writing-object-backup.service:12`）。
- 证据：入口创建 `.object-db-stage.*` 与 `.object-db-checksum.*`，发布器只接受 `.backup-*`
  或 `.rehydrate-*`。真实发布器合成调用稳定 exit 1，报 `staging path is outside the private
  backup directory`，无最终 dump；`set -eu` 使脚本在临时 PG/对象复制前退出。
- 影响：对象 timer 每次运行均失败，不能生成任何完整图片备份；既有独立 DB 备份不受这条
  错误影响。CI 的图片演练走独立 harness，没有覆盖这个正式入口的发布合同。
- 最小修复：复用发布器认可的临时前缀，并补一个真正执行该入口发布环节的合同测试。

### P2：清单发布中断会使后续新备份持续失败

- 位置：`deploy/scripts/object_backup.py:119-126,294-298,541-544`。
- 触发：新快照目录创建后，在 JSON 已发布、SHA 尚未发布的窗口断电/杀进程/写入失败；
  或更新清单时两者暂时不匹配。
- 证据：`publish()` 分别替换两个文件。故障探针在 SHA 发布前抛 OSError，保留 JSON 而无
  sidecar；之后两次调用真实 `main()` 的 backup 分支均 exit 1 / FileNotFoundError，未创建
  各自的新快照目录。历史扫描在新快照创建之前，且没有隔离损坏清单。
- 影响：一次中断会阻断以后所有新图片备份，必须人工清理/核对才能恢复。ADR-0034:38
  要求损坏时停止垃圾回收，并不要求停止生成新备份。
- 最小修复：损坏清单不提供缓存、显式报警，但允许创建新备份；垃圾回收继续失败关闭。
  另一方案是完整清单目录原子发布，同时处理创建后尚未发布清单的遗留目录。

## 非阻断建议：服务器快照的错误 DB 配对防护

专项 reviewer 提出的第三项经主 Agent 与计划 reviewer 复核后不列为 P2。
`object_backup.py:322-336` 只校验清单属于目标引用；server_snapshot 清单 1 对象、目标 2 对象
会通过，遗漏的目标对象不会被恢复。但 `deploy/README.md:328` 明确要求先恢复 timestamp/hash
匹配的 DB dump，正常完整备份由该 dump 的全集生成，当前反例违反此文档前置，不能声称
正确配对恢复也会漏图。

可增加防误配检查：server_snapshot 校验引用集合相等及配对信息；author_export 保留子集语义。
这不是本次合并阻断项。

## 主审验证与边界

- 根复核探针：`/private/tmp/audit-pr227-root-review-probe.py`；结果见
  `artifacts/review-root-probes.json`。全部为合成字节、合成 key、私有临时目录，没有网络/DB。
- 已读取固定 head 的调用链与计划 §6.3，所有被报告代码均在本次 diff 中。
- 文档检查：`make docs-check` 与 `git diff --check` 通过。裸
  `make docs-check BASE_REF=origin/main` 仍要求六份既有架构文档复核；读取本 PR 正文已有的
  逐项无影响说明后，以脚本支持的 `--no-change-reason` 完成同一增量检查并通过，未修改门禁。
- 未访问真实数据库、Guimi、稿件、账户或模型；未执行 Docker、生产脚本或容量演练，未重跑
  全量测试/浏览器。历史 CI 通过不推翻上述真实函数反例。
- 交付仅为本地报告与任务事实纠正；未提交、推送、评论 PR、合并或部署。
- 下一步：后续执行应先修复两项确认问题，补入口与清单发布故障回归，运行受影响部署测试与
  文档门禁，再独立复核。当前用户请求为 review，本轮不执行修复。

## 后续整改跟踪

此文件保留 4acf184c4 的历史审查结论，不代表后续修复版本仍有上述两项问题。
用户随后授权修复并更新 PR #227，暂不合并。两项本地修复及 7 项新增回归已完成，六项故障
反例已证明修复前失败、修复后通过；专题 41、完整部署 309 项通过，隔离双桶恢复通过。
新 head 的独立 GPT-6.1 Sol / xhigh 审查结果将另存 REVIEW-XHIGH.md，执行状态以 TASK.md 为准。
