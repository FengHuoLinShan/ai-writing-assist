<script setup>
import {
  computed,
  nextTick,
  onBeforeUnmount,
  ref,
  watch,
} from "vue"
import {
  calculateAdaptivePopoverPlacement,
  readVisualViewportRect,
} from "./adaptivePopoverPlacement.js"

const props = defineProps({
  anchor: { type: Object, default: null },
  busy: { type: Boolean, default: false },
  busyText: { type: String, default: "正在开启…" },
  confirmText: { type: String, default: "确认" },
  expectedText: { type: String, default: "" },
  id: { type: String, required: true },
  inputLabel: { type: String, default: "" },
  message: { type: String, required: true },
  open: { type: Boolean, default: false },
})

const emit = defineEmits(["close", "confirm"])
const popover = ref(null)
const primaryButton = ref(null)
const textInput = ref(null)
const inputValue = ref("")
const position = ref(null)
let animationFrame = null
let listenersAttached = false
let resizeObserver = null
let returnFocusTarget = null

const popoverStyle = computed(() => {
  if (!position.value) {
    return {
      left: "0px",
      top: "0px",
      visibility: "hidden",
    }
  }
  return {
    "--rp-popover-arrow-x": `${position.value.arrowX}px`,
    left: `${position.value.left}px`,
    maxHeight: `${position.value.maxHeight}px`,
    top: `${position.value.top}px`,
    visibility: "visible",
    width: `${position.value.width}px`,
  }
})
const canConfirm = computed(() => !props.expectedText || inputValue.value === props.expectedText)

function updatePosition() {
  animationFrame = null
  if (!props.open || !props.anchor?.getBoundingClientRect || !popover.value) return
  const next = calculateAdaptivePopoverPlacement({
    anchorRect: props.anchor.getBoundingClientRect(),
    popoverRect: popover.value.getBoundingClientRect(),
    viewportRect: readVisualViewportRect(),
  })
  const firstPosition = position.value === null
  position.value = next
  if (firstPosition) void nextTick(() => (props.expectedText ? textInput.value : primaryButton.value)?.focus())
}

function schedulePositionUpdate() {
  if (!props.open || animationFrame !== null) return
  const requestFrame = globalThis.requestAnimationFrame
    || ((callback) => globalThis.setTimeout(callback, 0))
  animationFrame = requestFrame(updatePosition)
}

function cancelPositionUpdate() {
  if (animationFrame === null) return
  const cancelFrame = globalThis.cancelAnimationFrame || globalThis.clearTimeout
  cancelFrame(animationFrame)
  animationFrame = null
}

function attachPositionListeners() {
  if (listenersAttached) return
  listenersAttached = true
  globalThis.addEventListener?.("resize", schedulePositionUpdate)
  globalThis.addEventListener?.("scroll", schedulePositionUpdate, true)
  globalThis.visualViewport?.addEventListener?.("resize", schedulePositionUpdate)
  globalThis.visualViewport?.addEventListener?.("scroll", schedulePositionUpdate)
  if (globalThis.ResizeObserver) {
    resizeObserver = new ResizeObserver(schedulePositionUpdate)
    if (props.anchor) resizeObserver.observe(props.anchor)
    if (popover.value) resizeObserver.observe(popover.value)
  }
}

function detachPositionListeners() {
  if (!listenersAttached) return
  listenersAttached = false
  globalThis.removeEventListener?.("resize", schedulePositionUpdate)
  globalThis.removeEventListener?.("scroll", schedulePositionUpdate, true)
  globalThis.visualViewport?.removeEventListener?.("resize", schedulePositionUpdate)
  globalThis.visualViewport?.removeEventListener?.("scroll", schedulePositionUpdate)
  resizeObserver?.disconnect()
  resizeObserver = null
}

function requestClose() {
  if (!props.busy) emit("close")
}

function confirm() {
  if (!props.busy && canConfirm.value) emit("confirm", inputValue.value)
}

watch(
  () => [props.open, props.anchor],
  async ([open]) => {
    cancelPositionUpdate()
    detachPositionListeners()
    position.value = null
    if (!open) {
      const target = returnFocusTarget
      returnFocusTarget = null
      await nextTick()
      target?.focus?.()
      return
    }
    inputValue.value = ""
    returnFocusTarget = props.anchor
    await nextTick()
    attachPositionListeners()
    schedulePositionUpdate()
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  cancelPositionUpdate()
  detachPositionListeners()
})
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      ref="popover"
      class="rp-adaptive-confirm"
      :data-placement="position?.placement || 'pending'"
      :style="popoverStyle"
    >
      <span class="rp-adaptive-confirm__arrow" aria-hidden="true"></span>
      <section
        :id="id"
        class="rp-sea-notice rp-adaptive-confirm__surface"
        :class="{ 'is-busy': busy }"
        role="alertdialog"
        :aria-describedby="`${id}-message`"
        :aria-labelledby="`${id}-title`"
        aria-modal="false"
        @keydown.esc.stop.prevent="requestClose"
      >
        <strong :id="`${id}-title`">请确认</strong>
        <p :id="`${id}-message`">{{ message }}</p>
        <label v-if="expectedText" class="rp-adaptive-confirm__field">
          <span>{{ inputLabel || `请输入“${expectedText}”` }}</span>
          <input
            ref="textInput"
            v-model="inputValue"
            type="text"
            autocomplete="off"
            :disabled="busy"
            :aria-describedby="`${id}-message`"
            @keydown.enter.prevent="confirm"
          />
        </label>
        <footer class="rp-adaptive-confirm__actions">
          <button type="button" :disabled="busy" @click="requestClose">取消</button>
          <button
            ref="primaryButton"
            class="primary"
            type="button"
            :disabled="busy || !canConfirm"
            @click="confirm"
          >{{ busy ? busyText : confirmText }}</button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>
