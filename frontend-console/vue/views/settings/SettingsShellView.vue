<script setup>
import GlobalSettingsView from "./GlobalSettingsView.vue"
import ProjectSettingsView from "./ProjectSettingsView.vue"
import { getRouter } from "../../bridge/index.js"

const props = defineProps({
  scope: { type: String, default: "account" },
  currentProjectId: { type: String, default: null },
  currentProjectTitle: { type: String, default: "" },
  llmConnections: { type: Object, default: null },
  llmBalances: { type: Object, default: () => ({ items: [] }) },
  authorPrefs: { type: Object, default: () => ({}) },
  effectiveLLM: { type: Object, default: null },
  effectivePrefs: { type: Object, default: null },
})

const router = getRouter()
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
        <h1>账户与当前作品</h1>
        <p>账户负责连接与通用偏好；当前作品负责本作品的创作与导入偏好。</p>
      </div>
      <span v-if="currentProjectTitle" class="settings-shell__project">当前作品：{{ currentProjectTitle }}</span>
    </header>
    <nav class="settings-shell__tabs" role="tablist" aria-label="设置范围">
      <button type="button" class="tab-btn" :class="{ active: scope === 'account' }" :aria-selected="scope === 'account'" role="tab" data-action="settings-scope-account" @click="selectScope('account')">账户</button>
      <button type="button" class="tab-btn" :class="{ active: scope === 'project' }" :aria-selected="scope === 'project'" role="tab" data-action="settings-scope-project" :disabled="!currentProjectId" @click="selectScope('project')">当前作品</button>
    </nav>
    <GlobalSettingsView
      v-if="scope === 'account'"
      :llm-connections="llmConnections"
      :llm-balances="llmBalances"
      :author-prefs="authorPrefs"
    />
    <ProjectSettingsView
      v-else
      :project-id="currentProjectId"
      :project-title="currentProjectTitle"
      :effective-l-l-m="effectiveLLM"
      :effective-prefs="effectivePrefs"
    />
  </div>
</template>
