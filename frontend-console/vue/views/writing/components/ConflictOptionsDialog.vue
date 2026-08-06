<template>
  <div v-if="model.open" ref="overlayRef" class="modal-overlay" @keydown="onKeydown" @focusin="onFocusin">
    <div ref="dialogRef" class="modal-content" role="dialog" aria-modal="true" aria-label="剧情设定冲突检查选项" aria-labelledby="conflict-options-dialog-label" tabindex="-1">
      <span id="conflict-options-dialog-label" class="sr-only">剧情设定冲突检查选项</span>
      <div class="modal-header">
        <h3 id="conflict-options-dialog-heading">剧情设定冲突检查</h3>
        <button type="button" class="btn-icon" aria-label="关闭" @click="requestClose">×</button>
      </div>
      <div class="modal-body writing-conflict-options">
        <label class="writing-checkbox-label">
          <input v-model="model.includeCandidates" type="checkbox">
          <span>包含待处理内容</span>
        </label>
        <p class="writing-form-hint">包含后，依赖待处理内容的结果会标记注意原因；不会修改正文、场景、地图或已采用设定。</p>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-ghost" @click="requestClose">取消</button>
        <button type="button" class="btn btn-primary" @click="$emit('submit')">开始检查</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useModalDialog } from "../../../composables/useModalDialog.js"
const props = defineProps({ model: { type: Object, required: true } })
defineEmits(["submit"])
const requestClose = () => { props.model.open = false }
const { overlayRef, dialogRef, onKeydown, onFocusin } = useModalDialog({ isOpen: () => props.model.open, requestClose })
</script>
