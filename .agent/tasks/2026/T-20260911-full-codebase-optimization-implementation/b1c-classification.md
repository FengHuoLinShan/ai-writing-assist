# B1c 路径分类账

日期：2026-09-12。范围仅限审查发现 F6-3、F5-1、F6-4、F6-8、E1-9；判定依据为当前 Git 跟踪清单、全仓消费者检索、文件内容和正式文档。删除仅影响仓库工件，可由对应提交恢复，不重写历史。

| 路径 | 规模 | 消费/唯一证据 | 判定 |
|---|---:|---|---|
| `.claude/scheduled_tasks.lock` | 1 文件，130 B | 记录已失效 PID/session，无消费者 | 删除：纯运行时锁 |
| `.claude/workflows/module-architecture.js` | 1 文件，5 KiB | 无消费者；扫描已不存在的 `backend/app/modules/*`，写入旧绝对路径；正式架构图和机器清单已存在 | 删除：过时的一次性生成脚本 |
| `.claude/settings.json` | 1 文件 | 当前 Claude 项目配置 | 保留 |
| `.opencode/loop-history/` | 21 文件，192 KiB | 工具轮次历史；`docs/README.md` 明确排除；结论已由本次 241 条逐项审查重新验证 | 删除：被当前审查取代的工具会话产物 |
| `.playwright-mcp/` | 6 文件，32 KiB | 无消费者；已在 `.gitignore`；含控制台日志和重复页面快照 | 删除：浏览器运行时产物 |
| `.superpowers/brainstorm/*/state/` 与 `content/waiting*.html` | 7 文件 | PID/server-info 与相同等待占位页，无产品消费者 | 删除：运行时状态和占位页 |
| `.superpowers/brainstorm/*/content/` 其余设计稿 | 22 文件 | 无代码消费者，但包含地图、写作布局和交互方案的唯一可读设计探索 | 保留：存在明显产品设计价值；后续如正式方案完全吸收再另批归档 |
| `backend/backend/.test-logs/` | 11 文件，100 KiB | 错误工作目录产物，无消费者/文档引用 | 删除原始日志，在本账记录最小证据：两次 PostgreSQL 导入分别因未注册 `outline.generate_structure` 与 world_objects 终态解释失败；一次 plot-structure 完成（3 threads、3 arcs、1 foreshadowing、1 reveal）；并发探测仅一轮记录 1/2/4/8/16/75 全成功，其余三轮 0 |
| `backend/.test-logs/` | 240 文件，25,388 KiB | 付费真实模型历史证据；4 个具体日志被验收文档直接引用，其余多数没有等价来源 | 保留 239 个不可替代的运行证据；删除无消费者且可由日志重建的 `latest.json` 指针 |
| `backend/tests/e2e/samples/lotm_chapter_1.txt` | 1 文件，8.9 KiB | 无消费者 | 删除：无价值且含第三方作品衍生样本 |
| `backend/tests/e2e/samples/lotm_empty.txt` | 1 个空文件 | 无消费者 | 删除 |
| `backend/tests/e2e/samples/lotm_chapters_1_2_3.txt` | 1 文件，27.6 KiB | `seed_data.py` 消费，三份历史文档引用 | 用三章原创合成文本等价替换并改为中性文件名；同步消费者与当前文档引用。保留三章分隔、人物/地点/组织/物品、时间与因果线索，验证导入/RAG 结构而不保存第三方原文 |

## 验证与回滚

- 每类独立提交；删除前后以 `git ls-files` 和全仓引用检索复核。
- 合成样本运行后端 E2E 中实际消费正文的导入/RAG/Outline 用例；工具工件清理运行部署/镜像门禁，确认未进入构建产物。
- 删除均可 revert。真实模型证据和实质设计探索不因“未被代码 import”而删除。
