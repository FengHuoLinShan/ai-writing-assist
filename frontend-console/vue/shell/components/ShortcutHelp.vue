<template>
  <div ref="overlay" id="help-overlay" :class="{ hidden: !open }" :aria-hidden="String(!open)" :inert="!open"
    @click.self="emit('close')" @keydown.capture="handleKeydown">
    <div id="help-modal" role="dialog" aria-modal="true" aria-labelledby="shell-help-title" tabindex="-1">
      <div id="help-header"><h2 id="shell-help-title">快捷键帮助</h2><button id="help-close" type="button" aria-label="关闭快捷键帮助" @click="$emit('close')">×</button></div>
      <div id="help-body"><table class="help-table"><tbody>
        <tr v-for="item in shortcuts" :key="item.keys"><td><kbd>{{ item.keys }}</kbd></td><td>{{ item.label }}</td></tr>
      </tbody></table></div>
    </div>
  </div>
</template>

<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from "vue"

const props = defineProps({ open: Boolean })
const emit = defineEmits(["close"])
const overlay = ref(null)
let previouslyFocused = null
let inertedSiblings = []
let focusGeneration = 0

const FOCUSABLE_SELECTOR = [
  "a[href]", "button:not([disabled])", "input:not([disabled])", "select:not([disabled])",
  "textarea:not([disabled])", "[contenteditable='true']", "[tabindex]:not([tabindex='-1'])",
].join(",")

function focusableElements() {
  return Array.from(overlay.value?.querySelectorAll?.(FOCUSABLE_SELECTOR) || [])
    .filter((element) => !element.closest("[hidden], [aria-hidden='true'], [inert]"))
}

function isolateBackground() {
  const parent = overlay.value?.parentElement
  inertedSiblings = Array.from(parent?.children || []).filter((element) => (
    element !== overlay.value && !element.hasAttribute("inert")
  ))
  for (const element of inertedSiblings) element.setAttribute("inert", "")
}

function restoreBackground() {
  for (const element of inertedSiblings) element.removeAttribute("inert")
  inertedSiblings = []
}

function handleKeydown(event) {
  if (!props.open) return
  if (event.key === "Escape") {
    event.preventDefault()
    event.stopPropagation()
    emit("close")
    return
  }
  if (event.key !== "Tab") return
  const focusable = focusableElements()
  if (!focusable.length) {
    event.preventDefault()
    overlay.value?.querySelector?.("#help-modal")?.focus?.()
    return
  }
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (event.shiftKey && (document.activeElement === first || !focusable.includes(document.activeElement))) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && (document.activeElement === last || !focusable.includes(document.activeElement))) {
    event.preventDefault()
    first.focus()
  }
}

watch(() => props.open, async (open) => {
  const generation = ++focusGeneration
  if (open) {
    previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null
    isolateBackground()
    await nextTick()
    if (!props.open || generation !== focusGeneration) return
    const target = focusableElements()[0] || overlay.value?.querySelector?.("#help-modal")
    target?.focus?.()
    return
  }
  restoreBackground()
  await nextTick()
  if (generation !== focusGeneration) return
  if (previouslyFocused?.isConnected) previouslyFocused.focus()
  previouslyFocused = null
}, { immediate: true })

onBeforeUnmount(restoreBackground)

const shortcuts = [
  { keys: "?", label: "显示快捷键帮助面板" }, { keys: ":", label: "聚焦命令栏（命令模式）" }, { keys: "/", label: "聚焦命令栏（搜索模式）" },
  { keys: "Esc", label: "返回上级 / 关闭弹窗 / 退出命令栏" }, { keys: "j / k", label: "列表上下移动" }, { keys: "h / l", label: "左右切换区域" },
  { keys: "Enter", label: "打开 / 选中" }, { keys: "n", label: "新建" }, { keys: "e", label: "编辑" }, { keys: "Ctrl/Cmd+S", label: "保存当前章节" },
  { keys: "Ctrl/Cmd+Shift+O", label: "打开 / 关闭大纲浮窗" }, { keys: "s", label: "保存" }, { keys: "g", label: "生成" }, { keys: "x", label: "删除（需二次确认）" },
]
</script>
