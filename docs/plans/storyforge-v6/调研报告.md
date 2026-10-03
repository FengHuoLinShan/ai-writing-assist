# StoryForge(故事熔炉)深度调研报告

> 调研对象:https://github.com/yuanbw2025/storyforge(本地克隆 `/tmp/storyforge-deep-research/repo`,HEAD=`436abe42`,2026-10-01)
> 调研方式:八个方向的只读静态调研(产品定位 / 用户旅程 / 架构 / 数据层 / AI 管线 / 互动叙事改编 / 工程质量安全 / 活跃度社区)+ 三份与本项目(ai-writing-assist / NovelCraft)的对比分析。全程未运行双方任何代码、测试、构建或真实模型调用。
> 证据口径:文中 path:line 为各方向分析师在本次会话实际读取时记录的行号;SF 侧证据分两档——分析师亲自打开核实的,与转引自工作流材料的(抽查过的关键条目均与克隆一致)。汇总阶段另行实测核对了一处争议数字,见「十五、调研方法与局限」。

---

## 一、项目概览

**一句话定位**:开源(MIT)、本地优先、纯前端(无后端)的 AI 叙事创作与体验套件——在浏览器里写长/短篇小说、把小说改编成剧本/漫画/漫剧素材,把设定封存成可版本化的"世界",再在其上跑跑团、角色聊天、AI 小镇等互动产品(README.md:15 自述"开源、本地优先的 AI 叙事创作与体验工具";docs/PROJECT-MASTER-CHARTER.md:37 定义为"面向叙事创作与叙事体验的 AI 原生生产系统",并明确"不是单一小说编辑器")。

**技术盘**(package.json 与摸底实测):TypeScript 全仓(src/lib 959 个 .ts/.tsx,仅 1 个 json);React 19(锁定 19.2.8)+ react-router 8(^8.3.0)+ Zustand 5(49 个 store)+ Dexie 4(4.4.5)+ TipTap 3 + Tailwind 3.4;构建 Vite 6.4.3(PWA,`base=/storyforge/`,生产部署 Vercel);测试 Vitest 2.1.9(happy-dom + fake-indexeddb,覆盖率门槛 registry 75%/其余 58%)+ Playwright chromium;文档站 VitePress。版本号 3.9.1、MIT、约 90 个 npm 脚本;README 推荐 Node 24。

**运行形态**:无任何服务端,浏览器本地优先,AI 全部 BYOK(自带 API Key);开发服务器在 vite.config.ts:162-242 为 13 家 LLM 供应商(DeepSeek/OpenAI/Kimi/Claude/Gemini/豆包/Qwen/GLM 等)配 CORS 代理——仅 dev 期有效,生产是纯静态站。

**基本盘**(GitHub API,gh api,2026-10-01):
- 800 stars、135 forks、MIT、open_issues 8;建仓 2026-04-13,至今约 5.6 个月。
- Git 提交 1663 个(本地完整克隆,`git rev-parse --is-shallow-repository`=false),剔除 bot 后人工提交 1448,其中 99.3% 来自 yuanbw2025 一人。
- 12 个 release tag(v3.6.0→v3.9.1),最新 v3.9.1 停在 2026-08-04;Windows 安装包停在 v3.7.4(2026-07-03 后所有 release 无二进制附件)。
- 站内流量(仓库自带 data/traffic/,每日 cron 归档):9 月 views 8242、独立访客 3349,clones 3884;release 资产累计下载约 704 次。

**本项目基线速写**(用于对比章节的锚):NovelCraft 是面向中文长篇创作与私人故事(RP)双场景的 AI 结构化创作引擎——服务端架构(Python 3.12+/FastAPI/SQLAlchemy async + Vue 3 + PostgreSQL 17/pgvector),12 个业务模块,用证据、版本与授权流水线维护长期叙事状态,"模型输出"与"正式资产"分开管理;当前 Alpha/工程验证阶段(README.md:14)。

---

## 二、产品与定位

状态的机器事实源是 src/lib/product/product-catalog.ts(100-113);路由在 src/App.tsx:42-63 全部实际存在(逐一验证);权威逐项状态在 docs/roadmap/CAPABILITY-BASELINE.md。

**本次汇总实测核对了 catalog 状态计数**:`grep -o "status: '[a-z]*'" src/lib/product/product-catalog.ts | sort | uniq -c` 输出 **6 released / 7 preview / 1 experimental(共 14 个条目)**。架构方向材料所称"15 个条目、preview 8"与实测不符,以实测为准(该差异不影响任何结论,只涉及条目计数)。

### 正式产品(released,6 条)

| 产品线 | 入口 | 解决的创作问题 | 关键证据 |
|---|---|---|---|
| 分步骤长篇 | /long、/workspace/:projectId | 跨章记忆:早期伏笔/事实找回、人物状态承接、章后变化确认;四层资料链=原文+结构化事实+分层摘要+按需检索,Context Gateway 先查目录再读细节并记录来源 | README.md:70、185-197;基线 B-LF-01~06;规模门 tests/regression/R-PHASE4-long-form-scale-gate.test.ts:17-19 定义 10 万/30 万/100 万字符夹具(文件存在,本次未运行) |
| 短篇小说 | /short | 5,000~25,000 字、3~8 章:篇幅目标变完成条件、审校意见落到章节证据、缺章/待处理候选阻止发布 | README.md:211-219;showcase/short-novel/ 4 部,如 tide-radio/release-evidence.json(实测 5080 字/目标 5000、4 章、17 次审校、手稿 SHA-256) |
| 小说转剧本 | /script | 改编可追溯:冻结原文来源、改编决定关联节拍与场景、忠实度与戏剧性分开审、场景 AST 结构化正文、Fountain/FDX/打印导出 | README.md:221-231;showcase/screenplay/ 4 部(.fountain+.fdx+source-novel+release-evidence.json) |
| 小说转漫画 | /comic | 页格分阶段生产:显式阅读链写进数据结构、角色视觉档案、本地 SVG 排字层(错字不重画)、分镜版/视觉版双版本、PNG/WebP/CBZ/PDF 导出 | README.md:233-244;showcase/comic/ 4 部(du 实测 71M/44M/44M/57M,共约 216MB) |
| 漫剧素材 | /motion | 为外部视频工具(Seedance/Runway/LTX)准备逐集剧本、分镜、参考帧提示词与逐镜执行包;"产品终点停在外部视频生成之前"(总纲 4.6,PROJECT-MASTER-CHARTER.md:175) | catalog:105 maturityNote 明示"不包含视频生成和成片制作";showcase/motion-drama/last-train-echo/ 仅 1 个 seedance-execution-pack.md,无成片 |
| 世界引擎 | /world | 让设定成为可重复引用的资产:独立编号、不可变封存版本(WorldRelease)、按产品需求读取(describe/search/read)、SourcePlan 冻结"计划用什么"、SourceManifest 记录"实际用了什么" | README.md:266-274;基线 D-WORLD-01~04;实现入口 src/lib/context-gateway/world-release-client.ts 存在 |

### 预览(preview,7 个)与实验(experimental,1 个)

节点创作(B-NODE-02 partial,官方节点绑定长篇正式 Skill,"实验节点的草稿不能直接采纳为正式作品内容",README.md:203)、跑团/AI KP(原创 2d6 调查规则、秘密按接收者过滤、检查点续玩;《雾港:最后一盏灯》7 场景/6 线索/3 结局可玩;"公共联网多人尚未部署,同机交接不提供设备拥有者的秘密保护",README.md:64)、角色聊天(冻结角色档案、承诺/秘密/冲突记忆;"当前为纯文字")、后日谈 AI 小镇(六时段日程、居民知识隔离、14 日回放验证)、文字冒险(行动前置条件、背包资源、阈值/随机/资源支付判定)、AVG(剧情节拍绑定声明式演出指令)、文字开放世界(《盐脊:断流之夜》20-30 分钟内置纵向展示,基线 74 行明言它"证明核心系统闭环,不等于 3-5 小时完整验收世界、真实模型质量或商业验收已经完成")。experimental:/community 社区市场(catalog:113,"默认隐藏,仅允许本地显式研究")。

**内容资产(非生成能力,README 自认)**:《雾港:失潮钟声》(/play/mist-harbor)是预写作品:18 节点/158 节拍/3 结局/17 项美术,无需 API;README.md:40 明言"这是预写的内置作品……不代表通用文字游戏生成能力已完成"。

**发现一处 README 与代码事实的偏差**:README.md:30 与产品导览表(README.md:118-127)只列 5 个正式产品,漏了 catalog 已登记 released 的漫剧素材;文档站 website-docs/getting-started/what-is-storyforge.md:26 写"六个产品在当前目录标为已发布"。是刻意低调还是未同步,仓库无说明,如实报告差异。

### 目标用户与三大定位的代价

仓库没有正式的用户画像文档(website-docs/、docs/ 中检索"目标用户/受众"仅命中 Prompt 库)。基于间接证据的推断:主要面向**中文个人创作者**——界面与默认文档中文优先、运营生态全中文(B 站教程、知乎专栏、QQ 群 1082374587、爱发电)、showcase 题材与 Prompt 库的网文方法论;结合 BYOK 与审慎的候选确认模式,画像还包括"愿为 AI 效果自己负责"与"对 AI 生成持审慎态度"的作者。体量佐证:GitHub 流量账本显示小众早期项目,不是大众产品。

- **开源(MIT)**:代码可商用;代价是 main 即生产、无 staging(AGENTS.md:28),Release 是旧固定快照、版本号停滞 3.9.1——用户实质上被迫当"主干用户"。
- **本地优先**:作品、设定、存档都在当前浏览器 IndexedDB;代价 README 写得很实:数据按"浏览器×域名×端口"隔离(localhost 与不同端口也不共享,README.md:448)、备份责任完全在用户("第一次创作后就做一次 JSON 备份",README.md:428)、可选 Gist 备份"不是端到端加密存储"(README.md:426)。
- **BYOK**:模型费用由服务商直接向用户收取("开源代码和本地数据管理不意味着云端生成免费",README.md:398);代价:CORS 是纯前端架构的硬代价(设置面板 18 个供应商中 9 家标 cors:false 需本地代理,AIConfigPanel.tsx:21-37;vite 代理仅开发服务器提供)、效果风险自担("不是每个模型都已通过所有产品的效果测试",README.md:407)、Key 管理责任在用户。

### 宣传话术 vs 仓库实物

**有实物支撑(已逐一验证)**:13 个产品入口全部有路由与 catalog 登记;README「可以检查哪些证据」表(README.md:379-392)引用的 6 个回归测试 + 18 个实现入口文件全部存在(逐个 ls 验证);tests/regression/ 实际 740 个文件;四条改编产品线有真实成品与哈希化证据文件;供应商清单与 AIConfigPanel.tsx:21-38 实际选项一致;项目自我克制的话术在同仓库内互相印证(README.md:40、197、242;基线:71"工程闭环不能冒充这些外部事实")。

**属于措辞边界的宣称(不假但需按其限定理解)**:"10 万/30 万/100 万字符规模验证"是工程夹具验证(seedScale 种子数据),宣传价值上限是"检索链路可扩展",不是"能产出百万字好小说"(README.md:197 自我声明"真实作者长期文学一致性是持续质量研究");"六产品正式"是工程闭环口径,各产品缺口列均承认"provider 表现、文学质量、盲评持续观察";showcase 成品证明生产管线可跑通,不证明内容达到商业/文学标准。

**本次未验证**:未运行 npm run ci、测试套件或应用构建(只读产品分析),"25 道门通过""e2e 通过"只能确认已配置(package.json:61)而非本次执行通过;界面实际形态仅有 2026-09-15 隔离截图与文档互证,未启动应用亲验。

---

## 三、用户旅程与交互体验

本章按真实用户操作顺序还原:安装/启动 → 首页 → 体验内置作品《雾港》→ 建项目 → 长篇创作 → 改编/发布。所有结论来自对克隆的只读阅读,涉及交互效果的表述为基于代码与文档的推断。

### 步骤 0:安装与启动

两条获得路径:在线版(https://yuanbw.vercel.app/storyforge/,Vercel 部署)与本地源码运行(git clone + npm ci + npm run dev,推荐 Node 24;README.md:92-107)。整站挂在 `<BrowserRouter basename="/storyforge/">` 之下(src/main.tsx:104)。

**启动硬门序列**(src/main.tsx:38-76):① 尽早申请 `navigator.storage.persist()` 持久化存储,注释说明不申请时浏览器可把 IndexedDB 当 best-effort 驱逐,"用户表现为数据被重置"(main.tsx:33-40);② `validateRegistry()` 校验三注册表("不完整的读写与生命周期定义不得进入 UI",main.tsx:50);③ `openCurrentSchema()` 数据库 schema 硬门,失败时渲染整屏错误页"StoryForge 无法启动……应用已在任何 Store 初始化之前停止"(main.tsx:54-57、84-96)。老数据/新版本不兼容时,用户看到的不是半可用界面而是明确的停止页——一致性优先于可用的取舍。兼容性垫片:index.html:9-36 在模块包之前注入 ES2023 polyfill,注释点名微信/QQ 内置浏览器、老安卓 WebView、Safari<15.4 的"点章节就报错 transactions.findLast"事故。

### 步骤 1:首页

九分区单页(HomePage.tsx:16),主导航 PRODUCT_NAVIGATION 直接 import 自 ui-preview/src/catalog.ts(product-navigation.ts:1-4)——设计目录即产品导航的单一事实源。「继续上次创作」由全局 ResumeTracker 挂在所有路由外实现(ResumeTracker.tsx:4-14),凡处于工作区路径就记录最近工作位置。空态有语境化文案与 CTA;「这一步,需要你」侧栏列出 awaiting_confirmation/failed/recovery_required/paused 的 AI 运行记录——AI 任务失败或等待确认不会被淹没。内置作品《盐脊》《雾港》卡片直接摆上今天页,每次路由切换前 `open()` 都先 `await flushPendingEditsV1()` 再 navigate(HomePage.tsx:25)——待写盘的编辑先落库。

### 步骤 2:体验内置作品《雾港:失潮钟声》

落地页 hero + 事实徽章"18 个叙事节点 / 3 条结局 / 无需 API"(MistHarborPage.tsx:103-127);用 node 统计 src/content/mist-harbor/story.ts:节点对象 18 个、节拍行 158 个、ending 3 个,与 README.md:36 完全一致。两种玩法二选一:视觉小说与文字冒险。

**首次开始 = 走一遍正式产品生产线**:`mistHarborInstallation.install()` 创建雾港世界版本 → 创建 Brief → `authorize-start`(带 briefHash/authorizationNonce)→ 构建 → `publishProductProductionV1` 发布不可变版本(src/lib/mist-harbor/production.ts:381-505),用 Web Locks 防多标签并发(production.ts:507-513),失败可续(failed/cancelled 归档重建、recovery-required 走重试)。玩家其实消费的是与正式漫画/跑团同一套 productRelease 机制。

**存档与恢复**:进入页面即查询最近一个非 archived 会话作为 resumeId;「继续游玩」复用会话,若"存档与当前作品不匹配"(备份回灌后 releaseId 变化)显式报错(MistHarborPage.tsx:56-57)。AVG 内剧情选择自动落检查点(去重),可 fork 真实子会话分支(avg-game-player.ts:47-131);文字冒险顶栏常驻"自动保存已开启",AI 行动中断可恢复且"不会重复调用模型"(AdventureGamePlayer.tsx:760),页脚声明"存档固定在这一不可变来源上"(:885);无障碍面板(字号四档/行距三档/高对比/减少动效)。

**玩家到作者的反向通道**:作品页导航栏「查看雾港原稿」直达 `/workspace/{worldProjectId}`(MistHarborPage.tsx:81-85);README.md:40 声明"修改原稿不会自动改写已发布游戏"——游戏绑定不可变 productRelease,数据结构保证。

### 步骤 3-5:建项目、长篇创作、改编发布

- **建项目**是原子事务:`createWorkspace` 在一个 Dexie `rw` 事务里同时写 projects、worlds、works 三表并回填指针(create-workspace.ts:155-229);长篇默认 targetWordCount 300000;可绑定本机文件夹,绑定失败不回滚创建结果("作品已创建,文件夹尚未绑定")。
- **长篇创作**:23 个步骤模块线性导航(navigation.ts:9-32),三模式切换(分步骤/节点/主 Agent);章节面板按卷分组,TipTap 编辑器 `key=章节 id` 强制切章重挂载防 AI 生成态跨章串台。**保存机制**:章节更新统一走 `coordinatePendingEditV1` 串行化同记录写(chapter.ts:100-131),content 变化即把摘要节点标 stale;正式生成前强制 `flushPendingEditsV1()`,任一保存失败即"作者编辑保存失败,已阻止正式生成"——AI 不能越过未落库的作者编辑。每 5 分钟自动快照 + 每 10 分钟可选 Gist 云备份(WorkspacePage.tsx:190-191)。
- **候选与采纳**:生成产出为 durable candidate,刷新后按"源章节 hash 仍当前"恢复;过期候选留在事件账本审计但绝不显示为可采纳(ChapterEditor.tsx:597-624)。
- **改编发布**(剧本):来源冻结(「冻结来源并创建剧本」按钮文案即契约,ScreenplayPage.tsx:69);发布要求 readiness 报告通过、Brief 已确认、来源引用能冻结、无未处理任务,最终以 CAS(比较改编根 revision + activeSourceManifestHash)写入发布(release.ts:33-97)——并发修改下发布失败而非覆盖。showcase 的 release-evidence.json 记录 version、immutable:true、contentHash、逐文件 sha256。

### 交互模式专题

- **进度保存四道防线**:①编辑串行落库+同键写排队;②导航/生成前强制 flush,失败即阻断下游;③每 5 分钟自动快照+可选 Gist;④启动期申请 persistent storage。另有 beforeunload 兜底。
- **误操作保护**:高危操作统一走 `requireBackupBefore`(删项目、删世界组、启用多世界、覆盖式导入、还原快照等"不可逆"操作,三选一:立即备份后继续/声明已备份继续/取消,require-backup-before.ts:1-34);删除二次确认带影响范围说明;候选过期拦截;发布 CAS 失败拒绝覆盖。
- **UI 成熟度**:ui-preview/ 199 个"已确认样式"示例页即导航事实源,且诚实声明"示例中的『已保存』『已发布』等状态不代表真实业务能力"(ui-preview/README.md:4,11);抽查 aria-label/role 密度高(HomePage 7 处、AdventureGamePlayer 20 处)。
- **文案质量是突出资产**:统一人称与语感贯穿全仓——「潮汐迟到了十三分钟。/而这座城,正在忘记你的名字。」(MistHarborPage.tsx:114-118);空态把功能写成叙事(「这里将留下你的故事」「故事还在等你」);错误文案面向用户而非系统。
- **i18n 真实边界**:自研 i18n 模块存在(zh-CN+en)但注释自认"框架预留……项目当前无真实多语言需求"(i18n/index.ts:1-3);全仓 grep `useTranslation` 命中 1 个文件(模块自身),**0 个组件使用**——整个界面为硬编码中文。九语言 README 是文档层努力,产品 UI 当前是中文单语产品。

### 「写出故事,也走进故事」如何落地(README.md:7 即全站 slogan)

「写出故事」一侧已闭环(23 步工作台全链);「走进故事」用同一套底座交付:游玩即消费不可变 productRelease。四条"写→玩"桥梁在代码里可见:①存档绑定 releaseId;②玩家→作者反向通道(查看原稿);③读者→作者转化(示例库「创建体验副本」把内置文本变为自己可编辑的项目,ExampleLibrary.tsx:42-45);④首页同屏并列创作入口与作品入口。边界诚实是该口号的可信度来源(预写作品、开发中标注、示例声明、同机交接不提供秘密保护)。

**旅程相关风险(推断)**:单浏览器单副本;首次玩《雾港》走完整生产线不是秒开;中文单语+硬编码文案散布约 358 个组件文件;i18n 扩展是大工程;public/ 114MB 媒资随包分发,在线版用户流量成本存在。

---

## 四、架构与技术栈

### 总体组织原则:多产品 × 单底座 × 三注册表

这不是按功能堆叠的单体,而是 AGENTS.md:10-23 明文声明并在代码里落地的「多产品组合 + 共享工程底座」:六个上层产品(跑团/角色聊天/AI 小镇/文字冒险/AVG/文字开放世界)只读引用冻结的世界版本,运行结果禁止自动回写世界引擎(AGENTS.md:17-19)。docs/ARCHITECTURE.md:37-95 用 mermaid 画出分层:S1 世界封存 → S2 产品定向 → S3 产品执行。

「为什么这么组织」写在组织方式本身:本地优先纯前端应用一旦允许组件随手写库、随手拼 prompt 上下文,用户数据生命周期就会失控。所以把三件事收口成三个单一事实源:

1. **`CONTEXT_SOURCES` + `assembleContext()`** —— AI 读什么(context-sources.ts,3343 行,注册 132 个上下文源);
2. **`FIELD_REGISTRY` + `AdoptionSchema` + `adopt()`** —— AI 可以正式写什么(field-registry.ts 799 行、adoption-schema.ts 1049 行、adopt.ts 837 行);
3. **`PROJECT_TABLES`** —— 全部表的导出/导入/删除/迁移/作用域/引用重映射生命周期(project-tables.ts 2152 行)。

这三份注册表是启动硬门:main.tsx:46-51 在渲染任何 UI 之前先校验,任一失败整个应用停在错误页。validate.ts:24-287 做双向核对(Dexie 实际表 ↔ PROJECT_TABLES 互查、外键、重复、成环、owner 归属)。lifecycle.ts:1-245 从 PROJECT_TABLES 派生全部事务表集合,文件头注释明言"禁止在 Store 或 service 中维护第二份手写清单"。

### 依赖方向与机器门禁

scripts/check-architecture.mjs(2373 行)是 TypeScript AST 级架构 lint,实测含 286 处 `violations.push`、约 110 个命名规则标签,关键条目:UI 层禁止 `db.xxx.add/update/delete` 必须走 adopt() 或 store action(:98-110);组件禁止手挑旧 builder 必须走 assembleContext(:113-124);lib 内 AI 写回必须走 adopt() 或已登记入口(:260-325);UI 禁止导入底层 chat/streamChat,必须进 FormalAIEntry 集中执行器(:791-794);上层产品只能依赖世界中立协议、零物理世界表(:787、1466 起)。文件头自述"自动执行 CLAUDE.md 的三注册表铁律……让屎山无法复发"(:2-5)。

**实测到的方向偏差(事实,非文档宣称)**:lib → stores 反向导入 60 个文件(最集中是 stores/ai-config 35 处与 stores/prompt 27 处,例如三注册表本尊 context-sources.ts:14 就 import useAIConfigStore——模型配置是运行时用户设置,Zustand store 被当作全局配置单例使用);stores → lib 49 个文件。即真实方向是 components → stores ⇄ lib → db,架构门禁管的是"写库路径、AI 路径、世界协议"三类关键边界,而不是严格单向依赖。

### 分层与共享边界

实测规模:src 共 1373 个 .ts/.tsx;src/lib 75 个目录、958 个文件;src/components 330 个文件。src/lib 按文件数排序的大域:open-world 142、agent 123、types 80、ai 73、ttrpg 63、evals 44、product-production 43。分层(ARCHITECTURE.md:115-125):产品 UI → Workspace/Work/Scope → 产品应用服务 → Agent/Skill → Durable Harness → Context Gateway/记忆 → 三注册表 → 数据。

**共享层(禁止复制)**:三注册表与 db;AI 接入(lib/ai/adapters 25 个任务适配器;lib/agent/run 约 70 个 `*-durable.ts`);产品生产设施 lib/product-production/(43 文件,production-executor.ts 10904 行是全仓最大文件);product/runtime-core.ts 自述"Product-neutral session, event-log, checkpoint and projection infrastructure";世界出口 world-release-client + describe/search/read 协议;PRODUCT_CATALOG_V1 冻结 14 个产品条目(实测计数,见第二章),catalog 校验强制每个条目有成熟度边界说明。

**产品自有层(有意重复,属设计决定)**:六个上层产品各自拥有 lib/ttrpg(63)、lib/open-world(142)、lib/adventure(18)等;各自的 runtime-api.ts 是薄再导出壳("共享内核 + 产品命令面");各自有 harness、authoring-contract、六个独立 player store。

**结构性重复(值得注意)**:production-brief.ts 与 production-compiler.ts 只在 adventure 和 ttrpg 各有一份——推断是同一条生产管线的两份平行实现,尚未(或有意不)沉到共享层;剧本/漫画/短篇三个改编产品各自有形状雷同的 contracts/production/release/renderers/service 文件组,只共享底层媒资 blob 存储。节点模式对长篇的复用是正面案例:不复制生成/记忆/数据体系,而是把节点动作绑定到与分步骤长篇完全相同的 skillId,通用生成被降级为 experimental-draft、candidate-only(domain-action-registry.ts:26-31)。

### 状态管理、路由、样式

Zustand 5 模式是"store = Dexie 表的 UI 投影 + action",重复样板被工厂收敛(createProjectSingletonStore,_factories.ts:67-166)。react-router 8 + basename="/storyforge/",21 个页面组件全部 lazy() 按路由分块;路由壳很薄,WorkspacePage 连续 30+ 个 lazy 挂领域面板。样式:Tailwind 3 但颜色/阴影全部映射到 CSS 变量,14 套皮肤以 `:root[data-theme=...]` 覆盖同一批变量实现(themes.css 907 行)——换肤只换变量、工具类不动,这是 14 套皮肤低成本并存的原因。

### 构建与质量门

vite.config.ts(263 行):base=/storyforge/;dev 期 13 家 LLM 供应商 CORS 代理(:162-242);PWA workbox 预缓存上限放宽到 5MiB(注释原因 pdf.js+mammoth);manualChunks 按真实路径归组 vendor 并注释"排除回调 runtime-core 的文件以保持 chunk 图无环";strictPort 防端口漂移。tsconfig strict 全开、src 内 0 处 @ts-ignore,但 **include 仅 src——tests/ 和 scripts/ 完全不在 tsc 检查范围**。eslint 扁平配置零 warning 基线,`no-explicit-any` 显式 off 并注释理由。`npm run ci` 实测串联 **26 道门**(本次汇总以 `node -e` 解析 package.json ci 脚本计 `&&` 分段数=26;早期摸底材料称"约 25 道",以实测为准):required-tables → ai-manual → ai-entry-registry → architecture → 9 个 text-open-world 专项检查 → source-reachability → docs → roadmap → agent-context/freshness → canon-coverage → project-metrics → dependencies → lint → tsc → coverage → build → bundle-size。

测试:tests/regression 740 个文件(本次汇总实测 `find`);tests/e2e **57 个 .spec.ts**(本次实测 `ls tests/e2e/*.spec.ts | wc -l` = 57,顶层共 58 个条目;摸底材料所称"64 个 e2e spec"与另一材料的"递归 find 64 个文件(含子目录 helper)"均为口径差异,以 57 spec 为准);vitest 覆盖率只统计核心逻辑层(registry/db/export/import/ai),UI 显式排除——"高门槛给注册表、UI 交给 E2E"的取舍在注释里写明(vitest.config.ts:37-39、63-65)。

**结论**:组织方式是治理目标的空间投影——(1)本地优先+无后端 ⇒ 数据生命周期必须机器可推导;(2)AI 直连用户模型 ⇒ 输出必须候选化;(3)多产品并行 ⇒ 所有权边界前置到目录与 catalog;(4)防"屎山复发"是显式目标。代价也清晰:lib→stores 双向渗透、个别产品平行管线未收敛、i18n 预留未用、巨型文件集中共享层复杂度(executor 10904 行、skill-registry 5470 行)。

---

## 五、数据层与本地优先

### 1. IndexedDB 封装:Dexie 4 + 自研治理层

底层是 Dexie 4(package.json:74 `"dexie": "^4.0.11"`),真正的工程投入在上层「三注册表」治理层——project-tables.ts:1-13 声明 PROJECT_TABLES 是全部 Dexie 表元信息的单一事实源,"禁止在该注册表之外手写第二份表清单"。

**表数量勘误**:数据层方向材料称"schema v10,共 126 张表(src/lib/db/schema.ts:126-127)"。本次汇总实测:awk 统计 schema.ts 中 STORYFORGE_STORES_V1..V10 常量展开后的唯一表名 = **123**,ensure-schema.ts 的 REQUIRED_TABLES 数组元素 = **123**,docs/ARCHITECTURE.md:106-107 亦写"v10 / 123 张 required tables"。schema.ts:126-127 实际是数据库名与版本常量,并非表计数注释。**判为该方向材料的推导误差,以 123 为准**(此差异不改变任何结论)。

- **迁移策略**:append-only 的声明式 schema,构造函数逐版本 version(1)→version(10),每个 V2-V9 常量注释为"保留作为当时的精确迁移步骤";迁移只新增表/索引,没有数据内容变换。有跨分支并轨实例:v8/v9 时 chat 分支也发过一版 v8 schema,v9/v10 桥接保留 `chatAuthoringDrafts` 避免丢表(schema.ts:434-437)。
- **启动硬门**:`openCurrentSchema()` 校验代码声明表集合与实际打开的库完全一致,不符就关闭连接并抛错(ensure-schema.ts:149-164);bootstrap 失败则整页替换为错误屏。**不存在静默半迁移的库,旧库直接拒绝启动**。CI 第一道门 check:required-tables 用静态解析比对 schema.ts 表常量与 REQUIRED_TABLES(check-required-tables.mjs:17-31)。
- **两个刻意不入主库的存储**:`storyforge-fsa`(独立 IndexedDB,原生 API)只存 File System Access 目录句柄,"刻意不进 Dexie 主库/三注册表——它是基础设施,不是项目数据"(folder-handle-store.ts:1-11);localStorage 存主题与 AI 配置(provider/model/Key),是设备级设置,不进项目导出。

### 2. 核心数据建模

权威依据 docs/DATA-GOVERNANCE.md:6-8,43-49:每条持久化记录必须能回答 projectId、worldId/worldGroupId、workId 三层归属。Project 是"本地工作区壳"(只保存 workspaceUid、workspacePurpose、活动指针;"作品标题等内容只属于 Work,禁止在这里镜像",types/project.ts:113-133);World 是世界根(identityKind、稳定 code、currentVersion);Work 是作品根,kind 涵盖 novel/screenplay/comic/motion-drama/avg/ttrpg/ai-town/character-interaction。世界冻结为不可变版本:worldRevisions(链式 parentRevisionId)与 worldReleases(contentHash、version)。

章节/角色/实体:OutlineNode 树(卷/篇章/故事块/章节)与 Chapter(挂 outlineNodeId,content 为 HTML,含摘要来源正文哈希、连续性 handoff 等派生证据字段);**角色身份世界所有,作品只挂绑定**(workCharacterBindings 唯一索引 `&[workId+characterId]`,"不复制或修改身份",world-ownership.ts:80-88);实体/设定走 codex 两表 + 事实账本表(temporalFacts、knowledgeLedger 等)。

主键与关联:本地关联全部是裸数值 ID,**IndexedDB 层没有外键约束**;引用完整性靠 PROJECT_TABLES 每张表的 refs 声明(cascade/setNull/indirect/blob-owner 四类)。唯一性用 Dexie `&` 复合索引实现。每次读写经 workspace/scope.ts 的 assertRecordInScope 校验归属。**AI 写入唯一入口**:`adopt()` 自称"当前架构唯一的结构化采纳入口"(adopt.ts:1),正文采纳还会在同一写边界把依赖该章的 narrativeSummaryNodes 标记 stale——保证"模型输出先成候选、作者确认后才写库"在数据层有强制入口。

### 3. 备份、导入导出与项目文件格式

- **导出格式(ProjectExportData v14)**:导出引擎由注册表派生,遍历 exportable 表,把本地数值外键替换为 `_xxxExportId` 便携引用、媒资二进制转 base64;导出前 fail-closed 校验产品运行树完整性(事件序号连续、release 哈希一致、会话分支 lineage 可重放),防止把损坏数据导出成备份(registry-export.ts:42-200)。
- **导入是"只建新、不覆盖"**:入口先在事务外跑 `assertTrustedProjectBackup` 预检——"只接受与当前架构完全一致的备份,不执行升级或缺表补空",只认 v14、逐表精确字段闭集,未知/缺失字段直接报错(backup-trust.ts:1-9,103-112);然后单事务内按依赖拓扑序重建全部表,分配**新 projectId**,项目名固定追加"(导入)"(registry-import.ts:1538-1570)。信任边界是"严格拒绝"而非"尽力兼容",fail-closed 方向正确。
- **快照体系(四层)**:①库内快照(snapshots 表存整个项目的导出 JSON 字符串;每 5 分钟自动一张、每项目最多 20 张 auto,手动快照永不清理;恢复=JSON.parse 后走同一个 importProjectJSON,即**恢复为新项目**);②完整 JSON 文件导出;③本地文件夹绑定(File System Access API,写入"必须位于明确的用户手势内;MEMORY-0 禁止页面进入、授权恢复或定时器调用",folder-backup.ts:99-115)+ GitHub Gist 私有备份;④**记忆工作区(人可读文件投影)**——把可编辑表投影成 YAML/Markdown 同步到绑定文件夹:同步前写 pending.json 事务标记,覆盖前把旧内容存进 history/,写完逐文件回读比对 canonicalHash;冲突按三方哈希分类为八类并映射到不同动作,文件侧改动只能作为"采用候选"经作者确认回库,不是自动覆盖(workspace-projection.ts:1297-1372,862-902)。
- **《雾港》的数据组织**:内置作品不是打包的数据库文件,而是构建期编译进 bundle 的 TS 源码常量;首次点进时由用户触发的 install 流程在用户本地库里真实建数据(建 Project/World/Work 行、经 governed adopt 播种、发布 WorldRelease、走产品生产管线产出不可变 ProductRelease)。
- **可分发产品包格式**:ProductDistributionBundleV2 = {schema, version, productRelease:{contentHash, manifest}, sourceWorld:{contentHash}, media:[{asset, dataBase64}], bundleHash},"源世界只是 provenance,包绝不内嵌/重建/解引用 WorldRelease 表"(distribution-bundle.ts:40-56)。仓库里 58MB 的 tidewake-town release.storyforge-product.json 实测就是该格式。

### 4. 性能、冲突与多标签页一致性

- **媒资双后端 + 内容寻址**:≤8MiB 的 blob 存 IndexedDB 行内,更大的走 OPFS(路径 storyforge/media/v1/work-\<id\>/\<sha256\>),单对象上限 100MiB;写前配额检查,同 workId+contentHash 已存在则复用并重验哈希,读取时校验字节数 + SHA-256,不符即标 corrupt 并抛错(media-blob-store.ts)。
- **大文档导入分块**:chunker 切块后逐块落库,worldview 追加去重、角色跨块重名合并(chunk-writer.ts)。
- **多标签页一致性整体结论:没有全局跨标签状态同步,靠"唯一索引作权威 + 窄场景显式协调"**。49 个 Zustand store 是每个标签页各自的内存副本,未发现任何 `db.on('versionchange')`/`onblocked` 处理(全仓 grep 无结果)。两个标签页同时编辑同一章是**最后写入胜**:updateChapter 直接 db.chapters.update,没有版本号乐观锁,coordinatePendingEditV1 只做页内按 key 串行化。跨标签的权威机制是 IndexedDB 唯一复合索引(event-store.ts:88-92 注释直说"同标签页变更串行化;IndexedDB 的唯一 sequence 索引仍是跨标签权威");开放世界命令幂等靠 `&[sessionId+commandId]`,请求结果未知时拒绝重发、强制走核对恢复流程;Web Locks API 串行化跨标签临界区(雾港/盐脊安装、跑团 KP 协调、社区游戏开局)。

### 5. 数据丢失风险点

**已建立的防线**(均代码核实):高危操作强制备份红线 requireBackupBefore;批量改写先快照(全文替换/实体重命名/对比润色);导入/恢复永不覆盖;媒资 GC 两阶段且保守;文件同步永不静默覆盖;全应用源码 grep 不到 indexedDB.deleteDatabase(无"一键清库"功能)。

**残余风险**(代码指出,标注推断):①删大纲节点=一次性 confirm 级联删正文,不走强制备份,兜底只有 5 分钟自动快照(OutlinePanel.tsx:458-475;与其自家 requireBackupBefore 红线防护等级不一致);②自动快照失败是静默的(定时器 catch 后仅 console.error,useAutoBackup.ts:27-29);③多标签页同章并发编辑无冲突提示(最后写入胜);④persist() 被拒时的驱逐面仍在(Chrome 按"使用度启发式"静默授予);⑤1.5s 防抖窗口内进程被杀会丢正文;⑥Gist 备份以用户 PAT 明文 Bearer 调用,无最小权限校验。

---

## 六、AI 能力与 Prompt 工程

### 0. 总体架构:一条传输出口 + 一张上下文注册表 + 一条候选管线

全部 AI 调用收敛到 src/lib/ai/client.ts 的三个函数:streamChat(流式,:311)、chat(非流式,:439)、chatWithImagesV1(视觉输入,:243)。所有 18 个 provider 用同一个 OpenAI 兼容请求构造器 buildRequest(client.ts:135-216)——连 Claude、Gemini 也走 OpenAI 兼容端点(proxy-endpoints.ts:14)。上面再套三层:任务路由(task-routing.ts)、正式入口注册表(ai-entry-registry.json,47 个条目)、durable 候选/采纳管线。

### 1. Provider 适配层

- **18 个 provider**(types/ai.ts:2-21):deepseek/openai/qwen/doubao/minimax/glm/wenxin/gemini/poe/kimi/claude/modelscope/nvidia/agnes/longcat/opencode/ollama/custom。差异只体现在请求体微调(GLM temperature 钳到 (0,1]、Poe 只传 model+messages、DeepSeek thinking 开关、6 家不传 stream_options)。
- **Key 存在与传输:明文,无加密**。勾选"记住"时 Key 以 JSON 明文写入 `localStorage['storyforge-ai-config']`(stores/ai-config.ts:29,263-274);不记住则放 sessionStorage;多套预设同样明文。全仓 grep `encrypt|AES|crypto.subtle` 在 stores/ai 层无任何命中。Key 只以 `Authorization: Bearer` 头从浏览器直发 provider。**日志防泄做得较认真**:请求日志 URL 只保留 protocol+host(logger.ts:58-66),Key 替换为 [REDACTED],日志只存内存 50 条不进 Dexie。
- **provider 能力矩阵 fail-closed**:provider-capabilities.ts:43-66 逐家记录 native tool calls 和 JSON mode 是否 supported/unverified/unsupported,默认 unverified 走严格文本解析;注释明确记录了 Agnes 宣称支持 response_format 但实测吐不出完整 JSON 的教训(:57-61)。矩阵是人工标注的契约证据,不是运行时探测。
- **代理是 dev-only**:vite.config.ts dev server 配 13 条 CORS 代理,生产无任何服务端中转(无 vercel.json/serverless 配置)。
- **任务路由**:按调用 category 前缀分类为 creation/extraction/analysis/review + 6 种 agent 角色,映射到用户预设的不同 preset(可给抽取任务配便宜模型),未分类回退全局。

### 2. Prompt 模板与上下文装配

- **模板组织**:系统内置提示词唯一入口 SYSTEM_PROMPT_SEEDS(源码 238 个 moduleKey 定义),运行时持久化进 Dexie promptTemplates 表,作者可编辑可回滚、可 per-template modelOverride。渲染引擎极简:`{{var}}` 替换 + 单层 `{{#if}}`(不支持嵌套),缺失变量置空并 warn;作者标记的好/坏示例作为 few-shot 追加(上限 3 好 2 反例,prompt-engine.ts:63-84)。
- **上下文来源注册表**:context-sources.ts 自称"AI 上下文读取源的唯一注册表",共 **132 个源**,每个声明 scope/layer(L0-L3)/budgetTokens/owner/读取函数。写作链关键源:世界观 L2 8000 tokens("放开字段级硬截断:核心设定完整注入");角色档案 L2 8000(主要角色全维度/次要一句话/NPC 仅名字);前文连续性四件套全部 `protectedFromTrim`——前驱原文尾部、连续性 handoff、前章计划对账、最近已验证摘要(context-sources.ts:2961-3006);多世界隔离:"禁止默认世界资料泄漏到其它世界"(context-builder.ts:302-308)。
- **预算双层裁剪 + 保护块 + 证据**:第一层 assembleContext——输入预算=模型窗口−输出预留−5%(拿不到模型 48K 兜底);每源按 budgetTokens 确定性截断(二分查找+显式"已按预算截断"标记),整请求超窗再按 L3→L2→L1 整层丢弃;atomic 源超预算直接抛错而非静默裁。装配产物带完整证据(每源 included/omitted/trimmed 状态、字符与 token 数、sha256、delivery)。第二层请求前兜底 trimMessagesToFit,但 `<<<STORYFORGE_CONTINUITY_CORE>>>` 包裹的连续性保护块不可丢弃——裁后校验,装不下直接抛错拒发(context-budget.ts:318-323);协议型调用可用 contextOverflowPolicy:'reject' 拒绝任何静默裁剪。Token 估算是纯启发式:**中文 1.5 token/字、其他 0.25 token/字符**(context-budget.ts:144-151)——对现代 tokenizer 明显偏高,会导致预算提前收缩、装得下的上下文被裁。

### 3. 流式、长文、重试与成本

- **流式**:手工解析 SSE;useAIStream 状态挂全局 session store——标签切换组件卸载时生成仍继续;delta 合帧 32ms 才 publish,防"provider 一次网络读吐几百个 delta 打爆 React 嵌套更新上限"。
- **长文本分段与续写**:正文生成是**单调用,不自动切段**,字数参数上限放开到所选模型最大输出。超长靠三件套:①chapter.continue 续写模式,只带已有正文**末尾 3000 字**+1600 字续写锚点(chapter-adapter.ts:141-171),完成后拼接采纳;②chapter.memory 单次结构化抽取"摘要+handoff"作跨章记忆,前章对账记录已完成/未完成目标、偏移、新增约束;③批量卷纲逐卷串行,把上一卷**候选**(未采纳)注入下一卷并显式标注"不是已采纳 Canon"。规模上限由 eval 门禁背书(long-form-scale-gate.ts 定义三档规模证据)。
- **重试**:传输层极窄——只有 streamChat 对 429/503 重试 2 次(2s/4s 线性退避);非流式 chat() 不做任何自动重试。**结构化输出修复管线**:8 步确定性归一化 + jsonrepair 库 + 至多一次修复调用,产物分 ready/usable-with-warnings/manual-repair/blocked 四档。Agent runner 有完整护栏:默认 8 步/8 工具/48K token,硬上限 15 步/20 工具/250K/4 次协议错误,工具调用签名去重实现 loop_detected。**候选/采纳是错误处理的最终兜底**:AI 输出一律先落 durable 候选(带源文本哈希、输出哈希、ContextManifest 哈希),作者确认后经 CAS 采纳;上下文陈旧抛 ProseCopilotStaleError 拒绝采纳。
- **成本控制**:每次调用按 category/provider/model/token 记入 Dexie aiUsageLog,费用按版本化价格目录正则匹配估算(USD→CNY 汇率 localStorage 默认 7.2);生产预检 fail-closed:"provider+model 对未过审就不给报价,不把通用估算冒充 provider 账单"(usage-log.ts:127-153)。价格表用 `/o1|o3/` 这类无锚点正则匹配模型名——新增模型名含子串即误配。

### 4. 多模态

- **视觉输入** chatWithImagesV1:1-12 张图、dataUrl 强校验、detail low/high 分别预留 300/1200 tokens、图片字节不进日志。
- **图像生成**:唯一通道 OpenAI 兼容 `/images/generations`,b64_json 或 HTTPS URL 回传;provider 必须是 openai/custom,默认模型 gpt-image-1。能力声明诚实到保守:`referenceImage:false、deterministicSeed:false、inpainting:false`——规格要求参考图/seed 时先报 warning,须作者显式确认"有限一致性"才继续。漫画候选生成流程很重:visualBible 未确认不生成、来源 stale 不生成、requestHash 全量哈希实现幂等复用(命中即 reuse 不再花钱)、返回后根/格 revision 变了候选不落库;权利声明前置 rights.source=provider-generated。
- **Voronoi 地图是聪明反例**:让 AI 只输出 MapGenConfig 参数(全部白名单校验),地图由本地确定性引擎渲染——AI 不画图,杜绝图像 API 依赖和不一致。
- **Embedding**:独立配置(换写作模型不影响向量),默认关闭、推荐本地 ollama+bge-m3"手稿不出本机";失败由调用方降级到关键词检索,向量带 `${provider}:${model}` 标签防跨模型混算。

### 5. 聪明与可疑的设计

**聪明的**:①连续性保护块+双层 fail-closed(把"上下文被静默吃掉"变成显式错误);②能力证据矩阵 fail-closed(把实测教训固化进矩阵);③AI 只出参数、引擎出图(Voronoi);④修复管线+候选采纳 CAS;⑤注册表化一切(入口/上下文源/工具/技能全在注册表中并有 CI 门);⑥大段领域知识直接写进 system prompt(历史地理学常识、网文情绪公式);⑦细节控(GLM temperature 钳位防 1210 错、Gemini 错误对象先解包、NVIDIA 冷启动 60s)。

**可疑的**:①Key 明文存储(localStorage 对任何 XSS 可读,本地优先的自觉取舍但应对用户明示);②token 估算常数粗糙(中文 1.5/字明显偏高,估算误差直接驱动裁剪决策,裁剪是真实数据丢失);③窗口/价格表靠子串正则硬编码,容易过时;④SSE 解析静默吞错(`JSON.parse` 失败 `catch {}` 忽略,坏 chunk 丢失无痕迹);⑤句级字符串隔离脆弱(按"未来计划/尚未发生/异世界档案"子串整句剔除,角色台词"这一切尚未发生"会被误删,chapter-adapter.ts:29-33);⑥"去 AI 味"让模型自评(可被提示注入也可被截断偏置,正文只取前 4000 字);⑦默认静默裁剪(创作类调用默认 trim 只 console.warn,普通作者看不到哪些上下文被裁掉);⑧CLAIM 与验证缺口(能力矩阵大量 unverified、模型 token 数照抄厂商宣传值,无运行时探测)。

---

## 七、核心机制深挖:互动叙事与改编流水线

> 注:该方向材料在漫画图像管线处截断(漫画线 Panel Plan 之后的漫剧素材线、跑团 KP 运行时内核等细节缺失,相关内容以遗留问题形式记入第十四章)。

StoryForge 最有辨识度的机制是一条贯穿的纪律:**候选 → 作者确认 → 冻结 → 哈希绑定 → 事件溯源运行**。世界引擎把小说已确认语义 Canon 显式派生为可版本化 WorldRelease;上层产品只能经哈希校验的 WorldReference 与 SourcePin 读取冻结来源;所有 AI 输出必须带作者审定状态才可落库;运行期是不可变 ProductRuntimePackage 之上的事件日志回放。

### 1. 世界引擎:数据模型与派生机制

- **语义注册表是唯一事实源**:哪些表属于"世界语义"、采用什么 Canon 策略,由 PROJECT_TABLES 逐表声明 `worldSemantic: { area, resourceKind, canonPolicy }`(project-tables.ts:561 起约 30 处)。两种 Canon 策略:`authoritative-table`(整表即正典)与 `confirmed-rows-only`(仅 status='confirmed' 行,如修炼进度、时间性事实、角色认知事件)。世界页面按 10 个能力域投影完成度(权重 foundation 0.2 最高、multi-world 0),readiness 三态。
- **派生:小说 → 世界草稿(显式、单向、可回滚)**:`deriveNovelToWorld` 前置校验来源;派生前捕获源工作区内容修订指纹,快照建完后再验证新鲜度,期间源变了就报"捕获期间源作品发生变化"——乐观并发控制(derivation.ts:75-89);用 importProjectJSON 导入成独立工作区再升格;写一条 WorldDerivationV1 溯源行(源 workspaceUid/workCode/修订向量/内容哈希);失败时经注册生命周期级联回滚。源作品永不被触碰,副本不跟随后续源编辑。
- **修订/发布:冻结快照 + 双重哈希**:`buildWorldSemanticSnapshot` 只取选中世界语义表里已确认 Canon 行,被排除行按状态归类计入统计;产物是 WorldReleaseManifestV3(dependencies 每表行数+contentHash、records、resourceCatalog、capabilityProfile、sourceManifest);`createWorldRevision` 在事务内**再取一次严格快照并与事务外快照比对**,内容在冻结期间变化则拒绝(releases.ts:414-419);`publishWorldRevision` 发布不可变 WorldRelease,UID 形如 `WR-{worldCode}-v{version}-{hash前24}` 且刻意排除本地行 ID——导出/导入重映射不改身份。
- **上层产品消费边界 WorldReference**:可移植哈希覆盖 worldCode/releaseUid/version/releaseHash/manifestIdentity/capabilityIdentity,校验时**故意不解引用本地记录 ID** 以保证导出后仍可验证(world-reference.ts:39-69);文字开放世界创建器对候选世界做就绪检查,不一致即 `world-release-drift`。

### 2. 文字开放世界的生成机制:P0→QA 编译拓扑

`TEXT_OPEN_WORLD_PRODUCTION_TASK_CONTRACTS_V1`(open-world/production-contract.ts:132-584)定义 28 个任务合同——生成一个可玩文字开放世界的完整编译器:P0 source-lock(确定性)冻结来源为可验证 SourcePin;P1 source-curation(6 次模型调用)形成清单/证据账本/显式缺口;P2 体验设计+玩法骨架;P3 故事架构(核心冲突/多结局合同);P4-P8 地区骨架/主线/故事线/叙事包/任务与六本目录;P8F 任务定稿;**P9 场景脚本(161 次模型调用预算,至多 159 场景+1 共享请求,3.6M 超时)**;P10 系统定稿;V1 确定性预检→V2 平衡/语义双评审→V3 确定性装配→QA 硬闸。每个模型任务自带 retryPolicy(transport/rate-limit 可重试,authorization/stale 不可)、stalePolicy(watches 多级哈希,传播 transitive-downstream,onChange 'pause-for-author')、失败 pause;写目标统一 productBuildArtifacts + adoptionExtension。发布是独立大闸:收集全部哈希组成 adoption intent,校验后产出 ProductRelease。

### 3. 小说→剧本→漫画改编流水线

- **来源钉住与新鲜度(共用底座)**:resolveAdaptationSourceManifest 把小说 Work 按四种选择模式切出规范章序的 AdaptationSourceUnit 列表,每个带稳定 sourceUnitKey 与 contentHash;inspectAdaptationFreshness 随时校验来源未变,变则所有下游候选 stale。
- **分析层(第一处人工介入)**:三类候选结构 SourceFact/CausalEdge/Decision 全部强制稳定 key、**禁止嵌入本地 ID**、逐字段 exact-keys 校验;人工介入点是显式契约:authorStatus 注释写明"由审阅 UI 提供,永不从模型输出解析"(analysis.ts:33-37);采纳需 expectedAdaptationRevision+sourceManifestVersion 的 CAS,且因果边只能引用已 confirmed 的事实。
- **剧本线(11 个 Agent 技能阶段)**:source-analysis→causal-graph→adaptation-brief→decision-pass→beat-sheet→scene-card→scene-draft→grounding-review→dramaturgy-review→targeted-rewrite;顺序门:Beat 采纳要求 Brief 已确认+存在已确认事实与决策;Scene Card 要求每 Beat 至少一卡、场号唯一;两类审查(grounding/dramaturgy)产出 ReviewIssue;定点改写只能处理该场当前版本的开放问题。完成检查器列 blocker:未决 AgentRun、上游未确认、场须 reviewed/locked、双审查 revision 未跟上、开放 critical/major 问题、预计时长偏离目标 >35%。发布再次检查 ready,冻结全部产物为 manifest(本地 ID 换成 sourceUnitKey),draftGuard 做发布 CAS;导出是确定性渲染器(Fountain/FDX XML/打印 HTML 三种,带自家往返解析器用于验证)。
- **漫画线**:Brief 确认→ComicScriptBeat→ComicPagePlan(**必须精确覆盖 chapterCount×targetPagesPerChapter 页**,顺序/页号/beatKeys 全校验)→视觉圣经 ComicGlobalVisualBible+ComicVisualSubject(删主体前须先清参考图)→Panel Plan(每页格数与显式 nextPanelKey 阅读链必须匹配,固定 negativePrompt 'no text, no letters, no speech balloons…')——*(材料在此截断)*。

### 4. 零模型调用的确定性编译:内置作品《雾港:失潮钟声》

把上述纪律走通为零模型调用链:18 节点/158 节拍/20 选择的静态 TS 剧本 → 世界预置 → 确定性生产管线(质量门硬编码校验 18/158/3 结局/17 张美术)→ 不可变 ProductRelease,以 AVG 和文字冒险两个版本发布。这证明"产品生产线"与"模型生成"是解耦的两层——同一套管线既能跑 AI 任务合同,也能跑纯确定性内容。

---

## 八、工程质量与安全

检查方式:全部为只读静态检查;两条"过时"判断辅以 npm 官网 web 搜索(2026-10)。未运行任何测试/构建/npm audit。

### 1. 测试体系

- **单测(vitest 2.1.9)**:文件数实测(find tests -type f)= 874:tests/regression 740、tests/e2e 64(递归口径,含 7 helpers;顶层 58 条目、57 个 .spec.ts——本次汇总已实测厘清,见第四章)、tests/registry 18、tests/canon 6、tests/acceptance 9(是 JSON 验收记录文件,非测试代码)。静态声明用例约 3,949 处(grep it(/test(/it.each,实际运行更多)。
- **覆盖内容**:regression 以 R-* 编号家族覆盖极广(OPEN-* 188 个面向文字开放世界);tests/registry 专测三注册表;tests/canon 测世界隔离。抽查用例直接在 fake-indexeddb/DOM 上构造 ReadableStream/Request 级行为测试,非快照式空转,质量较高。
- **覆盖率门(vitest.config.ts:43-79)**:仅针对核心逻辑层(registry/db/export/import/ai),全仓 lines 58%/branches 60%,registry 目录 75%/70%;UI 层、ai/client.ts、prompt-seeds 显式排除。门槛是"分层诚实"而非全仓高覆盖——UI 只靠 E2E。
- **E2E(Playwright chromium)**:57 个 spec、186 个用例,单 worker 串行、CI 重试 1 次;默认 CI 走 PLAYWRIGHT_FROZEN_WORKSPACE=1 伺服冻结快照而非 dev server。覆盖面:core-workflow、longform、screenplay、comic、motion-drama、ttrpg、text-open-world 全家桶(15 个)、memory-workspace、product-production-performance 等——主链产品和治理红线都有端到端防线。

### 2. CI 与类型/lint 严格度

CI(.github/workflows/ci.yml)17 个步骤:11 个自研 Node 检查器 → ESLint 零 warning → tsc --noEmit → 覆盖率测试 → 生产构建 → 体积预算 → Chromium 全套 e2e。另有 4 个 workflow:release(tag 触发,先校验 tag/package.json/changelog 一致)、deploy-docs(SSH+rsync 到腾讯云)、star-history(每 15 分钟刷 README 星史图)、traffic-archive(每日归档流量 CSV)。npm scripts 55 个,ci 串联 26 道门(本次实测,见第四章)。ESLint `--max-warnings=0` 全部 warn 变阻断,但 no-explicit-any off(src 内实测 142 处 as any),无 security 插件;55 处 eslint-disable。tsconfig strict 全开、src 内 0 处 @ts-ignore,但 **include 仅 src——tests/ 与 scripts/ 完全不在 tsc 检查范围**,测试代码类型从未被静态检查(推断:tests 由 vitest esbuild 转译)。

### 3. 治理文档

非常完整且互相咬合,远超同类开源项目:AGENTS.md(86 行,任务唯一自动加载入口,定义三注册表铁律、"main 直接进入生产部署,没有 staging")、CLAUDE.md(195 行工程宪法 2.4.0,规则具体可执行)、CONTRIBUTING.md(76 行,含"不写『CI 全绿』的诚实要求")、SECURITY.md(29 行,要素齐全,无赏金/SLA)、CHANGELOG.md(1,413 行,开头自我声明"只保留历史表述,不定义当前状态";版本停在 3.9.1)。

### 4. 依赖健康度

直接依赖 25 + dev 20,lockfile 993 个包,依赖面克制(无 UI 组件库、无后端)。关键锁定版本:react 19.2.8、react-router 8.3.1、zustand 5.0.15、dexie 4.4.5、typescript 5.9.3、eslint 9.39.5、@playwright/test 1.62.1、vite 6.4.3、vitest 2.1.9、tailwindcss 3.4.19。**过时项**(npm 官网 web 搜索,2026-10):vitest 2.x 落后两个大版本(最新 5.0.3);vite 6.x 落后两个大版本(最新 8.3.1);tailwindcss 3.x(社区已有 v4)。重量级依赖处理得当:pdfjs-dist 与 mammoth 仅动态 import 按需加载,不进首屏,并设 PDF 20MB/DOCX 10MB 上限。

### 5. 安全面

- **发现 1 个真实的未转义 HTML 注入点**:src/components/tools/GlobalReplacePanel.tsx:664-668 用 dangerouslySetInnerHTML 渲染 `match.snippet.replace(new RegExp(query,'gi'), ...)` 的高亮结果,snippet 是未转义的章节正文原文切片(chapter.content 为富文本 HTML)。章节内容可经项目 JSON 备份导入进入,故这是**存储型 XSS 链**:恶意备份 → 导入 → 作者打开「全局替换」搜索命中 → 任意 HTML(如 `<img onerror>`)在应用源内执行,可触及 IndexedDB 手稿与 localStorage 中的 API Key。附带缺陷:`new RegExp(query)` 未转义用户输入,含正则元字符的查询会在 render 期抛错。无任何测试覆盖该组件;index.html 与 vite.config.ts 均未设 CSP,仓库亦无 vercel.json 自定义头,无纵深缓解。
- **其余 7 处 dangerouslySetInnerHTML 全部有防线**:AI 生成 SVG 经 DOMParser 白名单清洗(sanitize-svg.ts:21-77,有 R-svg-xss 回归);漫画 SVG 内部所有用户/AI 文本经 escapeXml;产品分发包导入也复用 sanitize 并上报删除内容。`.innerHTML =` 两处仅用于文本提取,不回写 DOM,低风险。marked 15 产出的 HTML 未直连 innerHTML(经 TipTap/ProseMirror schema 解析渲染),但 marked 本身不消毒——若未来有人把它接进 dangerouslySetInnerHTML 会立即形成注入面。
- **API Key 存储**:明文 localStorage(见第六章)。好的一面:AI 日志对 Key 主动脱敏;项目备份不含 Key(AI 配置不在 Dexie 表内)。
- **导入解析信任边界(最强的部分)**:inspectProjectBackup 预检只接受与当前契约完全一致的备份(版本必须等于 v14、字段白名单、不升级、不缺表补空);再进 registry-import.ts(2,004 行)按拓扑逐行导入,必填外键缺失整体回滚,域对象逐类合同校验。残余风险:**预检与合同都不消毒 HTML 字段内容**,chapter.content 按原样入库——与 GlobalReplacePanel 注入点正好构成完整链。

**未运行/未验证项**:未运行任何 vitest/playwright/tsc/eslint/npm audit/构建;测试通过率、覆盖率门槛是否真达标、audit 实时结果均未验证,上文只报告门禁的存在与配置;用例数为静态 grep 计数;依赖"落后版本"引用 web 搜索快照;部署侧(Vercel 平台是否注入 CSP 头)无法从仓库判定。

---

## 九、活跃度、社区与商业化

数据口径:git 统计在本地完整克隆执行(非浅克隆,历史完整);GitHub 数据用 gh api(2026-10-01);B站/知乎页面同日经 WebFetch/web_reader 抓取。

### 1. Git 活跃度

总量 1663 提交,跨度 2026-04-13 → 2026-10-01;人工提交 1448。月度节奏:04(半月)11 → 05 112 → 06 351 → 07 235 → 08 141 → **09 598**(峰值)。注意 8 月全量口径 283 看似平稳,但其中 142 个是 bot(流量归档 + star-history 刷新)。近三个月波动大(235→141→598)。作者分布:yuanbw2025(两个邮箱身份)787+651=1438,占人工提交 99.3%;外部贡献者仅 francswiftsword-ui(6)与 Terry/hexawing(4)。近期 commit 主题:文字开放世界与文字冒险主线整合、longform Agent 体验修复、28 条原创提示词模板库、新版 UI 十四套主题、九语言 README。工作流是自开分支自合 PR:81 个 PR、55 个合并、57 个本人发起——PR 门禁主要服务单人流程。**结论:极强单人产出、单点依赖(bus factor=1)**。

### 2. GitHub 指标与增长

800 stars、135 forks(gh api,2026-10-01)。Star 增长:仓库每 15 分钟自动刷新 star-history SVG,本次 curl 该 SVG 并解析曲线坐标反推(近似值):2026-06-01 ≈75 → 07-01 ≈180 → 08-01 ≈440 → 09-01 ≈610 → 10-01 = 799/800。约 5 个月 0→800,近两月约 150-190/月,增速未见衰减。站内流量(官方 Traffic API 口径):views 月度 6 月 2745 → 7 月 11086 → 8 月 11356 → 9 月 8242;clones 6 月 2972 → 8 月 5639 → 9 月 3884。(另一材料引用 9-30 单日 views 193/独立 91——与月度合计为不同口径,非矛盾。)

**Release 与下载**:12 个 tag,但 v3.7.4(2026-07-03)之后所有 release 无二进制附件;最新 release v3.9.1 停在 2026-08-04;CHANGELOG.md:18 自述"应用语义版本仍保持 3.9.1;正式版本号与 Release tag 将在下一次独立发版流程中决定"——即 5-9 月大量功能进主干但**发版流程停摆两个月**。release 资产累计下载合计约 704 次(v3.7.2 453、v3.7.4 144 等)——真实安装用户规模为数百量级。

**Issues/PR 参与度**:历史 issue 19 个,16 个来自 13 位外部用户;当前 open 8 个中 6 个为真 issue,较新的外部 issue 回复少(#101 0 评论)。外部 PR 21 个,仅 3 个被合并。**外部参与以提 issue 为主,代码贡献转化率低;维护者对 issue 的响应不均衡**(部分 bug issue 五天内关闭,#56/#30/#101 长期无回复)。

### 3. 社区运营

官方渠道:B站视频教程(播放 **3.9 万**、点赞 1281、收藏 3625,发布 2026-06-26,唯一视频教程)、知乎专栏(2026-05-15,评论 167,赞同数元数据不可见)、QQ 群 1082374587、开发者个人主页与文档站。九语言 README(README.md:30 自述"界面及关联文档的语言覆盖请以实际内容为准")。运营材料与基建:showcase/ 用真实成品代替营销素材;website-docs/ 含反馈中心("不要求国内用户跳转 GitHub");文档站部署到**腾讯云自有服务器**(deploy-docs.yml:53),反馈表单 POST 自有 API——产品虽是纯前端,开发者自费维护了产品之外的服务端。社区健康文件:CONTRIBUTING/SECURITY/3 个 issue template 齐备;**无 CODE_OF_CONDUCT.md、无 FUNDING.yml**。外部讨论面:web 搜索仅见 GitHub、B站、知乎与一条 Threads 提及;未发现 linux.do/V2EX/Reddit 独立讨论帖。

### 4. 商业化与可持续性

**收入现状:只有自愿赞助**。README.md:527-534 爱发电收款码(无超链接、无金额/赞助人数披露),声明"全部功能与后续更新不会因是否赞助而有区别"。官方路线图明确推迟商业化:PROJECT-MASTER-CHARTER.md:48"网站、账户、社区、市场、平台与商业化属于核心产品能力稳定后的后续阶段";roadmap 阶段 F 两项均为 **LATER**;路线图主干当前在阶段 E——仍在横向扩张而非收敛。

**可持续性评估**——正面:工程纪律罕见地强,9 月仍以 598 个人工提交高速迭代,star 增速健康。风险:①单点依赖(99% 提交出自一人,一人停更即项目停更);②收入与成本不匹配的结构性缺口(需自费腾讯云+反馈服务,大模型订阅靠赞助,商业化被无限期后置);③发版停摆(下载通道实际冻结,与 star 增长脱节);④外部贡献合并率低(21 个外部 PR 收 3 个),社区暂未形成接力梯队;⑤路线图持续加产品线,单人产能与范围扩张的张力会随时间放大。

### 5. 对标/竞品提及

README 与产品契约文档不点名对标。唯一系统性竞品研究在 docs/audits/NOVEL-PROMPT-CRAFT-20260927.md:19-28,逐项列出公开来源与"熔炉的取舍":蛙蛙写作(按具体问题拆工具)、Sudowrite(选区级定向修改、场景卡驱动初稿)、Novelcrafter(去 AI 味方法、术语/选区替换/可克隆提示词)、Foreverse 续写控制、EQ-bench 评估思路、B站提示词教程。即作者实际对标的是蛙蛙写作、Sudowrite、Novelcrafter 等 AI 写作产品的公开方法论(声明未复制付费内容);同类开源工具(SillyTavern 等)未被提及。

**未能获取的数据**:爱发电赞助金额/人数(页面需登录);知乎赞同数(直接抓取 403);QQ 群人数与活跃度(无公开口径);star 曲线为 SVG 坐标反推的近似值;issue 响应时长未逐一统计。

---

## 十、对比 ai-writing-assist(一):功能矩阵

**口径**:"NC"= 本项目 NovelCraft(服务端架构,证据为本工作区实读 path:line);"SF"= StoryForge(SF 证据分"SF 抽查"= 对比分析师亲自核实,与"调研材料"= 转引,抽查过的条目均与克隆一致)。本次只读,未运行任何一方代码。覆盖度三档:无/基础/成熟,按工程实现与实物证据评定,不按宣传口径。

| 功能域 | NC 覆盖度 | SF 覆盖度 | 深度差异要点 |
|---|---|---|---|
| 1. 长篇/短篇创作 | 长篇=成熟;短篇=无 | 双成熟 | NC 只有长篇一条写作主线;SF 长短篇分列两条正式产品线,短篇有独立 5k–25k 目标与发布闭环 |
| 2. 大纲与章节管理 | 成熟 | 成熟 | NC 走"不可变修订+Scene 级结构"(全版本化);SF 走"画布式节点树";粒度类似但 NC 版本化更硬 |
| 3. 角色卡 | 成熟 | 成熟 | NC 差异点=角色知识边界(知道/不知道/误解);SF 差异点=四档角色分层+漫画视觉圣经+角色聊天冻结档案 |
| 4. 世界观与知识库 | 成熟 | 成熟 | NC=带来源的事实账本+复核工作台+统一地图;SF=世界观五模块+事实库+世界引擎(不可变 WorldRelease、显式派生)——SF 把设定做成可分发资产 |
| 5. AI 审校与一致性 | 成熟(治理型) | 成熟(工具型) | NC 约束"AI 不能写什么"(发布冲突检查/语义审读/批注定向修订/证据编译);SF 优化"AI 写得怎么样"(25 个任务适配器/连续性保护块/章后影响修订) |
| 6. 角色扮演/互动体验 | 成熟(单路径) | 基础(六产品全 preview) | NC 的 RP 是正式路径(不可变消息树/分支/看海循环/流式恢复);SF 铺了六条线但 catalog 全部 preview、自认未验收,仅内置《雾港》预写作品可零 API 游玩 |
| 7. 剧本与漫画改编 | 无 | 成熟 | NC 无任何改编产品线(代码内"剧本"是 Scene 对白脚本,非改编);SF 有剧本(十步+双审查+Fountain/FDX)与漫画(十二步+页格排字+CBZ/PDF)两条 released 线 |
| 8. 导出与发布 | 基础 | 成熟 | NC=正文 txt/md/md-zip+RP 旅程 Markdown,发布是应用内稿件状态;SF=全产品不可变 release(contentHash)+Fountain/FDX/PDF/CBZ/分发包——可携带、可哈希验证的成品资产 |
| 9. 备份恢复 | 基础(服务器代管) | 成熟(用户自持) | NC 靠 PostgreSQL+草稿检查点+任务恢复,无用户全量备份出口;SF 五层备份+fail-closed 导入预检+高危操作强制备份 |
| 10. 多设备与协同 | 基础(多设备天然,协同=AI) | 无~基础 | NC 账号+服务端=任意设备登录同一数据,协作为 AI 多角色实验;SF 无服务端,数据按浏览器隔离,跨设备仅手动 JSON/Gist,无多人协同 |

**分域关键证据**(摘):NC 正文承载 writing_drafts 按 chapter_index+version_number 唯一、带 content_hash 与发布冲突快照(backend/modules/writing/models.py:32-101);短篇无(全 backend/modules 无 short_novel 命中,project_kind 只有 author/interaction 两值)。NC 结构层 11 张表全部版本化(outline_state/models.py)。NC 角色知识边界 character_knowledge(world/models/character.py:148-160)是 SF 无对应表的建模。NC 证据编译=原文回读/hash 校验/可见性/确认快照;SF 的去 AI 味靠模型自评+前 4000 字截断。NC interaction 模块 10 张表、流式经持久化 offset 恢复(streaming.py:71-132)、"看海"为 heartbeat 驱动有界循环。SF 跑团《雾港:最后一盏灯》有 examples/ttrpg/ 可玩包。NC 导出仅 txt/md/md-zip 且按章序复核已采用版本哈希(writing/services.py:279-319)。

**双方功能盲区**——NC:无短篇/剧本/漫画/漫剧等形态化产品与视觉成品管线;无用户级全量备份/迁移出口;无玩法型互动;高级审校能力全部默认关闭、真实质量未验收;离线不可用;Prompt 全量是工程内置,用户仅在"高级生成工具"有限编辑。SF:无服务端(无账号、无跨设备同步、备份责任全在用户;Key 明文+1 个未转义注入点构成"手稿+Key 一锅端"链);无服务端长任务(生成依赖页面存活,无 worker 级断点续跑);六个互动产品与节点模式全部 preview、无一转正;一致性治理弱于 NC(无服务器级证据编译/可见性/授权确认快照,连续性靠 prompt 保护块与前端 stale 标记);版本号停滞、发版停摆;i18n 框架零采用。

---

## 十一、对比 ai-writing-assist(二):架构范式

两条路线的分野不在"谁更先进"而在**状态与计算放在哪里**。SF 把全部状态放进用户浏览器(IndexedDB+BYOK+无后端),换来零部署摩擦、真离线与数据主权;NC 把状态放进服务端(PostgreSQL+任务队列+worker+账户体系),换来可恢复长任务、服务端流式缓冲、加密 Key 托管与用量账本。

### 1. 数据归属与隐私

SF:数据主权在用户,托管责任也在用户——启动申请 persist() 防"整库被浏览器驱逐→用户表现为数据被重置"(main.tsx:24-43 注释,本次抽查核实);导入/恢复一律建新项目;隐私对面是安全面:Key 明文 localStorage(抽查核实 ai-config.ts:29),叠加 GlobalReplacePanel 注入点构成"手稿+Key 一锅端"链。NC:数据主权在运营者,但安全机制可集中建设——业务读写隔离 novel_id+owner 校验;**模型 Key 在服务端以 Fernet 信封加密落库**(backend/infrastructure/llm/secret_store.py:10-11,42;指纹用部署密钥 HMAC);公开演示是唯一匿名例外且收窄到"24 小时匿名 owner 只读固定 source revision、临时 DeepSeek Key 只留在当前 tab sessionStorage"(docs/00_整体设计.md:18-25)。判断:纯隐私叙事("我的手稿永不离开我的机器")只有 local-first 能讲;但对 XSS/设备失窃的抵抗力、密钥静态加密、集中备份演练是服务端的优势面。双方都是 BYOK,差别在 Key 交给谁保管。

### 2. 多端同步与多人协同

SF:结构上没有这两件事——无服务端即无同步通道;多标签页无全局状态同步,同章并发编辑是最后写入胜;跑团明确"公共联网多人尚未部署"(README.md:64)。NC:多端是架构免费赠品,协同是产品决定不做——单一 PostgreSQL 即多端一致源;断线续流靠服务端持久化 offset(SSE 重连按 persisted_offset 补发或 reset,backend/modules/interaction/streaming.py:76-147)。但注意两处**产品层面的收窄**:①ADR-0013 operation receipt 任务"只在发起页恢复;不新增全局任务中心"(docs/00_整体设计.md:146-149)——服务端架构完全允许全局任务中心,这是刻意不建;②"项目共享/多人协作权限"明确列入不做(docs/00_整体设计.md:352);ADR-0027 的"有限协作"是单宿主内最多三名并发 AI 成员,不是人类多用户。判断:多端同步服务端结构性胜出;多人协同双方都未交付,但 NC 的账户/owner 底座让"加人"是产品工程,SF 要先变成一个服务端项目。

### 3. 离线能力

SF 有真离线:PWA service worker 仅生产注册、ES2023 polyfill 兼容国产浏览器,写作阅读全程可用,AI 调用才需网络。NC 离线为零:前端无任何 service worker/PWA 配置(本次 grep frontend-console 应用源文件命中为空)。判断:离线是 local-first 独占能力;NC 唯一缓解是"弱网可用"(SSE offset 续传),完全离线写正文做不到。

### 4. 成本结构

SF:应用层边际成本≈0(生产是 Vercel 静态站),开发者唯一付费证据是自费腾讯云文档站+反馈 API;CORS 代理 dev-only 意味着 9/18 家供应商在在线版受限——成本转嫁给用户。NC:每个活跃用户都消耗服务器资源(PG+worker+MinIO+SearXNG+备份基建);并发治理是服务端职责(进程级 semaphore+provider 级 token bucket/熔断)。判断:规模化分发成本 SF 完胜;反向看,SF 把"保证可用性"的成本也转嫁给用户(数据自备份、CORS 自解决),NC 把责任收归运营者。

### 5. 部署与上手摩擦

SF:试用=打开一个 URL;本地版需 Node 24+git/npm;无 .env、无数据库、无迁移。NC:自托管是一条完整运维链(uv sync+npm ci+make db+migrate+Fernet 密钥+systemd+openresty;生产发布走固定 40 位 SHA 的 release.sh);公网已有体验入口(novel.zhh.se)——普通用户可零运维试用,摩擦只落在自托管者身上。判断:首次试用摩擦 SF 胜;但 SF 的版本困境说明"纯前端发版简单"并没有兑现为发版纪律。两条路线在 schema 演进上殊途同归地选择了 fail-closed(SF"版本不符直接拒绝启动"的硬门 vs NC Alembic 显式迁移+启动 schema guard)。

### 6. LLM Key 管理与计费

| 维度 | StoryForge | 本项目 |
| --- | --- | --- |
| 存储 | localStorage 明文(抽查核实) | Fernet `fernet-v1` 信封加密入库;等值比较用 HMAC 指纹 |
| 传输 | 浏览器直发,受 CORS 限制(9/18 家需 dev-only 代理) | 服务端出站,统一 egress |
| 泄漏面 | XSS→localStorage 全读(有真实注入点) | 服务器被攻破→信封+环境密钥;无浏览器暴露面 |
| 用量记账 | 仅本地 Dexie aiUsageLog+子串正则价格表 | AIRunEnvelopeV1 统一约束累计额度/deadline,"重试、恢复和 requeue 不重置账本";usage_unknown 显式建模,"未知用量不能被记录成零成本"(agent_runtime.py:108-231) |

判断:NC 的 Key 管理是"真保管"(加密、指纹、账本、未知态保留),SF 是"真放手"(运营者全程 blindness 是隐私优点也是保护真空)。NC 深度导入实测发现 token 截断问题并固化 32768 冻结预算——这类"跑真实请求→固化预算"的工程闭环依赖服务端可控出站,浏览器直连很难做严格。

### 7. 长任务:两条路线的根本分野

**SF:任务寿命=标签页寿命,durable 只保数据不保计算。** 传输层重试仅 streamChat 对 429/503 重试 2 次(抽查核实 client.ts:351-363);长管线靠"durable 候选+刷新后按源哈希恢复"补偿;开放世界 P9 场景脚本 161 次调用预算(抽查核实 production-contract.ts:442)——但这一切都发生在**一个前台标签页里**:用户关掉标签页,161 次调用即刻中断,持久化的是事件与候选,不是运行中的进程。跨标签协调靠 Web Locks 与唯一索引,无任何后台执行体。

**NC:任务寿命=worker 进程寿命,客户端只是观察者。** PostgreSQL 任务队列以 FOR UPDATE SKIP LOCKED 领取、lease 建立、attempt 自动重排队列、lease 栅栏下的 checkpoint 合并(lifecycle.py:968,995,654-668);独立 worker 常驻(backend/run_worker.py);关键设计是"任务开始时有权限"与"完成时仍有权写入"两次判断(README.md:166-171);演化管线把"provider 调用"与"数据库提交"分离:先耐久化采样结果,apply_frozen 重验 owner epoch 后短事务提交,已计费但未确认的响应保留 unknown 态而非当免费失败;60 章深度导入是确定性窗口计划+三个 LLM 阶段、冻结 32768 输出预算(backend/modules/imports/README.md:37-42)。

**上限对比**:local-first 的天花板=浏览器进程生命周期、IndexedDB 配额、单标签页内存、CORS 决定 provider 面、无调度无定时无后台——"用户必须盯着进度条"是结构性的。服务端的天花板=worker 池容量与服务器成本、运营复杂度;但可以无人值守跑小时级任务、跨用户并发治理、真实请求校准预算。**判断**:对"长文生成、批量导入、演化阅读"这类 NC 的核心负载,服务端不是锦上添花而是能力成立的前提——SF 的 P9 161 调用合同在浏览器里只能以"用户开着页等"的方式兑现,NC 同样规模的 60 章导入可以关掉页面跑完。反过来,SF 的"durable 候选+源哈希新鲜度+过期拒绝采纳"与 NC"返回时重验+冻结恢复"在语义上高度同构——**候选/确认/陈旧拦截这一层与范式无关,可移植;不可移植的是计算驻留地**。

### 8. 每种范式擅长什么

**local-first 擅长**(均有实物证据):零摩擦试用与分发、数据主权与离线、零边际服务器成本、"无服务端可攻破"的攻击面收缩。天花板:多端、多人、后台任务、集中检索、密钥保管、治理权限——每一样都需要先造一个后端。**服务端擅长**(NC 实物证据):可恢复长任务与流式续传、加密密钥托管与用量账本、pgvector 混合召回的索引规模与新鲜度、受控 Agent 的服务端冻结预算、固定 SHA 发布与备份演练。天花板:常驻成本、运营责任、离线缺失、"数据集中在一家"的信任门槛与合规面。**双方共同的自觉**:AI 输出一律先候选、作者确认才采纳、来源 hash 陈旧即拒绝——这是范式之上的共识层。

### 9. 对 NC:哪些场景被锁死/放大

**被锁死**:①离线写作(无 service worker,断网即不可用);②零账户零部署试用与隐私定位("数据永不离开本机"在服务端架构下是伪命题);③浏览器即全部的小工具场景。**被放大**:①无人值守长任务;②跨设备续写与断线恢复;③规模化检索(pgvector 对应 SF 需在 IndexedDB 自建检索层的上限);④密钥与预算治理;⑤未来的多用户/协作(账户与 owner 底座已在,加人类协作是产品决定而非重写)。**重要区分——"锁死"里有三样其实是产品选择而非架构限制**:全局任务中心、项目共享/多人权限(都是服务端架构随时可加而刻意不建)、离线(真锁死,但弱网已部分补偿)。给结论时不应把这三者混同为"服务端架构做不到"——前两者 NC 恰恰随时可加,SF 才是真的做不到。

---

## 十二、对比 ai-writing-assist(三):AI 管线与数据模型

两边 AI 管线是同一套治理哲学("模型输出先成候选、确认后才写正式资产")的两种工程化。SF 引用标【材料】的行号来自调研材料未逐行复核,其余为对比分析师亲读。

### 1. Prompt 模板组织与拼装

**SF:模板即数据,作者可改,引擎极简。** SYSTEM_PROMPT_SEEDS 唯一入口(238 个 moduleKey),运行时持久化进 Dexie,作者可编辑可回滚;渲染引擎只支持 `{{var}}`+单层 `{{#if}}`(prompt-engine.ts:1-40 亲读);system prompt 内嵌大段领域方法论。**NC:文件模板+内联 step 双轨,模板受开发期契约检查。** backend/prompts/ 只有 12 个 .md 静态模板,其余是代码内联 step;作者可编辑面极窄(仅世界生成中心的内置视角+项目级自定义模板,带运行时 validator);独有:backend/tools/prompt_contracts/ 开发期漂移检查——JSON 声明 prompt 字段、Pydantic schema、关键持久化映射、纯函数 probe,不执行真实 LLM;全局纪律:"项目不使用跨业务的全局共享 Prompt",正文与项目资料一律作为 fenced 不可信 user/context 数据注入(Prompt体系设计.md:690-697 亲读)。小结:SF 模板可玩性高但无防漂移门;NC 模板收敛但每处拼装都有 schema+契约测试兜底。SF 用作者好坏例 few-shot,NC 用"作者明确排除的内容不得借 author_decisions 重新进入候选"——对注入面 NC 更严。

### 2. 上下文组装与预算管理

**SF:token 级精细预算+证据账本+保护块。** 132 个上下文源注册,assembleContext 是唯一装配入口;输入预算=窗口−输出预留−5%(48K 兜底);两级裁剪(每源二分截断+显式标记;超窗按 L3→L2→L1 整层丢弃);atomic 源超预算直接抛错;装配产物带 per-source 证据(included/omitted/trimmed、字符与 token 数、sha256、delivery);连续性保护块信封请求前校验否则拒发;协议调用可整体拒绝裁剪。弱点:token 估算纯常数(中文 1.5/字),窗口查硬编码表;正文上下文句级字符串隔离会误伤台词。**NC:条目数 Top-K+确认制+真实 tokenizer。** ContextCompiler 按 scope 调度 loader(两阶段加载);预算是"条目数"而非 token(CONTEXT_BUDGET:core_entities 8、characters 6、rag_chunks 8 等,contracts.py:481-492 亲读);无字符级裁剪的场景显式声明 `input_budget_policy: "no_application_truncation"`,P20 强制 budget_tokens==0 的确认,否则失败——宁失败不静默摘要;token 计数用 tiktoken 真实 tokenizer,加载失败退 UTF-8 字节保守上界("宁可多裁不能静默超窗",token_estimation.py:14-45 亲读);裁剪记录按资料性质标注事实等级(事实/计划/规划/派生/候选/混合)。小结与互相可搬:SF 的"每源 token 预算+二分截断+分层丢弃+per-source 哈希证据"是教科书级实现,NC 目前只有条目数预算、粒度粗;NC 的"确认指纹一致才消费+no_application_truncation 显式声明+事实等级标注"补上了 SF 默认静默 trim 的窟窿(SF 创作类调用默认 trim 只 console.warn)。token 估算 NC(tiktoken)明显优于 SF(常数)。

### 3. 实体/世界/章节建模与别名/去重治理

**SF:宽表+注册表引用+同名检测,轻。** Character 是 98 行宽接口(13 个扩展维度、九宫格阵营、narrativeStatus 规划层带 statusEvidenceChapterId 证据绑定、多世界字段;types/character.ts:16-98 亲读);**没有实体的别名字段**;实体去重**仅同名检测**(character-copilot.ts:504-530 亲读,重复检查与 adopt 写回锁进同一事务;全仓 grep "去重/查重"仅此一处实体级命中)——无拼音、无语义、无别名融合。亮点是事实账本:FactPredicateSpec 受控谓词(key/subjectTypes/factKind/cardinality/conflictPolicy/constitution 世界宪法主题),AI 输出必须映射到已登记谓词;时序以 chapterId 为稳定身份、绝不缓存 order(章节可拖动重排,temporal-fact.ts:87-90 亲读)。**NC:统一实体表+三级去重+别名提取,重而完整。** CoreEntity 统一实体表:public_info/hidden_truth 双层信息、reveal_level 四档、pgvector embedding、search_text 生成列=name||aliases(pg_trgm)、pinyin_string 拼音缓存(core.py:43-115 亲读);别名由 P14 alias_relation_extraction 从锁定 Scene 逐字证据提取;去重三级管线:pg_trgm DB 初筛+embedding 语义候选→RRF 混合→精确别名命中→阈值分流(dedup_service.py:42-213 亲读);LLM 只做融合判定,pair_fingerprint 持久化,每 12 对持久一次、恢复从已处理对数继续(entity_fusion.py:373-449 亲读)。章节正文:WritingDraft 唯一版本约束+content_hash+状态机;连续性走事件溯源(memory_events/delta_log 等)。小结:实体治理 NC 是完整子系统、SF 是薄层;但 SF 的"受控谓词+cardinality+conflictPolicy+constitution"和"chapterId 作稳定时序身份"是 NC 没有的表达方式,值得评估吸收。

### 4. 一致性与审校、证据/确认机制

**SF 的对应物**:candidate/adopt CAS+ContextManifest+正文语义审阅。durable candidate 携带源文本哈希/输出哈希/ContextManifest 哈希,源变化即 stale 拒绝采纳;adopt() 在同一写边界把依赖该章的摘要节点标 stale(注释:"Keep this lifecycle rule at the single write boundary so durable AI adoption cannot leave a fresh-looking summary cache behind",adopt.ts:1、37-45 亲读)。正文语义审阅:prose-semantic-review.ts 定义 **9 类 issue code**(world-rule-conflict/character-motivation-break/causal-gap/continuity-conflict/pov-knowledge-leak/future-plot-leak/character-voice-drift/outline-deviation/unsupported-state-change),severity=blocking|warning|uncertain,每条带 candidateQuote+evidence,reviewer 含 correlatedJudge 字段(:13-60 亲读)。信息边界:information-boundary.ts 构建确定性 forbiddenClaims 清单+manifestHash,生成后逐 claim 检查泄漏——这是 NC hidden_guard 的对应物(:16-49,374-405 亲读)。弱点:无"作者确认→重编译→指纹核对"的独立快照链,上下文证据复用靠 ContextManifest 哈希比对,粒度更粗【推断】。**NC:Confirmation/Snapshot 是一等公民。** preview_confirmation→compile_with_tiers→作者确认→落库;任务侧按确认记录重编译并核对指纹("novel_id/action/confirmation_id 三重匹配,不符 raise",p20_context.py:81-85 亲读);ContextSnapshot 只保存 hash、引用、原因码与预算摘要,不保存原文;hidden_guard 确定性词表**从冻结 compile 自身的来源派生**,不重新查询世界;审校 chunk_N 分片近读,finding-bound 定向返修——_targeted_revision_ranges 把 findings 按 excerpt 唯一定位合并为 spans,_excerpt_uniquely_locates 保证 excerpt 恰在正文唯一出现(semantic_review.py:114-244 亲读);2026-10 新增 scene_contract_items 逐条三态判定(met/unmet/unknown),unmet 须附"最应补写处的唯一原文"作返修锚点。小结:确认/证据链 NC 更严;审校两边同构(分片近读+finding+定向返修),SF 的 9 类 issue 分类学和 correlatedJudge 更成体系,NC 的 scene_contract 三态+返修锚点+excerpt 唯一性校验更细。

### 5. 长文本分段续写与流式编排

**SF:单调用不切段,续写靠尾部窗口;流式工程在客户端。** chapter.continue 只带末尾 3000 字+1600 字锚点(chapter-adapter.ts:141-175 亲读);流式 SSE 手工解析+32ms 合帧+切标签页不中断。**NC:续写有确定性 materializer 与前缀校验;流式有元数据尾块分离。** 续写接收锁定 base draft 完整正文、只输出新增,materializer 注入"拒绝擅自增加会约束后文的长期规则、承诺、期限、关系变化或重大后果";采纳前校验"续写候选比较续写部分开头与冻结基稿结尾",基稿被改过则比较降级为覆盖缺口说明(services.py:1507-1554 亲读)——比 SF 的 slice(-3000) 保守窗口保留更多信息,代价是输入更大【推断:大章节下成本更高】。分段编排形态不同:NC 不在正文层切段,而在审校/收束/知识治理层做确定性 map-reduce(审校 chunk 分片、世界收束固定字符预算顺序 map+二叉 reduce);跨块由 checkpoint 恢复。流式独有:InteractionStreamFramer 流式安全地隐藏 `<INTERACTION_META_V1>` 尾块——正文先行可见、元数据后置,尾块缺失/截断/schema 无效只丢弃附加信息、**不判废已生成正文**(framing.py:9-43 亲读)。SF 的正文无此"正文+JSON 尾块"流式分离机制【推断:全仓未见对应物】。

### 6. 多模态

**SF:完整漫画生产链,能力声明 fail-closed。** 看图 chatWithImagesV1;画图唯一通道 OpenAI 兼容 /images/generations;漫画侧请求先幂等认领、来源新鲜度检查、requestHash 全量哈希幂等复用(命中即 reuse 不再花钱)、visualBible 未确认不生成;能力声明诚实到保守(referenceImage:false 等);权利声明前置。聪明反例 Voronoi(AI 只出白名单参数)。**NC:立绘走本地 CLI 候选+地图册程序参考图,无漫画分镜管线。** 世界对象立绘:local CLI 只在审查包装之后——服务端从实体已确认数据构建默认 prompt、作者可编辑、每个结果都是候选须经显式 adopt(world_object_image_generation.py:1-9 亲读);地图册:AI 只做空间线索提取与层级规划,固定 gpt-image-2 Image API;"程序生成不含文字的结构参考 PNG"、"图片结果不反向更新几何"——与 SF 的 Voronoi 同思路:AI 不直接产出地理事实。无漫画/CG 分镜与逐格生产模块(ls 亲验);也没有 SF 式的 requestHash 图片候选幂等复用【推断:未检索到对应实现】。小结:多模态 SF 明显更完整;NC 立绘的"服务端构建默认 prompt+作者可编辑+显式 adopt"门禁与 SF 同构但入口更收敛。

### 7. 结论

**SF 更聪明的点**(均有亲读或材料证据):①每源 token 预算+二分截断+分层丢弃+per-source 哈希证据;②连续性保护块信封;③handoff/planReconciliation 结构化对象(带 offset 的 evidenceQuotes、伏笔提前暴露检测字段,outline.ts:49-96 亲读);④受控谓词事实账本;⑤图片候选 requestHash 幂等复用;⑥provider 能力矩阵 fail-closed;⑦SSE delta 32ms 合帧+全局 session 生成不中断。**NC 更扎实的点**:①实体治理完整子系统(三级去重+别名提取+拼音+pgvector+RRF);②tiktoken 真实 tokenizer;③确认-重编译-指纹-快照全链;④prompt contract 开发期漂移检查;⑤fenced 不可信数据边界+无全局共享 prompt+流式元数据尾块分离;⑥审校细度(excerpt 唯一性定位、scene_contract 三态、返修锚点);⑦服务端事务/CAS/novel_id 租户隔离。**可直接搬运**:给 NC——每源 token 预算+裁剪标记+per-source sha256 证据(可近乎直译)、连续性保护块信封、ChapterContinuityHandoff 式结构化交接对象、图片候选 requestHash 幂等复用、provider 能力矩阵 unverified=fail-closed、9 类语义审校 issue 分类学;给 SF——三级实体去重与别名提取、tiktoken、confirmation→重编译→指纹核对、流式元数据尾块分离、prompt contract 漂移检查。

---

## 十三、借鉴清单与差异化机会(含优先级)

> 重要前提:对比发现 NC 许多直觉上的"借鉴点"**已经存在且更强**,不能重复建设——真实 tokenizer(token_estimation.py:11-30 vs SF 常数)、冻结能力档案(capabilities.py:14-45 verified_input_ceiling_tokens+calibration_status vs SF 大量 unverified)、重试错误分类(retry.py:29-60)、上下文编译 P0 永不逐出+逐项 omitted 理由(compiled_context.py:60,229-243)、服务端密钥(secret_store.py)、CSP(deploy/openresty/site.conf.template:13)。以下只列真实缺口。

### 清单一:值得直接借鉴(借给 NC)

| 编号 | 项 | SF 证据(✓核=对比分析师亲自核实) | NC 现状 | 代价(推断) |
|---|---|---|---|---|
| B1 | AI 正式入口注册表:executionBoundary+adoptAllowed+allowedCallers 机器化 | ai-entry-registry.json 实测 47 条目,每条带执行边界,仅 13 条允许 adopt;check:ai-entry-registry 把"谁能调 AI、谁能写库"变成 CI 可 lint 的数据 | AIStepPurpose 仅 primary/三类 repair;"禁绕过 open_project_llm_client()"只靠 AGENTS.md 文字与评审 | 1-2 周 |
| B2 | AST 级架构守护门 | scripts/check-architecture.mjs:1-6 自述"防止任何人(人/AI)重新引入反模式",实测 2373 行 | scripts/ 仅 3 个文件,"跨模块仅经 contracts/facade/DI"无机器门 | 1 周 |
| B3 | 作者标记好/坏例→few-shot 注入 | prompt-engine.ts:63-84 实测:examples.good 截前 3、bad 截前 2 | grep few_shot/好坏例 零命中——真实缺口 | 1-2 周 |
| B4 | 消息层连续性锚点校验+overflow reject 策略 | continuity-envelope.ts:1-2 保护块;client.ts:322-332 发送前校验否则拒发——双层防线 | compiled_context.py 已有 P0 永不逐出,但保护终止于编译产物,无第二道锚点断言 | 2-4 天 |
| B5 | 任务级模型路由(按任务种类选模型) | task-routing.ts:4-15 抽取类跑便宜模型 | llm_runtime.py:351 仅 high_quality 二档 | 1 周 |
| B6 | 发布证据账本(schema 化 evidence 文件+哈希) | showcase/screenplay/night-last-stop/release-evidence.json 实测存在 | evals 有版本化 jsonl,但 README 承诺的"脱敏版本化长篇评测集"无对外机器可查证据形态 | 3-5 天 |
| B7 | 长篇规模分档夹具门 | long-form-scale-gate.ts:7-8 三档义务证据+README 自认诚实边界 | task_capacity.py 只探队列容量 | 2-3 周 |

### 清单二:需要规避的坑

| 编号 | 坑 | 证据 | NC 落点 |
|---|---|---|---|
| P1 | 明文 Key+未转义注入点构成"手稿+Key 一锅端"链 | ai-config.ts:263-275 明文 localStorage;GlobalReplacePanel.tsx:664-668 dangerouslySetInnerHTML 渲染未转义正文(✓核) | 已有三道防线(服务端 secret_store、CSP、esc() 惯例);若做全局替换高亮,禁字符串拼 HTML,用组件渲染或先 esc 再替换 |
| P2 | token 估算常数化,误差直接驱动裁剪决策 | context-budget.ts:144-151 CJK 1.5/字(✓核) | 保持"任何新路径不许退回常数估算" |
| P3 | 流式解析静默吞错、重试面过窄 | client.ts:414-419 SSE JSON.parse 失败裸 catch(✓核) | 流式解析异常必须计数并落 run receipt,不得裸 catch |
| P4 | 用子串/无锚点正则做"语义"判断 | chapter-adapter.ts:29-33 句级剔除;usage-log.ts 价格表 /o1\|o3/ 无锚点正则 | 红线:凡"判断内容含义"的逻辑禁用子串/正则,一律走结构化字段或确认语义 |
| P5 | 文档宣称与产品目录漂移、权威链自指 | README 漏列已发布漫剧素材;CHANGELOG 自认"只保留历史表述" | 权威指针链条保持一层;README 功能导览从能力目录生成而非手写 |
| P6 | 媒资与生成物入库失控 | checkout 391MB 中约 88% 是媒体;单文件 58MB base64 JSON | 评测产物/截图/演示包设体积门 |
| P7 | 功能进主干但发版停摆 | CHANGELOG.md:18 版本保持 3.9.1;release 停 2026-08-04,9 月 main 有 598 人工提交(✓核) | 保持"main 可达 commit 即可发布"节奏,版本号不与营销脱节 |
| P8 | 巨型文件与注册表单文件膨胀 | production-executor.ts 10904 行、skill-registry.ts 5470 行、context-sources.ts 3343 行(wc -l ✓核) | 当前最大 world_generation_center_service.py 5232 行已接近可感知阈值;设行数告警 |
| P9 | 分层反向依赖被 CI 默许 | context-sources.ts:14 本尊就反向 import store(✓核);lib 全仓 60 文件反向 | B1/B2 落地后自动拦下——两笔投资互相增强 |
| P10 | 级联删除弱防护+后台失败静默 | OutlinePanel 删大纲节点普通确认即级联删正文;自动快照失败仅 console.error(简报) | 任何新增级联删除路径防护等级不得低于其父对象;worker 失败必须有用户可见态 |
| P11 | 类型/测试门禁覆盖盲区 | tsconfig include 仅 src,tests/ 与 scripts/ 不在 tsc 范围 | 引入 TS 或收紧 mypy 时一次性覆盖测试代码 |
| P12 | 能力宣称照抄厂商,已付过学费 | provider-capabilities.ts:57-61 注释实录 Agnes 宣称 response_format 实测失败(✓核) | 新接模型默认未校准、不给业务路径用;校准结论(含失败)写进档案注释 |

### 清单三:差异化机会(结合 NC 双画像:长篇小说作者 A / 非技术 RP 用户 B)

| 编号 | 机会 | 论证 |
|---|---|---|
| D1 | 零配置 AI+真实成本可见(SF 结构性做不到) | SF 强制 BYOK+Key 明文+9 家供应商需 dev 代理;NC 有 owner 账户级已验证连接+真实余额查询。对 B 画像做到"注册即用",对 A 画像就地展示余额/消耗趋势——注意 NC schemas.py:384-388 明确"费用只记录状态,不估算货币金额",成本可见应基于真实余额与 token 计数,不要重蹈 SF 本地价格估算过时表的问题。**迁移动机为推断** |
| D2 | 长期记忆质量的"公开可验证"(领先) | SF 的规模验证是工程夹具且自己承认;其检索质量无法跑服务端盲评。NC 已有 rp-long-memory v2/v3 holdout 数据集+creative_forecast"blind review and honest costs"。把"记得住"从体验承诺变成可审计承诺——发布脱敏评测集+每次能力更新的质量证据账本(借 B6 形态) |
| D3 | RP→创作的证据化回流(SF 独占) | SF 明令"运行结果不得自动回写世界引擎"(AGENTS.md:18 ✓核),写玩互通是单向冻结。NC 有 Evidence 重新物化/confirmation 指纹语义与 ADR-0018 只读引用先例,RP 分支中作者点头的片段可以带完整证据链变成正文/设定候选。风险:必须守住"AI 不越权"——默认建议制、作者确认制 |
| D4 | 服务端编辑审读与短期前瞻流水线(已在途) | SF 的审查全部是生产质量门,没有面向作者正文的日常审读队列。NC 的 EditorialDesk 与 semantic_review 已在工作树进行中(本会话 git status 可见),creative_forecast 已有离线盲评骨架 |
| D5 | 跨设备与"改得安心"默认闭环(SF 独占) | SF 数据按浏览器隔离、备份责任全在用户、五层本地备份是对无服务端的补丁。NC 服务端持久化+版本/工作稿/发布候选使换设备、误删恢复、回滚是默认能力而非用户义务 |
| D6 | 有限协作(授权内领先) | SF 跑团自认"公共联网多人尚未部署",整个产品无多人概念。NC ADR-0027 已授权有限协作。注意按 ADR-0027 边界收敛,不扩张为通用多人编辑 |

### 优先级排序

| 优先级 | 项 | 逻辑 |
|---|---|---|
| P0 | B4 锚点校验+reject;B1 AI 入口注册表;B3 好坏例 few-shot | 先做"保护已有资产"的(B4 极低成本补双层防线;B1 治理杠杆最大,把承诺 5"AI 不越权"机器化);B3 唯一直接提升生成质量,数据资产随使用复利 |
| P1 | B2 AST 架构门;B6 评测证据账本;B5 任务级模型路由 | 长期防退化(B2 在模块数增长前落地成本最低);B6 同时是 D2 的交付物;B5 成本/延迟双降 |
| P2 | B7 规模分档夹具 | 收益真实但成本最高,随评测集计划一并启动 |

**刻意不借**:三注册表全套移植(NC 的 Postgres schema+Pydantic+Evidence 已覆盖同等约束)、RequireBackupBefore 全套(服务端不硬删已消除主要风险面)、Voronoi 式地图参数化(NC assistant_map_tools.py:1"Map-owned confirmed operations; no generated coordinates"✓核,哲学已同)。

---

## 十四、风险与未解之题(各方向遗留问题汇总)

### 未运行验证类(所有方向共同)

- 全程未运行 SF 任何代码、测试、CI、构建(26 道门只确认配置存在,未验证通过状态);约 3900 个测试用例只做静态盘点,通过率与质量是否名实相符未验证;npm audit 未执行,依赖漏洞状态无实时漏洞库证据;界面未启动亲验,README 描述的 UI 与各产品工作台真实交互只有截图和文档互证;NC 侧同样未运行测试/构建,覆盖率门槛为配置核对。

### SF 各方向遗留

- **产品定位**:产品"效果好不好"(文学质量、各供应商实测表现)只有仓库自述的"持续评测"口径,无第三方或实测数据;README 漏列漫剧素材的原因无法裁定;traffic CSV 只覆盖 GitHub,无在线版真实使用数据。
- **用户旅程**:AI 生成链的实际输出质量、任务成功率、费用无运行时数据;ChapterEditor.tsx 3609 行只精读了关键路径;HomeTools 三个分区组件未展开细读;在线版与 main 可能有部署时差;公共联网多人未部署。
- **架构**:src/lib 各领域内部实现质量(executor 10904 行等巨型文件的内聚性)未逐文件深读;check-architecture 约 110 条规则只看了标题与关键段落;lib→stores 反向依赖的豁免机制未追到具体清单;brief/compiler 平行实现的历史成因只有代码形状证据。
- **数据层**:Dexie liveQuery 对其他标签页写入的感知能力未实测;memory/retrieval 引擎内部算法未深读(只到表结构与 stale 传播);workspace-impact 改动影响传播未完整刻画;大项目自动快照的实际体积/耗时无实测。
- **AI 管线**:orchestrator.ts(2423 行)与 context-gateway/selector.ts(975 行)未逐行深读;47 个 AI 入口的 allowedCallers 一致性未逐条核对(由 CI 门承担);token 估算/价格表/窗口预设的数值准确性未做真实请求验证。
- **互动叙事改编**:open-world 142 文件仅深读编译合同层,evolution/director/combat 玩法内核未深读;用户自建 AVG 的 AI 生成链路未深读;跑团 KP 运行时(万余行)只确认状态槽位与安装边界;AgentRun/Harness 通用底座(scheduler 6118 行)未深读;**本章材料在漫画图像管线处截断**(漫剧素材线细节缺失)。
- **工程质量**:未逐个审阅用例质量;e2e 快照服务与 acceptance JSON 的生成消费机制未深读;Vercel 平台侧 CSP 无法从仓库判定。
- **活跃度**:爱发电收入、知乎赞同数、QQ 群活跃度不可得;star 曲线为 SVG 反推近似值;issue 响应时长只抽样。

### NC 侧遗留(对比方向)

- worker 生产环境实际并发数、吞吐与恢复演练结果未验证(需生产访问);per-account 用量汇总/计费表是否存在未深查(只确认 AIRunEnvelope 与 usage_unknown 机制);ADR-0025 知识治理只读到稳定出口契约;图片候选幂等复用是否存在于任务层未深读 local_agent 模块;前端为纯 JS 无类型层是 NC 自身更大的结构性短板(超出对比范围,仅记录);工作树存在未提交进行中改动(assistant/editorial、writing/semantic_review 等),"已在途"结论以当前工作树为准。

### 口径争议与已裁定项

- e2e 数量:以 57 个 .spec.ts 为准(本次实测;64 为递归 find 含 helper 的口径,摸底材料"64 个 e2e spec"不准确)。
- CI 门数量:26 道(本次实测;摸底"约 25 道"不准确)。
- Dexie 表数:123(本次实测;数据层材料"126"未能复现,判为推导误差)。
- catalog 条目:14 条(6 released/7 preview/1 experimental,本次实测;架构材料"15 条目/preview 8"不符)。
- traffic 日均(9-30 末行)与月度合计(9 月)为不同口径,非矛盾。

---

## 十五、调研方法与局限

**方法**:八个 SF 方向(产品定位、用户旅程、架构、数据层、AI 管线、互动叙事改编、工程质量安全、活跃度社区)与三份 NC 对比(功能矩阵、架构范式、AI 管线)由工作流的多个分析师分别执行,全部为**只读静态调研**:文件读取、grep/find/wc 统计、git log 统计、gh api 查询、B站/知乎页面抓取(WebFetch/web_reader,知乎直抓 403 改用 reader)。活跃度方向确认非浅克隆(git rev-parse --is-shallow-repository=false)。

**本次汇总阶段新增核对**(汇总撰稿人在克隆内实际执行的命令):
1. `git rev-parse --short HEAD` → `436abe42`(与各方向材料一致)。
2. `ls tests/e2e/*.spec.ts | wc -l` → 57;`ls tests/e2e/ | wc -l` → 58;`find tests/regression -type f | wc -l` → 740。
3. `grep -o "status: '[a-z]*'" src/lib/product/product-catalog.ts | sort | uniq -c` → 6 released / 7 preview / 1 experimental。
4. `node -e` 解析 package.json ci 脚本计 `&&` 分段 → 26 道门。
5. `awk '/STORYFORGE_STORES_V[0-9]+ = \{/,/^\};/' src/lib/db/schema.ts | grep -oE "^  [A-Za-z_]+:" | sort -u | wc -l` → 123;ensure-schema.ts REQUIRED_TABLES 数组元素 → 123;docs/ARCHITECTURE.md:106-107 亦写 123。

**证据分级**:各方向分析师亲自打开核实的行号,与转引自工作流材料的行号(对比章节标【材料】/「简报」,汇总抽查过的关键条目均与克隆一致)在原文中已标注;本报告在引用处尽量保留该分级,无法逐一复核的转引以原文标注为准。

**总体局限**:
1. **未运行任何代码**——所有"门禁通过""覆盖率达标""效果验收"均只报告配置与文档证据;两侧产品的真实生成质量、任务成功率、端到端耗时均无运行时数据,本报告不比较文学质量。
2. **静态只读的盲区**——多标签页并发、liveQuery 跨标签感知、真实模型行为、P9 级长管线的真实耗时等只能基于代码推断,推断处均已标注【推断】。
3. **材料截断**——互动叙事改编方向材料在漫画图像管线处截断,漫剧素材线与跑团 KP 内核细节缺失。
4. **外部数据不可得**——爱发电收入、QQ 群活跃度、知乎赞同数、在线版真实使用数据;GitHub 指标仅截至 2026-10-01 单日快照。
5. **版本时效**——克隆固定在 HEAD=436abe42(2026-10-01 前后),依赖"落后版本"结论基于 npm 官网 2026-10 快照;NC 侧"已在途"结论基于当前工作树未提交改动。
6. NC 与 SF 的对比结论服务于 NC 自身的借鉴与差异化决策,不构成对任一产品的完整评价;SF 侧证据约六成依赖转引(已标注),关键声明经抽查核实。
