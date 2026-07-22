<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"
import LlmFormFields from "./components/LlmFormFields.vue"
import AuthorPreferencesForm from "./components/AuthorPreferencesForm.vue"
import DeepImportFields from "./components/DeepImportFields.vue"
import SourceLabel from "./components/SourceLabel.vue"
import { getApi, getConfirm, getRouter, getToast } from "../../bridge/index.js"
import { useSaveButton } from "../../composables/useSaveButton.js"
import { useLeaveGuard } from "../../composables/useLeaveGuard.js"
import { projectSettingsSession } from "./projectSettingsSession.js"
import {
  buildLlmPayload,
  llmFormFromEffective,
  validateLLMPayload,
} from "./logic/llmForm.js"
import {
  authorFormFromEffective,
  buildAuthorPrefsPayload,
  validateAuthorPreferences,
} from "./logic/authorPreferences.js"
import { buildDeepImportPayload, deepImportFormFromSettings } from "./logic/deepImport.js"

/**
 * 项目设置页 — #/workbench/<pid>/project-settings 入口。
 * 编排三个 Tab：主配置、深度导入、作者偏好。
 * 数据由 island 的 load() 预取传入；保存/重置后本地刷新 effective 数据
 * （vanilla 走 router.refresh() 全量重渲染，这里等价为局部响应式刷新，
 *  Tab 与未保存输入不再丢失——行为差异属于刻意改进）。
 */
const props = defineProps({
  projectId: { type: String, default: null },
  projectTitle: { type: String, default: "" },
  effectiveLLM: { type: Object, default: null },
  effectivePrefs: { type: Object, default: null },
  templates: { type: Array, default: () => [] },
})

const TABS = [
  { key: "main", label: "主配置" },
  { key: "deep", label: "深度导入" },
  { key: "author", label: "作者偏好" },
]

// 会话级保留所选 Tab（vanilla renderer 单例 _tab 语义）：路由往返后恢复
const tab = ref(projectSettingsSession.tab)
watch(tab, (value) => {
  projectSettingsSession.tab = value
})

function deepImportSettingsSource(llm) {
  const deepImport = llm?.deep_import
  return deepImport?.source === "project" ? deepImport.value || {} : {}
}

const effectiveLLM = ref(props.effectiveLLM)
const effectivePrefs = ref(props.effectivePrefs)
const llmForm = ref(llmFormFromEffective(props.effectiveLLM))
const authorForm = ref(authorFormFromEffective(props.effectivePrefs))
const deepImportForm = ref(deepImportFormFromSettings(deepImportSettingsSource(props.effectiveLLM)))
const llmBaseline = ref(JSON.stringify(llmForm.value))
const authorBaseline = ref(JSON.stringify(authorForm.value))
const deepImportBaseline = ref(JSON.stringify(deepImportForm.value))
// 刷新 effective 后重挂载 LLM 表单，复位其内部状态（Key 可见性、供应商联动标记）
const llmFormVersion = ref(0)

const dataReady = computed(() => Boolean(effectiveLLM.value && effectivePrefs.value))
const configuredProviders = computed(() => effectiveLLM.value?.api_key_configured_providers?.value || [])
const apiKeyConfigured = computed(() => Boolean(effectiveLLM.value?.api_key_configured?.value))
const deepImportSource = computed(() => effectiveLLM.value?.deep_import || { source: "system", value: null })

const llmButton = useSaveButton()
const deepImportButton = useSaveButton()
const authorButton = useSaveButton()

function gotoGlobalSettings() {
  getRouter().navigate("settings")
}

async function refreshEffective({
  llmForm: refreshLlmForm = true,
  authorForm: refreshAuthorForm = true,
  deepImportForm: refreshDeepImportForm = true,
} = {}) {
  const api = getApi()
  const [llm, prefs] = await Promise.all([
    api.settings.getEffectiveLLMSettings(props.projectId),
    api.settings.getEffectiveAuthorPrefs(props.projectId),
  ])
  effectiveLLM.value = llm
  effectivePrefs.value = prefs
  if (refreshLlmForm) {
    llmForm.value = llmFormFromEffective(llm)
    llmBaseline.value = JSON.stringify(llmForm.value)
    llmFormVersion.value += 1
  }
  if (refreshAuthorForm) {
    authorForm.value = authorFormFromEffective(prefs)
    authorBaseline.value = JSON.stringify(authorForm.value)
  }
  if (refreshDeepImportForm) {
    deepImportForm.value = deepImportFormFromSettings(deepImportSettingsSource(llm))
    deepImportBaseline.value = JSON.stringify(deepImportForm.value)
  }
}

async function saveLLM() {
  const toast = getToast()
  const submittedForm = JSON.stringify(llmForm.value)
  const { payload, api_key: apiKey, clear_api_key: clearApiKey } = buildLlmPayload(llmForm.value)
  const validation = validateLLMPayload(payload)
  if (!validation.ok) return toast(validation.message, "warning")
  llmButton.saving.value = true
  try {
    await getApi().projects.updateLlmSettings(props.projectId, {
      ...payload,
      api_key: apiKey,
      clear_api_key: clearApiKey,
    })
    // D17: Key 未配置时给提示但仍报告其他字段已保存
    const configured = new Set(configuredProviders.value)
    const willHaveKey = Boolean(apiKey) || (!clearApiKey && configured.has(payload.provider_id))
    if (willHaveKey) {
      toast("LLM 配置已保存", "success")
    } else {
      toast("Key 未配置，已保存其他字段", "warning")
    }
    await refreshEffective({
      llmForm: JSON.stringify(llmForm.value) === submittedForm,
      authorForm: false,
      deepImportForm: false,
    })
  } catch (err) {
    toast(err.message || "保存失败", "error")
    llmButton.flashError()
  } finally {
    llmButton.saving.value = false
  }
}

async function resetAllLLMFields() {
  const confirm = getConfirm()
  if (!confirm("将清除项目所有 LLM 覆盖，回退到全局默认。继续？")) return
  const toast = getToast()
  try {
    await getApi().projects.updateLlmSettings(props.projectId, {
      provider_id: null,
      label: null,
      base_url: null,
      model: null,
      timeout: null,
      max_tokens: null,
      temperature: null,
      top_p: null,
      extra: {},
      deep_import: {},
      api_key: "",
      clear_api_key: true,
      clear_all_api_keys: true,
    })
    toast("已恢复所有 LLM 字段到全局默认", "success")
    await refreshEffective({ authorForm: false })
  } catch (err) {
    toast(err.message || "重置失败", "error")
  }
}

async function saveDeepImport() {
  const toast = getToast()
  const submittedForm = JSON.stringify(deepImportForm.value)
  const out = buildDeepImportPayload(deepImportForm.value)
  if (!out.ok) return toast(out.error, "warning")
  deepImportButton.saving.value = true
  try {
    const api = getApi()
    const effective = await api.settings.getEffectiveLLMSettings(props.projectId)
    const pickProject = (field) => (effective[field]?.source === "project" ? effective[field].value : null)
    await api.projects.updateLlmSettings(props.projectId, {
      provider_id: pickProject("provider_id"),
      label: pickProject("label"),
      base_url: pickProject("base_url"),
      model: pickProject("model"),
      timeout: pickProject("timeout"),
      max_tokens: pickProject("max_tokens"),
      temperature: pickProject("temperature"),
      top_p: pickProject("top_p"),
      extra: pickProject("extra") || {},
      deep_import: out.value,
    })
    toast("深度导入参数已保存", "success")
    await refreshEffective({
      llmForm: false,
      authorForm: false,
      deepImportForm: JSON.stringify(deepImportForm.value) === submittedForm,
    })
  } catch (err) {
    toast(err.message || "保存失败", "error")
    deepImportButton.flashError()
  } finally {
    deepImportButton.saving.value = false
  }
}

async function resetDeepImport() {
  const confirm = getConfirm()
  if (!confirm("将清除项目深度导入覆盖，整体回退。继续？")) return
  const toast = getToast()
  try {
    await getApi().settings.resetLLMSettingsField(props.projectId, "deep_import")
    toast("deep_import 已恢复到全局默认", "success")
    await refreshEffective({ llmForm: false, authorForm: false })
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
      llmForm: false,
      authorForm: JSON.stringify(authorForm.value) === submittedForm,
      deepImportForm: false,
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

    // 服务器基线只更新被恢复的字段；同表单的其他本地草稿必须原样保留。
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
  return JSON.stringify(llmForm.value) !== llmBaseline.value
    || JSON.stringify(authorForm.value) !== authorBaseline.value
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
    <button class="btn btn-link" id="project-settings-goto-global" @click="gotoGlobalSettings">返回全局设置</button>
  </div>

  <div v-else class="project-settings-view">
    <div class="view-header view-header--with-tabs section-header">
      <h2 class="view-header__title">
        项目设置
        <span class="view-header__project">{{ props.projectTitle }}</span>
      </h2>
      <nav class="subnav settings-tab-nav">
        <button
          v-for="item in TABS"
          :key="item.key"
          class="tab-btn"
          :class="{ active: tab === item.key }"
          :data-tab="item.key"
          @click="tab = item.key"
        >{{ item.label }}</button>
      </nav>
      <div class="view-header__actions llm-global-actions">
        <button class="btn btn-sm btn-link" id="project-settings-goto-global" @click="gotoGlobalSettings">全局设置 →</button>
      </div>
    </div>

    <div class="settings-tab-content">
      <template v-if="dataReady">
        <div v-if="tab === 'main'" class="llm-main-tab">
          <LlmFormFields
            :key="llmFormVersion"
            v-model="llmForm"
            :templates="props.templates"
            :source-map="effectiveLLM"
            :with-api-key="true"
            :api-key-configured="apiKeyConfigured"
            :configured-providers="configuredProviders"
          />
          <div class="settings-actions">
            <button
              class="btn btn-primary"
              id="llm-tab-save"
              :class="{ 'settings-btn-loading': llmButton.saving.value, 'settings-btn-error': llmButton.error.value }"
              :disabled="llmButton.saving.value"
              @click="saveLLM"
            >保存项目 LLM 配置</button>
            <button class="btn btn-link" id="llm-tab-reset-all" @click="resetAllLLMFields">恢复所有字段到全局默认</button>
          </div>
          <ul class="llm-source-legend">
            <li><span class="source-label source-project">已覆盖</span>：项目自填值</li>
            <li><span class="source-label source-global">继承全局</span>：项目未设</li>
            <li><span class="source-label source-system">系统默认</span>：全局也无</li>
            <li><span class="source-label source-unset">未配置</span>：必须填</li>
          </ul>
        </div>

        <div v-else-if="tab === 'deep'" class="deep-import-tab">
          <p class="settings-section-hint">
            深度导入不继承“默认输出上限”，而是按阶段使用独立的系数、下限和上限。
          </p>
          <p class="deep-import-source-hint">
            深度导入参数 <SourceLabel :source="deepImportSource.source" :value="deepImportSource.value" />
          </p>
          <DeepImportFields v-model="deepImportForm" />
          <div class="settings-actions">
            <button
              class="btn btn-primary"
              id="deep-import-tab-save"
              :class="{ 'settings-btn-loading': deepImportButton.saving.value, 'settings-btn-error': deepImportButton.error.value }"
              :disabled="deepImportButton.saving.value"
              @click="saveDeepImport"
            >保存深度导入参数</button>
            <button
              v-if="deepImportSource.source === 'project'"
              class="btn btn-link"
              id="deep-import-tab-reset-all"
              @click="resetDeepImport"
            >恢复到全局/系统默认</button>
          </div>
        </div>

        <div v-else-if="tab === 'author'" class="author-prefs-tab" data-mode="project">
          <AuthorPreferencesForm v-model="authorForm" :source-map="effectivePrefs" @reset-field="resetAuthorPrefsField" />
          <div class="settings-actions">
            <button
              class="btn btn-primary"
              id="author-prefs-tab-save"
              :class="{ 'settings-btn-loading': authorButton.saving.value, 'settings-btn-error': authorButton.error.value }"
              :disabled="authorButton.saving.value"
              @click="saveAuthorPrefs"
            >保存作者偏好</button>
          </div>
        </div>
      </template>
      <template v-else>加载中…</template>
    </div>
  </div>
</template>
