<script setup>
import { computed } from 'vue'
import { useModalDialog } from '../composables/useModalDialog.js'
const props = defineProps({ mobile: Boolean, open: Boolean, title: { type: String, required: true } })
const emit = defineEmits(['close'])
const isOpen = computed(() => props.mobile && props.open)
const { overlayRef, dialogRef, onKeydown, onFocusin } = useModalDialog({ isOpen: () => isOpen.value, requestClose: () => emit('close') })
</script>
<template>
  <Teleport to="body" :disabled="!mobile">
  <div v-show="!mobile || open" ref="overlayRef" :class="mobile ? 'workspace-drawer-overlay' : 'workspace-drawer-inline'" @click.self="mobile && $emit('close')">
    <section ref="dialogRef" @keydown="isOpen && onKeydown($event)" @focusin="isOpen && onFocusin($event)" :class="mobile ? 'workspace-drawer' : 'workspace-drawer-inline'" :role="mobile ? 'dialog' : undefined" :aria-modal="mobile ? 'true' : undefined" :aria-label="mobile ? title : undefined" :tabindex="mobile ? -1 : undefined">
      <header v-if="mobile"><h2>{{ title }}</h2><button type="button" class="btn" :aria-label="`关闭${title}`" @click="$emit('close')">完成</button></header>
      <slot />
    </section>
  </div>
  </Teleport>
</template>
