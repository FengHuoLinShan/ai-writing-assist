<template>
  <header id="topbar">
    <div class="topbar-left"><div class="logo"><span class="logo-mark" aria-hidden="true">N</span><span class="logo-name">NovelCraft</span></div></div>
    <div class="topbar-center">
      <ActionMenu class="topbar-workspace-menu" menu-id="topbar-workspaces" label="浏览作品与工作区" trigger-text="工作区" :items="workspaceMenuItems" @select="navigateItem" />
      <span class="topbar-context-label">正在创作</span><span class="separator">/</span>
      <span id="topbar-project" :title="projectTitle">{{ projectTitle || '选择作品' }}</span><span class="separator">/</span>
      <span id="topbar-module">{{ moduleTitle }}</span>
      <span id="topbar-submodule" class="topbar-submodule" :class="{ hidden: !submoduleVisible }">{{ submoduleVisible ? `· ${submoduleTitle}` : '' }}</span>
      <span v-if="viewNote" id="topbar-view-note" class="topbar-view-note">{{ viewNote }}</span>
      <span id="topbar-chapter" class="topbar-chapter" :class="{ hidden: !wordcountVisible }">{{ wordcountVisible ? `第 ${wordcount.chapterIndex} 章` : '' }}</span>
    </div>
    <div class="topbar-right">
      <button v-if="assistantEnabled" type="button" class="btn btn-sm creative-assistant-button" aria-controls="project-assistant-panel" :aria-expanded="assistantOpen" @pointerdown="$emit('assistant-context')" @click="$emit('open-assistant')"><span aria-hidden="true">✦</span>项目助手</button>
      <span id="topbar-status-dot" class="status-indicator" :class="connected ? 'connected' : 'disconnected'" role="status" :aria-label="connectionLabel" :title="connectionLabel"></span>
      <span id="topbar-status" class="status-text">{{ connected ? '已连接' : '未连接' }}</span>
      <div id="topbar-wordcount" class="topbar-wordcount" :class="{ hidden: !wordcountVisible }" aria-label="写作字数仪表盘">
        <span id="topbar-chapter-wc" title="本章字数">{{ formatNumber(wordcount.chapterWords) }} 字</span>
        <span v-if="wordcount.todayWords > 0" id="topbar-today-wc" title="今日新增字数">今日新增 {{ formatNumber(wordcount.todayWords) }} 字</span>
        <span id="topbar-save-state" class="save-state" :class="wordcount.saveState" :title="saveStateTitle">◆</span>
      </div>
      <ThemePicker :model-value="theme" @update:model-value="$emit('select-theme', $event)" />
      <details ref="accountMenu" class="topbar-account-menu">
        <summary class="avatar" role="button" :title="accountMenuLabel" aria-label="账户菜单" aria-describedby="topbar-status">U</summary>
        <div class="topbar-account-menu__panel">
          <button type="button" @click="runMenuAction('open-settings')"><strong>账户与模型连接</strong><span>管理 AI 服务和创作偏好</span></button>
          <button type="button" @click="openAppearance"><strong>外观</strong><span>主题、明暗模式与资源包</span></button>
          <button type="button" @click="runMenuAction('manage-account')"><strong>账户信息</strong><span>查看身份与安全设置</span></button>
          <button type="button" @click="runMenuAction('show-help')"><strong>帮助</strong><span>快捷键与常用操作</span></button>
        </div>
      </details>
    </div>
  </header>
</template>

<script setup>
import { computed, ref } from "vue"
import { getRouter } from "../../bridge/index.js"
import ActionMenu from "../../components/ActionMenu.vue"
import { SHELL_MORE_ITEMS, SHELL_NAV_ITEMS } from "../navigation.js"
import ThemePicker from "./ThemePicker.vue"

const WORKSPACE_ITEMS = Object.freeze([
  ...SHELL_NAV_ITEMS.map(({ view, label, title }) => ({ action: view, label, hint: title })),
  ...SHELL_MORE_ITEMS.map(({ view, label, title }) => ({ action: view, label, hint: title })),
  { action: "writing", label: "正文编辑", hint: "打开当前作品的章节编辑器" },
])

const props = defineProps({
  projectTitle: { type: String, default: "" }, moduleTitle: { type: String, default: "项目" }, submoduleTitle: { type: String, default: "" },
  viewNote: { type: String, default: "" }, connected: Boolean, theme: { type: String, required: true }, wordcount: { type: Object, required: true }, wordcountVisible: Boolean,
  assistantEnabled: Boolean, assistantOpen: Boolean,
  workspaceItems: { type: Array, default: () => [] },
})
const emit = defineEmits(["select-theme", "manage-account", "open-settings", "show-help", "assistant-context", "open-assistant", "navigate"])
const workspaceMenuItems = computed(() => props.workspaceItems.length ? props.workspaceItems : WORKSPACE_ITEMS)
const accountMenu = ref(null)
const connectionLabel = computed(() => props.connected ? "服务已连接" : "服务未连接")
const accountMenuLabel = computed(() => `账户菜单，${connectionLabel.value}`)
const saveStateTitle = computed(() => ({ saving: "保存中", unsaved: "未保存", saved: "已保存" })[props.wordcount.saveState] || "保存状态")
// 子视图与模块同名时隐藏子段，避免「查找 · 查找」式重复面包屑
const submoduleVisible = computed(() => Boolean(props.submoduleTitle) && props.submoduleTitle !== props.moduleTitle)
function openAppearance() {
  if (accountMenu.value) accountMenu.value.open = false
  return getRouter().navigate("settings", null, true, new URLSearchParams({ section: "appearance" }))
}
function navigateItem(item) { emit("navigate", item.action) }
function formatNumber(value) { return Number(value || 0).toLocaleString() }
function runMenuAction(action) {
  const summary = accountMenu.value?.querySelector("summary")
  if (accountMenu.value) accountMenu.value.open = false
  summary?.focus()
  emit(action)
}
</script>
