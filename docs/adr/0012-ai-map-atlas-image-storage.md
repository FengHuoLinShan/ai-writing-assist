# ADR-0012 — AI 地图册图片运行时与对象存储

- **状态**: Accepted / Implemented
- **日期**: 2026-08-12
- **取代**: ADR-0003 的 Leaflet 地图视口决策

## 背景

旧地图以六边形、动态图层和时间化 Map Fact 为中心，既不能形成作者可直接浏览的视觉地图册，
也把地图事实维护成本扩散到 imports、memory 和 writing。新产品要求根据已确认资料规划层级，
由固定图片模型生成候选，并由作者选择是否加入地图册。

图片字节不适合进入 PostgreSQL；本地磁盘不能覆盖多 worker 与部署；现有通用任务表又会随
项目级联删除，因此还需要处理“生成 worker 晚到上传”和“项目永久删除”之间的竞态。

## 决策

1. 旧地图表和 `/api/world/maps*` 直接破坏性删除，不迁移旧数据，也不提供兼容端点。地图册只保留 run、node、page、annotation 四表。
2. 图片固定使用 OpenAI Image API 的 `gpt-image-2`。账户图片连接独立于文本 provider，只复用通用加密凭证表；项目通过 `open_project_image_client()` 与 secret-free snapshot 取得运行时。
3. 图片存入 map-atlas 自有 S3 adapter，使用 boto3 在线程池执行；每次尝试使用不可变 key `map-atlas/{novel_id}/pages/{page_id}/attempts/{task_id}-{attempt}/image.png`，page 只指向胜出 attempt。浏览器只经 owner 与项目门禁的后端接口流式读取。
4. 每次编辑都新建 page，并用 `derived_from_page_id` 追溯；不建立 revision 或 edition。
5. 生图 checkpoint 在 `provider_in_flight` 失联时要求作者确认可能重复扣费，禁止无条件自动重试。
6. finalization 持项目 share lock 完成上传、复核 task lease 与 `review_ready` 落库，整段只提交一次。失败补偿只删精确 attempt key。永久删除持项目 exclusive lock，先取消生成、再创建 `owner_scope=global` 且 `novel_id=NULL` 的幂等项目前缀清理任务，最后删除项目。
7. `20260812_ai_map_atlas` 会永久删除旧地图表。非开发环境且已有项目数据时，migration 必须收到本次发布的一次性确认短语、备份文件名和 SHA-256 证明才能 drop。支持的生产发布流程先创建备份并完成隔离恢复演练，再要求操作者输入 `DROP_LEGACY_MAP_DATA_20260812`；证明只通过当次进程环境传递，不写入生产环境文件。无项目数据的 fresh 库以及 dev/test/CI 不触发该确认。

## 结果

- S3 与 boto3 是新基础设施依赖，但 adapter 归 map-atlas 所有，不扩展成通用媒体模块。
- 项目删除的全局清理任务只保存 canonical 项目前缀与批次；精确补偿任务只保存
  canonical page object key 与批次。两者都不保存凭证、不出现在普通 task API。
- Context/RAG 继续走既有稳定 seam；地图册不创建新的公开 Context scope。
- 生成图片是作者可采用资产，不自动成为 World Bible 或世界事实。

## 未采用方案

- PostgreSQL BLOB：扩大备份、事务和数据库 I/O 成本。
- 本地磁盘：不能为多 worker 和部署提供稳定共享存储。
- 通用媒体模块、多 provider registry、edition/current、revision 表：v1 只有一个图片模型与一条派生链，不足以证明这些抽象需要存在。
- Responses API：Image API 已覆盖生成、整图编辑、蒙版、多参考图和连续派生，并能明确固定图片模型。
