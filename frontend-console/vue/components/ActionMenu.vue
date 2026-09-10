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
    <Teleport :to="floatingTarget" :disabled="!floating || !open">
    <div ref="list" :id="listId" class="action-menu-list" :class="{ 'action-menu-list--floating': floating }" :style="floating ? floatingStyle : undefined" role="menu" :aria-labelledby="triggerId" @keydown="onKeydown" @focusout="onFocusOut" @click="closeExtraAction">
      <button
        v-for="(item, index) in items"
        :key="item.action"
        class="action-menu-item"
        :class="item.class || ''"
        :data-action="item.action"
        :aria-disabled="item.disabled ? 'true' : undefined"
        :title="item.hint || undefined"
        :tabindex="open && activeIndex === index ? 0 : -1"
        type="button"
        role="menuitem"
        v-bind="dataAttrs(item)"
        @click.stop="select(item)"
      >{{ item.label }}<small v-if="item.disabled && item.hint">{{ item.hint }}</small></button>
      <slot />
    </div>
    </Teleport>
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
  floating: { type: Boolean, default: false },
})
const emit = defineEmits(["select", "close"])

const floatingTarget = typeof document !== "undefined" && document.getElementById("main-layout") ? "#main-layout" : "body"
const root = ref(null)
const trigger = ref(null)
const list = ref(null)
const floatingStyle = ref({ display: "none" })
const open = ref(false)
const activeIndex = ref(0)
let focusGeneration = 0
const triggerId = computed(() => `action-menu-trigger-${props.menuId}`)
const listId = computed(() => `action-menu-list-${props.menuId}`)
const triggerLabel = computed(() => props.label || "更多操作")

function closeExtraAction(event) {
  const button = event.target.closest?.("button")
  if (button && !button.disabled && button.getAttribute("aria-disabled") !== "true") close({ restoreFocus: true })
}
function contains(target) { return root.value?.contains(target) || list.value?.contains(target) }
function positionMenu() {
  if (!open.value || !props.floating || !trigger.value || !list.value) return
  const anchor = trigger.value.getBoundingClientRect()
  const viewport = window.visualViewport
  const left = viewport?.offsetLeft || 0, top = viewport?.offsetTop || 0
  const width = viewport?.width || window.innerWidth, height = viewport?.height || window.innerHeight
  if (anchor.bottom < top || anchor.top > top + height) {
    close({ recoverHiddenFocus: false })
    return
  }
  const menuWidth = Math.min(260, width - 16)
  const below = top + height - anchor.bottom - 12, above = anchor.top - top - 12
  const useBelow = below >= Math.min(list.value.scrollHeight, 280) || below >= above
  const maxHeight = Math.max(44, Math.min(360, useBelow ? below : above))
  const menuHeight = Math.min(list.value.scrollHeight || 44, maxHeight)
  floatingStyle.value = {
    position: "fixed", display: "block", right: "auto",
    left: Math.max(left + 8, Math.min(anchor.left, left + width - menuWidth - 8)) + "px",
    top: (useBelow ? anchor.bottom + 4 : Math.max(top + 8, anchor.top - menuHeight - 4)) + "px",
    width: menuWidth + "px", minWidth: "0", maxHeight: maxHeight + "px", overflowY: "auto",
  }
}

function dataAttrs(item) {
  return Object.fromEntries(
    Object.entries(item.data || {}).map(([key, value]) => [`data-${key}`, value]),
  )
}

function focusItem(index) {
  const buttons = list.value?.querySelectorAll("button") || []
  if (!buttons.length) return
  const nextIndex = (index + buttons.length) % buttons.length
  activeIndex.value = nextIndex
  const generation = ++focusGeneration
  void nextTick(() => {
    if (!open.value || generation !== focusGeneration || activeIndex.value !== nextIndex) return
    list.value?.querySelectorAll("button")[nextIndex]?.focus()
  })
}

function close({ restoreFocus = false, recoverHiddenFocus = true } = {}) {
  const generation = ++focusGeneration
  const wasOpen = open.value
  open.value = false
  floatingStyle.value = { display: "none" }
  window.removeEventListener("resize", positionMenu)
  window.visualViewport?.removeEventListener("resize", positionMenu)
  window.visualViewport?.removeEventListener("scroll", positionMenu)
  document.removeEventListener("scroll", positionMenu, true)
  if (wasOpen) emit("close")
  releaseActionMenu(close)
  document.removeEventListener("click", onDocumentClick)
  if (restoreFocus) trigger.value?.focus()
  else if (wasOpen && recoverHiddenFocus) {
    void nextTick(() => {
      if (generation !== focusGeneration || open.value || hasAnotherActionMenu(close)) return
      if (contains(document.activeElement)) trigger.value?.focus()
    })
  }
}

function openMenu(index = 0) {
  claimActionMenu(close)
  open.value = true
  document.addEventListener("click", onDocumentClick)
  if (props.floating) {
    floatingStyle.value = { position: "fixed", display: "block", visibility: "hidden" }
    window.addEventListener("resize", positionMenu)
    window.visualViewport?.addEventListener("resize", positionMenu)
    window.visualViewport?.addEventListener("scroll", positionMenu)
    document.addEventListener("scroll", positionMenu, true)
    void nextTick(positionMenu)
  }
  focusItem(index)
}

function toggle() {
  if (open.value) close()
  else openMenu(0)
}

function select(item) {
  if (item.disabled) return
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
      openMenu((list.value?.querySelectorAll("button").length || 1) - 1)
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
  if (!list.value?.contains(event.target) || event.target.tagName !== "BUTTON") return
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
    focusItem((list.value?.querySelectorAll("button").length || 1) - 1)
  } else if (event.key === "Escape") {
    event.preventDefault()
    close({ restoreFocus: true })
  } else if (event.key === "Tab") {
    close()
  }
}

function onFocusOut(event) {
  if (open.value && !contains(event.relatedTarget)) close({ recoverHiddenFocus: false })
}

function onDocumentClick(event) {
  if (open.value && !contains(event.target)) close()
}

onBeforeUnmount(() => {
  close({ recoverHiddenFocus: false })
})
</script>

<style scoped>
.action-menu-list--floating { z-index: 110; }
.action-menu-item[aria-disabled="true"] { opacity: .55; cursor: not-allowed; }
.action-menu-item small { display: block; white-space: normal; }
.action-menu-list--floating .action-menu-item { min-height: 44px; white-space: normal; overflow-wrap: anywhere; }
</style>
