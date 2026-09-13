<template>
  <div
    class="vue-shell-root creative-shell"
    :class="{ 'public-demo-shell': publicDemo }"
    :data-public-demo="publicDemo || undefined"
    :data-theme="theme.resolved.value"
    @pointerdown.capture="dismissTransientUi"
    @shell-theme-request="theme.apply($event.detail)"
  >
    <Topbar v-if="showAuthorChrome" :project-title="projectTitle" :module-title="moduleTitle" :submodule-title="submoduleTitle" :view-note="viewNote"
      :connected="health.connected.value" :theme="theme.current.value" :wordcount="wordcount.dashboard" :wordcount-visible="wordcountVisible"
      :assistant-enabled="assistantEnabled" :assistant-open="assistantOpen" @assistant-context="captureAssistant" @open-assistant="assistantOpen = !assistantOpen" @navigate="navigate"
      :public-demo="publicDemo" @select-theme="theme.apply" @manage-account="accountOpen = true" @open-settings="navigate('settings')" @show-help="showHelp" @copy-demo="requestDemoCopy" />
    <div id="main-layout" :class="{ 'main-layout--immersive': !showAuthorChrome }">
      <Sidebar v-if="showAuthorChrome" ref="sidebar" :current-view="shellState.currentView" :project-title="projectTitle" :public-demo="publicDemo" @navigate="navigate" @show-help="showHelp" />
      <WorkspaceHost ref="workspace" @ready="setRouteHost" @click.capture="blockDemoWorkspaceControl" @keydown.capture="blockDemoWorkspaceControl" />
      <aside id="contextual-notes"></aside>
      <ProjectAssistant v-if="!publicDemo && showAuthorChrome && shellState.currentProjectId" :project-id="shellState.currentProjectId" :page="shellState.currentView" :open="assistantOpen" :initial-context="assistantContext" @open="assistantOpen = true" @close="assistantOpen = false" @availability="assistantEnabled = $event" />
    </div>
    <CommandPalette v-if="!publicDemo" ref="commandPalette" :services="services" />
    <ShortcutHelp v-if="!publicDemo" :open="helpOpen" @close="hideHelp" />
    <ServiceHosts v-if="!publicDemo" :services="services" />
    <AccountDialog v-if="!publicDemo" :open="accountOpen" :account="accountService.current" :config="accountService.config"
      @close="accountOpen = false" @logout="logout" @account-invalidated="accountService.invalidate('account-deletion')"
      @switch-mode="accountOpen = false; navigate('home')" />
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue"
import ProjectAssistant from "../components/ProjectAssistant.vue"
import { getAssistantWorkContext } from "../bridge/index.js"
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
import { storeDemoCopyIntent } from "../auth/entryMode.js"

const props = defineProps({
  services: { type: Object, required: true },
  healthIntervalMs: { type: Number, default: 30_000 },
})
const assistantOpen = ref(false)
const assistantEnabled = ref(false)
const assistantContext = ref(null)
function captureAssistant() {
  try { assistantContext.value = { projectId: shellState.currentProjectId, context: getAssistantWorkContext(shellState.currentProjectId, shellState.currentView) } }
  catch { assistantContext.value = null }
}

const services = props.services
const publicDemo = Boolean(globalThis.publicDemoMode)
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
  if (["home", "journeys", "interaction", "demo-rp"].includes(shellState.currentView)) {
    return false
  }
  if (shellState.currentView === "settings") {
    const returnTarget = services.router.getCurrentQuery()?.get("return_to") || ""
    if (normalizeRpReturnTarget(returnTarget)) return false
  }
  return true
})

const projectTitle = computed(() => shellState.currentProject?.title || shellState.currentProject?.name || "")
const moduleTitle = computed(() => services.router.getRoute(shellState.currentView).title)
const submoduleTitle = computed(() => services.router.getSubViewTitle(shellState.currentView, shellState.currentSubView))
const viewNote = computed(() => ({
  project: "选择一部作品，或从空白和已有正文开始。",
  today: "从上次停下的地方继续，待处理内容可以稍后决定。",
  world: "管理人物、地点、物品和关系等长期创作资料；需要 AI 时就在本页打开工具。",
  writing: "按章节写作，工作稿会自动保存。",
  rag: "在正文与作品资料中查找可靠来源。",
  generate: "旧生成入口正在转向所属工作页；已有会话仍可恢复。",
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

let demoObserver = null
const demoMutationLabel = /新建|新增|创建|保存|删除|导入|上传|生成|更新|修改|编辑|采用|发布|设置|连接|助手|归档|恢复|撤销|重做|清空|日志/
function isDemoMutationControl(control) {
  if (!control) return false
  if (control.matches("textarea, [contenteditable='true'], input[type='file']")) return true
  if (control.matches("input:not([type]), input[type='text'], input[type='number'], input[type='url']")) {
    return !/搜索|筛选/.test(`${control.getAttribute("aria-label") || ""} ${control.placeholder || ""}`)
  }
  if (!control.matches("button")) return false
  const label = [
    control.dataset?.action,
    control.getAttribute("aria-label"),
    control.title,
    control.textContent,
  ].filter(Boolean).join(" ")
  return demoMutationLabel.test(label)
}
function lockDemoWorkspaceControls() {
  if (!publicDemo || !routeHost.value) return
  for (const control of routeHost.value.querySelectorAll("button, input, textarea, select, [contenteditable='true']")) {
    if (!isDemoMutationControl(control)) continue
    if (control.matches("input, textarea")) {
      control.readOnly = true
      control.setAttribute("aria-readonly", "true")
    } else if (control.matches("[contenteditable='true']")) {
      control.setAttribute("contenteditable", "false")
      control.setAttribute("aria-readonly", "true")
    } else {
      control.disabled = true
      control.setAttribute("aria-disabled", "true")
    }
    control.title = "演示项目为只读；登录并复制后可以尝试修改。"
  }
}
watch(routeHost, (host) => {
  demoObserver?.disconnect()
  demoObserver = null
  if (!publicDemo || !host || typeof MutationObserver === "undefined") return
  lockDemoWorkspaceControls()
  demoObserver = new MutationObserver(lockDemoWorkspaceControls)
  demoObserver.observe(host, { childList: true, subtree: true })
}, { flush: "post" })
onBeforeUnmount(() => demoObserver?.disconnect())

async function navigate(view) {
  try { await services.router.navigate(view, navDestination(services, view)) }
  catch (err) { services.toast(`导航失败：${err?.message || "未知错误"}`, "error") }
}
function requestDemoCopy() {
  storeDemoCopyIntent()
  const url = new URL(globalThis.location.href)
  url.searchParams.delete("demo")
  url.hash = ""
  globalThis.location.assign(url)
}
function blockDemoWorkspaceControl(event) {
  const control = event.target?.closest?.("button, input, textarea, select, [contenteditable='true']")
  if (!publicDemo || !isDemoMutationControl(control)) return
  event.preventDefault()
  event.stopImmediatePropagation()
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

if (!publicDemo) {
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
}

defineExpose({
  getRouteHost: () => routeHost.value,
  updateWordcountDashboard: wordcount.update,
  openCommandPalette: (prefix = ":") => commandPalette.value?.open(prefix),
  showHelp,
})
</script>

<style src="./creative-shell.css"></style>
