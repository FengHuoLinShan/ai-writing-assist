<template>
  <div ref="pickerRoot" class="topbar-theme" @focusout="onFocusOut">
    <button
      id="theme-toggle"
      ref="toggleButton"
      class="btn-icon"
      type="button"
      title="切换主题"
      aria-label="切换主题"
      aria-haspopup="menu"
      aria-controls="theme-menu"
      :aria-expanded="open"
      @click.stop="toggleMenu"
      @keydown="onToggleKeydown"
    >☀</button>
    <div id="theme-menu" :class="{ hidden: !open }" role="menu">
      <button
        v-for="item in SHELL_THEMES"
        :key="item.value"
        ref="menuItems"
        type="button"
        class="theme-option"
        role="menuitemradio"
        :aria-checked="modelValue === item.value"
        :data-theme-value="item.value"
        :tabindex="focusedValue === item.value ? 0 : -1"
        @click.stop="select(item.value)"
        @keydown="onItemKeydown($event, item.value)"
      >{{ item.icon }} {{ item.label }}</button>
    </div>
  </div>
</template>

<script setup>
import { nextTick, ref } from "vue"
import { SHELL_THEMES } from "../composables/useTheme.js"

const props = defineProps({ modelValue: { type: String, required: true } })
const emit = defineEmits(["update:modelValue"])
const open = ref(false)
const pickerRoot = ref(null)
const toggleButton = ref(null)
const menuItems = ref([])
const focusedValue = ref(null)

function focusItem(value) {
  void nextTick(() => {
    if (!open.value || focusedValue.value !== value) return
    menuItems.value.find((item) => item?.dataset?.themeValue === value)?.focus()
  })
}

function openMenu() {
  const current = SHELL_THEMES.find((item) => item.value === props.modelValue)
  focusedValue.value = current?.value || SHELL_THEMES[0]?.value || null
  open.value = true
  focusItem(focusedValue.value)
}

function toggleMenu() {
  if (open.value) {
    close()
    return
  }
  openMenu()
}

function close() {
  open.value = false
  void nextTick(() => {
    if (pickerRoot.value?.contains(document.activeElement)) toggleButton.value?.focus()
  })
}

function closeAndFocusToggle() {
  open.value = false
  void nextTick(() => toggleButton.value?.focus())
}

function select(theme) {
  emit("update:modelValue", theme)
  closeAndFocusToggle()
}

function onToggleKeydown(event) {
  if (["Enter", " ", "Spacebar"].includes(event.key)) event.stopPropagation()
}

function onItemKeydown(event, value) {
  event.stopPropagation()
  const currentIndex = SHELL_THEMES.findIndex((item) => item.value === value)
  if (currentIndex < 0) return
  let nextIndex = currentIndex
  if (event.key === "ArrowDown") {
    nextIndex = (currentIndex + 1) % SHELL_THEMES.length
  } else if (event.key === "ArrowUp") {
    nextIndex = (currentIndex - 1 + SHELL_THEMES.length) % SHELL_THEMES.length
  } else if (event.key === "Home") {
    nextIndex = 0
  } else if (event.key === "End") {
    nextIndex = SHELL_THEMES.length - 1
  } else if (event.key === "Escape") {
    event.preventDefault()
    closeAndFocusToggle()
    return
  } else {
    return
  }
  event.preventDefault()
  focusedValue.value = SHELL_THEMES[nextIndex]?.value || null
  focusItem(focusedValue.value)
}

function onFocusOut(event) {
  if (!event.currentTarget.contains(event.relatedTarget)) close()
}

defineExpose({ close })
</script>

