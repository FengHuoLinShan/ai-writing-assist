# Module: map / AI 地图册子系统

## 定位

地图是 world 拥有的作者工作台子系统。它把已确认的 Context、RAG 与 World Bible 资料编译为
最多 20 页的层级计划，再固定调用 OpenAI `gpt-image-2` 生成候选图片。候选图不会自动成为
正式设定；作者逐页加入后才进入“我的地图册”。

- API 前缀：`/api/world/map-atlas`
- 目标用户：管理长篇设定的项目 owner；公开读者地图不在 v1 范围。
- 模型：文本规划沿用项目 LLM；图片固定为 `gpt-image-2`。
- 存储：map-atlas 自有 S3 adapter；浏览器只经 owner 与 `novel_id` 校验的图片接口读取。
- 取代：旧 `/api/world/maps*`、六边形/路径/领地/时间轴和 Map Observation/Fact 已删除，无兼容端点或数据迁移。

## 用户状态

- “本次生成结果”展示某次 run 的完整候选层级，允许采用、拒绝、修改或稍后处理。
- “我的地图册”只展示已采用图片及其导航祖先；同一地点可以有多张已采用图片，组成画廊。
- 加入只增加候选图，不替换旧图；拒绝后进入不可恢复的 `rejected` 历史；移出只作用于选中的旧图，并可从 `deprecated` 历史恢复。
- 每页分别保存资料直接支持、AI 视觉补全和资料冲突。AI 补全部分明确不是正式设定；有冲突的页面采用前必须再次确认。

## 数据模型

ORM 位于 `backend/modules/world/map_atlas_models.py`。

| 表 | 归属与约束 |
|---|---|
| `map_atlas_runs` | 一次计划/生成 run；保存授权选项、secret-free LLM/图片快照、context hash、source manifest、计划、进度与停止状态。 |
| `map_atlas_nodes` | 跨 run 复用的层级节点；新节点为 `provisional`，首张页面采用时原子采用其祖先链。 |
| `map_atlas_pages` | 必填 `novel_id/run_id/node_id`；每次生成或编辑都是独立页面，并用 `derived_from_page_id` 形成历史链。 |
| `map_atlas_annotations` | 前端文字标注的归一化坐标、来源打开目标、可选目标节点和乐观并发版本。 |

节点按 `cover → world → region → city → district → street → interior` 分层，默认最深到街道，
室内层必须由作者显式开启。`(novel_id, semantic_key)` 复用 canonical location 或父路径语义键。
正式树展示拥有已采用页面或已采用后代的节点；没有自身图片的祖先只作为目录。标注仅在目标
节点已有 adopted 页面时允许跳转。最后一张 adopted 页面被移出后，无 adopted 后代的节点从
正式树隐藏，但页面仍可恢复。

## Context、规划与来源

地图册不新增公开 Context scope。`world.map_atlas.generate` operation 固定使用
`reveal_mode=author_full`，由 generation-background 调用
`world.facade.get_world_background(context_mode="canonical", limit=160)`，并以 RAG
`purpose=map_atlas` 补充已确认/已发布资料。工作稿只在作者打开开关时通过既有 seam 加入；
候选对象始终排除。

文本模型输出经 `AtlasPlan` 校验：最多 20 页、无环、父级先于子级、来源均属于当前项目。
每页 prompt 以地点完整名称为语义锚点，但要求图中不出现文字、字母、数字或符号；名称由前端
标注层展示。run 保存 context snapshot、来源 hash 和 source manifest；“补全/更新”只处理缺失
节点或来源 hash 已变化的节点，完整重做是次级操作。

## 图片工作流与计费恢复

父级到子级串行生成；父图以及已采用的封面/世界图可作为风格参考。页面 checkpoint 为：

`prepared → provider_in_flight → uploaded → review_ready`

作者可请求“生成完当前页后停止”，完成的候选保留，恢复从下一页继续。如果 worker 在
`provider_in_flight` 失联，页面进入 `retry_requires_confirmation`；只有作者确认可能产生重复
费用后才再次请求。只有确认未返回图片的 429/5xx 可以有界自动重试。

设置模块只复用通用加密凭证表保存独立 `openai-image` 连接；它不参与文本 provider 列表或
`active_provider_id`。无费用连接检查只证明 Key 可达，图片权限、组织验证与额度在首次真实生成
时分别处理。图片统一为不透明 PNG。蒙版和源图必须同为 PNG、同尺寸、各小于 50MB，蒙版必须
含 alpha；蒙版是模型指导而非像素级边界保证。

## 私有对象存储与永久删除

每次尝试使用不可变 key
`map-atlas/{novel_id}/pages/{page_id}/attempts/{task_id}-{attempt}/image.png`，page 只记录胜出 attempt。
boto3 同步操作统一放在线程池。失败补偿只删精确对象，项目前缀仅用于永久删除。
finalization 在短事务中取得项目 share lock 与 task lease，持锁上传后再次校验 lease 再写页状态；
数据库提交失败就删除精确 key，补偿失败则排入全局清理。

项目永久删除取得排他锁、取消普通生成任务、创建 `owner_scope=global` 且 `novel_id=NULL` 的前缀
清理任务，再删除项目。清理任务只保存前缀和批次，不保存凭证，也不出现在普通 task API；它
幂等重试。排他锁会等待已开始的 finalization，且阻止旧 worker 开始新上传。

## API

| 方法 | 路径 | 行为 |
|---|---|---|
| POST | `/{novel_id}/runs` | 创建初次、更新或完整重做 run。 |
| GET | `/{novel_id}/runs/latest`、`/{novel_id}/runs/{run_id}` | 查询 run 与进度。 |
| POST | `/{novel_id}/runs/{run_id}/stop`、`/resume` | 停止或恢复；重复费用风险需显式确认。 |
| GET | `/{novel_id}/runs/{run_id}/results` | 查询本次生成结果。 |
| GET | `/{novel_id}/atlas` | 查询已采用地图册。 |
| GET | `/{novel_id}/pages/history` | 查询不可恢复的 `rejected` 历史与可恢复的 `deprecated` 历史。 |
| POST | `/{novel_id}/pages/{page_id}/{adopt|reject|archive|restore|retry}` | 独立页面状态操作。 |
| POST | `/{novel_id}/pages/{page_id}/{regenerate|edit}` | 生成派生候选；edit 支持蒙版和多参考页。 |
| PATCH | `/{novel_id}/annotations/{annotation_id}` | 乐观并发更新标注。 |
| GET | `/{novel_id}/pages/{page_id}/image` | 经 owner/项目门禁流式读取私有 PNG。 |

所有入口先验证当前 account principal、项目 owner 与 `novel_id`，参考页、目标节点和来源引用均
再次按项目过滤。API 不返回对象 key、凭证或长期预签名 URL。

## 验证

- 后端：`backend/modules/world/tests/test_map_atlas.py`、`backend/modules/settings/tests/test_image_connection.py`
- 删除竞态：`backend/tests/e2e/test_project_task_gate_concurrency.py`
- 前端：`frontend-console/tests/vue/map/MapAtlasView.test.js`
- 图片 adapter：自动测试使用固定 PNG、mock AsyncOpenAI 和 mock boto3；付费 live smoke 默认跳过。
- 收尾：生产代码中 `MapFact|MapObservation|map_observation|/world/maps` 必须零引用。

## 非目标

v1 不提供 edition/revision 表、通用媒体模块、多图片 provider、Responses API、PDF/ZIP 导出、
公开读者地图或自动回写世界事实。每次派生新页面已经提供所需历史，不再复制第二套版本系统。
