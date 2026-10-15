<template>
  <section class="interaction-author" aria-label="RP旅程管理">
    <header class="interaction-author__header">
      <div>
        <p class="interaction-author__eyebrow">作品关联的角色旅程</p>
        <h2>RP旅程</h2>
        <p class="interaction-author__intro">管理由当前作品资料开启的独立旅程。旅程历史仍保留在自己的空间里。</p>
      </div>
      <button class="btn btn-sm" type="button" :disabled="loading || busy" @click="load">重新读取</button>
    </header>

    <p v-if="loading" class="interaction-author__status" role="status">正在读取关联旅程…</p>
    <p v-if="error" class="interaction-author__error" role="alert">{{ error }}</p>
    <p v-if="backupError" class="interaction-author__error" role="alert">本地草稿暂不可用，未保存的输入仍留在当前页。</p>

    <div class="interaction-author__toolbar">
      <label>查看
        <select v-model="statusFilter" :disabled="loading || busy">
          <option value="active">进行中的旅程</option>
          <option value="archived">已归档旅程</option>
        </select>
      </label>
      <span v-if="journeys.length">{{ journeys.length }} 段旅程</span>
    </div>

    <p v-if="!loading && !journeys.length" class="interaction-author__empty">
      {{ statusFilter === 'active' ? '当前作品资料还没有开启关联旅程。' : '这里还没有已归档的关联旅程。' }}
    </p>

    <div v-if="journeys.length" class="interaction-author__layout">
      <nav class="interaction-author__journeys" aria-label="关联旅程列表">
        <button
          v-for="journey in journeys"
          :key="journey.id"
          type="button"
          class="interaction-author__journey"
          :aria-current="selected?.id === journey.id ? 'true' : undefined"
          :disabled="busy || loading"
          @click="selectJourney(journey)"
        >
          <strong>{{ journey.title }}</strong>
          <span>{{ journey.status === 'active' ? '进行中' : '已归档' }} · 资料版本 {{ journey.source.version_number }}</span>
          <small v-if="journey.source.stale">关联资料有新版本，旅程仍使用已冻结的旧版。</small>
        </button>
      </nav>

      <article v-if="selected" class="interaction-author__detail" aria-label="所选旅程">
        <div class="interaction-author__detail-head">
          <div>
            <p class="interaction-author__eyebrow">{{ selected.status === 'active' ? '进行中的旅程' : '已归档的旅程' }}</p>
            <h3>{{ selected.title }}</h3>
          </div>
          <span class="interaction-author__source-chip" :class="{ 'is-stale': selected.source.stale }">
            {{ selected.source.stale ? '资料版本较旧' : `资料 v${selected.source.version_number}` }}
          </span>
        </div>
        <p class="interaction-author__binding">关联范围：作品项目 {{ selected.source.author_project_id.slice(0, 8) }}… → RP 旅程空间 {{ selected.consumer_project_id.slice(0, 8) }}… · 来源修订 {{ selected.source.revision_id.slice(0, 8) }}…（v{{ selected.source.version_number }}，指纹 {{ selected.source.fingerprint.slice(0, 12) }}…）。旅程与作品分开保存；此处设置不会扩大 RP 角色权限。</p>

        <template v-if="selected.status === 'active'">
          <section class="interaction-author__card" aria-label="旅程显示设置">
            <h4>显示设置</h4>
            <label class="interaction-author__toggle">
              <input v-model="draftActionOptions" type="checkbox" :disabled="busy" @change="saveDraft" />
              <span><strong>显示可选行动</strong><small>只控制回复后是否展示行动建议；不会开启持续续写、联网或多角色能力。</small></span>
            </label>
            <button class="btn btn-sm" type="button" :disabled="busy || draftActionOptions === selected.action_options_enabled" @click="prepareSettings">预览设置变更</button>
          </section>

          <section class="interaction-author__card" aria-label="旅程标题">
            <h4>旅程名称</h4>
            <label class="interaction-author__field">名称
              <input v-model="draftTitle" maxlength="255" :disabled="busy" @input="saveDraft" />
            </label>
            <button class="btn btn-sm" type="button" :disabled="busy || !draftTitle.trim() || draftTitle.trim() === selected.title" @click="prepareRename">预览新名称</button>
          </section>

          <section class="interaction-author__card" aria-label="摘要整理">
            <h4>整理旅程摘要</h4>
            <p>只整理当前选定路径中可以压缩的旧故事段；最近的故事尾段会保留。此操作会调用模型，可能产生费用。</p>
            <button class="btn btn-sm" type="button" :disabled="busy || Boolean(summaryJob)" @click="prepareSummary">查看资料与预算</button>
            <div v-if="summaryPreview" class="interaction-author__preview" aria-label="摘要整理预览">
              <p><strong>本次范围</strong>：{{ summaryPreview.segment_node_count }} 个旧故事节点；保留最近 {{ summaryPreview.protected_tail_node_count }} 个节点。</p>
              <p>估算输入 {{ formatNumber(summaryPreview.estimated_input_tokens) }} tokens；单次输入上限 {{ formatNumber(summaryPreview.input_ceiling_tokens) }}，输出上限 {{ formatNumber(summaryPreview.output_limit_tokens) }}。</p>
              <p>运行根 {{ summaryPreview.root_capability_id }}：最多 {{ summaryPreview.request_limit }} 次模型请求；任务最多 {{ summaryPreview.max_attempts }} 次尝试，恢复策略 {{ summaryPreview.recovery_policy }}。每次 provider timeout {{ timeoutLabel(summaryPreview.provider_timeout_seconds) }}。累计 token 上限：{{ summaryPreview.token_limit ?? '未设置' }}；总 deadline：{{ timeoutLabel(summaryPreview.deadline_seconds) }}。</p>
              <p>模型：{{ summaryPreview.provider || '当前连接' }} · {{ summaryPreview.model || '当前模型' }}。费用类别：可能产生模型费用。</p>
              <p v-if="summaryPreview.source_stale" class="interaction-author__warning">作品已有更新资料版本；本次仍固定使用 RP 旅程引用的来源版本，不读取新版正文。</p>
              <p class="interaction-author__warning">{{ summaryPreview.execution_block_reason }}</p>
              <button v-if="summaryPreview.execution_ready" class="btn btn-primary btn-sm" type="button" :disabled="busy || Boolean(summaryJob)" @click="confirmSummary">单独确认并开始模型整理</button>
              <button v-else class="btn btn-primary btn-sm" type="button" disabled :title="summaryPreview.execution_block_reason">当前不能开始模型整理</button>
              <button class="btn btn-sm" type="button" :disabled="busy" @click="summaryPreview = null; saveDraft()">关闭预览</button>
            </div>
            <div v-if="summaryJob" class="interaction-author__preview" aria-live="polite">
              <p role="status">{{ summaryStatusLabel }}</p>
              <p v-if="summaryJob.task_id">任务回执：{{ summaryJob.task_id }}</p>
              <button v-if="summaryJob.confirmPayload && !summaryJob.task_id" class="btn btn-sm" type="button" :disabled="busy" @click="recoverSummary">核对上次确认结果</button>
              <button v-if="['done', 'completed', 'failed', 'not_submitted'].includes(summaryJob.status)" class="btn btn-sm" type="button" :disabled="busy" @click="clearSummaryJob">关闭状态</button>
            </div>
          </section>

          <section class="interaction-author__card interaction-author__archive" aria-label="归档旅程">
            <h4>归档旅程</h4>
            <p>旅程会从进行中列表移出，但长期历史仍保留，也可以恢复。</p>
            <button class="btn btn-sm" type="button" :disabled="busy" @click="prepareState('archive')">预览归档</button>
          </section>
        </template>

        <section v-else class="interaction-author__card" aria-label="恢复旅程">
          <h4>恢复这段旅程</h4>
          <p>恢复后，旅程回到进行中列表；保留原有历史与来源修订。</p>
          <button class="btn btn-primary btn-sm" type="button" :disabled="busy" @click="prepareState('restore')">预览恢复</button>
        </section>
      </article>
    </div>

    <section v-if="pendingOperation" class="interaction-author__confirm" aria-label="确认旅程变更">
      <h3>核对后确认</h3>
      <p>{{ pendingOperation.preview.effect }}</p>
      <dl v-if="pendingOperation.preview.before || pendingOperation.preview.after">
        <div v-if="pendingOperation.preview.before"><dt>当前</dt><dd>{{ pretty(pendingOperation.preview.before) }}</dd></div>
        <div v-if="pendingOperation.preview.after"><dt>变更后</dt><dd>{{ pretty(pendingOperation.preview.after) }}</dd></div>
      </dl>
      <p v-if="pendingOperation.preview.source_fingerprint" class="interaction-author__binding">来源指纹：{{ pendingOperation.preview.source_fingerprint.slice(0, 12) }}…；消费者空间：{{ pendingOperation.preview.consumer_project_id }}</p>
      <div class="interaction-author__actions">
        <button class="btn btn-primary btn-sm" type="button" :disabled="busy" @click="confirmOperation">{{ busy ? '正在保存…' : '确认这项变更' }}</button>
        <button class="btn btn-sm" type="button" :disabled="busy" @click="pendingOperation = null; saveDraft()">返回编辑</button>
      </div>
    </section>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue"
import { getApi } from "../bridge/index.js"
import { ACCOUNT_INVALIDATED_EVENT, ACCOUNT_MARKER_KEY } from "../../shared/accountStorage.js"

const props = defineProps({ projectId: { type: String, default: null }, active: { type: Boolean, default: true } })
const journeys = ref([])
const selectedId = ref(null)
const statusFilter = ref("active")
const draftTitle = ref("")
const draftActionOptions = ref(true)
const pendingOperation = ref(null)
const summaryPreview = ref(null)
const summaryJob = ref(null)
const loading = ref(false)
const busy = ref(false)
const error = ref("")
const backupError = ref(false)
let generation = 0
let summaryPollTimer = null
let disposed = false

const selected = computed(() => journeys.value.find(item => item.id === selectedId.value) || null)
const api = () => getApi()?.interactions
const summaryStatusLabel = computed(() => {
  const status = summaryJob.value?.status
  if (status === "pending") return "摘要任务已入队，等待处理。"
  if (status === "running") return "摘要正在整理，可以离开后回来查看。"
  if (status === "done" || status === "completed") return "摘要整理已完成。"
  if (status === "failed") return "摘要任务未完成；保留原路径和任务回执，请核对后续状态。"
  if (status === "not_submitted") return "当前没有找到已提交任务；预览没有排队或调用模型。"
  return "确认结果尚待核对。"
})

function storageKey(projectId = props.projectId) {
  const account = localStorage.getItem(ACCOUNT_MARKER_KEY) || "local"
  return `interaction_author_v1:${account}:${projectId || "none"}`
}
function readDraft() {
  try { return JSON.parse(localStorage.getItem(storageKey()) || "{}") } catch { backupError.value = true; return {} }
}
function saveDraft() {
  try {
    const saved = readDraft()
    const drafts = { ...(saved.drafts || {}) }
    if (selectedId.value) drafts[selectedId.value] = {
      ...drafts[selectedId.value],
      title: draftTitle.value,
      actionOptions: draftActionOptions.value,
      pendingOperation: pendingOperation.value,
      summaryPreview: summaryPreview.value,
      summaryJob: summaryJob.value,
    }
    localStorage.setItem(storageKey(), JSON.stringify({
      selectedId: selectedId.value,
      statusFilter: statusFilter.value,
      drafts,
      pendingOperation: pendingOperation.value,
      summaryPreview: summaryPreview.value,
      summaryJob: summaryJob.value,
    }))
    backupError.value = false
  } catch { backupError.value = true }
}
function current(token, projectId) { return !disposed && token === generation && props.projectId === projectId }
function clearPoll() { if (summaryPollTimer) clearTimeout(summaryPollTimer); summaryPollTimer = null }

function applyJourneyDraft(journey, savedDrafts = readDraft().drafts || {}) {
  selectedId.value = journey?.id || null
  const draft = journey ? savedDrafts[journey.id] : null
  draftTitle.value = draft?.title ?? journey?.title ?? ""
  draftActionOptions.value = draft?.actionOptions ?? journey?.action_options_enabled ?? true
  pendingOperation.value = null
  summaryPreview.value = null
}

function selectJourney(journey) {
  if (selectedId.value === journey.id) return
  generation++
  applyJourneyDraft(journey)
  clearPoll()
  const saved = readDraft().drafts?.[journey.id] || {}
  pendingOperation.value = saved.pendingOperation || null
  summaryPreview.value = saved.summaryPreview || null
  summaryJob.value = saved.summaryJob || null
  saveDraft()
  if (summaryJob.value?.confirmPayload && !summaryJob.value.task_id) {
    void recoverSummary()
  } else if (summaryJob.value && ["pending", "running", "checking"].includes(summaryJob.value.status)) {
    scheduleSummaryPoll()
  }
}

async function load() {
  if (!props.projectId || !props.active || !api()?.authorJourneys) return
  const projectId = props.projectId
  const token = ++generation
  const saved = readDraft()
  loading.value = true
  error.value = ""
  journeys.value = []
  selectedId.value = null
  try {
    const result = await api().authorJourneys({ author_project_id: projectId, status: statusFilter.value })
    if (!current(token, projectId)) return
    journeys.value = result.preview?.items || []
    const restored = journeys.value.find(item => item.id === saved.selectedId) || journeys.value[0]
    applyJourneyDraft(restored, saved.drafts || {})
    const restoredId = restored?.id
    const restoredDraft = (saved.drafts || {})[restoredId] || {}
    pendingOperation.value = (restoredDraft.pendingOperation || saved.pendingOperation)?.args?.journey_id === restoredId
      ? (restoredDraft.pendingOperation || saved.pendingOperation)
      : null
    summaryPreview.value = (restoredDraft.summaryPreview || saved.summaryPreview)?.request?.journey_id === restoredId
      ? (restoredDraft.summaryPreview || saved.summaryPreview)
      : null
    summaryJob.value = (restoredDraft.summaryJob || saved.summaryJob)?.confirmPayload?.journey_id === restoredId
      ? (restoredDraft.summaryJob || saved.summaryJob)
      : null
    saveDraft()
    if (summaryJob.value?.confirmPayload) void recoverSummary()
  } catch (err) {
    if (current(token, projectId)) error.value = err.message || "暂时无法读取关联旅程。"
  } finally {
    if (current(token, projectId)) loading.value = false
  }
}

async function prepareOperation(kind, args) {
  if (busy.value || !api()) return
  const projectId = props.projectId
  const token = generation
  busy.value = true
  error.value = ""
  try {
    const prepareMethod = {
      settings: "prepareAuthorJourneySettings",
      rename: "prepareAuthorJourneyTitle",
      archive: "prepareAuthorJourneyArchive",
      restore: "prepareAuthorJourneyRestore",
    }[kind]
    const response = await api()[prepareMethod](args)
    if (!current(token, projectId)) return
    pendingOperation.value = {
      kind,
      args,
      preview: response.preview,
      previewHash: response.preview_hash,
    }
    saveDraft()
  } catch (err) {
    if (current(token, projectId)) error.value = err.message || "无法准备这项变更，请刷新后重试。"
  } finally {
    if (current(token, projectId)) busy.value = false
  }
}

function prepareSettings() {
  if (!selected.value) return
  return prepareOperation("settings", {
    author_project_id: props.projectId,
    journey_id: selected.value.id,
    expected_selection_epoch: selected.value.selection_epoch,
    expected_action_options_enabled: selected.value.action_options_enabled,
    action_options_enabled: draftActionOptions.value,
    expected_preview_hash: null,
    confirmed: false,
  })
}
function prepareRename() {
  if (!selected.value) return
  return prepareOperation("rename", {
    author_project_id: props.projectId,
    journey_id: selected.value.id,
    expected_title: selected.value.title,
    title: draftTitle.value.trim(),
    expected_preview_hash: null,
    confirmed: false,
  })
}
function prepareState(kind) {
  if (!selected.value) return
  return prepareOperation(kind, {
    author_project_id: props.projectId,
    journey_id: selected.value.id,
    expected_status: kind === "archive" ? "active" : "archived",
    expected_preview_hash: null,
    confirmed: false,
  })
}

async function confirmOperation() {
  if (!pendingOperation.value || busy.value) return
  const pending = pendingOperation.value
  const method = {
    settings: "confirmAuthorJourneySettings",
    rename: "confirmAuthorJourneyTitle",
    archive: "confirmAuthorJourneyArchive",
    restore: "confirmAuthorJourneyRestore",
  }[pending.kind]
  const projectId = props.projectId
  const token = generation
  busy.value = true
  error.value = ""
  try {
    await api()[method]({
      ...pending.args,
      expected_preview_hash: pending.previewHash,
      confirmed: true,
    })
    if (!current(token, projectId)) return
    pendingOperation.value = null
    const nextFilter = pending.kind === "archive" ? "archived" : pending.kind === "restore" ? "active" : statusFilter.value
    const filterChanges = nextFilter !== statusFilter.value
    if (filterChanges) statusFilter.value = nextFilter
    saveDraft()
    busy.value = false
    if (!filterChanges) await load()
  } catch (err) {
    if (current(token, projectId)) {
      error.value = err.message || "旅程已变化；草稿仍保留，请重新读取并核对。"
      if (err.status === 409) {
        pendingOperation.value = null
        saveDraft()
        busy.value = false
        await load()
        if (!disposed && props.projectId === projectId) {
          error.value = "旅程已变化；已重新读取当前状态，未保存的设置或名称仍保留。"
        }
        return
      }
      saveDraft()
    }
  } finally {
    if (current(token, projectId)) busy.value = false
  }
}

async function prepareSummary() {
  if (!selected.value || busy.value || !api()) return
  const projectId = props.projectId
  const token = generation
  const args = {
    author_project_id: projectId,
    journey_id: selected.value.id,
    operation_id: crypto.randomUUID(),
    expected_preview_hash: null,
    confirmed: false,
  }
  busy.value = true
  error.value = ""
  try {
    const result = await api().prepareAuthorSummaryRefresh(args)
    if (!current(token, projectId)) return
    summaryPreview.value = { ...result.preview, request: args, preview_hash: result.preview_hash }
    summaryJob.value = null
    saveDraft()
  } catch (err) {
    if (current(token, projectId)) error.value = err.message || "无法准备摘要预算与资料预览。"
  } finally {
    if (current(token, projectId)) busy.value = false
  }
}

async function confirmSummary() {
  if (!summaryPreview.value?.execution_ready || busy.value) return
  const projectId = props.projectId
  const token = generation
  const confirmPayload = {
    ...summaryPreview.value.request,
    expected_preview_hash: summaryPreview.value.preview_hash,
    confirmed: true,
  }
  summaryJob.value = { operationId: confirmPayload.operation_id, confirmPayload, status: "checking" }
  saveDraft()
  busy.value = true
  error.value = ""
  try {
    const response = await api().confirmAuthorSummaryRefresh(confirmPayload)
    if (!current(token, projectId)) return
    summaryJob.value = { ...summaryJob.value, task_id: response.result?.task_id, status: response.result?.status || "pending" }
    saveDraft()
    scheduleSummaryPoll()
  } catch (err) {
    if (current(token, projectId)) {
      error.value = err.message || "确认结果未确认；保留同一操作标识，可核对原回执。"
      if (err.status === 409) {
        summaryJob.value = null
        if (summaryPreview.value) {
          summaryPreview.value = {
            ...summaryPreview.value,
            execution_ready: false,
            execution_block_reason: "确认预览已失效，请重新读取资料与预算。",
          }
        }
      } else {
        summaryJob.value = { ...summaryJob.value, status: "uncertain" }
      }
      saveDraft()
    }
  } finally {
    if (current(token, projectId)) busy.value = false
  }
}

async function recoverSummary() {
  if (!summaryJob.value?.confirmPayload || busy.value || !api()) return
  const projectId = props.projectId
  const token = generation
  const payload = summaryJob.value.confirmPayload
  busy.value = true
  try {
    const result = await api().authorSummaryRefreshResult(payload)
    if (!current(token, projectId)) return
    summaryJob.value = { ...summaryJob.value, task_id: result.task_id || null, status: result.status }
    saveDraft()
    if (["pending", "running"].includes(result.status)) scheduleSummaryPoll()
  } catch (err) {
    if (current(token, projectId)) error.value = err.message || "暂时无法读取原任务回执。"
  } finally {
    if (current(token, projectId)) busy.value = false
  }
}

function scheduleSummaryPoll() {
  clearPoll()
  if (!summaryJob.value?.confirmPayload || !["pending", "running", "checking"].includes(summaryJob.value.status)) return
  summaryPollTimer = setTimeout(async () => {
    await recoverSummary()
  }, 3000)
}
function clearSummaryJob() {
  clearPoll()
  summaryJob.value = null
  summaryPreview.value = null
  saveDraft()
}

function formatNumber(value) { return Number(value || 0).toLocaleString() }
function timeoutLabel(value) { return value == null ? "未设置总时限" : `${formatNumber(value)} 秒` }
function pretty(value) { return JSON.stringify(value, null, 2) }

function accountInvalidated() {
  generation++
  clearPoll()
  journeys.value = []
  selectedId.value = null
  pendingOperation.value = summaryPreview.value = summaryJob.value = null
  draftTitle.value = ""
  draftActionOptions.value = true
}

watch(statusFilter, () => { if (props.active) void load() })
watch(() => props.projectId, () => {
  generation++
  clearPoll()
  journeys.value = []
  selectedId.value = null
  pendingOperation.value = summaryPreview.value = summaryJob.value = null
  draftTitle.value = ""
  draftActionOptions.value = true
  if (props.active) void load()
})
watch(() => props.active, active => { if (active) void load() })

globalThis.addEventListener?.(ACCOUNT_INVALIDATED_EVENT, accountInvalidated)
onBeforeUnmount(() => {
  disposed = true
  generation++
  clearPoll()
  globalThis.removeEventListener?.(ACCOUNT_INVALIDATED_EVENT, accountInvalidated)
})
</script>

<style scoped>
.interaction-author{min-width:0;color:var(--text-primary);font-size:13px;line-height:1.65}.interaction-author__header,.interaction-author__detail-head,.interaction-author__toolbar,.interaction-author__actions{display:flex;align-items:center;justify-content:space-between;gap:12px}.interaction-author__header{padding-bottom:12px;border-bottom:1px solid var(--border-color,var(--border))}.interaction-author h2,.interaction-author h3,.interaction-author h4,.interaction-author p{margin-top:0}.interaction-author h2{font-size:20px;margin-bottom:3px}.interaction-author h3{font-size:18px;margin-bottom:0;overflow-wrap:anywhere}.interaction-author h4{font-size:14px;margin-bottom:8px}.interaction-author__eyebrow{margin-bottom:3px;color:var(--text-secondary);font-size:11px;letter-spacing:.07em}.interaction-author__intro,.interaction-author__binding,.interaction-author__journey span,.interaction-author__journey small,.interaction-author__toggle small{color:var(--text-secondary)}.interaction-author__toolbar{margin:14px 0;justify-content:flex-start}.interaction-author__toolbar label{display:flex;align-items:center;gap:8px}.interaction-author select,.interaction-author input:not([type=checkbox]){box-sizing:border-box;max-width:100%;padding:8px;border:1px solid var(--border-color,var(--border));border-radius:6px;background:var(--bg-primary,var(--bg-base));color:inherit;font:inherit}.interaction-author__layout{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.5fr);gap:14px;align-items:start}.interaction-author__journeys{display:grid;gap:7px;min-width:0}.interaction-author__journey{display:grid;gap:3px;width:100%;min-width:0;text-align:left;padding:10px;border:1px solid var(--border-color,var(--border));border-radius:7px;background:var(--bg-primary,var(--bg-base));color:inherit;font:inherit;cursor:pointer}.interaction-author__journey[aria-current=true]{border-color:var(--accent,var(--primary));box-shadow:inset 3px 0 var(--accent,var(--primary))}.interaction-author__journey strong,.interaction-author__journey span,.interaction-author__journey small{overflow-wrap:anywhere}.interaction-author__journey small{color:#9a6611}.interaction-author__detail{min-width:0}.interaction-author__detail-head{align-items:flex-start;margin-bottom:8px}.interaction-author__source-chip{flex:none;padding:3px 7px;border-radius:99px;background:var(--bg-muted);color:var(--text-secondary);font-size:11px}.interaction-author__source-chip.is-stale{background:#fff2d6;color:#80540b}.interaction-author__binding{font-size:12px;overflow-wrap:anywhere}.interaction-author__card,.interaction-author__confirm{margin:12px 0;padding:12px;border:1px solid var(--border-color,var(--border));border-radius:8px;background:var(--bg-primary,var(--bg-base))}.interaction-author__toggle{display:flex;align-items:flex-start;gap:9px;margin:10px 0}.interaction-author__toggle input{margin-top:5px}.interaction-author__toggle span{display:grid;gap:2px}.interaction-author__field{display:grid;gap:5px;margin:8px 0}.interaction-author__preview{margin-top:12px;padding:10px;border-left:3px solid var(--accent,var(--primary));background:var(--bg-muted);overflow-wrap:anywhere}.interaction-author__preview p{margin-bottom:7px}.interaction-author__warning,.interaction-author__error{color:var(--danger,#9c2d29)}.interaction-author__error{padding:9px 10px;border-radius:6px;background:var(--danger-muted,#fff0ef);overflow-wrap:anywhere}.interaction-author__empty{padding:22px 12px;text-align:center;color:var(--text-secondary);border:1px dashed var(--border-color,var(--border));border-radius:8px}.interaction-author__confirm{position:sticky;bottom:8px;z-index:2;box-shadow:0 6px 26px #0002}.interaction-author__confirm dl{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.interaction-author__confirm dl div{min-width:0;padding:8px;background:var(--bg-muted);overflow-wrap:anywhere}.interaction-author__confirm dt{color:var(--text-secondary);font-size:11px}.interaction-author__confirm dd{margin:2px 0 0;white-space:pre-wrap}.interaction-author__actions{justify-content:flex-start}.interaction-author :is(button,input,select):focus-visible{outline:2px solid var(--accent,var(--primary));outline-offset:3px}.interaction-author :is(button,select){min-height:38px}.interaction-author__journey{min-height:54px}.interaction-author__archive{border-color:#d5b998}
@media(max-width:700px){.interaction-author__layout{grid-template-columns:1fr}.interaction-author__journeys{grid-template-columns:1fr}.interaction-author__header{align-items:flex-start}.interaction-author__header .btn{flex:none}.interaction-author__confirm dl{grid-template-columns:1fr}.interaction-author__source-chip{max-width:42%;white-space:normal;text-align:center}.interaction-author__toggle input{width:20px;height:20px;flex:none}.interaction-author :is(button,select){min-height:44px}}
</style>
