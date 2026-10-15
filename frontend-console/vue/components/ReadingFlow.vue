<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { getApi, getConfirm } from "../bridge/index.js"

const props = defineProps({ projectId: { type: String, required: true }, entry: { type: Boolean, default: false } })
const emit = defineEmits(["state"])
const state = ref(null), busy = ref(false), error = ref(""), preview = ref(null), pending = ref(null)
const endChapter = ref(1), requestLimit = ref(20), discoverDetails = ref(false)
const discoverSpatial = ref(true)
const recomputeCompleted = ref(false), fromScene = ref(1)
const scopeKind = ref("scene"), targetId = ref(""), targetQuery = ref("")
const targets = ref([]), targetTotal = ref(0), targetOffset = ref(0)
const proposals = ref(null)
const worldAuditSupplementPreview = ref(null)
const rescanFrom = ref(1), rescanThrough = ref(1), rescanCategories = ref([])
const rescanPreview = ref(null), rescanPending = ref(null)
const rescanActive = computed(() => run.value?.category_rescans?.some(item => ["pending", "running"].includes(item.status)))
const opened = ref(false)
let generation = 0, timer = null
const run = computed(() => state.value?.run)
const scopeBudget = computed(() => (recomputeCompleted.value || ["failed", "source_changed"].includes(run.value?.status) ? state.value?.default_budget_mode : run.value?.budget_mode || state.value?.default_budget_mode) === "confirmed_scope")
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
  if (opened.value && (["pending", "running"].includes(run.value?.status) || rescanActive.value)) {
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
    : "为当前作品启用逐场景理解试用？没有场景时会先准备边界，并计入本次调用额度。切换后，旧的完整和分阶段整理不能继续，世界资料会保留候选供核对采用，剧情结构候选经独立复核后进入故事大纲草稿，采用时会重新校验原文。已保存正文与历史保留，可暂停自动理解后继续写作。"
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
      discover_details: discoverDetails.value,
      ...(discoverSpatial.value ? { discover_spatial: true } : {}),
      end_chapter: continuing || revising || scoped ? run.value.end_chapter : Number(endChapter.value), request_limit: scopeBudget.value ? null : Number(requestLimit.value),
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
    if (current() && run.value?.run_key === key) {
      proposals.value = result
      if (!result.items.some(item => item.supplement?.attempt_id === worldAuditSupplementPreview.value?.attempt_id)) {
        worldAuditSupplementPreview.value = null
      }
    }
  })
}
async function previewWorldAuditSupplement(item) {
  await perform(async current => {
    const key = run.value.run_key
    const attemptId = item.supplement.attempt_id
    const result = await api().worldAuditSupplementPreview(props.projectId, key, attemptId)
    if (current() && run.value?.run_key === key) {
      worldAuditSupplementPreview.value = {
        ...result,
        operation_id: crypto.randomUUID(),
        attempt_id: attemptId,
      }
    }
  })
}
async function startWorldAuditSupplement(item) {
  const preview = worldAuditSupplementPreview.value
  if (!preview || preview.attempt_id !== item.supplement.attempt_id) return
  const calls = preview.call_count
  const additional = preview.additional_budget
  const message = `补审将分为 ${preview.group_count} 组，调用模型 ${calls} 次。${preview.deferred_count ? `${preview.deferred_count} 组仍超过单项容量，需要结合原文核对。` : ""}${additional ? `现有额度不足，将增加 ${additional} 次调用额度。` : ""}确认后开始？`
  if (!await getConfirm()(message)) return
  await perform(async current => {
    const key = run.value.run_key
    try {
      await api().worldAuditSupplementStart(props.projectId, key, preview.attempt_id, {
        operation_id: preview.operation_id,
        expected_fingerprint: preview.fingerprint,
        authorization_confirmed: true,
      })
    } catch (err) {
      if (err.status === 409) worldAuditSupplementPreview.value = null
      throw err
    }
    if (!current() || run.value?.run_key !== key) return
    worldAuditSupplementPreview.value = null
    const refreshed = await api().proposals(
      props.projectId, key, proposals.value?.offset || 0,
    )
    if (current() && run.value?.run_key === key) proposals.value = refreshed
  })
}
async function resumeWorldAuditSupplement(item) {
  await perform(async current => {
    const key = run.value.run_key
    await api().worldAuditSupplementResume(props.projectId, key, item.supplement.attempt_id)
    if (!current() || run.value?.run_key !== key) return
    const refreshed = await api().proposals(
      props.projectId, key, proposals.value?.offset || 0,
    )
    if (current() && run.value?.run_key === key) proposals.value = refreshed
  })
}
async function prepareRescan() {
  await perform(async current => {
    const key = run.value.run_key
    const request = { operation_id: crypto.randomUUID(), from_scene_index: Number(rescanFrom.value) - 1,
      through_scene_index: Number(rescanThrough.value) - 1, categories: [...rescanCategories.value], request_limit: run.value.budget_mode === "confirmed_scope" ? null : Number(requestLimit.value) }
    const result = await api().categoryRescanPreview(props.projectId, key, request)
    if (current() && key === run.value?.run_key) rescanPreview.value = { ...result, request }
  })
}
async function startRescan() {
  await perform(async current => {
    const key = run.value.run_key
    rescanPending.value ||= { ...rescanPreview.value.request, expected_fingerprint: rescanPreview.value.fingerprint, authorization_confirmed: true }
    try { await api().categoryRescanStart(props.projectId, key, rescanPending.value) }
    catch (err) {
      if (current() && [400, 403, 404, 409, 422].includes(err.status)) rescanPreview.value = rescanPending.value = null
      throw err
    }
    if (!current()) return
    rescanPreview.value = rescanPending.value = null
    await read(current)
  })
}
async function resumeRescan(item) {
  await perform(async current => {
    await api().categoryRescanResume(props.projectId, run.value.run_key, item.operation_id)
    if (current()) await read(current)
  })
}
watch([rescanFrom, rescanThrough, rescanCategories, requestLimit], () => { if (!rescanPending.value) rescanPreview.value = null }, { deep: true })
watch(() => run.value?.run_key, () => {
  proposals.value = null
  worldAuditSupplementPreview.value = null
  discoverDetails.value = !!run.value?.discovery_enabled
  discoverSpatial.value = run.value ? run.value.spatial_discovery_enabled === true : true
  rescanPreview.value = rescanPending.value = null
  rescanFrom.value = 1; rescanThrough.value = Math.max(1, run.value?.completed_scenes || 1)
  rescanCategories.value = (run.value?.discovery_categories || []).filter(item => ["language_habit", "external_appearance"].includes(item.key)).map(item => item.key)
})
async function loadTargets(offset = 0) {
  await perform(async current => {
    const result = await api().targets(props.projectId, run.value.run_key, { kind: scopeKind.value, query: targetQuery.value, offset })
    if (!current()) return
    targets.value = result.items; targetTotal.value = result.total; targetOffset.value = offset
    targetId.value = ""
  })
}
watch(scopeKind, () => { targets.value = []; targetId.value = ""; targetTotal.value = 0; targetOffset.value = 0 })
watch([endChapter, requestLimit, recomputeCompleted, fromScene, scopeKind, targetId, discoverDetails, discoverSpatial], () => { if (!pending.value) preview.value = null })
watch(() => props.projectId, () => {
  generation++; clearTimeout(timer)
  state.value = preview.value = pending.value = proposals.value = null
  worldAuditSupplementPreview.value = null
  rescanPreview.value = rescanPending.value = null
  rescanCategories.value = []; rescanFrom.value = rescanThrough.value = 1
  error.value = ""; busy.value = false; endChapter.value = 1
  recomputeCompleted.value = false; fromScene.value = 1
  discoverDetails.value = false; discoverSpatial.value = true
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
      <p v-if="run" role="status">{{ statusText }} · {{ run.preparing_scenes ? "准备场景边界" : run.preparing_structure ? "整理剧情结构候选" : `${run.completed_scenes} / ${run.total_scenes} 场景` }}</p>
      <p v-if="run?.unchecked_discovery_gaps?.length" role="status">保留 {{ run.unchecked_discovery_gaps.length }} 处作者确认的未检查缺口；原请求结果未知，后续完成也不代表这部分已检查。</p>
      <progress v-if="run?.total_scenes" :value="run.completed_scenes" :max="run.total_scenes" aria-label="理解进度" />
      <div class="reading-actions">
        <button class="btn btn-sm" type="button" :disabled="busy" @click="refresh">刷新进度</button>
        <button v-if="!enabled" class="btn btn-sm" type="button" :disabled="busy" @click="changeEngine('evolution')">启用逐场景理解…</button>
        <button v-else class="btn btn-sm" type="button" :disabled="busy" @click="changeEngine('read_only')">暂停自动理解…</button>
        <button v-if="run?.can_resume" class="btn btn-primary" type="button" :disabled="busy" @click="resume">恢复理解</button>
      </div>
      <details v-if="run?.completed_scenes && run.discovery_categories?.length" class="reading-category-rescan">
        <summary>补扫细节类别</summary>
        <p>对已读范围补查选定类别。旧场景回执保留，只新增有来源、经复核的细节记录；未选择的类别不算已检查。</p>
        <fieldset :disabled="busy || rescanActive || !!rescanPending">
          <legend>范围与类别</legend>
          <label>从第几场<input v-model.number="rescanFrom" type="number" min="1" :max="run.completed_scenes" aria-label="补扫起始场景"></label>
          <label>读到第几场<input v-model.number="rescanThrough" type="number" :min="rescanFrom" :max="run.completed_scenes" aria-label="补扫截止场景"></label>
          <label v-for="item in run.discovery_categories" :key="item.key" class="reading-recompute-toggle"><input v-model="rescanCategories" type="checkbox" :value="item.key">{{ item.label }}</label>
          <button type="button" class="btn btn-sm" :disabled="!rescanCategories.length || run.status !== 'completed'" @click="prepareRescan">预览类别补扫</button>
        </fieldset>
        <div v-if="rescanPreview" class="reading-confirmation">
          <p v-if="rescanPreview.budget_mode === 'confirmed_scope'">完成本次确认范围：补扫 {{ rescanPreview.scene_count }} 场的所选类别，并核对发现结果。</p>
          <p v-else>预计 {{ rescanPreview.scene_count }} 场，基础发现与复核约 {{ rescanPreview.call_count }} 次调用，含去重核对最多 {{ rescanPreview.maximum_calls }} 次；现有额度 {{ rescanPreview.budget_remaining }} 次，需增加 {{ rescanPreview.additional_budget }} 次。</p>
          <button type="button" class="btn btn-primary" :disabled="busy" @click="startRescan">{{ rescanPending ? "确认补扫启动结果" : "确认并开始补扫" }}</button>
          <button v-if="!rescanPending" type="button" class="btn btn-sm" :disabled="busy" @click="rescanPreview = null">取消补扫</button>
        </div>
        <p v-for="item in run.category_rescans || []" :key="item.operation_id" role="status">
          第 {{ item.from_scene_index + 1 }}—{{ item.through_scene_index + 1 }} 场：{{ ({ pending: "补扫等待开始", running: "正在补扫，已完成结果保留", completed: "补扫完成，可查看类别覆盖与来源", failed: "补扫中断，结果保留", needs_reconciliation: "请求结果与费用尚未核清，不能重发" })[item.status] || "请刷新核对补扫状态" }}
          <button v-if="item.can_resume" type="button" class="btn btn-sm" :disabled="busy || rescanActive" @click="resumeRescan(item)">恢复类别补扫</button>
        </p>
      </details>
      <section v-if="run" class="reading-proposals" aria-label="本次世界资料提案">
        <button class="btn btn-sm" type="button" :disabled="busy" @click="loadProposals()">查看世界资料提案</button>
        <template v-if="proposals">
          <p>这里只回看提案和原文证据。已保存的候选请到世界资料中核对后采用；剧情结构候选完成后进入故事大纲草稿，采用时会重新校验理解来源。有疑问的提案可修改正文或从对应场景重新理解。</p>
          <p v-if="!proposals.items.length">本页暂未产生世界资料提案。</p>
          <details v-for="(item, index) in proposals.items" :key="`${item.scene_index}-${index}`">
            <summary>第 {{ item.scene_index + 1 }} 场 · {{ item.stale ? "历史或尚未提交" : item.review_status === "passed" ? "候选待采用" : item.review_groups?.some(group => group.status === "passed") ? "部分已核对，其余待核对" : "仍需核对" }}</summary>
            <p v-if="item.stale">来源已变化或本场尚未提交，请核对后再使用。</p>
            <details v-if="item.review_groups?.length" class="reading-review-groups">
              <summary>分项核对：{{ item.review_groups.filter(group => group.status === "passed").length }} / {{ item.review_groups.length }} 项通过</summary>
              <ul>
                <li v-for="(group, groupIndex) in item.review_groups" :key="groupIndex">
                  {{ group.candidate_count }} 条提案：{{ group.status === "passed" ? "已核对" : "仍需核对" }}
                  <span v-for="(issue, issueIndex) in group.issues" :key="issueIndex">{{ issue }}</span>
                </li>
              </ul>
            </details>
            <section v-if="item.supplement?.available || item.supplement?.status" class="reading-world-audit-supplement">
              <p v-if="item.supplement.status === 'pending' || item.supplement.status === 'running'" role="status">延后场景补审{{ item.supplement.status === 'pending' ? '等待开始' : '进行中' }}。重新查看提案可读取最新进度。</p>
              <p v-else-if="item.supplement.status === 'completed'">补审已结束，已核对 {{ item.supplement.reviewed_groups }} 组；通过的候选已保存为待作者采用资料。</p>
              <p v-else-if="item.supplement.status === 'needs_reconciliation'">有一次请求结果尚未确认，系统不会重发；请先核对请求和费用状态。</p>
              <p v-else-if="item.supplement.status === 'failed' || item.supplement.status === 'cancelled'">补审已中断，已完成的分组结果保留；请核对原文与当前世界对象。</p>
              <button v-if="item.supplement.can_resume" class="btn btn-sm" type="button" :disabled="busy" @click="resumeWorldAuditSupplement(item)">继续补审</button>
              <button v-if="item.supplement.available" class="btn btn-sm" type="button" :disabled="busy" @click="previewWorldAuditSupplement(item)">预览延后场景补审</button>
              <div v-if="worldAuditSupplementPreview && worldAuditSupplementPreview.attempt_id === item.supplement.attempt_id" class="reading-confirmation">
                <p v-if="run.budget_mode === 'confirmed_scope'">完成本次确认范围：补审 {{ worldAuditSupplementPreview.group_count }} 组，超出输入容量的资料保留待核对。</p>
                <p v-else>预计 {{ worldAuditSupplementPreview.group_count }} 组、{{ worldAuditSupplementPreview.call_count }} 次模型调用；{{ worldAuditSupplementPreview.deferred_count }} 组仍需人工核对。现有额度 {{ worldAuditSupplementPreview.budget_remaining }} 次，需增加 {{ worldAuditSupplementPreview.additional_budget }} 次。</p>
                <button class="btn btn-primary" type="button" :disabled="busy" @click="startWorldAuditSupplement(item)">确认补审</button>
              </div>
            </section>
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
          <p v-if="scopeBudget">完成本次确认范围</p>
          <label v-else>{{ run?.status === 'needs_budget' ? "本次追加调用上限" : "本次最多调用模型" }}<input v-model.number="requestLimit" type="number" min="1" max="1000" required :disabled="busy || !!pending"></label>
        </div>
        <label v-if="run?.status === 'completed'" class="reading-recompute-toggle"><input v-model="recomputeCompleted" type="checkbox" :disabled="busy || !!pending">重新核对已有场景</label>
        <label v-if="!run || recomputeCompleted || ['source_changed', 'failed'].includes(run.status)"><input v-model="discoverDetails" type="checkbox" :disabled="busy || !!pending">同时发现条件行为、线索与承诺，持续更新细节台账</label>
        <p v-else>细节发现：{{ run.discovery_enabled ? '已启用' : '本轮未启用，可选择重新核对已有场景时开启' }}</p>
        <label v-if="!run || recomputeCompleted || ['source_changed', 'failed'].includes(run.status)" class="reading-recompute-toggle"><input v-model="discoverSpatial" type="checkbox" aria-label="同时发现空间线索" :disabled="busy || !!pending">同时发现地点、空间关系与行程线索，整理为待审地图资料</label>
        <p v-else>空间发现：{{ run.spatial_discovery_enabled ? '已启用，沿用本轮设置' : '本轮未启用，可选择重新核对已有场景时开启' }}</p>
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
          <p v-if="preview.budget_mode === 'confirmed_scope'">完成本次确认范围：准备边界、逐场理解、独立复核和整理。已完成结果保留，有疑问时留待核对。</p>
          <p v-else-if="preview.scene_count === null">先准备场景边界，完成后逐场景理解。边界准备、必要修复、理解、独立复核和剧情结构整理共同使用最多 {{ preview.request_limit }} 次模型调用；额度用完会暂停，不自动追加。</p>
          <p v-else-if="Number.isInteger(preview.recompute_from_scene_index)">保留前 {{ preview.inherited_scene_count }} 场已核实的理解，从第 {{ preview.recompute_from_scene_index + 1 }} 场起重新核对后续场景；最多调用模型 {{ preview.request_limit }} 次。旧结果与费用记录保留。<template v-if="preview.expanded_scope">前面的来源或场景已变化，范围已向前扩大。</template></p>
          <p v-else>本次{{ preview.request.mode === 'continue' ? "继续读取" : "读取" }} {{ preview.scene_count }} 个场景，理解、独立复核与剧情结构整理合计最多调用模型 {{ preview.request_limit }} 次。理解结果可追溯来源，冲突留待确认；不会改写正文或覆盖作者确认。</p>
          <p v-if="preview.discovery_enabled">细节发现及独立核对{{ preview.budget_mode === 'confirmed_scope' ? '包含在本次确认范围内' : '也使用本次调用额度' }}。台账只保留有据理解，作者判断另行保存。</p>
          <p v-if="preview.spatial_discovery_enabled">空间线索抽取和独立核对可能产生模型费用，共用本次额度。资料只作为候选，需作者审核后采用；不会自动生成地图图片。</p>
          <ul v-if="Object.keys(preview.optional_steps || {}).length" aria-label="可选步骤调用额度">
            <li v-for="(step, name) in preview.optional_steps" :key="name">{{ name === 'spatial' ? '空间发现' : name === 'details' ? '细节发现' : name }}：预计 {{ step.request_range?.minimum ?? 0 }}—{{ step.request_range?.maximum ?? step.quota }} 次调用，独立额度 {{ step.quota }} 次{{ step.used ? `，已使用 ${step.used} 次` : '' }}。</li>
          </ul>
          <p v-if="preview.spatial_discovery_enabled">可选步骤额度用完会留下未检查缺口；不会自动追加额度，也不会因空间发现失败中断主阅读。</p>
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
.reading-category-rescan fieldset { display: flex; flex-wrap: wrap; gap: .75rem; min-width: 0; padding: .75rem; border: 1px solid var(--border-color, #ddd); border-radius: .5rem; }
progress { width: 100%; }
.reading-confirmation { padding-block-start: .75rem; }
</style>
