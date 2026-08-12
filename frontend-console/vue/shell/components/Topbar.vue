<template>
  <header id="topbar">
    <div class="topbar-left"><div class="logo"><span class="logo-mark">◆</span>NovelCraft</div></div>
    <div class="topbar-center">
      <span id="topbar-project">{{ projectTitle }}</span><span class="separator">·</span>
      <span id="topbar-module">{{ moduleTitle }}</span>
      <span id="topbar-submodule" class="topbar-submodule" :class="{ hidden: !submoduleVisible }">{{ submoduleVisible ? `· ${submoduleTitle}` : '' }}</span>
      <span v-if="viewNote" id="topbar-view-note" class="topbar-view-note">{{ viewNote }}</span>
      <span id="topbar-chapter" class="topbar-chapter" :class="{ hidden: !wordcountVisible }">{{ wordcountVisible ? `第 ${wordcount.chapterIndex} 章` : '' }}</span>
    </div>
    <div class="topbar-right">
      <span id="topbar-status-dot" class="status-indicator" :class="connected ? 'connected' : 'disconnected'" title="后端连接状态"></span>
      <span id="topbar-status" class="status-text hidden">{{ connected ? '已连接' : '未连接' }}</span>
      <div id="topbar-wordcount" class="topbar-wordcount" :class="{ hidden: !wordcountVisible }" aria-label="写作字数仪表盘">
        <span id="topbar-chapter-wc" title="本章字数">{{ formatNumber(wordcount.chapterWords) }}</span><span class="wc-separator">/</span>
        <span id="topbar-today-wc" title="今日字数">{{ formatNumber(wordcount.todayWords) }}</span>
        <span id="topbar-save-state" class="save-state" :class="wordcount.saveState" :title="saveStateTitle">◆</span>
      </div>
      <ThemePicker :model-value="theme" @update:model-value="$emit('select-theme', $event)" />
      <details ref="accountMenu" class="topbar-account-menu">
        <summary class="avatar" role="button" title="账户菜单" aria-label="账户菜单">U</summary>
        <div class="topbar-account-menu__panel">
          <button type="button" @click="runMenuAction('open-settings')"><strong>账户与模型连接</strong><span>管理 AI 服务和创作偏好</span></button>
          <button type="button" @click="runMenuAction('manage-account')"><strong>账户信息</strong><span>查看身份与安全设置</span></button>
          <button type="button" @click="runMenuAction('show-help')"><strong>帮助</strong><span>快捷键与常用操作</span></button>
        </div>
      </details>
    </div>
  </header>
</template>

<script setup>
import { computed, ref } from "vue"
import ThemePicker from "./ThemePicker.vue"

const props = defineProps({
  projectTitle: { type: String, default: "" }, moduleTitle: { type: String, default: "项目" }, submoduleTitle: { type: String, default: "" },
  viewNote: { type: String, default: "" }, connected: Boolean, theme: { type: String, required: true }, wordcount: { type: Object, required: true }, wordcountVisible: Boolean,
})
const emit = defineEmits(["select-theme", "manage-account", "open-settings", "show-help"])
const accountMenu = ref(null)
const saveStateTitle = computed(() => ({ saving: "保存中", unsaved: "未保存", saved: "已保存" })[props.wordcount.saveState] || "保存状态")
// 子视图与模块同名时隐藏子段，避免「查找 · 查找」式重复面包屑
const submoduleVisible = computed(() => Boolean(props.submoduleTitle) && props.submoduleTitle !== props.moduleTitle)
function formatNumber(value) { return Number(value || 0).toLocaleString() }
function runMenuAction(action) {
  const summary = accountMenu.value?.querySelector("summary")
  if (accountMenu.value) accountMenu.value.open = false
  summary?.focus()
  emit(action)
}
</script>
