# ADR-0008 — 大纲当前层 AI 创作与 PlotThread 信息推进聚合

- **状态**: Accepted
- **日期**: 2026-07-17
- **关联契约**: `POST /api/outline/generate`、`POST /api/outline/generate/apply`

## 背景

旧 P20 用一次调用同时生成剧情线、篇章纲、Scene、伏笔和揭示，混淆了总纲之后三个不同
设计尺度，也让作者离开正在工作的页面。伏笔与揭示又以两个顶层模块分别编辑，同一信息从
隐藏到兑现的因果关系只能靠作者自行拼合。Planned Scene 创作还可能与从正文抽取 Scene
混淆。

## 决策

### 1. AI 创作入口跟随当前大纲层级

剧情线页、篇章纲页和 Scene 工作台分别提供 PlotThread、OutlineArc 和 Planned Scene 的
AI 创作/修订入口。一次只生成当前层；当前 StoryOutline 是硬前提和上位依据，其他层只作为
上下文。P20 不进入生成中心，小说总纲 AI 仍留在小说总纲页。

三类入口共用 `outline_generate` task 和既有 generate/apply HTTP 地址，但 v2 request 显式
携带 target、mode、作者指令和所选当前层资产。preview 可编辑，apply 重建总纲、选择资产与
确认 context 的 fingerprint，在一个 savepoint 内原子写入。修订保留 ID、引用和原 source，
并把前值及本次来源追加到 AI revision history。

### 2. PlotThread 聚合作者侧信息推进

PlotThread 是作者侧“某条剧情线如何控制信息”的聚合根。剧情线 AI 输出统一的
`information_movements`：信息对象、表层理解、隐藏内容及按顺序排列的播种、强化、局部揭示、
完整揭示和兑现节点。调用方确定性投影为既有 `foreshadowing_plans` 与 `reveal_plans`，两类
投影共享 `information_movement_id` 并关联同一剧情线。

底层两张表、REST API、Context/Writing 读者揭示判断和深度导入消费能力继续保留。
`RevealPlan` 增加与伏笔一致的 `related_thread_ids`；关联可多选但必须同一 `novel_id`。旧计划
不自动猜测归属，空关联项在剧情线页的“未归入剧情线”区域由作者分配。线程进入历史不会
级联删除计划；失去最后一个 active 关联的计划重新成为未归类。

### 3. Planned Scene 与正文证据分离

P20 只创作可供后续写作的 Scene 细纲，不从正文提取。新 Planned Scene 不创建
`scene_chunks`、章节 ID 或精确 span，只记录 `planning_state=planned`、计划章节范围和父篇章纲。
真实正文映射建立后状态转为 `materialized`。修订已有正文 Scene 时，模型无权修改映射。
“从正文提取 Scene”继续复用 imports 深度导入 Scene 阶段。

### 4. 完整确认上下文与严格层级权限

P20 实际消费作者确认过的 context，不在确认后另建不同背景。确认使用无驱逐编译；P20 不做
应用层输入裁剪，provider 超限即失败。人物 Top-6 与非人物对象 Top-16 是相关资产范围而非
token 预算。模型只接收短引用和 fenced 不可信 user JSON，不输出数据库 ID、状态、来源、
复核位或持久化动作。

## 影响

- 大纲规范子导航收敛为小说总纲、篇章纲、剧情线、场景工作台；旧伏笔/揭示路由重定向到
  剧情线的信息推进区域。
- OutlineArc 只能复用已有 PlotThread；缺少必要线程时返回作者决策项。PlotThread 优先复用
  已有线程，避免近义副本。
- 深度导入 Phase 3 使用独立 Scene 证据结构化契约；没有 Scene 证据时返回空/复核，不回退
  P20 创作 Prompt。
- 已完成 v1 preview 保留旧 apply 兼容；未完成 v1 task fail closed。

## 拒绝方案

### A. 在生成中心增加“剧情线创作”子标签

拒绝。它把作者从当前结构页带离，也使当前选择、重叠范围和修订目标变得不直观。

### B. 保留一次生成整套结构

拒绝。不同尺度相互代写，难以表达 no-change、跨层缺失和精确修订权限。

### C. 合并伏笔与揭示底层表

拒绝。读者可见性、Context/Writing 和深度导入仍需要两类确定性投影；作者体验归并不要求
破坏底层职责。
