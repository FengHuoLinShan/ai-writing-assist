<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { getApi, getConfirm } from "../bridge/index.js"

const props = defineProps({ projectId: { type: String, required: true }, entry: { type: Boolean, default: false } })
const emit = defineEmits(["state"])
const state = ref(null), busy = ref(false), error = ref(""), preview = ref(null), pending = ref(null)
const endChapter = ref(1), requestLimit = ref(20)
const recomputeCompleted = ref(false), fromScene = ref(1)
const scopeKind = ref("scene"), targetId = ref(""), targetQuery = ref("")
const targets = ref([]), targetTotal = ref(0), targetOffset = ref(0)
const proposals = ref(null)
const opened = ref(false)
let generation = 0, timer = null
const run = computed(() => state.value?.run)
const enabled = computed(() => state.value?.engine?.engine === "evolution")
const canStart = computed(() => enabled.value && (!run.value || ["completed", "stopped", "source_changed", "needs_budget"].includes(run.value.status) || (run.value.status === "failed" && run.value.total_scenes > 0 && !run.value.preparing_scenes)))
const statusText = computed(() => ({
  completed: "所选范围理解已更新", pending: "等待读取正文", running: "正在读取正文、整理变化",
  failed: "理解中断，已完成部分保留", interrupted: "理解中断，已完成部分保留",
  source_changed: "正文已变化，旧结果保留供回看", stopped: "已暂停，历史结果保留",
  needs_reconciliation: "上次请求可能已计费，需要先核对结果，不能直接重试",
  cancelled: "已停止，已完成部分保留",
  needs_budget: "本次调用额度已用完，已完成结果保留",
  needs_scene_review: "场景边界需要确认，请在故事大纲处理后恢复理解",
})[run.value?.status] || "")
const api = () => getApi().evolution

async function perform(action) {
  if (busy.value) return
  const token = generation
  busy.value = true; error.value = ""
  try { await action(() => token === generation) }
  catch (err) { if (token === generation) error.value = err.message || "暂时无法完成，请保留当前范围后重试。" }
  finally { if (token === generation) busy.value = false }
}
function schedule() {
  clearTimeout(timer)
  if (opened.value && ["pending", "running"].includes(run.value?.status)) {
    timer = setTimeout(() => { void refresh() }, 5000)
  }
}
async function read(current) {
  const firstRead = !state.value
  let result
  try { result = await api().status(props.projectId) }
  catch (err) {
    if (current()) {
      emit("state", null)
      if (props.entry && firstRead) opened.value = true
    }
    throw err
  }
  if (!current()) return
  if (result.run?.status === "completed" && state.value?.run?.status !== "completed" && !preview.value && !pending.value) {
    endChapter.value = Math.max(Number(endChapter.value), result.run.end_chapter + 1)
  }
  state.value = result
  emit("state", result)
  if (props.entry && firstRead && result.engine.engine !== "legacy") opened.value = true
  if (result.run?.status === "failed") fromScene.value = Math.min(result.run.total_scenes, result.run.completed_scenes + 1)
  schedule()
}
async function refresh() { await perform(read) }
function toggle(event) {
  opened.value = event.target.open
  if (opened.value) void refresh()
  else clearTimeout(timer)
}
async function changeEngine(engine) {
  const token = generation, projectId = props.projectId, epoch = state.value?.engine?.epoch
  const stop = engine === "read_only"
  const message = stop
    ? "暂停当前作品的自动理解？已完成结果与费用记录会保留。"
    : "为当前作品启用逐场景理解试用？没有场景时会先准备边界，并计入本次调用额度。切换后，旧的完整和分阶段整理不能继续，世界资料会保留候选供核对采用，剧情结构的完整整理尚未接入新流程。已保存正文与历史保留，可暂停自动理解后继续写作。"
  if (!await getConfirm()(message)) return
  if (token !== generation) return
  await perform(async current => {
    await api().switchEngine(projectId, {
      engine, expected_epoch: epoch,
      stop_active: stop, authorization_confirmed: true,
    })
    if (!current()) return
    preview.value = pending.value = null
    await read(current)
  })
}
async function prepare() {
  await perform(async current => {
    const append = run.value?.status === "completed"
    const continuing = run.value?.status === "needs_budget"
    const revising = run.value?.status === "source_changed"
    const scoped = run.value?.status === "failed" || (append && recomputeCompleted.value)
    const request = {
      operation_id: crypto.randomUUID(), mode: continuing ? "continue" : revising ? "revise" : scoped ? "scoped_recompute" : append ? "append" : "bootstrap",
      run_key: append || continuing || revising || scoped ? run.value.run_key : null,
      ...(scoped ? scopeKind.value === "scene"
        ? { from_scene_index: Number(fromScene.value) - 1 }
        : { [scopeKind.value === "entity" ? "entity_id" : "observation_id"]: targetId.value } : {}),
      end_chapter: continuing || revising || scoped ? run.value.end_chapter : Number(endChapter.value), request_limit: Number(requestLimit.value),
    }
    const result = await api().preview(props.projectId, request)
    if (current()) preview.value = { ...result, request }
  })
}
async function start() {
  await perform(async current => {
    pending.value ||= {
      ...preview.value.request, expected_fingerprint: preview.value.fingerprint,
      authorization_confirmed: true,
    }
    let result
    try { result = await api().start(props.projectId, pending.value) }
    catch (err) {
      if (current() && [400, 403, 404, 409, 422].includes(err.status)) {
        pending.value = preview.value = null
      }
      throw err
    }
    if (!current()) return
    state.value = result; preview.value = pending.value = null
    emit("state", result)
    schedule()
  })
}
async function resume() {
  await perform(async current => {
    const result = await api().resume(props.projectId, run.value.run_key)
    if (current()) { state.value = result; schedule() }
  })
}
async function loadProposals(offset = 0) {
  await perform(async current => {
    const key = run.value.run_key
    const result = await api().proposals(props.projectId, key, offset)
    if (current() && run.value?.run_key === key) proposals.value = result
  })
}
watch(() => run.value?.run_key, () => { proposals.value = null })
async function loadTargets(offset = 0) {
  await perform(async current => {
    const result = await api().targets(props.projectId, run.value.run_key, { kind: scopeKind.value, query: targetQuery.value, offset })
    if (!current()) return
    targets.value = result.items; targetTotal.value = result.total; targetOffset.value = offset
    targetId.value = ""
  })
}
watch(scopeKind, () => { targets.value = []; targetId.value = ""; targetTotal.value = 0; targetOffset.value = 0 })
watch([endChapter, requestLimit, recomputeCompleted, fromScene, scopeKind, targetId], () => { if (!pending.value) preview.value = null })
watch(() => props.projectId, () => {
  generation++; clearTimeout(timer)
  state.value = preview.value = pending.value = proposals.value = null
  error.value = ""; busy.value = false; endChapter.value = 1
  recomputeCompleted.value = false; fromScene.value = 1
  scopeKind.value = "scene"; targetId.value = ""; targets.value = []; targetQuery.value = ""; targetTotal.value = 0; targetOffset.value = 0
  if (opened.value || props.entry) void refresh()
})
onMounted(() => { if (props.entry) void refresh() })
onBeforeUnmount(() => { generation++; clearTimeout(timer) })
</script>

<template>
  <details class="reading-flow" :open="opened" @toggle="toggle">
    <summary>逐场景理解 · 试用</summary>
    <p>按保存的正文逐步理解，下一场会读到前面的理解。没有场景时先准备边界；有疑问时留待确认。</p>
    <p v-if="busy" role="status">正在处理…</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <template v-if="state">
      <p v-if="run" role="status">{{ statusText }} · {{ run.preparing_scenes ? "准备场景边界" : `${run.completed_scenes} / ${run.total_scenes} 场景` }}</p>
      <progress v-if="run?.total_scenes" :value="run.completed_scenes" :max="run.total_scenes" aria-label="理解进度" />
      <div class="reading-actions">
        <button class="btn btn-sm" type="button" :disabled="busy" @click="refresh">刷新进度</button>
        <button v-if="!enabled" class="btn btn-sm" type="button" :disabled="busy" @click="changeEngine('evolution')">启用逐场景理解…</button>
        <button v-else class="btn btn-sm" type="button" :disabled="busy" @click="changeEngine('read_only')">暂停自动理解…</button>
        <button v-if="run?.can_resume" class="btn btn-primary" type="button" :disabled="busy" @click="resume">恢复理解</button>
      </div>
      <section v-if="run" class="reading-proposals" aria-label="本次世界资料提案">
        <button class="btn btn-sm" type="button" :disabled="busy" @click="loadProposals()">查看世界资料提案</button>
        <template v-if="proposals">
          <p>这里只回看提案和原文证据。已保存的候选请到世界资料中核对后采用；有疑问的提案可修改正文或从对应场景重新理解。</p>
          <p v-if="!proposals.items.length">本页暂未产生世界资料提案。</p>
          <details v-for="(item, index) in proposals.items" :key="`${item.scene_index}-${index}`">
            <summary>第 {{ item.scene_index + 1 }} 场 · {{ item.stale ? "历史或尚未提交" : item.review_status === "passed" ? "候选待采用" : "仍需核对" }}</summary>
            <p v-if="item.stale">来源已变化或本场尚未提交，请核对后再使用。</p>
            <article v-for="(entity, entityIndex) in item.entities" :key="entityIndex">
              <strong>{{ entity.name }}</strong>
              <p v-for="(text, field) in [entity.summary, entity.public_info, entity.hidden_truth].filter(Boolean)" :key="field">{{ text }}</p>
              <blockquote v-for="(quote, quoteIndex) in entity.evidence_quotes" :key="quoteIndex">{{ quote }}</blockquote>
            </article>
            <article v-for="(alias, aliasIndex) in item.aliases" :key="`alias-${aliasIndex}`">
              <strong>{{ alias.entity }} · 别名 {{ alias.alias }}</strong>
              <blockquote v-for="(quote, quoteIndex) in alias.evidence_quotes" :key="quoteIndex">{{ quote }}</blockquote>
            </article>
            <article v-for="(relation, relationIndex) in item.relations" :key="`relation-${relationIndex}`">
              <strong>{{ relation.source }} · {{ relation.target }}</strong><p>{{ relation.description }}</p>
              <blockquote v-for="(quote, quoteIndex) in relation.evidence_quotes" :key="quoteIndex">{{ quote }}</blockquote>
            </article>
            <p v-for="(finding, findingIndex) in item.findings" :key="`finding-${findingIndex}`">需核对：{{ finding }}</p>
            <p v-if="item.uncertainties.length">本场还有未能确定的内容，请结合原文核对。</p>
          </details>
          <div class="reading-actions">
            <button v-if="proposals.offset" class="btn btn-sm" type="button" :disabled="busy" @click="loadProposals(Math.max(0, proposals.offset - proposals.limit))">上一页提案</button>
            <button v-if="proposals.offset + proposals.limit < proposals.total" class="btn btn-sm" type="button" :disabled="busy" @click="loadProposals(proposals.offset + proposals.limit)">下一页提案</button>
          </div>
        </template>
      </section>
      <form v-if="canStart || pending" @submit.prevent="prepare">
        <div class="reading-fields">
          <p v-if="['needs_budget', 'source_changed', 'failed'].includes(run?.status) || recomputeCompleted">沿已确认范围读到第 {{ run.end_chapter }} 章。</p>
          <label v-else>读到第几章<input v-model.number="endChapter" type="number" min="1" required :disabled="busy || !!pending"></label>
          <label>{{ run?.status === 'needs_budget' ? "本次追加调用上限" : "本次最多调用模型" }}<input v-model.number="requestLimit" type="number" min="1" max="1000" required :disabled="busy || !!pending"></label>
        </div>
        <label v-if="run?.status === 'completed'" class="reading-recompute-toggle"><input v-model="recomputeCompleted" type="checkbox" :disabled="busy || !!pending">重新核对已有场景</label>
        <template v-if="run?.status === 'failed' || recomputeCompleted">
          <label>重新核对什么<select v-model="scopeKind" :disabled="busy || !!pending"><option value="scene">一段场景</option><option value="entity">人物或世界对象</option><option value="observation">一条已有观察</option></select></label>
          <label v-if="scopeKind === 'scene'">从第几场重新核对<input v-model.number="fromScene" type="number" min="1" :max="run?.total_scenes" required :disabled="busy || !!pending"></label>
          <div v-else>
            <p>从已提交理解中选择。人物陈述、推测等仍保留原性质；选择不会将其确认为事实。</p>
            <label>查找名称或观察文字<input v-model="targetQuery" type="search" maxlength="200" :disabled="busy || !!pending"></label>
            <button class="btn" type="button" :disabled="busy || !!pending" @click="loadTargets()">查找已读内容</button>
            <label v-if="targets.length">核对目标<select v-model="targetId" required :disabled="busy || !!pending"><option disabled value="">请选择</option><option v-for="item in targets" :key="item.id" :value="item.id">第 {{ item.scene_index + 1 }} 场 · {{ item.label }}</option></select></label>
            <p v-if="targetId">原文：{{ targets.find(item => item.id === targetId)?.quote }}</p>
            <p role="status">找到 {{ targetTotal }} 项。{{ targetTotal === 0 ? '没有找到不代表正文中不存在；可改用场景范围核对。' : '' }}</p>
            <button v-if="targetOffset > 0" class="btn" type="button" :disabled="busy || !!pending" @click="loadTargets(Math.max(0, targetOffset - 50))">上一页</button>
            <button v-if="targetOffset + targets.length < targetTotal" class="btn" type="button" :disabled="busy || !!pending" @click="loadTargets(targetOffset + 50)">下一页</button>
          </div>
        </template>
        <button class="btn" type="submit" :disabled="busy || !!pending || ((run?.status === 'failed' || recomputeCompleted) && scopeKind !== 'scene' && !targetId)">查看理解范围</button>
        <div v-if="preview" class="reading-confirmation">
          <p v-if="preview.recompute_target">核对目标：{{ preview.recompute_target.label }}。以它最早出现的场景定位，重新读取该场及依赖它的后续场景。</p>
          <p v-if="preview.scene_count === null">先准备场景边界，完成后逐场景理解。边界准备、必要修复、理解和独立复核共同使用最多 {{ preview.request_limit }} 次模型调用；额度用完会暂停，不自动追加。</p>
          <p v-else-if="Number.isInteger(preview.recompute_from_scene_index)">保留前 {{ preview.inherited_scene_count }} 场已核实的理解，从第 {{ preview.recompute_from_scene_index + 1 }} 场起重新核对后续场景；最多调用模型 {{ preview.request_limit }} 次。旧结果与费用记录保留。<template v-if="preview.expanded_scope">前面的来源或场景已变化，范围已向前扩大。</template></p>
          <p v-else>本次{{ preview.request.mode === 'continue' ? "继续读取" : "读取" }} {{ preview.scene_count }} 个场景，理解与独立复核合计最多调用模型 {{ preview.request_limit }} 次。理解结果可追溯来源，冲突留待确认；不会改写正文或覆盖作者确认。</p>
          <p>本次使用模型：{{ preview.model }}</p>
          <button class="btn btn-primary" type="button" :disabled="busy" @click="start">{{ pending ? "确认启动结果" : "确认并开始理解" }}</button>
        </div>
      </form>
    </template>
    <button v-else-if="!busy" class="btn" type="button" @click="refresh">读取理解状态</button>
  </details>
</template>

<style scoped>
.reading-flow { margin-block: 1.5rem; padding: 1rem; border: 1px solid var(--border-color, #ddd); border-radius: .7rem; }
.reading-proposals article { margin-block: 1rem; padding-inline-start: .75rem; border-inline-start: 2px solid var(--border-color, #ddd); }
blockquote { margin: .5rem 0; overflow-wrap: anywhere; color: var(--text-secondary); }
summary { cursor: pointer; font-weight: 600; }
p { overflow-wrap: anywhere; }
.reading-actions, .reading-fields { display: flex; flex-wrap: wrap; gap: .75rem; margin-block: .8rem; }
label { display: grid; gap: .35rem; flex: 1 1 12rem; min-width: 0; }
.reading-recompute-toggle { display: flex; align-items: center; gap: .5rem; }
input:not([type="checkbox"]), select { width: 100%; max-width: 100%; box-sizing: border-box; }
progress { width: 100%; }
.reading-confirmation { padding-block-start: .75rem; }
</style>
