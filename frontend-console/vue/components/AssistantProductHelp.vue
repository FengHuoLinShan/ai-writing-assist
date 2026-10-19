<script setup>
import { openAssistantDestination } from '../shared/assistantNavigation.js'
defineProps({ guide: { type: Object, default: null }, automaticAvailability: { type: Object, default: null } })
</script>
<template>
  <section class="assistant-product-help" aria-label="操作帮助">
    <p>按当前产品的实际入口操作。讨论记录、修改预览和保存回执分别核对。</p>
    <p v-if="!guide?.items?.length" role="status">操作说明暂未读到，请重开助手读取当前版本。</p>
    <details v-for="topic in guide?.items || []" :key="topic.id">
      <summary>{{ topic.title }}</summary>
      <ol><li v-for="step in topic.steps" :key="step">{{ step }}</li></ol>
      <p>{{ topic.condition }}</p>
      <p v-if="topic.id === 'automatic' && automaticAvailability?.available === false" role="status">{{ automaticAvailability.reason }}</p>
      <button type="button" class="btn btn-sm" @click="openAssistantDestination(topic.destination)">打开对应工作台</button>
    </details>
    <small v-if="guide?.version">说明版本：{{ guide.version }}</small>
  </section>
</template>
<style scoped>
.assistant-product-help { overflow: auto; padding: 1rem; line-height: 1.6; }
.assistant-product-help details { padding-block: .65rem; border-bottom: 1px solid var(--border-color, var(--border)); }
.assistant-product-help summary { cursor: pointer; font-weight: 600; min-height: 44px; }
.assistant-product-help ol { padding-inline-start: 1.4rem; }
.assistant-product-help small { display: block; margin-block-start: 1rem; color: var(--text-secondary); }
</style>
