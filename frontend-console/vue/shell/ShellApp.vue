<template>
  <div
    class="vue-shell-root"
    @pointerdown.capture="dismissTransientUi"
    @shell-theme-request="theme.apply($event.detail)"
  >
    <Topbar v-if="showAuthorChrome" :project-title="projectTitle" :module-title="moduleTitle" :submodule-title="submoduleTitle" :view-note="viewNote"
      :connected="health.connected.value" :theme="theme.current.value" :wordcount="wordcount.dashboard" :wordcount-visible="wordcountVisible"
      @select-theme="theme.apply" @manage-account="accountOpen = true" @open-settings="navigate('settings')" @show-help="showHelp" />
    <div id="main-layout" :class="{ 'main-layout--immersive': !showAuthorChrome }">
      <Sidebar v-if="showAuthorChrome" ref="sidebar" :current-view="shellState.currentView" :project-title="projectTitle" @navigate="navigate" @show-help="showHelp" />
      <WorkspaceHost ref="workspace" @ready="setRouteHost" />
      <aside id="contextual-notes"></aside>
    </div>
    <CommandPalette ref="commandPalette" :services="services" />
    <ShortcutHelp :open="helpOpen" @close="hideHelp" />
    <ServiceHosts :services="services" />
    <AccountDialog :open="accountOpen" :account="accountService.current" :config="accountService.config"
      @close="accountOpen = false" @logout="logout" @account-invalidated="accountService.invalidate('account-deletion')"
      @switch-mode="accountOpen = false; navigate('home')" />
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
import { navDestination, normalizeRpReturnTarget } from "./navigation.js"

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
const showAuthorChrome = computed(() => {
  if (["home", "journeys", "interaction"].includes(shellState.currentView)) {
    return false
  }
  if (shellState.currentView === "settings") {
    const returnTarget = services.router.getCurrentQuery?.()?.get?.("return_to") || ""
    if (normalizeRpReturnTarget(returnTarget)) return false
  }
  return true
})

const projectTitle = computed(() => shellState.currentProject?.title || shellState.currentProject?.name || "")
const moduleTitle = computed(() => services.router.getRoute(shellState.currentView)?.title || shellState.currentView || "项目")
const submoduleTitle = computed(() => services.router.getSubViewTitle(shellState.currentView, shellState.currentSubView))
const viewNote = computed(() => ({
  project: "选择一部作品，或从空白和已有正文开始。",
  today: "从上次停下的地方继续，待处理内容可以稍后决定。",
  world: "管理人物、地点、物品和关系等长期创作资料。",
  writing: "按章节写作，工作稿会自动保存。",
  rag: "在正文与作品资料中查找可靠来源。",
  generate: "面向高级用法的生成与上下文工具。",
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
