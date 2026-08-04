<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"
import AuthorPreferencesForm from "./components/AuthorPreferencesForm.vue"
import DeepImportFields from "./components/DeepImportFields.vue"
import SourceLabel from "./components/SourceLabel.vue"
import { getApi, getConfirm, getRouter, getToast } from "../../bridge/index.js"
import { useSaveButton } from "../../composables/useSaveButton.js"
import { useLeaveGuard } from "../../composables/useLeaveGuard.js"
import { projectSettingsSession } from "./projectSettingsSession.js"
import {
  authorFormFromEffective,
  buildAuthorPrefsPayload,
  validateAuthorPreferences,
} from "./logic/authorPreferences.js"
import { buildDeepImportPayload, deepImportFormFromSettings } from "./logic/deepImport.js"

const props = defineProps({
  projectId: { type: String, default: null },
  projectTitle: { type: String, default: "" },
  effectiveLLM: { type: Object, default: null },
  effectivePrefs: { type: Object, default: null },
})

const TABS = [
  { key: "deep", label: "深度导入" },
  { key: "author", label: "作者偏好" },
]

function deepImportSettingsSource(llm) {
  const deepImport = llm?.deep_import
  return deepImport?.source === "project" ? deepImport.value || {} : {}
}

const initialTab = TABS.some((item) => item.key === projectSettingsSession.tab)
  ? projectSettingsSession.tab
  : "deep"
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

const dataReady = computed(() => Boolean(effectiveLLM.value && effectivePrefs.value))
const deepImportSource = computed(() => (
  effectiveLLM.value?.deep_import || { source: "system", value: null }
))
const activeModelLabel = computed(() => {
  const label = effectiveLLM.value?.label?.value || "模型"
  const model = effectiveLLM.value?.model?.value || ""
  const connected = Boolean(effectiveLLM.value?.api_key_configured?.value)
  return `${label}${model ? ` · ${model}` : ""}${connected ? "" : " · 未连接"}`
})

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

async function refreshEffective({
  author = true,
  deepImport = true,
} = {}) {
  const api = getApi()
  const [llm, prefs] = await Promise.all([
    api.settings.getEffectiveLLMSettings(props.projectId),
    api.settings.getEffectiveAuthorPrefs(props.projectId),
  ])
  effectiveLLM.value = llm
  effectivePrefs.value = prefs
  if (author) {
    authorForm.value = authorFormFromEffective(prefs)
    authorBaseline.value = JSON.stringify(authorForm.value)
  }
  if (deepImport) {
    deepImportForm.value = deepImportFormFromSettings(deepImportSettingsSource(llm))
    deepImportBaseline.value = JSON.stringify(deepImportForm.value)
  }
}

async function saveDeepImport() {
  const toast = getToast()
  const submittedForm = JSON.stringify(deepImportForm.value)
  const out = buildDeepImportPayload(deepImportForm.value)
  if (!out.ok) return toast(out.error, "warning")
  deepImportButton.saving.value = true
  try {
    await getApi().projects.updateLlmSettings(props.projectId, {
      deep_import: out.value,
    })
    toast("深度导入参数已保存", "success")
    await refreshEffective({
      author: false,
      deepImport: JSON.stringify(deepImportForm.value) === submittedForm,
    })
  } catch (err) {
    toast(err.message || "保存失败", "error")
    deepImportButton.flashError()
  } finally {
    deepImportButton.saving.value = false
  }
}

async function resetDeepImport() {
  if (!getConfirm()("将清除项目深度导入覆盖，恢复默认。继续？")) return
  const toast = getToast()
  try {
    await getApi().settings.resetLLMSettingsField(props.projectId, "deep_import")
    toast("深度导入参数已恢复默认", "success")
    await refreshEffective({ author: false })
  } catch (err) {
    toast(err.message || "重置失败", "error")
  }
}

async function saveAuthorPrefs() {
  const toast = getToast()
  const submittedForm = JSON.stringify(authorForm.value)
  const prefs = buildAuthorPrefsPayload(authorForm.value)
  const validation = validateAuthorPreferences(prefs)
  if (!validation.ok) return toast(validation.message, "warning")
  authorButton.saving.value = true
  try {
    await getApi().settings.updateProjectAuthorPrefs(props.projectId, prefs)
    toast("作者偏好已保存", "success")
    await refreshEffective({
      author: JSON.stringify(authorForm.value) === submittedForm,
      deepImport: false,
    })
  } catch (err) {
    toast(err.message || "保存失败", "error")
    authorButton.flashError()
  } finally {
    authorButton.saving.value = false
  }
}

async function resetAuthorPrefsField(field) {
  const toast = getToast()
  const submittedFieldValue = authorForm.value[field]
  try {
    await getApi().settings.resetProjectAuthorPrefsField(props.projectId, field)
    const prefs = await getApi().settings.getEffectiveAuthorPrefs(props.projectId)
    const refreshedForm = authorFormFromEffective(prefs)
    effectivePrefs.value = prefs

    const nextBaseline = JSON.parse(authorBaseline.value)
    nextBaseline[field] = refreshedForm[field]
    authorBaseline.value = JSON.stringify(nextBaseline)
    if (authorForm.value[field] === submittedFieldValue) {
      authorForm.value = { ...authorForm.value, [field]: refreshedForm[field] }
    }
    toast(`${field} 已恢复到全局默认`, "success")
  } catch (err) {
    toast(err.message || "重置失败", "error")
  }
}

function hasUnsavedChanges() {
  return JSON.stringify(authorForm.value) !== authorBaseline.value
    || JSON.stringify(deepImportForm.value) !== deepImportBaseline.value
}

useLeaveGuard(() => (
  !hasUnsavedChanges()
  || getConfirm()("项目设置有未保存修改，确定放弃并离开吗？")
))

function beforeUnload(event) {
  if (!hasUnsavedChanges()) return
  event.preventDefault()
  event.returnValue = ""
}

onMounted(() => window.addEventListener("beforeunload", beforeUnload))
onBeforeUnmount(() => window.removeEventListener("beforeunload", beforeUnload))
</script>

<template>
  <div v-if="!props.projectId" class="project-settings-view empty-state settings-empty-state">
    <p class="empty-hint">请先进入项目</p>
    <button
      id="project-settings-goto-global"
      class="btn btn-link"
      @click="gotoGlobalSettings"
    >返回账户设置</button>
  </div>

  <div v-else class="project-settings-view">
    <div class="view-header view-header--with-tabs section-header">
      <h2 class="view-header__title">
        项目设置
        <span class="view-header__project">{{ props.projectTitle }}</span>
      </h2>
      <nav class="subnav settings-tab-nav" role="tablist" aria-label="项目设置">
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
    </div>

    <aside class="settings-account-model-notice">
      <span>当前模型：{{ activeModelLabel }}</span>
      <button
        id="project-settings-goto-global"
        class="btn btn-sm btn-link"
        @click="gotoGlobalSettings"
      >到账户设置管理</button>
    </aside>

    <div
      id="project-settings-tab-panel"
      class="settings-tab-content"
      role="tabpanel"
      :aria-labelledby="tabId(tab)"
      :aria-busy="!dataReady || activeTabSaving"
    >
      <template v-if="dataReady">
        <div v-if="tab === 'deep'" class="deep-import-tab">
          <p class="settings-section-hint">
            这些高级参数只影响本项目的深度导入；模型与 Key 由账户设置统一管理。
          </p>
          <p class="deep-import-source-hint">
            深度导入参数
            <SourceLabel
              :source="deepImportSource.source"
              :value="deepImportSource.value"
            />
          </p>
          <DeepImportFields v-model="deepImportForm" />
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
          </div>
        </div>

        <div v-else class="author-prefs-tab" data-mode="project">
          <AuthorPreferencesForm
            v-model="authorForm"
            :source-map="effectivePrefs"
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
            >保存作者偏好</button>
          </div>
        </div>
      </template>
      <template v-else><p role="status">加载中…</p></template>
    </div>
  </div>
</template>
