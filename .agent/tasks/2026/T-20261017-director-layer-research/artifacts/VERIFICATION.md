# 独立来源核验

核验日期：2026-10-17。核验者独立阅读 EVENT、MACRO、SCENE、MODEL、INTERACTION、ADDITIONAL-SOURCES，并重新打开一手来源，不以分支代理的“已核验”代替核验。仅写本文件，没有修改产品、调用业务模型、接触数据库或运行测试。

## 核验结论

拟用于主报告的20项核心来源全部确认存在，作者、年份及文献类型可追溯；其中至少16项重新检查了原文方法、结果或限制，超过50%要求。详细核验计入：Futures Toolkit、Park、Windrum、IPOCL、Belief 2018、DOC、Dramatron、Le Guin 2016、Wordcraft、CoAuthor、Amershi、Doshi、Ashkinaze、WhatELSE、TaleBrush、Huang；另对Lost in the Middle、FANToM也重新检查了核心任务及适用范围。Re3本次按出版方摘要使用；James按原典相关段落使用，均不冒充阅读全文。

没有来源直接证明“宏观／事件／场景三个独立入口优于两个入口或自由入口”，也没有来源验证本项目当前模型或中文长篇作者效果。保留三尺度方案必须标成研究启发的产品假设。宏观抽象不等于推理更容易；增加层级也增加交接与误差级联风险。

## 关键修正与限缩

1. **IPOCL页码有版本差异，不是已确认引用错误。** 作者托管PDF首页写217–267；Crossref的出版方登记元数据为217–268。已用Crossref API核实DOI、作者、2010年及JAIR身份；主报告可省页码。不要依据PDF首页就断言EVENT页码错误。
2. **Dramatron区分版本。** 2022 arXiv题名为 *Co-Writing Screenplays and Theatre Scripts with Language Models: An Evaluation by Industry Professionals*；2023 CHI正式题名去掉“An”。正式DOI为10.1145/3544548.3581225，Crossref确认CHI 2023、四名作者及1–34页；arXiv版为102页。若阅读2022版，就按该版本引用并另注正式版本，不能混配年份、标题及页数。
3. **Wordcraft完整题名有副标题。** *Creative Writing with an AI-Powered Writing Assistant: Perspectives from Professional Writers*，Ippolito、Yuan、Coenen、Burnam，2022。文内自称whitepaper，按作者白皮书／arXiv预印本使用，不能与另一篇Wordcraft系统论文合并成一个同行评审来源。
4. **TaleBrush是CHI 2022正式主会论文。** DOI 10.1145/3491102.3501819；不是CHI EA演示条目。N=14可核实；§6.3明确观察到控制运势牺牲部分连贯性和语法，用户研究未正式对比其他共创工具。
5. **WhatELSE是CHI 2025论文的作者预印本。** Lu、Zhou、Wang，DOI 10.1145/3706598.3713363；N=12。§5任务是六人物、五地点、六动作的简单童话领域，多数参与者无互动叙事创作经验；不能外推中文长篇或“恰好三层”优越性。
6. **Belief 2018是AIIDE 14(1)的Poster Papers分区。** 正式会议论文身份及222–228页可核，不宜泛写成长篇心理学验证。有效互动样本82，部分预期行为须提示后才出现，作者承认目标优先级缺失。
7. **Versu技术文稿不等于IEEE论文。** *The AI Architecture of Versu*，Richard Prideaux Evans、Emily Short，作者网站技术文稿；原文未明确年，不能由URL的2014/05确定发表年。不可混配 *Versu—A Simulationist Storytelling System* 的题名或DOI。

## 已核验可用：核心来源20项

“可用”只表示在本行限定范围内可引用，不表示产品效果已成立。D=重新检查方法／结果／限制；A=摘要；P=原典相关段落。DOI仅填实际在出版页、PDF或Crossref核到的值，不替无DOI材料虚构标识。

| 来源／类型与标识 | 本次独立读取与实际支持范围 | 必须保留的限制 |
| --- | --- | --- |
| Government Office for Science (2024), [Futures Toolkit第2版](https://assets.publishing.service.gov.uk/media/66c4493f057d859c0e8fa778/futures-toolkit-edition-2.pdf)，官方方法指南；[官方版本页](https://www.gov.uk/government/publications/futures-toolkit-for-policy-makers-and-analysts) | D；核对2024更新和Futures Wheels、情景与压力测试用途；可借鉴条件未来、目标反推、后果链 | 政策方法指导，不是小说作者或AI工具实验；不复制其时间尺度为小说标准 |
| Park et al. (2023), [Generative Agents](https://arxiv.org/html/2304.03442v2)，UIST；10.1145/3586183.3606763 | D；25代理、两游戏日，记忆／规划／反思及可信感评价；§7明确过度礼貌合作、记忆失真 | 非长期社会预测；不能赋予当前模型具体成功率 |
| Windrum, Fagiolo & Moneta (2007), [Empirical Validation of Agent-Based Models: Alternatives and Prospects](https://jasss.soc.surrey.ac.uk/10/2/8.html)，JASSS 10(2)8方法论文 | D；尤其history-friendly方法的验证与敏感性批评；支持区分结构假设、轨迹拟合和经验有效性 | 不研究LLM或小说，历史复现相似不自动证明机制正确 |
| Riedl & Young (2010), [Narrative Planning: Balancing Plot and Character](https://faculty.cc.gatech.edu/~riedl/pubs/jair.pdf)，JAIR；10.1613/jair.2989 | D；初态、前提／效果、作者与角色目标分离，意图框架；作者明确一般规划不能覆盖全部叙事属性 | 手工小领域；动机理解不是文学质量；页码版本差异见上 |
| Shirvani, Farrell & Ware (2018), [Combining Intentionality and Belief](https://ojs.aaai.org/index.php/AIIDE/article/view/13037)，AIIDE Poster Papers；10.1609/aiide.v14i1.13037 | D；[作者全文](https://cs.uky.edu/~sgware/reading/papers/shirvani2018combining.pdf)两研究，信念与意图结合、预期他人行动，82有效互动样本 | 受规则约束的小互动，不等于深层心理；不能称所有比较均显著 |
| Yang, Tian, Peng & Klein (2022), [Re3](https://aclanthology.org/2022.emnlp-main.296/)，EMNLP；10.18653/v1/2022.emnlp-main.296 | A；出版方摘要明确计划／当前状态反复注入、排序与事实编辑 | 本次未复核其全文方法；不能把系统组合收益归于事件层 |
| Yang, Klein, Peng & Tian (2023), [DOC](https://aclanthology.org/2023.acl-long.190/)，ACL Long Papers；10.18653/v1/2023.acl-long.190 | D；详细大纲与控制器共同作用，正文§4及§6明确大纲错误级联、层级细度不一致 | 英语数千词；不是“越细越好”，未解决节奏／伏笔 |
| Mirowski, Mathewson, Pittman & Evans (2022), [Dramatron作者预印本](https://arxiv.org/pdf/2209.14958)，10.48550/arXiv.2209.14958；另有2023 CHI正式版 | D；15位专业人士、两小时共写与访谈；原文§5列强制log line、潜台词／动机及跨场对白问题 | 质性研究与系统共创；不能证明自主完整创作或中文小说迁移 |
| Le Guin (2016-02-29), [Navigating the Ocean of Story: Session 2, Round 1](https://www.ursulakleguin.com/bvc-navigating-the-ocean-of-story-session-2-round-1)，作者本人创作论；另核[2015 Session 1](https://www.ursulakleguin.com/bvc-navigating-the-ocean-of-story-session-1)存在 | D；原文问答反对把冲突当唯一变化源，讨论朗读／节奏及结尾无通用公式 | 个人创作立场；不能作为软件效果的经验实验 |
| James (1884), [The Art of Fiction，收于1888 Partial Portraits](https://www.gutenberg.org/files/58471/58471-h/58471-h.htm)，原典数字版 | P；人物与事件互相表现，桌边站姿／目光的微小事件例子存在 | 审美论辩，非现代作者需求调查；不把整本收录年当文章初刊年 |
| Ippolito et al. (2022), [Wordcraft专业作者白皮书](https://wordcraft-writers-workshop.appspot.com/paper/wordcraft_writers_workshop_paper.pdf)，10.48550/arXiv.2211.05030 | D；13位已出版作者、8周、日志访谈，局部任务与声音／控制／平庸建议负担 | 开发方研究自家工具、LaMDA；不把白皮书标同行评审；题名需含副标题 |
| Lee, Liang & Yang (2022), [CoAuthor](https://arxiv.org/pdf/2201.06796)，CHI；10.1145/3491102.3502030 | D；63写作者、1445会话，按需请求、接受／忽略、自由编辑，过程记录 | 英语众包短任务；采用率、编辑量与所有权相关不等于质量因果 |
| Amershi et al. (2019), [Guidelines for Human-AI Interaction](https://www.microsoft.com/en-us/research/wp-content/uploads/2019/01/Guidelines-for-Human-AI-Interaction-camera-ready.pdf)，CHI；10.1145/3290605.3300233 | D；49设计从业者、20产品、18条指南；表1可核情境信息及易调用／忽略／纠正原则 | 通用交互准则，不能直接推出三个独立页面最优 |
| Doshi & Hauser (2024), [Generative AI enhances individual creativity but reduces the collective diversity of novel content](https://arxiv.org/pdf/2312.00506)，Science Advances；10.1126/sciadv.adn5290 | D；Crossref核期刊／年份；作者全文核293写作者、600评价者、英语八句故事、1／5起意条件 | 期刊页面打开失败，方法按作者全文；不同作品相似性提高不是AI必然同质化 |
| Ashkinaze et al. (2025), [How AI Ideas Affect the Creativity, Diversity, and Evolution of Human Ideas](https://arxiv.org/pdf/2401.13481)，ACM CI；10.1145/3715928.3737481 | D；Crossref与[大会程序](https://ci.acm.org/2025/program/)确认正式身份；844人、48国、3414响应；高暴露条件下集体多样性增加，但未观察到个体原创性评分相应提升 | 物品替代用途任务及动态传播；与短小说任务不同，不能直接推翻Doshi的特定实验 |
| Lu, Zhou & Wang (2025), [WhatELSE](https://arxiv.org/html/2502.18641v1)，CHI；10.1145/3706598.3713363 | D；§4抽象层级及实例／大纲往返，§5 N12简单童话任务 | 不是三尺度产品对照；模板、小领域、新手与现场引导限制外推 |
| Chung et al. (2022), [TaleBrush](https://johnr0.github.io/assets/publications/CHI2022-TaleBrush.pdf)，CHI；10.1145/3491102.3501819 | D；§6.3控制代价、§7 N14、§8交互讨论，确有局部控制与编辑 | 仅主角运势、英语、旧模型；用户研究未正式对比其他共创工具 |
| Liu et al. (2024), [Lost in the Middle: How Language Models Use Long Contexts](https://aclanthology.org/2024.tacl-1.9/)，TACL；10.1162/tacl_a_00638 | D；位置控制的多文档问答和键值取用、U形性能及上下文长度关系 | 测试模型与任务特定；不能量化当前模型小说上下文损失 |
| Huang et al. (2024), [Large Language Models Cannot Self-Correct Reasoning Yet](https://proceedings.iclr.cc/paper_files/paper/2024/file/8b4add8b0aa8749d80a34ca5d941c355-Paper-Conference.pdf)，ICLR正式会议论文 | D；尤其§4 GSM8K等响应数下辩论弱于自洽采样，§5初始提示公平性 | 等响应数不是严格等token／延迟；不能泛化成所有自我改稿无用 |
| Kim et al. (2023), [FANToM: A Benchmark for Stress-testing Machine Theory of Mind in Interactions](https://aclanthology.org/2023.emnlp-main.890/)，EMNLP；10.18653/v1/2023.emnlp-main.890 | D；人物进出对话制造信息不对称，分别问事实／信念／信息接触 | 基准能启发知识边界验证，不能证明完整人物心理与角色弧 |

## 延伸材料：存在性已核与需要限缩

以下不是主报告20项核心。独立打开了原始链接，按有限范围保留；没有为凑来源数扩大主文。

| 来源 | 本次核验判断 |
| --- | --- |
| [Granovetter 1978](https://www.journals.uchicago.edu/doi/10.1086/226707)，AJS 83(6)，10.1086/226707 | 出版方元数据及摘要可读，正文需获取权限；只保留阈值分布与群体结果的摘要结论。不得声称读过推导、实证及全文。 |
| [Arthur 1989](https://gamef21.classes.ryansafner.com/readings/Arthur-1989.pdf) | 原期刊论文课程镜像可读；标题、作者及1989元数据一致。可以保留条件性锁定，不外推为制度必然结果；本次未独立核验历史实例争议。 |
| [Yu & Riedl 2013 Drama Management](https://faculty.cc.gatech.edu/~riedl/pubs/aiide13.pdf) | 作者PDF存在、题名作者可核；本次未独立重查其完整实验。主报告不把它作为自由小说生成或充分作者控制证明。 |
| [PROCO 2024](https://aclanthology.org/2024.emnlp-main.714.pdf) | 正式EMNLP，题名为 *Large Language Models Can Self-Correct with Key Condition Verification*；确有遮蔽条件核验法。不能外推短题答案验证能处理复杂小说开放判断。 |
| [Wunderlich et al. 2026](https://aclanthology.org/2026.acl-srw.1/)，10.18653/v1/2026.acl-srw.1 | 正式ACL Student Research Workshop论文，不是ACL主会长文。§3–4及限制已详核：1000题、非推理模型、MMLU-Pro／BBH、理论FLOPs与内存传输时间估算；并非实际API延迟或中文导演质量。小幅差异且区间重叠，不应据标题宣称多代理必有收益。 |
| [Joshi & Vogel 2025](https://nikhitajoshi.ca/papers/prompt-length-ownership.pdf) | 作者PDF存在，完整题名 *Writing with AI Lowers Psychological Ownership, but Longer Prompts Can Help*；本次未独立复核全部实验／排除流程，主报告若保留只作补充，不据此要求长表单。 |
| [The AI Architecture of Versu](https://versu.com/wp-content/uploads/2014/05/versu.pdf) | 原文§1–2明确强剧情／强自主、社会实践与角色分离、反馈界面经验；作者技术文稿、年份未明；不混IEEE论文。 |

## 排除与失败记录

- Pinter：分支已有三次官方正文打开失败记录。本次遵照主报告决定，不重试，也不纳入核心书目或核心论证；官方搜索摘录不足以冒充完整演讲审读。
- Senanayake Doctoral Consortium研究议程：不纳入效果证据；本次未再审全文，因此仅保留根代理排除决定，不计入独立核验数量。
- Semantic Scholar Graph API：web打开失败；随后实际HTTP请求 `ARXIV:2502.18641` 返回429 Too Many Requests。没有申请密钥或重试付费服务；替代为作者／出版方原文，并用Crossref API核IPOCL、Dramatron正式版、Doshi、Ashkinaze元数据。数据库匹配只确认元数据，不判定正文结论正确。
- DOI解析页：IPOCL及Dramatron的doi.org web打开Internal Error；Crossref API成功取得出版方登记信息。Doshi期刊DOI页面亦未取到正文，按作者全文及Crossref交叉核验。
- 本次没有复算统计检验、复现代码、购买付费全文、检索撤稿数据库或穷尽所有后续研究。没有将作者机构背景等同正式利益冲突声明。

## 综合可接受条件

主报告可以保留三尺度与21个方向的建议，但须持续区分：原论文实际观察、创作论视角、工程／产品推论及本项目待验证假设。所有数字须绑其样本和任务；不汇总成跨领域平均收益，不做meta-analysis，不把来源数量或已通过书目核验当产品质量证据。

未开展中文作者试用或当前业务模型实测；主要风险仍是把小任务的交互先例外推为长篇创作收益。
