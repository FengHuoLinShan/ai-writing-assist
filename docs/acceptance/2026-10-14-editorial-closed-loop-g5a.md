# G5a 编辑闭环合成 harness 与 E2E 验收

2026-10-14，G5a（能力审计后续第二批计划 §3.6，泳道 A，零模型费用）在分支
`codex/g5a-editorial-closed-loop`（基于 `fd9e72790`）完成：浏览器 harness 增加编辑审读、
批注修订与改后复核的脚本化回复，并新增真实 API/worker/SQL + 合成 provider 的闭环 E2E。
未改任何默认开关，未触碰 `deploy/compose`，未调用真实模型。

## 交付内容

- `backend/tests/support/assistant_editorial_provider.py`：编辑闭环的确定性模型回复。
  按 structured-output schema title（`ReviewPass` / `RecheckOutput` /
  `WritingTargetedRevisionOutput` / `DirectorShardPlan`）路由，正文标记句
  （刻意放慢 / 失败）驱动慢速与失败路径；知识治理审计沿用既有
  `creative_browser_provider.structured_reply` 的 `AuditVerdictOutput`。失败注入必须用
  合法 JSON 但违反 schema 的输出：截断 JSON 会被客户端的截断恢复策略补全成 schema
  默认值（见缺口 G2），“零意见完成”不等于失败。
- `backend/tests/support/assistant_browser_app.py`：`_generate` 在通用合成回复之后接入
  `editorial_reply`，未命中时行为不变。
- `frontend-console/e2e/assistant-editorial.spec.js`（4 用例）：首次进入与空态（桌面 +
  390px）、保存正文→交给编辑→真实审读→意见处置→BR-4 桥接（真实
  `writing_comment_run` + 导演/补丁/治理审计）→改后复核（真实
  `assistant_editorial_recheck`，三值结论）→正文变化后的 stale 冲突；审读失败终态与
  继续入口；停止、刷新离开恢复与停止后继续到完成。验收口径取画像 A：不越权、不静默
  覆盖正文、切页刷新不丢进度、长任务可离开并知道下一步。
- `playwright.assistant.config.js` 的 harness 档位纳入新用例并在测试环境显式打开
  `ASSISTANT_EDITORIAL_ENABLED`（生产默认仍关）；`playwright.functional.config.js`
  的 testIgnore 同步排除，普通 functional 套件不加载。

## 验证范围

| 层级 | 结果 | 命令 |
|---|---|---|
| 闭环 E2E（新） | 4/4 通过 | `DATABASE_URL=<agent_e2e 库> BACKEND_PORT=18100 FRONTEND_PORT=18101 PW_REUSE_EXISTING_SERVER=0 npm --prefix frontend-console run test:e2e:assistant -- assistant-editorial.spec.js` |
| assistant 档位全量 | 5/5 通过（含既有 assistant.spec.js） | 同上（不带用例过滤） |
| assistant 模块测试 | 141 passed | `uv --directory backend run --locked --extra ci -- pytest modules/assistant/tests -q` |
| 合成回复单元冒烟 | 通过（schema 路由、失败/慢速标记、三值复核、补丁、导演、未知回落 None） | 进程内脚本驱动 `editorial_reply` |

环境：本机 PostgreSQL 17（localhost:5207）独占库 `agent_e2e_g5a_editorial`（库名含
`agent_e2e` 以满足 harness 启动门禁），独占端口 18100/18101，专用后端 harness
（`ASSISTANT_BROWSER_HARNESS=1`）+ 真实 worker；浏览器仍走真实 API 与 SQL，模型 IO 全部
合成。测试结论只覆盖控制平面（入口、状态机、恢复、冲突、门禁），不代表真实模型意见
质量（归 G7，用 `backend/evals/datasets/editorial/`）。

## 缺口清单（G5b 输入）

- **G1 桥接候选采用门禁与入口文案脱节。** 编辑台回执「替换候选已生成：去写作页审阅并
  采用」，但服务端 `validate_candidate_upstream` 对 `writing_comment_revision` 候选要求
  先通过独立审稿（`modules/writing/semantic_review.py:415-429`；实测直接采用返回 409
  「批注修订候选尚未通过独立审稿」），闭环中没有任何一步提示该前置。写作页候选面板的
  「采用到工作稿」按钮同样会先撞 409。建议：回执/意见卡说明「先在写作页完成独立审稿再
  采用」，或评估桥接候选是否豁免/内联独立审稿；本切片 E2E 只验证入口与真实
  `writing_comment_run` 回执，不闭环独立审稿后的采用。
- **G2 截断 JSON 恢复可把坏输出静默降级为「零意见完成」。**
  `infrastructure/llm/client.py` `_parse_structured_json` 的 `balanced_truncated_json`
  策略会把「{」补全为「{}」，schema 全默认值校验通过——审读以 completed 收尾、零意见、
  空 summary，报告无失败痕迹（实测复现）。模型侧一次彻底坏输出被当成一次完整但无发现
  的审读，作者无从区分「编辑觉得没问题」与「输出坏了」。建议：恢复策略产出的结果在
  报告/诊断中标注，或对 findings 类 schema 限制该恢复。harness 侧已用 schema-invalid
  JSON 规避。
- **G3 审读失败的用户可见文案是内部诊断。** 失败终态的 `error` 直接透出
  「All 1 structured output attempts failed: Schema validation failed …」一类英文技术
  文案（实测），违反画像 A「不暴露内部状态」。建议失败态给作者语言（「这次审读没有完成，
  已保存的分段仍保留，可点继续重试」），技术诊断收进次级入口。
- **G4 harness 环境的清理任务噪音。** 无 bucket 配置时
  `map_atlas_storage_cleanup` / `world_object_image_cleanup` 周期任务持续 requeue（每轮
  worker 轮询刷 WARNING，占用并发槽），assistant 档位日志被淹没。属既有现象，建议
  harness 启动时禁用这两类周期任务或预置合成 bucket。
- **G5 「部分采用」仍无统一定义**（§3.6 已记录，G5b 已裁定）：正文候选只能整体采用，
  “部分”仅存在于助手批次确认、编辑台多意见子集处置、骨架包条目取舍三处；本切片未新增
  语义，E2E 覆盖了多意见子集处置的既有形态。
- **G6 停止/恢复的小额重复审读。** 单章未完成分段被停止后续跑时，同一分段的读者层会
  再次调用（进度以分段为粒度回滚），预算内最多重复一次读者视角请求；不可见、不越权，
  仅记录为后续优化候选。

## 边界与未覆盖

- 候选采用的完整链路（独立审稿→采用→BR-4 采用后自动改后复核）未闭环，见 G1；采用后
  自动复核的代码路径（`draft_service.py` → `ASSISTANT_EDITORIAL_POST_ADOPTION_RECHECKS`）
  已有领域测试覆盖。
- 真实意见质量、联网、生产 compose 透传（G5c）不在本切片范围。
- 截图证据见 Playwright `test-results/assistant`（本地运行产物，不入库）。
