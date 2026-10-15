# 三份计划的实施与验收对账

2026-10-16，root 依据三份 `docs/plans/2026-10-15-*.md` 与 ADR-0035至0041核对。
这是执行记录，不新增授权或改变原完成条件；三份TASK仍为active。当前固定710dbce431（产品C4 c579加Sol净fixture），
A3及追加Sol修复、A4独立审修均已合入；C4尾项Sol64a已合；C5/C0新批次仍未合入，任务笔记不改变验证范围。
用户要求Luna/max实施，Sol/high独立审查并直接修复。

| 批次 | 当前工程结果 | 仍需完成或满足的条件 |
| --- | --- | --- |
| 地图M0–M2 | 类型词表、空间契约、可选发现、增量候选、作者审核及助手操作已集成并审修 | 五题材真实端到端评测尚未通过 |
| 地图M3–M4 | 空间参考维度、按能力默认关闭、提醒与修复预览已集成并审修 | 真实Writing辅助对比与作者验收未完成；不能据单测开启默认能力 |
| 地图M5 | 保留前置和既有数据 | 势力路线图阶段1未交付，不提供旧无时效字段假装的领地图层 |
| 操作A0 | 纯SPEC目录、路由关联、真实HTTP留痕、隐私及保留期已集成并审修 | 历史无覆盖不能补造为完整观测 |
| 操作A1 | 第一波89项目录及主要真实领域入口已交付 | Writing真实章节重排、一般Story时间线新Luna/max已从02fa独立实施，见A1-A2-HANDOFF |
| 操作A2 | 目标DAG、范围冻结、分级确认、同根计量、恢复/漂移与真实PG已集成并审修 | 后续新目录扩展须保持旧冻结与真实父根约束 |
| 操作A3 | Sol fb62a4c66已合eab，十二项作者操作/真实摘要worker/Collab原子R3/浏览器完成独立审修 | root新库组合30项全部通过，旧目录预算停点与三普通回归均由Sol直接修；扩大普通后端8258项已通过 |
| 操作A4 | Luna b554经Sol bb6直接审修已合primary3caf，统计报表/边界序列/前向真实测量已装配 | root新库43PG/迁移/head/parity与门禁通过，扩大后端8914项与前端3180项、lint/build均通过；至少数周真实数据、真实前三高频模式选择和代码化不能用合成样本代替 |
| 档案C0 | 条目/兼容层/时点接口与有效期C0c已集成并审修 | 自定义类型借用内核、五题材档案预设、表格和JSON互通独立Sol已固定008d，等待C5顺序总装/目录冻结及原专库升级，见C0-TEMPLATE-INTERCHANGE-TAIL |
| 档案C1 | 还未启动整批 | 原计划前置为C0与演化第四阶段长篇跑通；该真实长篇门禁尚未通过，不能冒称已满足 |
| 副驾驶C2 | 对象简报、参考维度、人物卡与反应v2及真实HTTP/PG/界面已集成并审修 | 默认关闭能力仍需真实质量验收后再决定启用 |
| 副驾驶C3 | 七类统一提醒、只读结构缺项、处置及对象界面已集成并审修 | 短期前瞻表演格式、人物弧计划/实际、演化阅读状态提醒新Luna/max批次从c579开始实施；旧导入入口替换等待正式默认入口门禁 |
| 导演C4 | simulation_v3、有限结算、完整表演/素材/角度、历史树和独立参考已集成并审修 | 导演对象refs与事件分别转World候选已由Sol64a闭环合c579，root发现的2项偏好测试隔离失败已由Sol56f直接修并cherry710，45组合PG与8919普通后端均通过；RP协议迁移仍需独立Interaction评测；实际模型质量和作者使用尚未验收 |
| 推进C5 | Luna候选ac4已固定并交新Sol审修自由/导向推进、步长、交汇、钩子、历史、持续授权及Flow | Sol已修不可变guard/知识/预算/钩子和每步主路径TypeError并建新专库，当前进行顶层完整装配与实际Worker/PG验收；势力参与和方案分支等待外部路线图阶段1、2 |

旧bd31固定点root为5133后端/27PG/3173前端；eab合A3后的前端3175/lint/build/docs/repo-gates通过。
eab普通后端8255通过/3失败，30项PG为29通过/1 Goal失败。Sol净bf78将首轮完整目录9925→6812token，
保留全部ID/风险/费用和12000预算；f1e113e修三处普通回归及五confirm路由首调用前排他active/owner门禁。
两净fix已cherry至primary f5c6。root保留专库复验head/ORM parity、30项PG全部通过（10.57s），
日志/tmp/map-a3-primary-fixed-{head,metadata,pg}-20261016.log；docs/repo-gates通过。
扩大普通回归已完成8258通过/7跳过/1 deselected/1既有warning，295.54s；
/tmp/map-a3-primary-combined-fixed-20261016.log，-W error::RuntimeWarning。本固定点工程回归通过。
A4现合3caf：root新库43PG（11.69s）、fresh迁移/head/parity、docs/repo-gates通过；完整普通后端8914通过/9跳过/1 deselected/1既有warning（337.54s），RuntimeWarning转error。
全前端首轮3179pass/1旧GenerateView测试5秒超时，单例原断言通过；后端结束后以maxWorkers=2整套复验252文件3180项全通过（77.73s），lint/build通过，未改代码或超时。当前3caf A4工程固定点全绿，未验证数周真实使用。
C4 Sol与新C5 Sol按共享写权先后组合，C0模板互通Sol独立审修，三批代码均未合3caf。
C4此前Sol普通扩大8299项以及真实TaskWorker/HTTP/390与1280浏览器证据保留在C4-C5-HANDOFF。

真实地图R3保持诊断封存：失败回执、未运行项与未知用量保留；holdout不得解码或运行。
后续真实评测沿用用户确认的“模拟作者显式指定Scene地点”口径，必须在最终固定代码后重新
核对pipeline/owner模型/范围预算，不能盲目沿用旧51次上限或将unknown视为零。
地图World审核、显式地点指定、Writing成对对比、Assistant使用与评分都还没有真实通过。

主代理继续逐批集成与验证，不修产品或Git冲突；问题交Sol直接修复。本任务只有本地提交，
没有push、PR、main合并或部署授权。未完成条件不靠缩小范围或改名后续任务来关闭。

C4 Sol64a已合c579、root看图与原始HTTP日志；同源前端3182/lint/build沿用。root保留库从A4升级C4 head/parity通过；首轮43PG通过/2新fixture偏好隔离失败已由C5 Sol净56f直接修，cherry710后45组合PG全部通过（15.09s）。普通生产源码同源完整后端8919通过/9跳过/1 deselected/1既有warning（329.73s），RuntimeWarning转error。当前C4工程固定点全绿。C5已接共享槽且顺序负责C0 checkpoint总装；C0 Sol已退出，C3/A1两Luna独立实现并行。

C5原MAX发布序号差持续触发偏差由root识别，Sol撤销Writing发布触发，改真实完整Scene阅读成功投影与Evolution成功事务免费outbox；wp_read_count后继迁移在原专库增量升级/parity通过，完整触发/恢复PG仍待验。C3/A1新库hold最终线性头，未创建。
