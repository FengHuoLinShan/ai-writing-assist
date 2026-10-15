# C0 模板与互通的剩余实施

2026-10-16 root 按主计划 §4.2–4.4、§4.9 核对 primary `6ad6b94df` 后确认。
本文件是原三份计划中的实施交接，不新增产品范围，不替代当前源码或授权。
仍按 Luna/max 实施、Sol/high 独立审查并直接修复；root 独占三份 TASK。

- 自定义类型借用内置内核面向：当前 `WorldObjectDossierService._validate_facing` 只认
  `CORE_FACINGS[entity_type]`，`list_facets` 同样只给该类型内核与全项目词表面向。
  自定义类型虽能使用项目面向，尚不能显式借用人物、种族等内核。复用版本化
  `EntityProfileTemplate`，明确作者选择、来源类型和键，处理重复键与类型转换；不能仅放宽校验
  就让模型任意声明内核。角色视角、证据来源及确定性检查的注册字段边界保持。
- 五题材档案面向预设：`project_vocabulary_presets.py` 当前五包只覆盖空间种类，没有
  `dossier_facing`。按修仙、西幻、都市、科幻、悬疑覆盖受支持对象类型，复用同一项目词表、
  模板与 copy-on-apply 语义；预设版本、作者修改、重复应用和撤销依据可验证。
  当前CORE_FACINGS已有character/location/item/faction/species/rule/secret/event八类，
  包括既有faction的形态、理念等内核，题材档案预设应全部覆盖，不能因外部前置省略这一类。
  本批不补独立势力路线图的新治理/成员/领地模型，不用旧字段假装完成M5或推进势力接入。
- 表格与 JSON 互通：Imports 的 `spreadsheet_migration.ColumnTarget` 仍是旧固定字段，
  当前目录无 Dossier/facet 映射；World dossier HTTP 只有条目/历史/模板接口，尚无按模板导出。
  复用现有上传/映射预览/显式采用和来源修订，不另建导入基础设施；任意列不得直接成为
  确定性状态字段，未知/失效面向、跨项目 term、过期模板及冲突须明确停下。
  JSON 的具体模式先核对既有领域导入导出入口，保证导出可回读、身份/来源/可见性清楚。
  导出仅作者 HTTP；ADR-0038 禁止对 AI 开放向系统外公开发布或导出，不能将作者导出误作新 AI 工具。
- 可发现与可操作：沿用 WorldObjectDossierEditor、ProjectVocabularyPanel 与现有表格映射界面，
  保留草稿、409、键盘和窄屏。每个新增 AI 可用操作提供纯 SPEC、真实 HTTP/trace 与版本冻结；
  仅导出文件或接线清单不能算闭环。

当前 C0c 已由 Sol 完成并合入 primary `9b9c022a5`，前端 fixture 后固定 `bd31d959d`；
root 的5133后端、27专库PG、3173前端与lint/build/docs/repo-gates全部通过。
上述尾项尚未派发。共享 keys/bootstrap/目录冻结、worker及TaskRegistry现由 A3 Sol 独占；
后续从最新已审 primary 复用干净任务树，新建主题分支，最终由 Sol 顺序组合。
旧模板 format_version=1、Dossier/Assistant 的历史输入快照保持版本化，不因新增借用字段改写。
结构化 JSON 只走明确的作者档案 manifest 边界，不扩文稿或表格上传后缀白名单。
唯一后端环境为 primary/backend/.venv，Node24，无安装依赖、默认开发库、真实模型、R3或holdout访问。
PostgreSQL 只用 root 明确分配的新专库，不能借用其他代理的库。保持旧目录与 map.edit 哈希冻结。

root已核实原world-object-dossier-impl任务树干净，在不删除旧
codex/world-object-validity-impl/ee51f869a的前提下，切到新分支
codex/dossier-template-interchange-impl，起点978a14e2d（产品bd31加任务笔记）。
该树已准备，尚未派代理；不要误认为有Luna正在实现本尾项。
