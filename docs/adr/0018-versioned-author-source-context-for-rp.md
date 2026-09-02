# ADR-0018：RP 只读引用作者作品的不可变资料版本

- 状态：Accepted / Implemented
- 日期：2026-09-01
- 影响模块：interaction、project、imports、writing、evidence、world、story、frontend

## 背景

RP 原有路径只使用模型训练知识、当前选中旅程历史和回顾。它保持了作者项目与私人旅程的
写入隔离，却无法可靠复用用户已经导入、整理和校正的作品资料。直接让隐藏 interaction 项目
查询作者项目当前状态又会产生版本漂移、跨项目越权、未来章节泄漏和 RP 输出回写正史的风险。

作品可能仍在连载。“可开始 RP”不能等同于作品已有结尾，而应表示当前导入版本的全部现有
章节已经完成来源校验、深度导入、精确索引、Scene/offset 覆盖和关键指代消歧。

## 决策

1. `interaction_source_revisions` 保存同 owner 作者项目的不可变资料目录：精确 Writing
   draft/version/hash manifest、剧情锚点、证据化对象目录、关键歧义决议、workflow 和就绪状态。
   manifest hash 用于正文版本 CAS；整体 fingerprint 另覆盖锚点、对象目录和歧义决议，并在
   ready 后冻结。它不复制小说全文；Writing 仍是唯一正文事实源。
2. 允许唯一的跨项目业务读取：同一 owner、显式选择的 author source revision → 一个隐藏
   interaction consumer project。所有来源查询使用 source `novel_id`，所有 RP 写入使用
   consumer `novel_id`。浏览器不能提交 owner，也不能任意指定未授权 source project。
3. 就绪状态固定为 `organizing / needs_confirmation / ready / failed`。`ready` 只证明当前
   manifest 的全部章节已整理并可精确引用，不要求存在结尾。普通低置信字段被排除；只有会使
   人物/别名或核心关系端点无法唯一引用的歧义阻断。
4. 每条旅程冻结一个 source revision、一个章节内剧情锚点、玩家身份和引用策略。已开始旅程
   只能保持或推进剧情点；切换作品、回退或无法映射玩家/固定对象时必须新建旅程。新版资料
   就绪后只提示，不能自动升级旧旅程。
5. Evidence indexing 让 `chapter_text` chunk 按 draft/hash 并存，并在候选排序前按 manifest
   过滤；命中仍从 Writing 历史 draft 回读并重验 hash/offset。Evidence compilation 的
   `compile_interaction_story_context()` 使用独立 16K 参考预算、读者/人物知识边界、章节和
   offset 截止，并只保存 hash、引用、原因和预算摘要；不长期保存 rendered source context。
6. interaction attempt 同时冻结 selection epoch 与 source context epoch。来源归档、版本失效、
   固定项失效或任一 epoch 漂移时失败关闭，不能退回纯模型知识。
7. RP 输出、旅程回顾和原创玩家身份只写 interaction 项目，不写回作者正文、World、Story
   或正史。来源项目软删除后旅程仍可读但停止新生成；仍有旅程引用时永久删除被阻止。

## 结果

- 现有无文件、纯模型知识旅程保持兼容；source 字段和 API 均为 additive。
- 一部作者作品可被多个私人旅程复用，每个旅程仍拥有独立分支与回顾。
- 历史 chunk 暂随资料版本保留，项目永久删除时级联清理；在真实容量数据出现前不新增独立
  GC、队列、工作流引擎、顶级模块或 crossover 模型。
- 作品准确性改善必须通过不保存版权正文的 context on/off 盲评验证；自动门禁不能冒充用户
  试用，也不能在严重剧透回归存在时宣称“减少出戏”。
