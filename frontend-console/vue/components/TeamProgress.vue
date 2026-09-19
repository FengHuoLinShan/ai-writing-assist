<template>
  <section class="team-progress" :aria-label="`${collaboration.label || '专项协作'}进度`">
    <p role="status" aria-live="polite">{{ phase }} · 已完成 {{ collaboration.completed_count }} 项，共 {{ collaboration.total_count }} 项</p>
    <p v-if="collaboration.freshness === 'stale'" role="alert">依据已变化。这份报告保留供比较，请重新检查当前稿。</p>
    <p v-else-if="collaboration.phase === 'completed' && collaboration.completion !== 'complete'">{{ collaboration.completion === 'blocked' ? '结论尚未通过复核，未检查范围不能视为通过。' : '本次仅完成部分检查，请结合未覆盖范围阅读。' }}</p>
    <ul><li v-for="item in collaboration.work_items" :key="item.key">{{ item.label }}：{{ statuses[item.status] || '待查' }}</li></ul>
    <details v-if="collaboration.coverage?.length"><summary>检查范围与局限</summary><article v-for="item in collaboration.coverage" :key="item.label"><strong>{{ item.label }}</strong><p>{{ item.checked_dimensions.join('、') || '尚无完整检查回执' }}</p><ul><li v-for="omission in item.omissions" :key="omission">{{ omission }}</li></ul></article></details>
    <p v-if="collaboration.unread_chapters?.length">以下章节尚未回读：{{ collaboration.unread_chapters.join('、') }}。不代表已经排除影响。</p>
    <p v-if="collaboration.coverage_basis">{{ collaboration.coverage_basis }}</p>
    <details v-if="collaboration.reading_nodes?.length"><summary>逐章冻结的读者认知</summary>
      <article v-for="node in collaboration.reading_nodes" :key="node.draft_id"><h4>读完第 {{ node.chapter_index }} 章</h4>
        <template v-for="[key, label] in [['known', '已知'], ['guesses', '猜测'], ['newly_revealed', '新揭示']]" :key="key"><strong>{{ label }}</strong><ul><li v-for="(belief, index) in node.beliefs[key]" :key="index">{{ belief.belief }}<blockquote>{{ belief.excerpt }}</blockquote><p>{{ belief.interpretation }}</p></li></ul></template>
        <p>未解问题：{{ node.beliefs.unanswered.join('；') }}</p>
      </article>
    </details>
    <p v-if="collaboration.remaining_work?.length">待查：{{ collaboration.remaining_work.join('、') }}</p>
    <button v-for="result in collaboration.domain_results" :key="result.id" type="button" class="btn btn-sm" @click="$emit('locate', result)">{{ result.type === 'world_stress_report' ? '查看压力测试情境与作者决定' : '在原工作区查看与处理' }}</button>
  </section>
</template>

<script setup>
import { computed } from "vue"
const props = defineProps({ collaboration: { type: Object, required: true } })
defineEmits(["locate"])
const phases = { preparing: "准备资料", investigating: "分别核对", domain_review: "复核调查线索", summarizing: "整理结论", reviewing: "核对结论", completed: "查证结束" }
const statuses = { pending: "待查", running: "核对中", succeeded: "已完成", failed: "未完成", blocked: "等待前项", cancelled: "已停止" }
const phase = computed(() => phases[props.collaboration.phase] || "准备资料")
</script>

<style scoped>
.team-progress{padding:12px;border:1px solid var(--border);border-radius:8px;line-height:1.7;overflow-wrap:anywhere}
.team-progress p{margin:6px 0}.team-progress ul{padding-left:20px}.team-progress button{min-height:44px;white-space:normal}
</style>
