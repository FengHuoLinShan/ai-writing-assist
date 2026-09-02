<template>
  <div id="command-bar" ref="bar" :class="{ active, 'has-suggestions': suggestions.length > 0 }" :inert="!active" :aria-hidden="String(!active)">
    <div class="command-header"><span id="command-mode" class="command-mode-label" :class="modeClass">{{ modeLabel }}</span><span id="command-hint">{{ hint }}</span></div>
    <div class="command-input-wrap"><span id="command-prompt">{{ prompt }}</span>
      <input id="command-input" ref="input" v-model="value" type="text" autocomplete="off" spellcheck="false" :placeholder="placeholder" aria-label="命令栏输入"
        role="combobox" aria-controls="command-suggestions" :aria-expanded="suggestionsVisible" aria-autocomplete="list" :aria-activedescendant="activeSuggestionId" aria-describedby="command-hint"
        @focus="ensureOpen" @blur="hideWhenEmpty" @keydown="onInputKeydown" />
    </div>
    <div id="command-suggestions" class="command-suggestions" role="listbox" aria-label="命令建议">
      <button v-for="(suggestion, index) in renderedSuggestions" :id="suggestionId(index)" :key="suggestion.name" type="button" class="suggestion" :class="{ active: activeSuggestionIndex === index }" :data-cmd="suggestion.name"
        role="option" :aria-selected="activeSuggestionIndex === index" tabindex="-1" @pointerenter="setActiveSuggestion(index)" @mousedown.prevent="execute(suggestion.name)">
        <span>{{ suggestion.name }}<span v-if="suggestion.help" class="shell-suggestion-description">{{ suggestion.help }}</span></span><span class="suggestion-key">Enter</span>
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from "vue"

const props = defineProps({ services: { type: Object, required: true } })
const active = ref(false); const value = ref(""); const input = ref(null); const bar = ref(null)
const activeSuggestionIndex = ref(-1)
const originFocus = ref(null)
const mode = computed(() => value.value.startsWith("/") ? "SEARCH" : "COMMAND")
const prompt = computed(() => mode.value === "SEARCH" ? "/" : ":")
const modeLabel = computed(() => mode.value === "SEARCH" ? "搜索模式" : "命令模式")
const modeClass = computed(() => mode.value === "SEARCH" ? "search" : "command")
const placeholder = computed(() => mode.value === "SEARCH" ? "搜索..." : "输入命令...")
const hint = computed(() => !value.value.trim() ? "" : mode.value === "SEARCH" ? "按 Enter 查找作品资料" : "Tab 补全")
const suggestions = computed(() => {
  const text = value.value.trim()
  return text.startsWith(":") ? props.services.commands.getSuggestions(text.slice(1)) : []
})
const renderedSuggestions = computed(() => suggestions.value.slice(0, 6))
const suggestionsVisible = computed(() => active.value && renderedSuggestions.value.length > 0)
const activeSuggestion = computed(() => renderedSuggestions.value[activeSuggestionIndex.value] || null)
const activeSuggestionId = computed(() => activeSuggestion.value ? suggestionId(activeSuggestionIndex.value) : undefined)

function setMode(next) { props.services.state.mode = next }
function suggestionId(index) { return `command-suggestion-${index}` }
function clearActiveSuggestion() { activeSuggestionIndex.value = -1 }
function setActiveSuggestion(index) {
  if (index >= 0 && index < renderedSuggestions.value.length) activeSuggestionIndex.value = index
}
function isValidReturnTarget(target) {
  return target instanceof HTMLElement
    && target.isConnected
    && target.tabIndex >= 0
    && !target.matches(":disabled")
    && !target.closest("[inert]")
    && !target.inert
}
async function open(prefix = ":") {
  if (!active.value) originFocus.value = isValidReturnTarget(document.activeElement) ? document.activeElement : null
  value.value = prefix
  active.value = true
  clearActiveSuggestion()
  setMode(prefix === "/" ? "SEARCH" : "COMMAND")
  await nextTick()
  input.value?.focus()
  input.value?.setSelectionRange(prefix.length, prefix.length)
}
function close({ restoreOrigin = false } = {}) {
  const returnTarget = restoreOrigin ? originFocus.value : null
  const inputWasFocused = document.activeElement === input.value
  value.value = ""
  active.value = false
  clearActiveSuggestion()
  setMode("NORMAL")
  originFocus.value = null
  if (inputWasFocused) input.value?.blur()
  if (returnTarget) void nextTick(() => { if (isValidReturnTarget(returnTarget)) returnTarget.focus() })
}
function ensureOpen() { if (!active.value) active.value = true; setMode(mode.value) }
function hideWhenEmpty() { if (!value.value) close() }
async function execute(command) { const text = String(command || "").trim(); close(); if (!text) return; try { await props.services.commands.execute(text) } catch (err) { props.services.toast(`命令执行失败：${err?.message || "未知错误"}`, "error") } }
function complete() { const first = renderedSuggestions.value[0]; if (first) value.value = `${first.name} ` }
function onInputKeydown(event) {
  if (["ArrowDown", "ArrowUp"].includes(event.key)) {
    if (!renderedSuggestions.value.length) return
    event.preventDefault()
    event.stopPropagation()
    const direction = event.key === "ArrowDown" ? 1 : -1
    activeSuggestionIndex.value = activeSuggestionIndex.value < 0
      ? (direction > 0 ? 0 : renderedSuggestions.value.length - 1)
      : (activeSuggestionIndex.value + direction + renderedSuggestions.value.length) % renderedSuggestions.value.length
  } else if (event.key === "Enter") {
    event.preventDefault()
    event.stopPropagation()
    execute(activeSuggestion.value?.name || value.value)
  } else if (event.key === "Escape") {
    event.preventDefault()
    event.stopPropagation()
    close({ restoreOrigin: true })
  } else if (event.key === "Tab") {
    event.preventDefault()
    complete()
  }
}
function contains(target) { return Boolean(bar.value?.contains(target)) }
watch(value, clearActiveSuggestion)
watch(mode, clearActiveSuggestion)
defineExpose({ open, close, execute, isOpen: () => active.value, contains })
</script>

<style scoped>
.shell-suggestion-description{color:var(--text-tertiary);margin-left:8px;font-size:12px}.command-suggestions .suggestion{width:100%;border:0;background:transparent;text-align:left}
</style>
