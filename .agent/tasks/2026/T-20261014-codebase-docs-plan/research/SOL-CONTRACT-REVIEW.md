# Sol 最终契约复核

日期：2026-10-14。独立 reviewer 宿主配置：`gpt-6.1-sol` / `high`（主代理按用户最新要求派发）；没有派生代理，没有使用业务 LLM/provider。使用 Ponytail full，只做范围内的只读契约复核。

集成树：`/Users/tywww/.codex/worktrees/docs-refresh-luna/ai-writing-assist`。已核实 HEAD 为固定 B `22bb499789cba89fea92e918fd853ab768688e07`；正式说明有未提交修改，新增阅读指南与图对尚未提交。先读该树 AGENTS、World 局部 AGENTS 与 Git diff。旧 L1/L2/L5、R1/R2 只作导航/历史；下述关键结论均重新读取 owning source。没有把旧 reviewer 的身份或结论当成本次 Sol 验收。

## 结论

本次定向复核发现 **1 项 P2 文档契约矛盾，现已修订并独立复核关闭**：Account 到 Project 的服务端瞬态运行时 profile 实际含 Key，原有相互关联说明却称其为 secret-free。主代理修订四处说明后，本 reviewer 重新核对修改和源码，确认已区分内部 profile 与公开/持久投影。

除该项外，本次指定关键点没有发现新的阻断性契约错误。**可以关闭本次限定范围的最终文档契约验收。** 这不是全库审计通过声明，不替代视觉复核、主代理最终文档门禁、模型/作者/生产验收。

## 发现、修订与复核

### SC-1 — P2：将含 Key 的内部运行时 contract 错写为 secret-free

- 文档位置：`docs/modules/17_account.md:58–60`、`docs/modules/01_project.md:24–26`、`backend/modules/account/README.md:73–75`。前两份在本轮变更列表内，第三份是相同事实的现有代码邻近说明。
- 错误结论：Account facade 只向 Project 暴露 secret-free runtime contract。
- 源码反证：`backend/modules/account/settings_schemas.py:100–114` 的 `AccountLLMRuntimeProfile` 和 `:141–150` 的 `AccountImageRuntimeProfile` 都有必需 `api_key: str`；`settings_service.py:185–205` 与 `:349–387` 按 owner 解密凭据并返回含 Key 的 profile；`facade.py:90–112` 直接返回这两个内部 contract；`backend/modules/project/llm_runtime.py:63–75` 接收 profile 并在服务端瞬态 settings 中物化 `llm`。
- 影响：读者会把“公开响应/持久 snapshot 无 secret”误解成“内部 facade 从不传递 Key”，进而误判凭据边界与需要保护的服务端对象；也与文档紧接着描述的当前 Key 读取路径互相矛盾。这里没有发现或宣称真实 Key 泄漏。
- 最小修订：三处统一说明“Project 仅经 Account facade 获取服务端瞬态运行时配置；Key 仅在服务端内存中传递。公开配置投影、项目 settings、持久任务 snapshot 与日志不得含 Key”。保留账户加密存储、owner 门禁、Project seam 与 effective composition 的现有职责。不要修改业务实现或把真实 API Key 写入任何工件。
- 复核条件：重新读取三处句子及上述 profile/facade/Project resolver，确认 secret-free 仅用于公开/持久投影，不误用于含 Key 的内部 profile。

**修订复核结果：已关闭。** 主代理修订 `docs/modules/17_account.md:58–62`、`docs/modules/01_project.md:24–27`、`backend/modules/account/README.md:73–77`，并主动修订同义的 `docs/00_整体设计.md:180`。本 reviewer 重新读取这四处当前文本及 diff，均明确内部服务端瞬态 profile 可携带解密 Key，公开响应、持久项目 settings/snapshot 与日志仍不得包含 Key；owner/current provider Key 和 Project seam 职责未放宽。

原树 `claims.csv` 的 `L1-PROJECT-TEXT-SNAPSHOT-RESTORE` conclusion 也已独立回读，正确区分瞬态 profile 与 secret-free snapshot；总数仍为 72。`build-ledgers.py` 保留原 L1 输入并在生成最终账本时应用独立 Sol 校正。原始 L1 研究是历史原始结论，不能继续作为该句现状的依据。对 CSV 的追加回读确认：evidence 保留原 `research/L1.md` 并追加本报告路径及 Sol/high 校正身份，validation_identity 同时保留原身份和独立校正说明；72 行 claim_id 唯一。追溯建议也已落实。

## 已独立核对的主要契约

| 项目 | 实际检查的文档与源码 | 结论和证明范围 |
|---|---|---|
| Project 文字 snapshot | `docs/modules/01_project.md:32–39,100–109`；`backend/modules/project/llm_runtime.py:45–90,94–145,188–285`；Account `settings_service.py:349–387` | snapshot 校验 version、novel_id、hash；恢复显式传原 provider_id，读取当前 owner 的该 provider 当前 Key，保留原模型与能力档案；base URL/extra hash 漂移失败关闭。active provider 切换不自动改派；不能从这些源码推断当前数据库已存在 Codex owner 连接。 |
| Project 图片 snapshot | `docs/modules/01_project.md`；`backend/modules/project/image_runtime.py:38–117` | 图片 snapshot 与文字分开，校验 owner/provider/固定模型/base URL 后读取当前图片 Key。图片 snapshot 含固定公开 base URL；文字段落“不保存完整 Base URL”没有被误扩展到图片。 |
| Local 当前与兼容边界 | `CONTEXT.md`、整体/数据库设计、本机模块两份 README/设计、阅读指南、ADR 索引与 `docs/adr/0029-local-cli-image-only.md`；`project/llm_runtime.py:208–213`、`local_agent/executor_service.py:69–79`、`runtime.py:66–145`、`api.py:445–497`、`companion.py:307` 起 | 正常新文字路径退役和旧 snapshot 拒绝，不等于所有旧 invocation 都不可领取。claim 没按 image mode 过滤；companion 仍分流到历史文字执行。文档保留 DB 未查、usage null 未知、cwd 非沙箱；ADR 正文未改变，索引只澄清实现边界。 |
| Writing 采用与 Story seam | `docs/modules/11_writing.md:203–209,246–255`、阅读指南；`writing/draft_service.py:533–574,579–604`、`service_support.py:390–414`、`generation_service.py:519–521`、`semantic_review.py:215–218` | 同一键且原采用结果仍存在时重放返回原结果；无键/异键拒绝；跨 novel 校验仍在。Scene execution bundle 来自 Story facade。没有宣称再次执行采用或绕过来源/知识门禁。 |
| Evidence GET 与 focused-search | `docs/modules/08_evidence.md:252–260,384–402`；`compilation/api.py:359–381,822–839`、`facade.py:928–940`、`services/confirmation_service.py:206–221,720` 起、`schemas.py:789–813`、`focused_tasks.py` 的 active-project gates | GET 只读持久确认并投影摘要，不重编译，也不返回 compile_options/provider/Key/checkpoint；novel_id 过滤、项目门禁与统一 404 在实际路径中。focused-search 三路由存在；没有把检索授权写成资产写入授权。 |
| RP hold、stop 与 partial | `docs/modules/18_interaction.md:52–69,178–183`；`interaction/generation.py:614–628,730–815,1296` 起、`services.py:1815–1917`、`runtime_policy.py:71–99` | 审查前 hold 不进 visible_text；PASS 后释放。stop 清理可恢复运行状态但保留私有 hold 审计；只有 visible_text 用于 partial，无可见正文则 cancelled。当前文字没有承诺 stop 后可恢复/发布 hold。 |
| Canon Phase 0 | `docs/modules/02_world.md:17–25`；`world/api/canon.py:52–61`、`services/worldbuilding/world_authority_service.py:302–328,372–394`、`authority.py:660–664` | preview 分支仅 PagePublish/Revert；admit 另有 AssertBatch 显式 422，FamilyCutover 也拒绝；五 formal family disabled。没有将“通用路由存在”误写成 Assertion 准入可用。 |
| Evolution 次序、复用与变化反例 | `docs/modules/22_evolution.md:284–331,499–505`、阅读指南与运行图；`evolution/world.py:965–1107`、`pipeline.py` provider 耐久化/unknown billing/recovery 段；`tests/test_world.py:1564–1694`、`tests/test_p4_completion.py:862–1020` | World 抽取先于 relation preparation，关系调用取决于 identity_candidates，之后规划审查组。8 调用只是一项合成测试源码断言：当前 EntityRelation 行变了、冻结关系前缀未变。World group 用例改第一组精确输入，断言仅一次 dispatch，不能当作关系历史内容变化的反例。测试本轮未运行。 |
| CLI eval 与 DI | `testing-guide.md:618` 起、`development-guide.md:262–268,320` 起；`evals/codex_executor.py:29–35,110–117`、`cli.py:1840–1842`、`ask_world.py:874–884`、`project_executor.py`/对应测试的符号与接线搜索；`app/main.py:19,53`、`app/bootstrap.py:567` 起、`run_worker.py:61–64`、`core/container.py` | 旧 eval 新调用校准门拒绝；Ask World 在 holdout 运行标记写入前拒绝。Project executor 的存在/单元覆盖不代表 CLI 已接线。API 与 worker 使用同一 bootstrap；ServiceKey 在容器内归一为 name 字符串。 |
| 用户指南 Key、导入与撤销 | `docs/product/new-user-guide.md` 变更、`word-guide-source.md:5`；`account/settings_service.py:67–90,120–167,255–290`、`settings_schemas.py:138`、`imports/adoption_policy.py:15–57`、`spreadsheet_migration/service.py:1041–1097`、World/Story author_migration 的冲突与回滚路径 | 新文字 Key 最小生成验证，图片 credential_only；已验证 fingerprint 可复用。授权深度导入允许无需复核 Scene/工作态结构落地，世界设定仍候选；表格撤销会保留后改/被引用对象并报告原因。历史 Word 源稿明确不代表当前指南，未冒充新 DOCX。 |
| 保存与离开 | 新用户指南 FAQ；`frontend-console/vue/views/writing/useWritingWorkspace.js:534–547,1622–1642`、`controllers/editorController.js:580–615`、`interaction/interactionSession.js:38–75` | 章节切换前 autosave，仍 dirty 且 saveError 则不切换；本机备份失败有风险反馈，离开/刷新有 guard。文档使用“尝试”和“最近未保存可能丢失”，未承诺绝对不丢。这里只核源码，没有浏览器交互实测。 |

## 覆盖数字与新增视觉改动

- 对原任务 CSV 做只读解析计数：claims 72、baseline document inventory 679、source coverage 1,381；source read_grade 为 targeted_sections 152 / inventory_only 1,229；claim decisions 为 retained 43 / updated 26 / coverage gap 2 / runtime unknown 1。与 ledger-summary 一致。原任务 RESULT 和新计划明确这些不是全库逐行审计、测试数或文学验收数；没有将本 reviewer 额外阅读追加入 L1–L7 的 152。
- 已静态检查 module HTML diff：新增项只涉及窄屏 toolbar 换行、44px toggle、aria-controls/expanded、focus-visible、可聚焦滚动 region 与 reduced-motion。图内本机标签修正与对应 Draw.io 含义一致。XML 几何 diff 是 id 3/6/22 三框增高，以及 id 24 下移；未涉及业务代码。
- 已读取 runtime HTML 的四条流程、限制文本，并对照阅读指南与核心调用链。它们只作流程图，不宣称默认开启/真实质量通过。
- 本次不调用浏览器、不确认像素/键盘实测，不把旧 R2 的截图结论作为自己的独立视觉验收；最终视觉复核与主代理门禁另行负责。Draw.io 原生渲染、Copy/PNG/PDF 导出也未验证。

## 未执行与剩余工作

未访问真实/测试数据库、账户连接、Secrets、稿件或原始模型日志；未调用模型、运行业务测试或评测，未提交、推送、合并或部署。未运行最终 docs-check / diff-check，按派发范围由主代理执行。没有改变正式文档、源码、测试、ADR 或任务账本，仅新增本报告。

下一步：主代理完成最终文档门禁、固定最终文件指纹并交付；可以将本报告记录为契约复核已关闭，保留上述未知和未执行边界。SC-1 与账本校正追溯均已完成定向复核，无剩余契约阻断。
