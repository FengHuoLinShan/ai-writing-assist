<template>
  <div id="command-bar" ref="bar" :class="{ active, 'has-suggestions': suggestions.length > 0 }" :inert="!active" :aria-hidden="String(!active)">
    <div class="command-header"><span id="command-mode" class="command-mode-label" :class="modeClass">{{ modeLabel }}</span><span id="command-hint">{{ hint }}</span></div>
    <div class="command-input-wrap"><span id="command-prompt">{{ prompt }}</span>
      <input id="command-input" ref="input" v-model="value" type="text" autocomplete="off" spellcheck="false" :placeholder="placeholder" aria-label="命令栏输入"
        @focus="ensureOpen" @blur="hideWhenEmpty" @keydown.enter.prevent.stop="execute(value)" @keydown.escape.prevent.stop="close" @keydown.tab.prevent="complete" />
    </div>
    <div id="command-suggestions" class="command-suggestions">
      <button v-for="suggestion in suggestions.slice(0, 6)" :key="suggestion.name" type="button" class="suggestion" :data-cmd="suggestion.name" @mousedown.prevent="execute(suggestion.name)">
        <span>{{ suggestion.name }}<span v-if="suggestion.help" class="shell-suggestion-description">{{ suggestion.help }}</span></span><span class="suggestion-key">Enter</span>
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, ref } from "vue"

const props = defineProps({ services: { type: Object, required: true } })
const active = ref(false); const value = ref(""); const input = ref(null); const bar = ref(null)
const mode = computed(() => value.value.startsWith("/") ? "SEARCH" : "COMMAND")
const prompt = computed(() => mode.value === "SEARCH" ? "/" : ":")
const modeLabel = computed(() => mode.value === "SEARCH" ? "搜索模式" : "命令模式")
const modeClass = computed(() => mode.value === "SEARCH" ? "search" : "command")
const placeholder = computed(() => mode.value === "SEARCH" ? "搜索..." : "输入命令...")
const hint = computed(() => !value.value.trim() ? "" : mode.value === "SEARCH" ? "按 Enter 跳转 RAG 搜索" : "Tab 补全")
const suggestions = computed(() => {
  const text = value.value.trim()
  return text.startsWith(":") ? props.services.commands.getSuggestions(text.slice(1)) : []
})

function setMode(next) { props.services.state.mode = next }
async function open(prefix = ":") { value.value = prefix; active.value = true; setMode(prefix === "/" ? "SEARCH" : "COMMAND"); await nextTick(); input.value?.focus(); input.value?.setSelectionRange(prefix.length, prefix.length) }
function close() { value.value = ""; active.value = false; setMode("NORMAL") }
function ensureOpen() { if (!active.value) active.value = true; setMode(mode.value) }
function hideWhenEmpty() { if (!value.value) close() }
async function execute(command) { const text = String(command || "").trim(); close(); if (!text) return; try { await props.services.commands.execute(text) } catch (err) { props.services.toast(`命令执行失败：${err?.message || "未知错误"}`, "error") } }
function complete() { const first = suggestions.value[0]; if (first) value.value = `${first.name} ` }
function contains(target) { return Boolean(bar.value?.contains(target)) }
defineExpose({ open, close, execute, isOpen: () => active.value, contains })
</script>

<style>
.shell-suggestion-description{color:var(--text-tertiary);margin-left:8px;font-size:12px}.command-suggestions .suggestion{width:100%;border:0;background:transparent;text-align:left}
</style>
