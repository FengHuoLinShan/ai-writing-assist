<script setup>
import { displayStateBadgeClass } from "../../../../shared/assetDisplayState.js"

defineProps({
  cards: { type: Array, default: () => [] },
  metaFor: { type: Function, required: true },
})
const emit = defineEmits(["open", "create-task", "toggle-favorite", "add-to-topic"])
</script>

<template>
  <ul class="world-library-list" aria-label="资料列表">
    <li v-for="card in cards" :key="card.key" class="world-library-list__row" :data-world-card-kind="card.kind">
      <button type="button" class="world-library-list__main" data-action="open-world-card" @click="emit('open', card)">
        <span class="world-library-list__symbol" aria-hidden="true">{{ metaFor(card).symbol }}</span>
        <span class="world-library-list__copy"><strong>{{ card.title }}</strong><small>{{ metaFor(card).label }} · {{ card.summary || '还没有摘要' }}</small></span>
        <span class="world-library-list__badges">
          <span v-if="card.isFavorite" class="world-library-list__star" aria-label="已收藏">★</span>
          <span class="badge" :class="displayStateBadgeClass(card.state)">{{ card.stateLabel }}</span>
        </span>
      </button>
      <div class="world-library-list__actions">
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
.world-library-list__main { display: grid; min-width: 0; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 12px; border: 0; padding: 6px; color: inherit; background: transparent; text-align: left; cursor: pointer; }
.world-library-list__main:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.world-library-list__symbol { display: grid; width: 36px; height: 36px; place-items: center; border-radius: var(--radius-sm); background: var(--bg-hover); }
.world-library-list__copy { min-width: 0; display: grid; gap: 4px; }
.world-library-list__copy strong, .world-library-list__copy small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.world-library-list__copy small { color: var(--text-muted); }
.world-library-list__badges { display: inline-flex; align-items: center; gap: 6px; }
.world-library-list__star { color: var(--accent); }
.world-library-list__actions { display: flex; flex-wrap: wrap; gap: 6px; padding: 0 6px 2px; }
@media (min-width: 1080px) {
  .world-library-list__row { grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 8px; }
  .world-library-list__actions { flex-direction: column; align-items: stretch; padding: 0; }
}
@media (max-width: 760px) {
  .world-library-list__row > .btn, .world-library-list__actions .btn { min-height: 44px; }
  .world-library-list__main { min-height: 52px; grid-template-columns: auto minmax(0, 1fr); }
  .world-library-list__main .world-library-list__badges { grid-column: 2; width: fit-content; }
}
</style>
