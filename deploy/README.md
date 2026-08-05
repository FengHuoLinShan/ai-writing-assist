# `zy` 生产部署

本目录提供可审查、固定 commit、先备份后迁移的单机生产部署。它不会把开发
`docker-compose.yml` 暴露到公网，也不会把真实密钥提交到 Git。

当前目标拓扑：

```text
Internet
  -> Cloudflare Tunnel (public HTTPS)
    -> 127.0.0.1:3259
      -> 1Panel OpenResty (security headers, 50 MiB upload boundary)
       -> 127.0.0.1:18080 (frontend)
       -> 127.0.0.1:18000 (API)
            -> PostgreSQL private data network
       worker -> PostgreSQL private data network
       api/worker -> local TEI embedding + approved LLM provider egress
```

这是按 `zy` 当前 1Panel v2.2.3 / OpenResty host-network 模式生成的拓扑。API 和
frontend 只绑定宿主机 loopback，不对公网开放；PostgreSQL、worker 和 embedding
完全不发布宿主机端口。OpenResty 无需也不能再连接 Compose bridge 网络。

## 已确认与尚待填写

复制 `.env.production.example` 后填写下列 `CHANGE_ME` 项。校验器会在任何必填
决策或密钥未完成时拒绝发布。

| 状态 | 配置 | 说明 |
|---|---|---|
| 已确认 | `DEPLOY_DOMAIN=novel.zhh.se` | 现有 Cloudflare Tunnel 的公共主机名 |
| 已确认 | `OPENRESTY_TUNNEL_PORT=3259` | Tunnel 的 loopback HTTP 源站端口 |
| 已确认 | `AUTH_MODE=public` | 首发即启用邮箱账号体系 |
| 已确认 | `DATABASE_MODE=fresh` | 首次发布若发现已有 public 表会拒绝继续 |
| 已确认 | `LLM_RATE_LIMIT_PER_MINUTE=0` | 用户使用项目 LLM 配置；仍保留并发上限 |
| 已确认 | `EMBEDDING_*` | zy 本机 CPU TEI + `BAAI/bge-base-zh-v1.5`，768 维 |
| 待填写 | `AUTH_SECRET_KEY` | 新生成至少 32 字符 |
| 待填写 | `BOOTSTRAP_OWNER_EMAIL` | 新库 bootstrap 的私有 owner 邮箱，只写入服务器 `0600` 环境文件 |
| 待填写 | `SMTP_*`、`SUPPORT_EMAIL` | 兼容 SMTP 的 host、登录、发件与支持邮箱，只写入服务器 `0600` 环境文件 |
| 待开通 | `B2_*`、`RESTIC_*` | 私有 Backblaze B2 bucket、限定 bucket 的 key、restic 密码 |
| 待开通 | `HEALTHCHECKS_*_PING_URL` | 三个检查，通知收件人只在私有监控配置中设置 |

Authing 微信保持关闭，直到真实扫码验收通过。

## 准备生产环境文件

在服务器的专用 checkout `/opt/ai-writing-assist` 中：

```bash
cp deploy/.env.production.example deploy/.env.production
chmod 600 deploy/.env.production
python3 deploy/scripts/validate_env.py --env deploy/.env.production
```

真实 bootstrap owner、SMTP host/login/from、support email 与监控通知收件人只可保存在服务器
当前用户拥有、权限精确为 `0600` 的 `deploy/.env.production`；不要将它们写入示例、文档、测试或 Git。

可使用以下命令生成独立随机值；不要复用本地开发密钥：

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
cd backend
python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

`POSTGRES_PASSWORD` 只允许 URL-safe 字符，以便 Compose 安全构造 asyncpg URL。
`POSTGRES_IMAGE` 与 `EMBEDDING_IMAGE` 都必须写为显式 tag 加小写 64 位 SHA-256 digest；
校验器拒绝可变 tag、缺 tag、截断/大写 digest 与附加字符。生产 PostgreSQL 当前固定为
`pgvector 0.8.6-pg17-bookworm` 的已审查 digest。固定 digest 使发布输入可复查，并不承诺
不同 Docker builder 的镜像层逐字节一致。
真实 `.env.production`、备份和发布状态均已加入 `.gitignore`。校验器会强制生产
env 文件不是 symlink、归当前有效用户所有、且权限精确为 `0600`；不满足时即使使用
`--get` 读取单个值也会拒绝。

容器 stdout/stderr 使用 Docker `local` logging driver 滚动保存。每个服务最多约
100 MiB（10 个各 10 MiB 的文件）；这不是 30 天的时间保留，也不替代 OpenResty/1Panel
外部访问日志或集中日志。OpenResty 访问日志仍按下文的 30 天策略保留。

## 首次发布

发布只能接受完整的 40 位 commit SHA。脚本会检查干净工作树、拉取远端、构建固定
tag 镜像、启动 PostgreSQL、创建并验证 custom-format 备份、运行 Alembic、处理公开
模式 bootstrap 认领、启动应用并进行容器内健康检查。

```bash
bash deploy/scripts/release.sh <full-40-character-commit-sha>
```

Cloudflare Tunnel 的 `novel.zhh.se` 公共主机名应使用 HTTP 源站
`http://127.0.0.1:3259`。公网 TLS 由 Cloudflare 终止，OpenResty 只监听 loopback，
不占用宿主机的 80/443。发布完成后渲染与 1Panel host 网络兼容的站点配置：

Cloudflare Tunnel 是公网客户端身份的信任边界。OpenResty 对 API 与 frontend upstream 都使用
`CF-Connecting-IP` 覆盖（绝不追加）`X-Real-IP` 和 `X-Forwarded-For`；loopback 直连属于受信
host scope。若该 header 缺失，nginx 不传递空值，后端会安全地共享 direct-proxy bucket。这里不验证
当前外部 Cloudflare 设置，也不提供分布式或全局 DDoS 防护承诺。

```bash
python3 deploy/scripts/render_openresty.py \
  --env deploy/.env.production \
  --output /tmp/ai-writing-assist.conf
```

将渲染结果放入 1Panel 管理的 `/opt/1panel/www/conf.d/`，并在 OpenResty 容器内执行
配置测试后再 reload。最后验证公网链路：

```bash
bash deploy/scripts/verify_public.sh
```

`release.sh` 与 `restore.sh` 会共同检查 API `/api/health`、前端入口及既有稳定运行时脚本，
并确认 worker 容器的 PID 1 的独立 argv token 为 `run_worker.py`，且控制循环 marker 在 30 秒内
更新；三项都通过才会写入成功发布状态，避免容器仅因 `/healthz` 可达而掩盖静态文件权限、缺失、
worker 退出或只剩 PID 的空转问题。带有
`deploy/frontend-asset-contract.version`（当前值为 `1`）的提交还必须提供由生产构建验证器生成的
`asset-inventory.txt`：容器内和公网验证都会逐项请求清单中的全部资源，并校验内容类型。没有该 marker 的历史提交继续使用稳定脚本检查，以保证回滚不会被新合同阻断；但带 marker 的提交缺少或提供无效清单会直接失败，绝不静默降级。`verify_public.sh` 还会从公网入口确认 HTML 声明资源属于清单。只有该脚本通过，才代表
DNS、TLS、OpenResty、前端运行时资产、API 和数据库的完整公网链路通过。

`deploy/worker-liveness-contract.version` 的当前值为 `1`。仅当历史固定 SHA 完全没有该 marker
（且不是 symlink）时，shared health gate 才回退到旧 worker 的精确 PID 1 argv-token 检查，以便恢复
到 Phase57 前的镜像；新版本的 marker 是 fixed-SHA tracked contract，发布输入和部署合同会验证其存在。
marker 已存在但损坏、非普通文件或内容不匹配时会 fail closed，绝不静默降级。当前 Compose healthcheck
直接运行 v1 liveness CLI。

生产 worker 收到 SIGTERM 时，`run_worker.py` 会调用 `TaskWorker.stop()`，停止新 claim 并 drain
已领取的任务；Compose 通过 `stop_grace_period: 2m` 给这段过程两分钟。超过窗口 Docker 会 SIGKILL，
此时任务不会被承诺完成，而是由既有 lease heartbeat 与 stale recovery 的崩溃恢复路径接管。

`verify_public.sh` 无参数时保留上述完整发布验收，包含 `asset-inventory.txt` 的所有发布资源。
`runtime_health.sh` 每轮先复用本机 API、完整内部前端资产和 worker 进程健康检查，再执行一个
小型真实 embedding 向量/维度探测，最后调用 `verify_public.sh --runtime`；后者只校验公网 HTTPS API、
入口和入口 HTML 声明的 JS/CSS，避免每 5 分钟遍历完整资源清单。embedding 探测以 45 秒总预算、
10 秒单请求和 5 秒重试间隔运行，避免 timer 长时间挂起；它不检查外部 LLM provider 或任何 LLM
调用，也不验证向量的语义质量。它们都不会创建或启用外部 Healthchecks 检查。

## 日常更新

每次发布继续使用固定 commit：

```bash
bash deploy/scripts/release.sh <new-full-commit-sha>
```

### 部署合同测试

提交前可在现有后端 pytest 环境运行：

```bash
make test-deploy
```

该目标执行 `deploy/tests` 的静态/CLI 合同测试，并已作为后端 CI 与本地
`make test-ci` 的门禁。它会对本地 shell helper 做摘要/健康组合行为验证，并对脚本
顺序与 Compose 声明做静态合同检查；它不启动 Compose、不访问外部服务，也不替代真实发布、
公网验证或备份恢复演练。

发布、恢复、独立/嵌套备份、账号清理与 runtime health 共享主机本地的
`deploy/.state/production-operation.lock`，并都使用 exclusive `flock`。release/restore 中调用的
backup 会复用继承的 FD，不会自我死锁。生产变更首次获取锁最多等待固定 300 秒，仍被占用则以既有
“another production operation”错误 fail closed；runtime health 首次获取遇到安全有效但已占用的锁时会打印
一条无 secret 的 skip 诊断并以 0 退出，且不会读取环境/发布状态、运行 Git/Docker/curl，或发送
Healthchecks `/start`、成功或 `/fail` ping。这样计划中的发布/恢复不会产生误报。健康检查真正获得锁后会
在完整的本机和公网检查期间持续持有它，所以一个最多 5 分钟的健康运行也会让新的生产变更有界等待。
持久的 `0600` 文件存在是正常状态，操作可能进行时不得删除；进程崩溃后由 OS 自动释放锁。它只是协作脚本的
同主机 advisory coordination，不是分布式、全局或跨主机锁。

### Production image contract

`make test-production-images` 单独构建 backend 与 frontend 生产 Dockerfile，并运行容器级
smoke checks：backend 必须以非 root 运行、没有构建期 uv、且可导入应用；frontend 必须通过
`nginx -t` 且入口、manifest 和资产清单是可读普通文件。它需要 Docker daemon 和镜像仓库访问，
因此不放入日常 `make test-ci`，但 GitHub Actions 会以独立 `Production image contract` job
执行。

生产 Compose 只对第一方 `api`、`worker`、`frontend`、`migrate` 和
`account-maintenance` 施加只读根文件系统、移除全部 Linux capabilities 与
`no-new-privileges`。backend 进程仅通过 `/tmp` tmpfs 写入临时解析文件；frontend 仅通过
nginx 用户拥有的 `/run` 和 `/var/cache/nginx` tmpfs 写入。PostgreSQL 与 embedding 不继承这套
未经各自验证的策略。镜像合同 smoke 在相同受限 flags 下检查有效 UID、零 `CapEff`、`NoNewPrivs: 1`、
不可写应用/静态目录、backend tempfile，以及实际 nginx health/asset 请求。

这些限制降低第一方容器内的意外写入和提权面，但不会消除应用漏洞、Docker daemon、宿主机或
依赖镜像风险。若生产出现未声明写路径，保留日志并通过既有固定 SHA 发布流程回滚本次聚焦提交；
不得为临时修复把根文件系统改回可写。

本地 smoke target 只构建并验证镜像运行时合同；CI 在其后对两份本地镜像生成 CycloneDX
SBOM（OS 与 library 清单），先验证并上传为保留 14 天的 artifact，再执行门禁扫描。SBOM
保留未修复与低严重度发现以便审查；门禁只阻断可修复的 HIGH/CRITICAL 漏洞。通过扫描不代表
镜像或供应链不存在任何风险。

镜像轮换必须把新上游 tag 和 digest 一起复核，并在同一次改动中更新 Dockerfile、生产 Compose/
示例环境文件、CI service image 和合同测试；不可仅改 tag 或仅改 digest。该过程不改变 API、
数据库 schema、前端 wire 形状或正常用户操作，所有作者与读者画像只会获得更一致的发布结果。

### 分支与发布规则

- 本地开发从最新 `origin/main` 创建 `codex/<slug>` 主题分支，不直接在 `main`
  提交；验证和评审完成后再合入 `main`。
- `main` 是唯一发布主干，不维护长期“生产分支”。历史部署实现分支不能代表当前线上版本。
- 生产只接受 `origin/main` 可达的完整 40 位 commit SHA。`release.sh` 会先 fetch
  `origin` 并拒绝主题分支独有、本地未推送或无法解析为精确 SHA 的提交。
- 服务器 checkout 在发布后保持 detached；当前线上版本以
  `deploy/.state/deployment-state.json` 的 `current_commit` 为准，不以服务器当前分支名或本地工作树状态推断。
- 回滚同样选择一个仍可达 `origin/main` 的已知良好 SHA，并继续走备份、迁移和健康检查，
  不把生产机切回某个长期分支。

脚本在 migration 前保存备份，并只在 shared health gate 成功后写入唯一权威状态
`deploy/.state/deployment-state.json`。v1 JSON 恰有 `schema_version: 1`、32 位 operation nonce、
`release`/`restore` operation、当前/前一 40 位 commit 和本仓库 `deploy/backups` 直属 `.dump` 的规范绝对路径。
文件必须是当前用户拥有的普通 `0600` 文件，目录必须是私有 `0700` 目录；未知/缺失字段、重复 key、错误类型、
multiline、symlink、错误 owner/mode 或不安全路径都 fail closed。helper 以私有临时文件完整写入并 fsync，再原子 replace
与 fsync 目录；旧 manifest 不安全或损坏时绝不覆盖。健康检查失败时 API、worker 和 frontend 会停止，数据库及备份保留，
不会把失败发布继续对外提供。

下一次 release、restore、runtime health 或 account maintenance 优先读取 manifest 的 `current_commit`，并继续要求它
精确解析且可达 `origin/main`。只有 manifest 完全不存在时，才以既有只读 legacy `current-release`（12 位前缀）+
`current-commit`（40 位 SHA）pair，或首次发布 HEAD 作为兼容回退；新脚本不删除、重写或更新这些旧文件。失败或取消的
尝试会切回这份已完成 checkout，并在本次可能已启动 new application services 时停止它们。写 manifest 的 catchable-signal
临界区覆盖临时文件、file fsync、rename、directory fsync 与临时清理；若 signal 在 durable rename 后、shell boolean 更新前
抵达，cleanup 仅在 `current_commit` 和本次唯一 nonce 都匹配时保留 target。仅发给 helper 子进程的 HUP/INT/TERM 会在临界区
被吞掉，使它正常完成并让 shell 观察到同一份 target authority；组信号仍由 shell trap 处理。若 rename 后 directory fsync
失败，helper 会先原子恢复写前的精确 manifest bytes（首次写入则删除新文件）并再次 fsync 目录，恢复确认后才返回失败让 shell
回滚。若恢复不能完成，helper 只会在已验证 target manifest 仍可见时带 warning 成功退出，让 shell 保持 target；不会留下
`manifest=target` 却让 cleanup checkout 到 previous 的分裂。SIGKILL/掉电没有 shell cleanup，atomic replace 提供旧或新记录。cleanup trap
本身不会 reset/clean 工作树、额外写入或恢复数据库、重启旧服务或改写最终状态；但在数据库替换或 migration 后失败的底层
操作可能已经改库，服务会保持停止并需要人工恢复。本说明描述仓库内脚本合同，不表示生产机器或外部服务已经实际验证。

runtime health 在读取这份 manifest（或 manifest 完全缺失时的 legacy pair）、环境或运行任何 Git/Compose/curl 前先取得同一 exclusive operation
lock；若有 mutation 正在持锁则本轮成功 skip，不发送主动 ping。它不会掩盖持续故障：timer 仍按既有 5 分钟
节奏运行，Healthchecks 的 missed-ping/grace 仍是长时间停机或持续维护的告警路径。account maintenance 与
runtime health 在任何 Compose 操作前也只从这份已验证的 manifest（或 manifest 完全缺失时的 legacy pair）导出本地镜像 `RELEASE_ID`
（完整 commit 的前 12 位），绝不信任残留 checkout 的 HEAD。若 `.state` 存在，
它必须是当前用户拥有、非 symlink、权限精确为 `0700` 的私有目录；不安全或不完整状态会 fail closed。
首次发布时 manifest 与 `current-release`/`current-commit` 两个 legacy 文件都不存在则使用当前、
`origin/main` 可达的 HEAD；若 `.state` 目录本身也不存在，只读检查不会创建它。这描述仓库脚本合同，
不表示生产状态已经实际验证。

restore 在 fetch/check-out 前先用当前 checkout 的 validator fail fast；成功切换到 target commit 后，
会在 image build、备份 archive list、确认提示、停服或任何数据库操作之前重新运行 target 自带的 validator。
该 target 校验失败时，既有 cleanup 只会恢复 finalized checkout/state，且不会执行 Docker 操作或进入 downtime。
这描述仓库脚本合同，不表示生产环境已经实际验证。

release 与 restore 在 fetch 前及 target checkout 后各执行一次严格 deployment-checkout guard；任何 tracked、
staged 或 unmerged 路径都会拒绝。仅 untracked/ignored 运行时数据可使用 `deploy/.env.production`、
`deploy/.state`（及其 descendants）与 `deploy/backups`（及其 descendants）这一精确 allowlist；这些路径绝不允许
被 Git 跟踪。两次 checkout 均以本次 Git
调用禁用 hooks，避免主机本地 hook 在 guard 前执行。target validator 通过后，脚本从目标 40 位 commit 的 tracked
Git tree 以 `git archive` 创建私有临时 build snapshot，并用临时 Compose override 将所有第一方 build context 定向到
该 snapshot；`.env.production`、state、backups、ignored cache 和其他 worktree 内容不会进入 Docker context。override
与 snapshot 会持续到本次 release/restore 结束后清理。它保证固定 source provenance，不承诺基础镜像、网络、工具链或
Docker builder 输出逐字节相同；本说明不表示外部生产环境已验证。

target checkout 的环境校验后、build context 前，release/restore 还要求 tracked
`deploy/deployment-state-contract.version` 恰为 `1`，且目标 commit 自带可执行的 stdlib state helper。这样旧 target
无法在新脚本写入 manifest 后被静默部署；缺 marker/helper 或不匹配即在 build、停服和数据库操作前 fail closed。

release 在 target preflight 与 target API/frontend build 完成后、pre-migration backup 前进入有界
maintenance window：先停止 API、frontend 与 worker（worker 依既有 2 分钟 grace drain），再 reconcile
target PostgreSQL 与 embedding，随后执行首次 fresh database guard、embedding contract check、snapshot、
migration 和新服务启动。依赖镜像或 Compose 配置变更时 Docker Compose 可能 recreate 容器，所以 reconciliation
必须在旧 application services drain 后进行；这会使有界 downtime 比仅迁移阶段更长。restore 也会在确认与二次
checksum 后、safety backup 和任何数据库替换前走同一停服门槛。停止失败会阻断后续数据库工作；quiesce 之后失败
会让 application services 保持停止并需要人工恢复。代价是作者和读者在发布/恢复期间会短暂不可用，收益是避免
旧代码与新 schema 或已替换依赖容器重叠；这不是零停机方案，也不表示生产演练已完成。

## 备份、恢复和账号清理

手动备份：

```bash
bash deploy/scripts/backup.sh
```

备份写入 `deploy/backups/`，使用 `pg_restore --list` 验证并生成 SHA-256 sidecar，然后由
restic 加密、去重后上传私有 Backblaze B2。保留 7 个 daily、4 个 weekly 和 6 个
monthly 快照；超过 `BACKUP_RETENTION_DAYS` 的本地备份会自动清理。脚本在开始、成功
或失败时 ping Healthchecks.io；告警收件人只由私有监控配置决定。

备份与恢复都将 `deploy/backups/` 当作私有文件系统边界：脚本会以原子创建或打开的目录
描述符校验其最终路径不是 symlink、是当前用户拥有的目录且权限精确为 `0700`；当前用户拥有的
既有宽松目录会收紧为 `0700`，所有者、类型、路径 inode/device 或元数据在校验期间不一致时直接
拒绝。恢复在解析所选备份之前执行此检查，备份则在 healthcheck、staging 清理和数据库操作之前执行。
这是仓库内脚本合同，不表示生产主机的目录状态已经验证。

每次备份先以两份私有唯一 staging 文件写入并校验，再发布完整的 `.dump` 与 `.sha256`；同一 UTC
timestamp 的已发布文件或 sidecar 存在时拒绝覆盖。可捕获的失败或信号只清理当前和遗留的 staging
文件，以及本次发布未完成的精确 half-pair，绝不删除已完成 pair。完成 local pair 后立即按现有
本地 retention 清理，后续 restic 不可用、上传或 forget 失败仍保留新 pair；本说明不表示外部备份或
Healthchecks 已被验证。

在 zy 安装 restic、初始化仓库（密码丢失将无法恢复）：

```bash
apt-get update
apt-get install -y restic
set -a
. deploy/.env.production
set +a
restic init
```

上线前必须完成一次临时库恢复演练。Backblaze 和 Healthchecks 的真实 key/URL
只放在 `deploy/.env.production`，不进入 systemd unit 或 Git。

恢复是破坏性操作，要求明确输入确认短语，并在覆盖前再创建一份安全备份。恢复会先要求
同名 `.dump.sha256` 为非空普通文件（不能是 symlink），其中只能有一条小写 64 位 SHA-256
记录；脚本直接重算所选 `.dump` 的摘要而不信任 sidecar 中的文件名。缺失、格式错误或不匹配
都会在确认和数据库写操作前拒绝继续：

```bash
bash deploy/scripts/restore.sh \
  deploy/backups/<timestamp>.dump \
  <matching-full-commit-sha>
```

将 `deploy/systemd/*.service` 和 `*.timer` 安装到 `/etc/systemd/system/` 后：

```bash
systemctl daemon-reload
systemctl enable --now ai-writing-backup.timer
systemctl enable --now ai-writing-account-maintenance.timer
systemctl enable --now ai-writing-runtime-health.timer
systemctl list-timers 'ai-writing-*'
```

backup oneshot 的保守 `TimeoutStartSec` 为 4 小时，account-maintenance 为 1 小时；两者都使用
`TimeoutStopSec=2m` 与 `KillMode=control-group`。超时会令该 service 失败，并在给予 shell/Docker CLI
子进程 TERM/cleanup 窗口后由 systemd 结束整个 control group；Healthchecks 的 `/fail` 或 missed ping
仍是告警路径，进程终止后 OS 会释放共享 operation lock。两项 service 还 `Wants`/`After=network-online.target`，这只保证启动排序，不证明 Internet、
B2 或 restic 已可用。数值是保守的病态上限而非 SLA；应在观察实际运行时间后通过经过评审的 systemd drop-in
调整，并完成外部 Docker daemon/容器终止演练。本说明不表示该演练已完成。

账号清理超过 26 小时、备份超过 26 小时、或 runtime 健康检查主动报告失败/漏 ping 时必须告警。
为 runtime 的 5 分钟周期在 Healthchecks 配置适度 grace（例如 10 分钟），并演练 `/fail` 与 missed
ping 告警。operation lock 持有时 runtime 的无 ping skip 是预期行为；grace 不应长到掩盖超过维护窗口的
持续不可用。真实 ping URL 和外部检查仍需由运维人员在 Healthchecks 单独创建与配置。OpenResty 访问
日志保留 30 天，数据库本地备份最多保留 30 天。

## 上线门禁

上线前必须全部满足：

1. `validate_env.py` 通过，生产文件权限为 `0600`。
2. 固定 commit 的后端测试、前端测试、lint 和生产构建通过。
3. Alembic 只有一个 head；空库迁移和目标库备份通过。
4. `closed_test` 的共享令牌或 `public` 的 SMTP/bootstrap 登录路径验收通过。
5. OpenResty 配置测试通过，只有 80/443 对公网开放。
6. `verify_public.sh` 通过。
7. B2 加密备份成功，并完成恢复演练。
8. systemd 的 backup、account-maintenance 和 runtime-health 三个 timer 正常，Healthchecks
   邮件告警已完成 `/fail` 与 missed ping 演练。

本目录不自动申请域名/证书、不创建 SMTP/Authing/LLM 账户，也不保存任何真实凭据。
