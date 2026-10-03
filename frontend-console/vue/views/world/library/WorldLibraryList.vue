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
  <ul class="world-library-list" aria-label="资料列表">
    <li v-for="card in cards" :key="card.key" class="world-library-list__row" :class="{ 'world-library-list__row--selectable': selectable }" :data-world-card-kind="card.kind">
      <div v-if="selectable" class="world-library-list__select">
        <label v-if="selectable" class="selection-checkbox">
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
      </div>
      <!-- 主行是 button；关系标签是独立交互元素，平铺在外避免按钮嵌套（无效 HTML）。 -->
      <div class="world-library-list__mainwrap">
        <button type="button" class="world-library-list__main" data-action="open-world-card" @click="emit('open', card)">
          <span class="world-library-list__symbol" aria-hidden="true">{{ metaFor(card).symbol }}</span>
          <span class="world-library-list__copy">
            <strong>{{ card.title }}</strong>
            <small>{{ metaFor(card).label }} · {{ card.summary || '还没有摘要' }}</small>
          </span>
          <span class="world-library-list__badges">
            <span v-if="card.isFavorite" class="world-library-list__star" aria-label="已收藏">★</span>
            <span class="badge" :class="displayStateBadgeClass(card.state)">{{ card.stateLabel }}</span>
          </span>
        </button>
        <div v-if="(card.relationRefs || []).length && relationLabelFor" class="world-relation-member__refs">
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
      </div>
      <div class="world-library-list__actions">
        <button v-if="memberMode === 'unlinked'" class="btn btn-sm btn-ghost" type="button" data-action="relation-member-add-one" @click="emit('add-one', card)">加入本分组</button>
        <button v-if="memberMode === 'group' && (card.relationRefs || []).length" class="btn btn-sm btn-ghost" type="button" data-action="relation-member-remove-one" @click="emit('remove-one', card)">移出分组</button>
        <button
          class="btn btn-sm btn-ghost"
          type="button"
          :data-action="card.isFavorite ? 'world-card-unfavorite' : 'world-card-favorite'"
          :aria-pressed="card.isFavorite ? 'true' : 'false'"
          :aria-label="card.isFavorite ? `取消收藏 ${card.title}` : `收藏 ${card.title}`"
          @click="emit('toggle-favorite', card)"
        >{{ card.isFavorite ? '★ 已收藏' : '☆ 收藏' }}</button>
        <button class="btn btn-sm btn-ghost" type="button" data-action="world-card-add-topic" @click="emit('add-to-topic', card)">加入主题</button>
        <button class="btn btn-sm btn-ghost" type="button" data-action="world-card-create-task" @click="emit('create-task', card)">添加任务</button>
      </div>
    </li>
  </ul>
</template>

<style scoped>
.world-library-list { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
.world-library-list__row { display: grid; grid-template-columns: minmax(0, 1fr); gap: 6px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-panel); padding: 8px; }
.world-library-list__mainwrap { display: grid; min-width: 0; gap: 2px; }
.world-library-list__main { display: grid; min-width: 0; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 12px; border: 0; padding: 6px; color: inherit; background: transparent; text-align: left; cursor: pointer; }
.world-library-list__main:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.world-library-list__symbol { display: grid; width: 36px; height: 36px; place-items: center; border-radius: var(--radius-sm); background: var(--bg-hover); }
.world-library-list__copy { min-width: 0; display: grid; gap: 4px; }
.world-library-list__copy strong, .world-library-list__copy small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.world-library-list__copy small { color: var(--text-muted); }
.world-library-list__badges { display: inline-flex; align-items: center; gap: 6px; }
.world-library-list__star { color: var(--accent); }
.world-library-list__actions { display: flex; flex-wrap: wrap; gap: 6px; padding: 0 6px 2px; }
.world-relation-member__refs { display: flex; flex-wrap: wrap; gap: 6px; padding: 0 6px 2px 54px; }
.world-relation-member__ref { border: 1px solid var(--border); background: var(--bg-panel); color: var(--text-secondary); cursor: pointer; }
.world-relation-member__ref:hover { border-color: var(--accent); color: var(--text-primary); }
.world-relation-member__ref:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }
@media (min-width: 1080px) {
  /* 普通浏览：主行弹性、操作列右对齐（标题 nowrap 时 1fr 收缩出省略号，不挤压操作列）。 */
  .world-library-list__row { grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 8px; }
  /* 关系成员模式：勾选列 + 弹性主行 + 操作列（三列模板由修饰类分支）。 */
  .world-library-list__row--selectable { grid-template-columns: auto minmax(0, 1fr) auto; }
  .world-library-list__actions { flex-direction: column; align-items: stretch; padding: 0; }
}
@media (max-width: 760px) {
  .world-library-list__row > .btn, .world-library-list__actions .btn { min-height: 44px; }
  .world-library-list__main { min-height: 52px; grid-template-columns: auto minmax(0, 1fr); }
  .world-library-list__main .world-library-list__badges { grid-column: 2; width: fit-content; }
}
</style>
