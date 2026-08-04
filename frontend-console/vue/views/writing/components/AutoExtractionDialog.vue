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
        <p class="writing-form-hint" role="note">任务只会在作者确认后启动；普通 LLM 结果仍进入待处理或授权范围内的派生资产。</p>
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
  deep: "启动深度导入",
  scenes: "从正文提取 Scene",
  world_objects: "世界对象与别名/关系自动提取",
  plot_structure: "剧情线自动提取",
}[props.model.stage] || "自动提取"))
</script>
