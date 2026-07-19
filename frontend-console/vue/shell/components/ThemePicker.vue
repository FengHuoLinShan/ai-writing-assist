<template>
  <div class="topbar-theme" @focusout="onFocusOut">
    <button id="theme-toggle" class="btn-icon" type="button" title="切换主题" aria-haspopup="menu" :aria-expanded="open" @click.stop="open = !open">☀</button>
    <div id="theme-menu" :class="{ hidden: !open }" role="menu">
      <button v-for="item in SHELL_THEMES" :key="item.value" type="button" class="theme-option" role="menuitemradio"
        :aria-checked="modelValue === item.value" :data-theme-value="item.value" @click.stop="select(item.value)">{{ item.icon }} {{ item.label }}</button>
    </div>
  </div>
</template>

<script setup>
import { ref } from "vue"
import { SHELL_THEMES } from "../composables/useTheme.js"

defineProps({ modelValue: { type: String, required: true } })
const emit = defineEmits(["update:modelValue"])
const open = ref(false)
function select(theme) { emit("update:modelValue", theme); open.value = false }
function onFocusOut(event) { if (!event.currentTarget.contains(event.relatedTarget)) open.value = false }
defineExpose({ close: () => { open.value = false } })
</script>

<style>
.topbar-theme{position:relative}.topbar-theme #theme-toggle{background:none;border:none;color:var(--text-secondary);cursor:pointer;font-size:14px;padding:4px 8px;border-radius:var(--radius-sm)}
.topbar-theme #theme-menu{position:absolute;right:0;top:36px;background:var(--bg-panel);border:1px solid var(--border);border-radius:var(--radius-md);padding:6px 0;box-shadow:var(--shadow-lg);min-width:160px;z-index:1000}
.topbar-theme #theme-menu.hidden{display:none}.topbar-theme .theme-option{display:block;width:100%;text-align:left;padding:8px 14px;background:none;border:none;color:var(--text-body);font-size:13px;cursor:pointer}
</style>
