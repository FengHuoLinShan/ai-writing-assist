<template>
  <div v-if="model.open" class="modal-overlay" role="dialog" aria-modal="true" aria-label="剧情设定冲突检查选项">
    <div class="modal-content">
      <div class="modal-header">
        <h3>剧情设定冲突检查</h3>
        <button class="btn-icon" aria-label="关闭" @click="model.open = false">×</button>
      </div>
      <div class="modal-body writing-conflict-options">
        <label class="writing-checkbox-label">
          <input v-model="model.includeCandidates" type="checkbox">
          <span>包含待处理内容</span>
        </label>
        <p class="writing-form-hint">包含后，依赖待处理内容的结果会标记注意原因；不会修改正文、Scene、地图或已采用设定。</p>
      </div>
      <div class="modal-footer">
        <button class="btn btn-ghost" @click="model.open = false">取消</button>
        <button class="btn btn-primary" @click="$emit('submit')">开始检查</button>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({ model: { type: Object, required: true } })
defineEmits(["submit"])
</script>
