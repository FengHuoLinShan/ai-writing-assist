<template>
  <div ref="root" class="action-menu" :class="{ open }" :data-menu-id="menuId" @focusout="onFocusOut" @keydown="onKeydown">
    <button
      ref="trigger"
      class="action-menu-btn"
      type="button"
      :title="triggerLabel"
      :id="triggerId"
      :aria-label="triggerLabel"
      aria-haspopup="menu"
      :aria-expanded="String(open)"
      :aria-controls="listId"
      :disabled="disabled"
      @click.stop="toggle"
    >{{ triggerText }}</button>
    <div :id="listId" class="action-menu-list" role="menu" :aria-labelledby="triggerId">
      <button
        v-for="(item, index) in items"
        :key="item.action"
        class="action-menu-item"
        :class="item.class || ''"
        :data-action="item.action"
        :tabindex="open && activeIndex === index ? 0 : -1"
        type="button"
        role="menuitem"
        v-bind="dataAttrs(item)"
        @click.stop="select(item)"
      >{{ item.label }}</button>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref } from "vue"
import { claimActionMenu, hasAnotherActionMenu, releaseActionMenu } from "./actionMenuCoordinator.js"

const props = defineProps({
  menuId: { type: String, required: true },
  items: { type: Array, default: () => [] }, // [{ action, label, class?, data? }]
  label: { type: String, default: "更多操作" },
  triggerText: { type: String, default: "···" },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(["select"])

const root = ref(null)
const trigger = ref(null)
const open = ref(false)
const activeIndex = ref(0)
let focusGeneration = 0
const triggerId = computed(() => `action-menu-trigger-${props.menuId}`)
const listId = computed(() => `action-menu-list-${props.menuId}`)
const triggerLabel = computed(() => props.label || "更多操作")

function dataAttrs(item) {
  return Object.fromEntries(
    Object.entries(item.data || {}).map(([key, value]) => [`data-${key}`, value]),
  )
}

function focusItem(index) {
  if (!props.items.length) return
  const nextIndex = (index + props.items.length) % props.items.length
  activeIndex.value = nextIndex
  const generation = ++focusGeneration
  void nextTick(() => {
    if (!open.value || generation !== focusGeneration || activeIndex.value !== nextIndex) return
    root.value?.querySelectorAll(".action-menu-item")[nextIndex]?.focus()
  })
}

function close({ restoreFocus = false, recoverHiddenFocus = true } = {}) {
  const generation = ++focusGeneration
  const wasOpen = open.value
  open.value = false
  releaseActionMenu(close)
  document.removeEventListener("click", onDocumentClick)
  if (restoreFocus) trigger.value?.focus()
  else if (wasOpen && recoverHiddenFocus) {
    void nextTick(() => {
      if (generation !== focusGeneration || open.value || hasAnotherActionMenu(close)) return
      if (root.value?.contains(document.activeElement)) trigger.value?.focus()
    })
  }
}

function openMenu(index = 0) {
  claimActionMenu(close)
  open.value = true
  document.addEventListener("click", onDocumentClick)
  focusItem(index)
}

function toggle() {
  if (open.value) close()
  else openMenu(0)
}

function select(item) {
  close({ restoreFocus: true })
  emit("select", item)
}

function onKeydown(event) {
  if (event.target === trigger.value) {
    if (event.key === "ArrowDown") {
      event.stopPropagation()
      event.preventDefault()
      openMenu(0)
    } else if (event.key === "ArrowUp") {
      event.stopPropagation()
      event.preventDefault()
      openMenu(props.items.length - 1)
    } else if (event.key === "Escape" && open.value) {
      event.stopPropagation()
      event.preventDefault()
      close({ restoreFocus: true })
    } else if (event.key === "Enter" || event.key === " " || event.key === "Spacebar") {
      event.stopPropagation()
    } else if (open.value) {
      event.stopPropagation()
    }
    return
  }
  if (!event.target.classList?.contains("action-menu-item")) return
  event.stopPropagation()
  if (event.key === "ArrowDown") {
    event.preventDefault()
    focusItem(activeIndex.value + 1)
  } else if (event.key === "ArrowUp") {
    event.preventDefault()
    focusItem(activeIndex.value - 1)
  } else if (event.key === "Home") {
    event.preventDefault()
    focusItem(0)
  } else if (event.key === "End") {
    event.preventDefault()
    focusItem(props.items.length - 1)
  } else if (event.key === "Escape") {
    event.preventDefault()
    close({ restoreFocus: true })
  } else if (event.key === "Tab") {
    close()
  }
}

function onFocusOut(event) {
  if (open.value && !root.value?.contains(event.relatedTarget)) close({ recoverHiddenFocus: false })
}

function onDocumentClick(event) {
  if (open.value && !root.value?.contains(event.target)) close()
}

onBeforeUnmount(() => {
  close({ recoverHiddenFocus: false })
})
</script>
