<template>
  <div class="mobile-quick-note">
    <div class="mobile-note-header">
      <span class="mobile-note-chapter">第 {{ state.chapter }} 章</span>
      <span id="mobile-note-wc" class="mobile-note-wc">{{ state.content.length.toLocaleString() }} 字</span>
    </div>
    <textarea
      ref="editorEl"
      id="mobile-note-editor"
      class="mobile-note-editor"
      aria-label="移动端速记正文"
      :value="state.content"
      placeholder="在此记录灵感..."
    />
    <div class="mobile-note-actions">
      <button class="btn btn-primary" :disabled="state.saving" @click="$emit('save')">保存为工作稿</button>
      <button class="btn btn-ghost" @click="$emit('desktop')">完整编辑器</button>
    </div>
  </div>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref } from "vue"

const props = defineProps({
  state: { type: Object, required: true },
  attach: { type: Function, required: true },
  detach: { type: Function, required: true },
})
defineEmits(["save", "desktop"])
const editorEl = ref(null)
onMounted(() => nextTick(() => props.attach({ title: null, editor: editorEl.value })))
onBeforeUnmount(() => props.detach())
</script>
