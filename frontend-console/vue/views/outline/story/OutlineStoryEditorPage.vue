<template>
  <main class="story-outline-editor-page" :aria-busy="saving ? 'true' : undefined">
    <div v-if="!projectId" class="empty-state"><p>请先选择项目。</p></div>
    <div v-else-if="loadError" class="empty-state" role="alert">
      <div class="empty-icon">!</div>
      <p>故事总览加载失败</p>
      <p class="outline-empty-detail">{{ loadError }}</p>
      <button type="button" class="btn btn-sm" :disabled="reloading" @click="reloadPage">{{ reloading ? '重新加载中…' : '重新加载' }}</button>
    </div>
    <template v-else>
      <header class="story-outline-editor-page__header">
        <button type="button" class="btn btn-sm btn-ghost" data-action="close-story-outline-editor" @click="returnToOverview">← 返回故事总览</button>
        <div>
          <span class="story-outline-primary__eyebrow">{{ hasBaseRevision ? `基于当前版本 v${baseVersionNumber}` : '创建第一版' }}</span>
          <h2>{{ hasBaseRevision ? '编辑故事总览' : '手工创建故事总览' }}</h2>
          <p>保存会创建新版本，当前和过往内容都会保留。</p>
        </div>
        <p class="story-outline-editor-page__save-state" role="status" aria-live="polite">{{ saveState }}</p>
      </header>

      <aside v-if="restoredDraft" class="story-outline-editor-notice" :class="{ 'story-outline-editor-notice--warning': staleDraft }" role="status">
        <div>
          <strong>{{ staleDraft ? '已恢复较早版本的本地草稿' : '已恢复本地草稿' }}</strong>
          <p>{{ staleDraft ? '当前故事总览已更新。你的草稿没有丢失；保存前请核对差异，新版本会以当前内容为基准。' : '上次未完成的内容已自动带回，可以继续编辑。' }}</p>
        </div>
      </aside>

      <aside v-if="conflict" class="story-outline-editor-notice story-outline-editor-notice--warning" role="alert">
        <div>
          <strong>保存前，当前版本被其他会话更新了</strong>
          <p>{{ storageError
            ? "当前修改仍在此页面，但本地暂存不可用。请勿离开或刷新；先同步最新版本基准，再核对并重新保存。"
            : "本地草稿仍在。先同步最新版本基准，再核对并重新保存。" }}</p>
        </div>
        <button type="button" class="btn btn-sm" :disabled="rebasing" @click="rebaseDraft">{{ rebasing ? '同步中…' : '同步最新版本' }}</button>
      </aside>

      <p v-if="storageError" class="form-error" role="alert">{{ storageError }}</p>

      <form class="story-outline-editor-page__form" @submit.prevent="save">
        <StoryOutlineEditorFields :model-value="content" prefix="story-outline-manual" />
        <p v-if="saveError" id="story-outline-manual-error" ref="errorSummary" class="form-error" role="alert" tabindex="-1">{{ saveError }}</p>
        <footer class="story-outline-editor-page__actions">
          <span class="form-hint">{{ storageError
            ? "本地暂存不可用，离开或刷新会丢失未保存修改"
            : dirty ? "未发布修改已在本机暂存" : "修改后会自动暂存到本机" }}</span>
          <div>
            <button v-if="dirty" type="button" class="btn btn-sm btn-ghost" data-action="discard-story-outline-draft" :disabled="saving" @click="discardDraft">放弃本地草稿</button>
            <button type="submit" class="btn btn-sm btn-primary" data-action="save-story-outline-revision" :disabled="saving || conflict || !dirty">{{ saving ? '保存中…' : '保存为新版本' }}</button>
          </div>
        </footer>
      </form>
    </template>
  </main>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue"
import { getApi, getAppState, getConfirm, getRouter, getToast } from "../../../bridge/index.js"
import { useLeaveGuard } from "../../../composables/useLeaveGuard.js"
import StoryOutlineEditorFields from "./StoryOutlineEditorFields.vue"
import {
  editableStoryOutlineContent,
  idempotencyKey,
  validateStoryOutlineContent,
} from "./storyOutlineData.js"

const props = defineProps({
  projectId: { type: String, default: null },
  current: { type: Object, default: null },
  loadError: { type: String, default: null },
})

const api = getApi()
const router = getRouter()
const toast = getToast()
const confirm = getConfirm()
const currentRevision = computed(() => props.current?.revision || null)
const baseRevisionId = ref(props.current?.current_revision_id || null)
const baseVersionNumber = ref(currentRevision.value?.version_number || null)
const hasBaseRevision = computed(() => Boolean(baseRevisionId.value))
const baselineFingerprint = ref(JSON.stringify(editableStoryOutlineContent(currentRevision.value || {})))
const draftKey = `story-outline-editor-draft:${encodeURIComponent(props.projectId || "none")}`
const savedDraft = readDraft()
const content = reactive(editableStoryOutlineContent(savedDraft?.content || currentRevision.value || {}))
const restoredDraft = ref(Boolean(savedDraft))
const staleDraft = ref(Boolean(savedDraft && savedDraft.base_revision_id !== baseRevisionId.value))
const draftSavedAt = ref(savedDraft?.saved_at || null)
const storageError = ref("")
const saveError = ref("")
const saving = ref(false)
const reloading = ref(false)
const rebasing = ref(false)
const conflict = ref(false)
const allowLeave = ref(false)
const errorSummary = ref(null)
let operationKey = null
let lastAttemptFingerprint = null
let draftTimer = null

const fingerprint = computed(() => JSON.stringify(content))
const dirty = computed(() => fingerprint.value !== baselineFingerprint.value)
const saveState = computed(() => {
  if (saving.value) return "正在保存新版本…"
  if (storageError.value) return "本地暂存不可用"
  if (!dirty.value) return "当前内容未修改"
  if (!draftSavedAt.value) return "有未发布修改"
  const date = new Date(draftSavedAt.value)
  return Number.isNaN(date.getTime()) ? "草稿已保存在本机" : `草稿已保存在本机 · ${date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}`
})

watch(content, () => {
  if (!conflict.value) saveError.value = ""
  if (dirty.value) scheduleDraft()
  else clearStoredDraft()
}, { deep: true })

useLeaveGuard(() => {
  if (allowLeave.value || !dirty.value) return true
  if (saving.value) {
    toast("正在保存故事总览，请稍候", "info")
    return false
  }
  const backupComplete = persistDraft()
  return confirm(
    backupComplete
      ? "本地草稿已保留。确定离开故事总览编辑页吗？"
      : "当前修改尚未保存，浏览器也无法写入本地备份。离开后这些修改会丢失，仍要离开吗？",
  )
})

function readDraft() {
  if (!props.projectId) return null
  try {
    const value = JSON.parse(localStorage.getItem(draftKey) || "null")
    if (!value || value.project_id !== props.projectId || !value.content || typeof value.content !== "object") return null
    return value
  } catch {
    try { localStorage.removeItem(draftKey) } catch { /* noop */ }
    return null
  }
}

function persistDraft() {
  clearTimeout(draftTimer)
  draftTimer = null
  if (!props.projectId || !dirty.value) return !dirty.value
  try {
    const savedAt = new Date().toISOString()
    localStorage.setItem(draftKey, JSON.stringify({
      project_id: props.projectId,
      base_revision_id: baseRevisionId.value,
      saved_at: savedAt,
      content: editableStoryOutlineContent(content),
    }))
    draftSavedAt.value = savedAt
    storageError.value = ""
    return true
  } catch {
    storageError.value = "浏览器无法暂存这份草稿。请尽快保存为新版本，离开或刷新可能丢失修改。"
    return false
  }
}

function clearStoredDraft() {
  clearTimeout(draftTimer)
  draftTimer = null
  try { localStorage.removeItem(draftKey) } catch { /* noop */ }
  draftSavedAt.value = null
  storageError.value = ""
}

function scheduleDraft() {
  clearTimeout(draftTimer)
  draftTimer = setTimeout(persistDraft, 250)
}

async function focusSaveError() {
  await nextTick()
  errorSummary.value?.focus()
}

async function returnToOverview() {
  await router?.replace("outline", "story-outline")
}

async function reloadPage() {
  if (reloading.value) return
  reloading.value = true
  try { await router?.refresh() } finally { reloading.value = false }
}

async function save() {
  if (saving.value || conflict.value || !dirty.value) return false
  if (getAppState()?.currentProjectId !== props.projectId) {
    saveError.value = "项目已切换，请回到原项目后继续处理这份草稿。"
    await focusSaveError()
    return false
  }

  let validated
  try {
    validated = validateStoryOutlineContent(editableStoryOutlineContent(content))
  } catch (err) {
    saveError.value = err.message || "请补全必填内容后再保存。"
    await focusSaveError()
    return false
  }

  const attemptFingerprint = JSON.stringify({ base_revision_id: baseRevisionId.value, content: validated })
  try {
    if (!operationKey || lastAttemptFingerprint !== attemptFingerprint) operationKey = idempotencyKey()
    lastAttemptFingerprint = attemptFingerprint
  } catch (err) {
    saveError.value = err.message || "当前浏览器无法安全保存，请更换浏览器后重试。"
    await focusSaveError()
    return false
  }

  persistDraft()
  saving.value = true
  saveError.value = ""
  conflict.value = false
  try {
    const response = await api.outline.createStoryOutlineRevision(props.projectId, {
      ...validated,
      base_revision_id: baseRevisionId.value,
      idempotency_key: operationKey,
      source: "manual",
      provenance: { actor: "author", note: "前端手工保存" },
    })
    clearStoredDraft()
    baselineFingerprint.value = JSON.stringify(validated)
    allowLeave.value = true
    if (getAppState()?.currentProjectId !== props.projectId) return true
    toast(`故事总览已保存为新版本 v${response?.version_number || ""}`, "success")
    await router?.replace("outline", "story-outline")
    return true
  } catch (err) {
    const backupComplete = persistDraft()
    if (err?.status === 409) {
      conflict.value = true
      saveError.value = backupComplete
        ? "当前版本刚刚发生变化，本地草稿已保留。请先同步最新版本。"
        : "当前版本刚刚发生变化，当前修改仍在此页面，但本地暂存不可用。请勿离开或刷新。"
    } else {
      saveError.value = err.message || "保存失败，请稍后重试。"
    }
    await focusSaveError()
    return false
  } finally {
    saving.value = false
  }
}

async function rebaseDraft() {
  if (rebasing.value) return false
  rebasing.value = true
  try {
    const latest = await api.outline.getStoryOutline(props.projectId)
    if (getAppState()?.currentProjectId !== props.projectId) return false
    baseRevisionId.value = latest?.current_revision_id || null
    baseVersionNumber.value = latest?.revision?.version_number || null
    conflict.value = false
    saveError.value = ""
    staleDraft.value = true
    operationKey = null
    lastAttemptFingerprint = null
    const backupComplete = persistDraft()
    toast(
      backupComplete
        ? "已同步最新版本，本地草稿保持不变"
        : "已同步最新版本；当前修改仍在页面，但本地暂存不可用",
      backupComplete ? "success" : "warning",
    )
    return true
  } catch (err) {
    saveError.value = err.message || "同步最新版本失败，请稍后重试。"
    await focusSaveError()
    return false
  } finally {
    rebasing.value = false
  }
}

async function discardDraft() {
  if (dirty.value && !confirm("确定放弃这份本地草稿吗？未保存为版本的修改将无法恢复。")) return false
  clearStoredDraft()
  allowLeave.value = true
  await router?.replace("outline", "story-outline")
  return true
}

function beforeUnload(event) {
  if (!dirty.value || allowLeave.value) return
  persistDraft()
  event.preventDefault()
  event.returnValue = ""
}

onMounted(() => window.addEventListener("beforeunload", beforeUnload))
onBeforeUnmount(() => {
  clearTimeout(draftTimer)
  window.removeEventListener("beforeunload", beforeUnload)
})
</script>
