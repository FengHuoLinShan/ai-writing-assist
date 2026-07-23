<template>
  <div class="vue-shell-root" @pointerdown.capture="dismissTransientUi">
    <Topbar :project-title="projectTitle" :module-title="moduleTitle" :submodule-title="submoduleTitle" :view-note="viewNote"
      :connected="health.connected.value" :theme="theme.current.value" :wordcount="wordcount.dashboard" :wordcount-visible="wordcountVisible"
      :account-visible="accountService.visible" @select-theme="theme.apply" @manage-account="accountOpen = true" />
    <div id="main-layout">
      <Sidebar ref="sidebar" :current-view="shellState.currentView" @navigate="navigate" @show-help="showHelp" />
      <WorkspaceHost ref="workspace" @ready="setRouteHost" />
      <aside id="contextual-notes"></aside>
    </div>
    <CommandPalette ref="commandPalette" :services="services" />
    <ShortcutHelp :open="helpOpen" @close="hideHelp" />
    <ServiceHosts :services="services" />
    <AccountDialog :open="accountOpen" :account="accountService.current" :config="accountService.config"
      @close="accountOpen = false" @logout="logout" @account-invalidated="accountService.invalidate('account-deletion')" />
  </div>
</template>

<script setup>
import { computed, ref, watch } from "vue"
import CommandPalette from "./components/CommandPalette.vue"
import AccountDialog from "./components/AccountDialog.vue"
import ServiceHosts from "./components/ServiceHosts.vue"
import ShortcutHelp from "./components/ShortcutHelp.vue"
import Sidebar from "./components/Sidebar.vue"
import Topbar from "./components/Topbar.vue"
import WorkspaceHost from "./components/WorkspaceHost.vue"
import { useHealthPolling } from "./composables/useHealthPolling.js"
import { useShellShortcuts } from "./composables/useShellShortcuts.js"
import { useShellState } from "./composables/useShellState.js"
import { useTheme } from "./composables/useTheme.js"
import { useWordcountDashboard } from "./composables/useWordcountDashboard.js"
import { navDestination } from "./navigation.js"

const props = defineProps({
  services: { type: Object, required: true },
  healthIntervalMs: { type: Number, default: 30_000 },
})

const services = props.services
const accountService = services.account ?? {
  visible: false,
  current: null,
  config: { auth_mode: "local", wechat_enabled: false },
  invalidate: () => {},
  logout: async () => {},
}
const shellState = useShellState(services)
const theme = useTheme(services)
const health = useHealthPolling(services, { intervalMs: props.healthIntervalMs })
const wordcount = useWordcountDashboard()
const helpOpen = ref(false)
const accountOpen = ref(new URLSearchParams(location.search).get("auth") === "reauthenticated")
const commandPalette = ref(null)
const workspace = ref(null)
const sidebar = ref(null)
const routeHost = ref(null)

const projectTitle = computed(() => shellState.currentProject?.title || shellState.currentProject?.name || "")
const moduleTitle = computed(() => services.router.getRoute(shellState.currentView)?.title || shellState.currentView || "项目")
const submoduleTitle = computed(() => services.router.getSubViewTitle(shellState.currentView, shellState.currentSubView))
const viewNote = computed(() => ({
  project: "项目是其他所有模块的根。点击项目卡片即可进入创作流程。",
  world: "管理小说中的人物、地点、物品等长期创作资产。",
  writing: "按章节撰写正文。支持暂存、发布、版本管理。",
  rag: "检索小说正文与结构资料，追溯可靠证据来源。",
  generate: "先自由聊，确定后再生成待处理建议。",
})[shellState.currentView] || "")
const wordcountVisible = computed(() => (
  shellState.currentView === "writing"
  && Boolean(shellState.currentProjectId)
  && wordcount.dashboard.chapterIndex !== null
))

function syncRouteScope() {
  if (!routeHost.value) return
  routeHost.value.dataset.workspaceView = shellState.currentView || "unknown"
  routeHost.value.dataset.workspaceSubview = shellState.currentSubView || "root"
}
function setRouteHost(element) { routeHost.value = element; syncRouteScope() }
watch(() => [shellState.currentView, shellState.currentSubView], syncRouteScope)
watch(() => shellState.backendConnected, (value) => { health.connected.value = Boolean(value) })

async function navigate(view) {
  try { await services.router.navigate(view, navDestination(services, view)) }
  catch (err) { services.toast(`导航失败：${err?.message || "未知错误"}`, "error") }
}
function showHelp() { helpOpen.value = true }
function hideHelp() { helpOpen.value = false }
async function logout() {
  try { await accountService.logout() }
  catch (err) { services.toast(`退出失败：${err?.message || "未知错误"}`, "error") }
}
function focusSidebar() {
  const root = sidebar.value?.$el
  const target = root?.querySelector?.(`.nav-item.active[data-view]`) || root?.querySelector?.(`.nav-item[data-view]`)
  target?.focus?.()
}
function dismissTransientUi(event) {
  if (commandPalette.value?.isOpen() && !commandPalette.value.contains(event.target)) commandPalette.value.close()
}

useShellShortcuts({
  services,
  shellState,
  getRouteHost: () => routeHost.value,
  command: {
    open: (prefix) => commandPalette.value?.open(prefix),
    close: () => commandPalette.value?.close(),
    isOpen: () => Boolean(commandPalette.value?.isOpen()),
  },
  help: { open: showHelp, close: hideHelp, isOpen: () => helpOpen.value },
  focusSidebar,
})

defineExpose({
  getRouteHost: () => routeHost.value,
  updateWordcountDashboard: wordcount.update,
  openCommandPalette: (prefix = ":") => commandPalette.value?.open(prefix),
  showHelp,
})
</script>

<style>
.vue-shell-root{display:contents}
</style>
