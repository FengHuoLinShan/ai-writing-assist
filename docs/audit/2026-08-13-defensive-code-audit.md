# 后端生产代码不必要防御审计

> **日期**：2026-08-13
> **状态**：已完成；仅记录，未修改生产代码
> **基准**：`6b553dd6e97d355210e2822b2e758c6249d705d4`
> **变更**：文档-only；稳定接口/API/schema/wire/ORM/用户行为均未变，无 ADR 或用户确认需要。

## 1. 范围、方法与限制

范围仅为后端生产 Python：`backend/app`、`backend/core`、`backend/shared`、
`backend/infrastructure` 与 11 个 `backend/modules`。测试与 Alembic migration 只用作
旁证；前端、部署、测试本身不在本次全量审计范围。

本次以调用链、稳定接口、schema、ORM/migration 与相关测试交叉复核附件所列项目及邻近
模式；不以单处命中或行号直接定性。可复现的同一排除规则下，`sha256` 文本命中 119 行/60
文件，`hashlib.sha256` 文本出现次数为 104，`except Exception` 为 235 行/85 文件，
生产 `assert` 为 18。以上是定位统计，不代表逐一人工审完 235 个异常处理。

可复现命令（从基准 checkout 运行）。roots 仅含生产目录，故 `backend/alembic` migration
不在范围；每条命令同样排除测试 Python 文件：

```bash
rg -n -g '*.py' -g '!**/tests/**' -g '!test_*.py' 'sha256' backend/app backend/core backend/shared backend/infrastructure backend/modules | wc -l
rg -l -g '*.py' -g '!**/tests/**' -g '!test_*.py' 'sha256' backend/app backend/core backend/shared backend/infrastructure backend/modules | wc -l
rg -o -g '*.py' -g '!**/tests/**' -g '!test_*.py' 'hashlib\.sha256' backend/app backend/core backend/shared backend/infrastructure backend/modules | wc -l
rg -n -g '*.py' -g '!**/tests/**' -g '!test_*.py' 'except Exception' backend/app backend/core backend/shared backend/infrastructure backend/modules | wc -l
rg -l -g '*.py' -g '!**/tests/**' -g '!test_*.py' 'except Exception' backend/app backend/core backend/shared backend/infrastructure backend/modules | wc -l
rg -n -g '*.py' -g '!**/tests/**' -g '!test_*.py' '^[[:space:]]*assert ' backend/app backend/core backend/shared backend/infrastructure backend/modules | wc -l
```

本文中的“哈希”是内容哈希、消息摘要或指纹；凭据加密单列为 Fernet 加密。不存在“hash
加密”这一归类。审计是时间点证据，不构成当前架构契约。

## 2. 执行摘要

确认可简化项只有两处，均为局部重复控制流，预计合计约 **-15 行、-0 依赖**；本轮没有实施。
未发现可安全删除的安全哈希、消息摘要、凭据加密或安全比较实现。其余候选要么触及
API/schema/wire/ORM，要么证据不足，要么实际承担边界校验、并发语义或兼容性职责。
待确认候选只构成未来变更的触发条件，不代表本轮接口或行为变化。

**结论：`net: ~-15 lines, -0 deps possible`（估算；本轮未改）。**

## 3. 确认可简化项

按 ponytail 优先级排序：

| 排名 | 位置 | 现状与最小改动 | 预计收益 | 契约风险 |
|---|---|---|---:|---|
| 1 | `modules/rag/repositories.py::_upsert_chapter_chunk_rows` | 三个 dialect 分支均调用同一方法；收敛为一次调用。 | ~-11 行 | 无公开接口变化；实施时仍需覆盖各 dialect。 |
| 2 | `modules/world/schemas.py::_uuid_validator` | 三个分支最终均为 `str(v)`；保留 docstring，改为直接返回。 | ~-4 行 | 无 schema/wire 变化。 |

两项均尚未修改；实施前应以当前 HEAD 重看全部调用方和既有定向测试。

### Assert 复核

`_assert_found_in_novel` 之后的 5 处运行时检查可视为冗余，但同时承担静态类型收窄，删除
没有实质收益，故不计入净减。其他 `assert` 是局部状态不变量。不能把约 10 处断言统称为
“零风险可删”。

## 4. 必要安全边界与普通哈希

下列安全实现属于删除禁区：account 的 keyed HMAC（会话、CSRF、email、OTP）、middleware
CSRF、closed-test `compare_digest`、OIDC 的 state/PKCE/JWKS/JWT/nonce/`at_hash`，以及
LLM API key 的 Fernet 加密与用途分隔 HMAC fingerprint。未发现可安全删除项。

普通 `sha256` 多用于内容、缓存、任务幂等或新鲜度判断，不应因“不是密码学防御”就删除；其
是否可删须以消费者、持久化字段与失效语义判断。

## 5. 待确认候选（不计入净减）

| 候选 | 当前证据 | 为什么不作为本轮删减项 |
|---|---|---|
| `MapAtlasRun.context_hash` | 模型列、两处写入与 Alembic 存在，未见生产读取。 | 清理是 schema 级变更，需同时处理 ORM、migration 与文档。 |
| `external_packet.sha256` | 客户端自报 hash 与同一请求的 `pasted_context` 比较，不能防篡改。 | 属公开 schema/wire；服务端还按 packet presence 切换合约并回显。 |
| `profile_hash` | 非对手安全用途；快照损坏时 fail-closed 有可辩护价值。 | 删除会改变损坏/恢复语义，现有证据不足。 |

## 6. 附件中需要纠正的判断

| 主题 | 复核结论 |
|---|---|
| `model_validate` | imports 两处是 LLM/适配器边界；interaction 读取 ORM JSON 时也是持久化边界。保留。 |
| settings 双白名单 | service 与 repository 分别守住业务和持久化边界；保留。 |
| XHR 门禁 | 全局 middleware 与路由声明目前有重叠，但有 43 个端点声明（settings 10、project 2、map 11、interaction 20）；不可写为零风险重复。 |
| `SceneService` 二次 `get` | 首读结构 meta，随后通过 CrudService 保持并发删除/404 语义；保留。 |
| `project repository.update` | 返回 `Optional` 是现有语义，不可仅按调用方乐观路径收紧。 |
| memory 类型/dict 回退 | 可能是兼容性路径，证据不足。 |
| project task `flush` awaitable | 支持替身与松耦合，删除收益不足。 |

## 7. 已确认正确性缺陷（不修复）

`world_background` 对 `context_brief` projection 比较 `sha256(free_text)`，而生产 refresh 写入的是
`projection_source_hash(page)` 的结构化 JSON 哈希。正常投影因此会被判为非当前并回退到
`free_text`（除不可行的 SHA collision）。`activation_target_service` 是正确参考实现。

现有测试未覆盖“ready `context_brief` 经 background 聚合后被选用”。修复会改变上下文输出，
应作为独立正确性改动，不能伪装成防御代码删除项。

## 8. `except Exception` 定向复核

定向检查显示异常处理不能统一定性为冗余防御：

| 分类 | 示例 | 结论 |
|---|---|---|
| 已有 warning/degraded | context `novel_evidence`、writing API | 已明确降级或诊断路径。 |
| 故意 best-effort/cancellation | writing `conflict_ai` 取消收敛、interaction generation 失败后落库的二次失败 | 用于收敛/记录，非普通吞错。 |
| 静默吞错候选 | outline `scene_source_service`、`scene_fusion_draft`、context `import_activation`、imports `workflow_llm_adapters` fallback primary | 是错误处理质量候选；本轮不纳入 ponytail 净减，也不提出实施。 |

## 9. 后续触发条件

- 若要清理 `context_hash` 或 `external_packet.sha256`，先建立包含 schema/wire、ORM、migration、
  消费者与回归测试的独立变更。
- 若要修复 World Bible 哈希不一致，先明确预期上下文输出变化，并补 ready projection 聚合
  回归。
- 若要处理静默异常，逐处定义失败可见性、降级与持久化语义；不得用删除 `except` 或扩大
  吞错范围替代设计。
- 若实施第 3 节两项，保持最小 diff、无新依赖，并运行各自模块的现有定向测试。
