<script setup>
import { ref } from "vue"
import LlmFormFields from "./components/LlmFormFields.vue"
import AuthorPreferencesForm from "./components/AuthorPreferencesForm.vue"
import { getApi, getRouter, getToast, useStateKey } from "../../bridge/index.js"
import { useSaveButton } from "../../composables/useSaveButton.js"
import { buildLlmPayload, llmFormFromDefaults, validateLLMPayload } from "./logic/llmForm.js"
import {
  authorFormFromDefaults,
  buildAuthorPrefsPayload,
  validateAuthorPreferences,
} from "./logic/authorPreferences.js"

/**
 * 全局设置页 — #/settings 入口（无需选项目）。
 * 数据由 island 的 load() 预取并以 props 传入（对应 vanilla onEnter → render 节奏）。
 */
const props = defineProps({
  llmDefaults: { type: Object, default: null },
  authorPrefs: { type: Object, default: () => ({}) },
  templates: { type: Array, default: () => [] },
  projectsUsingDefaults: {
    type: Object,
    default: () => ({ items: [], total: 0, truncated: false }),
  },
})

const currentProjectId = useStateKey("currentProjectId")

const llmForm = ref(llmFormFromDefaults(props.llmDefaults))
const authorForm = ref(authorFormFromDefaults(props.authorPrefs))

const llmButton = useSaveButton()
const authorButton = useSaveButton()

function gotoRecentProject() {
  if (currentProjectId.value) getRouter().navigate("project-settings")
}

async function saveLLM() {
  const toast = getToast()
  const { payload } = buildLlmPayload(llmForm.value)
  const validation = validateLLMPayload(payload)
  if (!validation.ok) return toast(validation.message, "warning")
  llmButton.saving.value = true
  try {
    const clean = { ...payload }
    delete clean.api_key
    delete clean.clear_api_key
    await getApi().settings.updateGlobalLLMDefaults(clean)
    toast("LLM 全局默认已保存", "success")
  } catch (err) {
    toast(err.message || "保存失败", "error")
    llmButton.flashError()
  } finally {
    llmButton.saving.value = false
  }
}

async function saveAuthor() {
  const toast = getToast()
  const prefs = buildAuthorPrefsPayload(authorForm.value)
  const validation = validateAuthorPreferences(prefs)
  if (!validation.ok) return toast(validation.message, "warning")
  authorButton.saving.value = true
  try {
    await getApi().settings.updateGlobalAuthorPrefs(prefs)
    toast("作者偏好已保存", "success")
  } catch (err) {
    toast(err.message || "保存失败", "error")
    authorButton.flashError()
  } finally {
    authorButton.saving.value = false
  }
}

async function runManualMigration() {
  const toast = getToast()
  const api = getApi()
  toast("迁移中…", "info")
  const keys = Object.keys(localStorage).filter((key) => key.startsWith("novel_author_preferences:"))
  let migrated = 0
  for (const key of keys) {
    const projectId = key.split(":")[1]
    if (!projectId || projectId === "global") continue
    let parsed
    try {
      parsed = JSON.parse(localStorage.getItem(key) || "{}")
    } catch {
      continue
    }
    try {
      const existing = await api.settings.getProjectAuthorPrefs(projectId)
      if (
        existing &&
        (existing.daily_goal !== null || existing.editor_font !== null || existing.default_focus_mode !== null)
      ) {
        localStorage.removeItem(key)
        continue
      }
    } catch {
      continue
    }
    const payload = {
      daily_goal: parsed.dailyGoal ?? null,
      editor_font: parsed.editorFont ?? null,
      default_focus_mode: Boolean(parsed.defaultFocusMode ?? false),
    }
    try {
      await api.settings.updateProjectAuthorPrefs(projectId, payload)
      localStorage.removeItem(key)
      migrated += 1
    } catch (err) {
      console.error(`迁移 ${projectId} 失败:`, err)
    }
  }
  toast(`已迁移 ${migrated} 个项目，余 ${keys.length - migrated} 个`, migrated ? "success" : "info")
}
</script>

<template>
  <div class="global-settings-view">
    <div class="view-header section-header">
      <h2 class="view-header__title">
        全局设置
        <span class="view-header__project">owner: local（demo 占位）</span>
      </h2>
      <div class="view-header__actions llm-global-actions">
        <button
          class="btn btn-sm btn-link"
          id="goto-recent-project-btn"
          :disabled="!currentProjectId"
          @click="gotoRecentProject"
        >进入当前项目 →</button>
      </div>
    </div>

    <section class="settings-section">
      <h3>LLM 全局默认</h3>
      <p class="settings-section-hint">不存 API Key；项目级才配置 Key。</p>
      <LlmFormFields v-model="llmForm" :templates="props.templates" :with-api-key="false" />
      <div class="settings-actions">
        <button
          class="btn btn-primary"
          id="global-llm-save"
          :class="{ 'settings-btn-loading': llmButton.saving.value, 'settings-btn-error': llmButton.error.value }"
          :disabled="llmButton.saving.value"
          @click="saveLLM"
        >保存 LLM 全局默认</button>
      </div>
    </section>

    <section class="settings-section">
      <h3>作者偏好全局默认</h3>
      <AuthorPreferencesForm v-model="authorForm" />
      <div class="settings-actions">
        <button
          class="btn btn-primary"
          id="global-author-save"
          :class="{ 'settings-btn-loading': authorButton.saving.value, 'settings-btn-error': authorButton.error.value }"
          :disabled="authorButton.saving.value"
          @click="saveAuthor"
        >保存作者偏好</button>
      </div>
    </section>

    <section class="settings-section">
      <h3>引用此默认的项目（只读）</h3>
      <p v-if="!props.projectsUsingDefaults?.items?.length" class="empty-hint">没有项目继承全局默认</p>
      <template v-else>
        <ul class="projects-using-list">
          <li v-for="item in props.projectsUsingDefaults.items" :key="item.project_id">{{ item.title || "" }} ({{ item.project_id || "" }})</li>
        </ul>
        <p v-if="props.projectsUsingDefaults.truncated" class="settings-section-hint">还有更多项目省略…</p>
      </template>
    </section>

    <section class="settings-section">
      <h3>本地迁移</h3>
      <p class="settings-section-hint">将浏览器 localStorage 中的旧作者偏好一次性迁入后端。</p>
      <div class="settings-actions">
        <button class="btn btn-secondary" id="manual-migrate-btn" @click="runManualMigration">手动迁移所有项目本地偏好</button>
      </div>
    </section>
  </div>
</template>
