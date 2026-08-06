<!--
  WorldReviewFilterChips — 已激活筛选 chips（vanilla _renderReviewFilterChips
  2904-2920 的 Vue 化）；点击移除该筛选（navigate 写 query）。
-->
<template>
  <div v-if="chips.length" class="review-filter-chips">
    <button
      v-for="chip in chips"
      :key="chip.key"
      class="review-filter-chip"
      data-action="remove-review-filter"
      :data-filter-kind="kind"
      :data-filter-key="chip.key"
      @click="removeReviewFilter(kind, chip.key, filters)"
    >{{ chip.label }}：{{ chip.display }} ×</button>
  </div>
</template>

<script setup>
import { computed } from "vue"
import { removeReviewFilter } from "../logic/useWorldReview.js"

const props = defineProps({
  kind: { type: String, required: true }, // "alias" | "relation"
  filters: { type: Object, default: () => ({}) },
})

const LABELS = {
  q: "搜索", relation_type: "关系类型", source: "来源", workflow_id: "处理批次",
  scene_index: "场景", source_chapter_index: "章节", confidence_min: "最低置信度",
  confidence_max: "最高置信度", strength_min: "最低强度", strength_max: "最高强度",
  has_quote: "引用", type_kind: "类型范围", multi_alias_only: "同对象多别名",
  multi_type_only: "同对象对多类型",
}

const chips = computed(() => (
  Object.entries(props.filters)
    .filter(([key, value]) => !["skip", "limit"].includes(key) && value !== "" && value != null && value !== false)
    .map(([key, value]) => ({
      key,
      label: LABELS[key] || key,
      display: key === "has_quote" ? (String(value) === "false" ? "缺少" : "有") : value,
    }))
))
</script>
