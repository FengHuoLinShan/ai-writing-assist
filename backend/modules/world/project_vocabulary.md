# 项目词表 M0

项目词表为每个 `novel_id` 保存稳定词条身份和只追加的修订快照。名称、别名、说明和
ADR-0035 计算特性都属于快照；地图以 `type_ref`（词条 UUID）和
`type_revision_id`（修订 UUID）固定引用。作者改名或调整特性会新增修订，不会改变历史引用。

## 种类与特性

统一种类为 `space`、`level`、`feature`、`relation`、`transport`、`traveler`、
`access_condition`、`dossier_facing`、`faction_form`、`territory_control`。
空间与地图计算使用同一组有界 trait：

- `geometry`: `point`, `line`, `area`, `none`
- `containment`: `can_contain`, `independent_space`
- `connection`: `traversable`, `directed`, `cross_space`, `distance_constrained`
- `orientation`: `compass`, `vertical`
- `other`: `movable`, `qualitative_distance`

未声明特性使用空列表。开放的名称与说明用于显示和模型上下文；未知特性不参与确定性计算。

## 来源与生命周期

作者创建的词条和作者采用的预设词条优先于模型输入。模型写入只能经
`persist_reviewed_model_vocabulary_proposal` 接受带 Scene 引文及正文 `source_hash` 的提案；至少两个
不同 Scene，且独立复核收据通过并同时绑定原生成运行、词条种类/名称/别名/说明/特性摘要与当前证据 hash，词条才会启用。否则状态为 `emerging`。
该服务验证收据与词义、原生成运行及引文/正文 hash 的绑定，不会读取 Scene 原文，也不能证明引文逐字或复核语义独立；
M1 调用方必须先从 fresh Scene 回读中验证引文和来源，再运行独立复核，之后才可调用此写入窄口。
收据为 `VocabularyReviewReceipt(reviewer_run_id, proposal_run_id, proposal_hash, evidence_hash, verdict)`；
`proposal_hash` 用 `vocabulary_proposal_hash(kind, fields)` 计算，`evidence_hash` 用
`vocabulary_evidence_hash(evidence)` 计算。`proposal_run_id` 必须等于词条原生成运行，
响应中同名字段提供该 ID；复核运行必须不同于原生成运行和当前提案运行。
续证只累积证据，不替换既有词义；复核必须绑定被启用的既有字段与累积后的完整证据集合。
M1 仍须在可信服务端校验真实运行身份与独立上下文，不能把不同 UUID 当作语义独立证明。
模型会按名称和别名的 NFKC、大小写折叠及标点/空白归一结果复用同种类身份。归档与合并词条
保留为墓碑；多次合并沿链解析到最终身份，历史固定引用仍指向原 ID/修订。同名模型提案只返回 `restore_suggested`，不会重建新 UUID。

证据变化经 `replace_model_vocabulary_evidence` 更新；旧 Scene 被撤销时，
`invalidate_model_vocabulary_evidence` 新增修订、移除对应引文并清除过期复核。作者已确认的词条
不会被模型写入或证据失效降级。作者修改操作均需当前修订 ID，冲突时返回 409。归档和合并请求还必须显式携带 `confirmed=true`；
CAS 修订 ID 不代替领域二次确认。名称和每个别名的归一键均不能为空；合并后超过 24 个别名时
整次合并拒绝，作者整理后重试，不截断或丢弃名称历史。

预设为版本化的 `xianxia`、`fantasy`、`urban`、`science_fiction`、`mystery`；应用操作复制条目，
按预设版本和条目键幂等。预设更新不改动已经复制的词条。

## API 与调用接线

新路由定义于 `project_vocabulary_api.router`，由 World API 聚合处接入：

- `GET /api/world/project-vocabulary/{novel_id}`：有界读取，返回精确 `total_count` 与
  `omitted_count`，默认包含归档墓碑。
- `POST /{novel_id}/terms`、`GET /{novel_id}/terms/{type_ref}`、
  `PATCH /{novel_id}/terms/{type_ref}`：作者 CRUD；PATCH 使用 `expected_revision_id`。
- `POST /{novel_id}/terms/{type_ref}/archive|restore`：归档墓碑与作者恢复。
- `POST /{novel_id}/merge`、`POST /{novel_id}/terms/{type_ref}/split`：作者合并、拆分，均逐词条 CAS。
- `POST /{novel_id}/presets`：复制一个或多个题材预设。

助手 runtime v4 注册词条新增、编辑/改名、合并、拆分、归档、恢复与题材预设复制操作。
操作限于全书项目范围，预览读取最多 500 项并绑定全量内容 hash 与修订清单；读取不完整或
应用前任何词条变化都会拒绝执行。归档和合并由作者确认批次授权，确认字段由服务端补入；
一次助手操作最多触及 20 个词条。新操作不进入已创建的 v1/v2/v3 运行。

HTTP 与服务写路径均经过 Project owner/活动状态门禁，所有读取和写入都同时按 `novel_id` 过滤。
World API 和 `facade.py` 的聚合注册由 M0 集成者完成。跨模块窄出口为：

```python
read_project_vocabulary(db, novel_id, *, kind=None, limit=100, include_archived=True)
resolve_vocabulary_type_revisions(db, novel_id, refs)
persist_reviewed_model_vocabulary_proposal(db, novel_id, proposal)
replace_model_vocabulary_evidence(db, novel_id, type_ref, expected_revision_id, evidence, independent_review)
invalidate_model_vocabulary_evidence(db, novel_id, invalid_scene_ids)
```

`resolve_vocabulary_type_revisions` 仅回传精确同项目 `(type_ref, type_revision_id)` 配对，traits 来自
固定修订快照，状态来自词条当前生命周期；缺失或跨项目引用 fail-closed。作者、数据库迁移与 API 聚合之外，
本模块不执行模型调用或正典写入。

## 存储集成

ORM 注册于 `modules.world.models`。`project_vocabulary_revisions` 由服务只插入；数据库级不可变
trigger、同项目外键和表结构 migration 由集成批次添加。实现本身不编辑历史修订，也不自动迁移已有地图。
