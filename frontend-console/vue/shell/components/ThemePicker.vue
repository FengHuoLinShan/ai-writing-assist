<template>
  <div class="topbar-theme" role="radiogroup" aria-label="主题">
    <button
      v-for="item in SHELL_THEMES"
      :key="item.value"
      ref="dots"
      type="button"
      class="theme-dot"
      :class="{ 'is-active': modelValue === item.value }"
      :data-theme-value="item.value"
      :title="item.label"
      :aria-label="'切换到' + item.label"
      role="radio"
      :aria-checked="modelValue === item.value"
      :tabindex="modelValue === item.value ? 0 : -1"
      @click="select(item.value)"
      @keydown="onKeydown($event, item.value)"
    ></button>
  </div>
</template>

<script setup>
import { nextTick, ref } from "vue"
import { SHELL_THEMES } from "../composables/useTheme.js"

defineProps({ modelValue: { type: String, required: true } })
const emit = defineEmits(["update:modelValue"])
const dots = ref([])

function select(theme) {
  emit("update:modelValue", theme)
}

function focusDot(value) {
  void nextTick(() => {
    dots.value.find((item) => item?.dataset?.themeValue === value)?.focus()
  })
}

function onKeydown(event, value) {
  // 方向键以外的按键（含 Enter/Space 原生激活）只拦截冒泡，不阻止默认行为，
  // 避免进入文档级单键快捷键。
  event.stopPropagation()
  const currentIndex = SHELL_THEMES.findIndex((item) => item.value === value)
  if (currentIndex < 0) return
  let nextIndex = null
  if (event.key === "ArrowRight" || event.key === "ArrowDown") {
    nextIndex = (currentIndex + 1) % SHELL_THEMES.length
  } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
    nextIndex = (currentIndex - 1 + SHELL_THEMES.length) % SHELL_THEMES.length
  } else {
    return
  }
  event.preventDefault()
  const next = SHELL_THEMES[nextIndex]
  emit("update:modelValue", next.value)
  focusDot(next.value)
}
</script>
