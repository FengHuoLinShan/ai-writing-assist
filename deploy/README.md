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
| 已确认 | `BOOTSTRAP_OWNER_EMAIL` | 新库 bootstrap 账号归属 `948620502@qq.com` |
| 待填写 | `SMTP_PASSWORD` | 网易邮箱客户端授权码，只写入服务器 `0600` 环境文件 |
| 待开通 | `B2_*`、`RESTIC_*` | 私有 Backblaze B2 bucket、限定 bucket 的 key、restic 密码 |
| 待开通 | `HEALTHCHECKS_*_PING_URL` | 三个检查，邮件通知发到 `948620502@qq.com` |

Authing 微信保持关闭，直到真实扫码验收通过。

## 准备生产环境文件

在服务器的专用 checkout `/opt/ai-writing-assist` 中：

```bash
cp deploy/.env.production.example deploy/.env.production
chmod 600 deploy/.env.production
python3 deploy/scripts/validate_env.py --env deploy/.env.production
```

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
并确认 worker 容器的 PID 1 仍在运行 `run_worker.py`；三项都通过才会写入成功发布状态，
避免容器仅因 `/healthz` 可达而掩盖静态文件权限、缺失或 worker 退出问题。带有
`deploy/frontend-asset-contract.version`（当前值为 `1`）的提交还必须提供由生产构建验证器生成的
`asset-inventory.txt`：容器内和公网验证都会逐项请求清单中的全部资源，并校验内容类型。没有该 marker 的历史提交继续使用稳定脚本检查，以保证回滚不会被新合同阻断；但带 marker 的提交缺少或提供无效清单会直接失败，绝不静默降级。`verify_public.sh` 还会从公网入口确认 HTML 声明资源属于清单。只有该脚本通过，才代表
DNS、TLS、OpenResty、前端运行时资产、API 和数据库的完整公网链路通过。

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
  `deploy/.state/current-commit` 为准，不以服务器当前分支名或本地工作树状态推断。
- 回滚同样选择一个仍可达 `origin/main` 的已知良好 SHA，并继续走备份、迁移和健康检查，
  不把生产机切回某个长期分支。

脚本在 migration 前保存备份并把当前/前一 commit、镜像 tag 和备份路径记录在
`deploy/.state/`。健康检查失败时 API、worker 和 frontend 会停止，数据库及备份保留，
不会把失败发布继续对外提供。状态文件以同目录临时文件加原子替换写入，且
`current-release` 始终最后更新，表示对应三服务已健康。

## 备份、恢复和账号清理

手动备份：

```bash
bash deploy/scripts/backup.sh
```

备份写入 `deploy/backups/`，使用 `pg_restore --list` 验证并生成 SHA-256 sidecar，然后由
restic 加密、去重后上传私有 Backblaze B2。保留 7 个 daily、4 个 weekly 和 6 个
monthly 快照；超过 `BACKUP_RETENTION_DAYS` 的本地备份会自动清理。脚本在开始、成功
或失败时 ping Healthchecks.io，由其向 `948620502@qq.com` 发告警。

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

账号清理超过 26 小时、备份超过 26 小时、或 runtime 健康检查主动报告失败/漏 ping 时必须告警。
为 runtime 的 5 分钟周期在 Healthchecks 配置适度 grace（例如 10 分钟），并演练 `/fail` 与 missed
ping 告警；真实 ping URL 和外部检查仍需由运维人员在 Healthchecks 单独创建与配置。OpenResty 访问
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
