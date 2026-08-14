# ADR-0014 — 世界对象图片与单机 MinIO

- **状态**: Accepted
- **日期**: 2026-08-14
- **关联**: ADR-0012 的地图册对象存储

## 背景

作者需要在对象库中快速辨认人物和长期设定，但图片不应变成公开图库、通用媒体平台或新的
RAG/LLM 来源。地图册已使用私有 S3 语义；首版部署需要为对象图片复用这条受限路径，同时保持
生产凭据、容量和删除边界可审计。

## 决策

1. `core_entities` 只增加可空 `image_version` 与 `image_updated_at`；响应派生 `has_image`，不保存
   或暴露 object key。浏览器通过 owner 与 `novel_id` 双门禁的上传/读取接口获得缩略图或完整图。
2. 上传只接受真实 PNG/JPEG（严格小于 6MiB、最大 4096×4096），去 EXIF/元数据后输出 WebP。
   完整图最长边 896px、最大 256KiB；缩略图 192×192、最大 16KiB。人物使用水平居中、上方约
   四分之一的头部优先裁切，其他类型居中裁切。
3. 账户最多保存 20 张人物图及合计 50 张其他对象图；回收站项目仍占配额，替换不新增占用。
   对象软废弃、融合和别名化不迁移或删除图片；项目永久删除才排入精确对象和项目前缀清理。
4. 开发与生产均使用固定 digest 的单节点 MinIO，分为私有地图册（8GiB）与世界对象（24GiB）
   bucket。两个 bucket 都启用 versioning，清理任务删除对象及其历史版本；两者合计 32GiB，是
   单盘对象数据硬上限。生产只允许内部 data network 访问，禁用管理控制台。
5. `MINIO_ROOT_*` 仅供 MinIO 与一次性 bucket initializer 使用。API/worker 只取得现有
   `MAP_ATLAS_S3_*` 连接与应用凭据（加 `WORLD_OBJECT_S3_BUCKET`），policy 仅允许两桶的定位、
   列举（含版本）、Get/Put/Delete 对象及 DeleteObjectVersion；不允许创建 bucket 或修改 bucket
   policy。

## 结果

- 单盘 named volume 没有外部图片备份；磁盘故障会丢失图片。这是首版明确接受的上线风险，数据库
  与常规 restic 备份不承诺恢复图片。
- 存储 adapter、清理和错误补偿保持在地图册/world 所属模块，不建设通用 media API、图库、图片
  历史、人脸识别、裁切编辑器或图片进入 RAG/LLM 的能力。
- 图片加载或处理失败不影响对象文字资料的编辑；对象卡片保留无图首字色块回退。

## 未采用方案

- PostgreSQL BLOB：扩大数据库 I/O 与备份/恢复成本。
- 公开 bucket、公开 URL 或将 object key 交给浏览器：绕过账户与项目边界。
- 共享 root 凭据：运行时服务可越权改 bucket 或读取所有对象。
- 外部对象备份、多节点 MinIO、通用媒体平台：首版容量和恢复需求不足以证明其运行复杂度。
