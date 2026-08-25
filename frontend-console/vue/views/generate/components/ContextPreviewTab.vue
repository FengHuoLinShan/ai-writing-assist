<template>
  <article class="card generate-context-preview">
    <header class="generate-context-preview__header">
      <div>
        <span class="generate-context-eyebrow">AI 参考资料</span>
        <h3 class="card-title">完整参考资料</h3>
        <p>先确认资料范围和来源；只有复制或导出时才需要准备完整文本。</p>
      </div>
      <span v-if="sourceText" class="generate-context-preview-source">整理来源：{{ sourceText }}</span>
    </header>

    <template v-if="bundle">
      <div class="generate-result-actions generate-preview-actions">
        <button class="btn btn-sm" type="button" data-action="switch-generate-subtab" @click="$emit('return')">返回调整</button>
        <button class="btn btn-sm" :class="{ 'btn-primary': !markdown }" type="button" data-action="render-task-md" :disabled="busy" @click="$emit('render-markdown')">{{ busy ? "正在准备…" : markdown ? "重新准备完整文本" : "准备可复制文本" }}</button>
        <button v-if="markdown" class="btn btn-sm btn-primary" type="button" data-action="copy-task-md" @click="$emit('copy-markdown')">复制完整文本</button>
        <button v-if="markdown" class="btn btn-sm" type="button" data-action="export-task-md" @click="$emit('export-markdown')">导出文件</button>
      </div>

      <div id="gen-preview-output" :aria-busy="busy ? 'true' : undefined">
        <div v-if="busy" class="generate-context-preview__loading" role="status" aria-live="polite">正在准备可复制的完整文本；当前资料摘要仍会保留。</div>
        <div v-if="error" ref="errorEl" class="error-card generate-task-error" role="alert" tabindex="-1">
          <strong>暂时没能准备完整文本</strong>
          <p>{{ error }}</p>
          <button class="btn btn-sm" type="button" data-action="retry-context-preview" :disabled="busy" @click="$emit('render-markdown')">重试</button>
        </div>
        <ContextBundleView :bundle="bundle" />
        <details v-if="markdown" class="generate-context-markdown" open>
          <summary><span>可复制的完整文本</span><small>用于外部工具或人工核对</small></summary>
          <pre class="generate-markdown-pre">{{ markdown }}</pre>
        </details>
      </div>
    </template>

    <div v-else class="generate-context-preview-empty">
      <strong>还没有整理好的参考资料</strong>
      <p>先说明想完成什么，系统会汇集相关设定、人物和章节资料；不会修改作品。</p>
      <button class="btn btn-primary" type="button" data-action="start-context-preview" @click="$emit('return')">去整理参考资料</button>
    </div>
  </article>
</template>

<script setup>
import { nextTick, ref, watch } from "vue"
import ContextBundleView from "./ContextBundleView.vue"

const props = defineProps({ bundle: Object, markdown: String, sourceText: String, busy: Boolean, error: String })
defineEmits(["render-markdown", "copy-markdown", "export-markdown", "return"])

const errorEl = ref(null)
watch(() => props.error, async (error) => {
  if (!error) return
  await nextTick()
  errorEl.value?.focus()
})
</script>
