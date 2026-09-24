<template>
  <section class="editorial-desk" aria-label="编辑台">
    <header class="editorial-desk__heading">
      <div><strong>编辑台</strong><p>先确认本轮想守住的东西，再请编辑看已保存的正文。意见由你决定如何处理。</p></div>
      <button type="button" class="btn btn-sm" :disabled="loading" @click="load">刷新</button>
    </header>
    <p v-if="error" class="editorial-desk__error" role="alert">{{ error }}</p>
    <p v-if="loading" role="status">正在读取编辑台…</p>
    <template v-else-if="!policy?.feature_available"><p role="status">编辑台尚未向这部作品开放，已保存的正文不受影响。</p></template>
    <template v-else>
      <details class="editorial-desk__section" :open="!brief?.version">
        <summary>编辑约定 <small>第 {{ brief?.version || 0 }} 版 · 仅作者保存后生效</small></summary>
        <p>题材和基调只是起点。请写下这次审稿真正需要遵守的目标与保留项。</p>
        <label>目标读者<input v-model="briefDraft.target_readers" type="text" maxlength="500" /></label>
        <label>类型与阅读承诺<textarea v-model="briefDraft.genre_promise" rows="2" maxlength="1000" /></label>
        <label>本轮创作目标 <small>每行一项</small><textarea v-model="briefLists.goals" rows="3" /></label>
        <label>希望保留的叙述声音<textarea v-model="briefDraft.voice" rows="2" maxlength="2000" /></label>
        <label>明确不能改动的安排 <small>每行一项</small><textarea v-model="briefLists.preserve" rows="3" /></label>
        <label>刻意留白或误导 <small>每行一项</small><textarea v-model="briefLists.intentional_choices" rows="3" /></label>
        <label>本轮不审的资料 <small>每行一项，例如 chapter:12</small><textarea v-model="briefLists.excluded_targets" rows="2" /></label>
        <div class="editorial-desk__actions"><button type="button" class="btn btn-primary btn-sm" :disabled="busy" @click="saveBrief">保存编辑约定</button></div>
      </details>
      <p v-if="briefDraftNotice" role="status">{{ briefDraftNotice }}</p>

      <section class="editorial-desk__section" aria-labelledby="editorial-start-title">
        <h3 id="editorial-start-title">开始审读</h3>
        <div class="editorial-desk__scope">
          <label>范围<select v-model="scope"><option value="chapter">单章</option><option value="range">章节区间／一卷</option><option value="book">全书</option></select></label>
          <label v-if="scope !== 'book'">起始章<input v-model.number="startChapter" type="number" min="1" /></label>
          <label v-if="scope === 'range'">结束章<input v-model.number="endChapter" type="number" :min="startChapter || 1" /></label>
        </div>
        <fieldset><legend>本轮检查</legend><label v-for="item in dimensions" :key="item.id"><input v-model="selectedDimensions" type="checkbox" :value="item.id" />{{ item.label }}</label></fieldset>
        <label>暂不检查的章节 <small>可留空，多个章节用逗号分开</small><input v-model="excludedText" type="text" placeholder="例如 4, 9" /></label>
        <div class="editorial-desk__actions"><button type="button" class="btn btn-primary btn-sm" :disabled="busy || !selectedDimensions.length" @click="submitReview">{{ busy ? '提交中…' : '开始审读已保存正文' }}</button><span>长篇会分段进行，离开后可回来查看进度。</span></div>
      </section>

      <section class="editorial-desk__section" aria-labelledby="editorial-reviews-title">
        <div class="editorial-desk__section-head"><h3 id="editorial-reviews-title">意见书</h3><select v-if="reviews.length" v-model="selectedReviewId" aria-label="选择审稿记录"><option v-for="review in reviews" :key="review.id" :value="review.id">{{ scopeLabel(review.scope) }} · {{ statusLabel(review.status) }}</option></select></div>
        <p v-if="!reviews.length">还没有编辑意见。没有提醒不等于全书已检查。</p>
        <template v-else-if="selectedReview">
          <p class="editorial-desk__status" role="status">{{ statusLabel(selectedReview.status) }} · 已查 {{ selectedReview.checked_chapters.length }} 章，未查 {{ selectedReview.unchecked_chapters.length }} 章</p>
          <p v-if="selectedReview.brief_changed || selectedReview.status === 'stale'" class="editorial-desk__error">依据已变化；旧意见保留供回看，请对当前正文重新审读。</p>
          <p v-if="selectedReview.error" class="editorial-desk__error">{{ selectedReview.error }}</p>
          <p v-if="selectedReview.report?.summary">{{ selectedReview.report.summary }}</p>
          <p v-if="selectedReview.unchecked_chapters.length">尚未检查：{{ selectedReview.unchecked_chapters.join('、') }} 章。</p>
          <p v-if="selectedReview.missing.length">缺失或排除：{{ selectedReview.missing.map(item => `${item.chapter_index}章${item.reason === 'excluded' ? '（已排除）' : '（缺稿）'}`).join('、') }}。</p>
          <details v-if="selectedReview.context_sources?.length || selectedReview.context_omissions?.length"><summary>参考资料与未覆盖范围</summary><p v-for="(item, index) in selectedReview.context_sources || []" :key="index">第 {{ item.chapter_index }} 章 · {{ item.kind === 'world' ? '世界资料' : '故事结构' }} · {{ item.title }}</p><p v-for="(item, index) in selectedReview.context_omissions || []" :key="`missing-${index}`">未覆盖：{{ item }}</p></details>
          <p v-if="selectedReview.report?.coverage_complete === false">本次只完成了所列范围，不能当作全书审毕。</p>
          <div class="editorial-desk__actions">
            <button v-if="['partial', 'failed', 'cancelled'].includes(selectedReview.status) && selectedReview.unchecked_chapters.length" type="button" class="btn btn-sm" :disabled="busy" @click="resumeReview">继续未完成部分</button>
            <button v-if="['queued', 'running'].includes(selectedReview.status)" type="button" class="btn btn-sm" :disabled="busy" @click="stopReview">停止本次审读</button>
          </div>
          <div v-if="reviewIssues.length" class="editorial-desk__issues">
            <h4>先看最值得处理的 {{ Math.min(3, reviewIssues.length) }} 项</h4>
            <EditorialIssueCard v-for="issue in reviewIssues.slice(0, 3)" :key="issue.id" :issue="issue" :busy="busy" @decide="decide" @recheck="recheck" @add-intent="addIntent" @locate="locate" />
            <details v-if="reviewIssues.length > 3"><summary>展开其余 {{ reviewIssues.length - 3 }} 项</summary><EditorialIssueCard v-for="issue in reviewIssues.slice(3)" :key="issue.id" :issue="issue" :busy="busy" @decide="decide" @recheck="recheck" @add-intent="addIntent" @locate="locate" /></details>
          </div>
          <details v-else-if="selectedReview.report?.all_findings?.length"><summary>查看这份历史报告的意见</summary><article v-for="(finding, index) in selectedReview.report.all_findings" :key="index"><strong>{{ finding.judgment }}</strong><p>{{ finding.reader_impact }}</p><blockquote v-for="(evidence, n) in finding.evidence" :key="n">第 {{ evidence.chapter_index }} 章：{{ evidence.quote }}</blockquote></article></details>
          <p v-else-if="['completed', 'partial'].includes(selectedReview.status)">所查范围内暂无值得打断你的主要问题。</p>
        </template>
      </section>

      <details class="editorial-desk__section">
        <summary>主动跟进 <small>{{ policy?.enabled ? '已开启' : '未开启' }}</small></summary>
        <p>开启后，仅在你把已保存工作稿交给编辑，或未关闭问题关联的结构发生变化时，后台才排队检查。普通输入与自动保存不会触发。</p>
        <label><input v-model="automaticEnabled" type="checkbox" :disabled="busy || !policy?.automatic_available" /> 允许这部作品主动检查</label>
        <label>主动检查时排除的章节 <small>用逗号分隔</small><input v-model="automaticExclusionsText" type="text" placeholder="例如 4, 9" /></label>
        <button type="button" class="btn btn-sm" :disabled="busy || !policy?.automatic_available" @click="savePolicy">保存主动跟进设置</button>
        <p v-if="!policy?.automatic_available">后台编辑当前未开放；手动审读仍可使用。</p>
      </details>
    </template>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue"
import { getApi } from "../bridge/index.js"
import { locateAssistantSource } from "../shared/assistantNavigation.js"
import EditorialIssueCard from "./EditorialIssueCard.vue"

const props = defineProps({ projectId: { type: String, required: true }, active: Boolean, focusChapter: { type: Number, default: null }, focusIssueId: { type: String, default: null } })
const dimensions = [{ id: "structure", label: "结构" }, { id: "scene", label: "场景" }, { id: "reader", label: "读者体验" }, { id: "line", label: "行文" }, { id: "copy", label: "文字准确性" }]
const brief = ref(null), briefDraft = ref({}), briefLists = ref({}), briefDraftNotice = ref("")
const policy = ref(null), automaticEnabled = ref(false), automaticExclusionsText = ref("")
const reviews = ref([]), issues = ref([]), selectedReviewId = ref(null)
const scope = ref("chapter"), startChapter = ref(1), endChapter = ref(1)
const selectedDimensions = ref(dimensions.map(item => item.id)), excludedText = ref("")
const loading = ref(false), busy = ref(false), error = ref("")
const selectedReview = computed(() => reviews.value.find(item => item.id === selectedReviewId.value) || null)
const reviewIssues = computed(() => {
  const top = new Map((selectedReview.value?.report?.top_findings || []).map((finding, index) => [finding.fingerprint, index]))
  return issues.value.filter(item => item.review_id === selectedReviewId.value)
    .sort((a, b) => Number(b.id === props.focusIssueId) - Number(a.id === props.focusIssueId)
      || (top.get(a.fingerprint) ?? 999) - (top.get(b.fingerprint) ?? 999)
      || Number(a.disposition === "closed") - Number(b.disposition === "closed")
      || ({ high: 3, medium: 2, low: 1 })[b.finding.severity] - ({ high: 3, medium: 2, low: 1 })[a.finding.severity])
})
let poller = null, pendingOperationId = null, pendingPayload = null
function backupKey() { return `novelcraft:editorial-brief:${props.projectId}` }
function operationKey() { return `novelcraft:editorial-operation:${props.projectId}` }
function parseLines(value, limit) { return String(value || "").split("\n").map(item => item.trim()).filter(Boolean).slice(0, limit) }
function currentBriefValue() { return { ...briefDraft.value, ...Object.fromEntries(Object.entries(briefLists.value).map(([key, text]) => [key, parseLines(text, key === "goals" ? 12 : key === "excluded_targets" ? 200 : 20)])) } }
function scopeLabel(value) { return value.scope === "book" ? "全书" : value.scope === "range" ? `${value.start_chapter}—${value.end_chapter} 章` : `第 ${value.start_chapter} 章` }
function statusLabel(value) { return ({ queued: "等待审读", running: "审读中", partial: "部分完成", completed: "已完成", stale: "依据已变化", failed: "未完成", cancelled: "已停止" })[value] || "待查看" }
function restoreBrief(value) {
  brief.value = value
  let saved = null
  try { saved = JSON.parse(sessionStorage.getItem(backupKey()) || "null") } catch { /* stay with server copy */ }
  const source = saved?.version === value.version ? saved.brief : value.brief
  briefDraft.value = { ...source }
  briefLists.value = Object.fromEntries(["goals", "preserve", "intentional_choices", "excluded_targets"].map(key => [key, (source[key] || []).join("\n")]))
  briefDraftNotice.value = saved?.version === value.version ? "已恢复未保存的本地约定。" : ""
}
async function load() {
  if (!props.projectId) return
  const projectId = props.projectId
  loading.value = true; error.value = ""
  try {
    const [nextBrief, nextPolicy, nextReviews, nextIssues] = await Promise.all([
      getApi().projects.editorialBrief(projectId), getApi().assistant.editorialPolicy(projectId),
      getApi().assistant.editorialReviews(projectId), getApi().assistant.editorialIssues(projectId),
    ])
    if (projectId !== props.projectId) return
    restoreBrief(nextBrief); policy.value = nextPolicy; automaticEnabled.value = nextPolicy.enabled; automaticExclusionsText.value = (nextPolicy.excluded_chapters || []).join(", ")
    reviews.value = nextReviews; issues.value = nextIssues
    if (!nextReviews.some(item => item.id === selectedReviewId.value)) selectedReviewId.value = nextReviews[0]?.id || null
    if (props.focusIssueId) selectedReviewId.value = nextIssues.find(item => item.id === props.focusIssueId)?.review_id || selectedReviewId.value
  } catch (cause) { if (projectId === props.projectId) error.value = cause.message || "编辑台暂时无法读取，请稍后重试。" }
  finally { if (projectId === props.projectId) loading.value = false }
}
async function refreshResults() {
  if (!props.projectId || !props.active) return
  try {
    const [nextReviews, nextIssues] = await Promise.all([getApi().assistant.editorialReviews(props.projectId), getApi().assistant.editorialIssues(props.projectId)])
    reviews.value = nextReviews; issues.value = nextIssues
    if (!nextReviews.some(item => item.id === selectedReviewId.value)) selectedReviewId.value = nextReviews[0]?.id || null
    if (props.focusIssueId) selectedReviewId.value = nextIssues.find(item => item.id === props.focusIssueId)?.review_id || selectedReviewId.value
  } catch { /* keep the last readable result; explicit refresh shows an error */ }
}
async function saveBrief() {
  busy.value = true; error.value = ""
  try {
    const value = currentBriefValue()
    const saved = await getApi().projects.saveEditorialBrief(props.projectId, { expected_version: brief.value.version, brief: value })
    try { sessionStorage.removeItem(backupKey()) } catch { /* server save is authoritative */ }
    restoreBrief(saved); briefDraftNotice.value = "编辑约定已保存。旧报告仍保留原依据。"
    await refreshResults()
  } catch (cause) { error.value = cause.message || "保存失败，输入仍保留。" }
  finally { busy.value = false }
}
async function submitReview() {
  busy.value = true; error.value = ""
  try {
    const excluded = excludedText.value.split(/[,，\s]+/).filter(Boolean).map(Number)
    if (excluded.some(value => !Number.isInteger(value) || value < 1)) throw new Error("请用章节数字填写暂不检查的范围。")
    const payload = {
      novel_id: props.projectId, scope: scope.value,
      start_chapter: scope.value === "book" ? null : startChapter.value,
      end_chapter: scope.value === "range" ? endChapter.value : null,
      dimensions: selectedDimensions.value, excluded_chapters: excluded,
      expected_brief_version: brief.value.version,
    }
    let savedOperation = null
    try { savedOperation = JSON.parse(sessionStorage.getItem(operationKey()) || "null") } catch { /* keep in-memory retry */ }
    pendingOperationId = savedOperation?.payload && JSON.stringify(savedOperation.payload) === JSON.stringify(payload) ? savedOperation.id : pendingPayload && JSON.stringify(pendingPayload) === JSON.stringify(payload) && pendingOperationId ? pendingOperationId : crypto.randomUUID()
    pendingPayload = payload
    try { sessionStorage.setItem(operationKey(), JSON.stringify({ id: pendingOperationId, payload })) } catch { /* current tab still preserves the id */ }
    const review = await getApi().assistant.submitEditorialReview({ ...payload, operation_id: pendingOperationId })
    try { sessionStorage.removeItem(operationKey()) } catch { /* server receipt is authoritative */ }
    pendingOperationId = null
    pendingPayload = null
    await refreshResults(); selectedReviewId.value = review.id
  } catch (cause) { error.value = cause.message || "提交失败，请重试；本次请求会保持同一标识。" }
  finally { busy.value = false }
}
async function resumeReview() {
  busy.value = true; error.value = ""
  try { await getApi().assistant.resumeEditorialReview(props.projectId, selectedReviewId.value); await refreshResults() }
  catch (cause) { error.value = cause.message || "暂时无法续查。" }
  finally { busy.value = false }
}
async function stopReview() {
  busy.value = true; error.value = ""
  try { await getApi().assistant.stopEditorialReview(props.projectId, selectedReviewId.value); await refreshResults() }
  catch (cause) { error.value = cause.message || "暂时无法停止。" }
  finally { busy.value = false }
}
async function decide(issue, disposition, note) {
  busy.value = true; error.value = ""
  try { await getApi().assistant.decideEditorialIssue(issue.id, { novel_id: props.projectId, expected_version: issue.version, disposition, note }); await refreshResults() }
  catch (cause) { error.value = cause.message || "决定未保存，请刷新后重试。" }
  finally { busy.value = false }
}
async function recheck(issue) {
  busy.value = true; error.value = ""
  try { await getApi().assistant.recheckEditorialIssue(issue.id, { novel_id: props.projectId, expected_version: issue.version, operation_id: crypto.randomUUID() }); await refreshResults() }
  catch (cause) { error.value = cause.message || "复核未开始。" }
  finally { busy.value = false }
}
function addIntent(issue) {
  const value = issue.finding.intent_relation || issue.finding.judgment
  const lines = parseLines(briefLists.value.intentional_choices, 20)
  if (!lines.includes(value)) briefLists.value.intentional_choices = [...lines, value].join("\n")
  briefDraftNotice.value = "已放入编辑约定草稿。只有你点击“保存编辑约定”后才长期生效。"
}
function locate(evidence) { locateAssistantSource({ type: "writing_draft", id: evidence.draft_id, chapter_index: evidence.chapter_index, start: evidence.start, content_hash: evidence.content_hash }) }
async function savePolicy() {
  busy.value = true; error.value = ""
  try {
    const excluded = automaticExclusionsText.value.split(/[,，\s]+/).filter(Boolean).map(Number)
    if (excluded.some(value => !Number.isInteger(value) || value < 1)) throw new Error("请用章节数字填写排除范围。")
    policy.value = await getApi().assistant.saveEditorialPolicy(props.projectId, { enabled: automaticEnabled.value, excluded_chapters: excluded }, policy.value.generation)
  }
  catch (cause) {
    error.value = cause.message || "设置未保存。"
    try { policy.value = await getApi().assistant.editorialPolicy(props.projectId) } catch { /* preserve the last known settings */ }
  }
  finally { busy.value = false }
}
watch([briefDraft, briefLists], () => {
  if (!brief.value || loading.value) return
  try {
    if (JSON.stringify(currentBriefValue()) === JSON.stringify(brief.value.brief)) sessionStorage.removeItem(backupKey())
    else sessionStorage.setItem(backupKey(), JSON.stringify({ version: brief.value.version, brief: currentBriefValue() }))
  }
  catch { briefDraftNotice.value = "本地备份不可用；请先保存编辑约定再离开。" }
}, { deep: true })
watch(() => props.focusChapter, value => { if (value > 0) { scope.value = "chapter"; startChapter.value = value } }, { immediate: true })
watch([() => props.active, () => props.projectId], ([active]) => { if (active) { load(); poller ||= setInterval(refreshResults, 8000) } else if (poller) { clearInterval(poller); poller = null } }, { immediate: true })
onBeforeUnmount(() => { if (poller) clearInterval(poller) })
</script>

<style scoped>
.editorial-desk{display:grid;gap:16px;padding:16px;overflow-y:auto;min-height:0;color:var(--text-primary);line-height:1.55}.editorial-desk__heading,.editorial-desk__section-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.editorial-desk__heading p,.editorial-desk__section p{margin:6px 0;color:var(--text-secondary)}.editorial-desk__section{border:1px solid var(--border);border-radius:12px;padding:14px;background:var(--surface)}.editorial-desk__section summary{cursor:pointer;font-weight:700}.editorial-desk__section summary small{font-weight:400;color:var(--text-secondary)}.editorial-desk__section h3,.editorial-desk__section h4{margin:0 0 8px}.editorial-desk__section label{display:grid;gap:4px;margin:10px 0;font-size:14px}.editorial-desk__section label small{font-weight:400;color:var(--text-secondary)}.editorial-desk__section input:not([type=checkbox]),.editorial-desk__section textarea,.editorial-desk__section select{width:100%;min-height:38px;padding:8px;border:1px solid var(--border);border-radius:8px;background:var(--surface);color:var(--text-primary)}.editorial-desk__section fieldset{display:flex;flex-wrap:wrap;gap:6px 12px;border:0;padding:4px 0;margin:8px 0}.editorial-desk__section fieldset label,.editorial-desk__section>label:has(input[type=checkbox]){display:flex;align-items:center;gap:6px;margin:0}.editorial-desk__scope{display:flex;gap:10px;flex-wrap:wrap}.editorial-desk__scope label{flex:1 1 110px}.editorial-desk__actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:10px}.editorial-desk__error{color:var(--danger,#b42318);padding:8px;background:var(--danger-soft,#fff4f2);border-radius:8px}.editorial-desk__status{font-weight:700}.editorial-desk__issues{display:grid;gap:10px;margin-top:14px}@media(max-width:600px){.editorial-desk{padding:12px}.editorial-desk__heading,.editorial-desk__section-head{display:block}.editorial-desk__section-head select{margin-top:8px}}
</style>
