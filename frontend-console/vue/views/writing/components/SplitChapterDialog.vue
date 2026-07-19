<template>
  <div v-if="model.open" class="modal-overlay" role="dialog" aria-modal="true" aria-label="断章">
    <div class="modal-content">
      <div class="modal-header">
        <h3>断章</h3>
        <button class="btn-icon" aria-label="关闭" @click="model.open = false">×</button>
      </div>
      <div class="modal-body">
        <div class="form-group">
          <label for="vue-writing-split-offset">断章位置（字符 offset）</label>
          <input id="vue-writing-split-offset" v-model.number="model.position" class="form-input" type="number" min="1" :max="model.max">
        </div>
        <p>当前 Scene：{{ model.sceneTitle }}</p>
        <p class="writing-form-hint">将从指定 offset 切分为新章节，并同步更新 Scene chunk。</p>
      </div>
      <div class="modal-footer">
        <button class="btn btn-ghost" @click="model.open = false">取消</button>
        <button class="btn btn-primary" :disabled="model.busy" @click="$emit('submit')">{{ model.busy ? '断章中...' : '确认断章' }}</button>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({ model: { type: Object, required: true } })
defineEmits(["submit"])
</script>
