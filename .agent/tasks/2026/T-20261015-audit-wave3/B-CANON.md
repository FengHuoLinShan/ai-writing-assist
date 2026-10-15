# G8c 大纲直接页面消费的正典修订提示

用户已明确同意首片从不读世界书页的 Story checkpoint 改到真正读页面的大纲生成。
本树从 R1 合入后的 main 开始，已快进到 #243 合入的 a5a5e5d61；唯一主任务笔记仍在 wave3-r1 同任务目录。

World background 在同一查询捕获实际页面 version_number 的 revision_id + revision_digest，避免消费后再查当前头。
仅入选并进入 `world_bible_pages` 的页面登记，Top-K 省略页不登记，旧数据没有修订不造基线。
生成任务保存基线到 context_provenance，采用预览时复制到总纲 provenance，手工编辑继承基底的页面基线，恢复历史继承原基线。

公开当前/历史/列表 API 显式启用只读批量比对，返回 canon_staleness；页面修订、取消采用或不存在算变化。
内部领域读取默认不做动态比对，保护可能对整个 revision.model_dump 计算的指纹。
提示不写回、不降级，不改变内容/执行 profile、发布快照或 Scene checkpoint。
DI `world.read_bible_page_revisions` 的 Protocol 位于 Story；World 页和 revision 均按 novel_id/page_id 过滤。
现有 API owner 门禁、append-only 与 CAS 没有放宽。依赖棘轮61/61、9/9、0/0、函数导入517/517，预算未增加。

覆盖边界：大纲直接页面输入；Evidence 确认编译里的额外页面、综合梗概、其他生成方、Story checkpoint、
Evolution 台账继续未覆盖。未移除 Scene API 的 world_canon_revision unsupported 标记，权威文档已列清。

验证：2051 项相关 Story/World/Evidence 回归通过；随后为避免动态提示流入内部指纹做了显示读取门禁，
Story 扩展回归534通过，新增3项 SQLite断言最初因时区序列化差异失败（created_at aware→naive），
改为比较实际持久化读取前后的完整响应，5项定向测试通过。该后续改动的真实PG基线3项通过。
75项前端Story单元、100项PG critical、7项定向PG（含P2C失效重算和并发journal）通过。
390px浏览器路径1项通过，实际查看截图，提示可读、不横向溢出、编辑可用；该UI测试只注入提示响应，
真实修订变化及不写回由PG测试证明。前端lint/build、后端lint、repo/secret/diff门禁通过。

文档：基础docs-check通过；diff impact checker使用显式--no-change-reason通过。已逐项核对未更新的
入口、词汇表、总体/数据库设计、ADR/架构索引与模块图、Memory/Map/基础设施：没有新增模块、ORM表、
路由、worker或主要资料流；仅在既有Story→World方向新增只读DI outlet。World/Story说明、ADR0031、
计划调整已同步。PR使用模板的逐项无影响说明，保留影响器要求而不为留痕改写无关文档。

环境失败保留：初次浏览器缺PW_REUSE_EXISTING_SERVER=0；第二次缺匹配的Chromium，安装后成功。
首次定向PG从root运行无法解析Alembic相对目录，随后未覆盖默认-m而仅deselected；最终在backend目录
显式-m运行7项全部成功。不能把这些预检失败当成产品失败或把未执行当通过。

提交后的补查发现手工编辑会丢失页面基线，已修正为继承 CAS 基底的页面基线；新内容的 execution profile 仍重新派生。49项大纲CRUD/生成/基线测试及真实PG3项（含手工编辑与历史恢复）通过。
