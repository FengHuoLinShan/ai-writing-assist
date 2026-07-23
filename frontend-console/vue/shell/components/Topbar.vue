<template>
  <header id="topbar">
    <div class="topbar-left"><span class="logo"><span class="logo-mark">◆</span>NovelCraft</span></div>
    <div class="topbar-center">
      <span id="topbar-project">{{ projectTitle }}</span><span class="separator">·</span>
      <span id="topbar-module">{{ moduleTitle }}</span>
      <span id="topbar-submodule" class="topbar-submodule" :class="{ hidden: !submoduleTitle }">{{ submoduleTitle ? `· ${submoduleTitle}` : '' }}</span>
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
      <button v-if="accountVisible" class="avatar" type="button" title="账号设置" aria-label="账号设置" @click="$emit('manage-account')">U</button>
      <div v-else class="avatar">U</div>
    </div>
  </header>
</template>

<script setup>
import { computed } from "vue"
import ThemePicker from "./ThemePicker.vue"

const props = defineProps({
  projectTitle: { type: String, default: "" }, moduleTitle: { type: String, default: "项目" }, submoduleTitle: { type: String, default: "" },
  viewNote: { type: String, default: "" }, connected: Boolean, theme: { type: String, required: true }, wordcount: { type: Object, required: true }, wordcountVisible: Boolean,
  accountVisible: { type: Boolean, default: false },
})
defineEmits(["select-theme", "manage-account"])
const saveStateTitle = computed(() => ({ saving: "保存中", unsaved: "未保存", saved: "已保存" })[props.wordcount.saveState] || "保存状态")
function formatNumber(value) { return Number(value || 0).toLocaleString() }
</script>
