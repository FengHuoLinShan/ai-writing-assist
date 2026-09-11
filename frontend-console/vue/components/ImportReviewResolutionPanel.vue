<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue"
import { getApi, getConfirm, getRouter } from "../bridge/index.js"
import { useWorkflowPolling } from "../composables/useWorkflowPolling.js"
import { persistActiveWorkflow, recoverActiveWorkflows } from "../../shared/workflowProgress.js"

const props = defineProps({ projectId: { type: String, required: true }, sourceTaskId: { type: String, default: null } })
const emit = defineEmits(["updated"])
const api = getApi(), polling = useWorkflowPolling()
const summary = ref(null), task = ref(null), taskId = ref(null), error = ref(""), submitting = ref(false)
const startChapter = ref(1), endChapter = ref(0), open = ref(false), filter = ref("decision")
let epoch = 0
const info = computed(() => task.value?.result?.review_resolution || {})
const busy = computed(() => submitting.value || ["pending", "running"].includes(task.value?.status))
const labels = { organized: "已整理", decision: "需要决定", optional: "可选建议", incomplete: "处理未完成" }
const excluded = ref({}), pendingPackage = ref(null)
const visibleGroups = computed(() => {
  const groups = new Map()
  for (const item of (info.value.groups || []).filter(item => item.outcome === filter.value)) {
    const key = item.group_key || item.key
    if (!groups.has(key)) groups.set(key, { key, question: item.question, items: [] })
    groups.get(key).items.push(item)
  }
  return [...groups.values()]
})
async function acceptGroup(group) {
  const selected = group.items.filter(item => !excluded.value[item.key])
  if (!selected.length || busy.value) return
  const token = epoch
  submitting.value = true; error.value = ""
  try {
    const result = await api.imports.decideReview(taskId.value, props.projectId, { candidate_keys: selected.map(item => item.key), expected_fingerprints: Object.fromEntries(selected.map(item => [item.key, item.fingerprint])), confirmed: true })
    if (token !== epoch) return
    if (result.status === "accepted") { observe(taskId.value, token); emit("updated") }
    else { pendingPackage.value = result.suggestion_id; error.value = "本组还需完成世界规则校验或处理冲突，请打开采用预览。" }
  } catch (err) { if (token === epoch) error.value = err.message || "采用未完成，资料仍保留" }
  finally { if (token === epoch) submitting.value = false }
}
async function applySceneGroup(scene) {
  if (busy.value) return
  const token = epoch
  submitting.value = true; error.value = ""
  try {
    const result = await api.imports.applyReviewSceneGroup(taskId.value, scene.group_key, props.projectId, { expected_fingerprint: scene.fingerprint, confirmed: true })
    if (token !== epoch) return
    if (result.status === "pending") task.value = { ...task.value, status: "pending" }
    observe(taskId.value, token)
    emit("updated")
  } catch (err) { if (token === epoch) error.value = err.message || "场景提案没有应用，原内容保留" }
  finally { if (token === epoch) submitting.value = false }
}

function openScene(scene) { getRouter()?.navigate("outline", "scenes", true, new URLSearchParams({ scene_id: scene.scene_id })) }
function fieldLabel(key) { return { name: "名称", summary: "概要", public_info: "公开资料", hidden_truth: "作者资料", alias: "别名", description: "关系说明" }[key] }
function openPackage() { getRouter()?.navigate("world", "bible", true, new URLSearchParams({ adoption_package_id: pendingPackage.value })) }
async function load(token = epoch) {
  try {
    const value = await api.imports.reviewSummary(props.projectId)
    if (token === epoch) {
      summary.value = value
      if (!taskId.value && value.latest?.task_id) { taskId.value = value.latest.task_id; task.value = { status: value.latest.status, result: { review_resolution: value.latest.result } }; observe(taskId.value, token) }
    }
  }
  catch (err) { if (token === epoch) error.value = err.message || "整理概况暂时无法读取" }
}
function observe(id, token = epoch) {
  const notifyCompletion = ["pending", "running"].includes(task.value?.status)
  polling.stopAll()
  polling.start({ taskId: id, novelId: props.projectId, workflowType: "import_review_resolution",
    onUpdate: (_progress, value) => { if (token === epoch && value) task.value = value },
    onDone: () => { if (token === epoch) { if (notifyCompletion) emit("updated"); load(token) } },
    onFailed: (progress, value) => { if (token === epoch) { task.value = value || { status: "failed" }; error.value = progress.errorMessage || "整理未完成，已处理结果仍保留" } },
  })
}
async function start() {
  if (busy.value) return
  if (!Number.isInteger(startChapter.value) || startChapter.value < 1 || !Number.isInteger(endChapter.value) || endChapter.value < 0 || (endChapter.value && endChapter.value < startChapter.value)) { error.value = "请填写有效的章节范围"; return }
  const token = epoch, projectId = props.projectId
  submitting.value = true; error.value = ""
  try {
    const value = await api.imports.resolveReview({ novel_id: projectId, start_chapter: startChapter.value, end_chapter: endChapter.value, repair_scenes: true, authorization_confirmed: true })
    if (!value.task_id) throw new Error("整理未能开始，请重试")
    try { persistActiveWorkflow({ taskId: value.task_id, workflowType: "import_review_resolution", projectId, label: "智能整理导入资料", view: "world" }) }
    catch { if (token === epoch) error.value = "任务已提交，本机恢复入口保存失败；可在任务列表查看进度。" }
    if (token !== epoch) return
    taskId.value = value.task_id; task.value = { status: "pending" }; open.value = true
    observe(value.task_id, token)
  } catch (err) { if (token === epoch) error.value = err.message || "整理未能开始" }
  finally { if (token === epoch) submitting.value = false }
}
async function act(action) {
  if (!taskId.value || submitting.value) return
  const token = epoch, projectId = props.projectId, id = taskId.value
  if (action === "rollback" && (info.value.packages?.length || info.value.scene_results?.some(item => item.after || item.members?.length)) && !getConfirm()("撤销本次已整理的资料？后续人工修改会保留，有冲突的部分会单独说明。")) return
  submitting.value = true; error.value = ""
  try {
    if (action === "rollback") {
      const result = await api.imports.rollbackReviewResolution(id, projectId)
      if (token === epoch) { task.value = { ...task.value, result: { ...task.value?.result, review_resolution: { ...info.value, rollback: result } } }; emit("updated") }
    } else if (action === "cancel") {
      await api.tasks.cancel(id, projectId)
      if (token === epoch) observe(id, token)
    } else {
      await api.imports.resumeDeepImport(id)
      if (token === epoch) observe(id, token)
    }
  } catch (err) { if (token === epoch) error.value = err.message || "操作未完成，原资料仍保留" }
  finally { if (token === epoch) submitting.value = false }
}
function inspect(item) {
  const kind = { entity: "objects", alias: "aliases", relation: "relations" }[item.kind]
  getRouter()?.navigate("world", "review", true, new URLSearchParams({ kind }))
}
watch(() => `${props.projectId}:${props.sourceTaskId || ''}`, () => {
  const token = ++epoch
  excluded.value = {}; pendingPackage.value = null
  polling.stopAll(); taskId.value = null; task.value = null; summary.value = null; error.value = ""; submitting.value = false
  load(token)
  if (props.sourceTaskId) { taskId.value = props.sourceTaskId; observe(props.sourceTaskId, token); return }
  try {
    const saved = recoverActiveWorkflows(props.projectId).filter(item => item.workflowType === "import_review_resolution").at(-1)
    if (saved) { taskId.value = saved.taskId; observe(saved.taskId, token) }
  } catch { error.value = "本机恢复记录不可用，可从任务列表查看已有整理" }
}, { immediate: true })
onBeforeUnmount(() => { epoch += 1 })
</script>

<template>
  <section class="import-review-resolution" aria-label="智能整理导入资料">
    <h2>先让系统整理，再决定关键问题</h2>
    <p>查证原文，整理可靠资料；身份歧义和冲突交给你决定，其他建议可稍后查看。</p>
    <p v-if="summary">当前有 {{ summary.unclassified || 0 }} 项导入候选尚未整理。</p>
    <button v-if="!open && !busy" class="btn btn-primary" @click="open = true">整理这些资料</button>
    <form v-if="open && !busy" @submit.prevent="start">
      <div class="review-resolution-range">
        <label>起始章节<input v-model.number="startChapter" class="form-input" type="number" min="1" required /></label>
        <label>结束章节（0 表示末章）<input v-model.number="endChapter" class="form-input" type="number" min="0" required /></label>
      </div>
      <p>授权查读所选正文并使用模型。通过质量和证据校验的资料可自动采用；保留作者修改，可停止、恢复或撤销。不会重新导入整本作品。</p>
      <button class="btn btn-primary" type="submit" :disabled="submitting">授权并开始整理</button>
    </form>
    <p v-if="busy" role="status">正在整理资料，可离开后继续查看。</p>
    <p v-if="error" role="alert">{{ error }} <button class="btn btn-sm" @click="load()">重新读取</button></p>
    <p v-if="info.rollback?.status === 'complete'" role="status">本次整理已撤销，以下保留的是处理时的历史记录。</p>
    <div v-if="taskId" class="review-resolution-actions">
      <button v-for="(label, value) in labels" :key="value" class="btn btn-sm" :aria-pressed="filter === value" @click="filter = value">{{ label }}（{{ info.counts?.[value] || 0 }}）</button>
    </div>
    <p v-if="taskId" role="status">已处理 {{ info.processed_count || 0 }} / {{ info.fact_count || 0 }} 项资料；{{ info.question_count || 0 }} 组问题需要决定。</p>
    <article v-for="group in visibleGroups" :key="group.key">
      <strong>{{ group.question || labels[filter] }} · {{ group.items.length }} 项资料</strong>
      <div v-for="item in group.items" :key="item.key">
        <label v-if="['decision', 'optional'].includes(filter)"><input type="checkbox" :checked="!excluded[item.key]" @change="excluded[item.key] = !$event.target.checked" /> {{ item.label || '待核对资料' }}</label>
        <p v-else>{{ item.label }}</p>
        <dl v-if="item.proposed_fields"><template v-for="(value, key) in item.proposed_fields" :key="key"><template v-if="fieldLabel(key) && typeof value === 'string' && value"><dt>{{ fieldLabel(key) }}</dt><dd>{{ value }}</dd></template></template></dl>
        <p>{{ item.explanation || (item.outcome === 'incomplete' ? '此项尚未查证完成，不能作为已确认资料使用。' : '') }}</p>
        <details v-if="item.evidence?.length"><summary>原文依据</summary><blockquote v-for="(ref, index) in item.evidence" :key="index">{{ ref.quote }}</blockquote></details>
        <p v-if="item.reason === 'quality_not_qualified'">此类资料尚未通过自动采用的质量验收，保留为建议。</p>
        <button class="btn btn-sm" @click="inspect(item)">修改或查看详细资料</button>
      </div>
      <button v-if="['decision', 'optional'].includes(filter) && !info.rollback" class="btn btn-primary" :disabled="busy || group.items.every(item => excluded[item.key])" @click="acceptGroup(group)">确认采用本组选中资料</button>
    </article>
    <button v-if="pendingPackage" class="btn" @click="openPackage">打开本组采用预览</button>
    <details v-if="info.scene_results?.length"><summary>场景核对结果（{{ info.scene_results.length }}）</summary><article v-for="scene in info.scene_results" :key="scene.scene_id"><strong>{{ scene.label || '场景' }}</strong><p>{{ scene.explanation }}</p><p v-if="scene.scene_ids?.length > 1">本组 {{ scene.scene_ids.length }} 个场景将一起校验边界。</p><details v-if="scene.preview?.length"><summary>对照原范围与建议边界</summary><article v-for="member in scene.preview" :key="member.scene_id"><strong>{{ member.title }} · 第 {{ member.chapters.join('、') }} 章</strong><p>原范围按当前正文展示，未定位处会明确标出。</p><dl><dt>原起点</dt><dd>{{ member.before_start }}</dd><dt>建议起点</dt><dd>{{ member.after_start }}</dd><dt>原终点</dt><dd>{{ member.before_end }}</dd><dt>建议终点</dt><dd>{{ member.after_end }}</dd></dl></article></details><button v-if="scene.can_apply && !info.rollback" class="btn btn-primary" :disabled="busy" @click="applySceneGroup(scene)">确认应用本组来源修复</button><button class="btn btn-sm" @click="openScene(scene)">打开场景处理</button></article></details>
    <p v-if="info.rollback" role="status">{{ info.rollback.status === 'complete' ? '本次可撤销修改已恢复。' : '部分修改因后续编辑或引用而保留，请检查冲突。' }}</p>
    <div class="review-resolution-actions">
      <button v-if="busy && taskId" class="btn btn-sm" :disabled="submitting" @click="act('cancel')">停止整理</button>
      <button v-if="task?.available_actions?.includes('resume') && !busy && !info.rollback" class="btn btn-sm" @click="act('resume')">继续整理</button>
      <button v-if="!busy && task?.status === 'failed' && !info.packages?.length && !info.scene_results?.some(item => item.after || item.members?.length) && !info.rollback" class="btn btn-sm" @click="act('rollback')">结束本次整理</button>
      <button v-if="!busy && (info.packages?.length || info.scene_results?.some(item => item.after || item.members?.length)) && info.rollback?.status !== 'complete'" class="btn btn-sm" @click="act('rollback')">撤销本次整理</button>
    </div>
  </section>
</template>

<style scoped>
.import-review-resolution { padding: 16px; margin-block: 16px; border: 1px solid var(--border); border-radius: var(--radius-md); }
.review-resolution-range, .review-resolution-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-block: 12px; }
.review-resolution-range label { flex: 1 1 180px; min-width: 0; }
.import-review-resolution input, .import-review-resolution button { min-height: 44px; }
.import-review-resolution article { padding-block: 12px; border-bottom: 1px solid var(--border); }
</style>
