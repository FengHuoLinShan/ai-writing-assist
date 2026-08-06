<template>
  <div v-if="model.open" ref="overlayRef" class="modal-overlay" @keydown="onKeydown" @focusin="onFocusin">
    <div ref="dialogRef" class="modal-content writing-auto-extract-dialog" role="dialog" aria-modal="true" aria-label="自动提取" aria-labelledby="auto-extraction-dialog-label" :aria-busy="model.busy" tabindex="-1">
      <span id="auto-extraction-dialog-label" class="sr-only">自动提取</span>
      <div class="modal-header">
        <h3 id="auto-extraction-dialog-heading">{{ label }}</h3>
        <button type="button" class="btn-icon" aria-label="关闭" @click="requestClose">×</button>
      </div>
      <div class="modal-body">
        <div class="form-group">
          <label for="vue-auto-extract-start">起始章节</label>
          <input id="vue-auto-extract-start" v-model.number="model.start" class="form-input" type="number" min="1">
        </div>
        <div class="form-group">
          <label for="vue-auto-extract-end">结束章节</label>
          <input id="vue-auto-extract-end" v-model.number="model.end" class="form-input" type="number" min="1">
        </div>
        <label v-if="model.stage === 'scenes' || model.stage === 'deep'" class="writing-checkbox-label writing-form-option">
          <input v-model="model.highQuality" type="checkbox">
          <span>更高质量</span>
          <span class="writing-checkbox-hint">最大推理 + 融合补强，约需更长时间</span>
        </label>
        <p class="writing-form-hint" role="note">只有确认后才会开始整理；AI 结果会先进入待处理，不会自动变成正式设定。</p>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-ghost" @click="requestClose">取消</button>
        <button type="button" class="btn btn-primary" :disabled="model.busy" @click="$emit('submit')">{{ model.busy ? '提交中...' : '确认并开始提取' }}</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue"
import { useModalDialog } from "../../../composables/useModalDialog.js"
const props = defineProps({ model: { type: Object, required: true } })
defineEmits(["submit"])
const requestClose = () => { props.model.open = false }
const { overlayRef, dialogRef, onKeydown, onFocusin } = useModalDialog({ isOpen: () => props.model.open, requestClose })
const label = computed(() => ({
  deep: "完整整理导入内容",
  scenes: "从正文整理场景",
  world_objects: "整理人物、设定与关系",
  plot_structure: "从正文整理剧情线",
}[props.model.stage] || "自动提取"))
</script>
