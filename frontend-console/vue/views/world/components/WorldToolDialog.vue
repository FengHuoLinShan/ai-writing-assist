<script setup>
import { useModalDialog } from "../../../composables/useModalDialog.js"

const props = defineProps({ open: Boolean, title: { type: String, default: "资料工具" } })
const emit = defineEmits(["close"])
const close = () => emit("close")
const { overlayRef, dialogRef, onKeydown, onFocusin } = useModalDialog({ isOpen: () => props.open, requestClose: close })
</script>

<template>
  <Teleport to="body">
    <div v-if="open" ref="overlayRef" class="modal-overlay" @click.self="close" @keydown="onKeydown" @focusin="onFocusin">
      <section ref="dialogRef" class="modal-content modal-content--wide world-tool-dialog" role="dialog" aria-modal="true" aria-labelledby="world-tool-dialog-title" tabindex="-1">
        <header class="modal-header"><h2 id="world-tool-dialog-title">{{ title }}</h2><button type="button" class="btn-icon" aria-label="关闭" @click="close">×</button></header>
        <div class="modal-body"><slot /></div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.world-tool-dialog { max-height: min(760px, calc(100vh - 32px)); }
.world-tool-dialog .modal-body { overflow-y: auto; }
</style>
