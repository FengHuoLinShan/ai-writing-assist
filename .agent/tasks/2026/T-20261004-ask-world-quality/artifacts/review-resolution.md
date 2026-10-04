# 固定基线 WIP 独立审查与整改

基线：229491796b9b05fb753c02b8aa2168cbb11c04e4。范围：当前主题 worktree 的全部已跟踪差异与
任务相关未跟踪文件；两个子代理只读审查，主 Agent 实现整改。没有模型、库或浏览器的子代理验收。

## Standards

初审发现三项：分层数据集省略 split 会提前消费 holdout；启动标记随 freeze 目录变化可绕过；
冻结未交叉绑定实际 debug Prompt/profile 与 debug、自测教师参数。

整改后复核结论：原三项问题均已消除；未发现新的硬规则问题或需单列的代码气味。
独立审查没有重跑测试，测试证据由主 Agent 另列。

## Spec

初审同样确认冻结绕过与参数绑定问题，并要求明确 holdout 教师不能内部重试。
追加复核发现：若标记只绑定整份数据集 hash，修改 debug 后可能重复消费同一 holdout。

最终复核：标记已按稳定排序的 holdout 实际问题/可见证据材料计算，debug 和参考标签变化
不改变身份；重复启动、复制 freeze 及仅改 debug 的回归均在 DB 前拦截。原问题和教师重试
整改已落地，未发现新增问题。

## 整改与验证

- 数据集有 holdout 时必须指定 split；holdout 要求冻结证据；缺失或失配在数据库/模型前拒绝。
- 固定 eval cache 存材料身份的独占标记，复制配置和改 debug 不重置消费状态；holdout 教师 attempts=1。
- debug 和自测实际 Prompt、profile、教师 model/effort/executor 逐项绑定，不用冻结顶层自述替代运行证据。
- 后端定向 156 passed，含 eval、真实形状 API 确认/隔离、知识治理、正文范围确认等；前端 28 passed。
- Ruff check/format（六个改动 Python 文件）、ESLint、secret hygiene、git diff --check 通过。
- 离线 Ask World 门禁通过；docs-check 通过。BASE_REF 检查依既有本地 no-change-reason 明示
  架构维护文档无需内容更新，不声称无豁免全通过。

当前残余：v3 完整34条debug生成、一次性holdout、真人校准与真实问答浏览器/作者验收。
累计费用账本/已授权剩余额度尚未收到；本轮没有增加 DeepSeek 调用。任务不能标完成。


## 真实入口新增修复复核

- 完整BGE环境复现 world.ask 预览/确认重复模型重排改变已展示来源，持续context_preview_changed 409。
  ask_world复用现有确定性query plan与RRF，不做可选模型扩写/重排；保留novel/visibility过滤、正文回读、排除与指纹重验。
- 同章两个引用片段被映射为相同writing_chapter来源身份，知识导演plan报duplicate disposition。
  world_scope_entries按既有source_key合并身份，保留不同hash修订与完整rendered_context/其哈希；不删引用正文。
- Standards轴：两次静态复核均无新增硬规则问题，安全/范围/审查覆盖门禁保持。
- Spec轴：两次静态复核均无新增缺陷/越范围，预览→确认→执行和AskWorld自身检索调用闭合。
- 回归：检索规划/健康、真实确认、world生成中心129 passed；知识治理/真实确认/生成中心/Guimi范围98 passed。
  两批有重叠，不能相加当作独立用例数。回归中正文确实漂移和owner/novel/排除失败关闭仍验证。

- 去重身份最后补齐page_id fallback：相同正文不同页仍独立；新增反例通过，两轴再复核无残余问题。
