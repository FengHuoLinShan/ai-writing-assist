<script setup>
import { computed } from 'vue'
import { useModalDialog } from '../composables/useModalDialog.js'
const props = defineProps({ mobile: Boolean, open: Boolean, title: { type: String, required: true } })
const emit = defineEmits(['close'])
const isOpen = computed(() => props.mobile && props.open)
const { overlayRef, dialogRef, onKeydown, onFocusin } = useModalDialog({ isOpen: () => isOpen.value, requestClose: () => emit('close') })
</script>
<template>
  <div v-if="mobile && open" ref="overlayRef" class="workspace-drawer-overlay" @click.self="$emit('close')">
    <section ref="dialogRef" @keydown="onKeydown" @focusin="onFocusin" class="workspace-drawer" role="dialog" aria-modal="true" :aria-label="title" tabindex="-1">
      <header><h2>{{ title }}</h2><button type="button" class="btn" :aria-label="`关闭${title}`" @click="$emit('close')">完成</button></header>
      <slot />
    </section>
  </div>
  <slot v-else-if="!mobile" />
</template>
