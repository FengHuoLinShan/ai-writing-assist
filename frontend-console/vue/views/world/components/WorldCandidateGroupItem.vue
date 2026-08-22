<!--
  WorldCandidateGroupItem — 分组内候选条目（vanilla _renderCandidateGroupItem
  1784-1802 的 Vue 化）。
-->
<template>
  <article class="world-candidate-alias-item" :class="{ 'is-active': active }" :data-id="id" tabindex="0" @click="emit('select', id, $event)" @keydown.enter.self="emit('select', id, $event)" @keydown.space.prevent.self="emit('select', id, $event)">
    <div class="world-candidate-alias-item__identity">
      <WorldSelectionInput mode="one" scope="world-candidates" :id="id" :label="`选择 ${candidate.name || '待处理对象'}`" />
      <div>
        <strong>{{ candidate.name || "未命名候选" }}</strong>
        <span>{{ candidate.entity_type || "-" }}</span>
      </div>
      <span class="candidate-action-badge candidate-action-badge--alias_of_existing">{{ badgeLabel }}</span>
    </div>
    <div class="world-candidate-alias-item__evidence">
      <WorldInlineEvidence :pairs="evidencePairs" />
    </div>
    <div class="row-actions">
      <WorldCandidateActions :candidate="candidate" :action-options="actionOptions" />
    </div>
  </article>
</template>

<script setup>
import { computed } from "vue"
import { candidateMeta, entityId } from "../logic/worldEntityHelpers.js"
import { inlineEvidencePairs } from "../logic/useWorldReview.js"
import WorldCandidateActions from "./WorldCandidateActions.vue"
import WorldInlineEvidence from "./WorldInlineEvidence.vue"
import WorldSelectionInput from "./WorldSelectionInput.vue"

const props = defineProps({
  candidate: { type: Object, required: true },
  badgeLabel: { type: String, required: true },
  actionOptions: { type: Object, default: () => ({}) },
  active: { type: Boolean, default: false },
})
const emit = defineEmits(["select"])

const id = computed(() => entityId(props.candidate))
const evidencePairs = computed(() => inlineEvidencePairs(candidateMeta(props.candidate)))
</script>
