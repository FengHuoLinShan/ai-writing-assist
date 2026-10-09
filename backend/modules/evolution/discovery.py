"""Source-bound, independently reviewed discovery on the existing Scene journal."""

import json
from copy import deepcopy
from functools import partial

from pydantic import ValidationError

from core.errors import ConflictError
from infrastructure.llm.collaboration import content_hash
from infrastructure.llm.schemas import LLMMessage
from modules.evolution.ledger import list_ledger, persist_discovery_claim
from modules.evolution.ledger_contracts import (
    DISCOVERY_METHOD_VERSION,
    DiscoveryChange,
    DiscoveryOutput,
    DiscoveryReview,
    LedgerClaim,
    LedgerDependency,
    LedgerEvidence,
)
from modules.evolution.reading import require_current_prefix
from modules.evolution.sampler import (
    DISCOVERY_OUTPUT_TOKENS,
    SCENE_CALL_TIMEOUT_SECONDS,
)
from modules.evolution.state_review import (
    SceneCallFailedError,
)
from modules.evolution.state_review import (
    settled_discovery_output_failure as _settled_output_failure,
)
from modules.evolution.world import freeze_value

CONDITIONS_SEMANTICS = (
    "有来源的追踪维度；字段自身不自动表达必要或充分条件。"
    "原文或作者明确的适用约束仍须保留，不因是触发/程度/体征就删除。"
    "首个单例优先明示可对照的基础状态/约束；当次具体触发、程度与伴随表现"
    "保留在原事实/context及竞争解释，不宣告其无关，不将整个情境逐词拼为必要门槛。"
)

DISCOVERY_PROMPT = (
    "你为小说作者维护非文学细节台账，只提出有证据的派生理解，不决定正史。"
    "statement写最小充分主张，不顺带添加未绑定的地名、触发、持有或人物关系；需要额外事实时先选它的原文观察。背景增强保留原观察资格，不以本轮传闻替换整个历史行为主张。"
    "只保留有后续追踪价值的条件行为、线索和明确承诺，不为每条普通持有/位置状态新增台账。"
    "分类：conditional_behavior是人物在明确条件下的动作，即使只有一次也属此类，不能因未证明习惯就改成clue；"
    "首次明确情境动作写这一次的事实，conditions是有据追踪维度，不声称必要/充分条件或习惯。首个单例优先使用原句明示可对照的基础状态/约束，不把具体触发、程度及伴随体征拼为合取门槛；这些事实仍保留在原事实/context和竞争解释，不宣告无关，原文或作者明示的适用限制仍须保留。无明示基础状态不自行推定。一次不足以证明规律不等于该次条件中的动作不受支持，不要求先积累多次才记录。"
    "原句明确将主体状态或约束与该动作相连时，conditions必须包含这一可对照基础条件；外部触发可另作情境，不以外部触发替代原明示基础状态。后续原文有相同基础状态但选择不同动作时，保留不同触发说明并审查例外；旧字段若漏了基础状态，以旧/新原句显式修订并交conditions_review，不默改。未明示状态或限制仍不猜。"
    "主题所追踪的是人物在原文明示可对照条件下的具体动作时，条件和动作可分处相邻观察/句子；原段须明确同主体且情境连续，显式绑定条件context与动作occurrence。不能因动作句没有重复条件词或涉及物件就以clue替代、漏掉该有源行为；有独立外观/符号/现象证据的额外clue仍可保留，按各自单位分类和计数。已承诺的履行/违背沿原commitment，不因也是人物动作就改成条件行为。不从共场或邻接臆造条件关系。"
    "clue是物件、符号或现象的待解释含义；commitment是明确承诺及后续履行/违背观察。"
    "条件行为主题绑定具体人物，其他人相似动作不能增强该个人主题，也不能改成跨人群规律。"
    "同一人物/物件的同一具体细节沿已有主题增强、收窄或重释；含义改变或兑现不另建同义条目。主题初始uncertain也应回读后沿同一ID查证，不能因置信或措辞变化就new。"
    "主题身份与事件共指、模态、传闻真伪和习惯机理分开。已确定同一主体的同一行为转述沿原主题保留主观背景；未亲见或不能确认同一习惯不是另建同义主题的理由，本批无完整旧主题就留待对应批次。"
    "每条context也须有原文支持其与目标细节的关联，可用有依据的代词或间接链；共场、背景真实、未提及该细节或未说明二者关联都不能创造关联。不相关来源不附入旧主题，缺描写仅记扫描覆盖、不逐主题新增未出现记录。"
    "conditions只列有原文支持的实质追踪条件，单次触发背景、体征或姿势保留为context和竞争解释，不自动成为每次须逐字重现的必要条件。更新保留旧实质条件并说明当前情境差别；旧条件混入背景时须有来源的明确重新解释，不能任取交集凑例外。明确同实质条件下不同选择可记例外，不证明机制、不否定旧动作、不改作者instance。"
    "旧conditions若把单次外部触发当成必要门槛，须用原情境和当前明示的对照状态/约束原句解释其资格。"
    "有据重释时在change中显式修订conditions、保留原情境为context并交conditions_review；"
    "不机械保留初次触发，也不任选共享词或删除原实质条件凑例外。无两侧来源就留待核实。"
    "新主题用new，已有主题只用提供的entry_id和revision更新，"
    "同名或相似不证明身份相同，无法归并则保留竞争解释及待核实。"
    "每条输出的change必须至少引用一条current_observation_ids，支持/反证只选择给定observation_id；合法changes=[]无需引文，仍如实报告coverage。"
    "没有描写不是反例；exception必须有明确同条件例外或反驳原主张的反证。单次行为不得概括为总是。"
    "每个新增断言都须有原句支持，包括仅补背景的状态。未描写不表示未发生；缺少交付描写、对象尚未到来或等候不证明承诺尚未兑现或违约，望向某处不证明人物身在该处。"
    "statement的每个事实性新增限定（含时间、位置、情境）都须由本项选择或继承的证据原句支持；全批其它句子未选择时不能用于补写这些限定，需要该来源就显式选择，否则仅保留待核实解释。"
    "复述使用原文姓名或原引语；性别代词须本项已选/继承原句支持，不能由姓名、旧摘要或后文推得。"
    "未出现某种描写等资料覆盖说明只放coverage_note/unresolved，不夹入主题statement；statement只保留原文支持的主题主张及本轮相关背景。"
    "unresolved/coverage_note也保持言语和指称资格；不把叙述说明写成角色自认，不把缺完整目标写成文本主体歧义。"
    "已依明确共指识别的动作主体不能又报同一代词未消歧；真正缺失/歧义/未覆盖范围仍如实保留。"
    "character_statement仅表示原角色实际陈述的内容，不能借旧承诺原话把机器推断包装成角色陈述；未获原句支持的推断只作竞争解释或unclear待核实主张。"
    "每个‘自述/承认/表示/告知/知情’归属都须原句支持。叙述者说明某人未亲见，不表示该人向别人自述未亲见；角色姓名作句子主语也不表示他是信息报告者。混合声明分句保留原言语、叙述与主观资格，不新增传递或知情关系。"
    "代词和共指只帮助识别所指对象，不自动证明持有、归属、保管、所在地、知情或因果关系；共场或相邻句不能补出这些关系，每个关系断言须另有原文依据。"
    "回忆、陈述、误信与发生事实分开；同一事件重述使用已给的occurrence_id，"
    "没有本场新动作只证明回忆/重述，不证明与哪条已存旧event同一。仅有一条已存候选不证明小说只发生过一次；首次/某声警报等指认在旧源未有唯一对应时，不猜原锚。可能是另次旧事件属于关键实例身份未决，recall的same_occurrence_as留null、实例保持unknown，不以机理/时间/见证细节的竞争解释掩盖错归；原已定位发生与作者决定保留。有源可唯一对应的间接指认亦可，不要求特定关键词或逐词复现。"
    "以原句整段回忆/叙述框架独立核动作主体，不盲信派生predicate或候选角色：回忆者、见证者与被回忆动作的主体分位。实际原动作才是recall实例见证，初见/回忆触发及同一性说明是context；源有主体冲突或真实歧义则待核实，不改主体或猜锚。"
    "文本主体与World资产复用资格分开：可依清楚段落语法/连续叙述焦点解析唯一先行主体，不机械取最近名字。new_candidate或尚未入库不等于文本人物未知，也不证明与既有资产同一；清楚的新人物可有supported单次事实，真实多候选或身份/动作续接不明仍待核实。"
    "每条evidence必须区分purpose：occurrence为本条目所计的具体动作/线索出现/承诺实例；"
    "发生须直接匹配该主题：相关物件的保管/携带不表示符号再次出现，为履约准备不表示兑现。此类动作只作context；缺少符号或履行描写时不补推发生。"
    "context为紧张等条件状态、背景、位置、人物指称等支持证据，不增加发生次数，same_occurrence_as必须null。只有purpose=occurrence的event/recall才可填写原发生身份；回忆的背景和同一性说明也用context/null。"
    "一次摸扣行为由紧张和摸扣两段共同支持时，只把摸扣观察标为occurrence。"
    "同主体明确同条件下未做该动作或选择不同动作，记exception_case的occurrence，保留conditions及条件证据；这不反驳过去某次动作存在。只有原句反驳原主张时才记counterevidence。正向、同条件例外与反证次数分开。"
    "事件身份使用提供的event_occurrence_id；同一发生的不同观察不算多次。"
    "新event的same_occurrence_as留null由宿主计算，或逐字填本观察提供的event_occurrence_id；其它event/recall链接只填原主题occurrences表内的occurrence_id，绝不能填observation_ids。观察ID与发生ID是两个域（链接旧event须同场同源重叠，跨场回忆用recall），"
    "更新自动继承旧证据及evidence_uses的既有用途，不必重新选择已认证的旧物理来源。若再次选择已认证旧实例，保留其role/purpose/occurrence_kind和发生锚，不把原物理出现重新改选为context；新解释的原句才作context。旧unknown需明确重新核实后才能升级，不能凭旧理解自证。"
    "发生单位沿目标原具体细节，不随新statement扩大：同人不同动作、与线索相关的后续交付或时间进展可以补背景，但不证明原符号/现象再次出现。承诺的明确兑现/违背是该承诺的进展实例，不能借同一动作给其它线索也计发生。"
    "条件行为中，原文可明确识别的同一人物的原具体动作被原文明示再次/又发生，可作为新行为实例；旧单次触发、姿势/位置或确切物件共指不自动成为其必要条件。保留旧情境与新触发差别、物件同一性未知，不断言同一World资产或每次必然动作。主体身份或具体动作续接未定、仅相似动作仍待核实，不仅凭同表面名归并。"
    "一句含多个行动但不能区分具体发生时用unknown。无法证明实例同一性也用unknown。"
    "旧主题statement是待核实理解，不能当作新证据循环自证。"
    "prior_review=uncertain的初始主题仅供再次查证身份与原文；新证据足够时沿原entry_id修订，"
    "不足则保留待核实资格，不能把旧候选当已知事实。作者决定独立保留：scope=instance只约束basis_revision/scene_index的那次记录，不禁止后来真实独立实例加入主题或增加发生数，也不自动修正后续实例；scope=theme才有作者明确扩大授权。作者拒绝/修正不被覆盖，"
    "新证据若与其冲突，保留中性提示。范围仅限给定正文与已提交来源，后文不能补前史。"
    "theme_index的label/subject_labels用于定位同一主体同一具体细节，摘要/prior_review仅用于路由与避免重复，不作为原文证据或更新目标。已有对应细节但本批无完整theme时留待该theme所在批，不new。"
    "更新只能引用historical_context中提供完整证据的theme；不在本批则留待后续批。"
    "target_entry_id/expected_revision逐字复制本批完整theme的entry_id/revision。prior_review理由、作者basis_revision和theme_index只是历史或路由，不能拿其中旧修订号更新。本批无完整目标则不输出其change。"
    "仅有theme_index/prior_review而无本批完整theme时，不得输出该主题的任何change；"
    "无获授权的变化时changes=[]，仍须返回coverage和coverage_note说明本批实际覆盖；不复制历史revision或填写null占位来更新。"
    "输出前逐项自查：每个新增限定有已选/继承原句，模态表达本项实际主张而不是照抄旧主题最后一条传闻；明确当前行为可用event_observed，混合主张须保留各句资格。回忆动作选recall并链接旧occurrences表中已证同一事件的锚；回忆者与旧动作主体不是同一个角色位。"
    "allow_new_themes为false时不能新增，只更新本批主题；缺描写不产生更新。"
    "只输出一个JSON对象，根字段仅changes/unresolved/coverage/coverage_note，不复制Schema的type/properties或添加包装，不带编号或Markdown。changes允许为空；"
    "coverage_note用一句简短中文说明范围，不复述观察ID和协议；unresolved只列具体待解问题。"
    "new也用于没有既有目标的独立待核实新条目，不带target_entry_id/expected_revision；question仅用于本批完整既有主题，和其它更新一样必须带准确UUID及修订。已有对应主题但本批缺完整目标时只记unresolved，不用占位符或另new，"
    "exception必须引用明确exception_case或counterevidence。明确负向实例应修订原主题，保留历史动作，不另建一个无关联的没做主题。coverage只报告此次输入，不把召回未检范围说成不存在。"
)
REVIEW_PROMPT = (
    "独立核对小说细节发现，不采信生成器结论。逐项返回supported/uncertain/rejected。"
    "输入conditions_semantics定义字段含义，不替原文判定任何具体条件无关。首个单例核明示基础状态及真实限制，不能把全情境字符串自动当必要合取门槛；触发、程度与体征保留原事实/context和竞争解释。先核该次事实与主张范围，再核是否有规律：明确人物在有据情境中的一次动作可supported为单次条件行为，不能仅因一次不足证明习惯/因果就否定这次事实。若statement超范围概括则uncertain/rejected。"
    "四份认证名单只能引用本项change.evidence已选择的observation_id，以及身份/修订匹配的target_theme.evidence_observation_ids；new没有继承集合。全批其它观察可用于独立对照或说明reason，不能填进认证名单、增补来源或改写证据绑定。"
    "转述中的性别代词须本项已选/继承原句支持；原姓名或第一人称原话不证明性别，旧摘要/后文不补签历史。"
    "独立核类别：主题所追踪的是人物在原文明示可对照条件下的具体动作时，属于conditional_behavior；明示同主体且连续情境的条件与动作可来自相邻观察，须均被本项绑定并区分context/occurrence。物件clue不能替代或漏掉该有源行为，有独立外观/符号/现象证据的额外clue仍可保留，按各自单位分类和计数；已承诺的履行/违背沿原commitment，不因也是人物动作就改类。未绑定条件不能默补，返回uncertain/rejected，不从邻接/共场臆造条件。"
    "先分别核主题身份与每条证据的相关性，再核全部断言、模态和实例资格。已确定同主体同细节的转述不能因模态/事件共指/习惯机理未确定就new；核对theme_index，缺完整旧主题不证明新主题。"
    "context须有原文关联依据，不能因共场、背景真实、不增次数、未提及目标或未说明关联就附入旧主题。有来源的代词/间接链可支持关联，不要求同UUID；主题不匹配或证据不相关的更新rejected，uncertain仅保留相关但未证实的理解。"
    "conditions核实质追踪条件而非要求每个单次触发、症状措辞和姿势逐字重现；保留原实质条件及当前情境差别，拒绝无来源说明的缩条件或任意交集。明确同实质条件的负向/不同选择不要求旧主题先有普遍规律，作者instance不禁止后续独立例外；它不证明机制或证伪旧动作。"
    "目标conditions有变化时单独填写conditions_review，核对旧/新条件及绑定原句，逐项说明保留/删除/重释资格；仅本轮传闻受支持不证明旧条件可删除。认证源仅本项绑定且本批可见，缺依据返回uncertain/rejected。new或条件未变用null。"
    "支持须覆盖每个新增断言，包括context-only增强；不增加发生次数不能替代主张与模态审查。背景相关、竞争解释或没有反证都不足以支持额外推断。"
    "逐一核新增事实性限定（包括‘在某地/某情境时’等修饰语）是否由本项选择或继承的绑定引文支持；全批某句确实存在但未被本项绑定仍不够。若补入该来源才成立，整项uncertain/rejected，不能默补或借其它项认证。"
    "未描写交付不证明未兑现；对象未到或等候也不证明此前是否履行，望向某处不证明身在该处。character_statement只能表示角色实际说出的内容，旧原话不支持新增履行状态。含这类无原句支持的断言返回uncertain或rejected，不能因仅作context就判supported。"
    "单例的具体外部触发不因曾写入conditions就成为必要门槛；若候选以原/新原句明确重释为可对照状态或约束，"
    "先以conditions_review核该调整，再判同条件例外。不能仅因初次触发不同拒绝有据重释后的负样本，"
    "也不能在候选未有据修订条件时偷放例外；保留原情境、当前差别和过去动作，不推出必要条件或习惯。"
    "逐项核说话人/信息提供者与叙述层：叙述者说某人未亲见，不证明该角色说过、承认过或告知他人此事；相关姓名和真实背景不够支持自述/知情关系。原句不含对应言语或认识归属时uncertain/rejected，不能从旧statement或predicate继承这类额外资格。"
    "资料覆盖说明与世界状态分别核对：‘没有交付描写’描述本次资料覆盖，不等于‘尚未兑现’，不能把前者改读为后者再降低合法背景/原承诺资格；coverage不证明履行与否。"
    "共指/代词仅识别对象，不推得持有、归属、保管、位置、知情或因果关系；即使同场相邻句可识别同一物件，每个新增关系仍须独立原文支持。"
    "检查原句是否支持主张/条件/主体/模态，exception_case是否为同主体明确同条件下的负向/不同选择实例，counterevidence是否实际反驳原主张，是否以未描写当反例；"
    "检查每项宿主附的target_theme原label/subject_labels/statement/category/revision，与变化语义逐项对照；UUID存在和category相同不证明是同一主题，不能把人物关系细节改成无关物件符号。目标null或缺完整theme不能靠生成label猜目标。检查期望修订、发生实例与回忆同一性，context必须same_occurrence_as=null，事件计数不能来自重复引用。"
    "依据target_theme原具体细节及evidence_uses核发生单位，不能随新statement扩大后重新定义旧主题计数。条件行为须该人物的同一动作，线索须原符号/现象再次出现；有源的后续不同动作、对象交付、时间进展及含义解释仅作相关context。承诺的明确兑现/违背则可认证该承诺的进展实例。关联成立不表示发生单位相同，相关动作误标occurrence须在context名单纠正。"
    "原文可明确识别的同一人物的原具体动作有原文明示再现时，行为实例、物理物件同一性和触发机理分别核。不要以未重复初次动作的位置/姿势、World物件new_candidate或旧单次触发不同自动拒绝该动作实例；同物件或机理未知另留待核实，不静默合并World资产，也不推普遍习惯。旧实质条件保留，旧单次触发只保留其情境；不能强求全部重现。真正主体/动作续接未定或仅相似动作仍uncertain。"
    "旧evidence_uses显示已存用途，认证资格仍需区分prior_review和occurrence_kind，uncertain/unknown不冒充已认证事实。已认证用途继承不需重列；若本项重新选择旧源，逐项核对它声明的新用途。原物理出现不能只因本轮解释而改成背景；名单与本项用途不一致时指出并uncertain/rejected，不凭reason补源或让宿主默删重复源。旧unknown仍可由实际原句本轮独立认证，不能从旧候选自证。"
    "occurrence_observation_ids只列已确认的正向support实例；exception_case实例只列exception_observation_ids，counterevidence实例只列counterevidence_observation_ids，三名单独立且不能互相借用。条件状态/背景不列。"
    "名单认证发生身份，不是新增次数：同一事件的合法recall也须列本场回忆动作的observation_id，不能因不是新事件就留空；次数由宿主按occurrence_id去重。明确复核旧unknown的原physical源可列旧ID，不能凭旧候选自证。"
    "最终逐条核对名单：回忆中的具体原动作是recall实例见证，应列相应角色的实例名单；回忆触发、见证者陈述和同一性说明才是context。理由确认是同一旧事件时不能因为不新增次数把该动作改列context；不确定原锚时保持unknown，不能用回忆者的背景陈述代替动作见证。"
    "回忆场先以原句整段框架独立核谁回忆、谁当时行动，不从派生predicate或候选角色倒填主体；真正动作而非初见/回忆触发进入recall名单。"
    "禁止机械猜最近名字，不禁止原段唯一先行主体、清楚语法连续及不冲突语义的共指解析；引用仍是原句，不由宿主补字。"
    "World new_candidate只关资产复用资格，不等于明示文本主体未知；"
    "首次清楚人物可supported，不强求旧World身份。多个主体或对象仍不唯一则uncertain，不自动合并资产。"
    "主体冲突或用途不能认证时整项uncertain/rejected，"
    "不以overall supported留下未认证的动作context。"
    "逐项核对主题所计的具体行为/线索出现/履行是否由原句直接支持：携带或保管相关物件不证明符号再次出现，准备交付不等于兑现承诺。只补这类背景时当前动作不列实例名单，不能在理由说context却认证为主题发生。"
    "一次动作的条件证据与动作证据不表示两次动作，拒绝其他人物增强个人主题。承诺兑现/违背的实例名单引用对应本场交付/违背动作，旧承诺原话仅提供条件，不能代替当前行动。线索旧物理出现仍保留，后续含义解释/转述只作context，不抹掉旧出现也不算新出现。"
    "exception_observation_ids只列有条件证据支持的明确同条件负向/不同选择实例；共享条件必须是旧主题实质追踪条件，附加搜查/姿态等情境保留为条件差别和竞争解释，不抹掉共享条件下明确负样本，也不证明机理或否定旧动作。不能任取交集或删除旧实质条件来凑例外；counterevidence_observation_ids只列实际反驳原主张的观察ID。过去一次动作不被后来没做证伪，缺描写不列。"
    "未核实实例同一性或不确定主张时名单可为空；需逐条复核purpose而不是照抄生成器。"
    "独立区分本场没有新动作与已证明指定旧event同一。仅一条已存候选不是全文唯一证明；原源没有唯一对应的首次/警报/见面指认时，不认证猜测same_occurrence_as。可能另次旧事件是关键锚歧义，候选已猜锚须uncertain/rejected；same_occurrence_as=null的合法回忆可保留unknown且不增已定位次数。不能整体supported认证原锚、再把该同一性未决只写竞争解释。有源唯一的间接指认亦可，不增关键词门槛。"
    "context_observation_ids明确列仅作背景/条件的观察，生成器误标occurrence也要在此纠正；不能只在reason写背景。与正向/例外实例名单不重叠；真正实例身份不确定时保留unknown，不冒充context。"
    "supported的所有新context都须列入context名单，counter/context可由counter名单独立认证。任一新增证据不相关应reject整项，不用整体supported加reason排除它；宿主不会仅凭reason剥源后保留statement。继承已认证用途不用每轮重列。"
    "new须核对theme_index，不能把同主体同细节的新含义/兑现或初始uncertain续证另建同义条目；本批缺完整theme不证明新主题。作者scope=instance只约束basis_revision/scene_index那次记录，不能禁止后续独立实例或有来源的主观背景/竞争解释加入原主题，不是全主题次数上限；增强可以仅补新context而不增加动作次数，传闻仍按主观原句而非事实核对；scope=theme才是扩大授权。旧机器主题不是证据，作者决定不能被改写。每项change的引用必须属于给定观察，且至少有本场新证据；合法空changes不要求引文，不要求为满足引用而造变化。"
    "历史未知回忆不得因复核名单重列动作就升级为新的物理event。后续有新来源唯一指认时，可显式选择该历史recall链接旧原event，逐pair两侧专审并绑定本轮指认context，不回算旧head或加物理发生。"
    "本轮recall绑定具体旧锚时，必须填写recall_identity_reviews逐pair核定：原source至少包含目标该occurrence原已定位event动作，新source包含本轮recall动作与指认context；仅本项已选/继承且本批可见。先独立对照旧事件原句与新指认是否唯一对应，再认证动作，不从无新动作或唯一已存候选倒推旧锚。不够则身份uncertain/rejected并整项待核。"
    "低置信、竞争解释、关键身份歧义可合法保留，但不足以支持的概括返回uncertain。"
    "支持必须覆盖整项主张，不能用逐字命中代替语义蕴含。每项直接使用changes内宿主提供的change_index（从0开始），不按自然语言编号或省略项后重新排序；每项序号只返回一次，漏项不放行。"
)


def method_fingerprint():
    return content_hash(
        [
            DISCOVERY_METHOD_VERSION,
            DISCOVERY_PROMPT,
            REVIEW_PROMPT,
            DiscoveryOutput.model_json_schema(),
            DiscoveryReview.model_json_schema(),
            LedgerClaim.model_json_schema(),
            {
                "chunk_characters": 16000,
                "request_characters": 50000,
                "scene_call_timeout_seconds": SCENE_CALL_TIMEOUT_SECONDS,
                "occurrence_binding": 14,
                "world_identity_context": "normalized_type_stage_scoped_v2",
                "known_output_failure_isolation": True,
                "generation_thinking": "discovery_max_other_high",
                "discovery_max_tokens": DISCOVERY_OUTPUT_TOKENS,
                "structured_transport": "deepseek_native_complete_stream_v1",
                "conditions_transition_review": 1,
                "target_semantic_descriptor": 6,
                "prior_review_scope": "verdict_only",
                "question_update": "separate_proposal_v1",
                "conditions_semantics": CONDITIONS_SEMANTICS,
                "new_uncertain_theme_context": True,
                "structured_parse": "single_closer_v2",
                "quarantine_invalid_changes": True,
                "new_theme_primary_batch": True,
            },
        ]
    )


def discovery_messages(inputs, *, review=False):
    return [
        LLMMessage(role="system", content=REVIEW_PROMPT if review else DISCOVERY_PROMPT),
        LLMMessage(
            role="user", content=json.dumps(inputs, ensure_ascii=False, sort_keys=True)
        ),
    ]


def _dependency(frozen, payload):
    return LedgerDependency(
        run_key=frozen.run_id,
        attempt_id=frozen.attempt_id,
        scene_id=payload["scene_id"],
        scene_index=payload["scene_index"],
        source_manifest_hash=frozen.source_manifest_hash,
    ).model_dump(mode="json")


def _event_key(scene_id, sources):
    return content_hash(
        [
            "evolution.occurrence.v2",
            str(scene_id),
            sorted(
                {
                    (
                        source["draft_id"],
                        source["content_hash"],
                        source["start_offset"],
                        source["end_offset"],
                    )
                    for source in sources
                }
            ),
        ]
    )


def event_occurrence_id(observation):
    # ponytail: exact source intervals identify a witnessed occurrence; semantic
    # overlap needs explicit reviewed linking, never an observation-text hash.
    return _event_key(
        observation["position"]["scene_id"],
        [quote["source_ref"] for quote in observation["evidence_quotes"]],
    )


def _normalized_evidence(evidence):
    # Occurrence anchors are immutable even when supporting citations expand.
    return [
        {**item, "occurrence_origin": item.get("occurrence_origin")} for item in evidence
    ]


def _records(payload, dependency):
    records = [
        {
            **item,
            "position": {
                "scene_id": payload["scene_id"],
                "scene_index": payload["scene_index"],
                "chapter_index": int(
                    item["source_ref"]["chapter_identity"].rsplit(":", 1)[-1]
                ),
            },
            "dependency": dependency,
        }
        for item in payload.get("compiled_observations", [])
    ]
    return [
        {
            **item,
            "event_occurrence_id": event_occurrence_id(item)
            if item["modality"] == "event_observed"
            else None,
        }
        for item in records
    ]


def _compact(item):
    return {
        key: item[key]
        for key in (
            "observation_id",
            "predicate",
            "modality",
            "position",
            "mentions",
            "event_occurrence_id",
        )
    } | {"quotes": [evidence["quote"] for evidence in item["evidence_quotes"]]}


def _chunks(values, budget=16000):
    """Every item is included once; oversized single items are disclosed by caller."""
    chunks, current, size = [], [], 0
    for value in values:
        weight = len(json.dumps(value, ensure_ascii=False))
        if current and size + weight > budget:
            chunks.append(current)
            current, size = [], 0
        current.append(value)
        size += weight
    return [*chunks, current] if current else chunks


async def prepare_discovery(db, store, frozen):
    payload = frozen.payload
    current = _records(payload, _dependency(frozen, payload))
    pairs = await store.load_committed_pairs(frozen.run_id)
    if pairs:
        parent = await store.load_frozen(pairs[-1][0].run_key, pairs[-1][0].attempt_key)
        await require_current_prefix(db, store, parent)
    themes, offset = [], 0
    while True:
        page = await list_ledger(
            db,
            frozen.novel_id,
            through_scene_index=payload["scene_index"] - 1,
            offset=offset,
            limit=100,
        )
        themes.extend(
            item
            for item in page["items"]
            if item["source_status"] == "current"
            and item["claim"]["realm"] == "history"
            and not item.get("proposal_target")
            and item["independent_review"].get("verdict") in {"supported", "uncertain"}
        )
        offset += len(page["items"])
        if offset >= page["total"]:
            break
    surfaces = {
        mention["surface"] for item in current for mention in item.get("mentions", [])
    }
    relevant, all_prior, by_id = [], 0, {item["observation_id"]: item for item in current}
    theme_scenes = {
        dependency["scene_id"]
        for theme in themes
        for dependency in theme["claim"]["dependencies"]
    }
    theme_evidence = {
        item["observation_id"] for theme in themes for item in theme["claim"]["evidence"]
    }
    for receipt, row in pairs:
        if receipt.committed_scene_index >= payload["scene_index"]:
            continue
        previous = await store.load_frozen(receipt.run_key, receipt.attempt_key)
        for item in _records(previous.payload, _dependency(previous, previous.payload)):
            all_prior += 1
            if (
                item["position"]["scene_id"] in theme_scenes
                or item["observation_id"] in theme_evidence
                or any(
                    mention["surface"] in surfaces for mention in item.get("mentions", [])
                )
            ):
                by_id[item["observation_id"]] = item
                relevant.append(item)
    for theme in themes:
        theme["claim"]["evidence"] = _normalized_evidence(theme["claim"]["evidence"])
    descriptors = [
        {
            "entry_id": theme["entry_id"],
            "revision": theme["revision"],
            "category": theme["claim"]["category"],
            "label": theme["claim"]["label"],
            "subject_labels": sorted(
                {
                    target["label"]
                    for target in theme["claim"]["targets"]
                    if target["label"]
                }
                | set(theme["claim"]["unresolved_subjects"])
            ),
            "statement": theme["claim"]["statement"],
            "conditions": theme["claim"]["conditions"],
            "conditions_semantics": CONDITIONS_SEMANTICS,
            "confidence": theme["claim"]["confidence"],
            "modality": theme["claim"]["modality"],
            "author_decision": theme["author_decision"],
            "prior_review": {"verdict": theme["independent_review"].get("verdict")},
            "occurrences": [
                {
                    "occurrence_id": identity,
                    "observation_ids": sorted(
                        {
                            evidence["observation_id"]
                            for evidence in theme["claim"]["evidence"]
                            if evidence["occurrence_id"] == identity
                        }
                    ),
                }
                for identity in sorted(
                    {
                        evidence["occurrence_id"]
                        for evidence in theme["claim"]["evidence"]
                        if evidence["occurrence_id"]
                    }
                )
            ],
            "evidence_observations": [
                _compact(by_id[item_id])
                for item_id in sorted(
                    {item["observation_id"] for item in theme["claim"]["evidence"]}
                    | {
                        item_id
                        for item_id, observation in by_id.items()
                        if observation["position"]["scene_id"]
                        in {
                            dependency["scene_id"]
                            for dependency in theme["claim"]["dependencies"]
                        }
                    }
                )
                if item_id in by_id
            ],
            "evidence_observation_ids": sorted(
                {item["observation_id"] for item in theme["claim"]["evidence"]}
            ),
            "evidence_uses": [
                {
                    key: evidence[key]
                    for key in (
                        "observation_id",
                        "role",
                        "purpose",
                        "occurrence_kind",
                        "occurrence_id",
                        "occurrence_origin",
                    )
                }
                for evidence in theme["claim"]["evidence"]
            ],
        }
        for theme in themes
    ]
    context_units = [{"theme": theme} for theme in descriptors] + [
        {"observation": _compact(item)} for item in relevant
    ]
    batches = []
    for current_group in _chunks([_compact(item) for item in current]):
        for context_index, context in enumerate(_chunks(context_units) or [[]]):
            batches.append(
                {
                    "conditions_semantics": CONDITIONS_SEMANTICS,
                    "scene_text": payload["scene_text"],
                    "allow_new_themes": context_index == 0,
                    "theme_index": [
                        {
                            key: descriptor[key]
                            for key in (
                                "category",
                                "label",
                                "subject_labels",
                                "prior_review",
                                "statement",
                                "conditions",
                                "conditions_semantics",
                            )
                        }
                        for descriptor in descriptors
                    ],
                    "scene_index": payload["scene_index"],
                    "current_observation_ids": [
                        item["observation_id"] for item in current_group
                    ],
                    "current_observations": current_group,
                    "historical_context": context,
                    "recall_scope": {
                        "matching_surfaces": sorted(surfaces),
                        "historical_candidates": len(relevant),
                        "total_prior_observations": all_prior,
                    },
                }
            )
    unsupported = []
    for index, batch in enumerate(batches):
        if len(json.dumps(batch, ensure_ascii=False)) > 50000:
            unsupported.append(index)
    return {
        "method_fingerprint": method_fingerprint(),
        "observations": by_id,
        "themes": {theme["entry_id"]: theme for theme in themes},
        "batches": batches,
        "unsupported_batches": unsupported,
        "coverage": {
            "scene_index": payload["scene_index"],
            "current_observations": len(current),
            "observation_gaps": payload.get("unresolved_parts", []),
            "historical_candidates": len(relevant),
            "total_prior_observations": all_prior,
            "themes_included": len(themes),
            "planned_batches": len(batches),
            "unsupported_batches": unsupported,
            "recall_scope": "本场观察、已存主题及同表面名历史候选；不是全部历史语义扫描",
        },
    }


def _evidence_use_key(item):
    return content_hash(
        [
            item["observation_id"],
            item["role"],
            item["source_ref"],
            item["purpose"],
            item["occurrence_kind"],
            item["occurrence_id"],
            item.get("occurrence_origin"),
        ]
    )


def _visible_observation_ids(batch):
    visible_observations = set(batch["current_observation_ids"])
    for unit in batch["historical_context"]:
        if "observation" in unit:
            visible_observations.add(unit["observation"]["observation_id"])
        if "theme" in unit:
            visible_observations.update(
                item["observation_id"] for item in unit["theme"]["evidence_observations"]
            )
    return visible_observations


def _compile_change(prepared, raw, batch):
    current_ids = set(batch["current_observation_ids"])
    visible_themes = {
        unit["theme"]["entry_id"]
        for unit in batch["historical_context"]
        if "theme" in unit
    }
    visible_observations = _visible_observation_ids(batch)
    change = DiscoveryChange.model_validate(raw)
    if change.action == "new" and not batch.get("allow_new_themes", True):
        raise ValueError("new_theme_outside_primary_batch")
    choices = change.evidence
    if not any(item.observation_id in current_ids for item in choices):
        raise ValueError("discovery_requires_current_evidence")
    old = (
        prepared["themes"].get(str(change.target_entry_id))
        if change.target_entry_id
        else None
    )
    if change.target_entry_id and (
        str(change.target_entry_id) not in visible_themes
        or old is None
        or old["revision"] != change.expected_revision
        or old["claim"]["category"] != change.category
    ):
        raise ValueError("theme_identity_or_revision_not_proven")
    if change.modality in {"author_plan", "figurative"}:
        raise ValueError("discovery_history_modality_not_supported")
    evidence = deepcopy(old["claim"]["evidence"]) if old else []
    dependencies = list(old["claim"]["dependencies"]) if old else []
    occurrences = {
        item["occurrence_id"]
        for item in (old["claim"]["evidence"] if old else [])
        if item["occurrence_id"]
    }
    targets = list(old["claim"]["targets"]) if old else []
    unresolved = set(old["claim"].get("unresolved_subjects", []) if old else [])
    for choice in choices:
        observation = prepared["observations"].get(choice.observation_id)
        if observation is None or choice.observation_id not in visible_observations:
            raise ValueError("observation_not_in_frozen_input")
        for mention in observation.get("mentions", []):
            resolution = mention.get("resolution") or {}
            identity = resolution.get("resolved_entity_id")
            if resolution.get("outcome") == "reuse" and identity:
                targets.append(
                    {
                        "domain": "world",
                        "kind": "entity",
                        "target_id": identity,
                        "label": mention["surface"],
                        "version_fingerprint": content_hash(
                            [resolution, observation["dependency"]]
                        ),
                        "version_kind": "observation_binding",
                        "binding": "resolved",
                    }
                )
            else:
                unresolved.add(mention["surface"])
        kind, occurrence = choice.occurrence_kind, None
        if choice.purpose == "context":
            if choice.same_occurrence_as:
                raise ValueError("context_cannot_claim_occurrence_identity")
            kind = "context"
        if kind == "event" and any(
            prior["purpose"] == "occurrence"
            and (
                prior.get("occurrence_origin") == "recall"
                or prior["occurrence_kind"] == "recall"
            )
            and (
                prior["observation_id"] == choice.observation_id
                or any(
                    prior["quote"] == quote["quote"]
                    and prior["source_ref"] == quote["source_ref"]
                    for quote in observation["evidence_quotes"]
                )
            )
            for prior in (old["claim"]["evidence"] if old else [])
        ):
            raise ValueError("recalled_source_cannot_create_new_event")
        if (
            kind == "event"
            and observation["modality"] == "event_observed"
            and choice.same_occurrence_as == event_occurrence_id(observation)
        ):
            occurrence = choice.same_occurrence_as
        elif choice.same_occurrence_as:
            if (
                kind not in {"event", "recall"}
                or choice.same_occurrence_as not in occurrences
            ):
                raise ValueError("occurrence_identity_not_proven")
            if kind == "event":
                originals = [
                    item
                    for item in evidence
                    if item["occurrence_id"] == choice.same_occurrence_as
                    and item["occurrence_kind"] == "event"
                ]
                if not any(
                    item["position"]["scene_id"] == observation["position"]["scene_id"]
                    and item["source_ref"]["draft_id"] == quote["source_ref"]["draft_id"]
                    and item["source_ref"]["content_hash"]
                    == quote["source_ref"]["content_hash"]
                    and max(
                        item["source_ref"]["start_offset"],
                        quote["source_ref"]["start_offset"],
                    )
                    < min(
                        item["source_ref"]["end_offset"],
                        quote["source_ref"]["end_offset"],
                    )
                    for item in originals
                    for quote in observation["evidence_quotes"]
                ):
                    raise ValueError("event_occurrence_identity_not_proven")
            occurrence = choice.same_occurrence_as
        elif kind == "event":
            occurrence = event_occurrence_id(observation)
        elif kind == "recall":
            # The original occurrence is unknown, so it cannot increase a count.
            kind = "unknown"
        for quote in observation["evidence_quotes"]:
            evidence.append(
                LedgerEvidence(
                    observation_id=observation["observation_id"],
                    position={
                        **observation["position"],
                        "chapter_index": int(
                            quote["source_ref"]["chapter_identity"].rsplit(":", 1)[-1]
                        ),
                    },
                    modality=observation["modality"],
                    quote=quote["quote"],
                    source_ref=quote["source_ref"],
                    role=choice.role,
                    purpose=choice.purpose,
                    occurrence_id=occurrence,
                    occurrence_kind=kind,
                    occurrence_origin=choice.occurrence_kind,
                ).model_dump(mode="json")
            )
        dependencies.append(observation["dependency"])
    evidence = list({_evidence_use_key(item): item for item in evidence}.values())
    dependencies = list(
        {(item["run_key"], item["attempt_id"]): item for item in dependencies}.values()
    )
    claim = LedgerClaim(
        category=change.category,
        label=change.label,
        statement=change.statement,
        conditions=change.conditions,
        confidence=change.confidence,
        modality=change.modality,
        competing_explanations=change.competing_explanations,
        evidence=evidence,
        dependencies=dependencies,
        targets=list({content_hash(item): item for item in targets}.values()),
        unresolved_subjects=sorted(unresolved),
        method_fingerprint=prepared["method_fingerprint"],
    )
    return {
        "change": change.model_dump(mode="json"),
        "claim": claim.model_dump(mode="json"),
    }


def compile_discovery(frozen):
    payload, accepted, pending, inspected = frozen.payload, [], [], []
    prepared = payload["discovery_preparation"]
    failed_batches = []
    for index, batch in enumerate(prepared["batches"]):
        if index in prepared["unsupported_batches"]:
            pending.append({"reason": "capacity_unsupported", "batch": index})
            continue
        visible_observations = _visible_observation_ids(batch)
        generated = payload.get(f"scene_discovery_{index}") or {}
        review_journal = payload.get(f"scene_discovery_review_{index}") or {}
        if _settled_output_failure(generated) or _settled_output_failure(review_journal):
            failed_batches.append(index)
            pending.append({"reason": "settled_output_failure", "batch": index})
            inspected.append(
                {
                    "batch": index,
                    "coverage": "not_checked",
                    "note": "模型输出未通过格式或契约校验；本批派生结果未放行。",
                }
            )
            continue
        if generated.get("stage") != "sampled":
            raise ValueError("discovery_batch_not_frozen")
        output = DiscoveryOutput.model_validate(generated["result"])
        quarantined = (generated.get("paid_call_receipt") or {}).get(
            "validation_quarantine", []
        )
        if quarantined:
            pending.append(
                {
                    "reason": "invalid_changes_quarantined",
                    "batch": index,
                    "count": len(quarantined),
                }
            )
        review = DiscoveryReview.model_validate(
            (payload.get(f"scene_discovery_review_{index}") or {}).get(
                "result", {"verdicts": []}
            )
        )
        verdicts = {}
        duplicates = set()
        for verdict in review.verdicts:
            if verdict.change_index in verdicts:
                duplicates.add(verdict.change_index)
            verdicts[verdict.change_index] = verdict
        inspected.append(
            {
                "batch": index,
                "coverage": "partial" if quarantined else output.coverage,
                "note": output.coverage_note,
            }
        )
        pending.extend(
            {"reason": "unresolved", "note": note, "batch": index}
            for note in output.unresolved
        )
        for ordinal, raw in enumerate(output.changes):
            verdict = verdicts.get(ordinal)
            try:
                item = _compile_change(prepared, raw, batch)
            except (ValueError, ValidationError) as error:
                pending.append(
                    {
                        "reason": str(error),
                        "batch": index,
                        "change": raw.model_dump(mode="json"),
                    }
                )
                continue
            if ordinal in duplicates or verdict is None or verdict.verdict == "rejected":
                pending.append(
                    {
                        "reason": "independent_review_not_supported",
                        "batch": index,
                        "change": raw.model_dump(mode="json"),
                    }
                )
                continue
            chosen_ids = {choice.observation_id for choice in raw.evidence}
            context_ids = set(verdict.context_observation_ids)
            bound_ids = {
                evidence["observation_id"] for evidence in item["claim"]["evidence"]
            }
            if (
                not (
                    set(verdict.occurrence_observation_ids)
                    | set(verdict.exception_observation_ids)
                    | set(verdict.counterevidence_observation_ids)
                    | context_ids
                )
                <= bound_ids
            ):
                pending.append(
                    {"reason": "review_evidence_not_in_change", "change": item["change"]}
                )
                continue
            negative_roles = {
                "exception_case": set(verdict.exception_observation_ids),
                "counterevidence": set(verdict.counterevidence_observation_ids),
            }
            if (
                negative_roles["exception_case"] & negative_roles["counterevidence"]
                or context_ids
                & (
                    set(verdict.occurrence_observation_ids)
                    | negative_roles["exception_case"]
                )
                or set(verdict.occurrence_observation_ids)
                & (negative_roles["exception_case"] | negative_roles["counterevidence"])
                or any(
                    choice.observation_id in ids and choice.role != role
                    for choice in raw.evidence
                    for role, ids in negative_roles.items()
                )
            ):
                pending.append(
                    {"reason": "review_evidence_role_conflict", "change": item["change"]}
                )
                continue
            confirmed_counter = set(verdict.counterevidence_observation_ids) & {
                choice.observation_id
                for choice in raw.evidence
                if choice.role == "counterevidence"
                and choice.observation_id in batch["current_observation_ids"]
            }
            confirmed_exception = set(verdict.exception_observation_ids) & {
                choice.observation_id
                for choice in raw.evidence
                if choice.role == "exception_case"
                and choice.purpose == "occurrence"
                and choice.observation_id in batch["current_observation_ids"]
            }
            if raw.action == "exception" and not (
                confirmed_exception or confirmed_counter
            ):
                pending.append(
                    {
                        "reason": (
                            "exception_or_counterevidence_not_independently_confirmed"
                        ),
                        "change": item["change"],
                    }
                )
                continue
            basis = prepared["themes"].get(str(raw.target_entry_id), {})
            recall_links_confirmed = True
            for choice in raw.evidence:
                if choice.occurrence_kind != "recall" or not choice.same_occurrence_as:
                    continue
                if any(
                    evidence["observation_id"] == choice.observation_id
                    and evidence["occurrence_id"] == choice.same_occurrence_as
                    and evidence["occurrence_kind"] == "recall"
                    and evidence["purpose"] == choice.purpose
                    and evidence["role"] == choice.role
                    for evidence in basis.get("claim", {}).get("evidence", [])
                ):
                    continue
                certificates = [
                    certificate
                    for certificate in verdict.recall_identity_reviews
                    if certificate.observation_id == choice.observation_id
                    and certificate.occurrence_id == choice.same_occurrence_as
                ]
                originals = {
                    evidence["observation_id"]
                    for evidence in basis.get("claim", {}).get("evidence", [])
                    if evidence["occurrence_id"] == choice.same_occurrence_as
                    and evidence["occurrence_kind"] == "event"
                    and evidence["purpose"] == "occurrence"
                    and evidence["role"] == choice.role
                }
                if len(certificates) != 1:
                    recall_links_confirmed = False
                    break
                certificate = certificates[0]
                if (
                    certificate.verdict != "supported"
                    or not certificate.original_observation_ids
                    or not set(certificate.identity_observation_ids)
                    & set(batch["current_observation_ids"])
                    or choice.observation_id not in certificate.identity_observation_ids
                    or not set(certificate.original_observation_ids)
                    <= (originals & bound_ids & visible_observations)
                    or not set(certificate.identity_observation_ids)
                    <= (bound_ids & visible_observations)
                ):
                    recall_links_confirmed = False
                    break
            if not recall_links_confirmed:
                pending.append(
                    {
                        "reason": "recall_identity_not_independently_confirmed",
                        "change": item["change"],
                    }
                )
                continue
            if basis and set(raw.conditions) != set(basis["claim"]["conditions"]):
                conditions_review = verdict.conditions_review
                if (
                    conditions_review is None
                    or conditions_review.verdict != "supported"
                    or not conditions_review.observation_ids
                    or not set(conditions_review.observation_ids)
                    <= (bound_ids & visible_observations)
                ):
                    pending.append(
                        {
                            "reason": "condition_change_not_independently_confirmed",
                            "change": item["change"],
                        }
                    )
                    continue
            inherited_uses = {
                _evidence_use_key(evidence)
                for evidence in basis.get("claim", {}).get("evidence", [])
            }
            unconfirmed_context = False
            for evidence in item["claim"]["evidence"]:
                certified_role = {
                    "exception_case": verdict.exception_observation_ids,
                    "counterevidence": verdict.counterevidence_observation_ids,
                }.get(evidence["role"], verdict.occurrence_observation_ids)
                if _evidence_use_key(evidence) in inherited_uses:
                    observation = prepared["observations"].get(evidence["observation_id"])
                    if (
                        verdict.verdict == "supported"
                        and evidence["purpose"] == "occurrence"
                        and evidence["occurrence_kind"] == "unknown"
                        and evidence.get("occurrence_origin") == "event"
                        and evidence["observation_id"] in certified_role
                        and evidence["observation_id"] in visible_observations
                        and evidence["observation_id"] not in context_ids
                        and evidence["modality"] == "event_observed"
                        and observation
                        and observation["modality"] == "event_observed"
                        and any(
                            quote["quote"] == evidence["quote"]
                            and quote["source_ref"] == evidence["source_ref"]
                            for quote in observation["evidence_quotes"]
                        )
                    ):
                        evidence.update(
                            occurrence_kind="event",
                            occurrence_id=event_occurrence_id(observation),
                        )
                    continue
                if evidence["observation_id"] not in chosen_ids:
                    continue
                if evidence["observation_id"] in context_ids:
                    evidence.update(
                        purpose="context", occurrence_kind="context", occurrence_id=None
                    )
                    continue
                if (
                    verdict.verdict == "supported"
                    and evidence["purpose"] == "context"
                    and not (
                        evidence["role"] == "counterevidence"
                        and evidence["observation_id"]
                        in verdict.counterevidence_observation_ids
                    )
                ):
                    unconfirmed_context = True
                    break
                if (
                    evidence["purpose"] == "occurrence"
                    and evidence["observation_id"] not in certified_role
                ):
                    # Each role needs its own certification; negative is never positive.
                    evidence.update(occurrence_kind="unknown", occurrence_id=None)
            if unconfirmed_context:
                pending.append(
                    {
                        "reason": "context_evidence_not_independently_confirmed",
                        "change": item["change"],
                    }
                )
                continue
            # Legal uncertainty remains a separate candidate, never the theme head.
            if verdict.verdict == "uncertain":
                for evidence in item["claim"]["evidence"]:
                    if (
                        evidence["observation_id"] in batch["current_observation_ids"]
                        and evidence["purpose"] == "occurrence"
                    ):
                        evidence.update(occurrence_kind="unknown", occurrence_id=None)
            accepted.append(
                {
                    **item,
                    "review": verdict.model_dump(mode="json"),
                    "batch": index,
                    "ordinal": ordinal,
                }
            )
    unique = {content_hash([item["change"], item["claim"]]): item for item in accepted}
    target_counts = {}
    for item in unique.values():
        target = item["change"].get("target_entry_id")
        if target:
            target_counts[target] = target_counts.get(target, 0) + 1
    accepted = []
    for item in unique.values():
        if target_counts.get(item["change"].get("target_entry_id"), 0) > 1:
            pending.append(
                {"reason": "competing_changes_same_theme", "change": item["change"]}
            )
        else:
            accepted.append(item)
    return {
        "method_fingerprint": prepared["method_fingerprint"],
        "changes": accepted,
        "pending": pending,
        "inspected": inspected,
        "coverage": {**prepared["coverage"], "failed_batches": failed_batches},
        "binding": content_hash(
            [
                frozen.attempt_id,
                frozen.source_manifest_hash,
                frozen.previous_receipt,
                prepared,
            ]
        ),
    }


async def finish_scene_discovery(db, store, frozen, source, caller):
    if frozen.payload.get("discovery_version", 0) != 1:
        return frozen
    from modules.evolution.pipeline import _run_scene_call

    frozen = await freeze_value(
        db,
        store,
        frozen,
        "discovery_preparation",
        lambda payload: prepare_discovery(
            db, store, frozen.model_copy(update={"payload": payload})
        ),
    )
    prepared = frozen.payload["discovery_preparation"]
    if prepared["method_fingerprint"] != method_fingerprint():
        raise ConflictError("发现方法已变化，请保留旧结果并重新核对")
    if frozen.payload.get("discovery_result"):
        return frozen
    for index, batch in enumerate(prepared["batches"]):
        if index in prepared["unsupported_batches"]:
            continue
        for reviewing in (False, True):
            key = f"scene_discovery{'_review' if reviewing else ''}_{index}"
            inputs = batch
            if reviewing:
                generated = DiscoveryOutput.model_validate(
                    frozen.payload[f"scene_discovery_{index}"]["result"]
                )
                if not generated.changes:
                    continue
                visible_themes = {
                    unit["theme"]["entry_id"]: unit["theme"]
                    for unit in batch["historical_context"]
                    if "theme" in unit
                }
                inputs = {
                    **batch,
                    "changes": [
                        {
                            "change_index": ordinal,
                            **change,
                            "target_theme": {
                                key: visible_themes[change["target_entry_id"]][key]
                                for key in (
                                    "entry_id",
                                    "revision",
                                    "category",
                                    "label",
                                    "subject_labels",
                                    "statement",
                                    "conditions",
                                    "conditions_semantics",
                                    "modality",
                                    "evidence_observation_ids",
                                    "evidence_uses",
                                    "occurrences",
                                )
                            }
                            if change["target_entry_id"] in visible_themes
                            else None,
                        }
                        for ordinal, change in enumerate(
                            generated.model_dump(mode="json")["changes"]
                        )
                    ],
                }
            envelope = {
                "method_fingerprint": prepared["method_fingerprint"],
                "attempt_id": frozen.attempt_id,
                "source_manifest_hash": frozen.source_manifest_hash,
                "previous_receipt": frozen.previous_receipt,
                "input": inputs,
            }
            journal = frozen.payload.get(key) or {}
            if _settled_output_failure(journal):
                if journal.get("input_hash") != content_hash(envelope):
                    raise ConflictError("失败批次的冻结输入已变化，不能跳过核对")
                break
            try:
                frozen = await _run_scene_call(
                    db,
                    store,
                    frozen,
                    source,
                    journal_key=key,
                    inputs=envelope,
                    call_inputs={"inputs": inputs},
                    call=partial(
                        caller, "review_discovery" if reviewing else "discover_details"
                    ),
                )
            except SceneCallFailedError:
                frozen = await store.load_frozen(frozen.run_id, frozen.attempt_id)
                if not _settled_output_failure(frozen.payload.get(key) or {}):
                    raise
                # Keep the settled failed batch visible; no result and no new paid retry.
                break

    return await freeze_value(
        db,
        store,
        frozen,
        "discovery_result",
        lambda payload: _compiled_result(frozen.model_copy(update={"payload": payload})),
    )


async def _compiled_result(frozen):
    return compile_discovery(frozen)


async def apply_discovery(db, store, frozen):
    """Recompile frozen proof at commit; ledger rows share the original receipt."""
    if frozen.payload.get("discovery_version", 0) != 1:
        return []
    result = compile_discovery(frozen)
    if (
        result != frozen.payload.get("discovery_result")
        or result["method_fingerprint"] != method_fingerprint()
    ):
        raise ConflictError("发现证明或方法已变化，不能提交旧结果")
    applied, pending = [], list(result["pending"])
    for item in result["changes"]:
        try:
            applied.append(
                await persist_discovery_claim(
                    db,
                    frozen.novel_id,
                    item["change"],
                    item["claim"],
                    operation_key=content_hash(
                        [
                            "discovery",
                            frozen.run_id,
                            frozen.attempt_id,
                            item["batch"],
                            item["ordinal"],
                        ]
                    ),
                    review=item["review"],
                )
            )
        except ConflictError as error:
            if error.code != "ledger_revision_conflict":
                raise
            pending.append(
                {"reason": "author_or_theme_revision_changed", "change": item["change"]}
            )
    latest = await store.load_frozen(frozen.run_id, frozen.attempt_id)
    await store.replace_frozen_payload(
        latest.model_copy(
            update={
                "payload": {
                    **latest.payload,
                    "discovery_materialization": {"applied": applied, "pending": pending},
                }
            }
        )
    )
    return pending
