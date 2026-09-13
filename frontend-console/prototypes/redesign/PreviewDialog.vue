<script setup>
import { nextTick, ref } from 'vue'
import PreviewIcon from './PreviewIcon.vue'
import { vReveal } from './motion.js'
const dialog = ref(null)
const title = ref('')
const kind = ref('')
const drawer = ref(false)
const isOpen = ref(false)
const emit = defineEmits(['panel'])
let origin = null
async function open(heading, content = 'detail', asDrawer = false) {
  const wasOpen = dialog.value.open
  if (!wasOpen || !dialog.value.contains(document.activeElement)) origin = document.activeElement
  if (wasOpen && drawer.value !== asDrawer) dialog.value.close()
  title.value = heading
  kind.value = content
  drawer.value = asDrawer
  isOpen.value = true
  emit('panel', asDrawer ? content : null)
  await nextTick()
  if (!dialog.value.open) {
    if (asDrawer && !globalThis.matchMedia?.('(max-width: 800px)').matches) dialog.value.show()
    else dialog.value.showModal()
  }
  const focusTarget = content === 'new' || content === 'task'
    ? dialog.value.querySelector('input:not([disabled]), textarea')
    : dialog.value.querySelector('[autofocus]')
  focusTarget?.focus()
}
function close() {
  if (!dialog.value?.open) return
  dialog.value.close()
  isOpen.value = false
  emit('panel', null)
}
function onClose() {
  if (dialog.value.open) return
  isOpen.value = false
  emit('panel', null)
  if (origin?.isConnected && !origin.closest('[inert]')) origin.focus()
  else document.getElementById('rd-main')?.focus({ preventScroll: true })
}
defineExpose({ open, close, isOpen })
</script>
<template>
  <dialog ref="dialog" class="rd-dialog" :class="{ 'is-drawer': drawer, 'is-comparison': kind === 'compare' }" aria-labelledby="rd-dialog-title" @close="onClose" @click="event => { if (!drawer && event.target === dialog) close() }">
    <header><h2 id="rd-dialog-title">{{ title }}</h2><button class="rd-icon-button" aria-label="关闭面板" autofocus @click="close"><span class="rd-button-content"><PreviewIcon name="close"/></span></button></header>
    <div v-reveal="kind" class="rd-dialog-body"><slot :kind="kind" :close="close" /></div>
  </dialog>
</template>
