# 世界书完整校验验收记录

> 日期：2026-08-21  
> 范围：`codex/worldbook-full-validation`  
> 隐私：只记录计数、verdict 和 SHA-256；不保存 Vault 正文、路径、Prompt 或模型密钥。

## 1. 验收结论

- 结构 oracle：通过。
- Worldcheck 全库 checkpoint：通过。
- 产品 `world-state 0.1.0` 与 Worldbuilding Engine Ruby oracle：通过。
- seed 诚实性：通过。未有证据的六循环/22 切面/5 链/12 测不伪造 covered/pass。
- 预植缺陷：通过。缺区、多余区、taxonomy 重复/错名、无证据 covered/成熟度、无理由 not-applicable 均在信任边界失败。
- 本记录不声称文学质量 PASS；机器校验只证明结构、来源、依赖和已登记证据。

## 2. 私有冻结快照基线

`validate.rb --all --strict` 实测：

| 指标 | 结果 |
|---|---:|
| pages / text / schema | 296 / 296 / 296 |
| links | 12,253（frontmatter 5,959 + body 6,294） |
| decisions | 60 |
| canon rules | 203 |
| design principles | 12 |
| change records | 85 |
| physics checks | 35 |
| graph nodes / edges | 157 / 568 |
| errors / warnings | 0 / 0 |

Worldcheck `check --full` 结果：

- `ok=true`，`full_gate.status=passed`，`pages=296`；
- checkpoint manifest SHA-256：
  `5b032e755d249be7ded6fc4305ac89fa87b097b58e14214d8edadb77b5f37e32`。

## 3. 产品状态与引擎 oracle

从生成中心的三规则 seed 确定性构造 `world_design_checkpoint.v1`，只取其
`world_state`：

- 输入 SHA-256：`af265958fb32f675e3e39c3e49f23d4d52a2bf7471b77f43c7c29263004f92f9`；
- `worldbuild.rb validate --json`：`valid=true`，0 error，0 warning，3 rules，22 facets，12 pressure tests；
- `worldbuild.rb audit --json`：foundation=true，social_realism=false，situated_reality=false，
  counterfactual=false；6 循环和 22 切面保持 gap，5 链保持 gap，12 压测保持 not-run；
- route 仍归 world owner，证明 seed checkpoint 没有被误写为完整可交付世界。

## 4. 产品门禁证据

- Pydantic 严格校验 21 个 required key（schema/engine 版本 + 19 内容区），禁止 extra。
- F01–F22、C01–C05、T01–T12 同时校验 ID 和权威名称一一对应。
- `covered/partial`、非零成熟度、已运行压测和 canon 主张均需证据；
  `not-applicable` 需理由。
- 校验任务冻结 policy/manifest/dependency/target hash，预算或 coverage 不足不部分通过。
- full 单飞由 PostgreSQL/SQLite 部分唯一索引保底；targeted 不受错误串行。
- 作者启用项目策略后，draft publish 和 adoption apply 在任何正典写入前验证回执。
- warning 签收保存 owner、时间、理由、完整 finding IDs 和 receipt hash；
  stale/fail/author-required/insufficient-evidence 不可签收绕过。

## 5. 仓库回归

- 后端完整套件：4661 passed，12 skipped，6 deselected。
- 前端完整套件：143 files / 1851 tests passed；生产构建通过。
- PostgreSQL E2E：27 passed，包含空库迁移、full 单飞、targeted 并行与项目删除级联。
- Ruff、19 个 Prompt contracts、`git diff --check` 与
  `make docs-check BASE_REF=origin/main` 均通过。
- PostgreSQL 验收使用独立临时库 `world_validation_e2e`；完成后容器已删除，
  未读写开发库。

## 6. 运行时边界

- 生产代码不依赖 Ruby、MCP 或自治 Agent；Ruby 只是本地验收 oracle。
- 语义审计仅在激活策略明确开启时，使用项目 secret-free LLM snapshot 和有界 ReviewPacket。
- 本次没有用私有正文做仓库 fixture，也没有把 Vault 内容写入日志或数据库。
- 产品目标画像为长篇作者（画像 A）；“更愿意重复使用”仍是产品假设，
  不冒充真实用户验证。RP/阅读型用户（画像 B）没有新增入口或义务。
