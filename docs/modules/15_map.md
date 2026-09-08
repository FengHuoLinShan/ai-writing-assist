# Module: map / 统一地图底座

## 定位

地图是 world 拥有的作者工作台子系统。一套地图节点同时承载空间示意、图片底图与地点配图。
区域、城市、街区和街道可在没有图片连接时创建、编辑、保存；文本模型只提取已知空间关系，程序负责布局。
图片仍使用既有候选、派生历史和私有存储。地图保存或图片采用都不回写世界正史。

- API 前缀：`/api/world/map-atlas`
- 目标用户：管理长篇设定的项目 owner；提供按章首进度的作者端阅读预览，尚无公开读者或 RP 地图入口。
- 模型：空间关系提取沿用项目文本 LLM；可选图片固定为 `gpt-image-2`。手动制图不需要模型连接。
- 存储：map-atlas 自有 S3 adapter；浏览器只经 owner 与 `novel_id` 校验的图片接口读取。
- 取代：旧 `/api/world/maps*`、六边形/路径/领地/时间轴和 Map Observation/Fact 已删除，无兼容端点或数据迁移。
- `world_adoption_package.v1` 不纳入地图册操作；地图候选和页面仍走本模块既有作者采用流，不作为
  Scene memory 或 package 的对象/关系原子写入项。
- 深度导入新增的 workflow-scoped 实体去重 facade 不进入地图册生成、采用或图片恢复状态机；地图仍只消费已确认资料。
- World 关系新增的七类 `relation_kind` 只是审核与检索分类；地图册继续消费原有精确 `relation_type` 和已确认资料，不改变规划、来源 hash、采用或图片状态机。
- 世界书的 `world_validation` 回执不取代地图册自有的候选审核、来源 hash 和图片采用门禁；
  地图册不读取或写入 `world_validation_runs`。
- ADR-0017 Phase 0 只把 World Bible PageRevision 选入 Canon；地图册尚未切换为
  CanonRevision 消费者，仍按下文的已确认 Context/RAG/World Bible 来源与 hash
  门禁运行，不从 `world_assertions` 或 Canon manifest 双读。
- RP 的版本化作者作品引用只服务 `interaction.story` consumer；地图册不读取
  `interaction_source_revisions`、RP 剧情截止点或 consumer snapshot，也不把私人旅程分支当作
  地图资料。

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
| `map_atlas_nodes` | 唯一层级目录、地点身份、当前空间版本与结构任务；可独立于图片任务创建。 |
| `map_atlas_revisions` | 不可变空间图元、约束、来源和图片展示配置；当前 head 使用同项目、同节点复合外键。 |
| `map_atlas_pages` | 必填 `novel_id/run_id/node_id`；每次生成或编辑都是独立页面，并用 `derived_from_page_id` 形成历史链。 |
| `map_atlas_annotations` | 前端文字标注的归一化坐标、来源打开目标、可选目标节点和乐观并发版本。 |

节点按 `cover → world → region → city → district → street → interior` 分层，默认最深到街道，
室内层必须由作者显式开启。`(novel_id, semantic_key)` 复用 canonical location 或父路径语义键。
正式树展示拥有已保存空间版本、已采用图片或有效后代的节点。子图跳转接受纯空间图；
移出最后一张图片不会隐藏仍有空间版本的节点。旧图片和原有世界／街区／室内层级继续保留，
结构编辑支持区域、城市、街区和街道；室内仍仅保留既有图片能力。
纯空间节点调整目录与顺序无需存在生图任务；未绑定世界地点的地图可修改标题，绑定地点仍禁止
从地图界面改名。已有空间版本的节点仅允许区域／城市／街区／街道层级，避免目录调整后无法继续编辑。
目录更新继续比较 `expected_updated_at`，排序目标必须属于同项目与同一上级；路径身份随真实
父子关系逐层更新，不通过字符串前缀匹配不相关节点。

## 空间版本、编辑与图片统一

`map_atlas_revisions` 的内容、来源和生成身份追加写入，PostgreSQL trigger 禁止原地修改；
只有审查状态可变。手动保存、采用候选和恢复历史都创建新版本。写入比较 `base_revision_id`，
冲突返回 409，前端保留当前编辑并提供服务器版比较。`created_by_run_id` 可空且使用 SET NULL，
删除来源任务不能级联删除地图节点。

图元限定地点／地标点、道路／河流折线和区域多边形；文档最多 200 图元、400 关系、2000 控制点，
拒绝非有限坐标、未知字段、跨项目对象／图片／标注和悬空引用。局部地图单位与图片像素分离，
界面标明“不按比例”，不从行程推算距离。布局使用固定顺序的方向分层与有界网格避让，包含关系
生成示意包络，明确路线按经过顺序绘制；交叉不自动建立路口。已有位置与手工控制点保持固定，
矛盾或无法布置的内容保留待核对状态。

空间生成任务为 `world_map_schematic_generate`，确认动作为 `world.map_atlas.structure`。
一次最多 20 个目标（已采用地点或已保存图元），每批 5 个，单批输出上限 4000 tokens；只消费原 confirmation 中实际
保留的 Context items，跳过工作稿、排除项及预算省略项，不独立补读全库。模型只输出受限关系、
明确路线／河流类别、已有名称和逐字引文，不输出坐标或代码。批次 checkpoint 只恢复未完成部分，
同一 operation receipt 不重复创建任务。结果进入节点的空间候选，任务完成不推进当前地图 head；
采用时重验原 confirmation 和地图基准。旧来源 hash 变化时，已有原样引用可以随人工编辑保留为
待核对项，但不能借此新增失效引用，相关内容不进入阅读预览或新的结构引导生图。
加载当前地图与最多十个候选时重新核对来源，失效或恢复只改变响应中的提示，不更新原版本与历史。
候选差异审阅覆盖图元、空间关系、图片展示及标注绑定，并可切换对照已保存地图；采用支持整版或选择变更键；服务端计算依赖闭包，剩余修改生成基于新版本的候选继续待确认。

图片通过 `MapImagePlacement` 进入同一个地图版本：底图位于空间图元下方，地点配图关联节点或
图元。底图使用三个不共线锚点计算仿射变换，校准只改变图片展示，不改变空间位置；对齐锚点不
证明全图精度。校准绑定空间指纹，空间变化后底图默认退出叠加并提示复核，不自动收费重画。
透明度、阅读展示条件等纯展示修改不改变空间指纹。

结构引导生图固定目标节点与已保存版本，用 Pillow 生成结构参考 PNG 后进入原图片工作流；
不再由文本模型决定已有地图层级，也不要求第二次文本规划连接。结构图占用八张参考图总限额中的
一张，隐式父图仅使用剩余名额。生成与编辑前重新物化原确认，图元／来源不得超出该确认；
新图片记录 `source_map_revision_id` 和 `source_geometry_hash`，晚到图片只能成为候选。

旧图片不自动转换为几何事实，旧标注不按名称自动绑定。绑定之后由空间图元提供地点身份与名称，
旧标注接口拒绝独立位置写入；未校准图片继续作为参考图。像素和图片派生链仍由 page 持有，
空间版本只引用图片，不复制字节或建立通用媒体系统。

## 阅读进度预览

预览仍要求当前 account owner 与项目门禁。`chapter=N` 表示进入第 N 章时，使用既有 Evidence
reader visibility 和 Story 揭示策略；世界书作者页没有读者投影时保守排除。地点展示条件不能
覆盖世界资料权限，路线／轮廓及布局关系通过依赖闭包排除未揭示端点与依据。

服务端返回专用图元与图片白名单，不返回作者摘要、候选、冲突原文或隐藏统计。图片默认仅作者
可见；整图展示确认绑定图片 hash 与最早章首，且仍需满足引用内容的可见性。图片预览读取接口
再次检查同一投影，不能仅在前端隐藏标签。无法确认时仅展示矢量示意，保持已展示地点的位置。

## Context、规划与来源

地图册不新增公开 Context scope。`world.map_atlas.generate` operation 固定使用
`reveal_mode=author_full`，由 generation-background 调用
`world.facade.get_world_background(context_mode="canonical", limit=160)`，并以 RAG
`purpose=map_atlas` 补充已确认/已发布资料。工作稿只在作者打开开关时通过既有 seam 加入；
候选对象始终排除。

作者别名列表/审核使用的轻量读取不是地图素材接口；地图继续通过上述 World/Evidence seam
获取已确认来源，不以列表计数或别名投影替代完整 Context、来源 hash 和 manifest。

空间补充至多核对 20 个已采用地点、每批 5 个；正式页面只使用 `free_text` 与
`projection_policy=eligible` 的 section，工作稿仅在明确开启后以 working 来源进入。每地点
Wiki 与 RAG 合计最多 8000 字，每批最多 40000 字；抽取前释放事务，来源与 hash 进入 run/page manifest。

文本模型输出经 `AtlasPlan` 校验：最多 20 页、无环、父级先于子级、每个 canonical 地点至多
对应一个计划节点，且来源均属于当前项目。图片步骤最多读取 8 张参考图；隐式父图只在仍有
余量时加入。
每页 prompt 以地点完整名称为语义锚点，但要求图中不出现文字、字母、数字、方向箭头、距离、
比例尺、图例或层级标签；前端标注层只展示地点或地标名称，不展示层级、方向、距离、比例或图例。
run 保存 context snapshot、来源 hash 和 source manifest；“补全/更新”只处理缺失
节点或来源 hash 已变化的节点，完整重做是次级操作。

## 图片工作流与计费恢复

- 生成可选在 Prompt 确认点暂停；作者可编辑/复制 Prompt，并逐页选择
  站内生图或站外生图。只有确认后且存在站内页时才解析图片连接。
- 作者可独立上传 PNG/JPEG 作为候选页；JPEG 校验尺寸与帧数、处理 EXIF
  方向、去元数据并转为不透明 PNG；PNG 输入会剥离 tEXt/zTXt/iTXt/eXIf 等
  文本类辅助 chunk 后再入库。输入与输出均必须小于 50MB。
- upload run 仅用于候选审核与历史，不覆盖最新 AI 生成任务。

地图册不叠加 ADR-0013 的通用 operation receipt：图片生成已有 run/page checkpoint、
胜出 attempt 和可能重复计费的专用确认状态，继续由本模块状态机拥有恢复与重试语义。

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
地图册与世界对象图片共用单机 MinIO 的连接和受限应用凭据，但使用各自私有 bucket；地图册 bucket
硬配额为 8GiB，不能读取或写入对象图片 bucket（ADR-0014）。
finalization 在短事务中取得项目 share lock 与 task lease，持锁上传后再次校验 lease 再写页状态；
数据库提交失败就删除精确 key，补偿失败则排入全局清理。

项目永久删除取得排他锁、取消普通生成任务、创建 `owner_scope=global` 且 `novel_id=NULL` 的前缀
清理任务，再删除项目。清理任务只保存前缀和批次，不保存凭证，也不出现在普通 task API；它
幂等重试。排他锁会等待已开始的 finalization，且阻止旧 worker 开始新上传。

## API

| 方法 | 路径 | 行为 |
|---|---|---|
| POST | `/{novel_id}/nodes` | 无需图片任务创建区域或城市地图。 |
| GET | `/{novel_id}/nodes/{node_id}/map` | 当前结构、候选、图片层状态和空间任务状态。 |
| GET/POST | `/{novel_id}/nodes/{node_id}/revisions` | 查询历史或按基准版本保存地图。 |
| POST | `/{novel_id}/nodes/{node_id}/layout` | 有界布局、来源校验和图片校准预览，不持久化。 |
| POST | `/{novel_id}/nodes/{node_id}/generate-structure` | 携带 operation ID、confirmation、基准版本与地点范围入队。 |
| POST | `/{novel_id}/nodes/{node_id}/revisions/{revision_id}/review` | 采用／拒绝候选或将历史恢复为新版本。 |
| GET | `/{novel_id}/nodes/{node_id}/reader-preview` | 按章首生成只读白名单。 |
| GET | `/{novel_id}/nodes/{node_id}/reader-preview/images/{page_id}` | 重验预览白名单后读取图片。 |
| POST | `/{novel_id}/runs` | 创建初次、更新或完整重做 run；作者请求必须携带 action 匹配的 Context confirmation。 |
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

地图册只在 run 启动时打开一次统一 Context 审查窗；后续 plan、Prompt 复核、图片生成、重试和
恢复复用 run 中的 confirmation/snapshot，不重复打断作者。worker 通过 generation-background
重新物化同一 `compiled_context_fingerprint`，并保留作者加入/排除、author-full 可见性与来源
hash；指纹变化时在图片模型调用前失败关闭。

## 验证

- 空间与集成：`backend/modules/world/tests/test_map_structure.py`、`test_map_structure_workflow.py`。
- PostgreSQL：`backend/tests/e2e/test_unified_map_concurrency.py`；浏览器：`frontend-console/e2e/map-structure.spec.js`。
- 后端：`backend/modules/world/tests/test_map_atlas.py`、`backend/tests/account_project_preferences/test_image_connection.py`
- 删除竞态：`backend/tests/e2e/test_project_task_gate_concurrency.py`
- 前端：`frontend-console/tests/vue/map/MapAtlasView.test.js`
- 图片 adapter：自动测试使用固定 PNG、mock AsyncOpenAI 和 mock boto3；付费 live smoke 默认跳过。
- 收尾：生产代码中 `MapFact|MapObservation|map_observation|/world/maps` 必须零引用。

## 非目标

v1 不提供图片 edition 或第二套图片 revision、通用媒体模块、多图片 provider、Responses API、PDF/ZIP 导出、
公开读者地图或自动回写世界事实。图片历史由派生 page 表达；空间与展示配置由地图版本表达。

## 持续创作增量

- `MapGenerateRequest` 的 `location_ids` 与 `feature_ids` 合计 1–20，已有图元必须来自请求的已保存基准。
  其来源先预填到 Context 确认，执行只用实际保留项；不要求手工标记先创建世界正史。
- 自动关系的 `generated_by_task_id` 是服务端来源标记；普通保存不能伪造，手工修改关系后清除标记。
  它不进入空间指纹。局部整理保留无关及手工内容；失败、未覆盖或被裁剪的资料不触发旧关系删除。
- `review` 可传 `change_keys`（feature/constraint/image/binding），服务端验证基准、确认与所选新来源，
  连同必要依赖组成完整版本。关联图形删除需显式选择，当前完全原样继承的无关旧来源仍可待核对；
  不能把旧失效引用复制到新项。响应返回实际/扩展键及可继续处理的 remaining_candidate_id。
- `GET /{novel_id}/nodes/{node_id}/revisions/{revision_id}/preview` 只读该版本结构、来源提示与图片层，
  不重新布局或改变 head。历史预览与地图编辑、故事历史状态是不同语义。
- `GET /{novel_id}/map-links` 按来源章节、精确实体或名称查询已保存地图图元；过滤按 AND，
  最多扫描 200 个当前节点，截断通过 truncated 明示，不返回正文和私有来源摘要。
- 新关系 `along_street / entrance_to / faces` 有严格端点类型校验。未定位点可据关系布置，原坐标
  和控制点保留；交叉不自动成为路口。朝向线与临时排演只是图面解释，不创建世界事实。
- 结构引导图片增加图元身份与归一化位置对应说明，最终图片仍不烘焙文字；派生图更换来源版本时
  重建结构说明与来源清单，不沿用旧版 prompt 中已排除的资料。
