# Module: imports / 小说导入模块（原设计以外新增）

## 定位

imports 模块负责将本地小说文件解析并导入系统，创建 WritingDraft 记录以供后续实体抽取和创作使用。它也负责深度导入的工作流编排，但各阶段的具体业务写入仍通过对应模块的公开接口完成。

## 数据表

- `import_records` — file_name / file_type / file_size / total_chapters / imported_chapters / status / error_message

## 文件解析器（parsers.py）

| 格式 | 库 | 说明 |
|------|----|------|
| .txt | 内置 + chardet | 编码检测 + 章节正则分割 |
| .epub | ebooklib | 逐章提取 |
| .html/.htm | beautifulsoup4 | 提取文本 |
| .mobi/.azw3 | 内置 | 原始解析 |

## 服务

- ImportService.upload_and_import()：文件校验 → 解析 → 创建 WritingDraft → 更新 ImportRecord
- DeepImportWorkflow：三阶段深度导入流水线，运行在 `async_tasks` 的 `deep_import` 任务中

## 深度导入流水线（三阶段）

DeepImportWorkflow 将三步串成全自动流水线，直接入库无需用户中途确认：

### Phase 1: Scene 切分（并行，40%）
- 按 5 章/批 + 1 章 Overlap 拆分为 N 个子任务
- 每个子任务调用 LLM（scene_segmentation.md prompt）
- 输出写入 `scenes` 表
- Overlap 机制：第 i 批末尾 1 章与第 i+1 批首章重复
- 失败降级：逐章切分 → 机械分章

### Phase 2: 实体增量提取（串行，40%）
- 按 scene_index 顺序串行处理每个 Scene
- 加载当前 Memory 上下文 → LLM 抽取 → 3 层去重检测 → 自动入库
- 实体写入 `core_entities`，当前 `status="candidate"`，并带 `content_json._meta.auto_ingested=true`、来源 Scene/章节和批次元数据
- Delta 变更写入 delta_log（Scene 内坍缩后）
- 每个 Scene 完成时触发 Memory 增量快照

### Phase 3: 结构分析（单次，20%）
- 输入：全量 Scene 摘要 + 坍缩后 Delta 变更流 + 实体索引
- LLM 输出：plot_threads / outline_arcs / foreshadowing_plans / reveal_plans
- 四类产物分别写入对应表

### 进度状态

由 `DeepImportProgress` Schema 定义，并写入 `async_tasks.result`；`async_tasks.progress` 使用 0.0 / 0.4 / 0.8 / 1.0 表示阶段推进：
- current_step: scene_segmentation / entity_extraction / structure_analysis
- completed_steps: 已完成阶段
- message: 当前可展示给用户的中文状态
- phase1_total_batches / phase1_completed_batches
- phase2_total_scenes / phase2_completed_scenes
- degraded / degraded_batches 标记降级

重复导入时，`POST /api/imports/deep` 先返回：
- `status="requires_confirmation"`
- `requires_confirmation=true`
- `warning`

前端确认覆盖后重新提交 `force=true`，此时才创建 `deep_import` 任务。默认将旧数据标记为 deprecated；demo 阶段如重构导入派生表或重跑全量导入，也可以直接清空该小说的导入派生数据后重建。两种方式都必须保留用户确认和 novel_id 范围限制。

## 安全约束

- 文件类型白名单：`.txt .epub .html .htm .mobi .azw3`
- 大小上限：50MB
- 文件名必须 `os.path.basename` 处理，防止路径穿越

## API

```
POST /api/imports/upload                    # 上传并导入（multipart/form-data）
GET  /api/imports                           # 导入记录列表
GET  /api/imports/{id}                     # 导入记录详情
POST /api/imports/deep                     # 提交深度导入任务；重复导入需 force=true
POST /api/imports/deep/sync                # 同步执行深度导入（E2E/无 worker 场景）
POST /api/imports/deep/resume              # 兼容旧候选确认流程，当前已废弃
```

## 跨模块依赖

- 写入 writing_drafts 通过 `writing.facade.create_draft()`
- `writing.facade.create_draft()` 会同时提交 `rag_index_chapter` 任务
- Phase 1 通过 scene_segmentation 任务写入 `scenes` 表
- Phase 2 通过 world facade / 注册服务写入 `core_entities` / 关系数据，通过 memory 模块记录 `delta_log`
- Phase 3 通过 outline 注册服务写入 `plot_threads` / `outline_arcs` / `foreshadowing_plans` / `reveal_plans`
- 新增跨模块依赖应优先走 facade 或 DI container 注册服务；不得直接 import 其他模块 repositories/services
