---
id: T-20260923-guimi-flagship
title: 现有 guimi 旗舰演示增量升级
status: active
created: 2026-09-23T02:57:27+08:00
updated: 2026-09-24T08:16:00+08:00
---

## 目标与验收

执行用户附件01/02任务书与本轮明确要求：保留原guimi、先可验证备份，再全60章基础覆盖和连续关键篇章精修，贯通正文→对象与证据→地图→冻结来源RP，随后补齐真实图像、四至六开局和十条操作链。覆盖未完成V4能力，不以资料准备或单元测试冒充实际体验。

验收为代理验收，非人工试用。当前 READY=false。用户 2026-09-23 已明确要求部署并同步线上 guimi，但本轮又指定先完成前60章 Evolution 调试与验收，故发布排在演化之后。原作正文/工作稿/历史不改写；反事实和破坏性验证只在副本。

## 上下文与来源

- 用户ZIP：/Users/tywww/Downloads/Guimi_Astra_旗舰演示升级提示词包_v2.zip，两份任务书已完整读取；需求副本私存任务artifacts外，原始ZIP不提交。
- 原源码HEAD 0efb1359d70af3bec92ad47d0493238d62bc7861，分支codex/v4-audit-fixpack-1，243个WIP文件快照继承到隔离worktree，不等于已审查可合入。
- 工作树 /Users/tywww/.codex/worktrees/guimi-flagship/ai-writing-assist，分支codex/guimi-flagship。
- 私有数据/媒体/基线位置 /Users/tywww/.codex/artifacts/guimi-flagship-20260923，禁止提交原文、数据库、媒体私有材料和凭据。
- 实查两个backend/.env均指向ai_novel_acceptance_guimi。目标项目937c86f1-a2c3-4db5-963d-f3181095f339，owner零UUID有效active，author，标题诡秘之主·廷根篇；原TXT导入记录795b949a-6d9e-4706-ab0c-70ac210175fe，60/60 done。主开发库同ID是另一份演示项目，不能混用。

## 最新检查点（2026-09-24 06:02 CST，以此为准）

- 第14—15章按原文代理精修Scene五字段、克莱恩视角、`agent_proxy`审核标记，两库apply/repeat且原正文版本/hash未变；作者界面未复核66→64、缺设定42→40，两个Scene已采用。第14章3张、第15章2张人物卡与两份可编辑原文复盘剧本通过Story facade在两库apply/repeat，浏览器实查第14章三卡与剧本区；剧本仍是可编辑草稿，未冒充作者亲自采用。两个现有canonical故事线已增量关联戴莉/邓恩/韦尔奇住所并留逐字来源，未新造平行主线。戴莉肖像v1因符号状脸颊痕迹拒绝、v2目视合格并上传原项目World图，回读全图/缩图；私有清单已记录。
- Scene改动正确使前一Evolution run `reading-e68...` 标记`source_stale`，失效起点index13；旧66份回执不删。`revise`因正文/Scene span未变化而409，零费用`scoped_recompute`预览显示继承前13场、重算53场、无准备窗口。新run `reading-3e011044-12a5-4706-a464-91ff74e7c4e2`已开始，task `aeca714d-c4e0-4a24-b490-d42e8e748dde`，私有`evolution-follow.py`会话33803正在串行跑最多53场，**勿重复领取/重启**。首场done后账本累计保守USD6.3374034；原run已不应称当前完成，直到新run 66/66并审计。模型请求仍经原共享Meter/flock，unknown不重试。
- 当前HEAD仍0efb1359、主题分支有约304个WIP路径，`origin/main`已领先16提交（包含V4其它PR），大约190个同路径重叠；付费worker运行期间不要merge/rebase/改变工作树代码。前端build通过、定向101前端/13 World图片后端测试及lint通过；`make docs-check BASE_REF=origin/main`要求核两份治理文档，人工核`CLAUDE.md`和维护协议无当前变化后用明确no-change-reason脚本通过；`git diff --check`通过。完整`make test-ci`、PR、合并、发布仍待做。下一步等新run进展时只读审查代码/资产；run完成后核回执与原文，再基线合并、全门禁及线上同步。

## 较早检查点（2026-09-24 05:44 CST）

- 第6章灰雾神殿新增逐字来源绑定的World地点，图v1因背景多余人影已拒，v2正式上传并绑定现有Scene；第14章韦尔奇租住房屋、戴莉两项对象各以三处逐字原文和Evidence精修，审计库dry/apply/repeat与原库dry/apply/repeat均通过。第14章住宅图已上传World对象、地图新子节点并关联Scene，正常API回读和浏览器实际显示。读者侧发现仅地图cutoff不足以展示`author_only`对象，故增量建立Story揭示计划：进入第14章隐藏，进入第15章时城市入口、子图地点和同图出现；来源预览可返回并保留选中。图片、城景和方位中的艺术设计不当作地理事实，私有脚本和媒体回执在任务artifacts。
- Scene配图通用UI已显示第6、14章实际对象图；GET对象图新增`expected_version`并由前端带入Scene绑定版本，版本不符服务端拒绝返回，防对象更新竞态错图。定向前端101项、World图片后端13项、ESLint/Ruff通过；完整仓库门禁尚未跑。第14—15章原文已代理逐章回读；下一步补两章Scene目标/人物知识/剧本与连续线索，同时复核全60章待裁定World，继续整理发布所需工程变更。READY=false，尚无提交、PR、合并、部署或线上数据同步。

## 较早检查点（2026-09-24 04:59 CST）

- **前60章演化执行完成**：正常作者API `/api/evolution/reading` 显示run `reading-e68fb884-4eb1-4fff-a027-9721202b31ee` status=`completed`、66/66 Scene、end_chapter=60、无prepare待办，最终task `55401943-e68e-493e-8f42-dd17c8a61329` done、`reading_complete=true`、无next_task。DB内部run仍`active`是可追加运行态，产品计算状态为`completed`，不要误称已经drained。私有只读审计`evolution-60/audit-progress-66.json`核66份跨run真实回执，正文源总212868字符、2782观察、5隔离错误引文、50已写入World refs、458待决定；World审查5 passed / 45 capacity_deferred / 2 extraction_deferred / 14其他blocked。World和语义质量绝不可宣称全书验收通过。
- 共享paid ledger最终422请求，其中419 settled、3历史usage_unknown按最高预留保守计费，合计USD6.2550225估算上界，非账单；最近调用均settled，无在途。用户明确无预算上限，但仍保持历史unknown不重发和共享防重。原库与隔离库`writing_drafts`60条逐行全字段聚合哈希均`b2c1387ce64284e86be5560ea31f4c2c`，原文/版本未变。
- 第13章邓恩旧`public_info`驾驶马车错误已由正常World API按`expected_updated_at`更正为有车夫同乘，并通过Evidence facade附两条第13章逐字来源，repeat无重复，证据ID私存`dunn-carriage-correction.json`；图片version保持不变。API回读正确。下一步：选核心连续篇章继续代理精修对象/关系/知识/故事线/Scene/地图/图，评估未通过World候选；审查动态编排/参数与作者侧UI，跑门禁后PR/合并/生产发布与受控线上数据同步。READY=false，尚无提交/PR/合并/部署。
- 拆Scene后有90条旧MemoryEvent与当前Scene序号不同，但全为`source_stale=true`（88 deep_import、2 agent_curation），投影主动排除；有效事件错序为0，不得为此改写历史或调用重排失效影响已完成run。真正缺口是旧来源失效后地图历史在场只剩19条有效事件（1 agent_curation、18 evolution），核心篇章需来源回读后选择性补足，未知路线仍保持unknown。

## 较早检查点（2026-09-24 04:43 CST）

- 原库66 Scene中 index0—61 已真实提交，共62/66，覆盖到第58章附近；run `reading-e68fb884-4eb1-4fff-a027-9721202b31ee` active，剩余4场，下一任务`57d99397-00ba-448f-b332-b69bdf46ab11` 已由私有 `evolution-follow.py` batch-13 session46478 串行领取，勿重复执行。上个已结算账本点约USD5.9552196；按用户无上限授权继续同一共享Meter/flock，未知费请求仍不重发。批次完成后跑 `evolution-audit-status.py` 审计66份真实回执和World状态，核原稿60行版本/哈希及全计划drained状态。
- 新增第11章兄妹晚餐真实插画，本地`.local/guimi-flagship/media/moretti-dinner-scene-ch11-v1.png`，原图SHA256 `382d78485577914baeb2e6d296396f9c498d3949aa5a33e3d65844335cecb28a`。通过原项目正常地图API上传/采用到公寓节点，page `a67468fa-37c0-483d-b39c-344981d62c86`，source-bound场景标记`flagship-dinner-ch11`，最终地图revision`ca89da22-823f-4bbf-a392-4da1869c903f`。作者界面实际点标记可见图片、逐字回读第11章并返回保留选中；读者界面进入第11章隐藏，进入第12章才显示，API与浏览器均验证；私有`curate-dinner-map.py`重复执行无新增副本。源文未修改，图中摆盘是艺术诠释。
- 邓恩第13章肖像首版与克莱恩过于相似已拒，第二版`.local/guimi-flagship/media/dunn-first-introduction-portrait-v2.png`目视通过，正常World图片API上传既有canonical邓恩对象`75fa5aa8-e667-40a4-9622-d5e86a9f41a6`，version`9cdc053c-583f-4440-baef-83256d657965`，WebP full/thumbnail回读并repeat。第6章灰雾会面图仅本地候选，未上传/关联，不能算完成。媒体清单私存`media-manifest.json`，当前10项中的灰雾候选不在清单。
- 手工回读第13章发现既有邓恩 `public_info` 误称“他驾驶……马车”；原文明确有车夫，邓恩只是先上车。等当前Evolution批次全结束后，以来源绑定的正常World更新/CAS纠正，不在运行中改变下游World上下文。
- 本地API8067和Vite8167已重新启动，API经private `start-original.py`显式绑定原库且付费入口阻断，模型调用只通过scoped runner。当前浏览器地图公寓页；无PR/合并/线上同步，READY=false。随后先完成60章演化，再代理精修作者侧和真实UI验收，正式测试与发布门禁仍待做。

## 较早检查点（2026-09-24 04:00 CST）

- 当前原库66个有效Scene连续覆盖第1—60章；最新run `reading-e68fb884-4eb1-4fff-a027-9721202b31ee` 已提交index0—51，共52/66 Scene。下一任务 `07ce5010-1d3e-42f4-966a-8f153eff5fef` 已由私有 `evolution-follow.py` batch-12 session29516 串行领取，勿重复执行。上一个结算点共享ledger保守总额USD5.242173，用户已撤销预算上限；仍必须保留共享Meter、flock和未知费请求防重。
- 所有自动提交仅证实Evolution来源绑定流水线前52 Scene跑通，不代表World对象已采用、语义质量或人工试用。最近只读审计见 `evolution-60/audit-progress-41.json`；下一批完成后重新审计全部回执、World状态、隔离引文和原60章正文版本/哈希。原文、历史与旧RP source不得改写。当前READY=false，无提交/PR/合并/线上发布；后续需手工代理精修作者侧资产与实际UI，再走评审、合并、固定SHA发布和线上数据同步。

## 较早检查点（2026-09-24 03:34 CST）

- 当前66有效Scene覆盖1—60章，run`reading-610108b3-e6cd-4df7-9f32-bbe7264f84d5`已提交index0—40共41 Scene、到第39章。上一批batch-09 10场全done；下一任务`ee5cbd54-3423-4dcd-95c1-97b8243cbcff`已由私有`evolution-follow.py` batch-10 session71382串行执行，勿重复领取。完成41场时共享ledger329请求、保守USD4.4455701、最近50全settled且无在途；后续实时核算。
- 只读审计私存`evolution-60/audit-progress-41.json`：41原始回执（含逐条核实继承）、1759条观察、5条引文隔离、19 World refs、280 pending；World review为2 passed、9语义blocked、28 capacity_deferred、2 extraction_deferred。29场观察>40。World自动资产绝大多数未通过，正式旗舰内容须人工代理精修，不能称全书世界资料完成。
- 原60章writing_drafts仍60行，版本+内容hash摘要`c5b94bc880a440965ebf9df3c79f6da9`与audit基线一致；66有效Scene索引0—65连续，run active/budget_remaining467。代码/原项目均未PR、合并、线上发布。下一步等batch-10首次失败或完成，继续到第60章，然后重点手工精修核心对象/故事/地图/配图与作者侧实际使用，正式收尾测试/评审/发布门禁。

## 较早检查点（2026-09-24 03:25 CST）

- 当前66有效Scene覆盖前60章，最新`reading-610108b3-e6cd-4df7-9f32-bbe7264f84d5`已继承前31场并提交至index38（39场）；`evolution-follow.py` batch-09 session70576正在串行下一场，勿重复领取。完成index38时共享paid ledger保守USD4.3039593，后续在途以实时账本为准。此前`make docs-check BASE_REF=origin/main`需对未改CLAUDE.md/维护流程文档正式说明后通过，`git diff --check`通过；近期改动后收尾需复验。
- 第31场645字符中四条引文只缺原文全角缩进：采样器仅在非空白字符逐字相同且当前Scene唯一时取原文连续span/offset，回执记录原引文/区间；旧失败离线核对四条全唯一，新实测四条校准并成功提交，34项来源测试与Ruff通过。引文词句/标点有变或非唯一仍失败/隔离。
- batch-09后续index32—38顺序提交；一场World抽取已结算但坏JSON，`extraction_deferred`如设计只封锁World，本场观察/状态继续提交，账本真实计费留存。其他World `capacity_deferred`与语义blocked须分开统计。当前39场仅代表源绑定Evolution回执，不代表World、文学或作者体验完成；至前26场快照World仅1 passed，必须手工精修核心演示资产。
- 原稿60章writing_drafts版本+hash最近核验`c5b94bc880a440965ebf9df3c79f6da9`，下一个批次结束再核。READY=false，无提交/PR/合并/线上同步。恢复先看session70576、run status、pending task、共享ledger和private batch-09日志；若该batch完成，取最后done的next_task_id继续新`evolution-follow.py`；若failed，保留失败并从首次失败处修复，不重发费用未知请求。

## 较早检查点（2026-09-24 03:00 CST）

- 当前66个有效Scene覆盖前60章，最新 `reading-610108b3-e6cd-4df7-9f32-bbe7264f84d5` 继承前31场并提交index31（共32场）；私有`evolution-follow.py` batch-09 session70576继续串行下一场，勿重复领取。完成index31时共享ledger保守USD3.8045163，后续以实时账本为准。正文60行版本+hash摘要在拆分后仍`c5b94bc880a440965ebf9df3c79f6da9`。
- 上轮 `reading-9628457c-81bd-4874-b764-1a970e57cfe5`顺序提交index22—30（前31场）后，index31短Scene645字15观察中4条引用只是模型省略了原文换行后全角缩进，超过最多3条隔离上限而冻结失败。代码新增唯一去空白匹配，只有非空白字符完全一致、全Scene唯一时以原文连续片段/区间校准，并在付费回执记录原引文与区间；34项来源单测、Ruff通过。新真实第31场4条均校准、16观察编译并提交。非唯一、字词/标点变化仍不校准。
- 阶段审计 `evolution-60/audit-progress-26.json`：26场共1130来源观察、14 World refs、184 pending，World审查1 passed/7语义blocked/18 capacity_deferred，3条引文隔离；18场>40观察。该统计是历史26场快照，不是最新32场。不能称World资料自动完成；旗舰核心资料需按原文手工代理精修。
- 原第23—24章旧Scene5577字模型抽67观察>64上限，按原章节界在audit apply/repeat、原库apply/repeat拆成两个Scene；新备份`evolution-60/original-before-scene22-split.dump` SHA256`27c6e9b65c283460076b484d2a5d143b9dadf49dcd6d02bae47edd8bfddfee03`。现66场。第23章3540字/63观察与第24章2037字/32观察均完成；前22场原回执继承。
- 代码/数据仍未PR、合并、发布或线上同步。当前任务优先跑完前60章基础Evolution，同时记录World/语义欠项；之后作者侧手工打磨图像、地图、Scene及必要UI实际验收。恢复先查session70576、最新run/ledger，再续next_task_id；禁止重复已发出或未知费请求。

## 较早检查点（2026-09-24 02:40 CST）

- 当前真实计划已是66 Scene覆盖1—60章。`reading-9628457c-81bd-4874-b764-1a970e57cfe5`继承前22场，index22第23章已提交（原文3540字符、63观察）；index23第24章2037字符/32观察已编译，私有`evolution-follow.py` batch-08 session36382串行运行，勿重复领取。完成index22时共享ledger保守USD3.2394636，后续以实时账本为准。
- 上轮index22旧Scene合23—24章5577字符，DS无思考抽67观察>64 schema上限而冻结失败。原库先备份`evolution-60/original-before-scene22-split.dump` SHA256`27c6e9b65c283460076b484d2a5d143b9dadf49dcd6d02bae47edd8bfddfee03`，私有`evolution-split-scene22.py`在audit apply/repeat后original apply/repeat；按实际章界拆为23、24章，原有效65→66，60正文稿版本+hash摘要仍`c5b94bc880a440965ebf9df3c79f6da9`。旧run source_stale，新run scoped_recompute继承22原回执，不重采前缀。
- 产品代码新边界：已结算、已收到响应的World抽取`invalid_json/truncated_json/schema_validation`只延期World（`extraction_deferred`），冻结失败journal/费用，不写世界对象，Observation和独立状态复核可继续；连接/费用未知/权限/来源失败仍全场阻断。World22项集成、Ruff通过。第18个Scene旧别名关系无效uncertain item可由既有partial list validator隔离1项，其余aliases/relations严格schema，回执`validation_quarantine`记录；旧响应离线验证，40 tests通过。当前未实施全量World分批审查，多数World blocked须人工代理精修。
- 先前run `reading-8fba...`提交index17—21（共22场）后在合章采样失败。继承前缀必须以当前最新run为准，不复制回执。READY=false；当前无PR/合并/部署。下一步等batch-08运行结果；首次失败后定位根因或继续next_task_id，然后审核整段观察与重要世界候选。

## 较早检查点（2026-09-24 02:18 CST）

- 当前真实60章计划65 Scene，`reading-8fba6bd6-ab51-4309-8868-df74fb692ed6` 已继承前17场并提交到index19（20场）；私有 `evolution-follow.py` batch-07 session80148继续串行，最新任务由index19结果 `980ccd21-3e9e-421e-b63f-c7b319813de5`指向，勿重复领取。完成index19时共享paid ledger保守USD3.0386688，后续在途核实际账本。原稿仍不可修改，所有付费经private scoped worker+Meter+flock，API付费阻断仍开启。
- 第18场原始别名/关系输出6 aliases、3 relations、3 uncertain_items，仅其中1条不确定项多出两字段。`ProjectLLMSampler._scene_call`复用现有`partial_list_fields={"uncertain_items"}`，仅此列表逐项跳过非法项，别名/关系仍严格schema；回执增加validation_quarantine数量/索引/错误。旧第245次响应离线回放6/3/2有效，40项定向测试通过。新一次run `reading-b143...`在同场World抽取又给3个以上JSON闭合错误，不作猜修。
- `finish_scene_world`现仅对已收到完整用量且`invalid_json/truncated_json/schema_validation`的世界抽取失败，冻结失败journal和费用、World标`extraction_deferred`、不写对象，让Observation+独立状态复核继续；连接/费用未知、来源/权限错误仍阻断。22项World集成通过，Ruff通过。新run `reading-8fba...`index17—19顺序提交；index17/18 World因容量延期，未出现新格式失败。第20个Scene约4502字输出54条观察，标记人工代理复盘过密。
- 先前第13章high/65,536世界抽取成功；第14章48有效+1缺失引文隔离后成功；第15—17附近连续提交。前20 Scene不等于60章完成；World审查受容量/语义门限制，多数不是正式采用。READY=false，仍需完整作者侧精修、UI代理验收、代码评审、PR/合并、线上固定SHA发布与数据同步。
- 恢复先`write_stdin`轮询session80148或查DB `evolution_runs`/`async_tasks`；若session已终止，读private `batch-07-*.json`最后结果。确认无pending/worker后再从最新next_task_id续`evolution-follow.py`。任务记录不授权重复已发出/未知费请求。

## 较早检查点（2026-09-24 01:48 CST）

- 65场计划仍在原库持续真实执行；当前 `reading-b8847187-11fe-4583-b707-349e93092694` 已继承前12场并提交index12（共13场），`evolution-follow.py` batch-05 session75649正在串行下一场，勿重复领取。完成index12时共享账本保守累计USD2.4811752，后续以ledger实时核算。所有运行均由同一个私有 scoped worker+Meter+flock执行，公共API继续阻断付费调用。
- DS Flash 4.1实测：第13章世界抽取在high/32,768输出上限截断，因此Phase2a世界对象、AliasRelation与独立世界审查提升high/65,536；状态等复杂步骤high/至少32,768，窄观察disabled/16,384不变。新运行第13章成功。第14章弱模型把跨句内容拼成不存在的引文，原结果冻结失败；生产采样器现在最多隔离3条缺失或无定位重复引文和依赖状态，逐项原因/原输出记账，超量仍失败。新运行第14章48条有效观察+1条隔离成功提交，独立World语义审查blocked。定向来源32 tests、世界38 tests及Ruff通过。
- 第8—10章各自提交，World审查有容量延期；第11、12章也提交。当前13 Scene不等于60章完成。前10场 World 审查中3场审查通过/未通过具体以private audit报告核对；已确认index0、1、6语义blocked，index2、4、5、7、8、9 capacity_deferred，index3 passed，禁止混称。长期资料候选与正式采用仍分开。
- 私有质量只读脚本 `evolution-audit-status.py` 可随时按最新run核对继承回执、观察数、隔离、World审查、待决定；真实原稿60行hash仍以先前`c5b94bc880a440965ebf9df3c79f6da9`为最近核验值，下一节点再核。READY=false，无PR/部署。下一步等batch-05停止/完成，按冻结失败或续跑；之后对照阅读原文手工精修关键资产及代理验收。

## 较早检查点（2026-09-24 01:31 CST）

- 第7章重算 `reading-cc3c99f2-4cb7-499e-875c-91d0cbe3c915` 已完成前7章，append 到60章计划65 Scene/预算总530后串行完成第8、9章；第10章 `reading-cc3...` world抽取返回已结算`finish_reason=stop`但 JSON 单一 `}`/`]`笔误而停。`infrastructure/llm/client.py` 新增仅一个闭合括号错误且完整容器栈唯一确定时本地替换，再按原schema验证；旧真实响应第210次离线回放后13 entities/6 deltas完整验证，原失败回执保留。LLM client79 tests、Ruff通过。新`scoped_recompute` run `reading-0934bea8-8692-4f9b-85f5-982c7e114685`继承前9场，从index9续接，第10、11个Scene已成功；私有串行脚本 `evolution-follow.py` 在 session67851 从任务 `6cf2fb98-4d2b-45b7-92e3-a3aa039b7dbd` 跟随后续任务，遇首次失败即停。目前提交到index10（11 Scene）；最新已结算保守费用约 USD2.243865，后续在途以共享 ledger 实查。
- 前10场世界审查不能混算：index0、1、6输入低于45k但独立语义审查blocked，index2、4、5、7、8、9为`capacity_deferred`，index3通过。前7场6 blocked并非全部容量问题；已在用户更新中更正。World候选/观察回执与正式World采用分开；当前不宣称全书质量通过。
- `make docs-check BASE_REF=origin/main` 原命令列出 CLAUDE.md与documentation-maintenance.md需核对；逐项确认两者约定未变后用正式`--no-change-reason`获得通过，`git diff --check`通过。没有PR、合并、部署；READY=false。下一步等串行批次结果，定位首次失败或续跑；审计每Scene来源、费用与候选状态，再继续手工精修和上线门禁。

## 较早检查点（2026-09-24 01:15 CST）

- 用户参数取舍已实施：简单观察采样 DeepSeek thinking disabled/16,384；复杂结构化步骤 enabled/high/至少32,768，世界独立审查65,536。`llm_sampler.py` 对重复但无精确区间的引文仅隔离该观察和相关状态提议，原响应/原因保留回执，绝不存在的引文仍失败关闭；真实第6章有1条观察与2状态提议隔离后提交。`Phase2aEntityObservation` 对模型标 existing 却缺 matched_existing_ref 的条目降为 uncertain，保留原因且忽略身份写入；真实第7章旧失败响应12项中4项可如此保守解析。相关定向31+42 tests通过，Ruff check通过；Imports既有两处 Ruff format 基线不一致，未为本次重排全文件。
- 多轮真实调试保留冻结失败和费用：第5—7章旧合并 Scene 8,890字观察16,384截断；按章界拆成第5章后半、第6章、第7章，audit apply/repeat→原库 apply/repeat；第6章先后因重复引文无效0–0、无区间失败，遂实施上述隔离；第7章先因4个 existing 身份无匹配引用导致 schema失败，遂实施保守降级。各旧失败结果不重写。
- 从头前7章共7 Scene 在 run `reading-d9273faf-af87-4202-b5c6-95f792b67119` 完成，源绑定观察31/7/52/44/...（逐场见回执）；第6、7章超大 World 审查均 `capacity_deferred`，仅候选待核对，不等于正式设定。完成时账本196次左右、保守USD1.7902287；当前 in-flight 重新核对会增加调用，最终以共享ledger为准。
- 后续4个超长多章 Scene（章9—10、12—15、53—55、58—60）在隔离库分章/重复验证后，原库分章/重复验证，共新增8个Scene，现65有效Scene连续覆盖1—60章、最长约6,017字符；原60章writing_drafts 60行版本+内容hash摘要 `c5b94bc880a440965ebf9df3c79f6da9`，与隔离库一致。原库分章前新备份 `evolution-60/original-before-long-scene-splits.dump` SHA256 `669aced17e05f4e9b8b367ca1f2b33c11bce316fabb47b843954177bbd3723f0`，私有工具 `evolution-split-long-scenes.py`。
- 分章使已完成run `reading-d927...` 标 `source_stale`（后续Scene重排），直接append不可用。新 `scoped_recompute` run `reading-cc3c99f2-4cb7-499e-875c-91d0cbe3c915` 继承前6回执，任务 `20aba8ac-95b4-4572-8f88-a4b048d13f35` 正由 `evolution-run-once.py` 在 session94019 执行第7章，不要重复领取。完成后用 `evolution-start.py` mode append/end_chapter60/request_limit约500，再由私有 `evolution-follow.py` 串行跟随已授权next_task_id，遇失败即停，不自动重试。先核查当前任务、账本、source hashes；READY=false，线上未同步。

## 较早检查点（2026-09-24 00:34 CST）

- 用户明确调整 DS Flash 4.1：复杂任务 high 思考、提高输出 token；简单任务关闭思考，不苛求模型完美。`llm_sampler.py` 的窄观察采样保持 disabled/16,384；其他结构化复杂调用显式 enabled/high/至少32,768，世界独立审查至少65,536；模块 README 和定向测试已同步，`test_llm_sampler.py` + `test_world.py` 37 passed，Ruff 通过。世界审查输入 >45,000 字符时 `capacity_deferred`，保留待核对候选、不写正式 World；这不是质量通过。
- 首两 Scene 已在旧 run 成功提交；第4章对应 index2 由 `reading-15315b3e-3a4d-4252-b595-dd3237e97019` 的任务 `b8a03982-a018-445b-9813-d3e798cd61ac` 正常提交，52条来源引文观察，世界审查输入48,470字符而延期，World refs 0、待决定11。模型有一条把多项罗塞尔史料合成过长陈述，保留候选；代理抽查不等于文学质量验收。
- 当前下一场 index3（第5章前半）任务 `f210966d-e7a6-463a-93fb-27ac42cc774b` 正由私有 `evolution-run-once.py` 在 session 67611 执行，切勿重复领取。最新已结算账本178次/保守USD1.4340312，无预算上限；在途请求会暂增最高预留，结束后重新核对。原chapter1—60正文hash在运行前仍为 `6d7d725b82463d646db7dcbec57ad578`，本次不得修改原稿。原另有分拆前备份 `evolution-60/original-before-scene02-split.dump`，SHA256 `a3503743fc713a5f922b9da5aa6ed76ea7cba0b69059f978592df16afff602eb`。
- 第3—5章旧多章 Scene 已按准确章界在副本与原项目正常 Story 接口分拆，现55个有效 Scene 连续覆盖1—60章；分拆不是语义审查。当前 run 只计划到第5章两个子 Scene；完成后需 append 后续章节，继续逐场真实运行并人工代理抽查。READY=false；合并/部署仍未进行。

## 较早检查点（2026-09-23 23:17 CST）

- 用户最新顺序：先从头对 guimi 前60章真实 Evolution，主会话手动调试/验收/生图，产出适合参数与动态编排，再部署同步线上。用户已取消原 USD5 文本预算上限，要求可用额度用完为止。共同 ledger 未换：paid-calls.json 原150次保留，第150次未知费按预留 USD0.0932829 计入并标不重试原请求，cap_usd=null 及用户授权历史已原子写入；旧账本快照私存 `evolution-60/paid-calls-before-unlimited.json`。继续逐次计量，未知仍须冻结核对。
- 本轮原库先新备份 `evolution-60/original-before-evolution-20260923.dump` SHA256 `14836b40edb41c0976cab4ac84de870e41a4b4a6810326ce45ac8b06c3240b01`。原库没有既有 Evolution run，引擎初始 legacy。副本预检确认27 fallback：5个5/31/11/23/87字符旧切片与相邻 Scene 用正常 Story merge/mapping 接口合并，旧Scene deprecated留历史；22个整章 fallback 仅以 agent_proxy 核对正文来源边界，不标人工或语义通过。副本 apply/repeat 后原库 apply/repeat；53有效 Scene 连续覆盖1—60章，`preview_reading` 无准备窗口；60正文草稿整体hash仍为 `6d7d725b82463d646db7dcbec57ad578`。原库引擎已切换 evolution epoch2。私有脚本 `evolution-scene-repair.py`/证据 `scene-repair-*.json`。
- 从首章真实试跑：首run `reading-dff6...` 在请求发出前被未核销call150挡下，0新付费；按既有授权核销并重算。第二run `reading-597c...` 首采样耗尽12000输出token而无可见JSON，call151费用已结算并冻结；第三run `reading-1752...` 采样+状态+World阶段成功，独立世界审查12k截断失败，call152—155已结算；第四run `reading-05ec...` 非思考独立审查有可见JSON但仍12k截断，call156—159已结算。失败结果保留，不重试原请求哈希。
- 代码定向调参：`backend/modules/evolution/llm_sampler.py` 仅对DeepSeek窄观察采样禁思考；对长 `AuditVerdictOutput` 审查禁思考并提升输出上限32768。`backend/evals/v4_live.py` 支持 ledger 显式 null 无上限，仍保留未知费封锁、原请求禁止重发。定向21 tests通过，Ruff通过；完整CI/文档门禁未重验。
- 当前第四次新run `reading-b479faf0-1a32-4fa2-9b89-8542965d9cc4`，任务 `a4e5b9fd-84d6-483d-8274-9243ce1f6bc1` 由私有 `evolution-run-once.py` 在 session21129 实际执行。先收它的结果与ledger，再决定是否推进第二场；不要并行领取同任务。当前仍0正式已提交演化Scene，不得称前60完成。若长审查32k仍截断，应缩小审查批量而非无限提上限。

## 最新检查点（2026-09-23 12:29，以此为准）

- 用户最新调整：RP初步开局足够，重点转向作者侧。五张真实开局卡已在原项目；Klein连续两轮、艾文两轮和面包店开局有实际模型输出。Melissa开局任务de868a1a...在第150次请求超时失败，原请求不重试；批量父进程已停止并终止，后续莉亚/Audrey不会自动启动。共享账本150请求、保守最高USD0.9026916/5，call124与150 usage_unknown按最高预留计入。当前无付费worker。
- Scene6“炉火边的晚餐”（第11章）新增Klein/Melissa两条准确原文引文绑定的在场事件，audit apply/repeat与original apply均过；原107历史事件逐列不变，未知路线仍为unknown，不伪造travel。原项目事件与来源见private dinner-presence-original.json。
- Scene6新增2张源绑定场景人物卡与1份六节拍复盘剧本，九段原文逐字回读/草稿ID/hash/范围吻合。audit apply/repeat→original apply/repeat不增版本；原项目卡各v1，剧本v1已通过作者界面采用，正式Writing原文未改。脚本private curate-scene11-story.py与scene11-*.json。卡/脚本均明确标“代理精修、非作者亲自确认或人工试用”；剧本属既有情节复盘而非作者未来规划。
- 实际作者界面8167已读出两张人物卡与剧本，采用状态可见。发现卡只显示“本场人物1/2”与编辑会清空隐藏知识/约束字段；useStorySceneWorkspace.js已改成项目内仅作姓名映射并保留完整内容字段，新增相应回归，StorySceneWorkspace 17passed，定向ESLint通过。浏览器复测姓名“克莱恩·莫雷蒂”“梅丽莎”出现。剧本“检查这一稿”只提示人工确认，绝非语义质量验收。
- 已实际读原文1—12章，私有CONTENT_AUDIT待补8—12；60章仅来源范围结构覆盖，语义未全审。第8章5字符fallback与多POV Scene、第12章梦境/真实来访分界待精修。当前8张实际采用图（新增阿尔杰），内置生图10次；收费/配额未见可靠数字。正常登录与匿名仍未验收，READY=false。
- 本轮make docs-check通过。未运行完整CI；没有提交/推送/PR/合并/部署/公开发布。下一步优先继续第8—12章作者侧结构和人物/剧情线关联，随后重新验受影响界面/数据保护/文档门禁；不再安排RP付费冒烟。

## 最新检查点（2026-09-23 05:02）

- 原项目5张开局卡已正常领域保存、重复不增行、实际UI图片/人物/章节截止点显示。7张真实采用图正常上传并读回，9次内置生图操作（两次坏图拒绝）；图片原件不入库代码。原API新session67125、Vite8167。地图到RP有可直接点击入口，开局选择后建旅程；不使用固定回答。操作键保存在浏览器会话以支持不确定响应后刷新重试。
- 首次克莱恩开局（source v2）成功建旅程，但付费前因精修公寓对象未被旧RAG关联而失败，0新文本请求，失败任务/旅程保留。根因在Evidence编译只承认检索chunk对象ID而不回读冻结精修identity来源。已把精确SourceRangeRef随RP新source冻结，生成按source draft/hash回读、角色还须人物检索准入、固定证据计入预算；39项定向测试通过，隔离库5种开局直接编译preflight均无blocker。
- 原库新不可变source v3=dfc73b73-7500-4d0b-a59e-114e5df35013，审计库v3=146bf617-3711-4d46-b4c2-6a66acf04dcb；旧v1/v2逐列未动。两库各5卡按CAS升级到v3、保留原图片版本，apply/repeat/list通过。原卡先前v2快照见private openings-original-before-v3.json；当前原卡验证openings-original-v3-validation.json。新版克莱恩旅程83fa8256-e1af-4919-99b9-bcbb1ac3af3e已通过UI创建，task9e4404aa-40d4-48fa-b598-b854bb31d48b正在单任务真实模型runner执行；不要重复领取。
- 测试：Evidence/RP source/openings39pass；前端MapAtlas+开局目录+旅程71pass。World图片因新API image_version有旧断言1失败，已修断言并重跑中。费用截至此前132请求/保守USD0.7235058/5；本轮runner结果与费用尚未结算。READY=false，代理验收非人工试用，正常登录/匿名、多轮与全60语义仍待做。
- 下一步先收runner输出与World图片定向测试，审查实际模型内容；再用新card逐种真实开局和未预写输入，校验原库素材未变化，推进60章资料/高级功能。不要直接重试原call124。

## 当前进行中（2026-09-23 04:29）

RP开局目录已实现但未完成原项目数据与UI验收：新增models.InteractionOpening、openings.py、API owner list/save/image/start、RpOpeningCatalog.vue及JourneyListView入口。复用JourneyCreate与用户幂等键，save CAS/同payload幂等；图片需要source内已出场对象+reviewed_for_anchor+绑定image_version，WorldImageService.get新增expected_version，不回退新图。World facade新增read_world_object_image并同步public API test。CoreEntityResponse新增image_version供正常版本绑定；尚需复核匿名专用路径，当前普通owner/local only。

- 两库head现为20260923_rp_openings，原库先database-before-openings.dump。audit已实际保存5张无图验收卡并repeat/list成功，/tmp/guimi-openings-audit.log；无图仅隔离测试，不是正式开局完成。原项目尚未保存任何opening记录。
- private build-openings-pack.py已输出openings-original.json / openings-audit.json共5张source-bound开局（探索艾文、原作Klein、公寓与上学Melissa、原创莉亚马戏团、原作Audrey）。source原7ff405...，audit a5749...。private save-openings.py强制原项目每张有审核配图；待补image_reference，实际save时正常领域门禁。
- 新测试 backend opening+images+facade20passed；frontend catalog+journey25passed；API contract最初openingImage命名不一致已修fetchOpeningImage，14passed；定向ESLint过。World CoreEntityResponse新image_version尚未再回归。save/repeat datetime测试适配SQLite丢timezone而保留实际瞬时时间。
- Audrey肖像已生成目视通过，文件.local/.../audrey-early-portrait-v1.png，已正常上传canonical entity3cd1126a-a28e-4832-a833-c6784f063419；别名旧奥黛丽bf9...是merged，不能绑旧ID。audrey-entity-upload.json保留，但旧app响应未含version，应新API get读取。图片manifest尚未补Audrey。
- Bakery scene generated file exec-0d2deaae-039d-451c-a676-5791ff11d6f4.png，已copy.local/.../slin-bakery-v1.png并正常上传entityccf4cca4-f599-491d-b982-d2cf9e17a278；bakery-entity-upload.json，manifest待补。
- Circus square首图exec-bb73e496-7681-402a-9e92-80a7bf055822.png已目视，但衣服和水晶球不符合实际第4章：要求红黄小丑发传单、尖黑帽黑裙/红黄油彩女人、塔罗牌。正调用imagegen cell671修图，未上传，勿采用首图。完成后绑定广场entity4570b5bb-e001-4bd0-99b9-7435043d1416并补所有媒体manifest/图片API读回。所有原图保留。
- 原API再次重启为session工具返回最新（/tmp/guimi-original-api-03.log，runtime-venv，paid guard仍开）。旧pid34669已正常终止。web8167仍在。五卡实现无新付费，账本仍132 / USD0.7235058。
- 下一步收修正后的circus图，正常上传→读取各卡image_version并审核绑定→save-openings.py原项目apply/repeat→浏览器真实5卡显示与one-click创建→指定task私有run-rp-task.py实测开局/新输入。随后继续其他大项，不得称READY。

## 最新检查点（2026-09-23 04:13，以此覆盖下方早期状态）

- 两库现在schema head为20260923_rp_reference_refresh；新增原库第二备份database-before-reference-refresh.dump。普通owner POST /api/interactions/sources/{id}/refresh已真实通过。原新source=7ff405f1-c54c-42fd-80a1-972eb337316f，73引用，5精修对象首次出场章分别1/1/3/4/4；旧42dac704...全列不变，旧journey保持旧source。audit新source=a5749e21-f479-4cde-885e-54df80521890。初次audit未纳curated因list_entities没有status，已修用list_entity_terms状态并补回归。37后端tests通过；RP source/map UI72、API contract14通过。
- 室内Map代码和正常API已完成。原公寓node=a48eb5a4-53f2-40fd-a121-071c9a492c6f，page=dcc3c970-f580-4121-9586-062c1ef23bab，父city=b948a787-d310-44f7-a0a2-ba9bd8b9314f。原city追加3个精修检索点，oldrevision保留。map-curation-01.json及curate-map-01.py保留，room-map-uploaded.png读取2445789bytes。图为illustration而非无依据平面。浏览器已目视显示，回读第1章原文后返回同图。
- private curate-presence-01.py在audit先apply/repeat，再原apply，正常Story facade只写agent_curation独立producer家族1个来源已回读的Klein在场事件；原107事件逐列不变。Scene0=f8bb3562-d902-4ebb-8416-79e7c7189fd6，event=1fa809b9-9a10-480f-92aa-145a3955d9e2，第2章引文/原Scene范围绑定，不造路程。浏览器显示Klein本场出现于公寓、定位到配图，其余23人未知。不是模型自动抽取证据。MapScenePanel未知折叠2tests过，新增代理精修badge未重验。
- 实际已上传4幅：Klein、Melissa、旧公寓、怀表。Melissa entity=ea3bebfa-63df-46d4-ab2f-1b16f2a46827；怀表entity=645b60e1-3dbf-46d7-8920-9d9c344937ec，采用图.local/guimi-flagship/media/moretti-pocket-watch-v2.png。首版表盘错位拒绝，imagegen修改后已检查上传。内置共5完成调用，实际4采用图；Audrey imagegen cell633仍待收。generated_images保存原件不删除。
- 语义逐章已读实际1—7，CONTENT_AUDIT追加5—7摘要，不能称60全审。总新Evidence31=character11+World20。图片World quota需继续实查；未增加文本请求，USD0.7235058 / 5。
- 原API新session52038（runtime-venv，/tmp/guimi-original-api-02.log），已载新source refresh路由；web8167保持。CUA guimiTab IAB2 tab1当前map?node_id=a48...&feature_id=moretti-room，Scene0已展开且配图目视显示。Local账户不等于normal/anonymous验收。
- 文档已同步DB设计、CONTEXT、World/Interaction/Infrastructure模块、development/testing。make docs-check BASE_REF=origin/main原始要求4文档审查，2更新；CLAUDE/维护协议核对无影响，正式--no-change-reason门禁通过/tmp/guimi-docs-impact-ack.log。全文门禁未收尾。无提交/PR/合并/发布。
- 下一块：通用RP开局目录（不是新RP系统）与正常图片版本防剧透读取，4—6开局使用新冻结source+现有JourneyCreate/幂等。尚未写目录代码。候选体验：第4章普通人面包房工作探索；第2章原作Klein在公寓调查；第3章Melissa修表/上学；第4章马戏团占卜场景；第7章Audrey筹集鬼鲨血；第7章Alger船上行动。只是实施候选，先核玩家知识与exact anchor，再建；不要预写固定答案。全60基础内容、V4高级能力、地图物品/多视角、匿名与normal仍未完成。

## 当前进度和恢复快照

- READY=false；原项目已有增量修改，不再是只读阶段。原DB ai_novel_acceptance_guimi，项目937c86f1-a2c3-4db5-963d-f3181095f339，owner零UUID。先备份database-before.dump并在ai_novel_audit_guimi_flagship_20260923恢复132表4152行hash完全一致；原媒体7版本全部私存校验。两库已迁移20260922_evolution_reading；原正文/导入/Scene/故事/地图/旧RP source八组基线hash保持，见original-protection-check-01.json。
- 60章212868字的现有canonical Scene span覆盖无有效正文空洞；仅第1—4章完成代理逐章语义阅读，不得宣称全60章精修。
- 克莱恩4空档案字段已补，11准确Evidence；正常图片API上传真实早期肖像，浏览器已显示。world增量5对象：早期公寓、廷根市、银白怀表、斯林面包房、街口广场，audit apply/repeat全部过，原apply过，待原repeat。私有curated-world-original-apply.json含ID；不要将早期公寓绑到第30章新家水仙花街2号。
- 私有媒体：.local/guimi-flagship/media下Klein portrait + early apartment两幅实际PNG。前者已关联，后者待地图和对象关联。Melissa portrait正在内置imagegen cell561生成。图像工具实际配额/收费信息未知，不虚报含于USD5文本预算。
- 地图新增interior结构编辑，沿用既有Atlas模型无migration。backend map4组67passed；frontend首次104中103过、一个旧四层期望已更新重跑日志/tmp/guimi-interior-frontend-recheck.log。需要正常API创建公寓室内图、上传并采用真实房间图、来源图元与Scene绑定并做浏览器闭环。
- 真实RP journey489c75c0-d41b-4e4b-8749-ffe16b44c2ca，consumer37e4a55d-5d31-4928-8863-a88fb1faa400，第4章截止、原创玩家艾文、日常探索。两轮实际DSFlash生成通过；第二轮由浏览器临时输入两便士/买面包/先问工钱再决定，模型保留接工作选择，新增内容只属于私人RP。原作角色/匿名和正常登录/其他高级RP路径未验收。
- 共享原V4账本绝对路径 .../ai-writing-assist/.agent/tasks/2026/T-20260921-novelcraft-v4-implementation/artifacts/paid-20260922/paid-calls.json，共132请求，call124usage未知按用户最高cap结算保留原错，禁重发原hash；累计保守USD0.7235058 / 5。无正在运行付费worker。新请求只用private run-rp-task.py scoped task+consumer和同ledger flock，Meter覆盖ordinary+stream，4tests过。
- RP最初attempt0c9db057-1720-43d9-b35b-3e1a420dc056已cancelled，0付费。初始BGE subprocess主脚本缺main guard且依赖缺huggingface_hub；已修private runner guard，独立runtime-venv完整dev依赖并预热。第二轮BGE768维ready，首轮降级检索不能冒充完整验收。
- 产品BGE启动失败现在每秒检查死child并快速失败，保留300秒冷启动；97tests过。RP prepare持锁等待BGE导致stop延迟的事务问题仍需根治。
- 原API8067已改由private runtime-venv启动（session91188，/tmp/guimi-original-api.log），web8167 session95961；auditAPI8066 session68772 /web8166 session38681。API仍显式阻止付费，scoped worker跑指定队列任务；尚不是自由体验最终运行模式。Local auth不等于normal login/anonymous验收。
- Browser guimiTab IAB2 tab1，当前http://localhost:8167/#interaction/489c75c0-d41b-4e4b-8749-ffe16b44c2ca。第二轮实际输出已经AX读到。

## 未完成依赖

1. 首纵向地图图片/来源/当时人物物品/原文返回链；all60基础语义整理+连续核心篇章精修、人物知识/世界资料/关系/伏笔等。
2. RP冻结版本当前以正文manifest唯一，不能更新同正文的新资料；需要通用显式资料刷新保留旧journey版本，curated Evidence需要正规入catalog；4—6实际开局、≤3选择、图片截止与各RP能力实测。
3. 图像完整套装、地图全屏/移动/层级/场景历史与路线高级能力；写作/演化/持久认知/主动建议/创意局部采用等完整清单仍保留。
4. 继承V4 Phase3审查4项：start_reading续接丢structure与已生成草稿；structure builder model空串覆盖snapshot；结构独立审查仅摘要4000但采用全文；capability_bindings缺imports.structure_analysis。未修。
5. 当前新代码只定向测试，旧6257/2586/270全套不代表当前通过；收尾需docs-check BASE_REF=origin/main和受影响测试/lint/审查。无提交/PR/合并/部署/公开发布。

## 下一步

先收map前端重跑结果，在原项目正常API创建来源绑定的早期公寓室内图并上传/采用房间画，浏览器实际从地图跳原文并返回；再完成通用RP资料版本刷新及4—6开局。保留原正文与工作稿，所有破坏性/反事实测试仅audit副本。私有数据、正文、dump、媒体和凭据不提交Git。

## 2026-09-24 06:46 续接检查点（覆盖上方旧快照）

- 第1—13章作者侧首纵向闭环已完成，另读第14—15章并补韦尔奇住所、戴莉精确来源、真实图片及版本固定、地图层级与第14章隐藏/第15章可见的 RevealPlan；第14—15章 Scene、5张人物卡、2份可编辑剧本与2条既有故事线关联已在 audit/original 增量实施，未改写原文。前60章初轮 Evolution 为66/66，但这些 Scene 改动使第14场起的后缀失效，故正在重算；代理验收不等于人工作者试用。
- 冻结失败 run `reading-3e011044-12a5-4706-a464-91ff74e7c4e2` 在 index17 遇到 17 条事件证据索引超过旧 schema 上限16；已把该字段上限调到与 observation 最大64一致，已结算响应不重复提交。新 run `reading-49d85219-1dee-4cac-975b-8668b0e57e21` 从 index17 复用此前17份回执继续；私有 `evolution-follow.py` 会话10792在运行，输出目录 `artifacts/evolution-60/sampler-cap-recompute-tail-*`，每任务走共享付费账本并保存失败。最后已见 index19 后待继续；无需新授权预算。
- 当前分支 `codex/guimi-flagship` 仍基于旧 HEAD `0efb1359`，尚未提交/合并/部署。`origin/main=d70528b5b` 已拉取，前方16个提交，含并入的V4重叠工作；不可在付费 worker 运行时合并或改动其执行模块。当前 dirty 约307路径，包括继承的V4 WIP与本轮实现，原 checkout 不动。
- 当前分支同本机12个实验开关全开的 `make test-ci` 后端有44失败；干净 `origin/main` 使用相同.env和依赖有38个同失败。6个本分支新增失败已定位修正（RP opening route项目门禁、Evolution显式输出预算清单、World image_version mock、旧助手map schema兼容），定向34/34且Ruff通过。默认关闭实验开关的完整 `make test-ci` 正在跑，私有日志 `evolution-60/current-clean-config-ci.log`。不要把38个共同配置失败藏成绿色。
- 线上只读对照：生产guimi与本地动工前备份在113/114个已有项目表全字段（排时间戳）digest一致；唯一差异为两条assistant_runs的owner_id，生产owner是真实账户，本地为零UUID；生产另有11个项目/9账户。基线恢复到隔离本地库 `ai_novel_compare_production_baseline_20260924`。生产当前固定commit `b5a3ef2e660ddaa65b9bf0ac1ada48f795c53201`，15/15检查的演示及作者功能开关已开；上线只能在代码并入main后按release.sh固定SHA发布，随后做按项目增量数据/对象存储同步，绝不整库替换。当前本地相对基线已有34个项目表内容变化、新增4表及新迁移；细目见私有 `evolution-60/current-project-hashes.json`。尚无远端写入。
- 下一步：等待重算结束并检查66/66跨run回执与原文保护；收完整CI并解决新失败；更新Evolution验收文档参数/失败账本；提交分支、同最新main整合复测与PR评审；备份生产并做guimi项目级同步演练/校验、固定SHA发布与线上浏览器代理验收。并行可只读准备数据迁移方案，勿触碰生产其他项目或账户。

## 2026-09-24 07:03 续接检查点（以此为准）

- 运行检出固定提交 `7450ca0f5`（原 `codex/guimi-flagship`），前一轮默认配置 `make test-ci`：后端6300通过/15跳过、覆盖86.10%，前端2593通过，Ruff/部署测试/依赖审计通过。12个实验开关全开时的38个共同基线失败单列，不冒充全开绿色。
- 独立整合检出 `/Users/tywww/.codex/worktrees/guimi-flagship-integration/ai-writing-assist`，分支 `codex/guimi-flagship-integration`，已 `merge --no-commit origin/main=d70528b5b` 并解27处冲突；保留主干Phase3结构阶段修复和本轮DS调参/来源隔离/地图/Scene视觉。尚未提交merge。该整合结果默认配置 `make test-ci` 后端6303通过/15跳过、覆盖86.11%，前端2594通过，其他门禁通过；仍需 `docs-check BASE_REF=origin/main` 的治理文档核对说明、差异审查、merge commit/PR。
- 原运行检出与付费worker未切换，`evolution-follow.py` 会话10792仍串行处理 run `reading-49d85219-1dee-4cac-975b-8668b0e57e21`；最后见 tail-07 已done，累计保守费用 USD7.0932693，账本正常。不可在运行检出改执行代码或二次领同任务。当前后缀未到66/66，暂不可称最终演化完成。
- 生产同步设计预检：本地初始备份对线上同项目114个已有表中113完全一致、唯一assistant_runs owner差异；线上其他11项目/9账户须保留。本地当前37个项目表相对基线变化（运行中会继续变化），含Scene/World/Story/Atlas/Evolution；有地图与卡片 revision 循环FK，不能盲目表级替换。需要冻结最终源快照，先把迁移在隔离库演练，再线上备份、项目级upsert/受控删除过期Scene span并校验媒体对象和原文哈希。生产至今只读，未发布或迁移。
- 下一步：在整合检出完成docs/差异审查和merge commit、推PR并审查；继续监控旧检出重算；制作项目级同步工具与恢复演练，全部完成后再按main固定SHA发布并对线上正常账户/匿名代理验收。

## 2026-09-24 08:16 续接检查点（以此为准）

- 整合分支 `codex/guimi-flagship-integration` 已推送，当前 `0b9027db6`，Draft PR #170 已附任务；最新通用修复把用量完整的别名关系格式/schema失败冻结为 `extraction_deferred`，未知费用仍阻断且不重试。`make test-ci` 最新后端6305通过/15跳过、覆盖86.11%，前端2594通过，Ruff/部署测试/文档检查通过；PR 最新CI尚有1项运行中。12个开关全开的共同基线38失败仍单列，不能称该配置绿灯。
- 原库续跑 `reading-b9bc9757-fb5d-467e-8faa-72b124fa4b5a` 继承前36场，串行私有 `evolution-follow.py` session73469 正执行 tail，最后已见 tail-03 完成，保守累计 USD8.2533897。前次未知费 call503 按预留上限 USD0.0980841 入账，原请求不重发；所有旧失败/回执保留。运行检出已含相同关系失败修复，不得在付费 worker 活动时改动其代码或重复领取任务。
- 私有项目级同步工具 `evolution-60/project_bundle.py` 已在隔离库完成完整36变动表/3368行交易导入及只读verify，并对模拟真实非零 owner 目标通过。最终源尚未冻结。新建隔离基线 `ai_novel_guimi_final_baseline_e2e_20260924`，从线上一致的动工前备份副本克隆并迁移到当前head，保留未导入状态以待最终包检查。原库和线上其他项目没有被此工具改动。
- 私有媒体工具 `evolution-60/media_bundle.py` 从本地正常MinIO导出 guimi 前缀34件/18.4MB，回读逐件校验；另在同存储的隔离随机项目路径复制地图和World图各一件，目标verify后清理测试对象。应用凭据不能创建新bucket，故不把新bucket试验当作成功；项目路径复制已证实。线上目前只有只读 SSH 检查：`/opt/ai-writing-assist` detached HEAD与release state均为`b5a3ef2e...`。仍未发布、未同步数据或媒体。
- 下一步：等串行run完成后审计66份跨run回执、原60章草稿和费用；处理本地剩余挂起RAG任务，生成最终项目包并在隔离基线复验；完成PR评审/检查后按授权合并、固定SHA发布，再受控同步guimi项目级数据及媒体，线上代理验收正常账户/匿名路径。READY=false，代理验收明确不是人工试用。
