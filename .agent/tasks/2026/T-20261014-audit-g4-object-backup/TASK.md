---
id: T-20261014-audit-g4-object-backup
title: G4a 图片对象备份和恢复
status: completed
created: 2026-10-14T11:00:00+08:00
updated: 2026-10-14T12:03:42+08:00
---

# G4a 图片对象备份和恢复

## 恢复快照

- 本地实现、相关验收及主审容量修正已完成，等待主代理独立审查和集成；没有提交、推送、PR、合并或部署。
- 工作区：`.worktrees/audit-g4-object-backup`，`codex/audit-g4-object-backup`，基线 `22bb499789cba89fea92e918fd853ab768688e07`。
- 下一步：主代理检查本树 diff，整合共享文档复核理由，再在获授权的集成流程完成评审。
- 阻塞：无本地环境阻塞；生产启用明确未授权，不接触实际服务器、生产 env/root 凭据或真实数据库。
- 最后核实：2026-10-14T11:55:02+08:00。

## 目标与验收

按首批计划 §6.3 G4a：两桶全部地图状态页/mask、当前对象 full/thumb；DB 配对清单/自身 SHA、只读 List/Get 身份、不可变 key 增量镜像、不完整失败关闭、30 天老化、独立 service/timer 和真实隔离恢复对账。目录/ZIP 共用清单，不实现 G4b UI/端点。

## 上下文与边界

本任务仅本 worktree；不改主树、G2、共享索引或 docs-refresh WIP。无真实稿件、模型调用、B2 对象副本开通、常驻新服务、主栈更换、发布或提交授权。`backup.sh` stdout 与 release dump 配对不变，对象备份不接发布门禁，不删回退对象。

## 决策、发现与失败

- 先产生并校验 custom-format dump，再在无网络临时 PG 真恢复和运行 SQL 取清单；不以 live DB 后查伪装同快照。
- 不可变 key 的可信缓存来自 retention 内合法 server_snapshot 清单；本地 hash/size + 源 HEAD/metadata 命中时 GET=0，缺/不符才流式复制。重复 DB 引用折叠，hash/size/类别/novel 冲突失败关闭。
- v1 显式 source_kind：server_snapshot 必须实际 DB timestamp/dump/SHA；author_export 不得包含 DB 配对。每行支持中文相对 file，拒绝穿越/重复/缺图；目标 DB 引用须拥有同一 novel/bucket/key 和适用 hash/size。图片区恢复不恢复 DB、不能跨项目导入。
- 同一 restore shell 接收目录+timestamp 或单参数 ZIP；一次性 ops 私有解包、全部文件/目标引用验证在任何桶写入前执行，临时文件退出清理。
- restic 改 `--keep-within 30d --prune`，env retention 1–30；对象清单按 timestamp 老化，无引用且超龄对象和空目录清理，损坏清单停止垃圾回收。
- 首轮真实演练发现 macOS/Linux Pillow 编码字节差异；DB fixture 改为与实际上传相同的 Linux 编码 hash，未放松 checksum。MC version/anonymous 的实际 JSON 为嵌套 versioning.status / permission=private，按真实输出修正断言。
- 初始 uv 默认缓存受沙箱限制；使用已授权的只读 codex-luna-runtime Python 3.14.7，未修改共享依赖。专用 Docker runtime 从未修改的 backend/Dockerfile 和 uv.lock 构建；所有 audit-g4a 容器已清理，未动受保护旧容器/端口。
- 已只读核对 docs-refresh 对 deploy README/12_infrastructure 的 diff（无未提交重叠）；无外树写入。

## 验证证据

证据目录：`/private/tmp/audit-g4a-evidence/`，全为合成数据和脱敏日志。

- 开工 `make docs-check` 通过。
- 最终 `make test-deploy BACKEND_LOCKED_CI_RUN='<只读 runtime Python> -m'`：300 passed，`test-deploy-final.log`。
- 增量/目录 ZIP 边界/retention/最小权限/部署契约相关用例：176 passed，`final-targeted.log`；命中缓存 GET=0、坏本地重取、远端删除 incomplete 已覆盖。
- 真实服务器式演练：两桶七图、metadata/private/versioning/8GiB+24GiB、只读身份拒绝 Put/Delete/CreateBucket/Policy、DB dump 后 live 删除仍从恢复快照取得7项、源缺失/流中断均 incomplete；实测合成 RPO=2.547s、RTO=4.781s，`server-drill-summary.json`（由真实 tool 输出转录的摘要）。
- 后续共享格式和中文 author_export ZIP：真实 shell + Docker Compose 入口恢复七项，通过同一 PNG/WebP hash/size/decode/metadata 对账、匹配目标 PG 引用；不含 DB SHA，`author-shell-drill.log`。只有独立合成资源、network none、无主机端口，非 mock/static 演练。
- `make lint`、`make repo-gates` 通过：`lint.log`、`repo-gates.log`。既有 Git 范围 gates 以 HEAD 比较，工作树新脚本另经 Ruff、实际演练与 shell syntax 检查。
- `git diff --check`、sh -n 新脚本/initializer、新增 Python 的 Ruff 通过。
- 默认 `make docs-check BASE_REF=origin/main` 提示 ADR 对 development-guide、testing-guide、docs/architecture/README、documentation-maintenance 的复核；已逐项核对无规则变化，按现有 `--no-change-reason` 合同通过，`docs-check.log`。主代理 PR 须保留该明确复核理由，不能声称无条件默认命令通过。

## 交付结果

已交付：独立 object backup/restore 脚本、SQL、清单/增量/老化/ZIP 工具、ops Compose、service/timer、独立只读凭据与 policy、300 部署测试及真实演练、ADR-0034、ADR-0010/0014 修订、deploy README/12_infrastructure。

未交付：G4b 作者 UI/端点、G4c 自动同步、B2 对象副本、真实生产容量与故障/磁盘损坏 SLA、生产发布与启用。合成小图的 RPO/RTO 不代表真实规模；主审发现 PG 包含 candidate/reuse 图片字节，数据可合法超过2GiB；已改为本次匿名磁盘卷，
PGDATA 0700/999，无固定数据量截断、仍保留2GiB内存上限；启用前核验剩余磁盘空间。恢复中途失败可能已回灌部分精确 key，可修复后重试，不自动删除历史版本；同机副本不防整盘故障。

生产启用须另获发布授权，仅经固定 origin/main SHA release，配置分离凭据、initializer、四个 timer/失败告警后执行一次只读对账；实际库容量需复核。损坏清单或停用调度会延迟 retention，必须运维修复。正式清单协议见 ADR-0034 和 deploy README。

## 主审容量修正（2026-10-14）

- 目标：消除临时 PG 数据目录的固定2GiB上限，不改同批dump→恢复→引用SQL流程。
- 实现：新匿名 `/var/lib/postgresql/data` 卷、PGDATA 子目录0700；成功/EXIT失败路径仅 rm -fv 本次容器和匿名卷。其余tmpfs、network none/read-only/CPU/RAM上限保持。
- 验证：74项部署脚本契约测试通过；专用 `--snapshot-volume-only` 真实成功/坏归档失败恢复与权限验证通过，两种路径均确认本次容器和匿名卷已删除，证据 `/private/tmp/audit-g4a-evidence/snapshot-volume-drill.log`。
- 下一步：主代理复核和集成；本次Ruff、sh -n、git diff --check及带既有无变更理由的docs检查已通过，证据 `volume-script-contracts.log` / `volume-docs-check.log`。无生产操作/提交/推送；不重跑无关图片/浏览器/模型测试。
