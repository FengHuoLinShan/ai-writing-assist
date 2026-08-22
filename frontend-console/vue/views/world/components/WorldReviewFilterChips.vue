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
import { detailTypeLabel, kindLabel } from "../logic/worldTypeCatalog.js"

const props = defineProps({
  kind: { type: String, required: true }, // "candidate" | "alias" | "relation"
  filters: { type: Object, default: () => ({}) },
  reviewTypeCatalog: { type: Object, default: () => ({}) },
})

const LABELS = {
  q: "搜索", relation_type: "详细类型", relation_kind: "关系分类", alias_kind: "别名分类", source: "来源", workflow_id: "处理批次",
  scene_index: "场景", source_chapter_index: "章节", confidence_min: "最低置信度",
  confidence_max: "最高置信度", strength_min: "最低强度", strength_max: "最高强度",
  has_quote: "引用", type_kind: "类型范围", multi_alias_only: "同对象多别名",
  multi_type_only: "同对象对多类型",
  suggested_action: "处理任务", entity_type: "对象类型",
  has_reverse_candidates: "反向候选", has_canonical_relation: "正式关系",
}

const DISPLAY_VALUES = {
  create_new: "可作为新对象",
  alias_of_existing: "建议设为别名",
  alias: "建议设为别名",
  link_to_existing: "建议设为别名",
  merge_with_existing: "建议合并",
  needs_user_decision: "需我判断",
  custom: "自定义",
  recommended: "推荐类型",
}

function chipDisplay(key, value) {
  if (key === "relation_kind") return kindLabel(props.reviewTypeCatalog, "relation", value)
  if (key === "alias_kind") return kindLabel(props.reviewTypeCatalog, "alias", value)
  if (key === "relation_type") return detailTypeLabel(props.reviewTypeCatalog, "relation", value)
  if (key === "has_quote") return String(value) === "false" ? "缺少" : "有"
  if (["multi_alias_only", "multi_type_only", "has_reverse_candidates", "has_canonical_relation"].includes(key)) {
    return String(value) === "true" ? "是" : "否"
  }
  return DISPLAY_VALUES[value] || value
}

const chips = computed(() => (
  Object.entries(props.filters)
    .filter(([key, value]) => !["skip", "limit"].includes(key) && value !== "" && value != null && value !== false)
    .map(([key, value]) => ({
      key,
      label: LABELS[key] || key,
      display: chipDisplay(key, value),
    }))
))
</script>
