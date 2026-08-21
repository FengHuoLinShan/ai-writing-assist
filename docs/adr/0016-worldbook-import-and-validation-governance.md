# ADR-0016 — 世界书目录导入与校验治理

- **状态**: Accepted
- **日期**: 2026-08-21
- **决策来源**: 用户确认实施完整世界书闭环计划，并选择仅导入文本资料、手动增量重导入
- **关联计划**: `docs/references/2026-08-21-worldbook-full-validation-plan.md`

## 背景

World Bible 已有页面、工作稿、修订、建议、采用包、发布影响和语义检查，但没有目录级世界书
导入、持久化校验运行、完整依赖失效或作者签收门禁。真名回响 Vault 与 llmwiki 又都使用
Markdown/YAML/JSON 目录，不能通过现有小说文稿导入白名单表达。

目录内容、Wiki schema、AGENTS.md、Ruby/Shell 脚本和模型生成的规则均是不可信输入。若直接
复用 imports 上传、执行外部校验脚本或让页面字段控制 Prompt，会扩大上传与代码执行面，并
破坏 ADR-0006 的“world 拥有资料、evidence 拥有激活”边界。

## 决策

### 1. world 拥有受限文本目录入口

- 新入口只接受 `.md`、`.txt`、`.json`、`.yaml`、`.yml`；单文件不超过 2 MiB、单次总量
  不超过 25 MiB、最多 2,000 个文件。
- 浏览器只提交文件内容、规范化相对路径和内容摘要；服务端拒绝绝对路径、`..`、NUL、无效
  UTF、重复路径和大小写冲突。首版使用原生目录文件选择并允许多文件回退，不接受 zip、PDF、
  图片或其他二进制，也不读取服务端本机路径。
- 该入口不复用、不放宽 imports 的小说文稿白名单。所有公开请求继续执行 account owner、
  active project 与 `novel_id` 门禁。
- 导入先形成可预览、可重验的 pending suggestion。源文件中的 `canon`、`status` 或工具声明
  不构成作者采用；apply 只创建/更新工作稿与只读来源资料，冲突绝不静默覆盖。

### 2. 外部内容永不成为可执行配置

- AGENTS.md、Prompt、Ruby、Shell、WorldCheck 配置及其他脚本只可作为来源资料或声明式政策
  候选，不执行命令、不加载插件、不调用 MCP、不 `eval/exec`。
- 产品校验器使用 Python 与现有依赖，仅实现固定 schema、允许列表操作符和确定性函数。
  Ruby `validate.rb` 与 WorldCheck 只在本地只读验收中作为 oracle，不进入 Docker、worker 或
  生产依赖。
- 错误、日志、task meta 与 receipt 不保存正文、API Key、本机路径或堆栈；仅保存有界摘要、
  hash、finding、覆盖和预算账本。

### 3. 状态、采用与激活分离

- `world_design_checkpoint.v1` 与导入 suggestion 保存机器状态和候选，不是正典正文；自动
  生成内容只能是 `draft/proposed/author-required`。
- schema、正典规则、设计原则、数值声明和依赖政策以版本化 `validation_policy` 世界书页面
  保存。只有作者显式采用并激活的政策才改变发布门禁；旧项目未激活政策时保持现有行为。
- `source_material` 页面默认禁止上下文激活。Evidence/compilation 继续独占运行时选择、预算、
  可见性、confirmation 与 trace；world 不新增第二套 Activation Profile。
- draft publish 与 adoption package apply 只消费当前 manifest/policy/dependency hash 匹配的
  validation receipt。普通 warning 可由作者保留证据后签收；`fail`、`author-required`、
  `insufficient-evidence` 和 stale 不可绕过。

### 4. 任务、预算与保留

- 校验使用现有 PostgreSQL task transport、keyed coalescing、operation receipt 与 project LLM
  snapshot seam；`world_validation_runs` 是领域状态，不从 `async_tasks` 反推 verdict。
- 默认每个 ReviewPacket 最多 32,000 输入字符、一次运行最多 24 个 packet；项目可显式提高
  总输入上限，但不得超过 8,000,000 字符或 256 个 packet。超过预算返回
  `insufficient-evidence`，不以部分结果伪装通过。真实费用仍由所选 provider/model 决定，
  前端在提交前展示页数、字符数与预计 packet 数。
- v1 不自动清理 `source_material` 或 validation run。来源缺失只标记状态，项目永久删除才
  级联删除；达到真实容量或合规压力后再用新 ADR 定义保留窗口。
- 政策严格按 `schema_version` 解析；未知版本可作为候选资料保存，但不能激活或产生有效
  receipt。

## 影响

- world 新增一张 `world_validation_runs` 表、受限目录 API、验证任务和 World Bible 内的
  “世界健康”入口；不新增顶级模块、队列、数据库或生产运行时。
- `CreationSuggestion`、World Bible draft/revision、adoption package、Conflict Queue、
  TargetRef 和 Attention/Today 投影继续作为唯一既有 seam。
- RP interaction 不读取世界书，不新增入口或复杂度。

## 拒绝方案

### A. 复用 imports 文稿上传

拒绝。两者文件类型、作者意图、正典语义、来源保留与恢复模型不同，并会放宽现有白名单。

### B. 上传 zip 或执行项目内校验脚本

拒绝。zip 增加解包炸弹、路径穿越和二进制混入面；执行脚本把不可信资料升级为代码执行。

### C. 将 validation policy 塞入项目 Prompt 或 Activation Profile

拒绝。校验政策、Prompt 与上下文激活属于不同权限和生命周期，混合后无法证明 receipt 的
输入、版本与作者授权。

### D. 把 validation run 只存在 async_tasks.result

拒绝。task 是 transport；verdict、签收、manifest/policy hash 和 stale 生命周期属于 world
领域，必须有可查询、可失效的领域记录。
