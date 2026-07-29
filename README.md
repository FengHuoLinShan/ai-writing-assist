# NovelCraft｜AI 长篇创作与私人故事引擎

> 让大模型参与长篇创作与私人故事，但不让状态、权限和历史失控。
>
> FastAPI 后端 · Vue 3 SFC 控制台 · PostgreSQL + pgvector · 异步任务队列

[![Backend CI](https://github.com/FengHuoLinShan/ai-writing-assist/actions/workflows/backend-ci.yml/badge.svg)](https://github.com/FengHuoLinShan/ai-writing-assist/actions/workflows/backend-ci.yml)
[![PostgreSQL E2E](https://github.com/FengHuoLinShan/ai-writing-assist/actions/workflows/backend-postgresql-e2e.yml/badge.svg)](https://github.com/FengHuoLinShan/ai-writing-assist/actions/workflows/backend-postgresql-e2e.yml)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?logo=fastapi&logoColor=white)
![Vue](https://img.shields.io/badge/Vue-3-4FC08D?logo=vuedotjs&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17%20%2B%20pgvector-4169E1?logo=postgresql&logoColor=white)

[线上入口](https://novel.zhh.se) · [30 秒了解项目](#30-秒了解项目) · [为谁而做](#为谁而做) · [系统架构](#系统架构) · [核心时序](#核心时序) · [五分钟项目导览](#五分钟项目导览) · [开发者快速开始](#开发者快速开始)

NovelCraft 是一个 AI 长篇小说创作 Alpha：作者路径把正文版本、Scene、世界事实、剧情结构、
检索证据和 AI 建议放进同一条可追踪工作流；RP 路径让用户用自然语言进入熟悉的幻想世界，
并用不可变分支、流式恢复和持续回顾保存私人互动故事。

> 线上入口需注册；模型调用需要在账户设置中连接自己的 API Key。入口可用性以
> `/api/health` 为准；RP 首版已包含在当前固定 release 中，后续仓库改动是否上线仍以 release
> 记录为准。项目不提供公共共享账号，也不包含真实稿件、密钥或个人联系方式。

---

## 30 秒了解项目

| 核心问题 | 回答 |
| --- | --- |
| 它解决什么问题？ | 长篇内容持续数十万字后，人物设定、时间线、伏笔、章节结构和对话历史很容易失控；普通 Chat 或简单 RAG 只能生成文本，难以管理长期状态、分支选择和写回副作用。 |
| 它怎么解决？ | 作者路径用版本化正文和 Scene 锚定世界事实与剧情结构，再由 RAG、Context 和受控 LLM 生成可审查候选；RP 路径用不可变消息树、显式选中分支、流式 checkpoint 和回顾维持私人故事连续性。 |
| 核心差异是什么？ | 两条路径都不把“模型刚刚输出的内容”当作无条件真相：作者路径区分候选与正式资产；RP 路径只让代码级选中历史进入后续上下文，未选分支不会悄悄影响故事。 |
| 当前做到哪一步？ | 当前仓库具备双入口、作者导入/写作/世界设定/大纲/检索主链，以及模型知识 RP 旅程、分支、流式恢复、自动回顾和看海循环；仍是工程验证系统。 |
| 个人职责是什么？ | 负责产品构思、用户流程、需求拆解、架构与安全约束、AI Coding 编排、代码 Diff Review、测试验收和持续迭代；大规模实现主要由 AI Coding 工具完成。 |

**项目角色：产品负责人 + AI 应用工程编排者｜能力方向：AI 产品与 AI 应用开发。** 这个项目重点证明的不是“调用过一个模型”，而是能否把不稳定的模型能力约束成可解释、可恢复、可验收的产品系统。

## 为谁而做

NovelCraft 以两类核心用户作为产品判断基线：

- **长期创作的专业或业余作家**：需要工具长期记住幻想设定、故事历史、事件、人物、物品和
  关系，并能用时间、地图、Scene、来源和版本直观回顾整理，再安心继续写作。
- **想进入优秀作品世界的 RP 用户**：技术与写作技巧不是前提；只需说明世界、身份和开场
  愿望，就能用自然语言行动、纠正、重新生成、切换分支或持续观看故事。

两类用户共享账号级模型连接和可追踪 AI 基础设施，但不共享一套高复杂度首屏：首页只有
`我是作家` 与 `我是 RP 用户` 两个大框。作者获得完整控制，RP 用户获得低门槛开场与纯故事
交互。今后的功能规划与 Review
都必须回答两个问题：**目标用户会喜欢并再次使用吗？前端是否自然、清楚、舒服？**

RP 第一版只使用用户开场、模型训练知识、代码级选中历史和有效回顾，不依赖作者项目的
World、Outline、RAG、writing 或 memory。原作文件导入、按第 N 章分叉、项目共享和公开发布
仍不在当前范围。用户是否真正喜欢并长期使用仍是待验证产品假设。

完整画像、双入口方向、内容权利边界和功能判断模板见
[`docs/product/user-personas.md`](docs/product/user-personas.md)。

## 产品界面

以下画面来自仓库内受版本控制的 warm 主题视觉回归基线，使用脱敏 Fixture 数据，不复制生产数据。
当前基线覆盖作者主链；RP 交互仍在补充独立视觉基线，因此不使用合成界面冒充真实产品截图。

<table>
  <tr>
    <td width="50%">
      <img src="frontend-console/e2e/visual-writing.spec.js-snapshots/writing-desk-warm-darwin.png" alt="写作工作台：版本化正文、章节导航与 AI 写作辅助">
      <br>
      <strong>写作工作台</strong>：正文、章节、Scene 与 AI 辅助共处一屏。
    </td>
    <td width="50%">
      <img src="frontend-console/e2e/visual-world.spec.js-snapshots/world-review-objects-warm-darwin.png" alt="世界对象待处理：AI 抽取结果等待作者审核">
      <br>
      <strong>世界对象待处理</strong>：AI 抽取先进入审核区，不直接污染正式设定。
    </td>
  </tr>
  <tr>
    <td width="50%">
      <img src="frontend-console/e2e/visual-project-rag.spec.js-snapshots/rag-search-warm-darwin.png" alt="小说检索：展示候选片段与来源证据">
      <br>
      <strong>小说检索</strong>：召回正文证据，而不是只返回一段不可解释的答案。
    </td>
    <td width="50%">
      <img src="frontend-console/e2e/visual-outline.spec.js-snapshots/outline-threads-warm-darwin.png" alt="大纲工作台：总纲、剧情线和章节结构">
      <br>
      <strong>大纲 / 剧情线</strong>：把创作意图组织成可执行的结构层。
    </td>
  </tr>
</table>

## 为什么不是 Chat + RAG

一次对话可以写出一段文字，但长篇创作需要管理四类额外问题：

- **长期状态**：人物关系、地点、物件和规则会跨越大量章节，且会随创作演化。
- **版本与证据**：正文修改后，旧的摘要、向量和 AI 结论可能已经失效，必须知道它们来自哪个版本、哪个字符区间。
- **可见性边界**：生成当前 Scene 时，不能让未来情节成为模型证据；“能检索到”不等于“现在可以看”。
- **写回副作用**：模型建议、工作稿、已发布正文和正式世界事实具有完全不同的权限与风险。

因此系统把职责拆开：

> **RAG 负责找；Context 负责选、裁、确认和追踪；领域模块决定能不能写，以及写成什么状态。**

这也是 NovelCraft 与“聊天框外接向量库”的本质区别：检索只是输入链路的一环，产品真正管理的是从证据到决策、再到受控写回的完整生命周期。

## 产品闭环

### 作者路径：证据驱动的创作资产闭环

```mermaid
flowchart TB
    A["导入作品或创建项目"] --> B["Writing：版本化正文"]
    B --> C["Scene 切分与语义补全"]
    C --> D["World：人物、地点、关系与世界事实"]
    C --> E["Outline：总纲、剧情线、篇章纲与 Scene"]
    D --> F["RAG：候选召回"]
    E --> G["Context：可见性、预算、确认与证据链"]
    F --> G
    G --> H["LLM：生成建议或临时预览"]
    H --> I{"作者是否采用？"}
    I -- "编辑后采用" --> J["工作稿、已发布正文或已采用资产"]
    I -- "忽略 / 待处理" --> K["保留证据与历史，不污染正式资产"]
    J --> B
```

闭环中的关键设计是：**AI 输出先成为候选，作者采用后才成为正式资产**。系统允许自动化，但自动化必须有持久化授权范围、可回滚标记和冲突处理；低置信或无法消歧的结果仍回到待处理区。

### RP 路径：只让选中的故事继续生长

```mermaid
flowchart LR
    A["自然语言说明世界、身份和开场"] --> B["创建私人旅程"]
    B --> C["模型知识 + 用户设定 + 选中历史 + 有效回顾"]
    C --> D["流式生成不可变故事节点"]
    D --> E{"这段故事是否继续？"}
    E -- "继续" --> F["选中当前节点并推进"]
    E -- "重新生成 / 编辑" --> G["创建同级分支"]
    E -- "切换分支" --> H["更新代码级选中路径"]
    F --> I["自动回顾选中历史"]
    G --> H
    H --> I
    I --> C
```

RP 路径不复用作者项目的 World、Outline、RAG、writing 或 memory。它把“故事版本控制”收敛为
不可变节点和显式选中分支：重新生成不会覆盖旧内容，未选中的兄弟节点不会进入未来 Prompt、
导出或回顾。

## 系统架构

```mermaid
flowchart TB
    User["作者 / RP 用户"] --> UI["Vue 3 SFC 双入口"]
    UI --> API["FastAPI API"]

    subgraph Identity["三层之外：身份边界"]
        Account["account<br/>注册、登录、当前 principal"]
    end

    API --> Account

    subgraph Creative["创作系统：所有业务读写显式过滤 novel_id"]
        subgraph Facts["事实层"]
            Project["project<br/>项目根、owner 门禁、novel_id"]
            World["world<br/>人物、地点、关系、时间线、地图子系统"]
            Memory["memory<br/>可追踪记忆与状态快照"]
        end

        subgraph Structure["结构层"]
            Outline["outline<br/>总纲、剧情线、篇章纲、Scene"]
        end

        subgraph Support["辅助层"]
            Imports["imports<br/>解析与深度导入"]
            RAG["rag<br/>分块、向量、召回"]
            Context["context<br/>选择、裁剪、确认、证据链"]
            Writing["writing<br/>正文版本与写作候选"]
            Settings["settings<br/>账户模型连接与作者偏好"]
        end
    end

    subgraph RP["独立 RP 领域"]
        Interaction["interaction<br/>不可变分支、流式故事、回顾与看海"]
    end

    Account -->|"owner 校验"| Project
    Account -->|"owner 校验"| Interaction
    Interaction -->|"隐藏 interaction 项目"| Project
    Project --> World
    Project --> Memory
    Project --> Outline

    Writing -->|"当前正文与 Scene 证据"| RAG
    World -->|"事实候选"| Context
    Memory -->|"历史状态"| Context
    Outline -->|"结构与可见性"| Context
    RAG -->|"召回候选"| Context
    Context -->|"冻结后的确认输入"| Writing
    Imports -->|"经稳定接口生成候选资产"| World
    Imports -->|"经稳定接口生成结构"| Outline
    Imports -->|"导入正文"| Writing
    Settings -->|"作者偏好 / 非 secret 工作流设置"| Project

    subgraph Platform["共享受控基础设施"]
        Tasks["PostgreSQL 异步任务<br/>lease、checkpoint、恢复"]
        LLM["LLM gateway<br/>账户连接、schema、预算、超时、日志"]
        DB[("PostgreSQL 17<br/>pgvector")]
    end

    API --> Tasks
    Imports --> Tasks
    RAG --> Tasks
    Writing --> Tasks
    Interaction --> Tasks
    Settings -->|"账户级已验证 provider / model / Key"| LLM
    Project -->|"project client / execution snapshot"| LLM
    API --> DB
    Tasks --> DB
```

图中的箭头表达**资料流与产品协作关系**，不代表生产代码可以任意跨模块导入。代码层的跨模块依赖必须经过 `contracts.py`、`facade.py` 或已注册 DI port。

| 模块 | 领域职责 |
| --- | --- |
| `account` | 邮箱 / 可选 Authing 微信身份、单浏览器会话、重新认证与延期删除；位于三层创作架构之外。 |
| `project` | 作者 / interaction 项目聚合根、非 secret 工作流设置和 `owner_id + novel_id` 双重边界。 |
| `imports` | 文件解析、确定性 Phase 0 和可恢复的深度导入工作流。 |
| `world` | 人物、地点、关系、时间线、事件与地图子系统等长期世界事实。 |
| `memory` | 带来源的记忆、状态快照与可追踪上下文资产。 |
| `outline` | 总纲、剧情线、篇章纲、Scene 和结构覆盖关系。 |
| `rag` | 正文分块、embedding、向量召回和候选证据。 |
| `context` | 上下文选择、可见性、token 预算、确认快照和证据链。 |
| `writing` | 当前正文、版本、发布状态、写作生成与候选内容。 |
| `settings` | 账户级模型连接、只读余额、全局作者偏好和非 secret 项目级继承。 |
| `interaction` | 私人 RP 旅程、不可变选中历史、流式正文恢复、回顾和看海循环。 |

可继续深挖：

- [可编辑 Draw.io 架构源文件](docs/architecture/module-architecture.drawio)
- [HTML 架构图预览](docs/architecture/module-architecture.html)
- [架构文档导航](docs/architecture/README.md)
- [整体设计](docs/00_整体设计.md)

## 核心时序

### 1. 深度导入：从原文到可审核资产

```mermaid
sequenceDiagram
    autonumber
    actor Author as 作者
    participant API as FastAPI
    participant Queue as PostgreSQL 任务队列
    participant Imports as DeepImportWorkflow
    participant LLM as 受控 LLM Gateway
    participant Guard as 本地证据校验
    participant Domain as Writing / World / Outline

    Author->>API: 上传文本并持久化授权深度导入
    API->>API: 校验 account owner + novel_id
    API->>Queue: 写入任务与 secret-free 执行快照
    Queue->>Imports: claim lease，恢复 checkpoint
    Imports->>Imports: Phase 0 确定性解析、章节与基础 Scene
    Imports->>LLM: Phase 1a 切分 Scene 并生成逐字边界 anchor
    LLM-->>Guard: 结构化候选 + 原文证据
    Guard->>Guard: 校验 hash、offset、quote 与覆盖率
    alt 证据有效且章节覆盖完整
        Imports->>LLM: Phase 1b 按完整 Scene 正文补全语义字段
        LLM-->>Guard: 不改变边界的 Scene enrichment
        opt 高质量 Scene
            Imports->>LLM: Phase 1c 审核相邻候选并综合高置信融合组
            LLM-->>Guard: 融合决定或待处理建议
        end
        Imports->>Domain: Scene commit
        Imports->>LLM: Phase 2a / 2b 提取世界对象、别名与关系
        Imports->>LLM: Phase 3 分析剧情结构
        Imports->>Domain: 经稳定 facade 写入世界资产与大纲结构
        Domain-->>Author: 汇总待处理资产与异常
    else 证据失效或低置信
        Guard-->>Author: 阻断、章节级 fallback 或进入待处理，不静默写入
    end
    Imports->>Queue: checkpoint / 完成 / 可重试失败
```

这条链路把“模型理解长文本”拆成确定性解析、分阶段语义补全和本地证据验证。模型不能自行选择工具或跨模块编排，工作流、预算、超时、schema 和写入权限都由业务代码控制。

### 2. 写作生成：防止晚到结果覆盖新正文

```mermaid
sequenceDiagram
    autonumber
    actor Author as 作者
    participant Context as Context
    participant RAG as RAG
    participant Writing as Writing
    participant Queue as PostgreSQL 任务队列
    participant LLM as 受控 LLM Gateway

    Author->>Context: 确认本次生成范围与可见上下文
    Context->>RAG: 按当前 Scene 召回证据候选
    RAG-->>Context: 正文片段、来源与版本
    Context->>Writing: 回读当前正文并校验 source hash
    Context-->>Author: 展示 token 预算、裁剪结果和证据链
    Author->>Queue: 确认生成，冻结 confirmation fingerprint
    Queue->>Writing: claim lease，重读项目 / 正文 / Context 快照
    Writing->>LLM: 在数据库事务外调用模型
    LLM-->>Writing: 结构化写作建议
    Writing->>Writing: 重验 owner、novel_id、lease、正文 hash 和确认指纹
    alt 所有输入仍 fresh
        Writing->>Writing: 保存 candidate，不覆盖已发布正文
        Writing-->>Author: 展示候选，等待编辑或采用
    else 正文或确认已变化
        Writing-->>Author: 标记 stale，丢弃晚到写回
    end
```

这里解决的是典型异步竞态：用户等待模型时仍可能继续编辑。如果只在任务开始前检查一次版本，晚到结果就会覆盖新正文；因此系统在 LLM 返回后再次验证来源哈希、任务 lease 和确认指纹，只允许 fresh 结果落为候选。

### 3. RP 生成：不可变分支、流式恢复与晚到隔离

```mermaid
sequenceDiagram
    autonumber
    actor User as RP 用户
    participant UI as Vue 交互页
    participant API as FastAPI
    participant Interaction as Interaction
    participant Queue as PostgreSQL 任务队列
    participant LLM as 账户连接的 LLM
    participant DB as PostgreSQL

    User->>UI: 创建旅程并描述世界、身份与开场
    UI->>API: 创建当前账号私有 journey
    API->>Interaction: 校验 owner，创建隐藏 interaction 项目
    User->>UI: 继续 / 编辑 / 重新生成 / 选择分支
    UI->>API: 提交动作和当前 selection epoch
    API->>Interaction: 拒绝未解决 attempt，写入不可变用户节点
    Interaction->>Queue: 入队 + secret-free 执行快照
    Queue->>Interaction: claim lease，编译选中路径与有效回顾
    Interaction->>LLM: 事务外流式生成
    loop 可调的字符 / 时间阈值
        LLM-->>Interaction: 增量正文
        Interaction->>DB: checkpoint 可见缓冲与 offset
        UI->>API: SSE 按 offset 恢复
        API-->>UI: 已持久化增量
    end
    Interaction->>Interaction: 重验 owner、project、lease、selection epoch、选中路径和 provider 快照
    alt 所有边界仍 fresh
        Interaction->>DB: 写入不可变模型节点并更新选中分支
        Interaction->>Queue: 仅基于选中路径刷新回顾
        Interaction-->>UI: 完成；兄弟分支仍保留但不进入上下文
    else 选择已变、任务取消或 provider 漂移
        Interaction->>DB: 保留 attempt / 部分结果，不推进选中历史
        Interaction-->>UI: 由用户决定保留部分结果、重试或放弃
    end
```

“看海”是前端有界续写循环，不是自治 Agent：每轮仍经过同一任务、并发、权限和选中路径门禁，
用户离开会显式取消。流式 checkpoint 的时间与字符阈值是可调整实现参数，不是延迟承诺。

## 技术亮点

| 能力 | 工程做法 | 可深入讨论 |
| --- | --- | --- |
| 账户级模型连接 | API Key 先经最小真实调用验证，再加密并原子激活；项目只保存非 secret 工作流偏好，可恢复任务用 secret-free 快照固定 provider/model，再读取同 provider 的当前轮换 Key。 | 为什么密钥不再属于项目？Key 轮换、provider 移除或配置漂移时如何 fail closed？ |
| 受控 LLM 工作流 | 业务代码确定步骤，统一解析账户级模型连接，并对输出做 schema、预算、超时和日志约束。 | 为什么不做自由 ReAct Agent？DeepSeek 默认与 Kimi 门禁如何区分“可配置”和“已验证”？ |
| 证据绑定 | AI 结论携带原文 quote、字符区间、source hash 和 workflow 来源；正文变化后可以识别陈旧资产。 | 如何防止模型引用不存在的原文？offset 和 hash 各解决什么问题？ |
| RAG / Context 分离 | RAG 只负责候选召回；Context 负责可见性、token 预算、优先级、确认快照和证据追踪。 | 如何避免未来 Scene 泄漏？为什么检索结果不能直接进 prompt？ |
| PostgreSQL 可恢复任务 | 任务使用 lease、checkpoint、幂等边界和 secret-free 执行快照，API 重启后仍可恢复。 | 为什么现阶段不用 Redis / Kafka？如何防止重复消费和晚到写回？ |
| 不可变 RP 分支 | 编辑、重生成和切换都创建或选择节点，不原地重写历史；selection epoch 和选中路径在提交前复验。 | 为什么不能只在 Prompt 里说“忽略旧分支”？晚到流如何避免重新选中已放弃的故事？ |
| 可恢复流式正文 | 服务端持久化可见缓冲和 offset，SSE 可从断点恢复；技术失败的部分结果不会自动成为故事历史。 | 为什么网络 / provider 错误不自动重放？如何在成本、重复兄弟节点和恢复体验之间取舍？ |
| 双重租户隔离 | 公开浏览器请求同时校验当前 account 对项目的 `owner_id`，所有业务读写仍显式过滤 `novel_id`。 | owner 边界为什么不能代替 `novel_id`？worker 如何避免绕过用户权限？ |
| 建议与正式资产分离 | 普通模型输出进入候选或预览；只有作者采用，或有持久化授权的可回滚流水线，才能写入允许的资产。 | 如何设计人工确认、撤销、冲突和低置信回退？ |
| Vue 渐进迁移 | 保留现有 hash route-host seam，业务页以 Vue 3 SFC island 接入统一 bridge。 | 为什么不一次性重写前端？如何在迁移期保持 API、state 和路由一致？ |

## 关键设计取舍

| 没有选择 | 当前选择 | 原因 |
| --- | --- | --- |
| 自由 ReAct Agent 自主选工具、跨模块写数据 | 确定性业务工作流 + 统一 LLM gateway | 创作数据需要可预测权限、成本、超时、日志和回滚边界。 |
| Redis / Kafka 作为第一版任务基础设施 | PostgreSQL 任务表 + lease + checkpoint | Alpha 阶段优先减少运维面；当前吞吐量下，一致性和可恢复性比总线扩展性更重要。 |
| 立即引入图数据库 / 全量 GraphRAG | PostgreSQL 关系模型 + pgvector + 明确的领域关系 | 现阶段查询模式可以由关系表和向量召回覆盖；先验证关系价值，再为真实瓶颈增加基础设施。 |
| 一次性重写旧前端 | Vue 3 SFC 渐进迁移，复用 route host 与 bridge | 降低大爆炸式迁移风险，让产品功能与架构改造可以并行演进。 |
| 让 AI 自动改正式设定和已发布正文 | 候选、待处理、采用和发布状态分离 | 模型不确定性不能被包装成数据库中的确定事实，作者必须保留最终控制权。 |
| 把 RP 强塞进作者 World / RAG / memory | 独立 interaction 领域 + 隐藏项目隔离根 | RP 用户需要低摩擦故事交互；复用作者资产会暴露后台复杂度，也会混淆原作事实、私人分支和授权边界。 |
| 把连续续写包装成自治 Agent | 前端有界“看海”循环 + 服务端逐轮确定性门禁 | 保留沉浸感，同时限制并发、成本、离开后的后台续写和跨分支污染。 |

这些选择不是“永远不用”，而是按当前产品阶段控制复杂度。只有当吞吐量、查询模式、多人协作或运营数据证明现有边界成为瓶颈时，才升级基础设施。

## 个人贡献与 AI Coding 边界

我在这个项目中承担的是“产品负责人 + AI 应用工程编排者”的复合角色：

- 从长篇创作的状态失控问题出发，定义用户流程、产品闭环与分阶段路线。
- 拆解模块职责，制定 `owner_id + novel_id` 隔离、候选 / 正式资产分离、证据绑定和受控 LLM 等硬约束。
- 将需求转译为可验收的设计、接口契约、任务和测试门禁。
- 使用 Codex、Claude Code + DeepSeek 等 AI Coding 工具完成大规模实现，并负责提示上下文、任务编排、代码 Diff Review、问题定位和返工决策。
- 对最终行为负责：运行测试、检查架构边界、验收前端路径、维护文档，并把线上结果与本地未提交状态分开。

需要明确的是：**我不会把 AI Coding 生成的大规模代码包装成逐行手写。** 这个项目展示的是另一种工程能力——能否定义正确的问题和约束，组织 AI 产出，在真实代码库中识别风险，并把结果收敛到可运行、可测试、可解释的系统。

它能证明：

- 可以把模糊产品问题拆成稳定的领域边界和工程任务。
- 理解 RAG、Context Engineering、异步工作流、LLM 治理与多租户安全的组合关系。
- 能够 Review AI 生成代码，而不是只接受“能跑”的表面结果。
- 能围绕证据、失败路径和验收标准持续迭代。

它不能单独证明：

- 已经获得商业化 PMF 或稳定留存。
- 所有代码均由本人逐行手写。
- 在大规模真实用户并发下已经完成容量验证。

## 工程证据

### 持续集成与质量门禁

| 门禁 | 当前验证内容 |
| --- | --- |
| Backend quality | 密钥与敏感信息卫生检查、Ruff、快速测试和覆盖率门禁。 |
| PostgreSQL critical | 从空库执行 migration，并验证关键 PostgreSQL 并发与任务契约。 |
| Frontend unit quality | 前端单元测试和生产构建。 |
| PostgreSQL full E2E | 独立工作流按夜间或手动触发，运行更完整的 PostgreSQL 端到端验证。 |
| RP 并发与恢复 | 定向测试覆盖单旅程活动 attempt、账号并发上限、selection epoch、流式 offset、取消和部分结果保留。 |
| 视觉回归 | Playwright 基线覆盖写作、世界设定、检索、大纲等作者页面；RP 独立视觉基线仍待补齐。 |

README 使用实时 CI Badge，而不是把某一天的静态测试数量当作长期质量结论。

### 发布、备份与恢复

- 生产发布只能接受 `origin/main` 可达的 **40 位固定 commit SHA**，由 `deploy/scripts/release.sh` 执行；服务器以 detached HEAD 运行，避免“分支名等于生产版本”的漂移。
- 发布状态记录于 `deploy/.state/current-commit`，本地未提交修改、未推送 commit 或主题分支都不能成为生产输入。
- 部署脚本、健康检查、备份和恢复流程均在仓库中留有可审查入口；密钥只通过环境配置注入，不进入 README 或版本库。

<details>
<summary><strong>展开部署拓扑</strong></summary>

```mermaid
flowchart LR
    Internet["互联网用户"] --> Tunnel["Cloudflare Tunnel"]
    Tunnel --> Proxy["OpenResty<br/>loopback 入口"]
    Proxy --> Frontend["Vue 静态前端"]
    Proxy --> API["FastAPI API"]
    API --> DB[("PostgreSQL 17<br/>pgvector")]
    Worker["异步 Worker"] --> DB
    API --> Embedding["本地 TEI<br/>Embedding"]
    Worker --> Embedding
    API --> Provider["获准的 LLM Provider"]
    Worker --> Provider
```

OpenResty 与应用服务位于受控网络边界内；数据库不直接暴露给公网。Cloudflare Tunnel 提供公开入口，API 和 worker 只向配置过的 embedding / LLM provider 发起必要出站请求。

</details>

## 五分钟项目导览

1. **第 0–1 分钟：建立双入口。** 打开首页，说明作者要管理长期创作资产，而 RP 用户只想自然进入故事；两类需求共享账号和 LLM 基础设施，但不共享复杂首屏。
2. **第 1–2 分钟：展示作者闭环。** 进入世界对象待处理和大纲工作台，演示 AI 结果如何保留证据、等待作者采用。
3. **第 2–3 分钟：展示 RAG 与 Context。** 用小说检索找到正文片段，说明“召回候选”与“本轮有权使用”为什么必须分开。
4. **第 3–4 分钟：选择一条生成链路。** 线上版本已包含 RP 首版；在账户设置连接 DeepSeek 后，可展示重新生成、分支选择与断流恢复，也可选择作者候选生成。
5. **第 4–5 分钟：回到工程。** 展示架构图、作者 / RP 时序和 CI，说明账户模型连接、晚到结果防护、用户授权与 AI Coding 验收边界。

建议按以下路径深入了解：

`产品边界` → `RAG 与 Context` → `LLM 输出治理` → `异步一致性` → `多租户隔离` → `部署与恢复`

## 当前边界与下一阶段

这是一个**Alpha / 工程验证系统**，不是成熟商业产品。线上部署可能落后于当前仓库；
当前边界包括：

- 尚未通过正式用户研究证明留存、付费意愿和真实创作效率提升。
- 不宣称实体抽取准确率、生成采纳率或 P95 延迟达到某个未经持续评测的数字。
- 当前架构以单作者项目和可控并发为主，多人实时协作与大规模容量验证不在现阶段完成范围内。
- 视觉基线与自动化测试能证明主要路径可回归，但不能替代真实作者的长期创作反馈。
- RP 第一版不导入原作、不按章节分叉、不依赖作者结构化资产，也不提供项目共享；模型对作品
  知识和人物质感的稳定性仍需真实旅程样本验证。
- RP 与账户模型连接已随 [PR #26](https://github.com/FengHuoLinShan/ai-writing-assist/pull/26)
  合入 `origin/main`，并以固定 release `4a0797c7…` 通过健康检查上线。现有账号仍需在账户设置
  连接自己的 DeepSeek Key；旧项目 Key 不迁移且不再生效。Kimi 与长上下文能力仍以显式真实
  门禁结果为准，不承诺 1M 上下文。

下一阶段优先级：

1. 建立脱敏的长篇小说评测集，分别量化 Scene 边界、实体 / 关系抽取、证据有效率和跨章一致性。
2. 记录“候选 → 编辑 → 采用 / 拒绝”的产品漏斗，用真实采纳行为校准模型和交互。
3. 为 RP 建立首段生成耗时、重复使用、继续 / 重生成 / 分支选择、断流恢复 / 放弃和人工纠正率，
   验证“低门槛私人故事”是否真的带来持续使用。
4. 增强任务耗时、LLM 成本、重试、stale 结果、provider 漂移和证据失效的可观测性。
5. 在真实负载证明需要后，再评估队列拆分、缓存、图查询或多人协作基础设施。

## 开发者快速开始

<details>
<summary><strong>展开本地运行与测试命令</strong></summary>

### 环境

- Python 3.12+
- Node.js + npm
- Docker / Docker Compose
- PostgreSQL 17 + pgvector（由 Compose 提供）

### 启动

```bash
cp backend/.env.example backend/.env
make db
make migrate
make dev
```

后端与前端会分别启动；实际端口和环境变量以 `.env.example`、`development-guide.md` 与终端输出为准。

### 自检与测试

```bash
make doctor
make test
```

需要验证真实 PostgreSQL 语义时，使用仓库的 PostgreSQL critical / E2E 入口；前端开发和视觉回归命令见 `frontend-console/README.md` 与 `testing-guide.md`。

</details>

## 权威文档索引

| 想了解什么 | 入口 |
| --- | --- |
| 项目术语与跨模块边界 | [CONTEXT.md](CONTEXT.md) |
| 整体产品与技术设计 | [docs/00_整体设计.md](docs/00_整体设计.md) |
| 目标用户与双入口边界 | [docs/product/user-personas.md](docs/product/user-personas.md) |
| 架构图与阅读约定 | [docs/architecture/README.md](docs/architecture/README.md) |
| 各模块稳定接口 | [backend/modules/](backend/modules/)（各模块 `README.md`、`contracts.py` 与 `facade.py`） |
| 私人 RP 旅程与分支语义 | [backend/modules/interaction/README.md](backend/modules/interaction/README.md) |
| Prompt 与运行时调用契约 | [docs/prompts/Prompt体系设计.md](docs/prompts/Prompt体系设计.md) |
| 开发、测试与发布 | [development-guide.md](development-guide.md) · [testing-guide.md](testing-guide.md) · [deploy/README.md](deploy/README.md) |
| ADR 与长期架构决策 | [docs/adr/](docs/adr/) |

---

如果只记住一句话：**NovelCraft 不是让 AI 无边界地续写，而是让作者拥有可审查的创作资产，
让 RP 用户拥有可选择的私人故事，并让两条路径都保持权限、版本和恢复边界。**
