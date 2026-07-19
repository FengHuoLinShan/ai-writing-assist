<template>
  <div class="card">
    <div class="card-title">上下文预览</div>
    <div v-if="sourceText" class="generate-context-preview-source">来自：{{ sourceText }}</div>
    <template v-if="bundle">
      <div class="generate-result-actions generate-preview-actions">
        <button class="btn btn-sm" data-action="render-task-md" :disabled="busy" @click="$emit('render-markdown')">渲染 Markdown</button>
        <button class="btn btn-sm" data-action="copy-task-md" :disabled="!markdown" @click="$emit('copy-markdown')">复制</button>
        <button class="btn btn-sm" data-action="export-task-md" :disabled="!markdown" @click="$emit('export-markdown')">导出</button>
        <button class="btn btn-sm" data-action="switch-generate-subtab" @click="$emit('return')">返回</button>
      </div>
      <div id="gen-task-output"><pre v-if="markdown" class="generate-markdown-pre">{{ markdown }}</pre><ContextBundleView v-else :bundle="bundle" /></div>
    </template>
    <p v-else class="generate-context-preview-empty">还未执行任何 AI 生成或上下文编译。去「世界设定」共创，或在「任务」里编译上下文。</p>
  </div>
</template>

<script setup>
import ContextBundleView from "./ContextBundleView.vue"
defineProps({ bundle: Object, markdown: String, sourceText: String, busy: Boolean })
defineEmits(["render-markdown", "copy-markdown", "export-markdown", "return"])
</script>
