# ADR-0034 — 数据库配对的私有图片备份与恢复

- **状态**: Accepted / local implementation; production enablement pending
- **日期**: 2026-10-14
- **决策来源**: 用户批准审计首批 G4a，同机独立目录、作者手动导出先行、全部保留期不超过 30 天
- **修订**: ADR-0010 的数据导出非目标、ADR-0014 的无对象副本风险；延续 ADR-0012 的私有图片与不可变 key

## 背景

PostgreSQL dump 不包含两个 MinIO bucket 的图片。数据库与对象各自备份但未绑定快照，会把
在线库后来新增或已清理的 key 当成旧 dump 的恢复资料；同时 restic 的六个月策略超过隐私承诺。

## 决策

1. 独立 `backup_objects.sh` 在生产 operation lock 内先创建并校验 custom-format dump，再在无网络、
   无生产卷挂载的临时 PG 恢复该 dump。只对这个临时库运行 `object_references.sql`；不再次读取在线库。
   全部地图 review 状态的页面和 mask、世界对象当前 image_version 的 full/thumbnail 都进入清单。
2. `deploy/backups/objects/` 与 MinIO named volume 分离，目录 0700、文件 0600，拒绝 symlink。
   `objects/<bucket>/<immutable-key>` 保存镜像，`snapshots/<DB timestamp>/manifest.json` 及
   `manifest.sha256` 保存配对记录。世界对象没有 DB hash，读取时流式计算；地图页面的 DB hash/size
   有值时必须一致。重复备份复用不超过 retention 的合法清单 hash，本地校验 hash/size 并对源 HEAD 验证存在、
   size 与 metadata；匹配时不做 GET、无重复磁盘复制，缺失/不符才流式获取。相同引用去重，hash/size
   冲突失败关闭，不发布不可读取的重复清单。损坏或发布中断的历史清单不提供缓存，输出脱敏告警，
   但不阻断新快照复制和校验。
3. 清单 schema 为 `ai-writing-object-backup/v1`，显式区分 `source_kind=server_snapshot/author_export`，
   共用 timestamp、每行对象清单与文件布局。server_snapshot 必须包含实际 DB timestamp、dump 文件名及 SHA-256；
   author_export 的这三项必须为空，不能伪造 DB 配对；包含
   `complete/incomplete` 状态；每行包含 novel_id、bucket、key、sha256、byte_size、类别（map_page、
   map_mask、world_full、world_thumbnail）、状态、content_type 和原始对象 metadata；可选 `file` 是包内 objects 下相对路径，可用中文，
   不提供时使用 bucket/key。拒绝穿越、重复名、缺图和不匹配的 hash。清单本身也有 SHA-256。
   开始即写 incomplete，缺失/中断保留 missing/failed/pending；只有全量复制与校验通过才写 complete。
   单个对象缺失或内容损坏只记该行 missing/failed，其余对象继续复制；传输、权限或本地磁盘故障停止本轮，
   未处理行保留 pending。
4. 备份 ops 服务只有独立的 List/Get-only MinIO 身份，不共享 root 或应用凭据；数据 network 无公网。
   initializer 以 root 建桶、去匿名访问、启用 versioning、设置 8GiB/24GiB 配额及应用/备份 policy。
   恢复 ops 服务使用应用身份回灌图片，不得到 root。错误与收尾摘要不打印 SDK 敏感详情。
5. 新 object backup timer 在每日 03:17（数据库 timer 02:17）发起，并与发布、DB 备份、恢复和清理共锁。
   不接入 release 前置门禁，不改 backup.sh stdout 或 deployment-state dump 配对，不删发布回退对象。
   两个对象运维入口经既有 load_release_id 核验已完成部署状态，选择固定 SHA 镜像；非法状态在任何 Compose 调用前拒绝。
6. DB 本地 retention 上限 30 天；restic 用 `--keep-within 30d --prune`。对象清单按 DB timestamp 老化；
   镜像只删除不再被任何保留清单引用、且自身年龄超过 retention 的文件。不完整清单仍保护已复制对象；
   清单损坏时停止垃圾回收；新备份状态与保留清理结果分别报告，清理失败仍以非零退出码提示运维核对。
   永久删除项目/账号前缀随清单老化，不在线提前移除历史恢复资料。
7. 运维 `restore_objects.sh <private-directory> <timestamp>` 或单参数私有 ZIP 都先完成包与目标 DB 校验，
   然后重建桶配置并回灌；ZIP 用一次性 ops 解包至私有临时目录，退出清理；对账 hash、size、
   PNG/WebP 可解码、metadata 与 key 的 novel_id。两类来源共用恢复入口，先与目标 DB 的 novel_id/bucket/key/hash/size 引用核对，禁止跨项目导入；
   图片包不恢复 DB，author_export 不宣称 DB 快照一致。所有本地文件先校验，才开始远端写入；恢复仍可中途失败，
   不承诺跨对象事务。ZIP 与服务器目录采用相同布局，经 `object_backup.py unpack` 严格白名单解包并校验。
   G4b 已提供单项目 owner 导出 UI：浏览器计算摘要、解码校验并打包地图页、蒙版及对象 full/thumbnail；
   部分失败可重试，作者确认后才下载标注缺项的包，取消或离开中止下载。G4c 自动同步需要独立授权。

## 结果与限制

同机副本覆盖误删和桶损坏，不能抵抗整盘故障；作者本机导出（G4b）和未来 B2 才提供独立设备副本。
新增对象备份不上传 B2、不调用模型、不新增常驻服务或媒体 API。合成演练的实测 RPO/RTO 仅代表七张
小图与专用环境，不代表真实容量 SLA；临时 PG 使用本次容器的新建匿名数据卷，无固定数据容量截断；PGDATA 为 0700、UID/GID 999，
保持无网络、只读根文件系统和 1 CPU/2GiB 内存上限。成功及失败都仅 `docker rm -fv <本次容器>`
清除其匿名卷，不使用生产 PG/MinIO 卷、不执行全局 volume 清理。生产启用前仍须核验剩余磁盘容量。生产启用仍须发布授权、固定 origin/main SHA release、配置独立凭据、启用 timer 后只读对账。
