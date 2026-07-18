<!--
  WorldCandidateActions — 待处理候选的行内动作（vanilla _candidateActionsHtml
  1710-1736 的 Vue 化）。
-->
<template>
  <button v-if="visibility.canAccept" class="btn btn-sm btn-primary" data-action="accept-candidate" :data-id="id" @click="acceptCandidate(id)">采用</button>
  <button class="btn btn-sm" data-action="edit-entity" :data-id="id" @click="editEntity(id)">编辑后采用</button>
  <button v-if="visibility.canAlias" class="btn btn-sm btn-primary" data-action="resolve-candidate-alias" :data-id="id" :data-target-name="targetName" @click="showResolveAliasForm(id)">设为别名</button>
  <button v-if="visibility.canMerge" class="btn btn-sm" data-action="merge-entity" :data-id="id" :data-target-name="targetName" @click="showMergeForm(id)">合并到</button>
  <button class="btn btn-sm" :class="{ 'btn-danger': !visibility.isTemporary }" data-action="ignore-candidate" :data-id="id" @click="ignoreCandidate(id)">{{ visibility.isTemporary ? "设为临时" : "忽略" }}</button>
</template>

<script setup>
import { computed } from "vue"
import { candidateTargetName, entityId } from "../logic/worldEntityHelpers.js"
import { acceptCandidate, editEntity, ignoreCandidate, showMergeForm, showResolveAliasForm } from "../logic/worldEntityOps.js"
import { candidateActionVisibility } from "../logic/useWorldReview.js"

const props = defineProps({
  candidate: { type: Object, required: true },
  actionOptions: { type: Object, default: () => ({}) }, // { allowAlias?, allowMerge? }
})

const id = computed(() => entityId(props.candidate))
const targetName = computed(() => candidateTargetName(props.candidate))
const visibility = computed(() => candidateActionVisibility(props.candidate, props.actionOptions))
</script>
