<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"
import AuthorPreferencesForm from "./components/AuthorPreferencesForm.vue"
import DeepImportFields from "./components/DeepImportFields.vue"
import { getApi, getAppState, getConfirm, getRouter, getToast } from "../../bridge/index.js"
import { useSaveButton } from "../../composables/useSaveButton.js"
import { useLeaveGuard } from "../../composables/useLeaveGuard.js"
import { projectSettingsSession } from "./projectSettingsSession.js"
import {
  authorFormFromEffective,
  buildAuthorPrefsPayload,
  validateAuthorPreferences,
} from "./logic/authorPreferences.js"
import { buildDeepImportPayload, DEEP_IMPORT_GROUPS, deepImportFormFromSettings } from "./logic/deepImport.js"

const props = defineProps({
  projectId: { type: String, default: null },
  projectTitle: { type: String, default: "" },
  effectiveLLM: { type: Object, default: null },
  effectivePrefs: { type: Object, default: null },
  loadError: { type: String, default: null },
})

const TABS = [
  { key: "author", label: "创作偏好" },
  { key: "deep", label: "高级导入" },
]

function deepImportSettingsSource(llm) {
  const deepImport = llm?.deep_import
  return deepImport?.source === "project" ? deepImport.value || {} : {}
}

const initialTab = TABS.some((item) => item.key === projectSettingsSession.tab)
  ? projectSettingsSession.tab
  : "author"
const tab = ref(initialTab)
const tabButtons = ref([])
watch(tab, (value) => {
  projectSettingsSession.tab = value
})

const effectiveLLM = ref(props.effectiveLLM)
const effectivePrefs = ref(props.effectivePrefs)
const authorForm = ref(authorFormFromEffective(props.effectivePrefs))
const deepImportForm = ref(
  deepImportFormFromSettings(deepImportSettingsSource(props.effectiveLLM)),
)
const authorBaseline = ref(JSON.stringify(authorForm.value))
const deepImportBaseline = ref(JSON.stringify(deepImportForm.value))
const deepImportValidationError = ref(null)
const projectLoadError = ref(props.loadError || (
  props.projectId && (!props.effectiveLLM || !props.effectivePrefs)
    ? "项目偏好暂时无法加载。已有设置没有改变。"
    : ""
))
const loadPending = ref(false)
const authorValidationError = ref("")
const authorFeedback = ref(null)
const deepImportFeedback = ref(null)
let disposed = false

function ownsProjectSettings(projectId) {
  const state = getAppState()
  return !disposed
    && props.projectId === projectId
    && state?.currentProjectId === projectId
    && state?.currentView === "project-settings"
}

const dataReady = computed(() => Boolean(effectiveLLM.value && effectivePrefs.value))
const deepImportSource = computed(() => (
  effectiveLLM.value?.deep_import || { source: "system", value: null }
))
const deepImportSourceSummary = computed(() => {
  if (deepImportSource.value.source === "project") {
    const configured = deepImportFormFromSettings(deepImportSource.value.value || {})
    const defaults = deepImportFormFromSettings({})
    const changed = DEEP_IMPORT_GROUPS.reduce((count, group) => count + group.fields.filter((field) => (
      configured[group.id][field.key] !== defaults[group.id][field.key]
    )).length, 0)
    return changed ? `当前作品有 ${changed} 项与默认不同` : "当前作品使用已保存设置"
  }
  if (deepImportSource.value.source === "global") return "跟随账户默认设置"
  return "使用系统默认设置"
})
const activeModelLabel = computed(() => {
  const label = effectiveLLM.value?.label?.value || "模型"
  const model = effectiveLLM.value?.model?.value || ""
  const connected = Boolean(effectiveLLM.value?.api_key_configured?.value)
  return `${label}${model ? ` · ${model}` : ""}${connected ? "" : " · 未连接"}`
})
const authorDirty = computed(() => JSON.stringify(authorForm.value) !== authorBaseline.value)
const deepImportDirty = computed(() => JSON.stringify(deepImportForm.value) !== deepImportBaseline.value)
const authorState = computed(() => {
  if (authorFeedback.value) return authorFeedback.value
  return authorDirty.value
    ? { kind: "pending", message: "有未保存修改" }
    : { kind: "success", message: "已保存" }
})
const deepImportState = computed(() => {
  if (deepImportFeedback.value) return deepImportFeedback.value
  return deepImportDirty.value
    ? { kind: "pending", message: "有未保存修改" }
    : { kind: "success", message: "已保存" }
})

const AUTHOR_FIELD_LABELS = {
  daily_goal: "日更目标",
  editor_font: "编辑器字体",
  default_focus_mode: "默认专注模式",
}

const deepImportButton = useSaveButton()
const authorButton = useSaveButton()
const activeTabSaving = computed(() => (
  tab.value === "deep"
    ? deepImportButton.saving.value
    : authorButton.saving.value
))

function tabId(key) {
  return `project-settings-tab-${key}`
}

function focusTab(key) {
  void nextTick(() => {
    tabButtons.value
      .find((button) => button?.dataset?.tab === key)
      ?.focus()
  })
}

function onTabKeydown(event, key) {
  const currentIndex = TABS.findIndex((item) => item.key === key)
  if (currentIndex < 0) return
  let nextIndex = currentIndex
  if (["ArrowLeft", "ArrowUp"].includes(event.key)) {
    nextIndex = (currentIndex - 1 + TABS.length) % TABS.length
  } else if (["ArrowRight", "ArrowDown"].includes(event.key)) {
    nextIndex = (currentIndex + 1) % TABS.length
  } else if (event.key === "Home") {
    nextIndex = 0
  } else if (event.key === "End") {
    nextIndex = TABS.length - 1
  } else {
    return
  }
  event.preventDefault()
  const nextKey = TABS[nextIndex]?.key
  if (!nextKey) return
  tab.value = nextKey
  focusTab(nextKey)
}

function gotoGlobalSettings() {
  getRouter().navigate("settings")
}

function gotoWriting() {
  getRouter().navigate("writing")
}

async function refreshEffective({
  author = true,
  deepImport = true,
} = {}, projectId = props.projectId) {
  const api = getApi()
  const [llm, prefs] = await Promise.all([
    deepImport ? api.settings.getEffectiveLLMSettings(projectId) : null,
    author ? api.settings.getEffectiveAuthorPrefs(projectId) : null,
  ])
  if (!ownsProjectSettings(projectId)) return false
  if (author) {
    effectivePrefs.value = prefs
    authorForm.value = authorFormFromEffective(prefs)
    authorBaseline.value = JSON.stringify(authorForm.value)
  }
  if (deepImport) {
    effectiveLLM.value = llm
    deepImportForm.value = deepImportFormFromSettings(deepImportSettingsSource(llm))
    deepImportBaseline.value = JSON.stringify(deepImportForm.value)
  }
  return true
}

async function retryProjectSettings() {
  const projectId = props.projectId
  loadPending.value = true
  projectLoadError.value = ""
  try {
    const loaded = await refreshEffective({}, projectId)
    if (loaded) projectLoadError.value = ""
  } catch {
    if (ownsProjectSettings(projectId)) {
      projectLoadError.value = "项目偏好暂时无法加载。已有设置没有改变。"
    }
  } finally {
    loadPending.value = false
  }
}

async function reconcileAfterMutation(options, projectId) {
  try {
    return await refreshEffective(options, projectId)
  } catch (err) {
    if (ownsProjectSettings(projectId)) {
      getToast()(`已保存，但重新读取最新设置失败：${err.message || "未知错误"}`, "warning")
    }
    return false
  }
}

async function saveDeepImport() {
  const projectId = props.projectId
  const toast = getToast()
  const submittedForm = JSON.stringify(deepImportForm.value)
  const out = buildDeepImportPayload(deepImportForm.value)
  if (!out.ok) {
    deepImportValidationError.value = out
    deepImportFeedback.value = { kind: "error", message: "请修正标出的参数后再保存" }
    return toast(out.error, "warning")
  }
  deepImportValidationError.value = null
  deepImportButton.saving.value = true
  deepImportFeedback.value = { kind: "pending", message: "正在保存…" }
  try {
    await getApi().projects.updateLlmSettings(projectId, {
      deep_import: out.value,
    })
    if (!ownsProjectSettings(projectId)) return
    const unchanged = JSON.stringify(deepImportForm.value) === submittedForm
    if (unchanged) deepImportBaseline.value = submittedForm
    deepImportFeedback.value = { kind: "success", message: "高级导入设置已保存" }
    toast("深度导入参数已保存", "success")
    const reconciled = await reconcileAfterMutation({
      author: false,
      deepImport: unchanged,
    }, projectId)
    if (!reconciled && ownsProjectSettings(projectId)) {
      deepImportFeedback.value = { kind: "warning", message: "已保存；暂时无法重新读取最新设置" }
    }
  } catch (err) {
    if (!ownsProjectSettings(projectId)) return
    deepImportFeedback.value = { kind: "error", message: err.message || "保存失败，请稍后重试。" }
    toast(deepImportFeedback.value.message, "error")
    deepImportButton.flashError()
  } finally {
    deepImportButton.saving.value = false
  }
}

async function resetDeepImport() {
  if (!getConfirm()("将清除项目深度导入覆盖，恢复默认。继续？")) return
  const projectId = props.projectId
  const toast = getToast()
  try {
    await getApi().settings.resetLLMSettingsField(projectId, "deep_import")
    if (!ownsProjectSettings(projectId)) return
    toast("深度导入参数已恢复默认", "success")
    deepImportFeedback.value = { kind: "success", message: "已恢复默认设置" }
    const reconciled = await reconcileAfterMutation({ author: false }, projectId)
    if (!reconciled && ownsProjectSettings(projectId)) {
      deepImportFeedback.value = { kind: "warning", message: "已恢复默认；暂时无法重新读取" }
    }
  } catch (err) {
    if (!ownsProjectSettings(projectId)) return
    deepImportFeedback.value = { kind: "error", message: err.message || "恢复默认失败，请稍后重试。" }
    toast(deepImportFeedback.value.message, "error")
  }
}

async function saveAuthorPrefs() {
  const projectId = props.projectId
  const toast = getToast()
  const submittedForm = JSON.stringify(authorForm.value)
  const prefs = buildAuthorPrefsPayload(authorForm.value)
  const validation = validateAuthorPreferences(prefs)
  if (!validation.ok) {
    authorValidationError.value = validation.message
    authorFeedback.value = { kind: "error", message: "请修正日更目标后再保存" }
    toast(validation.message, "warning")
    void nextTick(() => document.getElementById("author-daily-goal")?.focus())
    return
  }
  authorButton.saving.value = true
  authorValidationError.value = ""
  authorFeedback.value = { kind: "pending", message: "正在保存…" }
  try {
    await getApi().settings.updateProjectAuthorPrefs(projectId, prefs)
    if (!ownsProjectSettings(projectId)) return
    const unchanged = JSON.stringify(authorForm.value) === submittedForm
    if (unchanged) authorBaseline.value = submittedForm
    authorFeedback.value = { kind: "success", message: "当前作品的创作偏好已保存" }
    toast("作者偏好已保存", "success")
    const reconciled = await reconcileAfterMutation({
      author: unchanged,
      deepImport: false,
    }, projectId)
    if (!reconciled && ownsProjectSettings(projectId)) {
      authorFeedback.value = { kind: "warning", message: "已保存；暂时无法重新读取最新设置" }
    }
  } catch (err) {
    if (!ownsProjectSettings(projectId)) return
    authorFeedback.value = { kind: "error", message: err.message || "保存失败，请稍后重试。" }
    toast(authorFeedback.value.message, "error")
    authorButton.flashError()
  } finally {
    authorButton.saving.value = false
  }
}

async function resetAuthorPrefsField(field) {
  const projectId = props.projectId
  const toast = getToast()
  const submittedFieldValue = authorForm.value[field]
  try {
    await getApi().settings.resetProjectAuthorPrefsField(projectId, field)
    if (!ownsProjectSettings(projectId)) return
    const prefs = await getApi().settings.getEffectiveAuthorPrefs(projectId)
    if (!ownsProjectSettings(projectId)) return
    const refreshedForm = authorFormFromEffective(prefs)
    effectivePrefs.value = prefs

    const nextBaseline = JSON.parse(authorBaseline.value)
    nextBaseline[field] = refreshedForm[field]
    authorBaseline.value = JSON.stringify(nextBaseline)
    if (authorForm.value[field] === submittedFieldValue) {
      authorForm.value = { ...authorForm.value, [field]: refreshedForm[field] }
    }
    const fieldLabel = AUTHOR_FIELD_LABELS[field] || "这个选项"
    authorFeedback.value = { kind: "success", message: `${fieldLabel}已恢复到全局默认` }
    toast(`${fieldLabel}已恢复到全局默认`, "success")
  } catch (err) {
    if (!ownsProjectSettings(projectId)) return
    authorFeedback.value = { kind: "error", message: err.message || "恢复默认失败，请稍后重试。" }
    toast(authorFeedback.value.message, "error")
  }
}

function hasUnsavedChanges() {
  return JSON.stringify(authorForm.value) !== authorBaseline.value
    || JSON.stringify(deepImportForm.value) !== deepImportBaseline.value
}

watch(authorForm, () => {
  authorValidationError.value = ""
  authorFeedback.value = null
}, { deep: true })

watch(deepImportForm, () => {
  deepImportValidationError.value = null
  deepImportFeedback.value = null
}, { deep: true })

useLeaveGuard(() => (
  !hasUnsavedChanges()
  || getConfirm()("项目偏好有未保存修改，确定放弃并离开吗？")
))

function beforeUnload(event) {
  if (!hasUnsavedChanges()) return
  event.preventDefault()
  event.returnValue = ""
}

onMounted(() => window.addEventListener("beforeunload", beforeUnload))
onBeforeUnmount(() => {
  disposed = true
  window.removeEventListener("beforeunload", beforeUnload)
})
</script>

<template>
  <div v-if="!props.projectId" class="project-settings-view empty-state settings-empty-state">
    <p class="empty-hint">请先进入项目</p>
    <button
      id="project-settings-empty-goto-account"
      class="btn btn-link"
      @click="gotoGlobalSettings"
    >返回账户与模型连接</button>
  </div>

  <div v-else class="project-settings-view">
    <nav class="settings-tab-nav" role="tablist" aria-label="当前作品设置">
      <button
        v-for="item in TABS"
        :key="item.key"
        class="tab-btn"
        :class="{ active: tab === item.key }"
        :data-tab="item.key"
        :id="tabId(item.key)"
        ref="tabButtons"
        role="tab"
        :aria-selected="tab === item.key"
        aria-controls="project-settings-tab-panel"
        :tabindex="tab === item.key ? 0 : -1"
        @click="tab = item.key"
        @keydown="onTabKeydown($event, item.key)"
      >{{ item.label }}</button>
    </nav>

    <aside v-if="dataReady" class="settings-account-model-notice">
      <span>AI 文本服务：{{ activeModelLabel }}</span>
      <button
        id="project-settings-goto-global"
        class="btn btn-sm btn-link"
        @click="gotoGlobalSettings"
      >管理连接</button>
    </aside>

    <div
      id="project-settings-tab-panel"
      class="settings-tab-content"
      role="tabpanel"
      :aria-labelledby="tabId(tab)"
      :aria-busy="loadPending || activeTabSaving"
    >
      <div v-if="projectLoadError" class="error-card settings-load-error" role="alert">
        <div>
          <strong>当前作品的设置暂时无法加载</strong>
          <p>已有偏好和导入设置没有改变，可以重新加载。</p>
        </div>
        <button class="btn btn-primary" type="button" :disabled="loadPending" @click="retryProjectSettings">
          {{ loadPending ? "正在加载…" : "重新加载" }}
        </button>
      </div>
      <template v-else-if="dataReady">
        <section v-if="tab === 'deep'" class="settings-section deep-import-tab">
          <div class="settings-section-heading">
            <div>
              <h2>高级导入设置</h2>
              <p>只在导入结果不理想或模型响应不稳定时调整。</p>
            </div>
            <button class="btn btn-sm btn-link" @click="gotoWriting">返回写作工作台</button>
          </div>
          <p class="settings-section-hint">
            这些参数只影响当前作品的深度导入；模型与密钥仍由账户设置统一管理。
          </p>
          <p class="deep-import-source-hint">
            {{ deepImportSourceSummary }}，通常无需调整。
          </p>
          <DeepImportFields v-model="deepImportForm" :validation-error="deepImportValidationError" />
          <div class="settings-actions">
            <button
              id="deep-import-tab-save"
              class="btn btn-primary"
              :class="{
                'settings-btn-loading': deepImportButton.saving.value,
                'settings-btn-error': deepImportButton.error.value,
              }"
              :disabled="deepImportButton.saving.value"
              :aria-busy="deepImportButton.saving.value"
              @click="saveDeepImport"
            >保存深度导入参数</button>
            <button
              v-if="deepImportSource.source === 'project'"
              id="deep-import-tab-reset-all"
              class="btn btn-link"
              @click="resetDeepImport"
            >恢复默认</button>
            <p class="settings-save-state" :class="`is-${deepImportState.kind}`" role="status">{{ deepImportState.message }}</p>
          </div>
        </section>

        <section v-else class="settings-section author-prefs-tab" data-mode="project">
          <div class="settings-section-heading">
            <div>
              <h2>当前作品的创作偏好</h2>
              <p>这里只覆盖当前作品；恢复后继续跟随账户默认值。</p>
            </div>
          </div>
          <AuthorPreferencesForm
            v-model="authorForm"
            :source-map="effectivePrefs"
            :errors="{ daily_goal: authorValidationError }"
            @reset-field="resetAuthorPrefsField"
          />
          <div class="settings-actions">
            <button
              id="author-prefs-tab-save"
              class="btn btn-primary"
              :class="{
                'settings-btn-loading': authorButton.saving.value,
                'settings-btn-error': authorButton.error.value,
              }"
              :disabled="authorButton.saving.value"
              :aria-busy="authorButton.saving.value"
              @click="saveAuthorPrefs"
            >保存创作偏好</button>
            <p class="settings-save-state" :class="`is-${authorState.kind}`" role="status">{{ authorState.message }}</p>
          </div>
        </section>
      </template>
      <p v-else role="status">正在加载当前作品的设置…</p>
    </div>
  </div>
</template>
