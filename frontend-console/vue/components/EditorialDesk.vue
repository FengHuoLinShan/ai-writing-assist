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
        <fieldset>
          <legend>本轮不审的章节</legend>
          <p v-if="chapterExclusionError" role="alert">{{ chapterExclusionError }}</p>
          <p v-if="chapterChoicesLoading" role="status">正在读取章节…</p>
          <p v-if="chapterChoicesError" role="status">章节列表暂时无法读取；已选范围仍会保留。<button type="button" class="btn btn-sm" @click="loadChapters">重新读取章节</button></p>
          <label v-for="chapter in excludedChapterChoices" :key="chapter.chapter_index">
            <input type="checkbox" :checked="isChapterExcluded(chapter.chapter_index)" @change="$event.target.checked = setChapterExcluded(chapter.chapter_index, $event.target.checked)" />
            第 {{ chapter.chapter_index }} 章<template v-if="chapter.title"> · {{ chapter.title }}</template>
          </label>
          <p v-if="!excludedChapterChoices.length && !chapterChoicesError && !chapterChoicesLoading">还没有可选择的章节。</p>
        </fieldset>
        <details v-if="otherExcludedTargets.length">
          <summary>此前排除的其他资料（{{ otherExcludedTargets.length }} 项）</summary>
          <p>这些范围仍会随编辑约定保存。需要重新纳入本轮审读时，可以逐项移除。</p>
          <p v-for="(target, index) in otherExcludedTargets" :key="target">已排除资料 {{ index + 1 }}<button type="button" class="btn btn-sm" @click="removeExcludedTarget(target)">重新纳入资料 {{ index + 1 }}</button></p>
        </details>
        <div class="editorial-desk__actions"><button type="button" class="btn btn-primary btn-sm" :disabled="busy" @click="saveBrief">保存编辑约定</button></div>
        <label class="editorial-desk__writing-toggle"><input type="checkbox" :checked="briefForWriting" :disabled="writingToggleBusy" @change="toggleBriefForWriting($event.target.checked)" />也用于 AI 写作<small>开启后，AI 正文建议与续写会在参考资料确认中带上这份约定；「AI 角色视角建议」不使用它，以免刻意留白和误导安排被当成角色已知。文风只影响表达方式，不会新增事实或情节。默认关闭。</small></label>
        <p v-if="briefForWriting && !briefForWritingEffective" role="status" class="editorial-desk__inherited">开关已开启，但编辑约定还是空的；保存一份有内容的约定后才会真正进入 AI 写作。</p>
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
          <details v-if="selectedReview.error_detail" class="editorial-desk__error-detail"><summary>查看技术详情</summary><p>{{ selectedReview.error_detail }}</p></details>
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
            <EditorialIssueCard v-for="issue in reviewIssues.slice(0, 3)" :key="issue.id" :issue="issue" :busy="busy" :selected="selectedIssueIds.includes(issue.id)" @decide="decide" @recheck="recheck" @add-intent="addIntent" @locate="locate" @toggle-select="checked => toggleIssueSelection(issue, checked)" />
            <details v-if="reviewIssues.length > 3"><summary>展开其余 {{ reviewIssues.length - 3 }} 项</summary><EditorialIssueCard v-for="issue in reviewIssues.slice(3)" :key="issue.id" :issue="issue" :busy="busy" :selected="selectedIssueIds.includes(issue.id)" @decide="decide" @recheck="recheck" @add-intent="addIntent" @locate="locate" @toggle-select="checked => toggleIssueSelection(issue, checked)" /></details>
            <section v-if="selectedIssueIds.length || revisionItems.length" class="editorial-desk__revision" aria-labelledby="editorial-revision-title">
              <h4 v-if="selectedIssueIds.length" id="editorial-revision-title">按选中的 {{ selectedIssueIds.length }} 条意见发起批注修订</h4>
              <h4 v-else id="editorial-revision-title">本轮批注修订</h4>
              <template v-if="selectedIssueIds.length">
                <p>请勾选需要修改的原文位置，连同意见原文和下面的处置说明一起交给批注修订，只生成改动所选片段的替换候选；候选到写作页要先通过独立审稿，通过后才能采用到工作稿。引文已不在当前稿的意见不会生成候选，会逐条说明原因。发起修订含生成、审查及必要返修，按实际调用计费。</p>
                <fieldset v-for="issue in selectedRevisionIssues" :key="issue.id">
                  <legend>{{ issue.finding?.judgment }}：选择修改位置</legend>
                  <label v-for="(evidence, index) in issue.finding?.evidence || []" :key="index">
                    <input v-model="evidenceChoices[issue.id]" type="checkbox" :value="index" :disabled="revisionBusy || flowBusy" />
                    第 {{ evidence.chapter_index }} 章：{{ evidence.quote }}
                  </label>
                </fieldset>
                <p v-for="range in revisionRanges" :key="range.key">联合修订范围：第 {{ range.chapter }} 章，{{ range.start + 1 }}–{{ range.end }} 字；{{ range.quotes.join(' / ') }}</p>
                <label v-if="revisionOverlaps.length"><input v-model="overlapConfirmed" type="checkbox" />已核对上方重叠片段的合并范围，同意联合修订。</label>
                <label>处置说明 <small>会连同意见原文一起交给修订</small><textarea v-model="revisionInstruction" rows="2" maxlength="2000" /></label>
                <div class="editorial-desk__actions">
                  <button type="button" class="btn btn-primary btn-sm" :disabled="revisionBusy || !revisionInstruction.trim() || !revisionSelectionReady || busy" @click="submitRevision">{{ revisionBusy ? '提交中…' : `发起 ${selectedIssueIds.length} 条修订` }}</button>
                  <button type="button" class="btn btn-sm" :disabled="revisionBusy || !revisionInstruction.trim() || !revisionSelectionReady || busy || !flowAvailable" data-action="start-revision-flow" @click="startRevisionFlow">走引导流程修订</button>
                  <button type="button" class="btn btn-sm" :disabled="revisionBusy" @click="clearIssueSelection">取消选择</button>
                </div>
                <p v-if="!flowAvailable" class="editorial-desk__note">引导流程未向当前作品开放时，可直接发起修订，效果相同。</p>
              </template>
              <p v-if="revisionError" class="editorial-desk__error" role="alert">{{ revisionError }}</p>
              <div v-if="revisionItems.length" class="editorial-desk__revision-results">
                <p v-for="item in revisionItems" :key="`${item.issue_id}:${item.chapter_index}:${item.task_id || item.reason}`">
                  <template v-if="item.kind === 'queued'">
                    <template v-if="!item.done">修订进行中…</template>
                    <template v-else-if="item.candidate_draft_id">替换候选已生成：<button type="button" class="btn btn-sm" @click="openRevisionCandidate(item)">去写作页完成独立审稿并采用</button></template>
                    <template v-else>修订未生成候选：{{ item.reason || '请查看写作页的任务提示' }}</template>
                  </template>
                  <template v-else-if="item.kind === 'unlocatable'">这条意见未能发起修订：{{ item.reason }}</template>
                  <template v-else>{{ item.reason || '这条意见未能发起修订' }}</template>
                </p>
                <p v-if="revisionCandidateReady" class="editorial-desk__note">采用前，写作页会先对这份候选做一次独立审稿；审稿通过前不能直接采用，这是为了防止未经检查的改写进入正文。</p>
              </div>
            </section>
          </div>
          <details v-else-if="selectedReview.report?.all_findings?.length"><summary>查看这份历史报告的意见</summary><article v-for="(finding, index) in selectedReview.report.all_findings" :key="index"><strong>{{ finding.judgment }}</strong><p>{{ finding.reader_impact }}</p><blockquote v-for="(evidence, n) in finding.evidence" :key="n">第 {{ evidence.chapter_index }} 章：{{ evidence.quote }}</blockquote></article></details>
          <p v-else-if="['completed', 'partial'].includes(selectedReview.status)">所查范围内暂无值得打断你的主要问题。</p>
        </template>
      </section>

      <!-- 引导流程（BR-4 流程 3）：选意见 → 桥接修订 → 候选审阅 → 改后复核。 -->
      <section v-if="flowView && !flowTerminal" class="editorial-desk__flowstrip" aria-label="修订引导流程">
        <header class="editorial-desk__section-head">
          <div><strong>{{ flowView.title }}</strong><p>{{ flowView.description }}</p></div>
          <span class="editorial-desk__flow-status">{{ flowStatusLabel }}</span>
        </header>
        <ol class="editorial-desk__flow-steps">
          <li v-for="step in flowView.steps" :key="step.step_id" :data-state="step.state">
            <span aria-hidden="true">{{ flowStepMark(step.state) }}</span>
            <span>{{ step.title }}</span>
          </li>
        </ol>
        <p v-if="flowView.stop" role="status">{{ flowView.stop.reason }}</p>
        <p v-else-if="flowView.status === 'running'" role="status">修订正在按流程推进，完成后会停下来说明。</p>
        <div v-if="flowRechecks.length" class="editorial-desk__revision-results">
          <p v-for="entry in flowRechecks" :key="entry.issue_id">
            <template v-if="entry.verdict_label">改后复核：{{ entry.verdict_label }}<template v-if="entry.reason"> — {{ entry.reason }}</template></template>
            <template v-else-if="['failed', 'cancelled'].includes(entry.status)">改后复核未完成，可在意见卡上重新发起。</template>
            <template v-else-if="entry.status === 'skipped'">改后复核未执行<template v-if="entry.reason">：{{ entry.reason }}</template>。</template>
            <template v-else>改后复核进行中…</template>
          </p>
        </div>
        <div class="editorial-desk__actions">
          <button
            v-for="action in flowView.stop?.actions || []"
            :key="action.action"
            type="button"
            class="btn btn-sm"
            :class="{ 'btn-primary': action === (flowView.stop?.actions || [])[0] }"
            :disabled="flowBusy"
            :data-action="`flow-${action.action}`"
            @click="runFlowAction(action.action)"
          >{{ action.label }}</button>
        </div>
        <p v-if="flowError" class="editorial-desk__error" role="alert">{{ flowError }}</p>
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
import { confirmAsync } from "../../shared/confirmAsync.js"
import { confirmEditorialImpact } from "../composables/useEditorialGuard.js"
import EditorialIssueCard from "./EditorialIssueCard.vue"

const props = defineProps({ projectId: { type: String, required: true }, active: Boolean, focusChapter: { type: Number, default: null }, focusIssueId: { type: String, default: null } })
const dimensions = [{ id: "structure", label: "结构" }, { id: "scene", label: "场景" }, { id: "reader", label: "读者体验" }, { id: "line", label: "行文" }, { id: "copy", label: "文字准确性" }]
const brief = ref(null), briefDraft = ref({}), briefLists = ref({}), briefDraftNotice = ref("")
const chapterChoices = ref([]), chapterChoicesError = ref(false), chapterChoicesLoading = ref(false), chapterExclusionError = ref("")
let chapterChoicesRequest = 0
function chapterTargetIndex(target) { const match = /^chapter:(\d+)$/.exec(target); return match ? Number(match[1]) : null }
const excludedChapterChoices = computed(() => {
  const chapters = new Map(chapterChoices.value.map(item => [Number(item.chapter_index), item]))
  for (const target of parseLines(briefLists.value.excluded_targets, 200)) {
    const match = /^chapter:(\d+)$/.exec(target)
    if (match && !chapters.has(Number(match[1]))) chapters.set(Number(match[1]), { chapter_index: Number(match[1]), title: "已选范围" })
  }
  return [...chapters.values()].sort((a, b) => a.chapter_index - b.chapter_index)
})
const otherExcludedTargets = computed(() => parseLines(briefLists.value.excluded_targets, 200).filter(target => !/^chapter:\d+$/.test(target)))
function removeExcludedTarget(target) { briefLists.value.excluded_targets = parseLines(briefLists.value.excluded_targets, 200).filter(item => item !== target).join("\n") }
function isChapterExcluded(chapter) { return parseLines(briefLists.value.excluded_targets, 200).some(target => chapterTargetIndex(target) === chapter) }
function setChapterExcluded(chapter, selected) {
  const targets = parseLines(briefLists.value.excluded_targets, 200).filter(item => chapterTargetIndex(item) !== chapter)
  if (selected && targets.length >= 200) {
    chapterExclusionError.value = "最多排除 200 项资料，请先取消一项再选择新章节。"
    return false
  }
  if (selected) targets.push(`chapter:${chapter}`)
  chapterExclusionError.value = ""
  briefLists.value.excluded_targets = targets.join("\n")
  return selected
}
async function loadChapters() {
  const projectId = props.projectId
  const request = ++chapterChoicesRequest
  chapterChoicesError.value = false
  chapterChoicesLoading.value = true
  try {
    const data = await getApi().writing.listChapters(projectId)
    if (projectId !== props.projectId || request !== chapterChoicesRequest) return
    chapterChoices.value = Array.isArray(data) ? data : data?.chapters || []
  } catch {
    if (projectId === props.projectId && request === chapterChoicesRequest) chapterChoicesError.value = true
  } finally {
    if (request === chapterChoicesRequest) chapterChoicesLoading.value = false
  }
}
const policy = ref(null), automaticEnabled = ref(false), automaticExclusionsText = ref("")
const reviews = ref([]), issues = ref([]), selectedReviewId = ref(null)
const selectedIssueIds = ref([])
const evidenceChoices = ref({}), overlapConfirmed = ref(false)
const selectedRevisionIssues = computed(() => reviewIssues.value.filter(issue => selectedIssueIds.value.includes(issue.id)))
const revisionRanges = computed(() => {
  const spans = selectedRevisionIssues.value.flatMap(issue => (evidenceChoices.value[issue.id] || []).map(index => {
    const entry = issue.finding.evidence[index]
    return { key: `${issue.id}:${index}`, chapter: entry.chapter_index, draft: entry.draft_id, start: entry.start, end: entry.end, quotes: [entry.quote] }
  })).filter(entry => Number.isInteger(entry.start) && Number.isInteger(entry.end)).sort((a, b) => a.chapter - b.chapter || a.start - b.start)
  const merged = []
  for (const span of spans) {
    const previous = merged.at(-1)
    if (previous && previous.chapter === span.chapter && previous.draft === span.draft && span.start < previous.end) {
      previous.end = Math.max(previous.end, span.end); previous.quotes.push(...span.quotes); previous.overlap = true
    } else merged.push({ ...span })
  }
  return merged
})
const revisionOverlaps = computed(() => revisionRanges.value.filter(range => range.overlap))
const revisionSelectionReady = computed(() => selectedRevisionIssues.value.every(issue => evidenceChoices.value[issue.id]?.length) && (!revisionOverlaps.value.length || overlapConfirmed.value))
function revisionRequestItems(instruction) {
  return selectedRevisionIssues.value.map(issue => ({ issue_id: issue.id, expected_version: issue.version, instruction, evidence_indices: [...(evidenceChoices.value[issue.id] || [])] }))
}
watch(evidenceChoices, () => { overlapConfirmed.value = false }, { deep: true })
const revisionInstruction = ref(""), revisionBusy = ref(false), revisionError = ref("")
const revisionItems = ref([])
const revisionCandidateReady = computed(() => revisionItems.value.some(item => item.kind === "queued" && item.done && item.candidate_draft_id))
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
let pendingOperationId = null, pendingPayload = null
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
const briefForWriting = ref(false)
const briefForWritingEffective = ref(false)
const writingToggleBusy = ref(false)
async function toggleBriefForWriting(enabled) {
  if (writingToggleBusy.value || !props.projectId) return
  const projectId = props.projectId
  writingToggleBusy.value = true; error.value = ""
  try {
    const saved = await getApi().projects.setEditorialBriefForWriting(projectId, Boolean(enabled))
    if (projectId !== props.projectId) return
    // effective 由服务端按"开关开启且约定非空"返回，不继承开启前的旧值
    briefForWriting.value = Boolean(saved.enabled)
    briefForWritingEffective.value = Boolean(saved.enabled) && Boolean(saved.effective)
    briefDraftNotice.value = saved.enabled
      ? (saved.effective
        ? "已开启：这份约定将进入 AI 正文建议与续写的参考资料确认。"
        : "已开启，但编辑约定还是空的；保存约定后才会进入 AI 写作。")
      : "已关闭：AI 写作不再读取这份约定。"
  } catch (cause) {
    if (projectId === props.projectId) error.value = cause.message || "切换失败，请重试。"
  } finally { writingToggleBusy.value = false }
}
async function load() {
  if (!props.projectId) return
  const projectId = props.projectId
  loading.value = true; error.value = ""
  chapterChoices.value = []
  void loadChapters()
  try {
    const [nextBrief, nextPolicy, nextReviews, nextIssues, nextWritingUse, nextCapabilities] = await Promise.all([
      getApi().projects.editorialBrief(projectId), getApi().assistant.editorialPolicy(projectId),
      getApi().assistant.editorialReviews(projectId), getApi().assistant.editorialIssues(projectId),
      getApi().projects.editorialBriefForWriting(projectId),
      getApi().assistant?.capabilities ? getApi().assistant.capabilities(projectId) : Promise.resolve(null),
    ])
    if (projectId !== props.projectId) return
    briefForWriting.value = Boolean(nextWritingUse?.enabled)
    briefForWritingEffective.value = Boolean(nextWritingUse?.effective)
    restoreBrief(nextBrief); policy.value = nextPolicy; automaticEnabled.value = nextPolicy.enabled; automaticExclusionsText.value = (nextPolicy.excluded_chapters || []).join(", ")
    reviews.value = nextReviews; issues.value = nextIssues
    flowAvailable.value = Boolean(nextCapabilities?.guided_flows?.available)
    if (flowAvailable.value && getApi().assistant.guidedFlowActive) {
      const active = await getApi().assistant.guidedFlowActive(projectId)
      if (projectId !== props.projectId) return
      flowView.value = active?.flow_id === "editorial_revision" ? active : null
    }
    pruneIssueSelection()
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
    pruneIssueSelection()
    if (!nextReviews.some(item => item.id === selectedReviewId.value)) selectedReviewId.value = nextReviews[0]?.id || null
    if (props.focusIssueId) selectedReviewId.value = nextIssues.find(item => item.id === props.focusIssueId)?.review_id || selectedReviewId.value
  } catch { /* keep the last readable result; explicit refresh shows an error */ }
}
async function saveBrief() {
  const activeReviews = reviews.value.filter(item => ["queued", "running"].includes(item.status))
  if (!(await confirmEditorialImpact(props.projectId, { kind: "brief", reviews: activeReviews }))) return
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
function pruneIssueSelection() {
  const known = new Set(issues.value.filter(item => !item.source_may_be_stale).map(item => item.id))
  selectedIssueIds.value = selectedIssueIds.value.filter(id => known.has(id))
}
function toggleIssueSelection(issue, checked) {
  evidenceChoices.value[issue.id] = checked && issue.finding?.evidence?.length === 1 ? [0] : []
  overlapConfirmed.value = false
  selectedIssueIds.value = checked
    ? [...selectedIssueIds.value, issue.id]
    : selectedIssueIds.value.filter(id => id !== issue.id)
}
function clearIssueSelection() { selectedIssueIds.value = [] }
async function submitRevision() {
  const instruction = revisionInstruction.value.trim()
  const selected = reviewIssues.value.filter(issue => selectedIssueIds.value.includes(issue.id))
  if (!instruction || !selected.length || !revisionSelectionReady.value) return
  revisionBusy.value = true; revisionError.value = ""
  try {
    const response = await getApi().assistant.reviseEditorialIssues({
      novel_id: props.projectId,
      operation_id: crypto.randomUUID(),
      items: revisionRequestItems(instruction),
      overlap_confirmed: overlapConfirmed.value,
    })
    revisionItems.value = (response.items || []).map(item => (
      item.status === "queued"
        ? { ...item, kind: "queued", candidate_draft_id: null, done: false }
        : { ...item, kind: item.status === "unlocatable" ? "unlocatable" : "failed" }
    ))
    revisionInstruction.value = ""
    clearIssueSelection()
    await pollRevisionTasks()
  }
  catch (cause) { revisionError.value = cause.message || "修订未发起，请稍后重试。" }
  finally { revisionBusy.value = false }
}
async function pollRevisionTasks() {
  const pending = revisionItems.value.filter(item => item.kind === "queued" && !item.done && item.task_id)
  if (!pending.length || !props.projectId || !props.active) return
  for (const item of pending) {
    try {
      const task = await getApi().tasks.get(item.task_id, props.projectId)
      if (task.status === "done") {
        item.done = true
        item.candidate_draft_id = task.result?.candidate_draft_id || null
        if (!item.candidate_draft_id) item.reason = "这次没有生成替换候选（例如正文在修订期间又变化），可在写作页重试"
      } else if (["failed", "cancelled"].includes(task.status)) {
        item.done = true
        item.reason = task.error_message || "修订任务未完成"
      }
    } catch { /* 下个轮询周期再试；不覆盖已有状态 */ }
  }
  revisionItems.value = [...revisionItems.value]
}
function openRevisionCandidate(item) {
  locateAssistantSource({ type: "writing_draft", id: item.candidate_draft_id, chapter_index: item.chapter_index })
}

// ============================================================
// 引导流程（BR-4 流程 3）：与批量修订并排的入口；选定意见后
// 经服务端确定性流程桥接，停点展示候选与改后复核结果。
// ============================================================
const flowAvailable = ref(false)
const flowView = ref(null), flowBusy = ref(false), flowError = ref("")
const flowTerminal = computed(() => ["completed", "failed", "cancelled"].includes(flowView.value?.status))
const FLOW_STATUS_LABELS = { running: "进行中", waiting_approval: "等你的决定", completed: "已完成", failed: "已停下", cancelled: "已结束" }
const flowStatusLabel = computed(() => FLOW_STATUS_LABELS[flowView.value?.status] || "")
const flowRechecks = computed(() => flowView.value?.panel?.rechecks || [])

function flowStepMark(state) {
  if (state === "done") return "✓"
  if (state === "active") return "●"
  if (state === "blocked") return "!"
  if (state === "skipped") return "—"
  return "○"
}

async function startRevisionFlow() {
  const instruction = revisionInstruction.value.trim()
  const selected = reviewIssues.value.filter(issue => selectedIssueIds.value.includes(issue.id))
  if (!instruction || !selected.length || !revisionSelectionReady.value || flowBusy.value) return
  flowBusy.value = true; flowError.value = ""
  try {
    flowView.value = await getApi().assistant.guidedFlowStart({ novel_id: props.projectId, flow_id: "editorial_revision" })
    flowError.value = ""
  }
  catch (cause) {
    flowError.value = cause.message || "修订引导流程暂时不可用，可直接发起修订。"
    return
  }
  finally { flowBusy.value = false }
  // 选定意见即作为流程的第一个作者选择提交；失败时保留选择与说明。
  const advanced = await advanceRevisionFlow({
    choice: {
      step_id: "select_issues",
      action: "select_issues",
      items: revisionRequestItems(instruction),
      overlap_confirmed: overlapConfirmed.value,
    },
  })
  if (advanced) {
    revisionInstruction.value = ""
    clearIssueSelection()
  }
}

async function advanceRevisionFlow(extra = {}) {
  if (!flowView.value || flowBusy.value) return null
  flowBusy.value = true
  try {
    flowView.value = await getApi().assistant.guidedFlowAdvance(flowView.value.run_id, { novel_id: props.projectId, ...extra })
    flowError.value = ""
    return flowView.value
  }
  catch (cause) { flowError.value = cause.message || "流程推进失败，请稍后重试。"; return null }
  finally { flowBusy.value = false }
}

async function refreshRevisionFlow() {
  if (!flowView.value || flowBusy.value || !props.active || flowTerminal.value) return
  try {
    if (!flowView.value.stop) await advanceRevisionFlow({})
    else flowView.value = await getApi().assistant.guidedFlow(props.projectId, flowView.value.run_id)
  }
  catch { /* 下一轮轮询重试，不覆盖已有状态 */ }
}

function runFlowAction(action) {
  if (action === "open_candidate") {
    const item = flowRecheckCandidate()
    if (item) locateAssistantSource({ type: "writing_draft", id: item.candidate_draft_id, chapter_index: item.chapter_index })
    return
  }
  if (action === "abandon_flow") return abandonRevisionFlow()
  advanceRevisionFlow({ choice: { step_id: flowView.value?.stop?.step_id || "", action } })
}

function flowRecheckCandidate() {
  return (flowView.value?.panel?.items || []).find(item => item.candidate_draft_id) || null
}

async function abandonRevisionFlow() {
  if (!flowView.value || flowBusy.value) return
  const confirmed = await confirmAsync("结束这条修订引导流程？已生成的替换候选会保留在候选列表中。", "结束流程")
  if (!confirmed) return
  flowBusy.value = true
  try {
    flowView.value = await getApi().assistant.guidedFlowAbandon(props.projectId, flowView.value.run_id)
    flowError.value = ""
  }
  catch (cause) { flowError.value = cause.message || "流程结束失败，请稍后重试。" }
  finally { flowBusy.value = false }
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
// 切换项目时清空上一项目的修订批处理状态，避免结果串项目显示
watch(() => props.projectId, () => {
  chapterExclusionError.value = ""
  revisionItems.value = []
  revisionError.value = ""
  revisionInstruction.value = ""
  selectedIssueIds.value = []
  flowView.value = null
  flowError.value = ""
})
// 轮询生命周期：active 且项目变化时重置重启；同一项目不重复 start；
// 失活与卸载都停表并置空句柄。
let poller = null
let pollerProjectId = null
function stopPoller() {
  if (poller) { clearInterval(poller); poller = null }
  pollerProjectId = null
}
function startPoller() {
  if (poller && pollerProjectId === props.projectId) return
  stopPoller()
  poller = setInterval(() => { refreshResults(); pollRevisionTasks(); refreshRevisionFlow() }, 8000)
  pollerProjectId = props.projectId
}
watch([() => props.active, () => props.projectId], ([active]) => { if (active) { load(); startPoller() } else stopPoller() }, { immediate: true })
onBeforeUnmount(() => { chapterChoicesRequest++; stopPoller() })
</script>

<style scoped>
.editorial-desk{display:grid;gap:16px;padding:16px;overflow-y:auto;min-height:0;color:var(--text-primary);line-height:1.55}.editorial-desk__heading,.editorial-desk__section-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.editorial-desk__heading p,.editorial-desk__section p{margin:6px 0;color:var(--text-secondary)}.editorial-desk__section{border:1px solid var(--border);border-radius:12px;padding:14px;background:var(--surface)}.editorial-desk__section summary{cursor:pointer;font-weight:700}.editorial-desk__section summary small{font-weight:400;color:var(--text-secondary)}.editorial-desk__section h3,.editorial-desk__section h4{margin:0 0 8px}.editorial-desk__section label{display:grid;gap:4px;margin:10px 0;font-size:14px}.editorial-desk__section label small{font-weight:400;color:var(--text-secondary)}.editorial-desk__section input:not([type=checkbox]),.editorial-desk__section textarea,.editorial-desk__section select{width:100%;min-height:38px;padding:8px;border:1px solid var(--border);border-radius:8px;background:var(--surface);color:var(--text-primary)}.editorial-desk__section fieldset{display:flex;flex-wrap:wrap;gap:6px 12px;border:0;padding:4px 0;margin:8px 0}.editorial-desk__section fieldset label,.editorial-desk__section>label:has(input[type=checkbox]){display:flex;align-items:center;gap:6px;margin:0}.editorial-desk__scope{display:flex;gap:10px;flex-wrap:wrap}.editorial-desk__scope label{flex:1 1 110px}.editorial-desk__actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:10px}.editorial-desk__error{color:var(--danger,#b42318);padding:8px;background:var(--danger-soft,#fff4f2);border-radius:8px}.editorial-desk__status{font-weight:700}.editorial-desk__issues{display:grid;gap:10px;margin-top:14px}.editorial-desk__revision{border:1px solid var(--border);border-radius:10px;padding:12px;margin-top:12px;background:var(--surface)}.editorial-desk__revision h4{margin:0 0 8px}.editorial-desk__revision label{display:grid;gap:4px;margin:10px 0;font-size:14px}.editorial-desk__revision label small{font-weight:400;color:var(--text-secondary)}.editorial-desk__revision textarea{width:100%;min-height:38px;padding:8px;border:1px solid var(--border);border-radius:8px;background:var(--surface);color:var(--text-primary)}.editorial-desk__revision-results{margin-top:8px;display:grid;gap:6px}.editorial-desk__revision-results p{margin:0;color:var(--text-primary)}
.editorial-desk__note{font-size:12px;color:var(--text-secondary)}
.editorial-desk__error-detail{font-size:12px;color:var(--text-secondary)}.editorial-desk__error-detail summary{cursor:pointer;font-weight:400}.editorial-desk__error-detail p{margin:6px 0;word-break:break-all}
.editorial-desk__flowstrip{border:1px solid var(--border);border-radius:12px;padding:14px;margin-top:12px;background:var(--surface);display:grid;gap:10px}
.editorial-desk__flowstrip header p{margin:4px 0 0;color:var(--text-secondary);font-size:13px}
.editorial-desk__flow-status{font-size:12px;color:var(--text-secondary);white-space:nowrap}
.editorial-desk__flowstrip[data-status] .editorial-desk__flow-status{font-weight:700}
.editorial-desk__flow-steps{list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap;gap:6px 16px;font-size:13px;color:var(--text-secondary)}
.editorial-desk__flow-steps li{display:flex;align-items:center;gap:6px}
.editorial-desk__flow-steps li[data-state="active"]{color:var(--text-primary);font-weight:700}
.editorial-desk__flow-steps li[data-state="blocked"]{color:var(--danger,#a33a2a)}
.editorial-desk__flowstrip>p{margin:0;font-size:13px;line-height:1.55;color:var(--text-primary)}@media(max-width:600px){.editorial-desk{padding:12px}.editorial-desk__heading,.editorial-desk__section-head{display:block}.editorial-desk__section-head select{margin-top:8px}}
</style>
