<script setup>
import { computed } from "vue"
import { displayStateBadgeClass } from "../../../../shared/assetDisplayState.js"
import { getBulkSelection, toggleBulkSelection } from "../logic/worldBulkSelection.js"

const props = defineProps({
  cards: { type: Array, default: () => [] },
  metaFor: { type: Function, required: true },
  // 关系分组视角：行选择与关系标签（默认关闭，维持普通资料浏览行为）。
  selectable: { type: Boolean, default: false },
  selectionScope: { type: String, default: "" },
  selectionLimit: { type: Number, default: 0 },
  relationLabelFor: { type: Function, default: null },
  memberMode: { type: String, default: "" }, // "group" | "unlinked"
})
const emit = defineEmits(["open", "create-task", "toggle-favorite", "add-to-topic", "add-one", "remove-one", "edit-relation"])

function isSelected(card) {
  if (!props.selectable || !props.selectionScope) return false
  return getBulkSelection(props.selectionScope).has(String(card.id))
}

function toggleSelected(card, event) {
  if (!props.selectable || !props.selectionScope) return
  toggleBulkSelection(props.selectionScope, card.id, event.target.checked)
}

const atLimit = computed(() => (
  props.selectionLimit > 0 && props.selectionScope
    ? getBulkSelection(props.selectionScope).size >= props.selectionLimit
    : false
))

function relationLabel(ref) {
  return props.relationLabelFor ? props.relationLabelFor(ref) : String(ref?.relation?.relation_type || "")
}
</script>

<template>
  <div class="world-bible-page-card-grid world-card-grid">
    <article v-for="card in cards" :key="card.key" class="world-bible-page-card world-card" :class="`world-card--${card.kind}`" :data-world-card-kind="card.kind" :style="{ '--world-bible-type-color': metaFor(card).color }">
      <div class="world-bible-page-card__band"></div>
      <div class="world-bible-page-card__head">
        <label v-if="selectable" class="selection-checkbox world-relation-member__check">
          <input
            type="checkbox"
            data-action="relation-member-toggle"
            :data-id="card.id"
            :checked="isSelected(card)"
            :disabled="!isSelected(card) && atLimit"
            @click.stop
            @change="toggleSelected(card, $event)"
          >
          <span class="sr-only">选择成员 {{ card.title }}</span>
        </label>
        <div class="world-bible-page-card__icon">{{ metaFor(card).symbol }}</div>
        <div class="world-bible-page-card__title">
          <h3>{{ card.title }}</h3>
          <div class="world-bible-page-card__meta">
            <span>{{ metaFor(card).label }}</span>
            <span v-if="card.isFavorite" class="world-library-cards__star" aria-label="已收藏">★</span>
            <span class="badge" :class="displayStateBadgeClass(card.state)">{{ card.stateLabel }}</span>
          </div>
        </div>
      </div>
      <p class="world-bible-page-card__summary">{{ card.summary || '还没有摘要，可以打开后补充。' }}</p>
      <div v-if="(card.relationRefs || []).length && relationLabelFor" class="world-relation-member__refs" aria-label="本分组中的关系">
        <button
          v-for="ref in card.relationRefs"
          :key="ref.relation.id"
          type="button"
          class="badge world-relation-member__ref"
          data-action="relation-member-edit-relation"
          :data-relation-id="ref.relation.id"
          :title="`编辑关系：${relationLabel(ref)}`"
          @click.stop="emit('edit-relation', ref)"
        >{{ relationLabel(ref) }}</button>
      </div>
      <div class="world-bible-page-card__footer">
        <span>{{ card.kind === 'entity' ? '人物或具体设定' : '资料页' }}</span>
        <span v-if="card.draftId">已保留未发布修改</span>
      </div>
      <div class="world-bible-page-card__actions">
        <button v-if="memberMode === 'unlinked'" class="btn btn-sm btn-ghost" type="button" data-action="relation-member-add-one" @click="emit('add-one', card)">加入本分组</button>
        <button v-if="memberMode === 'group' && card.relationRefs.length" class="btn btn-sm btn-ghost" type="button" data-action="relation-member-remove-one" @click="emit('remove-one', card)">移出分组</button>
        <button class="btn btn-sm btn-ghost" type="button" data-action="world-card-create-task" @click="emit('create-task', card)">添加到计划中的任务</button>
        <button class="btn btn-sm btn-ghost" type="button" :data-action="card.isFavorite ? 'world-card-unfavorite' : 'world-card-favorite'" :aria-pressed="card.isFavorite ? 'true' : 'false'" @click="emit('toggle-favorite', card)">{{ card.isFavorite ? '★ 已收藏' : '☆ 收藏' }}</button>
        <button class="btn btn-sm btn-ghost" type="button" data-action="world-card-add-topic" @click="emit('add-to-topic', card)">加入主题</button>
        <button class="btn btn-sm btn-primary" type="button" data-action="open-world-card" @click="emit('open', card)">{{ card.state === 'working' ? '继续编辑' : '打开' }}</button>
      </div>
    </article>
  </div>
</template>

<style scoped>
.world-library-cards__star { color: var(--accent); }
.world-relation-member__check { display: grid; place-items: center; }
.world-relation-member__refs { display: flex; flex-wrap: wrap; gap: 6px; }
.world-relation-member__ref { border: 1px solid var(--border); background: var(--bg-panel); color: var(--text-secondary); cursor: pointer; }
.world-relation-member__ref:hover { border-color: var(--accent); color: var(--text-primary); }
.world-relation-member__ref:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }
@media (max-width: 760px) {
  .world-bible-page-card__actions .btn { min-height: 44px; }
}
</style>
