<script setup>
import { computed } from "vue"
import GlobalSettingsView from "./GlobalSettingsView.vue"
import ProjectSettingsView from "./ProjectSettingsView.vue"
import { getRouter } from "../../bridge/index.js"
import { normalizeRpReturnTarget } from "../../shell/navigation.js"

const props = defineProps({
  scope: { type: String, default: "account" },
  currentProjectId: { type: String, default: null },
  currentProjectTitle: { type: String, default: "" },
  llmConnections: { type: Object, default: null },
  llmBalances: { type: Object, default: () => ({ items: [] }) },
  authorPrefs: { type: Object, default: () => ({}) },
  connectionsLoadError: { type: String, default: null },
  authorPrefsLoadError: { type: String, default: null },
  effectiveLLM: { type: Object, default: null },
  effectivePrefs: { type: Object, default: null },
  loadError: { type: String, default: null },
})

const router = getRouter()
const returningToRp = Boolean(normalizeRpReturnTarget(
  router?.getCurrentQuery?.()?.get?.("return_to"),
))
const pageTitle = computed(() => props.scope === "project" ? "当前作品设置" : "账户设置")
const pageHint = computed(() => {
  if (returningToRp) return "连接可用的 AI 服务后，会回到刚才的旅程位置。"
  return props.scope === "project"
    ? "只调整当前作品的创作习惯与导入方式。"
    : "管理 AI 服务连接与所有作品共用的创作习惯。"
})

function selectScope(scope) {
  if (scope === "project" && !props.currentProjectId) return router?.navigate?.("project")
  return router?.navigate?.(scope === "project" ? "project-settings" : "settings")
}
</script>

<template>
  <div class="settings-shell" data-settings-shell :data-settings-scope="scope">
    <header class="settings-shell__header">
      <div>
        <span class="settings-shell__eyebrow">设置</span>
        <h1>{{ pageTitle }}</h1>
        <p>{{ pageHint }}</p>
      </div>
      <span v-if="currentProjectTitle && !returningToRp" class="settings-shell__project">当前作品：{{ currentProjectTitle }}</span>
    </header>
    <nav v-if="!returningToRp" class="settings-shell__tabs" aria-label="设置范围">
      <button type="button" class="tab-btn" :class="{ active: scope === 'account' }" :aria-current="scope === 'account' ? 'page' : undefined" data-action="settings-scope-account" @click="selectScope('account')">账户设置</button>
      <button type="button" class="tab-btn" :class="{ active: scope === 'project' }" :aria-current="scope === 'project' ? 'page' : undefined" data-action="settings-scope-project" :disabled="!currentProjectId" @click="selectScope('project')">当前作品</button>
    </nav>
    <GlobalSettingsView
      v-if="scope === 'account'"
      :llm-connections="llmConnections"
      :llm-balances="llmBalances"
      :author-prefs="authorPrefs"
      :connections-load-error="connectionsLoadError"
      :author-prefs-load-error="authorPrefsLoadError"
    />
    <ProjectSettingsView
      v-else
      :project-id="currentProjectId"
      :project-title="currentProjectTitle"
      :effective-l-l-m="effectiveLLM"
      :effective-prefs="effectivePrefs"
      :load-error="loadError"
    />
  </div>
</template>
