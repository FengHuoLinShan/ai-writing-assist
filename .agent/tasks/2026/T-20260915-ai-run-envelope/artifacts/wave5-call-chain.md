# Wave 5 调用链复核（2026-09-16）

## 结论

主 Agent 重新从生产 `modules/` 的调用标记反查到 TaskRegistry/worker：当前 33 个生产文件含
受管入口或 `research`/stream/image 标记；`make prompt-contracts` 24 passed，未发现 AST 解析失败、
未知 capability 或未登记绑定。任务 registry 的 root/额度门禁已纳入本轮合并定向回归；新增的
`world_cocreation_turn` 已有 `world.generation.cocreation` parent，Interaction story 两个 task
也都有显式 root 与冻结额度。

## 边界核对

- 启用 envelope 的 task 均从 `TaskRunEnvelopeKeeper` 领取开始建立/恢复账本，provider 入口经
  `LLMClient`/managed step 计量；预算、deadline、root/step 身份拒绝发生在 provider I/O 前。
- `world_cocreation_turn` 的 chat/design 子步骤在活动 parent 下省略子 root，仅保留子步骤名与
  knowledge policy，避免 `world.generation.chat` 与 `world.generation.design_iteration` 造成
  同一 task 的 root 漂移；无信封同步调用仍保留原子语义。
- `interaction_story_generate` / `interaction_agent_story_generate` 的 task meta 与
  `InteractionGenerationAttempt.agent_checkpoint_json` 通过窄 mirror 同步；常驻 worker、requeue 与
  终态 lifecycle 复用同一 run。续段创建新 task 后，旧 task 终态只收口自己的
  队列行，不覆盖新 task 的 attempt 快照。
  旧 pending/awaiting-continue 缺信封时以 attempt id 建立稳定
  `legacy_untracked/usage_complete=false` run。mirror 以 `SKIP LOCKED` 避免与领域
  attempt→task 路径互等；本轮只做了 SQLite/语句锁序回归，PostgreSQL 仍待专用库验收。
  旧 awaiting-continue 的未知历史段不产生可用额度；新授权后最终 limit 为 46/29、revision=1，
  新版已跟踪段的正常续写仍为 92/58。
- 直接 provider 调用仍存在于已明确的 opt-out/非目标路径：Map atlas 的 focused plan/image、
  embedding/indexing 与健康/连接检查；这些路径没有声明 root，不会被误报为已迁移。未把它们写成
  “零旁路已完成”。
- `_ai_run_envelope` 仅保留在私有 meta/attempt checkpoint；公开 task meta/result 经过投影剥离，
  相关 worker/lifecycle/Interaction 回归通过。

## 本轮验收证据

- 真实 `TaskWorker` 回归分别覆盖 manual 与看海：旧 task 产生新 task 并正常终态，新 task
  恢复同一 attempt run；两条链同时验证幂等授权、累计额度/版本和旧终态不覆盖新快照。
- 合并定向 pytest：**378 passed, 2 deselected**；`make prompt-contracts`：**24 contracts passed**；
  changed-file `ruff check`：**All checks passed**。
- `make docs-check BASE_REF=origin/main` 与 `git diff --check`：通过。
- 主 Agent 独立运行 `make test-ci TEST_WORKERS=2`：test-deploy **270 passed**；backend
  **5746 passed, 13 skipped, 11 warnings**，coverage **86.02%**；frontend **191 files / 2491 tests**。
  secret hygiene、backend/frontend audit、lint、docs 均通过；backend audit 仅有已存档的
  `langchain-community` adverse status，无漏洞。
- PostgreSQL E2E 与真实 provider 未执行；不将 CI 绿色表述为它们已通过。
