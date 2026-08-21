# 世界书完整校验验收记录

> 日期：2026-08-21
> 范围：`codex/worldbook-full-validation`
> 隐私：只记录计数、verdict 和 SHA-256；不保存 Vault 正文、路径、Prompt 或模型密钥。

## 1. 验收结论

- 结构差分 oracle：通过，并记录一项可解释扩展差异。同一冻结快照上，
  Ruby 与产品原生层的共享检查均为 296 页、0 errors、0 warnings；产品额外的
  标题锚点解析发现 3 条过期锚点。`validate.rb` 只校验 WikiLink 页目标，不校验
  heading anchor，因此这 3 条是产品扩展 finding，不伪造成 Ruby 失败。
- Worldcheck 全库 checkpoint：通过。
- 产品 `world-state 0.1.0` 与 Worldbuilding Engine Ruby oracle：通过。
- seed 诚实性：通过。未有证据的六循环/22 切面/5 链/12 测不伪造 covered/pass。
- 预植缺陷：通过。缺区、多余区、taxonomy 重复/错名、无证据 covered/成熟度、无理由 not-applicable 均在信任边界失败。
- 本记录不声称文学质量 PASS；机器校验只证明结构、来源、依赖和已登记证据。

## 2. 私有冻结快照基线

`validate.rb --all --strict` 实测：

- 冻结快照文件清单 SHA-256：
  `297c817bec43bd34a986a74ed0cb70454eb697cda708e5c463ee89a6349868e9`；
- 产品受限导入 adapter + `deterministic_findings` 生成的同域 manifest
  SHA-256：`02ae14f5f359c1d5ca5b73996c7c487c1bca4a88dc7be8502cf1cd7b14241639`；
  共享校验子集输出 0 error / 0 warning，与 Ruby oracle 一致；产品增强的
  `wikilink-anchor-dangling` 输出 3 error / 0 warning。验收未修改私有 Vault，
  这三项在导入后会作为可定位的结构阻断呈现给作者。

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

- 本轮冻结输入 SHA-256：
  `e05f284895bb4797bfb0ffccf03d14d87b557c40bbfce3dbc59af5b4f4595661`；
- `worldbuild.rb validate --json`：`valid=true`，0 error，0 warning，3 rules，22 facets，12 pressure tests；
- `worldbuild.rb audit --json`：foundation=true，social_realism=false，situated_reality=false，
  counterfactual=false；6 循环和 22 切面保持 gap，5 链保持 gap，12 压测保持 not-run；
- route 仍归 world owner，证明 seed checkpoint 没有被误写为完整可交付世界。

## 4. 产品门禁证据

- Pydantic 严格校验 21 个 required key（schema/engine 版本 + 19 内容区），禁止 extra。
- 活动策略可声明 Frontmatter schema、required/forbidden regex、字段相等与数值容差；
  策略目录导入只生成候选工作稿，显式发布后才激活，且同时只允许一个活动策略。
- F01–F22、C01–C05、T01–T12 同时校验 ID 和权威名称一一对应。
- `covered/partial`、非零成熟度、已运行压测和 canon 主张均需证据；
  `not-applicable` 需理由。
- 校验任务冻结 policy/manifest/dependency/target hash，预算或 coverage 不足不部分通过。
- world-state checkpoint 正文进入冻结 manifest 和 ReviewPacket；checkpoint 变化会使
  旧 full receipt 立即 stale。语义分片每片持久化 input/result hash、coverage、
  findings 与预算，中断后跳过已完成分片。
- 原生引擎层显式投影六循环、22 切面及 L0–L6 框架/实例成熟度、
  5 耦合链、4 情境测试、12 压力测试、规则代价/故障/维护、失效下游和
  audit overclaim；未有证据只能产生 gap/not-run 或阻断。
- WikiLink 同时覆盖正文与 Frontmatter；heading anchor 是 Ruby strict 之外的产品增强检查。
- full 单飞由 PostgreSQL/SQLite 部分唯一索引保底；targeted 不受错误串行。
- 作者启用项目策略后，draft publish 和 adoption apply 在任何正典写入前验证回执。
- 规则/schema/术语/世界核心/校验策略/带依赖工作稿和采用包只接受包含该目标的 full
  receipt；普通工作稿保留 targeted 快速路径。
- warning 签收保存 owner、时间、理由、完整 finding IDs 和 receipt hash；
  stale/fail/author-required/insufficient-evidence 不可签收绕过。

## 5. 仓库回归

- 后端完整套件：4679 passed，12 skipped，6 deselected。
- 前端完整套件：143 files / 1855 tests passed；生产构建通过。
- PostgreSQL 关键 E2E：4 passed，覆盖空库迁移、full 单飞、targeted 并行与
  项目删除级联。此前同分支已跑过更广的 27 项 PostgreSQL 回归；本次修补后
  重跑直接受影响的关键集。
- Ruff、19 个 Prompt contracts、`git diff --check` 与
  `make docs-check BASE_REF=origin/main` 均通过。
- PostgreSQL 验收使用独立临时库 `world_validation_e2e`；完成后容器已删除，
  未读写开发库。

## 6. 运行时边界

- 生产代码不依赖 Ruby、MCP 或自治 Agent；Ruby 只是本地验收 oracle。
- 语义审计仅在激活策略明确开启时，使用项目 secret-free LLM snapshot 和有界 ReviewPacket。
- 本次没有用私有正文做仓库 fixture，也没有把 Vault 内容写入日志或数据库。
  验收使用的本地快照和隔离 WorldCheck state 已移入废纸篓，不留在运行目录；
  它们仍可由用户从废纸篓恢复。
- 产品目标画像为长篇作者（画像 A）；“更愿意重复使用”仍是产品假设，
  不冒充真实用户验证。RP/阅读型用户（画像 B）没有新增入口或义务。
