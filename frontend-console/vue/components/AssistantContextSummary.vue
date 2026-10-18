<template>
  <details class="assistant-context-summary">
    <summary>{{ fixed ? '本轮固定目标' : '本次参考' }}：{{ label }}</summary>
    <p v-if="fixed">目标绑定提交时的资料；切页或移动光标不会改变这一轮。</p>
    <p>{{ context.scope === 'project' ? '参考整个作品，仍遵守排除项和已确认范围。' : '当前位置优先，不自动扩大为整个作品。' }}</p>
    <p v-if="context.temporary_draft_id">临时草稿仅供讨论，正式修改前须先保存，再重新准备。</p>
    <p v-else-if="context.focus_ref">{{ versionLabel }}；回答前会重新核对。</p>
    <p v-else-if="context.selected_entities?.length">固定所选 {{ context.selected_entities.length }} 个对象及其保存版本；只覆盖这次选择，不代表全部匹配或全库。</p>
    <p v-else-if="context.draft_id">{{ context.source_hash ? '已绑定提交时的正文内容版本。' : '已选择保存的正文，提交时由服务端核对版本。' }}</p>
    <p v-if="context.context_confirmation_id">沿用已确认资料的叙事截止和视角；此处不会扩大范围。</p>
    <p v-else-if="context.page === 'world'">作者视角；这些资料不代表人物已知。</p>
    <p v-if="context.selection">选区共 {{ Array.from(context.selection).length }} 字：{{ context.selection.slice(0, 140) }}</p>
    <p>已排除 {{ context.excluded_targets?.length || 0 }} 项资料。</p>
    <template v-if="fixed && result">
      <p>本轮返回 {{ result.sources?.length || 0 }} 项依据；提供资料不代表结论正确。</p>
      <ul v-if="result.omissions?.length"><li v-for="item in result.omissions" :key="item">{{ item }}</li></ul>
    </template>
  </details>
</template>

<script setup>
import { computed } from 'vue'
const props = defineProps({ context: { type: Object, required: true }, fixed: Boolean, result: { type: Object, default: null } })
const label = computed(() => props.context.focus_label || (props.context.selected_entities?.length ? `已选 ${props.context.selected_entities.length} 个对象` : props.context.chapter_index ? `第 ${props.context.chapter_index} 章` : ({ world: '人物与世界', writing: '写作页面', outline: '故事结构', scene: '当前场景', map: '地图', rag: '查找结果' })[props.context.page] || '当前作品'))
const versionLabel = computed(() => props.context.focus_ref?.kind === 'dossier_entry' ? '已绑定这条档案的保存修订' : props.context.focus_ref?.kind === 'relation' ? '已绑定这条关系的保存版本' : '已绑定这个对象的保存版本')
</script>

<style scoped>
.assistant-context-summary{font-size:12px;line-height:1.6;overflow-wrap:anywhere;margin:8px 0;color:var(--text-secondary)}
.assistant-context-summary summary{cursor:pointer;min-height:32px;display:flex;align-items:center;color:var(--text-primary)}
.assistant-context-summary p{margin:6px 0}
</style>
