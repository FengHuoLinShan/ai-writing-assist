<template>
  <details class="assistant-review-result">
    <summary>查看审查结果与实际覆盖</summary>
    <p>{{ status }}</p>
    <p v-if="result.progress?.packets_planned != null">已检查 {{ result.progress.packets_completed }} / {{ result.progress.packets_planned }} 组资料。</p>
    <section v-for="group in checks" :key="group.chapter">
      <strong>第 {{ group.chapter }} 章</strong>
      <ul><li v-for="check in group.items" :key="check.label">{{ check.label }}：{{ check.status }}</li></ul>
    </section>
    <p v-for="world in Object.values(result.coverage?.world_constraints || {})" :key="world.chapter_index">第 {{ world.chapter_index }} 章{{ world.checked ? '已检查所列世界约束' : '世界约束未完整检查' }}，本次读取 {{ world.sources?.length || 0 }} 项世界资料；此模式不签署人物知识边界。</p>
    <ul v-if="omissions.length"><li v-for="(item, index) in omissions" :key="index">{{ item }}</li></ul>
    <article v-for="(finding, index) in result.findings || []" :key="finding.finding_id || index">
      <p>{{ finding.message || finding.title }}</p>
      <blockquote v-if="finding.location?.excerpt || finding.excerpt">{{ finding.location?.excerpt || finding.excerpt }}</blockquote>
      <button v-if="finding.location?.draft_id" type="button" class="btn btn-sm" @click="locateAssistantSource({ type: 'writing_draft', id: finding.location.draft_id, ...finding.location })">定位这处正文</button>
    </article>
  </details>
</template>
<script setup>
import { computed } from "vue"
import { locateAssistantSource } from "../shared/assistantNavigation.js"
const props = defineProps({ result: { type: Object, required: true } })
const status = computed(() => ({ completed: "审查已完成，请结合实际覆盖判断。", stale: "依据已变化，需要重新检查。", incomplete: "审查未完成，不能作为通过结论。", failed: "审查失败，已保留可用回执。" }[props.result.status] || "本次审查回执"))
const labels = { scene_contract: "场景约束", timeline_location: "时间与地点", identity_relation: "身份与关系", ability_world_rule: "能力与世界规则", knowledge_boundary: "人物知识边界" }
const checks = computed(() => Object.entries(props.result.coverage?.semantic_checks || {}).map(([id, item], index) => ({
  chapter: props.result.coverage.target_chapters?.[props.result.coverage.target_draft_ids?.indexOf(id)] || index + 1,
  items: Object.entries(labels).map(([key, label]) => ({ label, status: { checked: "已检查", not_applicable: "不适用", not_checked: "未检查" }[item[key]] || "未检查" })),
})))
const omissions = computed(() => [...(props.result.not_checked || []), ...(props.result.omissions || [])].map(item => typeof item === "string" ? item : item.message || item.reason || "有资料未覆盖，请在复核工作台查看。"))
</script>
