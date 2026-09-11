<template>
  <div v-if="model.open" ref="overlayRef" class="modal-overlay" @keydown="onKeydown" @focusin="onFocusin">
    <div ref="dialogRef" class="modal-content writing-auto-extract-dialog" role="dialog" aria-modal="true" aria-label="自动提取" aria-labelledby="auto-extraction-dialog-label" :aria-busy="model.busy" tabindex="-1">
      <span id="auto-extraction-dialog-label" class="sr-only">自动提取</span>
      <div class="modal-header">
        <h3 id="auto-extraction-dialog-heading">{{ label }}</h3>
        <button type="button" class="btn-icon" aria-label="关闭" @click="requestClose">×</button>
      </div>
      <div class="modal-body">
        <ProjectOrganizationHistory v-if="projectId" :project-id="projectId" @prepare="Object.assign(model, $event)" />
        <h4>开始新的整理</h4>
        <label class="form-group">本次整理目标<select v-model="model.stage" class="form-select"><option value="deep">完整基础整理</option><option value="scenes">补充场景</option><option value="world_objects">补充人物与世界资料</option><option value="plot_structure">整理剧情结构</option></select></label>
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
          <span class="writing-checkbox-hint">逐段复核并整理相邻场景，需要更长时间</span>
        </label>
        <p v-if="['deep', 'world_objects'].includes(model.stage)" class="writing-form-hint">基础成果先交付；系统保留本批查漏范围，稍后由你确认并继续。</p>
        <p class="writing-form-hint" role="note">{{ importAuthorizationNotice(model.stage) }}</p>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-ghost" @click="requestClose">取消</button>
        <button type="button" class="btn btn-primary" :disabled="model.busy" @click="$emit('submit')">{{ model.busy ? '提交中...' : '确认并开始提取' }}</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import ProjectOrganizationHistory from "../../../components/ProjectOrganizationHistory.vue"
import { computed } from "vue"
import { importAuthorizationNotice } from "../../../../shared/importAuthorization.js"
import { useModalDialog } from "../../../composables/useModalDialog.js"
const props = defineProps({ projectId: { type: String, default: null }, model: { type: Object, required: true } })
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
