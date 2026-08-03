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
| 待开通 | `HEALTHCHECKS_*_PING_URL` | 两个检查，邮件通知发到 `948620502@qq.com` |

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
真实 `.env.production`、备份和发布状态均已加入 `.gitignore`。

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
避免容器仅因 `/healthz` 可达而掩盖静态文件权限、缺失或 worker 退出问题。`verify_public.sh` 还会从公网入口解析并
逐一请求当前 HTML 声明的脚本和样式，校验成功状态与内容类型。只有该脚本通过，才代表
DNS、TLS、OpenResty、前端运行时资产、API 和数据库的完整公网链路通过。

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
systemctl list-timers 'ai-writing-*'
```

账号清理超过 26 小时、备份超过 26 小时或任务主动报告失败时必须告警。OpenResty
访问日志保留 30 天，数据库本地备份最多保留 30 天。

## 上线门禁

上线前必须全部满足：

1. `validate_env.py` 通过，生产文件权限为 `0600`。
2. 固定 commit 的后端测试、前端测试、lint 和生产构建通过。
3. Alembic 只有一个 head；空库迁移和目标库备份通过。
4. `closed_test` 的共享令牌或 `public` 的 SMTP/bootstrap 登录路径验收通过。
5. OpenResty 配置测试通过，只有 80/443 对公网开放。
6. `verify_public.sh` 通过。
7. B2 加密备份成功，并完成恢复演练。
8. systemd 两个 timer 正常，Healthchecks 邮件告警已做失败演练。

本目录不自动申请域名/证书、不创建 SMTP/Authing/LLM 账户，也不保存任何真实凭据。
