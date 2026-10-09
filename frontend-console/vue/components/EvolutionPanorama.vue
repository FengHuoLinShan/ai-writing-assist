<template>
  <details class="evolution-panorama" @toggle="toggle">
    <summary>世界演化 · 作者全景与细节台账</summary>
    <p class="evolution-note">仅供作者查看。这里保留有依据的理解，不会自动采用为设定，也不进入角色可见信息。</p>
    <div class="evolution-actions">
      <label v-if="scenes.length">查看到哪一场<select aria-label="查看到哪一场" v-model="cutoff" :disabled="saving" @change="load"><option v-for="item in scenes" :key="item.id" :value="item.id">{{ item.title || '未命名场景' }}</option></select></label>
      <button class="btn btn-sm" type="button" :disabled="loading || saving" @click="load">{{ loading ? '正在回读…' : data ? '刷新全景' : '查看本场全景' }}</button>
    </div>
    <p v-if="error" role="alert">{{ error }}</p>
    <details v-if="failedDrafts.length" open class="evolution-backup-warning"><summary>有输入尚未可靠备份，请保存或复制后再关闭</summary><article v-for="item in failedDrafts" :key="item.entry_id"><p>{{ item.label }}</p><button type="button" class="btn btn-sm" @click="openEntry(item, undefined)">恢复这条未保存判断</button><label>可复制的输入<textarea readonly :value="copyText(item.draft)" rows="3"></textarea></label></article></details>
    <template v-if="data">
      <p class="evolution-coverage" role="status">{{ coverageLabel }} · {{ data.coverage.note }}</p>
      <p v-if="data.coverage.scope" class="evolution-note">本场 {{ data.coverage.scope.current_observations }} 条观察，召回 {{ data.coverage.scope.historical_candidates }} / {{ data.coverage.scope.total_prior_observations }} 条历史候选。{{ data.coverage.scope.recall_scope }}</p>
      <p v-if="data.coverage.method_status === 'method_changed'">发现方法已更新，旧结果保留，建议重新核对。</p>
      <details v-if="data.coverage.pending?.length"><summary>本轮待核实 {{ data.coverage.pending.length }} 项</summary><p v-for="(item, i) in data.coverage.pending" :key="i">{{ pendingLabel(item.reason) }}<span v-if="item.change?.statement">：{{ item.change.statement }}</span><span v-if="item.note">：{{ item.note }}</span></p></details>
      <section aria-label="截止场景的历史状态">
        <h4>本场状态变化</h4>
        <p v-if="data.changes">{{ data.changes.note }}</p>
        <div v-if="data.changes?.items.length" class="evolution-table-wrap"><table><thead><tr><th>对象 / 状态</th><th>前一场记录</th><th>截止本场</th></tr></thead><tbody><tr v-for="(change, i) in data.changes.items" :key="i"><td>{{ change.subject_label }}<small>{{ change.dimension_label }} · {{ fieldLabel(change.field) }} · {{ layerLabel(change.layer) }}</small></td><td>{{ change.before_known ? valueText(change.before) : '前值未记载' }}<button v-if="change.before_source?.checkpoint_id" class="btn btn-sm" type="button" @click="openCheckpoint(change.before_source)">此前依据</button></td><td>{{ change.after_known ? valueText(change.after) : '本场未记载，不能判定消失' }}<button v-if="change.after_source?.checkpoint_id" class="btn btn-sm" type="button" @click="openCheckpoint(change.after_source)">本场依据</button></td></tr></tbody></table></div>
        <p v-else>暂未识别到可对照的状态变化；缺少记录不表示没有变化。</p>
        <h4>截止场景的历史状态</h4>
        <p v-if="!facts.length">尚未建立可展示的场景状态；未记载不表示确定没有。</p>
        <div v-else class="evolution-table-wrap"><table><thead><tr><th>对象 / 维度</th><th>状态</th><th>性质与依据</th></tr></thead><tbody>
          <tr v-for="(fact, i) in facts" :key="i"><td>{{ fact.subject_label }}<small>{{ fact.dimensionLabel }} · {{ fieldLabel(fact.field) }}</small></td><td>{{ valueText(fact.value) }}</td><td>{{ layerLabel(fact.layer) }} · {{ fact.confidence === 'confirmed' ? '作者确认' : '推导' }}{{ fact.possibly_false ? ' · 可能误信' : '' }}
            <details v-if="fact.provenance"><summary>字段依据</summary><SceneFieldProvenance :project-id="projectId" :field-label="fieldLabel(fact.field)" :provenance="fact.provenance" /></details>
            <button v-else-if="fact.source?.checkpoint_id" class="btn btn-sm" type="button" @click="openCheckpoint(fact.source)">整体依据</button><small v-else>来源待核实</small>
          </td></tr>
        </tbody></table></div>
        <p v-for="dimension in gaps" :key="dimension.dimension">{{ dimension.label }}：{{ dimension.gap_reason || '尚未建立可靠状态' }}</p>
        <p v-for="warning in data.state.warnings" :key="warning">{{ warning }}</p>
        <SceneCheckpointHistory :project-id="projectId" :scene-id="cutoff" @source="openCheckpoint" />
      </section>
      <details><summary>当前作者计划 · {{ data.plans.items.length }} 项</summary><p>{{ data.plans.note }}</p>
        <p v-if="!data.plans.items.length">尚未记录线索与回收计划。</p>
        <div v-else class="evolution-table-wrap"><table><thead><tr><th>线索</th><th>含义</th><th>计划章节</th></tr></thead><tbody><tr v-for="plan in data.plans.items" :key="plan.id"><td>{{ plan.name }}</td><td>{{ plan.summary || plan.surface_meaning }}<p v-if="plan.hidden_meaning">真相：{{ plan.hidden_meaning }}</p></td><td>埋设：{{ plan.planned_seed_chapter || '未定' }}<br>回收：{{ plan.planned_payoff_chapter || '未定' }}</td></tr></tbody></table></div>
      </details>
      <details><summary>排演与试改 · 独立查看</summary><p>排演结果只表示所选假设下的候选走向，不归入已发生历史。请在场景推演中回看人物反应与排演依据。</p><button class="btn btn-sm" type="button" @click="getRouter().navigate('scene', cutoff)">去场景推演查看排演</button></details>
      <section aria-label="细节台账">
        <h4>细节台账</h4>
        <form class="evolution-actions" @submit.prevent="search">
          <label>类别<select v-model="category" aria-label="类别"><option value="">全部</option><option value="conditional_behavior">条件行为</option><option value="clue">线索</option><option value="commitment">承诺</option></select></label>
          <label>查找条目<input v-model="query" type="search" maxlength="200"></label><button class="btn btn-sm" :disabled="loading" type="submit">筛选</button>
        </form>
        <p role="status">筛选后 {{ ledger.total }} 项。{{ !ledger.items.length ? '当前展示为空；扫描覆盖见上方，不据此判断正文中不存在。' : '' }}</p>
        <div v-if="ledger.items.length" class="evolution-table-wrap"><table><thead><tr><th>条目与条件</th><th>证据</th><th>资格 / 作者决定</th></tr></thead><tbody>
          <tr v-for="item in ledger.items" :key="item.entry_id"><td><button class="evolution-entry" type="button" :disabled="saving" @click="openEntry(item)">{{ item.claim.label }}</button><p>{{ statementFor(item) }}</p><small v-if="item.previous_supported">此前获支持的理解：{{ item.previous_supported.claim.statement }}</small><small>{{ categoryLabel(item.claim.category) }} · {{ modalityLabel(item.claim.modality) }}</small><p v-if="item.claim.conditions.length">条件：{{ item.claim.conditions.join('；') }}</p></td><td>{{ item.counts.occurrences }} 次已定位发生<small v-if="item.counts.exception_occurrences">{{ item.counts.exception_occurrences }} 次同条件例外</small><small v-if="item.counts.counter_occurrences">{{ item.counts.counter_occurrences }} 次明确反证</small><br>{{ item.counts.observations }} 条观察 · {{ item.counts.sources }} 段来源<small v-if="item.counts.extractions != null">{{ item.counts.extractions }} 轮来源抽取（不代表发生次数）</small><small v-if="item.counts.unknown_occurrences">{{ item.counts.unknown_occurrences }} 条发生身份未定</small></td><td>{{ reviewLabel(item) }}<small>{{ sourceLabel(item.source_status) }}</small><small v-if="item.method_status !== 'current'">方法已更新，建议核对</small><small v-if="item.identity_status && item.identity_status !== 'current'">关联身份待核实</small><small>{{ decisionFor(item) }}</small></td></tr>
        </tbody></table></div>
        <div class="evolution-actions"><button v-if="offset" class="btn btn-sm" type="button" :disabled="loading" @click="page(Math.max(0, offset - 30))">上一页</button><button v-if="offset + ledger.items.length < ledger.total" class="btn btn-sm" type="button" :disabled="loading" @click="page(offset + 30)">下一页</button></div>
      </section>
    </template>
      <section v-if="entry" class="evolution-detail" aria-label="条目详情">
        <h4>{{ entry.claim.label }} · 第 {{ entry.revision }} 次记录</h4><p>{{ entry.claim.statement }}</p>
        <p role="status">{{ reviewLabel(entry) }}<span v-if="entry.independent_review?.reason">：{{ entry.independent_review.reason }}</span></p><p v-if="entry.previous_supported">此前获支持的理解（第 {{ entry.previous_supported.revision }} 次）：{{ entry.previous_supported.claim.statement }}</p><p>{{ sourceLabel(entry.source_status) }} · {{ modalityLabel(entry.claim.modality) }}</p>
        <p v-if="entry.author_decision.corrected_statement">{{ decisionApplies(entry) ? '适用的作者修正' : '此前具体记录的作者修正（未扩大到本次发现）' }}：{{ entry.author_decision.corrected_statement }}</p>
        <p v-if="entry.identity_status === 'needs_revalidation'">关联对象已变化或有歧义，需重新核对身份。</p>
        <p v-if="entry.claim.targets.length">关联对象：{{ entry.claim.targets.map(item => item.label || '未记录名称的对象').join('、') }}（按原始观察绑定）</p>
        <p v-if="entry.claim.unresolved_subjects?.length">身份待核实：{{ entry.claim.unresolved_subjects.join('、') }}</p>
        <p v-for="text in entry.claim.competing_explanations" :key="text">其他解释：{{ text }}</p>
        <details open><summary>支持、例外、反证与回忆</summary><article v-for="(evidence, i) in entry.claim.evidence" :key="i"><small>第 {{ evidence.position.chapter_index }} 章 · {{ evidence.role === 'counterevidence' ? '明确反证' : evidence.role === 'exception_case' ? '同条件例外' : '支持依据' }} · {{ evidence.purpose === 'context' && evidence.occurrence_kind !== 'context' ? '实例资格待按当前方法核对，未计入次数' : occurrenceLabel(evidence.occurrence_kind) }}</small><blockquote>{{ evidence.quote }}</blockquote><button class="btn btn-sm" type="button" @click="openEvidence(i)">回看这一版原文</button></article></details>
        <label>历史修订<select aria-label="历史修订" :value="entry.revision" :disabled="saving" @change="openRevision(Number($event.target.value))"><option v-for="version in entry.history" :key="version.revision" :value="version.revision">第 {{ version.revision }} 次 · 第 {{ version.scene_index + 1 }} 场 · {{ revisionLabel(version.kind) }}</option></select></label>
        <p v-if="entry.revision !== entry.head_revision">这是历史记录。<button class="btn btn-sm" type="button" @click="rebase">读取最新记录，保留输入</button></p>
        <form v-if="draft" @submit.prevent="saveDecision">
          <fieldset :disabled="saving"><legend>我的判断</legend>
            <label>处理方式<select v-model="draft.decision" aria-label="处理方式"><option value="unreviewed">留待核对</option><option value="keep">保留这项理解</option><option value="reject">不接受这项理解</option><option value="corrected">按我的理解修正</option></select></label>
            <label v-if="draft.decision === 'corrected'">修正内容<textarea v-model="draft.corrected_statement" maxlength="2000" required rows="3"></textarea></label>
            <label>作者备注<textarea v-model="draft.note" maxlength="2000" rows="2"></textarea></label>
            <details><summary>判断适用范围</summary><p>默认只针对这次记录及其场景、对象。后续机器整理会保留你的判断。</p><label><input v-model="draft.scope" type="checkbox" true-value="theme" false-value="instance">扩大到这个主题的后续理解</label><label v-if="draft.scope === 'theme'"><input v-model="draft.confirmed_scope_expansion" type="checkbox" required>我确认扩大判断范围</label></details>
            <button class="btn btn-primary" type="submit" :disabled="!dirty || entry.revision !== entry.head_revision">{{ saving ? '正在保存…' : '保存我的判断' }}</button>
          </fieldset>
        </form>
        <p v-if="message" role="status">{{ message }}</p><p v-if="decisionError" role="alert">{{ decisionError }}</p>
        <button v-if="conflict" class="btn btn-sm" type="button" :disabled="saving" @click="rebase">读取新版并保留输入，核对后再保存</button>
        <p v-if="dirty && !backupError">输入已在本机备份，尚未保存到作品。</p><p v-if="backupError" role="alert">本机备份失败，输入仍在当前会话。保存成功或复制输入后再关闭页面。</p>
        <label v-if="backupError">可复制的输入<textarea readonly :value="copyText(draft)" rows="4"></textarea></label>
      </section>
      <section v-if="source" class="evolution-source" aria-label="回读的来源"><h4>来源回读</h4><p v-if="source.historical">这是历史版本，当前稿可能已修改。</p><p>{{ source.summary }}</p><blockquote v-if="source.context">{{ source.context }}</blockquote><p v-if="source.gap">{{ source.gap }}</p><button class="btn btn-sm" type="button" @click="source = null">收起来源</button></section>
      <p v-if="sourceError" role="alert">{{ sourceError }}</p>
  </details>
</template>

<script>
import { reactive } from "vue"
// ponytail: retain failed local backups in this browser session; no separate draft service.
const sessionDrafts = new Map()
const backupFailures = reactive(new Map())
</script>
<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue"
import { getApi, getRouter, registerAuxiliaryLeaveGuard } from "../bridge/index.js"
import SceneFieldProvenance from "../views/writing/components/SceneFieldProvenance.vue"
import SceneCheckpointHistory from "../views/writing/components/SceneCheckpointHistory.vue"
import { sceneFieldProvenance } from "../views/writing/sceneLensModel.js"
const props = defineProps({ projectId: { type: String, required: true }, sceneId: { type: String, required: true } })
const data = ref(null), ledger = ref({ items: [], total: 0 }), scenes = ref([]), cutoff = ref(props.sceneId)
const loading = ref(false), saving = ref(false), opened = ref(false), error = ref("")
const category = ref(""), query = ref(""), offset = ref(0), entry = ref(null), draft = ref(null)
const decisionError = ref(""), message = ref(""), backupError = ref(false), conflict = ref(false)
const source = ref(null), sourceError = ref("")
let generation = 0, detailGeneration = 0, sourceGeneration = 0, pending = null, activeKey = ""
const baseline = ref("")
const api = () => getApi().evolution
const failedDrafts = computed(() => [...backupFailures].filter(([key]) => key.startsWith(`evolution-draft:${props.projectId}:`)).map(([, value]) => value))
function copyText(value) { return `判断：${decisionLabel(value.decision)}\n修正：${value.corrected_statement || '无'}\n备注：${value.note}\n范围：${value.scope === 'theme' ? '整个主题' : '这次具体记录'}` }
function decisionApplies(item) { const value = item.author_decision || {}; return value.scope === "theme" || item.revision === value.basis_revision + 1 }
function statementFor(item) { return decisionApplies(item) && item.author_decision.corrected_statement || item.claim.statement }
function decisionFor(item) { return `${decisionApplies(item) ? '' : item.author_decision.decision ? '此前记录：' : ''}${decisionLabel(item.author_decision.decision)}` }
const categories = { conditional_behavior: "条件行为", clue: "线索", commitment: "承诺" }
const categoryLabel = key => categories[key] || "待分类"
const reviewLabel = item => item.proposal_target && item.independent_review?.verdict === "supported" ? "待核提案，问题依据已核对" : ({ supported: "独立核对支持", uncertain: "不确定候选，独立核对未充分支持", rejected: "独立核对不支持" })[item.independent_review?.verdict] || "独立核对状态未记录"
const sourceLabel = key => key === "current" ? "来源未变化" : "来源已变化，待核对"
const decisionLabel = key => ({ keep: "作者保留", reject: "作者不接受", corrected: "作者修正", unreviewed: "待作者核对" })[key] || "待作者核对"
const modalityLabel = key => ({ event_observed: "发生观察", character_statement: "人物陈述", belief: "信念", hypothesis: "待核实理解", author_plan: "作者计划", figurative: "比喻" })[key] || "待核实理解"
const occurrenceLabel = key => ({ event: "发生实例", recall: "已有事件回忆", claim: "陈述", context: "条件或背景支持，不增加发生次数", unknown: "发生身份未定" })[key] || "发生身份未定"
const revisionLabel = key => ({ new: "新发现", enhance: "增强", narrow: "收窄", exception: "例外或反证变化", question: "待核实", author_decision: "作者判断" })[key] || "历史记录"
const layerLabel = key => ({ fact: "事实层", belief: "信念层", observation: "观察层" })[key] || "待核实"
const pendingLabel = key => ({ settled_output_failure: "模型输出未通过格式或契约校验，该批未检查且未写入台账", condition_change_not_independently_confirmed: "条件变化尚未通过独立核对，原条件保留", counterevidence_not_independently_confirmed: "反证尚未通过独立核对", exception_or_counterevidence_not_independently_confirmed: "例外或反证尚未通过独立核对", review_evidence_not_in_change: "复核引用未绑定本项证据", review_evidence_role_conflict: "实例的正向、例外或反证资格存在分歧，需核对", invalid_changes_quarantined: "部分变化格式或目标修订不合法，已隔离", new_theme_outside_primary_batch: "重复新增请求已隔离", capacity_unsupported: "这一批超出方法容量，尚未检查", competing_changes_same_theme: "同一主题有不同修订，需核对", author_or_theme_revision_changed: "作者判断或主题已有新版本", unresolved: "仍需核实", independent_review_not_supported: "独立核对未支持该项" })[key] || "证据或身份尚未通过核对"
const fieldLabel = key => ({ state: "状态", location: "所在", location_id: "所在", custody_holder: "保管人", custody_owner: "所有人", opening_key_id: "所需钥匙", opening_moon_phase: "所需月相", moon_phase: "月相", knowledge: "所知", summary: "概述", text: "内容", status: "状态", relation: "关系", current_state: "当前状态" })[key] || "状态记录"
const coverageLabel = computed(() => ({ checked: "已检查本次召回范围", partial: "部分检查", not_checked: "未检查", not_enabled: "未启用发现", incomplete: "发现尚未完成", source_changed: "来源变化，待重新核对" })[data.value?.coverage.status] || "尚未核对")
const facts = computed(() => (data.value?.state.dimensions || []).flatMap(dimension => dimension.facts.map(fact => ({ ...fact, dimensionLabel: dimension.label, provenance: provenanceFor(fact) }))))
const gaps = computed(() => (data.value?.state.dimensions || []).filter(item => item.status !== "ok"))
const draftText = computed(() => JSON.stringify(draft.value))
const dirty = computed(() => !!draft.value && draftText.value !== baseline.value)
function provenanceFor(fact) { const value = sceneFieldProvenance(fact.source?.provenance); return value ? { ...value, eventId: null } : null }
function valueText(value) {
  const names = data.value?.state.subject_labels || {}
  if (Array.isArray(value)) return value.map(valueText).join("、")
  if (value && typeof value === "object") return Object.entries(value).filter(([key]) => !key.startsWith("_") && ["summary", "text", "description", "name", "location", "custody_holder", "custody_owner", "opening_key_id", "opening_moon_phase"].includes(key)).map(([key, item]) => `${fieldLabel(key)}：${valueText(item)}`).join("；") || "已记录，具体内容待核对"
  return String(names[value] || ({ full: "月圆", new: "新月", true: "是", false: "否" })[value] || (value ?? "未记载")).replace(/[0-9a-f]{8}-[0-9a-f-]{27,}/gi, "未记录名称的对象")
}
function preferencesKey() { return `evolution-view:${props.projectId}:${props.sceneId}` }
function rememberView() { try { localStorage.setItem(preferencesKey(), JSON.stringify({ category: category.value, query: query.value, offset: offset.value, cutoff: cutoff.value })) } catch { /* preferences do not protect author input */ } }
function backup() {
  if (!draft.value || !activeKey || !dirty.value) return
  const value = JSON.parse(JSON.stringify({ draft: draft.value, baseline: baseline.value, pending, entry_id: entry.value.entry_id, label: entry.value.claim.label }))
  sessionDrafts.set(activeKey, JSON.parse(JSON.stringify(value)))
  try { localStorage.setItem(activeKey, JSON.stringify(value)); backupFailures.delete(activeKey); backupError.value = false }
  catch { backupFailures.set(activeKey, value); backupError.value = true }
}
watch(draft, () => { pending = null; backup() }, { deep: true, flush: "sync" })
function resetScope() {
  generation++; detailGeneration++; sourceGeneration++
  backup(); data.value = null; ledger.value = { items: [], total: 0 }; scenes.value = []
  entry.value = draft.value = source.value = null; activeKey = ""; pending = null
  loading.value = saving.value = conflict.value = backupError.value = false
  error.value = decisionError.value = message.value = sourceError.value = ""
  category.value = query.value = ""; offset.value = 0; cutoff.value = props.sceneId
  try { const saved = JSON.parse(localStorage.getItem(preferencesKey()) || "null"); if (saved) { category.value = saved.category || ""; query.value = saved.query || ""; offset.value = saved.offset || 0; cutoff.value = saved.cutoff || props.sceneId } } catch { /* ignore unreadable preferences */ }
  if (opened.value) void load()
}
watch(() => [props.projectId, props.sceneId], resetScope)
async function toggle(event) { opened.value = event.target.open; if (opened.value && !data.value) { resetScope() } }
async function load() {
  const token = ++generation, project = props.projectId, scene = cutoff.value
  detailGeneration++; sourceGeneration++; backup(); entry.value = draft.value = source.value = null; activeKey = ""
  data.value = null; ledger.value = { items: [], total: 0 }
  loading.value = true; error.value = ""
  try {
    const result = await api().panorama(project, scene)
    const ordered = await getApi().outline.listScenesOrdered(project)
    const page = await api().ledger(project, { through_scene_index: result.state.scene_index, category: category.value, query: query.value, offset: offset.value, limit: 30 })
    if (token !== generation) return
    data.value = result; scenes.value = Array.isArray(ordered) ? ordered : ordered.items; ledger.value = page; rememberView()
  } catch (cause) { if (token === generation) error.value = cause.message || "全景暂时无法读取，已有输入保留。" }
  finally { if (token === generation) loading.value = false }
}
async function page(next) {
  const token = ++generation; offset.value = next; loading.value = true; error.value = ""
  try { const result = await api().ledger(props.projectId, { through_scene_index: data.value.state.scene_index, category: category.value, query: query.value, offset: next, limit: 30 }); if (token === generation) { ledger.value = result; rememberView() } }
  catch (cause) { if (token === generation) error.value = cause.message || "条目暂时无法读取。" }
  finally { if (token === generation) loading.value = false }
}
function search() { return page(0) }
function formFor(item) { const value = item.current_author_decision || item.author_decision || {}; return { expected_revision: item.head_revision, decision: value.decision || "unreviewed", note: value.note || "", corrected_statement: value.corrected_statement || "", scope: value.scope || "instance", confirmed_scope_expansion: value.scope === "theme" && value.confirmed_scope_expansion === true } }
async function openEntry(item, revision = item.revision, keep = false) {
  const token = ++detailGeneration; backup(); sourceGeneration++; source.value = null; decisionError.value = sourceError.value = message.value = ""
  try {
    const result = await api().ledgerEntry(props.projectId, item.entry_id, revision)
    if (token !== detailGeneration) return
    const retained = keep ? JSON.parse(JSON.stringify(draft.value)) : null
    activeKey = `evolution-draft:${props.projectId}:${item.entry_id}`; entry.value = result
    const form = formFor(result); baseline.value = JSON.stringify(form)
    let saved = sessionDrafts.get(activeKey)
    if (!saved) { try { saved = JSON.parse(localStorage.getItem(activeKey) || "null") } catch { /* session copy retained */ } }
    draft.value = retained ? { ...retained, expected_revision: result.head_revision } : saved?.draft || form
    pending = retained ? null : saved?.pending || null
    conflict.value = draft.value.expected_revision !== result.head_revision
    backup()
  } catch (cause) { if (token === detailGeneration) decisionError.value = cause.message || "条目暂时无法读取。" }
}
function openRevision(revision) { return openEntry(entry.value, revision, true) }
function rebase() { return openEntry(entry.value, null, true) }
async function saveDecision() {
  if (saving.value) return
  const token = detailGeneration, project = props.projectId, id = entry.value.entry_id, key = activeKey
  pending ||= { ...draft.value, corrected_statement: draft.value.decision === "corrected" ? draft.value.corrected_statement : null, operation_id: crypto.randomUUID() }
  backup(); saving.value = true; decisionError.value = message.value = ""
  try {
    await api().ledgerDecision(project, id, pending)
    sessionDrafts.delete(key); backupFailures.delete(key); try { localStorage.removeItem(key) } catch { /* successful server receipt is durable */ }
    if (token !== detailGeneration) return
    baseline.value = draftText.value; pending = null; backupError.value = conflict.value = false
    await openEntry({ entry_id: id }, undefined)
    if (token + 1 === detailGeneration) { message.value = "判断已保存到作品，历史记录保留。"; if (data.value) await page(offset.value) }
  } catch (cause) { if (token === detailGeneration) { decisionError.value = cause.message || "保存结果尚未确认，请保留输入后重试。"; if (cause.status === 409) conflict.value = true; backup() } }
  finally { if (token === detailGeneration || token + 1 === detailGeneration) saving.value = false }
}
async function openEvidence(index) {
  const token = ++sourceGeneration; sourceError.value = ""; source.value = null
  try { const result = await api().ledgerEvidence(props.projectId, entry.value.entry_id, index, entry.value.revision); if (token === sourceGeneration) source.value = result }
  catch (cause) { if (token === sourceGeneration) sourceError.value = cause.message || "原文无法回读，历史引用仍保留。" }
}
async function openCheckpoint(ref) {
  const token = ++sourceGeneration; sourceError.value = ""; source.value = null
  try { const result = await getApi().story.sceneCheckpointRecord(props.projectId, ref.checkpoint_id); if (token === sourceGeneration) source.value = { summary: result.display_summary || "已记录的场景状态依据", gap: result.gap_reason, historical: !result.is_current } }
  catch (cause) { if (token === sourceGeneration) sourceError.value = cause.message || "历史依据暂时无法回读。" }
}
const unregister = registerAuxiliaryLeaveGuard(() => backupFailures.size === 0)
function beforeUnload(event) { if (backupFailures.size) { event.preventDefault(); event.returnValue = "" } }
globalThis.addEventListener?.("beforeunload", beforeUnload)
onBeforeUnmount(() => { backup(); generation++; detailGeneration++; sourceGeneration++; unregister(); globalThis.removeEventListener?.("beforeunload", beforeUnload) })
</script>

<style scoped>
.evolution-panorama { margin-block: 1rem; min-width: 0; color: var(--text-primary); }
.evolution-panorama summary { cursor: pointer; font-weight: 600; padding-block: .5rem; }
.evolution-panorama section { margin-block: 1rem; }
.evolution-actions { display: flex; flex-wrap: wrap; align-items: end; gap: .6rem; }
.evolution-panorama label { display: grid; gap: .3rem; margin-block: .5rem; min-width: 0; }
.evolution-panorama label:has([type=checkbox]) { display: flex; align-items: start; }
.evolution-panorama select, .evolution-panorama input, .evolution-panorama textarea { max-width: 100%; box-sizing: border-box; }
.evolution-panorama textarea { width: 100%; }
.evolution-table-wrap { overflow-x: auto; max-width: 100%; }
.evolution-panorama table { width: 100%; border-collapse: collapse; font-size: .9rem; }
.evolution-panorama th, .evolution-panorama td { padding: .6rem; text-align: start; vertical-align: top; border-bottom: 1px solid var(--border-color, #ddd); min-width: 7rem; }
.evolution-panorama p, .evolution-panorama blockquote { overflow-wrap: anywhere; white-space: pre-wrap; }
.evolution-panorama small { display: block; color: var(--text-secondary); margin-block: .3rem; }
.evolution-entry { padding: 0; border: 0; background: transparent; color: var(--accent-color, #52736b); cursor: pointer; font: inherit; font-weight: 600; text-align: start; }
.evolution-detail, .evolution-source { border-left: 3px solid var(--accent-color, #52736b); padding-inline: .8rem; }
.evolution-detail article { margin-block: .8rem; }
.evolution-panorama blockquote { margin: .5rem 0; padding: .5rem; background: var(--bg-secondary, #8881); }
.evolution-note { color: var(--text-secondary); font-size: .85rem; }
.evolution-coverage { font-weight: 600; }
.evolution-panorama fieldset { min-width: 0; border: 0; padding: 0; }
</style>
