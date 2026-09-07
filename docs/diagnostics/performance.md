# 本机性能诊断运行手册

这是可选的合成数据诊断，不是 CI 延迟门禁，也不改变产品 API、schema 或任务协议。
目标是分开观察作者输入/保存、对象查找、参考资料、导入和 RP 阅读，避免将外部等待误判为卡死。
用户价值假设是减少创作中断和阅读等待；自动化记录不能证明真实作者满意度。

## 边界与前置条件

- 从主题分支运行；固定完整 Git SHA、依赖、设备、电源、视口和 Docker 资源限制。
- 使用 `backend/.python-version`、`frontend-console/.node-version` 和两份 lockfile。
- 工具只接受 `127.0.0.1:55439/e448_perf_test`，API/前端绑定 18000/18080。
  端口占用则停止，不终止未知进程，不迁移默认 `ai_novel_engine`。
- 数据全部合成。启用 public auth，夹具创建真实签名会话，保留 owner、CSRF 和 novel 隔离检查。
  不发送邮件，不导入用户凭据，不联系付费模型；embedding 指向不可用的 loopback 端口。
  因此索引可能以向量缺失的降级结果完成；不能报告真实 embedding/LLM 性能。
- 输出写入已忽略的 `backend/.test-artifacts/performance/`，目录权限 0700。
  `runtime-private.json`、`browser-private.json` 权限 0600，禁止提交或分享。
  HAR、trace、截图、heap、SQL 栈即使来自测试也只在本地审查。

## 准备与启动

必须在没有 `backend/.env` 的隔离 checkout 运行；工具在创建证据或改写进程环境前拒绝存在该文件
的工作目录，防止应用配置加载器读入开发/生产连接。不要为运行诊断删除现有 `.env`，应另建隔离 checkout。

首次创建专用实例；已有同名容器时先核对 label、映射和数据卷，不覆盖：

```sh
docker run -d --name novelcraft-e448-perf-db --label novelcraft.diagnostic=e448 \
  -p 127.0.0.1:55439:5432 \
  -e POSTGRES_DB=e448_perf_test -e POSTGRES_USER=perf_test \
  -e POSTGRES_PASSWORD=synthetic_perf_only \
  -v novelcraft-e448-perf-pgdata:/var/lib/postgresql/data \
  pgvector/pgvector@sha256:7ae6051efd0e60444282c27c7e141af07f322ce033300e727a49c3dd11075e38
```

仓库根目录执行 `make docs-check`、`uv sync --project backend --locked --extra ci`；
在前端目录以锁定 Node 执行 `npm ci`、`npm run build`。
后端目录依次执行：

```sh
uv run --locked --extra ci -- python -m tools.performance_probe migrate
uv run --locked --extra ci -- python -m tools.performance_probe seed
uv run --locked --extra ci -- python -m tools.performance_probe epub
```

`seed` 创建 S/L 作者与旅程夹具并写出 counts/hash/字节数和浏览器会话。
重复 seed 会轮换测试会话；浏览器运行期间不要执行。`epub` 同时生成具有明确章节边界的 TXT/EPUB。
`reset` 仅恢复两档前两章的已知工作稿，**不是整库或索引重置**；严格前后比较需从相同初始夹具建新实验，不能把累积的导入项目和任务当成相同状态。

后端两个独立终端，分别重定向到证据目录的 `api.log`、`worker.log`：

```sh
uv run --locked --extra ci -- python -m tools.performance_probe api
uv run --locked --extra ci -- python -m tools.performance_probe worker
```

前端另开终端：

```sh
BACKEND_PORT=18000 npm exec --no -- vite preview --host 127.0.0.1 --port 18080 --strictPort
```

这是生产前端 bundle 的本机预览，未覆盖生产反向代理、Tunnel、远端网络和服务器架构。

## 采集

前端目录运行 `node scripts/performance-probe.mjs <模式> <S|L>`：

| 模式 | 实际覆盖 |
|---|---|
| `smoke` | Chrome 有头模式打开写作、对象列表、RP，保存截图 |
| `baseline` | 每路径 5 次新浏览器上下文进入；两档正文各输入 60 秒并独立回读；30 次切章、对象筛选、普通/热点 API、RP 滚动；一次 compile；390px 检查 |
| `imports` | 两种格式经实际 UI 上传到独立合成项目，确认导航与 API 章节总数 |
| `recovery` | 断网保存、实际 localStorage 备份、确认离开/恢复、刷新和恢复后保存 |
| `profile` | 单独采样 5 组大段文本替换，保存 Chrome trace/cpuprofile；不混入基线 |
| `native-control` | 用同尺寸和字体的原生 textarea 对照大段替换；不等价于真实系统剪贴板/IME |
| `contention` | 300 章上传后的真实索引积压期间编辑另一项目；embedding 不可用，不代表 LLM 工作负载 |
| `multi-tab` | 两个真实浏览器上下文编辑同章，确认先保存成功、后保存 409，且冲突方正文保留 |
| `soak` | 20 次预热往返后，固定资料编辑/阅读 30 分钟，记录同页面 GC 后堆、DOM 与监听器；诊断数组每轮清空 |

`baseline` 的输入 roundtrip 包括 Playwright 调度和两次 requestAnimationFrame；它不是 INP。
Event Timing 仅采到浏览器暴露的、超过 16ms 的事件，不能用它推导全部交互分位数。
切页、请求、输入、保存、首段/完成时刻必须分开；缓存命中不产生网络请求。
冷进入指新浏览器上下文，浏览器进程/API/数据库并非都冷启动。
定位器就绪耗时包含 Playwright 自动等待，是观察上界；不能将它与 API 耗时相减后冒称前端渲染时间。

后端可另开轻量采集：

```sh
uv run --locked --extra ci -- python -m tools.performance_probe observe --seconds 2400
```

每两秒保存活动连接、事务年龄、阻塞 PID 及最新 100 个任务的生命周期字段，
不保存 query 文本、正文、task meta/result。此窗口可能漏掉很短的锁及更早任务；
需要完整任务总量时另外查询聚合，不能把 100 行当全部任务。

只有对象查询显示规模效应时，执行 `python -m tools.performance_probe queries --label before|after|repeat`（同一 uv 环境；选择一个 label）。
该独立 ASGI 采样保留账户鉴权，计数 SQL 调用和 driver 耗时；不含真实浏览器/网络开销。
请求时间减 SQL 时间仍含连接获取、事务提交、调度、序列化等，不是纯 Python CPU。
它另在只读事务及 5 秒超时内，对 L 档别名计数中捕获的最慢非锁定对象 SELECT 做 EXPLAIN ANALYZE；
只保存执行计划与语句 hash，不保存鉴权参数。执行计划包含合成项目标识，仍留在本地证据目录。

## 对象读取与真实输入复测

第二轮结果见 [别名优化与输入定位](2026-09-07-alias-optimization-and-editor-input.md)。
后端新增 `alias-seed`：在原夹具之外创建 AS / AL 两个项目，各 300 / 3,000 个对象，每对象含
一条旧字符串别名、一条 active 别名和一条 confidence=0 的 candidate 别名。重复调用只核验原
项目 owner、数量和内容 hash，漂移即失败，不覆盖现有夹具。要求先完成原 `seed`。

```sh
# backend
uv run --locked --extra ci -- python -m tools.performance_probe alias-seed
uv run --locked --extra ci -- python -m tools.performance_probe queries --label before
# frontend-console；优化后使用相同命令，将 before 换成 after
node scripts/performance-probe.mjs world AL before
```

`queries` 在原 S/L 和新增 AS/AL 上分别预热一次，再做 3 批 × 10 次请求；保存状态、响应 hash、
字节数、SQL 次数/driver 耗时和热点阶段边界。输出按 label 和时间命名，失败也保存已采集样本与
错误类型。热点计时仅在此独立进程临时包装既有方法和活动统计 port，退出时恢复，不进入正式
服务。`ranking_between_activity_and_page` 是两个 await 之间的经过时间，并非精确 CPU 时间；
`_list_hot` 包含子阶段，不能与它们相加。

`world` 的档位可选 S/L/AS/AL：5 次新上下文进入、每种 API 模式 30 次实际请求、30 次 UI 筛选，
最后检查 390px。它在测量前后核对专用 Docker label 和队列为空；`queries` 也会拒绝非空队列。
所有性能进程、测试、构建和夹具核验必须顺序运行。门禁不能检测全部外部 CPU/网络负载，
操作者仍需记录环境；不要将已有任务取消来掩盖正在进行的真实业务。

每个浏览器运行记录实际 Git SHA、tracked diff hash、业务源码与脚本 hash，不再把 `fixture.sha`
当成当前执行版本。生产前端 bundle 仍需单独核对资源清单 hash。原始结果位于原证据目录，
第二轮夹具、阶段结果和汇总位于 `round2/`，均不提交私有会话或原始 trace。

前端新增以下本机诊断模式；第三个参数是 S/L，第四个 label 默认为 repeat：

| 模式 | 用途与测量边界 |
|---|---|
| `world-checks` | 详情关闭后保留筛选、390px、明确注入 503 后验证错误反馈及重试；注入失败不是服务端基线 |
| `clipboard` | 系统剪贴板粘贴、全选粘贴、局部替换、撤销和继续输入；应用/原生 textarea，3k/30k，各 5 次，应用保存独立回读 |
| `clipboard-profile` | 相同流程另采 Chrome trace；CPU profile 仅为应用页，trace 可含其他页面，不混入无 profiler 结果 |
| `persistence` | 输入后静置至自动保存，记录输入事件、微任务、两帧回调与本地存储时刻；最后切章返回核对原文 |
| `ime` | 等待外部原生键盘产生 compositionstart 后观察 3 × 60 秒；本机未完成原生输入验证 |

剪贴板模式要求 macOS 的 `pbcopy/pbpaste`；只应在剪贴板为纯文本时运行，脚本在内存中保留并
恢复纯文本，不保存用户剪贴板到证据，不承诺保留非文本格式。实验内容全部取合成夹具。
输入时序探针记录长度和时刻，不记录输入内容；storage 的 `codeUnits` 是 UTF-16 单元数，
第二轮早期原始文件中同一字段曾名为 `bytes`，它不是 UTF-8 字节数。

输入 capture → handlers-returned 覆盖同步输入处理，后续微任务只是观察边界，不能等同于
全部 Vue 更新耗时；两帧返回不是 INP。原生对照复制尺寸、字体等指定样式，没有复制完整应用
容器、所有计算样式和监听器，因此差值不能直接归给 Vue。

`ime` 运行时须确认真正操作的是隔离诊断窗口，使用系统输入法物理按键，不能用 `insertText`
或手工派发 composition 事件替代。三轮结束后脚本打印 `finishFile`，外部操作者停止输入，再
创建该空标记文件，脚本才保存、独立回读并恢复原文；等待超时会失败并保留记录。本机 CUA 只
暴露日常 Chrome 实例，不能定向该隔离实例，因此此模式目前仅验证到 observer-ready，须人工验收。

## 卡死与验收

输入/点击五秒无反馈时记录操作与时间，先保留浏览器 trace、进程 CPU/RSS、任务 checkpoint、
数据库等待链；再对经过 cwd/PID 核对的诊断进程运行 `py-spy dump --pid "$PERF_PID"`。
连续三份栈间隔五秒，必要时 `py-spy record --pid "$PERF_PID" --duration 30 --rate 50 --threads --idle --output "$PERF_OUTPUT"`。
不输出 locals，不给未注册处理器的进程发送诊断信号，不放宽生产容器权限。
没有进程卡死时不为凑证据执行重启或栈转储。

只报告样本数、中位数、范围、失败和未完成样本。30 次不是可靠的 p95/p99 基线；
绝对目标和改善幅度需基线校准。以原始样本和重复批次波动判断变化，不设任意百分比门禁。
恢复、并发、离开保护和隔离测试与性能测量分时运行。

相关检查入口见 [测试指南](../../testing-guide.md)。新工具的最小检查为
`pytest tests/unit/test_performance_probe.py`，覆盖拒绝错误数据库及真实 TXT/EPUB 解析规模。
诊断不改变任何正式运行接口，无 schema migration 或新 ADR；收尾仍跑 docs-check 和 diff 检查。
停止只限本次创建的 API/worker/preview 与已核对 label 的诊断容器，保留数据卷和证据供复查。
