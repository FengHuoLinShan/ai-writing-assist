<template>
  <div v-if="bundle">
    <div class="generate-context-header">
      <span class="generate-context-stat">已加载 {{ bundle.sections?.length || 0 }} 段上下文</span>
      <span class="generate-context-meta">范围：{{ bundle.scope }}</span>
      <span class="generate-context-meta">揭示模式：{{ bundle.reveal_mode }}</span>
      <span class="generate-context-meta">Tokens：{{ bundle.total_tokens || 0 }}{{ budgetLabel }}</span>
    </div>
    <table v-if="bundle.sections?.length" class="data-table generate-context-table">
      <thead><tr><th>Tier</th><th>Section</th><th>Tokens</th><th>Truncated</th></tr></thead>
      <tbody>
        <tr v-for="section in bundle.sections" :key="section.key">
          <td class="generate-context-meta">{{ tierName(section.tier) }}</td>
          <td>{{ section.key }}</td><td>{{ section.token_count || 0 }}</td><td>{{ section.truncated ? '是' : '否' }}</td>
        </tr>
      </tbody>
    </table>
    <div v-if="bundle.evicted?.length" class="generate-context-tag-list">
      <strong class="generate-context-meta">已驱逐段落：</strong>
      <div class="generate-context-tags"><span v-for="key in bundle.evicted" :key="key" class="generate-context-tag">{{ key }}</span></div>
    </div>
    <div v-if="bundle.truncated?.length" class="generate-context-tag-list">
      <strong class="generate-context-meta">已截断段落：</strong>
      <div class="generate-context-tags"><span v-for="key in bundle.truncated" :key="key" class="generate-context-tag generate-context-tag--truncated">{{ key }}</span></div>
    </div>
    <div v-if="bundle.warnings?.length" class="generate-context-warning">
      <strong class="generate-context-warning-title">⚠ 警告</strong>
      <p v-for="warning in bundle.warnings" :key="warning" class="generate-context-warning-text">{{ warning }}</p>
    </div>
    <p class="generate-context-hint">点击“渲染 Markdown”查看完整上下文内容。</p>
  </div>
</template>

<script setup>
import { computed } from "vue"
import { tierName } from "../logic/generateLogic.js"
const props = defineProps({ bundle: { type: Object, default: null } })
const budgetLabel = computed(() => props.bundle?.budget_tokens > 0 ? ` / ${props.bundle.budget_tokens}` : "（无应用层裁剪）")
</script>
