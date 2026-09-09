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
        <span>{{ typeLabel || "未分类" }}</span>
      </div>
      <span class="candidate-action-badge candidate-action-badge--alias_of_existing">{{ badgeLabel }}</span>
    </div>
    <details class="world-candidate-alias-item__evidence"><summary>查看来源依据</summary>
      <WorldInlineEvidence :pairs="evidencePairs" />
    </details>
    <div class="row-actions">
      <button v-if="candidateTargetId(candidate) && candidateAction(candidate) === 'alias_of_existing'" type="button" class="btn btn-sm btn-primary" @click.stop="showResolveAliasForm(id)">作为“{{ candidateTargetName(candidate) || '已有对象' }}”的别名</button>
      <button type="button" class="btn btn-sm world-review-queue-action" data-action="prepare-candidate-review" :data-id="id" @click.stop="emit('select', id, $event)">查看并决定</button>
    </div>
  </article>
</template>

<script setup>
import { computed } from "vue"
import { candidateAction, candidateMeta, candidateTargetId, candidateTargetName, entityId } from "../logic/worldEntityHelpers.js"
import { inlineEvidencePairs } from "../logic/useWorldReview.js"
import { showResolveAliasForm } from "../logic/worldEntityOps.js"
import WorldInlineEvidence from "./WorldInlineEvidence.vue"
import WorldSelectionInput from "./WorldSelectionInput.vue"

const props = defineProps({
  candidate: { type: Object, required: true },
  badgeLabel: { type: String, required: true },
  typeLabel: { type: String, default: "" },
  active: { type: Boolean, default: false },
})
const emit = defineEmits(["select"])

const id = computed(() => entityId(props.candidate))
const evidencePairs = computed(() => inlineEvidencePairs(candidateMeta(props.candidate)))
</script>
